"""Bộ fallback nhận diện ảnh điều xe bằng Multimodal Vision AI khi PaddleOCR không đủ tin cậy."""

from app.ocr.reading_order import is_ui_noise
from app.providers.base_provider import VisionOCRResult
from app.providers.factory import get_ai_provider
from app.schemas.ocr import OCRLine, OCRResponse


class VisionOCRFallback:
    """Chuyển sang Vision LLM đọc chữ trên ảnh khi PaddleOCR lỗi hoặc ảnh nghiêng/viết tay."""

    @staticmethod
    async def recognize(image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi") -> OCRResponse:
        """Gọi Provider Vision đọc ảnh, lọc nhiễu UI và chuyển sang `OCRResponse` chuẩn."""
        provider = get_ai_provider()
        res: VisionOCRResult = await provider.ocr_image_vision(
            image_bytes=image_bytes,
            mime_type=mime_type,
            lang=lang,
        )
        engine_name = f"{provider.provider_name}_vision"
        clean_lines = [ln.strip() for ln in res.lines if ln.strip() and not is_ui_noise(ln)]
        clean_text = "\n".join(clean_lines)
        lines = [OCRLine(text=ln, confidence=res.confidence, box=[]) for ln in clean_lines]
        return OCRResponse(
            engine=engine_name,
            text=clean_text,
            confidence=res.confidence if clean_lines else 0.0,
            lines=lines,
            has_text=bool(clean_text.strip()),
            error=res.error if not res.success else None,
        )
