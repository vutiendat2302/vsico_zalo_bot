"""Module API Quản Lý Tệp Tin & Lưu Trữ Đối Tượng MinIO S3 (Files Management API).

Cung cấp vòng đời quản lý tệp và tài liệu chuyên nghiệp gồm:
- `GET /api/files/health`: Kiểm tra kết nối MinIO S3, bucket mặc định và thống kê bảng `files`.
- `POST /api/files/upload`: Tải tệp lên MinIO (multipart/form-data), tính SHA-256 và lưu metadata vào MySQL.
- `GET /api/files`: Truy vấn danh sách tệp phân trang, tìm kiếm và lọc theo trạng thái/loại nguồn.
- `GET /api/files/{file_ref}`: Lấy chi tiết metadata theo Snowflake `id` hoặc `file_key`, đối soát MinIO và sinh URL tạm thời.
- `GET /api/files/{file_ref}/url`: Xin cấp mới `Presigned GET URL` tạm thời cùng `bucket`, `object_key`, `file_key`.
- `DELETE /api/files/{file_ref}`: Xóa tệp linh hoạt theo phạm vi (`mysql` | `minio` | `both`) và lưu nhật ký kiểm toán.
"""

import base64
from datetime import datetime, timezone
import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Cookie, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from minio.error import S3Error
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.schemas import (
    FileDeleteResponse,
    FileDetailResponse,
    FileItemOut,
    FileListResponse,
    FileOCRRequest,
    FileOCRResponse,
    FileUploadResponse,
    FileUrlResponse,
)
from src.config.settings import settings
from src.domain.enums import StorageStatus
from src.infrastructure.ai_service_client import AIServiceClient
from src.infrastructure.database import get_db
from src.infrastructure.minio_client import minio_storage
from src.infrastructure.models import ActivityLog, FileRecord, User, ZaloGroup, ZaloMessage
from src.infrastructure.security import decode_access_token, extract_token
from src.infrastructure.snowflake import snowflake

logger = logging.getLogger("nhaxe_bot.api.files")

router = APIRouter(prefix="/api/files", tags=["9. Quản Lý Tệp & MinIO Storage (Files)"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # Giới hạn 50MB cho mỗi lần tải lên API


def _resolve_actor_id(
    authorization: Optional[str] = Header(None),
    vsico_token: Optional[str] = Cookie(None),
) -> Optional[str]:
    """Trích xuất `actor_id` từ JWT nếu caller có gửi token, giữ `None` nếu gọi nội bộ/test."""
    token = extract_token(authorization=authorization, vsico_token=vsico_token)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    return str(sub) if sub is not None else None


def _find_file_record(db: Session, file_ref: str) -> FileRecord:
    """Tìm bản ghi `FileRecord` theo Snowflake `id` hoặc `file_key`."""
    ref = (file_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tệp tin.")

    record: Optional[FileRecord] = None
    if ref.isdigit():
        record = db.scalar(select(FileRecord).where(FileRecord.id == int(ref)))
    if record is None:
        record = db.scalar(select(FileRecord).where(FileRecord.file_key == ref))

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tệp tin với mã '{ref}'.",
        )
    return record


def _to_file_out(
    record: FileRecord,
    *,
    minio_exists: Optional[bool] = None,
    presigned_url: Optional[str] = None,
    presigned_expires_in: Optional[int] = None,
) -> FileItemOut:
    """Chuyển đổi thực thể `FileRecord` sang DTO `FileItemOut` chuẩn hóa Snowflake ID dạng chuỗi."""
    return FileItemOut(
        id=str(record.id),
        file_key=record.file_key,
        bucket=record.bucket,
        object_key=record.object_key,
        original_name=record.original_name,
        mime_type=record.mime_type,
        size_bytes=int(record.size_bytes),
        sha256=record.sha256,
        source_type=record.source_type,
        source_url=record.source_url,
        message_id=str(record.message_id) if record.message_id is not None else None,
        storage_status=record.storage_status,
        minio_exists=minio_exists,
        presigned_url=presigned_url,
        presigned_expires_in=presigned_expires_in,
        meta=record.meta,
        created_at=record.created_at,
        deleted_at=record.deleted_at,
    )


@router.get(
    "/health",
    summary="Kiểm tra kết nối MinIO S3 và thống kê bảng files",
    description="Kiểm tra khả năng kết nối tới MinIO endpoint, trạng thái bucket mặc định và đếm bản ghi trong bảng `files`.",
)
def files_health_check(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Kiểm tra tình trạng kết nối MinIO S3 và thống kê số lượng tệp trong MySQL."""
    try:
        minio_info = minio_storage.health_check()
    except Exception as exc:
        logger.warning("Kiểm tra sức khỏe MinIO thất bại: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Không thể kết nối máy chủ MinIO S3: {exc}",
        ) from exc

    rows = db.execute(
        select(FileRecord.storage_status, func.count(FileRecord.id)).group_by(FileRecord.storage_status)
    ).all()
    counts = {str(st): int(cnt) for st, cnt in rows}
    total = sum(counts.values())

    return {
        "ok": True,
        "minio": minio_info,
        "database_files": {
            "total": total,
            "by_status": counts,
        },
    }


@router.post(
    "/upload",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tải tệp lên MinIO và lưu metadata MySQL",
    description=(
        "Tải tệp lên MinIO S3 theo cấu trúc `<tên nhóm>/<tên người gửi>-<tên file>-<thời gian>`, "
        "tính SHA-256, lưu vào bảng `files` và trả về `file_key`, `object_key` cùng `presigned_url`."
    ),
)
async def upload_file(
    file: UploadFile = File(..., description="Tệp tin cần tải lên (multipart/form-data)"),
    source_type: str = Form("MANUAL_UPLOAD", description="Nguồn tệp: MANUAL_UPLOAD | ZALO_IMAGE | EXCEL_PLAN | DOCUMENT"),
    group_name: Optional[str] = Form(None, description="Tên nhóm hoặc ID nhóm làm thư mục lưu trong bucket"),
    sender_name: Optional[str] = Form(None, description="Tên người gửi đặt ở đầu tên tệp"),
    folder: Optional[str] = Form(None, description="Thư mục dự phòng nếu không truyền group_name"),
    message_id: Optional[str] = Form(None, description="ID tin nhắn Zalo liên kết (nếu có)"),
    note: Optional[str] = Form(None, description="Ghi chú bổ sung"),
    meta_json: Optional[str] = Form(None, description="Metadata JSON tùy chọn"),
    expires_seconds: Optional[int] = Form(None, description="Thời hạn Presigned URL trả về (giây)"),
    actor_id: Optional[str] = Depends(_resolve_actor_id),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Tải tệp lên MinIO S3 theo cấu trúc nhóm/người gửi và lưu metadata vào bảng `files`."""
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tệp tải lên bị rỗng (0 byte).",
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Kích thước tệp vượt quá giới hạn cho phép ({MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )

    parsed_message_id: Optional[int] = None
    linked_msg: Optional[ZaloMessage] = None
    if message_id and message_id.strip():
        try:
            parsed_message_id = int(message_id.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Trường message_id phải là số nguyên Snowflake hợp lệ.",
            ) from exc
        linked_msg = db.scalar(select(ZaloMessage).where(ZaloMessage.id == parsed_message_id))
        if linked_msg is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy tin nhắn Zalo có id '{parsed_message_id}'.",
            )

    resolved_group = (group_name or "").strip() or None
    if not resolved_group and linked_msg is not None:
        grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == linked_msg.group_id))
        resolved_group = (grp.name if grp and grp.name else linked_msg.group_id)
    if not resolved_group and folder and folder.strip():
        resolved_group = folder.strip()

    resolved_sender = (sender_name or "").strip() or None
    if not resolved_sender and linked_msg is not None:
        resolved_sender = linked_msg.sender_name or linked_msg.sender_id
    if not resolved_sender and actor_id and actor_id.isdigit():
        actor_user = db.scalar(select(User).where(User.id == int(actor_id)))
        if actor_user:
            resolved_sender = actor_user.full_name or actor_user.username

    extra_meta: dict[str, Any] = {}
    if meta_json and meta_json.strip():
        try:
            parsed_meta = json.loads(meta_json)
            if not isinstance(parsed_meta, dict):
                raise ValueError("meta_json phải là JSON object.")
            extra_meta.update(parsed_meta)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Trường meta_json không hợp lệ: {exc}",
            ) from exc
    if note and note.strip():
        extra_meta["note"] = note.strip()
    if resolved_group:
        extra_meta["group_name"] = resolved_group
    if resolved_sender:
        extra_meta["sender_name"] = resolved_sender

    new_id = snowflake.generate()
    mime_type = (file.content_type or "application/octet-stream").strip()[:100]
    clean_source_type = (source_type or "MANUAL_UPLOAD").strip().upper()[:32]
    object_key = minio_storage.build_object_key(
        group_name=resolved_group,
        sender_name=resolved_sender,
        original_filename=file.filename,
        mime_type=mime_type,
    )
    try:
        if minio_storage.stat_object(object_key).get("exists"):
            object_key = minio_storage.build_object_key(
                group_name=resolved_group,
                sender_name=resolved_sender,
                original_filename=file.filename,
                mime_type=mime_type,
                suffix=str(new_id)[-6:],
            )
    except Exception:
        pass

    try:
        uploaded = minio_storage.upload_bytes(
            object_key=object_key,
            data=content,
            content_type=mime_type,
        )
    except Exception as exc:
        logger.exception("Lỗi khi tải tệp lên MinIO S3")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không thể tải tệp lên MinIO S3: {exc}",
        ) from exc

    file_key = f"doc_{new_id}_{uploaded.sha256[:12]}"
    extra_meta["etag"] = uploaded.etag

    record = FileRecord(
        id=new_id,
        file_key=file_key,
        bucket=uploaded.bucket,
        object_key=uploaded.object_key,
        original_name=(file.filename or "uploaded_file.bin")[:255],
        mime_type=mime_type,
        size_bytes=uploaded.size_bytes,
        sha256=uploaded.sha256,
        source_type=clean_source_type,
        source_url=None,
        message_id=parsed_message_id,
        storage_status=StorageStatus.STORED.value,
        meta=extra_meta,
    )

    try:
        db.add(record)
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=actor_id,
                action="FILE_UPLOADED",
                entity_type="file",
                entity_id=str(record.id),
                details={
                    "file_key": record.file_key,
                    "bucket": record.bucket,
                    "object_key": record.object_key,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                    "source_type": record.source_type,
                },
            )
        )
        db.commit()
        db.refresh(record)
    except Exception as exc:
        db.rollback()
        # Hoàn tác đối tượng đã đẩy lên MinIO để tránh sinh tệp mồ côi khi ghi DB thất bại
        try:
            minio_storage.delete_object(uploaded.object_key, uploaded.bucket)
        except Exception:
            logger.warning("Không thể hoàn tác đối tượng MinIO '%s' sau lỗi DB", uploaded.object_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi lưu metadata tệp vào MySQL: {exc}",
        ) from exc

    ttl = expires_seconds or int(settings.MINIO_PRESIGNED_EXPIRE_SECONDS or 3600)
    ttl = max(60, min(ttl, 7 * 24 * 3600))
    presigned_url = minio_storage.get_presigned_get_url(
        object_key=record.object_key,
        bucket_name=record.bucket,
        expires_seconds=ttl,
    )

    return FileUploadResponse(
        ok=True,
        message="Tải tệp lên MinIO và lưu metadata MySQL thành công.",
        file=_to_file_out(
            record,
            minio_exists=True,
            presigned_url=presigned_url,
            presigned_expires_in=ttl,
        ),
    )


@router.get(
    "",
    response_model=FileListResponse,
    summary="Danh sách tệp tin và metadata lưu trữ",
    description="Truy xuất danh sách tệp trong bảng `files` có phân trang, tìm kiếm và lọc theo `storage_status` hoặc `source_type`.",
)
def list_files(
    page: int = Query(1, ge=1, description="Số trang hiện tại"),
    page_size: int = Query(20, ge=1, le=100, description="Số bản ghi mỗi trang"),
    storage_status: Optional[str] = Query(None, description="Lọc theo trạng thái: PENDING | STORED | FAILED | DELETED"),
    source_type: Optional[str] = Query(None, description="Lọc theo loại nguồn tệp"),
    search: Optional[str] = Query(None, description="Tìm theo file_key, object_key, original_name hoặc sha256"),
    include_deleted: bool = Query(False, description="Bao gồm cả các bản ghi đã đánh dấu DELETED"),
    include_presigned_url: bool = Query(False, description="Tự động sinh Presigned URL cho các tệp STORED"),
    db: Session = Depends(get_db),
) -> FileListResponse:
    """Liệt kê danh sách tệp tin kèm phân trang và tùy chọn sinh nhanh Presigned URL."""
    query = select(FileRecord)

    if storage_status:
        query = query.where(FileRecord.storage_status == storage_status.strip().upper())
    elif not include_deleted:
        query = query.where(FileRecord.storage_status != StorageStatus.DELETED.value)

    if source_type:
        query = query.where(FileRecord.source_type == source_type.strip().upper())

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                FileRecord.file_key.ilike(pattern),
                FileRecord.object_key.ilike(pattern),
                FileRecord.original_name.ilike(pattern),
                FileRecord.sha256.ilike(pattern),
            )
        )

    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(
        query.order_by(FileRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    ttl = int(settings.MINIO_PRESIGNED_EXPIRE_SECONDS or 3600)
    items: list[FileItemOut] = []
    for rec in rows:
        url: Optional[str] = None
        exp: Optional[int] = None
        if include_presigned_url and rec.storage_status != StorageStatus.DELETED.value:
            try:
                url = minio_storage.get_presigned_get_url(
                    object_key=rec.object_key,
                    bucket_name=rec.bucket,
                    expires_seconds=ttl,
                )
                exp = ttl
            except Exception as exc:
                logger.warning("Không thể sinh Presigned URL cho '%s': %s", rec.object_key, exc)
        items.append(_to_file_out(rec, presigned_url=url, presigned_expires_in=exp))

    return FileListResponse(
        ok=True,
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get(
    "/{file_ref}",
    response_model=FileDetailResponse,
    summary="Lấy thông tin chi tiết tệp tin và đối soát MinIO",
    description="Truy vấn metadata từ MySQL theo Snowflake `id` hoặc `file_key`, đồng thời kiểm tra tồn tại thực tế trên MinIO và sinh Presigned URL tạm thời.",
)
def get_file_detail(
    file_ref: str,
    verify_minio: bool = Query(True, description="Gọi stat_object lên MinIO để kiểm tra đối tượng thực tế"),
    include_url: bool = Query(True, description="Sinh kèm Presigned URL tạm thời"),
    expires_seconds: Optional[int] = Query(None, ge=60, le=604800, description="Thời hạn URL (giây)"),
    db: Session = Depends(get_db),
) -> FileDetailResponse:
    """Lấy thông tin chi tiết của một tệp tin kèm trạng thái MinIO và Presigned URL."""
    record = _find_file_record(db, file_ref)
    minio_stat: Optional[dict[str, Any]] = None
    minio_exists: Optional[bool] = None

    if verify_minio:
        try:
            minio_stat = minio_storage.stat_object(
                object_key=record.object_key,
                bucket_name=record.bucket,
            )
            minio_exists = bool(minio_stat.get("exists"))
        except S3Error as exc:
            logger.warning("Lỗi đối soát MinIO cho '%s': %s", record.object_key, exc)
            minio_stat = {"exists": False, "error": str(exc)}
            minio_exists = False
        except Exception as exc:
            logger.warning("Không thể kết nối MinIO để đối soát '%s': %s", record.object_key, exc)
            minio_stat = {"exists": False, "error": str(exc)}

    url: Optional[str] = None
    ttl_used: Optional[int] = None
    can_sign = record.storage_status != StorageStatus.DELETED.value and (minio_exists is not False)
    if include_url and can_sign:
        ttl_used = expires_seconds or int(settings.MINIO_PRESIGNED_EXPIRE_SECONDS or 3600)
        ttl_used = max(60, min(ttl_used, 7 * 24 * 3600))
        try:
            url = minio_storage.get_presigned_get_url(
                object_key=record.object_key,
                bucket_name=record.bucket,
                expires_seconds=ttl_used,
            )
        except Exception as exc:
            logger.warning("Không thể sinh Presigned URL cho '%s': %s", record.object_key, exc)
            ttl_used = None

    return FileDetailResponse(
        ok=True,
        file=_to_file_out(
            record,
            minio_exists=minio_exists,
            presigned_url=url,
            presigned_expires_in=ttl_used,
        ),
        minio_stat=minio_stat,
    )


@router.get(
    "/{file_ref}/url",
    response_model=FileUrlResponse,
    summary="Lấy khóa đối tượng và sinh Presigned URL tạm thời",
    description="Kiểm tra đối tượng còn tồn tại trên MinIO rồi trả về `bucket`, `object_key`, `file_key` và `presigned_url`.",
)
def get_file_presigned_url(
    file_ref: str,
    expires_seconds: Optional[int] = Query(None, ge=60, le=604800, description="Thời hạn hiệu lực của URL (giây)"),
    db: Session = Depends(get_db),
) -> FileUrlResponse:
    """Sinh Presigned GET URL tạm thời để tải hoặc xem trước tệp trên MinIO."""
    record = _find_file_record(db, file_ref)
    if record.storage_status == StorageStatus.DELETED.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tệp '{record.file_key}' đã bị đánh dấu xóa khỏi kho lưu trữ.",
        )

    try:
        st = minio_storage.stat_object(object_key=record.object_key, bucket_name=record.bucket)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không thể kiểm tra đối tượng trên MinIO: {exc}",
        ) from exc

    if not st.get("exists"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Đối tượng '{record.object_key}' không tồn tại trên MinIO (có thể đã bị xóa riêng trên MinIO).",
        )

    ttl = expires_seconds or int(settings.MINIO_PRESIGNED_EXPIRE_SECONDS or 3600)
    ttl = max(60, min(ttl, 7 * 24 * 3600))
    url = minio_storage.get_presigned_get_url(
        object_key=record.object_key,
        bucket_name=record.bucket,
        expires_seconds=ttl,
    )

    return FileUrlResponse(
        ok=True,
        id=str(record.id),
        file_key=record.file_key,
        bucket=record.bucket,
        object_key=record.object_key,
        presigned_url=url,
        expires_in_seconds=ttl,
    )


@router.post(
    "/{file_ref}/ocr",
    response_model=FileOCRResponse,
    summary="Chạy OCR trực tiếp cho tệp đã lưu trên MinIO theo id hoặc file_key",
    description=(
        "Backend tự tra cứu bản ghi `files` trong MySQL theo Snowflake `id` hoặc `file_key` (dạng `doc_...`), "
        "tải nội dung tệp từ MinIO S3 rồi gửi sang `ai-service` `/api/v1/ocr` và trả về kết quả chuẩn `OCRResponse`."
    ),
)
def run_ocr_for_file(
    file_ref: str,
    payload: FileOCRRequest = Body(default_factory=FileOCRRequest),
    actor_id: Optional[str] = Depends(_resolve_actor_id),
    db: Session = Depends(get_db),
) -> FileOCRResponse:
    """Thực thi OCR trên ảnh đã lưu trong MinIO bằng `id` hoặc `file_key` từ MySQL."""
    record = _find_file_record(db, file_ref)
    if record.storage_status == StorageStatus.DELETED.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tệp '{record.file_key}' đã bị đánh dấu xóa khỏi kho lưu trữ.",
        )

    try:
        st = minio_storage.stat_object(object_key=record.object_key, bucket_name=record.bucket)
        if not st.get("exists"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Đối tượng '{record.object_key}' không còn tồn tại trên MinIO.",
            )
        raw_bytes = minio_storage.get_object_bytes(
            object_key=record.object_key,
            bucket_name=record.bucket,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không thể đọc tệp từ MinIO S3: {exc}",
        ) from exc

    b64_img = base64.b64encode(raw_bytes).decode("ascii")
    ocr_res = AIServiceClient.perform_ocr(
        image_base64=b64_img,
        lang=payload.lang,
        force_vision=payload.force_vision,
    )
    if ocr_res is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Không thể nhận kết quả OCR từ ai-service (dịch vụ tạm thời không khả dụng hoặc OCR đang tắt).",
        )

    ocr_dict: dict[str, Any] = {
        "engine": ocr_res.engine,
        "text": ocr_res.text,
        "confidence": ocr_res.confidence,
        "lines": ocr_res.lines,
        "has_text": ocr_res.has_text,
        "layout_type": ocr_res.layout_type,
        "preprocessing_applied": ocr_res.preprocessing_applied,
        "error": ocr_res.error,
    }

    if payload.save_meta:
        new_meta = dict(record.meta or {})
        new_meta["ocr"] = {
            "engine": ocr_res.engine,
            "confidence": ocr_res.confidence,
            "has_text": ocr_res.has_text,
            "layout_type": ocr_res.layout_type,
            "text_preview": ocr_res.text[:500],
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }
        record.meta = new_meta
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=actor_id,
                action="FILE_OCR_RUN",
                entity_type="file",
                entity_id=str(record.id),
                details={
                    "file_key": record.file_key,
                    "object_key": record.object_key,
                    "engine": ocr_res.engine,
                    "force_vision": payload.force_vision,
                    "has_text": ocr_res.has_text,
                    "confidence": ocr_res.confidence,
                },
            )
        )
        db.commit()

    return FileOCRResponse(
        ok=True,
        id=str(record.id),
        file_key=record.file_key,
        bucket=record.bucket,
        object_key=record.object_key,
        ocr=ocr_dict,
    )


@router.delete(
    "/{file_ref}",
    response_model=FileDeleteResponse,
    summary="Xóa tệp theo phạm vi (MySQL, MinIO hoặc cả hai)",
    description=(
        "Hỗ trợ 3 chế độ xóa chuyên nghiệp: "
        "`scope=both` (xóa trên MinIO và MySQL), "
        "`scope=mysql` (chỉ xóa metadata trong MySQL, giữ lại file trên MinIO), "
        "`scope=minio` (chỉ xóa object trên MinIO, cập nhật trạng thái DELETED trong MySQL)."
    ),
)
def delete_file(
    file_ref: str,
    scope: Literal["both", "mysql", "minio"] = Query(
        "both",
        description="Phạm vi xóa: both (cả MinIO và MySQL) | mysql (chỉ DB) | minio (chỉ object MinIO)",
    ),
    soft_delete: bool = Query(
        False,
        description="Nếu True khi xóa MySQL sẽ đánh dấu storage_status='DELETED' thay vì xóa hẳn bản ghi",
    ),
    actor_id: Optional[str] = Depends(_resolve_actor_id),
    db: Session = Depends(get_db),
) -> FileDeleteResponse:
    """Xóa tệp khỏi MySQL, MinIO S3 hoặc cả hai và ghi nhận nhật ký kiểm toán."""
    record = _find_file_record(db, file_ref)
    rec_id_str = str(record.id)
    file_key = record.file_key
    bucket = record.bucket
    object_key = record.object_key

    deleted_from_minio = False
    deleted_from_mysql = False
    resulting_status = record.storage_status

    if scope in ("both", "minio"):
        try:
            deleted_from_minio = minio_storage.delete_object(
                object_key=object_key,
                bucket_name=bucket,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Không thể xóa đối tượng trên MinIO S3: {exc}",
            ) from exc

    if scope == "minio":
        record.storage_status = StorageStatus.DELETED.value
        record.deleted_at = datetime.now(timezone.utc)
        resulting_status = StorageStatus.DELETED.value
    elif scope in ("both", "mysql"):
        if soft_delete:
            record.storage_status = StorageStatus.DELETED.value
            record.deleted_at = datetime.now(timezone.utc)
            resulting_status = StorageStatus.DELETED.value
        else:
            db.delete(record)
            deleted_from_mysql = True
            resulting_status = StorageStatus.DELETED.value

    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=actor_id,
            action="FILE_DELETED",
            entity_type="file",
            entity_id=rec_id_str,
            details={
                "scope": scope,
                "soft_delete": soft_delete,
                "file_key": file_key,
                "bucket": bucket,
                "object_key": object_key,
                "deleted_from_minio": deleted_from_minio,
                "deleted_from_mysql": deleted_from_mysql,
            },
        )
    )
    db.commit()

    scope_messages = {
        "both": "Đã thực hiện xóa tệp trên cả MinIO S3 và MySQL.",
        "mysql": "Đã thực hiện xóa metadata tệp trên MySQL (giữ nguyên đối tượng trên MinIO S3).",
        "minio": "Đã xóa đối tượng trên MinIO S3 và đánh dấu DELETED trong MySQL.",
    }

    return FileDeleteResponse(
        ok=True,
        scope=scope,
        soft_delete=soft_delete,
        id=rec_id_str,
        file_key=file_key,
        bucket=bucket,
        object_key=object_key,
        deleted_from_minio=deleted_from_minio,
        deleted_from_mysql=deleted_from_mysql,
        storage_status=resulting_status,
        message=scope_messages[scope],
    )
