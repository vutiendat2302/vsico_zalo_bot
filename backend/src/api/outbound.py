"""Module API Quản lý Kết quả Tin nhắn & Thông báo Gửi đi (Outbound Messages & Results API).

Phục vụ giao diện Quản trị và Điều hành vận tải (ĐHVT) theo dõi kết quả tin nhắn:
- Tin nhắn thông báo gửi khách hàng đã gửi (da_gui).
- Tin nhắn thông báo đang chờ duyệt (cho_duyet).
- Tin nhắn thông báo bị hủy (huy).
- Tin nhắn gửi thất bại do lỗi Zalo OA hoặc mạng (that_bai).
- Thao tác: Duyệt gửi (Approve), Hủy gửi (Cancel), Gửi lại (Resend), Thống kê tổng hợp.
"""

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from src.config.settings import settings
from src.domain.enums import (
    MessageStatus,
    OrderType,
    OutboundStatus,
    ReviewStatus,
    RoutingStatus,
    TmsSyncStatus,
    ValidationStatus,
)
from src.infrastructure.database import get_db
from src.infrastructure.models import (
    ActivityLog,
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TruckRecord,
    User,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.security import get_optional_current_user
from src.infrastructure.snowflake import snowflake

outbound_router = APIRouter(prefix="/api/outbound", tags=["Outbound Messages & Results"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CancelRequest(BaseModel):
    """Payload yêu cầu hủy tin nhắn gửi đi."""
    reason: Optional[str] = Field(default="Điều độ viên hủy lệnh điều xe.", description="Lý do hủy tin nhắn")


class OutboundContainerInfo(BaseModel):
    """Thông tin Container gắn với tin nhắn gửi đi."""
    container_no: Optional[str] = None
    truck_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    seal_no: Optional[str] = None
    plan_date: Optional[str] = None


class OutboundMessageItemResponse(BaseModel):
    """Chi tiết một tin nhắn thông báo kết quả gửi đi."""
    id: int
    target_group_id: int
    target_group_name: Optional[str] = None
    target_zalo_group_id: Optional[str] = None
    order_type: str
    message_kind: str
    content: str
    idempotency_key: str
    review_zalo_msg_id: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    status: str
    attempt_count: int
    zalo_message_id: Optional[str] = None
    last_error: Optional[str] = None
    created_at: str
    sent_at: Optional[str] = None
    containers: list[OutboundContainerInfo] = []


class OutboundSummaryResponse(BaseModel):
    """Thống kê tổng hợp số lượng kết quả tin nhắn."""
    ok: bool = True
    total: int = 0
    da_gui: int = 0
    cho_duyet: int = 0
    huy: int = 0
    that_bai: int = 0
    bo_qua_trung_lap: int = 0


@outbound_router.get("/summary", response_model=OutboundSummaryResponse)
def get_outbound_summary(db: Session = Depends(get_db)) -> OutboundSummaryResponse:
    """Lấy thống kê số lượng tin nhắn kết quả theo từng trạng thái.

    Returns:
        OutboundSummaryResponse: Thống kê số lượng `da_gui`, `cho_duyet`, `huy`, `that_bai`, `bo_qua_trung_lap`.
    """
    total = db.scalar(select(func.count(OutboundMessage.id))) or 0
    da_gui = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_([OutboundStatus.SENT.value, "da_gui"])
        )
    ) or 0
    cho_duyet = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_([OutboundStatus.PENDING_APPROVAL.value, "cho_duyet"])
        )
    ) or 0
    huy = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_([OutboundStatus.CANCELLED.value, "huy"])
        )
    ) or 0
    that_bai = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_([OutboundStatus.FAILED.value, "that_bai"])
        )
    ) or 0
    bo_qua_trung_lap = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_([OutboundStatus.IGNORED_DUPLICATE.value, "bo_qua_trung_lap"])
        )
    ) or 0

    return OutboundSummaryResponse(
        ok=True,
        total=total,
        da_gui=da_gui,
        cho_duyet=cho_duyet,
        huy=huy,
        that_bai=that_bai,
        bo_qua_trung_lap=bo_qua_trung_lap,
    )


_OUTBOUND_STATUS_FILTER_MAP: dict[str, list[str]] = {
    "sent": [OutboundStatus.SENT.value, "da_gui", "SENT"],
    "da_gui": [OutboundStatus.SENT.value, "da_gui", "SENT"],
    "pending_approval": [OutboundStatus.PENDING_APPROVAL.value, "cho_duyet", "PENDING_APPROVAL"],
    "cho_duyet": [OutboundStatus.PENDING_APPROVAL.value, "cho_duyet", "PENDING_APPROVAL"],
    "pending_send": [OutboundStatus.PENDING_SEND.value, "PENDING_SEND"],
    "sending": [OutboundStatus.SENDING.value, "SENDING"],
    "cancelled": [OutboundStatus.CANCELLED.value, "huy", "CANCELLED"],
    "huy": [OutboundStatus.CANCELLED.value, "huy", "CANCELLED"],
    "failed": [OutboundStatus.FAILED.value, "that_bai", "FAILED"],
    "that_bai": [OutboundStatus.FAILED.value, "that_bai", "FAILED"],
    "ignored_duplicate": [OutboundStatus.IGNORED_DUPLICATE.value, "bo_qua_trung_lap", "IGNORED_DUPLICATE"],
    "bo_qua_trung_lap": [OutboundStatus.IGNORED_DUPLICATE.value, "bo_qua_trung_lap", "IGNORED_DUPLICATE"],
}

_ORDER_TYPE_FILTER_MAP: dict[str, list[str]] = {
    "load": [OrderType.LOAD.value, "dong", "load", "xuat"],
    "dong": [OrderType.LOAD.value, "dong", "load", "xuat"],
    "xuat": [OrderType.LOAD.value, "dong", "load", "xuat"],
    "return": [OrderType.RETURN.value, "tra", "return", "nhap"],
    "tra": [OrderType.RETURN.value, "tra", "return", "nhap"],
    "nhap": [OrderType.RETURN.value, "tra", "return", "nhap"],
}


def _parse_filter_dt(raw: str, end_of_day: bool = False) -> Optional[datetime]:
    """Chuyển đổi chuỗi ngày hoặc ISO-8601 từ query filter sang datetime."""
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if end_of_day and len(cleaned) == 10:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return dt
    except ValueError:
        return None


@outbound_router.get("/messages")
def list_outbound_messages(
    status: Optional[str] = Query(default=None, description="Trạng thái: all, PENDING_APPROVAL, SENT, CANCELLED, FAILED"),
    order_type: Optional[str] = Query(default=None, description="Loại lệnh: LOAD/dong, RETURN/tra"),
    search: Optional[str] = Query(default=None, description="Tìm kiếm theo nội dung, cont, biển số, tài xế, nhóm"),
    from_time: Optional[str] = Query(default=None, description="Từ thời điểm (YYYY-MM-DD hoặc ISO-8601)"),
    to_time: Optional[str] = Query(default=None, description="Đến thời điểm (YYYY-MM-DD hoặc ISO-8601)"),
    limit: int = Query(default=50, ge=1, le=200, description="Số lượng bản ghi mỗi trang"),
    offset: int = Query(default=0, ge=0, description="Vị trí bắt đầu"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lấy danh sách tin nhắn kết quả gửi đi có phân trang và bộ lọc chuyên sâu."""
    stmt = (
        select(OutboundMessage)
        .options(
            joinedload(OutboundMessage.target_group),
            selectinload(OutboundMessage.items).joinedload(OutboundMessageItem.container_job),
        )
    )

    if status and status.strip().lower() != "all":
        key = status.strip().lower()
        status_values = _OUTBOUND_STATUS_FILTER_MAP.get(key)
        if not status_values:
            raise HTTPException(status_code=400, detail=f"Trạng thái lọc không hợp lệ: {status}")
        stmt = stmt.where(OutboundMessage.status.in_(status_values))

    if order_type and order_type.strip().lower() != "all":
        key = order_type.strip().lower()
        order_values = _ORDER_TYPE_FILTER_MAP.get(key)
        if not order_values:
            raise HTTPException(status_code=400, detail=f"Loại lệnh lọc không hợp lệ: {order_type}")
        stmt = stmt.where(OutboundMessage.order_type.in_(order_values))

    if search and search.strip():
        search_kw = f"%{search.strip()}%"
        group_match = exists(
            select(ZaloGroup.id).where(
                ZaloGroup.id == OutboundMessage.target_group_id,
                or_(
                    ZaloGroup.name.ilike(search_kw),
                    ZaloGroup.zalo_group_id.ilike(search_kw),
                ),
            )
        )
        cont_match = exists(
            select(OutboundMessageItem.outbound_message_id)
            .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
            .outerjoin(TruckRecord, TruckRecord.id == ContainerJob.truck_record_id)
            .where(
                OutboundMessageItem.outbound_message_id == OutboundMessage.id,
                or_(
                    ContainerJob.container_no.ilike(search_kw),
                    ContainerJob.seal_no.ilike(search_kw),
                    TruckRecord.truck_plate.ilike(search_kw),
                    TruckRecord.driver_name.ilike(search_kw),
                    TruckRecord.driver_phone.ilike(search_kw),
                ),
            )
        )
        stmt = stmt.where(
            or_(
                OutboundMessage.content.ilike(search_kw),
                OutboundMessage.idempotency_key.ilike(search_kw),
                OutboundMessage.approved_by.ilike(search_kw),
                group_match,
                cont_match,
            )
        )

    if from_time:
        from_dt = _parse_filter_dt(from_time, end_of_day=False)
        if from_dt:
            stmt = stmt.where(OutboundMessage.created_at >= from_dt)

    if to_time:
        to_dt = _parse_filter_dt(to_time, end_of_day=True)
        if to_dt:
            stmt = stmt.where(OutboundMessage.created_at <= to_dt)

    # Tổng số bản ghi khớp
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = db.scalar(count_stmt) or 0

    # Lấy dữ liệu phân trang
    stmt = stmt.order_by(OutboundMessage.created_at.desc(), OutboundMessage.id.desc()).offset(offset).limit(limit)
    rows = list(db.scalars(stmt).unique().all())

    serialized: list[dict[str, Any]] = []
    for r in rows:
        containers_info: list[dict[str, Any]] = []
        for it in r.items:
            job = it.container_job
            if job:
                # Tìm xe liên kết nếu có
                truck_plate = None
                driver_name = None
                driver_phone = None
                if job.truck_record_id:
                    truck = db.get(TruckRecord, job.truck_record_id)
                    if truck:
                        truck_plate = truck.truck_plate
                        driver_name = truck.driver_name
                        driver_phone = truck.driver_phone

                containers_info.append({
                    "container_no": job.container_no,
                    "truck_plate": truck_plate,
                    "driver_name": driver_name,
                    "driver_phone": driver_phone,
                    "seal_no": job.seal_no,
                    "plan_date": (job.raw_fields or {}).get("plan_date") or (job.created_at.date().isoformat() if job.created_at else None),
                })

        group_name = r.target_group.name if r.target_group else None
        zalo_gid = r.target_group.zalo_group_id if r.target_group else None

        serialized.append({
            "id": str(r.id),
            "target_group_id": str(r.target_group_id),
            "target_group_name": group_name or f"Nhóm Zalo #{r.target_group_id}",
            "target_zalo_group_id": zalo_gid,
            "order_type": r.order_type,
            "message_kind": r.message_kind,
            "content": r.content,
            "idempotency_key": r.idempotency_key,
            "review_zalo_msg_id": r.review_zalo_msg_id,
            "approved_by": r.approved_by,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "status": r.status,
            "attempt_count": r.attempt_count,
            "zalo_message_id": r.zalo_message_id,
            "last_error": r.last_error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "containers": containers_info,
        })

    return {
        "ok": True,
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "messages": serialized,
    }


@outbound_router.get("/messages/{message_id}")
def get_outbound_message_detail(message_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Xem chi tiết một tin nhắn kết quả gửi đi."""
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả yêu cầu.")

    containers_info: list[dict[str, Any]] = []
    for it in msg.items:
        job = it.container_job
        if job:
            truck_plate = None
            driver_name = None
            driver_phone = None
            if job.truck_record_id:
                truck = db.get(TruckRecord, job.truck_record_id)
                if truck:
                    truck_plate = truck.truck_plate
                    driver_name = truck.driver_name
                    driver_phone = truck.driver_phone

            containers_info.append({
                "container_no": job.container_no,
                "truck_plate": truck_plate,
                "driver_name": driver_name,
                "driver_phone": driver_phone,
                "seal_no": job.seal_no,
                "plan_date": (job.raw_fields or {}).get("plan_date") or (job.created_at.date().isoformat() if job.created_at else None),
            })

    group_name = msg.target_group.name if msg.target_group else None
    zalo_gid = msg.target_group.zalo_group_id if msg.target_group else None

    return {
        "ok": True,
        "message": {
            "id": str(msg.id),
            "target_group_id": str(msg.target_group_id),
            "target_group_name": group_name or f"Nhóm Zalo #{msg.target_group_id}",
            "target_zalo_group_id": zalo_gid,
            "order_type": msg.order_type,
            "message_kind": msg.message_kind,
            "content": msg.content,
            "idempotency_key": msg.idempotency_key,
            "review_zalo_msg_id": msg.review_zalo_msg_id,
            "approved_by": msg.approved_by,
            "approved_at": msg.approved_at.isoformat() if msg.approved_at else None,
            "status": msg.status,
            "attempt_count": msg.attempt_count,
            "zalo_message_id": msg.zalo_message_id,
            "last_error": msg.last_error,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
            "containers": containers_info,
        }
    }


class OutboundApprovePayload(BaseModel):
    """Schema tùy chọn khi ĐHVT chỉnh sửa nội dung trước khi duyệt gửi khách."""

    content: Optional[str] = Field(default=None, description="Nội dung thông báo đã chỉnh sửa")
    operator_name: Optional[str] = Field(default=None, description="Tên người duyệt")


@outbound_router.post("/messages/{message_id}/approve")
def approve_outbound_message(
    message_id: int,
    operator_name: str = Query(default="Điều độ viên", description="Tên người phê duyệt"),
    payload: Optional[OutboundApprovePayload] = Body(default=None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phê duyệt tin nhắn đang ở trạng thái 'cho_duyet' (cho phép sửa nội dung) và kích hoạt phát hành."""
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả.")

    if msg.status in (OutboundStatus.SENT.value, "da_gui"):
        return {"ok": True, "status": OutboundStatus.SENT.value, "message": "Tin nhắn này đã được gửi trước đó."}

    if msg.status not in ("PENDING_APPROVAL", "cho_duyet"):
        raise HTTPException(409, "Tin nhắn không còn ở trạng thái chờ duyệt.")

    actor = (
        current_user.username
        if current_user
        else ((payload.operator_name.strip() if payload and payload.operator_name else None) or operator_name)
    )
    edited_content = False
    if payload and payload.content is not None:
        cleaned_content = payload.content.strip()
        if not cleaned_content:
            raise HTTPException(status_code=400, detail="Nội dung thông báo sau khi sửa không được để trống.")
        if cleaned_content != msg.content:
            msg.content = cleaned_content
            edited_content = True

    now = _utc_now()
    msg.status = OutboundStatus.PENDING_SEND.value
    msg.approved_by = actor
    msg.approved_at = now
    msg.sent_at = None
    msg.last_error = None

    # Đồng bộ trạng thái ContainerJob, ReviewCase và ZaloMessage
    parent_msg_ids: set[int] = set()
    for item in msg.items:
        if item.container_job:
            cj = item.container_job
            cj.validation_status = ValidationStatus.VALID.value
            cj.routing_status = RoutingStatus.ROUTED.value
            cj.tms_sync_status = TmsSyncStatus.PENDING.value
            if cj.message_id:
                parent_msg_ids.add(cj.message_id)

            # Cập nhật review_cases liên quan đến container này
            for rc in db.scalars(
                select(ReviewCase).where(
                    ReviewCase.container_job_id == cj.id,
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                )
            ).all():
                rc.status = ReviewStatus.APPROVED.value
                rc.resolved_at = now
                rc.resolved_by = actor

    # Cập nhật trạng thái tin nhắn gốc (ZaloMessage) sang 'processed' nếu không còn ca pending
    for mid in parent_msg_ids:
        remaining_pending = db.scalar(
            select(func.count(ReviewCase.id)).where(
                ReviewCase.message_id == mid,
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
            )
        ) or 0
        if remaining_pending == 0:
            z_msg = db.get(ZaloMessage, mid)
            if z_msg:
                z_msg.processing_status = MessageStatus.PROCESSED.value

    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=str(current_user.id) if current_user else actor,
            action="OUTBOUND_APPROVED_WITH_EDIT" if edited_content else "OUTBOUND_APPROVED",
            entity_type="outbound_message",
            entity_id=str(msg.id),
            details={"edited_content": edited_content, "approved_by": actor},
        )
    )
    db.commit()

    target_grp = msg.target_group
    if target_grp and not target_grp.is_test and settings.AUTO_DISPATCH_OUTBOUND:
        from src.infrastructure.outbox_worker import drain_outbox

        drain_outbox(lambda: nullcontext(db), [msg.id])

    db.refresh(msg)
    return {
        "ok": True,
        "message": (
            f"Đã phê duyệt và gửi thành công tin nhắn #{message_id}."
            if msg.status == OutboundStatus.SENT.value
            else f"Đã phê duyệt tin nhắn #{message_id}, chờ worker cập nhật kế hoạch và gửi Zalo."
        ),
        "status": msg.status,
        "content": msg.content,
        "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
        "zalo_message_id": msg.zalo_message_id,
    }


@outbound_router.post("/messages/{message_id}/cancel")
def cancel_outbound_message(
    message_id: int,
    req: CancelRequest = CancelRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Hủy tin nhắn thông báo điều xe (chuyển sang trạng thái 'huy').

    Thường áp dụng khi điều độ hủy cuốc xe, nhà xe xin đổi lịch, hoặc thông tin bị sai lệch.
    """
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả.")

    msg.status = OutboundStatus.CANCELLED.value
    msg.last_error = f"Hủy bỏ: {req.reason}"
    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": f"Đã hủy tin nhắn #{message_id}.",
        "status": msg.status,
        "last_error": msg.last_error,
    }


@outbound_router.post("/messages/{message_id}/resend")
def resend_outbound_message(
    message_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Gửi lại tin nhắn kết quả (thường dùng khi bị lỗi mạng hoặc thất bại)."""
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả.")

    if msg.status != OutboundStatus.FAILED.value:
        raise HTTPException(409, "Chỉ gửi lại tin FAILED sau khi đã đối soát kết quả Zalo.")
    msg.status = OutboundStatus.PENDING_SEND.value
    msg.last_error = None
    db.commit()
    return {"ok": True, "status": msg.status, "message": "Đã đưa vào hàng đợi gửi lại."}


@outbound_router.post("/messages/{message_id}/mark-manual-sent")
def mark_outbound_manual_sent(
    message_id: int,
    note: Optional[str] = Query(default=None, description="Ghi chú xác nhận gửi thủ công"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Đánh dấu tin nhắn outbound lỗi là Đã gửi thủ công bởi ĐHVT sau khi copy gửi tay qua Zalo."""
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả.")

    now = _utc_now()
    msg.status = OutboundStatus.SENT.value
    msg.approved_by = msg.approved_by or "dhvt_manual_sent"
    msg.approved_at = msg.approved_at or now
    msg.sent_at = now
    msg.last_error = f"SENT_MANUALLY: {note}" if note else "SENT_MANUALLY"
    msg.zalo_message_id = msg.zalo_message_id or f"manual_sent_{uuid4().hex[:12]}"

    parent_msg_ids: set[int] = set()
    for item in msg.items:
        if item.container_job:
            cj = item.container_job
            cj.validation_status = ValidationStatus.VALID.value
            cj.routing_status = RoutingStatus.SENT.value
            if cj.message_id:
                parent_msg_ids.add(cj.message_id)
            for rc in db.scalars(
                select(ReviewCase).where(
                    ReviewCase.container_job_id == cj.id,
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                )
            ).all():
                rc.status = ReviewStatus.RESOLVED.value
                rc.resolved_by = "dhvt_manual_sent"
                rc.resolved_at = now

    for p_mid in parent_msg_ids:
        still_pending = db.scalar(
            select(func.count(ReviewCase.id)).where(
                ReviewCase.message_id == p_mid,
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
            )
        ) or 0
        if still_pending == 0:
            p_msg = db.get(ZaloMessage, p_mid)
            if p_msg:
                p_msg.processing_status = MessageStatus.PROCESSED.value

    db.commit()
    db.refresh(msg)
    return {
        "ok": True,
        "status": msg.status,
        "message_id": msg.id,
        "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
        "message": f"Đã đánh dấu tin nhắn #{message_id} là đã gửi thủ công.",
    }


@outbound_router.post("/seed-samples")
def seed_outbound_samples(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Tạo các bản ghi kết quả tin nhắn mẫu (Đã gửi, Chờ duyệt, Bị hủy, Thất bại) để người dùng xem và kiểm thử trực quan."""
    # Tìm nhóm Zalo làm đích (ưu tiên nhóm test để không gửi ra Zalo thật khi duyệt mẫu)
    target_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.is_test == True))
    if not target_grp:
        target_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == "test_sample_group"))
    if not target_grp:
        target_grp = ZaloGroup(
            zalo_group_id="test_sample_group",
            name="Nhóm Mẫu Test",
            group_role="destination",
            is_active=True,
            is_test=True,
        )
        db.add(target_grp)
        db.flush()

    samples_def = [
        {
            "order_type": "tra",
            "status": "da_gui",
            "content": "[VSICO THÔNG BÁO XE TRẢ HÀNG]\n- Tuyến: HP - Tận Quang\n- Xe: 15C-170.66\n- Tài xế: Phạm Văn Huynh (0986713346)\n- Cont: VSIU2621051 (Seal: 23333878)\n- Khách hàng: Logitem (Tân Quang)\n- Giờ đến dự kiến: 07:00",
            "key": f"sample_sent_{uuid4().hex[:8]}",
            "sent_at": _utc_now(),
            "approved_by": "Nguyễn Văn Hưng (ĐHVT)",
            "zalo_msg_id": f"zalo_oa_{uuid4().hex[:12]}",
        },
        {
            "order_type": "dong",
            "status": "cho_duyet",
            "content": "[VSICO THÔNG BÁO XE ĐÓNG HÀNG - CHỜ DUYỆT]\n- Tuyến: HP - Hải Dương\n- Xe: 29C-445.41\n- Tài xế: Vũ Tiến Đạt (0931142873)\n- Cont: GAOU7801569 (Seal: 23691177)\n- Khách hàng: DC (Bột ngọt)\n- Giờ hẹn: 07:00",
            "key": f"sample_pending_{uuid4().hex[:8]}",
            "sent_at": None,
            "approved_by": None,
            "zalo_msg_id": None,
        },
        {
            "order_type": "tra",
            "status": "huy",
            "content": "[VSICO THÔNG BÁO HỦY CHUYẾN XE]\n- Xe 15H-006.42 gặp sự cố hỏng lốp trên đường về kho Long An.\n- Hủy cuốc vận chuyển cont VSIU2321938 ngày 12/10/2026.",
            "key": f"sample_cancelled_{uuid4().hex[:8]}",
            "sent_at": None,
            "approved_by": "Trần Thị Lan (Điều hành)",
            "zalo_msg_id": None,
            "last_error": "Hủy bỏ: Xe hỏng đột xuất, đã điều xe 15H-067.22 thay thế.",
        },
        {
            "order_type": "dong",
            "status": "that_bai",
            "content": "[VSICO THÔNG BÁO XE ĐÓNG HÀNG]\n- Xe: 15H-067.22 / Đào Đức Thoại (0364461978)\n- Cont: VSIU2323000 (Seal: 23333330)",
            "key": f"sample_failed_{uuid4().hex[:8]}",
            "sent_at": None,
            "approved_by": None,
            "zalo_msg_id": None,
            "last_error": "Lỗi Zalo OA: Mã phản hồi HTTP 429 Too Many Requests (Quá tần suất cho phép)",
        },
    ]

    created_ids = []
    for s in samples_def:
        msg = OutboundMessage(
            target_group_id=target_grp.id,
            order_type=s["order_type"],
            message_kind="initial",
            content=s["content"],
            idempotency_key=s["key"],
            status=s["status"],
            approved_by=s.get("approved_by"),
            approved_at=_utc_now() if s.get("approved_by") else None,
            sent_at=s.get("sent_at"),
            zalo_message_id=s.get("zalo_msg_id"),
            last_error=s.get("last_error"),
            created_at=_utc_now(),
        )
        db.add(msg)
        db.flush()
        created_ids.append(msg.id)

    db.commit()
    return {
        "ok": True,
        "message": f"Đã tạo {len(created_ids)} bản ghi tin nhắn kết quả mẫu đủ 4 trạng thái (Đã gửi, Chờ duyệt, Bị hủy, Thất bại).",
        "created_ids": created_ids,
    }
