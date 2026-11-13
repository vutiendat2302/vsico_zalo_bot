"""Triển khai Google Gemini Provider cho phân tích hội thoại và OCR Vision."""

import base64
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base_provider import BaseAIProvider, ProviderResult, VisionOCRResult
from app.providers.json_utils import parse_json_object

logger = logging.getLogger(__name__)


class GeminiProvider(BaseAIProvider):
    """AI Provider sử dụng Google Gemini REST API hỗ trợ Structured JSON và Multimodal Vision."""

    @property
    def provider_name(self) -> str:
        """Tên định danh của Gemini Provider."""
        return "gemini"

    def _model_candidates(self) -> list[str]:
        """Tạo danh sách model ưu tiên theo cấu hình `.env` và dự phòng ổn định."""
        configured = (settings.AI_MODEL_NAME or "gemini-3.5-flash").strip()
        fallbacks = [configured, "gemini-2.5-flash", "gemini-2.0-flash"]
        seen: list[str] = []
        for model in fallbacks:
            if model and model not in seen:
                seen.append(model)
        return seen

    def _endpoint_for_model(self, model_name: str) -> str:
        """Xây dựng URL endpoint generateContent cho từng tên model Gemini."""
        base = (settings.AI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        return f"{base}/models/{model_name}:generateContent?key={settings.AI_API_KEY}"

    @staticmethod
    def _extract_candidate_text(resp_json: dict[str, Any]) -> str:
        """Đọc văn bản phản hồi từ cấu trúc JSON của Gemini API."""
        candidates = resp_json.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "\n".join(str(p.get("text", "")) for p in parts if p.get("text")).strip()

    async def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: float | None = None,
    ) -> ProviderResult:
        """Gửi prompt bóc tách văn bản sang Gemini và parse kết quả JSON."""
        if not settings.AI_API_KEY:
            return ProviderResult(
                success=False,
                model_name=settings.AI_MODEL_NAME,
                error="Chưa cấu hình AI_API_KEY cho GeminiProvider",
            )

        timeout = timeout_seconds or float(settings.AI_TIMEOUT_SECONDS or 10)
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        last_err: str | None = None
        for model in self._model_candidates():
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(self._endpoint_for_model(model), json=payload)
                latency_ms = int((time.perf_counter() - t0) * 1000)

                if resp.status_code == 200:
                    raw_text = self._extract_candidate_text(resp.json())
                    parsed = parse_json_object(raw_text)
                    if parsed:
                        return ProviderResult(
                            success=True,
                            parsed=parsed,
                            raw_text=raw_text,
                            model_name=model,
                            latency_ms=latency_ms,
                        )
                    last_err = f"Model {model} trả JSON rỗng hoặc không hợp lệ"
                else:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:250]}"
                    if resp.status_code in (400, 404):
                        logger.warning("Gemini model %s không khả dụng (%s), thử model dự phòng.", model, resp.status_code)
                        continue
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_err = str(exc)
                logger.warning("Lỗi gọi Gemini model %s: %s", model, last_err)

        return ProviderResult(
            success=False,
            model_name=settings.AI_MODEL_NAME,
            error=last_err or "Không nhận được phản hồi từ Gemini",
        )

    async def ocr_image_vision(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        lang: str = "vi",
        timeout_seconds: float | None = None,
    ) -> VisionOCRResult:
        """Nhận diện toàn bộ chữ trong ảnh phiếu/bảng điều xe bằng Gemini Multimodal Vision."""
        if not settings.AI_API_KEY:
            return VisionOCRResult(
                success=False,
                model_name=settings.AI_MODEL_NAME,
                error="Chưa cấu hình AI_API_KEY cho Gemini Vision OCR",
            )
        if not image_bytes:
            return VisionOCRResult(success=False, model_name=settings.AI_MODEL_NAME, error="Dữ liệu ảnh rỗng")

        timeout = timeout_seconds or float(settings.OCR_TIMEOUT_SECONDS or 15)
        img_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = (
            "Đọc chính xác toàn bộ chữ và số trong hình ảnh điều phối vận tải container này "
            "(biển số xe, rơ-moóc, số container 4 chữ + 7 số, số seal/chì, tên tài xế, "
            "SĐT 10 số, giờ hẹn, tên khách hàng, tên kho). "
            "Giữ nguyên bố cục từng dòng bảng/phiếu bằng các dòng xuống hàng rõ ràng, "
            "KHÔNG suy diễn hay bịa thông tin không nhìn thấy, KHÔNG giải thích thêm."
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": mime_type or "image/jpeg", "data": img_b64}},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.0},
        }

        last_err: str | None = None
        for model in self._model_candidates():
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(self._endpoint_for_model(model), json=payload)
                latency_ms = int((time.perf_counter() - t0) * 1000)

                if resp.status_code == 200:
                    raw_text = self._extract_candidate_text(resp.json())
                    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                    return VisionOCRResult(
                        success=bool(lines),
                        text="\n".join(lines),
                        lines=lines,
                        confidence=0.88 if lines else 0.0,
                        model_name=model,
                        latency_ms=latency_ms,
                    )
                last_err = f"HTTP {resp.status_code}: {resp.text[:250]}"
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_err = str(exc)

        return VisionOCRResult(
            success=False,
            model_name=settings.AI_MODEL_NAME,
            error=last_err or "Gemini Vision OCR thất bại",
        )
