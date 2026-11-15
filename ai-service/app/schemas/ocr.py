"""Schemas Pydantic cho endpoint nhận diện văn bản OCR."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class OCRRequest(BaseModel):
    """Payload nhận diện OCR ảnh từ backend."""
    image_base64: Optional[str] = Field(None, description="Chuỗi base64 của ảnh")
    image_url: Optional[str] = Field(None, description="URL tải ảnh từ MinIO hoặc Web")
    file_key: Optional[str] = Field(None, description="Khóa file trong MinIO")
    lang: str = Field(default="vi", description="Ngôn ngữ OCR")
    force_vision: bool = Field(
        default=False,
        description="Nếu true, bỏ qua PaddleOCR và gọi thẳng Vision LLM để kiểm thử",
    )


class OCRLine(BaseModel):
    """Dòng chữ nhận diện được từ ảnh."""
    text: str
    confidence: float
    box: list[list[int]] = Field(default_factory=list)


class OCRResponse(BaseModel):
    """Kết quả trả về sau khi OCR."""
    engine: str = Field(..., description="paddleocr | gemini_vision")
    text: str = Field(..., description="Toàn bộ văn bản bóc tách nối lại")
    confidence: float = Field(default=0.0, description="Độ tin cậy trung bình")
    lines: list[OCRLine] = Field(default_factory=list)
    has_text: bool = Field(default=False, description="Ảnh có chứa chữ hay không")
    layout_type: str = Field(
        default="unknown",
        description="Loại bố cục phát hiện được: chat_screenshot | table | slip | unknown",
    )
    preprocessing_applied: list[str] = Field(
        default_factory=list,
        description="Danh sách các bước tiền xử lý ảnh đã thực hiện",
    )
    error: Optional[str] = Field(
        default=None,
        description="Thông báo lỗi chi tiết nếu bước OCR/Vision thất bại",
    )
