"""Kiểm thử endpoint `/api/v1/ocr` và luồng fallback PaddleOCR -> Vision LLM."""

import base64
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.ocr.paddle_engine import PaddleOCREngine, PaddleResult
from app.ocr.vision_fallback import VisionOCRFallback
from app.schemas.ocr import OCRLine, OCRResponse

client = TestClient(app)
SAMPLE_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake_png_payload").decode("ascii")


def test_ocr_requires_valid_internal_token() -> None:
    """Từ chối request thiếu hoặc sai `X-Internal-Token` với HTTP 401/422."""
    resp_missing = client.post("/api/v1/ocr", json={"image_base64": SAMPLE_PNG_B64})
    assert resp_missing.status_code == 422

    resp_wrong = client.post(
        "/api/v1/ocr",
        headers={"X-Internal-Token": "wrong_secret"},
        json={"image_base64": SAMPLE_PNG_B64},
    )
    assert resp_wrong.status_code == 401


def test_ocr_uses_paddle_when_confident(monkeypatch) -> None:
    """Ưu tiên trả kết quả từ PaddleOCR khi độ tin cậy đạt ngưỡng >= 0.55."""

    async def _fake_paddle(_img_bytes: bytes) -> PaddleResult:
        return PaddleResult(
            success=True,
            lines=[OCRLine(text="15C-878.99 MSCU1234567", confidence=0.92, box=[])],
            joined_text="15C-878.99 MSCU1234567",
            avg_confidence=0.92,
        )

    monkeypatch.setattr(PaddleOCREngine, "recognize", _fake_paddle)

    resp = client.post(
        "/api/v1/ocr",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={"image_base64": SAMPLE_PNG_B64, "lang": "vi"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["engine"] == "paddleocr"
    assert data["has_text"] is True
    assert "MSCU1234567" in data["text"]


def test_ocr_falls_back_to_vision_when_paddle_low_conf(monkeypatch) -> None:
    """Tự động chuyển sang Vision fallback khi PaddleOCR trả độ tin cậy thấp hoặc rỗng."""

    async def _weak_paddle(_img_bytes: bytes) -> PaddleResult:
        return PaddleResult(success=False, joined_text="", avg_confidence=0.2)

    async def _fake_vision(image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi") -> OCRResponse:
        assert len(image_bytes) > 0
        return OCRResponse(
            engine="gemini_vision",
            text="Xe 50H-049.15\nCont SEGU4567890",
            confidence=0.9,
            lines=[OCRLine(text="Xe 50H-049.15", confidence=0.9, box=[])],
            has_text=True,
        )

    monkeypatch.setattr(PaddleOCREngine, "recognize", _weak_paddle)
    monkeypatch.setattr(VisionOCRFallback, "recognize", _fake_vision)

    resp = client.post(
        "/api/v1/ocr",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={"image_base64": SAMPLE_PNG_B64, "lang": "vi"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["engine"] == "gemini_vision"
    assert data["has_text"] is True
    assert "SEGU4567890" in data["text"]
