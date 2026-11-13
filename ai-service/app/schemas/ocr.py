"""Schemas Pydantic cho endpoint nhận diện văn bản OCR."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class OCRRequest(BaseModel):
    """Payload nhận diện OCR ảnh từ backend."""
    image_base64: Optional[str] = Field(None, description="Chuỗi base64 của ảnh")
    image_url: Optional[str] = Field(None, description="URL tải ảnh từ MinIO hoặc Web")
    file_key: Optional[str] = Field(None, description="Khóa file trong MinIO")
    lang: str = Field(default="vi", description="Ngôn ngữ OCR")


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
