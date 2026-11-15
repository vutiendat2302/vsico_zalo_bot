"""Dịch vụ điều phối pipeline OCR ảnh: Tiền xử lý -> PaddleOCR + Layout -> Vision Fallback."""

from app.ocr.image_loader import load_image_from_request
from app.ocr.image_preprocessor import ImagePreprocessor
from app.ocr.paddle_engine import PaddleOCREngine
from app.ocr.vision_fallback import VisionOCRFallback
from app.schemas.ocr import OCRRequest, OCRResponse

_MIN_PADDLE_CONFIDENCE = 0.55


class OCRService:
    """Điều phối quy trình nhận diện văn bản ảnh ưu tiên chi phí thấp và độ chính xác với bảng."""

    @staticmethod
    async def extract_text_from_image(req: OCRRequest) -> OCRResponse:
        """Tiền xử lý ảnh, chạy PaddleOCR cục bộ, phân tích bố cục và chuyển Vision khi cần."""
        loaded = await load_image_from_request(req)
        if not loaded or not loaded.image_bytes:
            return OCRResponse(
                engine="paddleocr",
                text="",
                confidence=0.0,
                lines=[],
                has_text=False,
                layout_type="unknown",
                preprocessing_applied=[],
            )

        prep = ImagePreprocessor.preprocess(loaded.image_bytes)
        if req.force_vision:
            vision_res = await VisionOCRFallback.recognize(
                image_bytes=prep.image_bytes,
                mime_type=loaded.mime_type,
                lang=req.lang,
            )
            return vision_res.model_copy(
                update={
                    "layout_type": "unknown",
                    "preprocessing_applied": prep.applied_steps,
                }
            )

        paddle_res = await PaddleOCREngine.recognize(prep.image_bytes)
        detected_layout = paddle_res.layout.layout_type if paddle_res.layout else "unknown"

        # Nếu là bảng nhiều cột phức tạp hoặc PaddleOCR không đạt ngưỡng tin cậy -> gọi Vision LLM
        should_use_vision = (
            (paddle_res.layout and paddle_res.layout.is_complex_table)
            or not paddle_res.success
            or not paddle_res.joined_text.strip()
            or paddle_res.avg_confidence < _MIN_PADDLE_CONFIDENCE
        )

        if not should_use_vision:
            return OCRResponse(
                engine="paddleocr",
                text=paddle_res.joined_text,
                confidence=paddle_res.avg_confidence,
                lines=paddle_res.lines,
                has_text=True,
                layout_type=detected_layout,
                preprocessing_applied=prep.applied_steps,
            )

        vision_res = await VisionOCRFallback.recognize(
            image_bytes=prep.image_bytes,
            mime_type=loaded.mime_type,
            lang=req.lang,
        )
        if vision_res.has_text:
            return vision_res.model_copy(
                update={
                    "layout_type": detected_layout if detected_layout != "unknown" else "table",
                    "preprocessing_applied": prep.applied_steps,
                }
            )

        # Trả về kết quả PaddleOCR (đã format theo cột nếu là bảng) khi Vision không khả dụng
        if paddle_res.joined_text.strip():
            return OCRResponse(
                engine="paddleocr",
                text=paddle_res.joined_text,
                confidence=paddle_res.avg_confidence,
                lines=paddle_res.lines,
                has_text=True,
                layout_type=detected_layout,
                preprocessing_applied=prep.applied_steps,
            )
        return vision_res.model_copy(
            update={
                "layout_type": detected_layout,
                "preprocessing_applied": prep.applied_steps,
            }
        )
