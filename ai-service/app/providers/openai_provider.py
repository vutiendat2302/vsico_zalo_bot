"""Triển khai OpenAI-Compatible Provider (OpenAI, Ollama, vLLM, Groq, OpenRouter)."""

import base64
import time

import httpx

from app.core.config import settings
from app.providers.base_provider import BaseAIProvider, ProviderResult, VisionOCRResult
from app.providers.json_utils import parse_json_object


class OpenAICompatibleProvider(BaseAIProvider):
    """Provider gọi endpoint `/chat/completions` chuẩn OpenAI cho cả text JSON và ảnh Vision."""

    @property
    def provider_name(self) -> str:
        """Tên định danh của OpenAI-Compatible Provider."""
        return settings.AI_PROVIDER or "openai_compatible"

    def _headers(self) -> dict[str, str]:
        """Khởi tạo HTTP header xác thực Bearer token."""
        headers = {"Content-Type": "application/json"}
        if settings.AI_API_KEY:
            headers["Authorization"] = f"Bearer {settings.AI_API_KEY}"
        return headers

    def _chat_url(self) -> str:
        """Tạo đường dẫn đầy đủ tới `/chat/completions`."""
        base = (settings.AI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    async def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float | None = None,
    ) -> ProviderResult:
        """Gọi API `/chat/completions` yêu cầu đầu ra JSON có cấu trúc."""
        if not settings.AI_API_KEY and "localhost" not in settings.AI_BASE_URL and "127.0.0.1" not in settings.AI_BASE_URL:
            return ProviderResult(
                success=False,
                model_name=settings.AI_MODEL_NAME,
                error="Chưa cấu hình AI_API_KEY cho OpenAICompatibleProvider",
            )

        timeout = timeout_seconds or float(settings.AI_TIMEOUT_SECONDS or 10)
        payload = {
            "model": settings.AI_MODEL_NAME,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self._chat_url(), headers=self._headers(), json=payload)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            if resp.status_code != 200:
                return ProviderResult(
                    success=False,
                    model_name=settings.AI_MODEL_NAME,
                    latency_ms=latency_ms,
                    error=f"HTTP {resp.status_code}: {resp.text[:250]}",
                )

            data = resp.json()
            raw_text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            parsed = parse_json_object(raw_text)
            return ProviderResult(
                success=bool(parsed),
                parsed=parsed,
                raw_text=raw_text,
                model_name=settings.AI_MODEL_NAME,
                latency_ms=latency_ms,
                error=None if parsed else "Phản hồi JSON từ model không hợp lệ",
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return ProviderResult(
                success=False,
                model_name=settings.AI_MODEL_NAME,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error=str(exc),
            )

    async def ocr_image_vision(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        lang: str = "vi",
        timeout_seconds: float | None = None,
    ) -> VisionOCRResult:
        """Nhận diện văn bản từ ảnh bằng tin nhắn đa phương thức chuẩn OpenAI."""
        if not image_bytes:
            return VisionOCRResult(success=False, model_name=settings.AI_MODEL_NAME, error="Dữ liệu ảnh rỗng")

        timeout = timeout_seconds or float(settings.OCR_TIMEOUT_SECONDS or 15)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_uri = f"data:{mime_type or 'image/jpeg'};base64,{b64}"
        payload = {
            "model": settings.AI_MODEL_NAME,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Đọc toàn bộ văn bản trong ảnh vận tải container (biển số xe, cont, seal, "
                                "tài xế, SĐT, kho, giờ). Giữ nguyên từng dòng, không bình luận thêm."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        }
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self._chat_url(), headers=self._headers(), json=payload)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code != 200:
                return VisionOCRResult(
                    success=False,
                    model_name=settings.AI_MODEL_NAME,
                    latency_ms=latency_ms,
                    error=f"HTTP {resp.status_code}: {resp.text[:250]}",
                )
            data = resp.json()
            raw_text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
            return VisionOCRResult(
                success=bool(lines),
                text="\n".join(lines),
                lines=lines,
                confidence=0.85 if lines else 0.0,
                model_name=settings.AI_MODEL_NAME,
                latency_ms=latency_ms,
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return VisionOCRResult(
                success=False,
                model_name=settings.AI_MODEL_NAME,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error=str(exc),
            )
