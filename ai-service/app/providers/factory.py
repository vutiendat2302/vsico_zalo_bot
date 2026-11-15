"""Factory lựa chọn AI Provider theo biến môi trường `AI_PROVIDER`."""

from app.core.config import settings
from app.providers.base_provider import BaseAIProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAICompatibleProvider


def get_ai_provider() -> BaseAIProvider:
    """Khởi tạo thực thể AI Provider tương ứng cấu hình hiện hành."""
    provider_key = (settings.AI_PROVIDER or "gemini").strip().lower()
    if provider_key == "gemini":
        return GeminiProvider()
    return OpenAICompatibleProvider()
