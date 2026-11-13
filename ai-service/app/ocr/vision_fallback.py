"""Bộ fallback nhận diện ảnh điều xe bằng Multimodal Vision AI khi PaddleOCR không đủ tin cậy."""

from app.providers.base_provider import VisionOCRResult
from app.providers.factory import get_ai_provider
from app.schemas.ocr import OCRLine, OCRResponse


class VisionOCRFallback:
    """Chuyển sang Vision LLM đọc chữ trên ảnh khi PaddleOCR lỗi hoặc ảnh nghiêng/viết tay."""

    @staticmethod
    async def recognize(image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi") -> OCRResponse:
        """Gọi Provider Vision đọc ảnh và chuyển sang `OCRResponse` chuẩn."""
        provider = get_ai_provider()
        res: VisionOCRResult = await provider.ocr_image_vision(
            image_bytes=image_bytes,
            mime_type=mime_type,
            lang=lang,
        )
        engine_name = f"{provider.provider_name}_vision"
        lines = [OCRLine(text=ln, confidence=res.confidence, box=[]) for ln in res.lines]
        return OCRResponse(
            engine=engine_name,
            text=res.text,
            confidence=res.confidence,
            lines=lines,
            has_text=bool(res.text.strip()),
        )
