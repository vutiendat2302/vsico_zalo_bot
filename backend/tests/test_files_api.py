"""Kiểm thử vòng đời quản lý tệp & MinIO Storage (`/api/files`): Upload, Query, URL, Delete (mysql | minio | both)."""

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.infrastructure.ai_service_client import AIOCRResult, AIServiceClient
from src.infrastructure.minio_client import MinIOUploadResult, minio_storage
from src.infrastructure.models import ActivityLog, FileRecord


class _InMemoryMinIO:
    """Giả lập kho lưu trữ MinIO S3 trong bộ nhớ phục vụ kiểm thử đơn vị cô lập."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}

    def upload_bytes(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        bucket_name: str | None = None,
    ) -> MinIOUploadResult:
        bucket = bucket_name or "vsico-zalo-files"
        sha = hashlib.sha256(data).hexdigest()
        etag = sha[:32]
        self.objects[(bucket, object_key)] = {
            "data": data,
            "content_type": content_type,
            "size_bytes": len(data),
            "etag": etag,
        }
        return MinIOUploadResult(
            bucket=bucket,
            object_key=object_key,
            size_bytes=len(data),
            sha256=sha,
            etag=etag,
        )

    def stat_object(self, object_key: str, bucket_name: str | None = None) -> dict:
        bucket = bucket_name or "vsico-zalo-files"
        entry = self.objects.get((bucket, object_key))
        if not entry:
            return {"exists": False, "bucket": bucket, "object_key": object_key}
        return {
            "exists": True,
            "bucket": bucket,
            "object_key": object_key,
            "size_bytes": entry["size_bytes"],
            "etag": entry["etag"],
            "content_type": entry["content_type"],
        }

    def get_presigned_get_url(
        self,
        object_key: str,
        bucket_name: str | None = None,
        expires_seconds: int | None = None,
    ) -> str:
        bucket = bucket_name or "vsico-zalo-files"
        ttl = expires_seconds or 3600
        return f"http://127.0.0.1:9000/{bucket}/{object_key}?X-Amz-Expires={ttl}"

    def delete_object(self, object_key: str, bucket_name: str | None = None) -> bool:
        bucket = bucket_name or "vsico-zalo-files"
        return self.objects.pop((bucket, object_key), None) is not None

    def get_object_bytes(self, object_key: str, bucket_name: str | None = None) -> bytes:
        bucket = bucket_name or "vsico-zalo-files"
        entry = self.objects.get((bucket, object_key))
        if not entry:
            raise KeyError(object_key)
        return entry["data"]

    def health_check(self) -> dict:
        return {
            "connected": True,
            "endpoint": "127.0.0.1:9000",
            "secure": False,
            "bucket": "vsico-zalo-files",
            "bucket_exists": True,
        }


def _patch_minio(monkeypatch) -> _InMemoryMinIO:
    """Thay thế các hàm gọi mạng của `minio_storage` bằng `_InMemoryMinIO`."""
    store = _InMemoryMinIO()
    monkeypatch.setattr(minio_storage, "upload_bytes", store.upload_bytes)
    monkeypatch.setattr(minio_storage, "stat_object", store.stat_object)
    monkeypatch.setattr(minio_storage, "get_presigned_get_url", store.get_presigned_get_url)
    monkeypatch.setattr(minio_storage, "get_object_bytes", store.get_object_bytes)
    monkeypatch.setattr(minio_storage, "delete_object", store.delete_object)
    monkeypatch.setattr(minio_storage, "health_check", store.health_check)
    return store


def test_files_upload_query_url_and_delete_both(
    api_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Kiểm thử quy trình Upload -> List -> Detail -> Presigned URL -> Delete cả MinIO và MySQL."""
    store = _patch_minio(monkeypatch)

    resp_health = api_client.get("/api/files/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["minio"]["connected"] is True

    sample_bytes = b"fake-png-content-for-vsico-minio-test"
    resp_up = api_client.post(
        "/api/files/upload",
        files={"file": ("lenh_dieu_xe.png", sample_bytes, "image/png")},
        data={
            "source_type": "MANUAL_UPLOAD",
            "group_name": "Nhóm Đội Xe Tuấn Hưng",
            "sender_name": "Phạm Tiến Hưng",
            "note": "Kiem thu Postman",
        },
    )
    assert resp_up.status_code == 201
    up_data = resp_up.json()
    f_info = up_data["file"]
    assert f_info["storage_status"] == "STORED"
    assert f_info["bucket"] == "vsico-zalo-files"
    assert f_info["object_key"].startswith("Nhom_Doi_Xe_Tuan_Hung/Pham_Tien_Hung-lenh_dieu_xe-")
    assert f_info["object_key"].endswith(".png")
    assert f_info["presigned_url"] is not None
    assert (f_info["bucket"], f_info["object_key"]) in store.objects

    # Lấy danh sách
    resp_list = api_client.get("/api/files", params={"search": f_info["file_key"]})
    assert resp_list.status_code == 200
    assert resp_list.json()["total"] == 1

    # Lấy chi tiết theo file_key
    resp_detail = api_client.get(f"/api/files/{f_info['file_key']}")
    assert resp_detail.status_code == 200
    detail_json = resp_detail.json()
    assert detail_json["file"]["minio_exists"] is True
    assert detail_json["minio_stat"]["size_bytes"] == len(sample_bytes)

    # Lấy URL theo Snowflake ID
    resp_url = api_client.get(f"/api/files/{f_info['id']}/url", params={"expires_seconds": 600})
    assert resp_url.status_code == 200
    assert "X-Amz-Expires=600" in resp_url.json()["presigned_url"]

    # Xóa cả MinIO và MySQL
    resp_del = api_client.delete(f"/api/files/{f_info['file_key']}", params={"scope": "both"})
    assert resp_del.status_code == 200
    del_json = resp_del.json()
    assert del_json["deleted_from_minio"] is True
    assert del_json["deleted_from_mysql"] is True
    assert (f_info["bucket"], f_info["object_key"]) not in store.objects
    assert db_session.scalar(select(FileRecord).where(FileRecord.id == int(f_info["id"]))) is None

    # Kiểm tra audit log ghi nhận upload và delete
    logs = db_session.scalars(
        select(ActivityLog).where(ActivityLog.entity_type == "file", ActivityLog.entity_id == f_info["id"])
    ).all()
    assert {log.action for log in logs} == {"FILE_UPLOADED", "FILE_DELETED"}


def test_files_delete_scope_mysql_only_and_minio_only(
    api_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Kiểm thử tách riêng phạm vi xóa: `scope=mysql` (giữ MinIO) và `scope=minio` (giữ metadata DELETED)."""
    store = _patch_minio(monkeypatch)

    # 1. Tạo tệp A và xóa chỉ trên MySQL (object MinIO phải còn nguyên)
    up_a = api_client.post(
        "/api/files/upload",
        files={"file": ("only_mysql_del.txt", b"alpha", "text/plain")},
    ).json()["file"]
    del_a = api_client.delete(f"/api/files/{up_a['file_key']}", params={"scope": "mysql"})
    assert del_a.status_code == 200
    assert del_a.json()["deleted_from_mysql"] is True
    assert del_a.json()["deleted_from_minio"] is False
    assert (up_a["bucket"], up_a["object_key"]) in store.objects
    assert db_session.scalar(select(FileRecord).where(FileRecord.id == int(up_a["id"]))) is None

    # 2. Tạo tệp B và xóa chỉ trên MinIO (bản ghi MySQL chuyển DELETED, /url báo 404)
    up_b = api_client.post(
        "/api/files/upload",
        files={"file": ("only_minio_del.txt", b"beta", "text/plain")},
    ).json()["file"]
    del_b = api_client.delete(f"/api/files/{up_b['file_key']}", params={"scope": "minio"})
    assert del_b.status_code == 200
    assert del_b.json()["deleted_from_minio"] is True
    assert del_b.json()["deleted_from_mysql"] is False
    assert del_b.json()["storage_status"] == "DELETED"
    assert (up_b["bucket"], up_b["object_key"]) not in store.objects

    rec_b = db_session.scalar(select(FileRecord).where(FileRecord.id == int(up_b["id"])))
    assert rec_b is not None
    assert rec_b.storage_status == "DELETED"
    assert rec_b.deleted_at is not None

    resp_url_b = api_client.get(f"/api/files/{up_b['file_key']}/url")
    assert resp_url_b.status_code == 404


def test_files_ocr_by_file_key_on_backend(
    api_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Kiểm thử chạy OCR trực tiếp từ Backend bằng mã `file_key` (doc_...) lưu trên MinIO."""
    _patch_minio(monkeypatch)
    captured: dict[str, object] = {}

    def _fake_perform_ocr(
        image_base64=None,
        image_url=None,
        file_key=None,
        lang="vi",
        force_vision=False,
    ) -> AIOCRResult:
        captured["image_base64"] = image_base64
        captured["lang"] = lang
        captured["force_vision"] = force_vision
        return AIOCRResult(
            engine="gemini_vision" if force_vision else "paddleocr",
            text="Xe15h00814/phạm tiến hưng/0332308336",
            confidence=0.95,
            lines=[{"text": "Xe15h00814/phạm tiến hưng/0332308336", "confidence": 0.95, "box": []}],
            has_text=True,
            layout_type="chat_screenshot",
            preprocessing_applied=["passthrough"],
            error=None,
        )

    monkeypatch.setattr(AIServiceClient, "perform_ocr", classmethod(lambda cls, **kw: _fake_perform_ocr(**kw)))

    up = api_client.post(
        "/api/files/upload",
        files={"file": ("lenh.png", b"png-bytes-sample", "image/png")},
    ).json()["file"]

    resp_ocr = api_client.post(
        f"/api/files/{up['file_key']}/ocr",
        json={"lang": "vi", "force_vision": True, "save_meta": True},
    )
    assert resp_ocr.status_code == 200
    body = resp_ocr.json()
    assert body["file_key"] == up["file_key"]
    assert body["ocr"]["engine"] == "gemini_vision"
    assert body["ocr"]["has_text"] is True
    assert captured["force_vision"] is True

    rec = db_session.scalar(select(FileRecord).where(FileRecord.file_key == up["file_key"]))
    assert rec is not None and rec.meta and rec.meta["ocr"]["engine"] == "gemini_vision"
    log = db_session.scalar(
        select(ActivityLog).where(ActivityLog.entity_id == up["id"], ActivityLog.action == "FILE_OCR_RUN")
    )
    assert log is not None
