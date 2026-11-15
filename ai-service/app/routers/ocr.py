"""Router xử lý nhận diện văn bản OCR từ hình ảnh (PaddleOCR / Gemini Vision)."""

from fastapi import APIRouter, Depends

from app.core.security import verify_internal_token
from app.ocr.service import OCRService
from app.schemas.ocr import OCRRequest, OCRResponse

router = APIRouter(prefix="/api/v1", tags=["2. Nhận Diện Hình Ảnh (OCR)"])


@router.post("/ocr", response_model=OCRResponse)
async def perform_ocr(
    payload: OCRRequest,
    _auth: str = Depends(verify_internal_token),
) -> OCRResponse:
    """Nhận diện chữ viết tiếng Việt từ ảnh phiếu lệnh điều xe hoặc giao nhận cont."""
    return await OCRService.extract_text_from_image(payload)
