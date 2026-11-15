"""Client Kết Nối & Quản Trị Đối Tượng MinIO S3 (MinIO Object Storage Client).

Cung cấp các thao tác quản lý vòng đời tệp tin trên MinIO tương thích S3:
1. Kiểm tra và tự động khởi tạo bucket lưu trữ nếu chưa tồn tại.
2. Tải tệp tin lên MinIO kèm tính toán mã băm SHA-256 toàn vẹn dữ liệu.
3. Kiểm tra trạng thái đối tượng thực tế (`stat_object`) trên MinIO.
4. Sinh liên kết tải tạm thời (`Presigned GET URL`) có thời hạn hết hạn rõ ràng.
5. Xóa đối tượng khỏi MinIO an toàn theo `bucket` và `object_key`.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import io
import logging
import os
import re
from typing import Any, Optional
import unicodedata
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from src.config.settings import TZ_VN, settings

logger = logging.getLogger("nhaxe_bot.minio")

_MIME_EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv",
    "text/plain": ".txt",
}


def slugify_path_segment(value: Optional[str], fallback: str = "mac_dinh", max_len: int = 80) -> str:
    """Chuẩn hóa tên nhóm, tên người gửi hoặc tên tệp không dấu an toàn cho đường dẫn S3/MinIO."""
    raw = (value or "").strip()
    if not raw:
        return fallback
    raw = raw.replace("đ", "d").replace("Đ", "D")
    ascii_str = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_str)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    if not cleaned or cleaned in (".", ".."):
        return fallback
    return cleaned[:max_len]


@dataclass(frozen=True)
class MinIOUploadResult:
    """Kết quả trả về sau khi tải thành công một đối tượng lên MinIO S3."""

    bucket: str
    object_key: str
    size_bytes: int
    sha256: str
    etag: str


class MinIOStorageClient:
    """Bộ giao tiếp tập trung với máy chủ MinIO S3 phục vụ lưu trữ ảnh và tài liệu."""

    def __init__(self) -> None:
        """Khởi tạo cấu hình client ở trạng thái lười (lazy-init) theo `settings`."""
        self._client: Optional[Minio] = None

    @staticmethod
    def build_object_key(
        group_name: Optional[str] = None,
        sender_name: Optional[str] = None,
        original_filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        suffix: Optional[str] = None,
        fallback_group: str = "chung",
        fallback_sender: str = "he_thong",
    ) -> str:
        """Sinh đường dẫn lưu trữ chuẩn `<nhóm>/<tên người gửi>-<tên file>-<thời gian>.<đuôi>`."""
        raw_group = (group_name or "").strip().replace("\\", "/")
        group_parts = [
            slugify_path_segment(part, fallback_group, max_len=64)
            for part in raw_group.split("/")
            if part.strip() and part.strip() not in (".", "..")
        ]
        group_seg = "/".join(group_parts) if group_parts else fallback_group

        sender_seg = slugify_path_segment(sender_name, fallback_sender, max_len=64).replace("-", "_")

        raw_file = (original_filename or "file").strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        raw_stem, raw_ext = os.path.splitext(raw_file)
        stem_seg = slugify_path_segment(raw_stem, "file", max_len=80).replace("-", "_")

        clean_ext = re.sub(r"[^A-Za-z0-9.]", "", raw_ext.lower())[:12]
        if not clean_ext or not clean_ext.startswith("."):
            clean_ext = _MIME_EXT_MAP.get((mime_type or "").split(";")[0].strip().lower(), "")

        dt = timestamp or datetime.now(TZ_VN)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_VN)
        else:
            dt = dt.astimezone(TZ_VN)
        ts_str = dt.strftime("%Y%m%d_%H%M%S")
        extra = f"_{suffix}" if suffix else ""

        return f"{group_seg}/{sender_seg}-{stem_seg}-{ts_str}{extra}{clean_ext}"

    @staticmethod
    def _normalize_endpoint(raw_endpoint: str, default_secure: bool) -> tuple[str, bool]:
        """Chuẩn hóa endpoint có thể chứa scheme `http://` hoặc `https://` về dạng host:port."""
        cleaned = (raw_endpoint or "127.0.0.1:9000").strip()
        if cleaned.startswith(("http://", "https://")):
            parsed = urlparse(cleaned)
            return parsed.netloc or "127.0.0.1:9000", parsed.scheme == "https"
        return cleaned, default_secure

    def get_client(self) -> Minio:
        """Lấy hoặc khởi tạo thực thể `Minio` dùng chung từ cấu hình môi trường."""
        if self._client is None:
            endpoint, secure = self._normalize_endpoint(
                settings.MINIO_ENDPOINT,
                bool(settings.MINIO_SECURE),
            )
            self._client = Minio(
                endpoint=endpoint,
                access_key=settings.MINIO_ROOT_USER,
                secret_key=settings.MINIO_ROOT_PASSWORD,
                secure=secure,
            )
        return self._client

    def default_bucket(self) -> str:
        """Trả về tên bucket mặc định của hệ thống."""
        return (settings.MINIO_BUCKET_NAME or "vsico-zalo-files").strip()

    def ensure_bucket_exists(self, bucket_name: Optional[str] = None) -> str:
        """Đảm bảo bucket đích đã tồn tại trên MinIO; tự động tạo mới nếu chưa có."""
        bucket = (bucket_name or self.default_bucket()).strip()
        client = self.get_client()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("Đã khởi tạo bucket MinIO mới: %s", bucket)
        return bucket

    def upload_bytes(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        bucket_name: Optional[str] = None,
    ) -> MinIOUploadResult:
        """Tải mảng byte lên MinIO và trả về thông tin toàn vẹn SHA-256 kèm ETag."""
        bucket = self.ensure_bucket_exists(bucket_name)
        sha256_hex = hashlib.sha256(data).hexdigest()
        size_bytes = len(data)
        stream = io.BytesIO(data)
        result = self.get_client().put_object(
            bucket_name=bucket,
            object_name=object_key,
            data=stream,
            length=size_bytes,
            content_type=content_type or "application/octet-stream",
        )
        etag = (getattr(result, "etag", "") or "").strip('"')
        return MinIOUploadResult(
            bucket=bucket,
            object_key=object_key,
            size_bytes=size_bytes,
            sha256=sha256_hex,
            etag=etag,
        )

    def stat_object(
        self,
        object_key: str,
        bucket_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Kiểm tra sự tồn tại và lấy metadata thực tế của đối tượng trên MinIO."""
        bucket = (bucket_name or self.default_bucket()).strip()
        try:
            st = self.get_client().stat_object(bucket, object_key)
            return {
                "exists": True,
                "bucket": bucket,
                "object_key": object_key,
                "size_bytes": getattr(st, "size", None),
                "etag": (getattr(st, "etag", "") or "").strip('"') or None,
                "content_type": getattr(st, "content_type", None),
                "last_modified": (
                    st.last_modified.isoformat() if getattr(st, "last_modified", None) else None
                ),
            }
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchBucket", "NotFound"):
                return {
                    "exists": False,
                    "bucket": bucket,
                    "object_key": object_key,
                }
            raise

    def get_object_bytes(
        self,
        object_key: str,
        bucket_name: Optional[str] = None,
    ) -> bytes:
        """Tải nội dung nhị phân của một đối tượng từ MinIO S3."""
        bucket = (bucket_name or self.default_bucket()).strip()
        resp = self.get_client().get_object(bucket, object_key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def get_presigned_get_url(
        self,
        object_key: str,
        bucket_name: Optional[str] = None,
        expires_seconds: Optional[int] = None,
    ) -> str:
        """Sinh Presigned GET URL tạm thời để tải hoặc xem trước tệp trên MinIO."""
        bucket = (bucket_name or self.default_bucket()).strip()
        ttl = expires_seconds or int(settings.MINIO_PRESIGNED_EXPIRE_SECONDS or 3600)
        ttl = max(60, min(ttl, 7 * 24 * 3600))
        return self.get_client().presigned_get_object(
            bucket_name=bucket,
            object_name=object_key,
            expires=timedelta(seconds=ttl),
        )

    def delete_object(
        self,
        object_key: str,
        bucket_name: Optional[str] = None,
    ) -> bool:
        """Xóa một đối tượng khỏi MinIO; trả về True nếu đối tượng từng tồn tại và đã bị xóa."""
        bucket = (bucket_name or self.default_bucket()).strip()
        existed = bool(self.stat_object(object_key=object_key, bucket_name=bucket).get("exists"))
        if not existed:
            return False
        self.get_client().remove_object(bucket, object_key)
        return True

    def health_check(self) -> dict[str, Any]:
        """Kiểm tra tình trạng kết nối MinIO và khả năng truy cập bucket mặc định."""
        bucket = self.default_bucket()
        endpoint, secure = self._normalize_endpoint(
            settings.MINIO_ENDPOINT,
            bool(settings.MINIO_SECURE),
        )
        exists = self.get_client().bucket_exists(bucket)
        return {
            "connected": True,
            "endpoint": endpoint,
            "secure": secure,
            "bucket": bucket,
            "bucket_exists": bool(exists),
        }


minio_storage = MinIOStorageClient()
