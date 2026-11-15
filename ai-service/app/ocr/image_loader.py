"""Tiện ích tải và chuẩn hóa dữ liệu ảnh đầu vào cho bộ máy OCR."""

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from urllib.parse import quote, urlparse

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


def _sign_s3_key(key: bytes, msg: str) -> bytes:
    """Tính chữ ký HMAC-SHA256 từng bước theo chuẩn AWS Signature V4."""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _build_s3_auth_headers(
    host: str,
    canonical_uri: str,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    now: datetime | None = None,
) -> dict[str, str]:
    """Tạo header xác thực AWS Signature V4 cho GET object từ MinIO bucket private."""
    dt = now or datetime.now(timezone.utc)
    amz_date = dt.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = dt.strftime("%Y%m%d")
    payload_hash = "UNSIGNED-PAYLOAD"

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = (
        f"GET\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{amz_date}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    k_date = _sign_s3_key(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign_s3_key(k_date, region)
    k_service = _sign_s3_key(k_region, "s3")
    k_signing = _sign_s3_key(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    auth_header = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": auth_header,
    }


def _normalize_minio_base(endpoint: str, secure: bool) -> tuple[str, str]:
    """Tách URL gốc và header `Host` hợp lệ từ cấu hình `MINIO_ENDPOINT`."""
    cleaned = (endpoint or "127.0.0.1:9000").strip().rstrip("/")
    if cleaned.startswith(("http://", "https://")):
        parsed = urlparse(cleaned)
        return f"{parsed.scheme}://{parsed.netloc}", parsed.netloc
    scheme = "https" if secure else "http"
    return f"{scheme}://{cleaned}", cleaned


async def load_image_from_request(req: OCRRequest) -> LoadedImage | None:
    """Nạp dữ liệu byte của ảnh từ `image_base64`, `image_url` hoặc `file_key` (MinIO object_key)."""
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

    target_url = (req.image_url or "").strip() or None
    req_headers: dict[str, str] = {}

    if not target_url and req.file_key:
        clean_key = req.file_key.strip().lstrip("/")
        bucket = (settings.MINIO_BUCKET_NAME or "vsico-zalo-files").strip()
        if clean_key.startswith(f"{bucket}/"):
            canonical_uri = "/" + quote(clean_key, safe="/-_.~")
        else:
            canonical_uri = f"/{quote(bucket, safe='-_.~')}/{quote(clean_key, safe='/-_.~')}"

        base_url, host_header = _normalize_minio_base(
            settings.MINIO_ENDPOINT,
            bool(settings.MINIO_SECURE),
        )
        target_url = f"{base_url}{canonical_uri}"
        access_key = (settings.MINIO_ROOT_USER or "").strip()
        secret_key = (settings.MINIO_ROOT_PASSWORD or "").strip()
        if access_key and secret_key:
            req_headers = _build_s3_auth_headers(
                host=host_header,
                canonical_uri=canonical_uri,
                access_key=access_key,
                secret_key=secret_key,
            )

    if target_url:
        try:
            async with httpx.AsyncClient(timeout=float(settings.OCR_TIMEOUT_SECONDS or 15), follow_redirects=True) as client:
                resp = await client.get(target_url, headers=req_headers)
            if resp.status_code == 200 and resp.content:
                ct = resp.headers.get("Content-Type")
                return LoadedImage(image_bytes=resp.content, mime_type=_detect_mime_type(resp.content, ct))
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    return None
