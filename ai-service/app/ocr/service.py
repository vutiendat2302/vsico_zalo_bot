"""Dịch vụ điều phối pipeline OCR ảnh (PaddleOCR nội bộ -> fallback Multimodal Vision)."""

from app.ocr.image_loader import load_image_from_request
from app.ocr.paddle_engine import PaddleOCREngine
from app.ocr.vision_fallback import VisionOCRFallback
from app.schemas.ocr import OCRRequest, OCRResponse

_MIN_PADDLE_CONFIDENCE = 0.55


class OCRService:
    """Điều phối quy trình nhận diện văn bản ảnh theo thứ tự ưu tiên chi phí và độ chính xác."""

    @staticmethod
    async def extract_text_from_image(req: OCRRequest) -> OCRResponse:
        """Nạp ảnh, ưu tiên chạy PaddleOCR cục bộ và tự chuyển Vision AI nếu cần."""
        loaded = await load_image_from_request(req)
        if not loaded or not loaded.image_bytes:
            return OCRResponse(engine="paddleocr", text="", confidence=0.0, lines=[], has_text=False)

        paddle_res = await PaddleOCREngine.recognize(loaded.image_bytes)
        if (
            paddle_res.success
            and paddle_res.joined_text.strip()
            and paddle_res.avg_confidence >= _MIN_PADDLE_CONFIDENCE
        ):
            return OCRResponse(
                engine="paddleocr",
                text=paddle_res.joined_text,
                confidence=paddle_res.avg_confidence,
                lines=paddle_res.lines,
                has_text=True,
            )

        vision_res = await VisionOCRFallback.recognize(
            image_bytes=loaded.image_bytes,
            mime_type=loaded.mime_type,
            lang=req.lang,
        )
        if vision_res.has_text:
            return vision_res

        # Trả về kết quả PaddleOCR dù độ tin cậy thấp hơn ngưỡng nếu Vision không khả dụng
        if paddle_res.joined_text.strip():
            return OCRResponse(
                engine="paddleocr",
                text=paddle_res.joined_text,
                confidence=paddle_res.avg_confidence,
                lines=paddle_res.lines,
                has_text=True,
            )
        return vision_res
