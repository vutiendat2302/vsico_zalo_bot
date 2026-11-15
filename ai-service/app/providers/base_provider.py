"""Module interface chuẩn cho các AI Provider trong `ai-service`."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    """Kết quả chuẩn trả về từ lệnh sinh JSON có cấu trúc của AI Provider."""

    success: bool
    parsed: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    model_name: str = ""
    latency_ms: int = 0
    error: str | None = None


@dataclass
class VisionOCRResult:
    """Kết quả nhận diện văn bản từ ảnh bằng mô hình đa phương thức (Vision LLM)."""

    success: bool
    text: str = ""
    lines: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model_name: str = ""
    latency_ms: int = 0
    error: str | None = None


class BaseAIProvider(ABC):
    """Lớp trừu tượng định nghĩa hợp đồng chung cho Gemini, OpenAI-compatible và provider khác."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Tên định danh của AI Provider."""

    @abstractmethod
    async def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float | None = None,
    ) -> ProviderResult:
        """Gửi prompt phân tích hội thoại và trả về dữ liệu JSON có cấu trúc."""

    @abstractmethod
    async def ocr_image_vision(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        lang: str = "vi",
        timeout_seconds: float | None = None,
    ) -> VisionOCRResult:
        """Đọc nội dung chữ tiếng Việt từ ảnh điều xe hoặc ảnh phiếu container."""
