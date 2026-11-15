"""Kiểm thử endpoint `/api/v1/ocr` và luồng fallback PaddleOCR -> Vision LLM."""

import base64
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.ocr.image_preprocessor import ImagePreprocessor
from app.ocr.layout_analyzer import LayoutAnalysisResult, LayoutAnalyzer
from app.ocr.paddle_engine import PaddleOCREngine, PaddleResult
from app.ocr.reading_order import ReadingOrder
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


def test_layout_analyzer_detects_table_and_reading_order_joins_columns() -> None:
    """LayoutAnalyzer phát hiện bảng nhiều cột với ngưỡng Y động và nối cột bằng ` | `."""
    raw_table = [
        {"text": "Biển số", "confidence": 0.99, "text_region": [[10, 10], [100, 10], [100, 42], [10, 42]]},
        {"text": "Số cont", "confidence": 0.99, "text_region": [[180, 12], [280, 12], [280, 44], [180, 44]]},
        {"text": "Số chì", "confidence": 0.99, "text_region": [[360, 10], [450, 10], [450, 42], [360, 42]]},
        {"text": "15C-878.99", "confidence": 0.96, "text_region": [[10, 60], [120, 60], [120, 96], [10, 96]]},
        {"text": "SELU4642484", "confidence": 0.97, "text_region": [[180, 76], [300, 76], [300, 110], [180, 110]]},
        {"text": "VSICO12345", "confidence": 0.95, "text_region": [[360, 62], [470, 62], [470, 96], [360, 96]]},
    ]
    layout = LayoutAnalyzer.analyze(raw_table)
    assert layout.layout_type == "table"
    assert layout.estimated_columns == 3
    assert layout.is_complex_table is True
    # Chiều cao chữ ~34px -> ngưỡng Y động > 14px nên vẫn gom đúng 1 hàng dù lệch 16px
    rows = ReadingOrder.reconstruct(raw_table, layout)
    assert len(rows) == 2
    assert rows[1] == "15C-878.99 | SELU4642484 | VSICO12345"


def test_ocr_routes_complex_table_to_vision_even_with_high_paddle_conf(monkeypatch) -> None:
    """Ảnh bảng nhiều cột phức tạp được ưu tiên chuyển sang Vision LLM để tránh lệch cột."""

    async def _table_paddle(_img_bytes: bytes) -> PaddleResult:
        return PaddleResult(
            success=True,
            lines=[OCRLine(text="Biển số | Số cont | Số chì", confidence=0.95, box=[])],
            joined_text="Biển số | Số cont | Số chì\n15C-878.99 | SELU4642484 | 12345",
            avg_confidence=0.95,
            layout=LayoutAnalysisResult(
                layout_type="table",
                row_count=4,
                estimated_columns=3,
                is_complex_table=True,
            ),
        )

    async def _fake_vision(image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi") -> OCRResponse:
        return OCRResponse(
            engine="gemini_vision",
            text="15C-878.99 - SELU4642484 - Chì 12345",
            confidence=0.94,
            lines=[OCRLine(text="15C-878.99 - SELU4642484 - Chì 12345", confidence=0.94, box=[])],
            has_text=True,
        )

    monkeypatch.setattr(PaddleOCREngine, "recognize", _table_paddle)
    monkeypatch.setattr(VisionOCRFallback, "recognize", _fake_vision)

    resp = client.post(
        "/api/v1/ocr",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={"image_base64": SAMPLE_PNG_B64, "lang": "vi"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["engine"] == "gemini_vision"
    assert data["layout_type"] == "table"
    assert "SELU4642484" in data["text"]


def test_image_preprocessor_handles_fake_and_small_png() -> None:
    """ImagePreprocessor đọc kích thước header PNG và passthrough an toàn không lỗi."""
    # PNG 1x1 tối giản chỉ có IHDR
    ihdr_only = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\xdc\x00\x00\x00\x3f\x08\x06\x00\x00\x00"
    res = ImagePreprocessor.preprocess(ihdr_only)
    assert res.original_size == (476, 63)
    assert len(res.image_bytes) > 0


def test_ocr_force_vision_bypasses_paddle(monkeypatch) -> None:
    """Khi truyền `force_vision=true`, bỏ qua PaddleOCR và gọi thẳng Vision LLM."""

    async def _paddle_should_not_run(_img_bytes: bytes) -> PaddleResult:
        raise AssertionError("Không được gọi PaddleOCR khi force_vision=True")

    async def _fake_vision(image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi") -> OCRResponse:
        return OCRResponse(
            engine="gemini_vision",
            text="Xe 15H-008.14 - Phạm Tiến Hưng",
            confidence=0.95,
            lines=[OCRLine(text="Xe 15H-008.14 - Phạm Tiến Hưng", confidence=0.95, box=[])],
            has_text=True,
        )

    monkeypatch.setattr(PaddleOCREngine, "recognize", _paddle_should_not_run)
    monkeypatch.setattr(VisionOCRFallback, "recognize", _fake_vision)

    resp = client.post(
        "/api/v1/ocr",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={"image_base64": SAMPLE_PNG_B64, "lang": "vi", "force_vision": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["engine"] == "gemini_vision"
    assert data["has_text"] is True
    assert "15H-008.14" in data["text"]


def test_paddle_engine_sends_api_key_header_when_configured(monkeypatch) -> None:
    """PaddleOCREngine tự động gửi header X-API-Key khi OCR_API_KEY được cấu hình."""
    import asyncio
    import httpx

    captured: dict[str, object] = {}

    class _FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"results": [[{"text": "Xe 15H-008.14", "confidence": 0.99, "text_region": [[0, 0], [100, 0], [100, 20], [0, 20]]}]]}

    class _FakeClient:
        def __init__(self, timeout: float):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict, headers: dict | None = None):
            captured["url"] = url
            captured["headers"] = headers or {}
            return _FakeResp()

    monkeypatch.setattr(settings, "OCR_API_KEY", "secret-ocr-key")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    res = asyncio.run(PaddleOCREngine.recognize(b"fake-bytes"))
    assert res.success is True
    assert captured["headers"] == {"X-API-Key": "secret-ocr-key"}


def test_image_loader_signs_s3_headers_for_file_key(monkeypatch) -> None:
    """`load_image_from_request` ký AWS SigV4 khi tải ảnh theo `file_key` từ bucket private MinIO."""
    import asyncio
    import httpx
    from app.ocr.image_loader import load_image_from_request
    from app.schemas.ocr import OCRRequest

    captured: dict[str, object] = {}

    class _FakeResp:
        status_code = 200
        content = b"\x89PNG\r\n\x1a\nfake-png"
        headers = {"Content-Type": "image/png"}

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, headers: dict | None = None):
            captured["url"] = url
            captured["headers"] = headers or {}
            return _FakeResp()

    monkeypatch.setattr(settings, "MINIO_ENDPOINT", "127.0.0.1:9000")
    monkeypatch.setattr(settings, "MINIO_BUCKET_NAME", "vsico-zalo-files")
    monkeypatch.setattr(settings, "MINIO_ROOT_USER", "minioadmin")
    monkeypatch.setattr(settings, "MINIO_ROOT_PASSWORD", "minioadmin123")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    loaded = asyncio.run(
        load_image_from_request(OCRRequest(file_key="uploads/postman/test.png", lang="vi"))
    )
    assert loaded is not None
    assert loaded.mime_type == "image/png"
    assert captured["url"] == "http://127.0.0.1:9000/vsico-zalo-files/uploads/postman/test.png"
    hdrs = captured["headers"]
    assert "AWS4-HMAC-SHA256" in hdrs["Authorization"]
    assert hdrs["x-amz-content-sha256"] == "UNSIGNED-PAYLOAD"
