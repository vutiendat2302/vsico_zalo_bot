"""Client nội bộ gọi AI & OCR Microservice (`ai-service`) từ Backend.

Tuân thủ bảo mật Zero-Trust:
- Luôn đính kèm header `X-Internal-Token` khớp `INTERNAL_SECRET`.
- Tự động che SĐT tài xế dạng `0903xxxx59` trước khi gửi văn bản ra ngoài và
  khôi phục SĐT thực sau khi nhận phản hồi.
- Tuyệt đối không log dữ liệu cá nhân thô và không làm sập tiến trình nếu `ai-service` tạm ngoại tuyến.
"""

import re
from dataclasses import dataclass
from typing import Any

import httpx

from src.config.settings import settings
from src.observability.logging import get_logger

logger = get_logger(__name__)

_VN_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]*\d){8,10}(?!\d)")


@dataclass
class AIExtractResult:
    """Kết quả bóc tách có cấu trúc nhận từ `ai-service` `/api/v1/extract`."""

    intent: str
    is_multi_vehicle: bool
    items: list[dict[str, Any]]
    model_name: str
    prompt_version: str
    raw_masked_text: str
    latency_ms: int


@dataclass
class AIOCRResult:
    """Kết quả nhận diện ảnh nhận từ `ai-service` `/api/v1/ocr`."""

    engine: str
    text: str
    confidence: float
    lines: list[dict[str, Any]]
    has_text: bool


@dataclass
class WarehouseMatchResult:
    """Kết quả đối chiếu địa chỉ kho từ `ai-service` `/api/v1/match-warehouse`."""

    matched: bool
    warehouse_id: int | None
    warehouse_name: str | None
    confidence: float
    source: str


class AIServiceClient:
    """Client HTTP dùng chung để Backend giao tiếp an toàn với `ai-service`."""

    @staticmethod
    def _headers() -> dict[str, str]:
        """Khởi tạo HTTP headers kèm `X-Internal-Token` nội bộ."""
        return {
            "Content-Type": "application/json",
            "X-Internal-Token": settings.INTERNAL_SECRET or "",
        }

    @staticmethod
    def _base_url() -> str:
        """Lấy địa chỉ cơ sở của AI Microservice từ cấu hình hệ thống."""
        return (settings.AI_SERVICE_URL or "").strip().rstrip("/")

    @staticmethod
    def mask_phones(
        text: str | None, existing_map: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        """Che SĐT trong văn bản thành dạng `0903xxxx59` trước khi gửi sang `ai-service`."""
        phone_map: dict[str, str] = dict(existing_map or {})
        if not text:
            return "", phone_map

        def _repl(match: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("84") and len(digits) == 11:
                digits = "0" + digits[2:]
            if len(digits) < 9 or len(digits) > 11:
                return match.group(0)
            base_tok = f"{digits[:4]}xxxx{digits[-2:]}"
            tok = base_tok
            idx = 2
            while tok in phone_map and phone_map[tok] != digits:
                tok = f"{base_tok}_{idx}"
                idx += 1
            phone_map[tok] = digits
            return tok

        return _VN_PHONE_RE.sub(_repl, text), phone_map

    @staticmethod
    def restore_phone(value: str | None, phone_map: dict[str, str]) -> str | None:
        """Khôi phục SĐT thật từ chuỗi kết quả do AI trả về."""
        if not value or not phone_map:
            return value
        out = str(value)
        for tok in sorted(phone_map.keys(), key=len, reverse=True):
            if tok in out:
                out = out.replace(tok, phone_map[tok])
        return out

    @classmethod
    def extract(
        cls,
        message_text: str,
        sender_id: str | None = None,
        group_id: str | None = None,
        carrier_id: int | None = None,
        quote_message: str | None = None,
        active_plans: list[dict[str, Any]] | None = None,
        context_messages: list[str] | None = None,
        message_type: str = "text",
    ) -> AIExtractResult | None:
        """Gửi yêu cầu phân loại ý định và bóc tách đa thực thể sang `/api/v1/extract`."""
        base = cls._base_url()
        if not base or not settings.AI_ENABLED:
            return None

        masked_text, phone_map = cls.mask_phones(message_text)
        masked_quote, phone_map = cls.mask_phones(quote_message, existing_map=phone_map)
        masked_ctx: list[str] = []
        for cm in context_messages or []:
            mc, phone_map = cls.mask_phones(cm, existing_map=phone_map)
            masked_ctx.append(mc)

        payload = {
            "message_text": masked_text,
            "sender_id": sender_id,
            "group_id": group_id,
            "carrier_id": carrier_id,
            "message_type": message_type,
            "quote_message": masked_quote or None,
            "context_messages": masked_ctx,
            "active_plans": active_plans or [],
        }

        try:
            timeout = float(settings.AI_TIMEOUT_SECONDS or 10) + 3.0
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{base}/api/v1/extract",
                    headers=cls._headers(),
                    json=payload,
                )
            if resp.status_code != 200:
                logger.warning("AI Service /extract trả về HTTP %s", resp.status_code)
                return None

            data = resp.json()
            items = data.get("items") or []
            for item in items:
                if isinstance(item, dict):
                    item["driver_phone"] = cls.restore_phone(item.get("driver_phone"), phone_map)
                    item["evidence"] = cls.restore_phone(item.get("evidence"), phone_map)

            return AIExtractResult(
                intent=str(data.get("intent") or "PARSE_TRUCK_INFO"),
                is_multi_vehicle=bool(data.get("is_multi_vehicle")),
                items=items,
                model_name=str(data.get("model_name") or settings.AI_MODEL_NAME),
                prompt_version=str(data.get("prompt_version") or "ai_extract_v2.0"),
                raw_masked_text=str(data.get("raw_masked_text") or masked_text),
                latency_ms=int(data.get("latency_ms") or 0),
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.debug("Không thể kết nối AI Service /extract (%s), chuyển fallback cục bộ.", exc)
            return None

    @classmethod
    def perform_ocr(
        cls,
        image_base64: str | None = None,
        image_url: str | None = None,
        file_key: str | None = None,
        lang: str = "vi",
    ) -> AIOCRResult | None:
        """Gọi `/api/v1/ocr` trên `ai-service` để trích xuất chữ từ ảnh điều xe."""
        base = cls._base_url()
        if not base or not settings.OCR_ENABLED:
            return None
        if not any([image_base64, image_url, file_key]):
            return None

        payload = {
            "image_base64": image_base64,
            "image_url": image_url,
            "file_key": file_key,
            "lang": lang,
        }
        try:
            timeout = float(settings.OCR_TIMEOUT_SECONDS or 15) + 5.0
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{base}/api/v1/ocr",
                    headers=cls._headers(),
                    json=payload,
                )
            if resp.status_code != 200:
                logger.warning("AI Service /ocr trả về HTTP %s", resp.status_code)
                return None

            data = resp.json()
            return AIOCRResult(
                engine=str(data.get("engine") or "paddleocr"),
                text=str(data.get("text") or ""),
                confidence=float(data.get("confidence") or 0.0),
                lines=data.get("lines") or [],
                has_text=bool(data.get("has_text")),
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.debug("Không thể kết nối AI Service /ocr (%s), dùng OCR fallback cục bộ.", exc)
            return None

    @classmethod
    def match_warehouse(
        cls,
        raw_address: str,
        carrier_id: int | None = None,
        customer_id: int | None = None,
        candidate_warehouses: list[dict[str, Any]] | None = None,
    ) -> WarehouseMatchResult | None:
        """Gọi `/api/v1/match-warehouse` để đối chiếu tên/địa chỉ kho nhiều tầng."""
        base = cls._base_url()
        if not base or not raw_address.strip():
            return None

        payload = {
            "raw_address": raw_address.strip(),
            "carrier_id": carrier_id,
            "customer_id": customer_id,
            "candidate_warehouses": candidate_warehouses or [],
        }
        try:
            timeout = float(settings.AI_TIMEOUT_SECONDS or 10)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{base}/api/v1/match-warehouse",
                    headers=cls._headers(),
                    json=payload,
                )
            if resp.status_code != 200:
                return None

            data = resp.json()
            return WarehouseMatchResult(
                matched=bool(data.get("matched")),
                warehouse_id=data.get("warehouse_id"),
                warehouse_name=data.get("warehouse_name"),
                confidence=float(data.get("confidence") or 0.0),
                source=str(data.get("source") or "unresolved"),
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.debug("Không thể kết nối AI Service /match-warehouse: %s", exc)
            return None
