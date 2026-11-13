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
from src.domain.enums import Intent, OrderType
from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_container, clean_driver_name, clean_phone, clean_plate, validate_iso6346
from src.infrastructure.ai_service_client import AIExtractResult, AIServiceClient
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
    def should_trigger_ai(
        cls,
        lines: list[ExtractedContainerLine],
        intent: Optional[Intent] = None,
    ) -> bool:
        """Kiểm tra xem kết quả từ Rule-based Parser có thực sự cần chuyển tiếp sang AI Fallback hay không.

        Nguyên tắc tiết kiệm token (Local/Rule-first):
        - Bảo toàn kết quả Rule-based nếu đã phát hiện lỗi cứng ISO 6346 (`check_digit_valid is False`)
          hoặc mâu thuẫn gắn kết Xe - Container (T34).
        - Định dạng chuẩn (`F1`, `F2`, `F3`) đã bóc tách được xe/container -> giữ Fast-Path Regex.
        - Tin Hủy (`CANCEL_REQUEST`): không cần gọi LLM.
        - Tin Bổ sung (`SUPPLEMENT`) / Đổi xe (`UPDATE_REQUEST`): nếu Regex đã bóc tách được
          ít nhất 1 thực thể đích/thay đổi (cont, biển số, chì, tài xế, SĐT, giờ hẹn) -> giữ Rule-based.
        - Tin Báo xe tự do (`PARSE_TRUCK_INFO`): chỉ gọi AI khi không tách được gì, confidence thấp
          hơn ngưỡng, hoặc thiếu cả cặp `truck_plate` + `container_no` / chỉ tách được 1 nửa trên tin phức tạp.
        """
        has_direct = bool(settings.AI_DIRECT_GEMINI_FALLBACK and settings.AI_API_KEY)
        if not settings.AI_ENABLED or (not settings.AI_SERVICE_URL and not has_direct):
            return False
        if intent == Intent.CANCEL_REQUEST:
            return False
        if not lines:
            return True

        # Bảo toàn cảnh báo nghiệp vụ cứng (lỗi ISO 6346 hoặc mâu thuẫn nhiều xe/cont T34)
        if any(ln.has_conflicting_mapping or ln.check_digit_valid is False for ln in lines):
            return False

        # Fast-Path Regex cho định dạng chuẩn F1, F2, F3
        if any(ln.source_format in ("F1", "F2", "F3") for ln in lines):
            return False

        # Tin bổ sung / đổi xe: nếu Regex đã tách được thực thể liên quan -> 0 gọi AI
        if intent in (Intent.SUPPLEMENT, Intent.UPDATE_REQUEST):
            has_useful = any(
                ln.container_no
                or ln.seal_no
                or ln.truck_plate
                or ln.driver_name
                or ln.driver_phone
                or ln.eta_time
                or ln.container_size
                for ln in lines
            )
            return not has_useful

        # Với định dạng tự do (`tu_do`): chỉ bỏ qua AI khi Regex đã tách đủ các trường cốt lõi;
        # nếu thiếu bất kỳ trường quan trọng nào hoặc có mốc giờ chưa bóc được -> tự động gọi LLM.
        threshold = settings.AI_FALLBACK_CONFIDENCE_THRESHOLD
        time_hint_re = re.compile(r"\b\d{1,2}\s*(?:h\d{0,2}|giờ|:\d{2})\b", re.IGNORECASE)
        for ln in lines:
            if ln.confidence < threshold:
                return True
            if not ln.truck_plate or not ln.container_no:
                return True
            if not ln.driver_name or not ln.driver_phone or not ln.order_type:
                return True
            if not ln.eta_time and time_hint_re.search(ln.line_text or ""):
                return True

        return False

    @classmethod
    def _convert_service_items(
        cls,
        raw_text: str,
        ai_res: AIExtractResult,
        reference_time: Optional[datetime] = None,
    ) -> list[ExtractedContainerLine]:
        """Chuyển danh sách thực thể từ `ai-service` về `ExtractedContainerLine` đã chuẩn hóa."""
        ref_date = (reference_time or datetime.now()).strftime("%Y-%m-%d")
        lines: list[ExtractedContainerLine] = []
        for idx, item in enumerate(ai_res.items, start=1):
            raw_plate = item.get("plate_number") or item.get("plate")
            norm_plate = clean_plate(raw_plate)
            raw_trailer = item.get("trailer_number")
            norm_trailer = clean_plate(raw_trailer) if raw_trailer else None
            cont_no = clean_container(item.get("container_no") or item.get("cont_no"))
            phone = clean_phone(item.get("driver_phone")) if item.get("driver_phone") else None

            raw_order = (str(item.get("order_type") or "").strip().upper())
            if raw_order in ("LOAD", "DONG", "XUAT"):
                order_val: Optional[str] = OrderType.LOAD.value
            elif raw_order in ("RETURN", "TRA", "NHAP"):
                order_val = OrderType.RETURN.value
            else:
                order_val = None

            check_ok: Optional[bool] = None
            warnings: list[str] = []
            if cont_no:
                check_ok = validate_iso6346(cont_no)
                if check_ok is False:
                    warnings.append(f"ISO6346_CHECK_DIGIT_MISMATCH:{cont_no}")

            lines.append(
                ExtractedContainerLine(
                    line_no=idx,
                    line_text=str(item.get("evidence") or raw_text),
                    source_format="tu_do",
                    plan_date=item.get("plan_date") or ref_date,
                    truck_plate=norm_plate,
                    raw_truck_plate=raw_plate,
                    trailer_plate=norm_trailer,
                    driver_name=clean_driver_name(item.get("driver_name")),
                    driver_phone=phone,
                    container_no=cont_no,
                    container_size=item.get("container_size") or item.get("cont_size"),
                    seal_no=item.get("seal_no"),
                    booking_no=item.get("booking_no"),
                    order_type=order_val,
                    warehouse_hint=item.get("warehouse_name") or item.get("location_raw"),
                    customer_hint=item.get("customer_name") or item.get("customer_raw"),
                    eta_time=item.get("eta"),
                    evidence=item.get("evidence"),
                    confidence=float(item.get("confidence") or 0.88),
                    check_digit_valid=check_ok,
                    warnings=warnings,
                )
            )
        return lines

    @classmethod
    def extract_with_ai_context(
        cls,
        raw_text: str,
        reference_time: Optional[datetime] = None,
        sender_id: Optional[str] = None,
        group_id: Optional[str] = None,
        carrier_id: Optional[int] = None,
        quote_message: Optional[str] = None,
        active_plans: Optional[list[dict[str, Any]]] = None,
        context_messages: Optional[list[str]] = None,
        message_type: str = "text",
    ) -> tuple[Optional[list[ExtractedContainerLine]], Optional[AIExtractResult]]:
        """Bóc tách qua `ai-service` kèm ngữ cảnh, tự fallback provider trực tiếp nếu microservice bận."""
        if not settings.AI_ENABLED:
            return None, None

        service_res = AIServiceClient.extract(
            message_text=raw_text,
            sender_id=sender_id,
            group_id=group_id,
            carrier_id=carrier_id,
            quote_message=quote_message,
            active_plans=active_plans,
            context_messages=context_messages,
            message_type=message_type,
        )
        if service_res is not None:
            converted = cls._convert_service_items(raw_text, service_res, reference_time=reference_time)
            return converted, service_res

        if not settings.AI_DIRECT_GEMINI_FALLBACK:
            return None, None

        direct_lines = cls.extract_with_ai(raw_text=raw_text, reference_time=reference_time)
        return direct_lines, None

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
        if not settings.AI_ENABLED or not settings.AI_API_KEY or not settings.AI_DIRECT_GEMINI_FALLBACK:
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
