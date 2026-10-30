"""Module Tích Hợp AI Fallback Đa Nhà Cung Cấp (Configurable Multi-Provider AI Fallback).

Chỉ được kích hoạt khi:
1. Tin nhắn đã vượt qua bộ lọc hội thoại xã giao (`IntentClassifier` xác nhận là tin báo xe).
2. Bộ bóc tách Rule-based (`TripParser`) không nhận diện được cấu trúc F1/F2/F3 và độ tin cậy
   thấp hơn ngưỡng `settings.AI_FALLBACK_CONFIDENCE_THRESHOLD`.
3. `settings.AI_ENABLED=True` và đã cấu hình `AI_API_KEY`.

Đặc biệt:
- Tự động che số điện thoại thành dạng `0931xxxx73` **trước khi gửi văn bản cho AI** để bảo mật,
  sau đó khôi phục lại số điện thoại thật (`0931142873`) khi lưu vào cơ sở dữ liệu nội bộ.
- Hỗ trợ trực tiếp cả **Google Gemini API (`AI_PROVIDER=gemini`)** lẫn **OpenAI-compatible API
  (`AI_PROVIDER=openai_compatible`)**, dễ dàng đổi qua `.env`.
"""

from datetime import datetime
import json
import re
from typing import Any, Optional
import urllib.request

from src.config.settings import settings
from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_container, clean_driver_name, clean_phone, clean_plate
from src.observability.logging import get_logger

logger = get_logger(__name__)


class AIFallbackExtractor:
    """Bộ bóc tách dự phòng bằng AI (Gemini / OpenAI / Ollama) với cơ chế che SĐT tự động."""

    _PHONE_FINDER = re.compile(r"\b((?:\+?84|0)\d{2,3})(\d{4})(\d{2,3})\b")

    @classmethod
    def mask_phones_for_ai(cls, raw_text: str) -> tuple[str, dict[str, str]]:
        """Che 4 số giữa của mọi số điện thoại thành `xxxx` trước khi gửi văn bản cho AI bên ngoài.

        Args:
            raw_text (str): Nội dung tin nhắn gốc chứa SĐT thật.

        Returns:
            tuple[str, dict[str, str]]: Cặp `(văn bản đã che SĐT, bảng ánh xạ khôi phục SĐT thật)`.
        """
        phone_map: dict[str, str] = {}

        def _replacer(match: re.Match[str]) -> str:
            full_raw = match.group(0)
            cleaned_real = clean_phone(full_raw) or full_raw
            masked_token = f"{match.group(1)}xxxx{match.group(3)}"
            phone_map[masked_token] = cleaned_real
            return masked_token

        masked_text = cls._PHONE_FINDER.sub(_replacer, raw_text)
        return masked_text, phone_map

    @classmethod
    def restore_real_phone(
        cls,
        extracted_phone: Optional[str],
        phone_map: dict[str, str],
    ) -> Optional[str]:
        """Khôi phục số điện thoại thật từ chuỗi SĐT đã che sau khi AI trả kết quả.

        Args:
            extracted_phone (Optional[str]): Số điện thoại do AI trích xuất (có thể chứa `xxxx`).
            phone_map (dict[str, str]): Bảng ánh xạ từ token `xxxx` về SĐT thật.

        Returns:
            Optional[str]: Số điện thoại thật 10 chữ số để lưu vào cơ sở dữ liệu.
        """
        if not extracted_phone:
            return None
        cleaned = str(extracted_phone).strip()
        if cleaned in phone_map:
            return phone_map[cleaned]
        for masked_key, real_val in phone_map.items():
            if masked_key.replace(" ", "") in cleaned.replace(" ", ""):
                return real_val
        return clean_phone(cleaned)

    @classmethod
    def should_trigger_ai(cls, lines: list[ExtractedContainerLine]) -> bool:
        """Kiểm tra xem kết quả từ Rule-based Parser có cần chuyển tiếp sang AI Fallback hay không.

        Chỉ kích hoạt khi `settings.AI_ENABLED=True` và bộ Rule-based (`TripParser`) không
        bóc tách được biển số xe và số container ở định dạng tự do (`tu_do`).
        Nếu Rule-based đã bóc tách được biển số hoặc số container (kể cả khi số cont bị sai
        Check Digit ISO 6346 hoặc dữ liệu mâu thuẫn T34), tuyệt đối giữ kết quả Rule-based
        để tiết kiệm chi phí và bảo toàn cảnh báo kiểm tra.

        Args:
            lines (list[ExtractedContainerLine]): Kết quả bóc tách từ `TripParser`.

        Returns:
            bool: True nếu cần gọi AI Fallback.
        """
        if not settings.AI_ENABLED or not settings.AI_API_KEY:
            return False
        if not lines:
            return True
        # Nếu đã khớp F1, F2, F3 hoặc đã bóc được cả biển số lẫn số cont thì không cần gọi AI
        if any(ln.source_format in ("F1", "F2", "F3") for ln in lines):
            return False
        if any(ln.truck_plate and (ln.container_no or ln.is_container_pending) for ln in lines):
            return False
        if any(ln.has_conflicting_mapping for ln in lines):
            return False
        # Chỉ gọi AI khi định dạng tự do bị thiếu thông tin cốt lõi (không bóc được biển số và số cont)
        return all(not ln.truck_plate and not ln.container_no for ln in lines)

    @classmethod
    def extract_with_ai(
        cls,
        raw_text: str,
        reference_time: Optional[datetime] = None,
    ) -> Optional[list[ExtractedContainerLine]]:
        """Gửi văn bản (đã che SĐT thành `xxxx`) tới AI Provider và chuyển kết quả về `ExtractedContainerLine`.

        Args:
            raw_text (str): Nội dung tin nhắn gốc.
            reference_time (Optional[datetime]): Thời gian gửi tin nhắn.

        Returns:
            Optional[list[ExtractedContainerLine]]: Danh sách dòng container do AI bóc tách (đã khôi phục SĐT thật),
                hoặc None nếu AI lỗi/timeout để hệ thống tự động giữ kết quả Rule-based.
        """
        if not settings.AI_ENABLED or not settings.AI_API_KEY:
            return None

        masked_text, phone_map = cls.mask_phones_for_ai(raw_text)
        ref_date = (reference_time or datetime.now()).strftime("%Y-%m-%d")

        system_prompt = (
            "Bạn là bộ trích xuất dữ liệu điều vận container của VSICO. "
            "Hãy trích xuất danh sách container từ tin nhắn tiếng Việt sang JSON chuẩn với khóa 'items', "
            "mỗi phần tử gồm: plan_date (YYYY-MM-DD), order_type ('dong'|'tra'|null), "
            "customer_raw, location_raw, plate, driver_name, driver_phone, cont_no, cont_size ('20'|'40'|'45'|null), "
            "seal_no, eta (HH:MM). Giữ nguyên chuỗi driver_phone như trong văn bản. Chỉ trả về JSON hợp lệ."
        )
        user_prompt = f"Ngày gửi tin: {ref_date}\nNội dung tin nhắn:\n{masked_text}"

        try:
            raw_json_str = cls._call_provider(system_prompt, user_prompt)
            if not raw_json_str:
                return None
            cleaned_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json_str.strip())
            parsed_data: dict[str, Any] = json.loads(cleaned_json)
            items = parsed_data.get("items") or []
            if not isinstance(items, list) or not items:
                return None

            results: list[ExtractedContainerLine] = []
            for idx, item in enumerate(items, start=1):
                real_phone = cls.restore_real_phone(item.get("driver_phone"), phone_map)
                raw_plate = item.get("plate")
                results.append(
                    ExtractedContainerLine(
                        line_no=idx,
                        line_text=raw_text,
                        source_format="tu_do",
                        plan_date=item.get("plan_date") or ref_date,
                        truck_plate=clean_plate(raw_plate),
                        raw_truck_plate=raw_plate,
                        driver_name=clean_driver_name(item.get("driver_name")),
                        driver_phone=real_phone,
                        container_no=clean_container(item.get("cont_no")),
                        container_size=item.get("cont_size"),
                        seal_no=item.get("seal_no"),
                        order_type=item.get("order_type"),
                        warehouse_hint=item.get("location_raw"),
                        customer_hint=item.get("customer_raw"),
                        eta_time=item.get("eta"),
                        confidence=0.90,
                    )
                )
            return results
        except Exception as exc:
            logger.warning("AI Fallback (%s) không khả dụng, giữ nguyên kết quả Rule-based: %s", settings.AI_MODEL_NAME, exc)
            return None

    @classmethod
    def _call_provider(cls, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Gọi HTTP API tới nhà cung cấp AI theo cấu hình `settings.AI_PROVIDER` (`gemini` hoặc `openai_compatible`)."""
        provider = settings.AI_PROVIDER.lower().strip()
        if provider == "gemini" or "generativelanguage.googleapis.com" in settings.AI_BASE_URL:
            return cls._call_gemini_native(system_prompt, user_prompt)
        return cls._call_openai_compatible(system_prompt, user_prompt)

    @classmethod
    def _call_gemini_native(cls, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Gọi trực tiếp Google Gemini REST API (`generateContent`), tự động xoay vòng model dự phòng nếu quá tải."""
        base_url = settings.AI_BASE_URL.rstrip("/")
        if base_url.endswith("/openai"):
            base_url = base_url[:-7]

        primary_model = settings.AI_MODEL_NAME.replace("models/", "").strip() or "gemini-3.5-flash"
        candidate_models = [primary_model]
        if "gemini-3.5-flash-lite" not in candidate_models:
            candidate_models.append("gemini-3.5-flash-lite")

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0,
            },
        }
        data_bytes = json.dumps(payload).encode("utf-8")

        last_err: Optional[Exception] = None
        for model_name in candidate_models:
            url = f"{base_url}/models/{model_name}:generateContent?key={settings.AI_API_KEY}"
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    return body["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as exc:
                last_err = exc
                continue

        if last_err:
            raise last_err
        return None

    @classmethod
    def _call_openai_compatible(cls, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Gọi API chuẩn OpenAI (`/chat/completions` - dùng cho OpenAI, DeepSeek, Groq, vLLM, Ollama)."""
        url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.AI_API_KEY}",
        }
        payload = {
            "model": settings.AI_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
