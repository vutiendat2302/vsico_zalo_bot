"""Router xử lý bóc tách thông tin hội thoại và phân loại ý định (NLP Extraction)."""

from fastapi import APIRouter, Depends

from app.analyze.service import AnalyzeService
from app.core.security import verify_internal_token
from app.schemas.extract import ExtractRequest, ExtractResponse

router = APIRouter(prefix="/api/v1", tags=["1. Bóc Tách NLP & Ý Định"])


@router.post("/extract", response_model=ExtractResponse)
async def extract_message(
    payload: ExtractRequest,
    _auth: str = Depends(verify_internal_token),
) -> ExtractResponse:
    """Bóc tách thực thể vận tải container và phân loại ý định hội thoại từ tin nhắn."""
    return await AnalyzeService.extract(payload)
