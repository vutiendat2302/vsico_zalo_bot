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

    _PHONE_FINDER = re.compile(r"(?<!\d)((?:\+?84|0)[35789]\d{1,2})(\d{4})(\d{2,3})(?!\d)")

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
        """Kiểm tra xem kết quả từ Rule/Local NLP Parser có thực sự cần gọi AI Fallback hay không.

        Nguyên tắc ưu tiên xử lý tại chỗ (Local-First, chỉ gọi LLM khi thực sự bế tắc hoặc mơ hồ):
        - Bỏ qua AI với tin xã giao (`IGNORE_CHAT`), hủy (`CANCEL_REQUEST`), duyệt/sửa của ĐHVT.
        - Bảo toàn cảnh báo nghiệp vụ cứng (lỗi ISO 6346 hoặc mâu thuẫn gắn kết Xe - Container T34).
        - Định dạng chuẩn (`F1`, `F2`, `F3`) đã bóc tách được xe/container -> giữ Fast-Path Regex.
        - Tin bổ sung / đổi xe / tra cứu / báo xe tự do có cấu trúc rõ (`confidence >= threshold`):
          nếu đã bóc tách được ít nhất 1 thực thể nghiệp vụ cốt lõi (xe, cont, SĐT, booking, chì, ETA)
          và không còn trường mơ hồ (`unresolved_fields`) hoặc mốc giờ bị bỏ sót -> xử lý hoàn toàn nội bộ.
        - Chỉ gọi Tier-3 LLM khi không bóc tách được thực thể nào, `confidence < threshold`,
          hoặc còn trường mơ hồ cần suy luận ngữ nghĩa.
        """
        has_direct = bool(settings.AI_DIRECT_GEMINI_FALLBACK and settings.AI_API_KEY)
        if not settings.AI_ENABLED or (not settings.AI_SERVICE_URL and not has_direct):
            return False
        if intent in (
            Intent.IGNORE_CHAT,
            Intent.CANCEL_REQUEST,
            Intent.APPROVE_OUTBOUND,
            Intent.EDIT_PENDING,
        ):
            return False
        if not lines:
            return True

        # Bảo toàn cảnh báo nghiệp vụ cứng (lỗi ISO 6346 hoặc mâu thuẫn nhiều xe/cont T34)
        if any(ln.has_conflicting_mapping or ln.check_digit_valid is False for ln in lines):
            return False

        # Đọc quyết định đánh giá từ Tầng 2 Local NLP (nếu Tầng 2 thấy còn tín hiệu dư cho trường thiếu -> lên Tầng 3 LLM)
        from src.parsing.local_nlp_extractor import evaluate_missing_field_signals

        for ln in lines:
            t2_decision = ln.field_evidences.get("tier2_nlp_decision")
            if not t2_decision:
                t2_decision, _ = evaluate_missing_field_signals(ln)
            if t2_decision == "ESCALATE_TIER3_LLM":
                return True

        # Fast-Path Regex cho định dạng chuẩn F1, F2, F3 (khi Tầng 2 không phát hiện tín hiệu dư bị bỏ sót)
        if any(ln.source_format in ("F1", "F2", "F3") for ln in lines):
            return False

        # Tin bổ sung / đổi xe: nếu Regex hoặc Local NLP đã tách được thực thể liên quan và không còn tín hiệu dư -> 0 gọi AI
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

        # Với định dạng tự do (`tu_do`): chỉ gọi LLM khi parsing thất bại, thiếu toàn bộ khóa định danh,
        # còn trường mơ hồ hoặc phát hiện mốc giờ thực sự chưa bóc được.
        # Lưu ý: KHÔNG khớp nhầm biển số dạng `15H`, `50H`, `29H` thành mốc giờ (time_hint_re).
        threshold = settings.AI_FALLBACK_CONFIDENCE_THRESHOLD
        time_hint_re = re.compile(
            r"(?:(?:[01]?\d|2[0-3])\s*:\s*[0-5]\d|"
            r"(?:[01]?\d|2[0-3])\s*(?:h|giờ)\s*[0-5]\d\b|"
            r"(?:lúc|luc|hẹn|hen|tới|toi|vào|vao|trước|truoc|sau|tầm|tam|khoảng|khoang)\s+(?:[01]?\d|2[0-3])\s*h\b)",
            re.IGNORECASE,
        )
        order_code_re = re.compile(r"\b(?:RO|LO)\d{3,6}\b", re.IGNORECASE)
        for ln in lines:
            if ln.unresolved_fields:
                return True
            t2_dec = ln.field_evidences.get("tier2_nlp_decision")
            has_primary_entity = bool(
                ln.truck_plate
                or ln.trailer_plate
                or ln.container_no
                or ln.driver_phone
                or ln.booking_no
                or ln.seal_no
                or ln.eta_time
                or (ln.driver_name and order_code_re.search(ln.line_text or ""))
            )
            if not ln.eta_time and time_hint_re.search(ln.line_text or ""):
                return True
            if t2_dec == "STOP_NO_SIGNAL" and (has_primary_entity or ln.driver_name):
                continue
            if not has_primary_entity:
                return True
            if ln.confidence < threshold:
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
            raw_trailer = item.get("trailer_number") or item.get("trailer_plate")
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
