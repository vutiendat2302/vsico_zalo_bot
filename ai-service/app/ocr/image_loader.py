"""Tiện ích tải và chuẩn hóa dữ liệu ảnh đầu vào cho bộ máy OCR."""

import base64
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.schemas.ocr import OCRRequest


@dataclass
class LoadedImage:
    """Thông tin ảnh nhị phân đã nạp từ base64, URL hoặc MinIO."""

    image_bytes: bytes
    mime_type: str = "image/jpeg"


def _detect_mime_type(data: bytes, hint: str | None = None) -> str:
    """Xác định MIME type thực tế từ magic bytes của ảnh."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"%PDF":
        return "application/pdf"
    if hint and "/" in hint:
        return hint.split(";")[0].strip().lower()
    return "image/jpeg"


async def load_image_from_request(req: OCRRequest) -> LoadedImage | None:
    """Nạp dữ liệu byte của ảnh từ `image_base64`, `image_url` hoặc `file_key`."""
    if req.image_base64:
        b64_str = req.image_base64.strip()
        mime_hint: str | None = None
        if b64_str.startswith("data:") and "," in b64_str:
            header, b64_str = b64_str.split(",", 1)
            mime_hint = header.replace("data:", "").split(";")[0].strip()
        try:
            raw = base64.b64decode(b64_str, validate=False)
            if raw:
                return LoadedImage(image_bytes=raw, mime_type=_detect_mime_type(raw, mime_hint))
        except (ValueError, TypeError):
            return None

    target_url = req.image_url
    if not target_url and req.file_key:
        scheme = "https" if settings.MINIO_SECURE else "http"
        target_url = f"{scheme}://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_NAME}/{req.file_key.lstrip('/')}"

    if target_url:
        try:
            async with httpx.AsyncClient(timeout=float(settings.OCR_TIMEOUT_SECONDS or 15), follow_redirects=True) as client:
                resp = await client.get(target_url)
            if resp.status_code == 200 and resp.content:
                ct = resp.headers.get("Content-Type")
                return LoadedImage(image_bytes=resp.content, mime_type=_detect_mime_type(resp.content, ct))
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    return None
