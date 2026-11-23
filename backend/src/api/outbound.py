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
from src.handlers.plan_sync_service import resolve_job_expected_time
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
from src.outbound.templates import format_arrival_time_display

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
    eta: Optional[str] = None


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
    cho_gui: int = 0
    huy: int = 0
    that_bai: int = 0
    bo_qua_trung_lap: int = 0
    ket_qua_dat: int = 0
    da_duyet: int = 0
    tu_dong_dat: int = 0


_DELIVERED_OR_PASSED_STATUSES = [
    OutboundStatus.SENT.value,
    "da_gui",
    "SENT",
    OutboundStatus.PENDING_SEND.value,
    "PENDING_SEND",
    OutboundStatus.SENDING.value,
    "SENDING",
]


@outbound_router.get("/summary", response_model=OutboundSummaryResponse)
def get_outbound_summary(db: Session = Depends(get_db)) -> OutboundSummaryResponse:
    """Lấy thống kê số lượng tin nhắn kết quả theo từng trạng thái.

    Returns:
        OutboundSummaryResponse: Thống kê số lượng `da_gui`, `cho_duyet`, `huy`, `that_bai`, `ket_qua_dat`, `da_duyet`, `tu_dong_dat`.
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
    cho_gui = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_([OutboundStatus.PENDING_SEND.value, OutboundStatus.SENDING.value])
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
    ket_qua_dat = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_(_DELIVERED_OR_PASSED_STATUSES)
        )
    ) or 0
    da_duyet = db.scalar(
        select(func.count(OutboundMessage.id)).where(
            OutboundMessage.status.in_(_DELIVERED_OR_PASSED_STATUSES),
            OutboundMessage.approved_by.is_not(None),
            OutboundMessage.approved_by != "auto_system",
        )
    ) or 0
    tu_dong_dat = max(0, ket_qua_dat - da_duyet)

    return OutboundSummaryResponse(
        ok=True,
        total=total,
        da_gui=da_gui,
        cho_duyet=cho_duyet,
        cho_gui=cho_gui,
        huy=huy,
        that_bai=that_bai,
        bo_qua_trung_lap=bo_qua_trung_lap,
        ket_qua_dat=ket_qua_dat,
        da_duyet=da_duyet,
        tu_dong_dat=tu_dong_dat,
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
    results_only: bool = Query(default=False, description="Chỉ lấy kết quả đã duyệt hoặc đạt điều kiện tự động gửi"),
    source_mode: Optional[str] = Query(default=None, description="Nguồn kết quả: all, approved, auto"),
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

    if results_only:
        stmt = stmt.where(OutboundMessage.status.in_(_DELIVERED_OR_PASSED_STATUSES))

    if source_mode and source_mode.strip().lower() != "all":
        sm = source_mode.strip().lower()
        if sm == "approved":
            stmt = stmt.where(
                OutboundMessage.approved_by.is_not(None),
                OutboundMessage.approved_by != "auto_system",
            )
        elif sm == "auto":
            stmt = stmt.where(
                or_(
                    OutboundMessage.approved_by.is_(None),
                    OutboundMessage.approved_by == "auto_system",
                )
            )
        else:
            raise HTTPException(status_code=400, detail=f"Nguồn kết quả không hợp lệ: {source_mode}")

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
        first_resolved_eta: Optional[str] = None
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

                job_eta = resolve_job_expected_time(db, job)
                if job_eta and first_resolved_eta is None:
                    first_resolved_eta = job_eta

                containers_info.append({
                    "container_no": job.container_no,
                    "truck_plate": truck_plate,
                    "driver_name": driver_name,
                    "driver_phone": driver_phone,
                    "seal_no": job.seal_no,
                    "plan_date": (job.raw_fields or {}).get("plan_date") or (job.created_at.date().isoformat() if job.created_at else None),
                    "eta": job_eta,
                })

        group_name = r.target_group.name if r.target_group else None
        zalo_gid = r.target_group.zalo_group_id if r.target_group else None
        content_display = r.content or ""
        if first_resolved_eta and "- Giờ đến dự kiến: Chưa có" in content_display:
            content_display = content_display.replace(
                "- Giờ đến dự kiến: Chưa có",
                f"- Giờ đến dự kiến: {format_arrival_time_display(first_resolved_eta)}",
            )

        serialized.append({
            "id": str(r.id),
            "target_group_id": str(r.target_group_id),
            "target_group_name": group_name or f"Nhóm Zalo #{r.target_group_id}",
            "target_zalo_group_id": zalo_gid,
            "order_type": r.order_type,
            "message_kind": r.message_kind,
            "content": content_display,
            "idempotency_key": r.idempotency_key,
            "review_zalo_msg_id": r.review_zalo_msg_id,
            "approved_by": r.approved_by,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "approval_source": "approved" if (r.approved_by and r.approved_by != "auto_system") else "auto",
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
    first_resolved_eta: Optional[str] = None
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

            job_eta = resolve_job_expected_time(db, job)
            if job_eta and first_resolved_eta is None:
                first_resolved_eta = job_eta

            containers_info.append({
                "container_no": job.container_no,
                "truck_plate": truck_plate,
                "driver_name": driver_name,
                "driver_phone": driver_phone,
                "seal_no": job.seal_no,
                "plan_date": (job.raw_fields or {}).get("plan_date") or (job.created_at.date().isoformat() if job.created_at else None),
                "eta": job_eta,
            })

    group_name = msg.target_group.name if msg.target_group else None
    zalo_gid = msg.target_group.zalo_group_id if msg.target_group else None
    content_display = msg.content or ""
    if first_resolved_eta and "- Giờ đến dự kiến: Chưa có" in content_display:
        content_display = content_display.replace(
            "- Giờ đến dự kiến: Chưa có",
            f"- Giờ đến dự kiến: {format_arrival_time_display(first_resolved_eta)}",
        )

    return {
        "ok": True,
        "message": {
            "id": str(msg.id),
            "target_group_id": str(msg.target_group_id),
            "target_group_name": group_name or f"Nhóm Zalo #{msg.target_group_id}",
            "target_zalo_group_id": zalo_gid,
            "order_type": msg.order_type,
            "message_kind": msg.message_kind,
            "content": content_display,
            "idempotency_key": msg.idempotency_key,
            "review_zalo_msg_id": msg.review_zalo_msg_id,
            "approved_by": msg.approved_by,
            "approved_at": msg.approved_at.isoformat() if msg.approved_at else None,
            "approval_source": "approved" if (msg.approved_by and msg.approved_by != "auto_system") else "auto",
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
    if current_user and current_user.role.upper() not in ("ADMIN", "DHVT"):
        raise HTTPException(status_code=403, detail="Chỉ tài khoản ĐHVT hoặc Admin được duyệt gửi thông báo.")
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
    elif msg.content and "- Giờ đến dự kiến: Chưa có" in msg.content:
        for it in msg.items:
            if it.container_job:
                resolved_eta = resolve_job_expected_time(db, it.container_job)
                if resolved_eta:
                    msg.content = msg.content.replace(
                        "- Giờ đến dự kiến: Chưa có",
                        f"- Giờ đến dự kiến: {format_arrival_time_display(resolved_eta)}",
                    )
                    break

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

            # Đồng bộ kế hoạch cục bộ & TMS cho các ca MANUAL chờ duyệt khi ĐHVT duyệt từ màn /results
            pending_rcs = list(
                db.scalars(
                    select(ReviewCase).where(
                        ReviewCase.container_job_id == cj.id,
                        ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                    )
                ).all()
            )
            if pending_rcs:
                from src.handlers.plan_sync_service import (
                    resolve_plan_detailed,
                    sync_combined_ro_to_lo_plans,
                    sync_job_to_local_plan,
                    sync_plan_to_tms,
                )
                from src.infrastructure.models import TransportPlan

                first_det = pending_rcs[0].details if isinstance(pending_rcs[0].details, dict) else {}
                raw_f = cj.raw_fields if isinstance(cj.raw_fields, dict) else {}
                sel_pid = first_det.get("selected_plan_id") or first_det.get("transport_plan_id") or raw_f.get("transport_plan_id")
                sec_pid = first_det.get("secondary_plan_id")
                sel_plan = db.get(TransportPlan, int(sel_pid)) if sel_pid and str(sel_pid).isdigit() else None
                sec_plan = db.get(TransportPlan, int(sec_pid)) if sec_pid and str(sec_pid).isdigit() else None
                if sel_plan is None and cj.message_id:
                    orig_m = db.get(ZaloMessage, cj.message_id)
                    src_g = (
                        db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == orig_m.group_id))
                        if orig_m
                        else None
                    )
                    if src_g:
                        sel_plan = resolve_plan_detailed(db, cj, src_g, for_update=True).plan
                if sel_plan is not None:
                    if sec_plan is not None and sec_plan.id != sel_plan.id:
                        ro_p = sec_plan if (sec_plan.order_type or "").lower() in ("tra", "return", "ro") else sel_plan
                        lo_p = sel_plan if ro_p is sec_plan else sec_plan
                        ro_out, lo_out = sync_combined_ro_to_lo_plans(
                            db=db, job=cj, ro_plan=ro_p, lo_plan=lo_p, actor_id=actor, allow_plan_override=True
                        )
                        if ro_out.mode in ("FILLED", "UPDATED"):
                            sync_plan_to_tms(
                                db, ro_p, job=cj, changed_fields=ro_out.changed_fields,
                                before_values=ro_out.before_values, allow_container_override=False, actor_id=actor
                            )
                        if lo_out.mode in ("FILLED", "UPDATED"):
                            sync_plan_to_tms(
                                db, lo_p, job=cj, changed_fields=lo_out.changed_fields,
                                before_values=lo_out.before_values, allow_container_override=False, actor_id=actor
                            )
                    else:
                        s_out = sync_job_to_local_plan(
                            db=db, job=cj, plan=sel_plan, allow_plan_override=True, actor_id=actor
                        )
                        if s_out.mode in ("FILLED", "UPDATED"):
                            sync_plan_to_tms(
                                db, sel_plan, job=cj, changed_fields=s_out.changed_fields,
                                before_values=s_out.before_values, allow_container_override=False, actor_id=actor
                            )

            # Cập nhật review_cases liên quan đến container này
            for rc in pending_rcs:
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
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Hủy tin nhắn thông báo điều xe (chuyển sang trạng thái 'huy').

    Thường áp dụng khi điều độ hủy cuốc xe, nhà xe xin đổi lịch, hoặc thông tin bị sai lệch.
    """
    if current_user and current_user.role.upper() not in ("ADMIN", "DHVT"):
        raise HTTPException(status_code=403, detail="Chỉ tài khoản ĐHVT hoặc Admin được hủy thông báo.")
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
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Gửi lại tin nhắn kết quả (thường dùng khi bị lỗi mạng hoặc thất bại)."""
    if current_user and current_user.role.upper() not in ("ADMIN", "DHVT"):
        raise HTTPException(status_code=403, detail="Chỉ tài khoản ĐHVT hoặc Admin được gửi lại thông báo.")
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
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Đánh dấu tin nhắn outbound lỗi là Đã gửi thủ công bởi ĐHVT sau khi copy gửi tay qua Zalo."""
    if current_user and current_user.role.upper() not in ("ADMIN", "DHVT"):
        raise HTTPException(status_code=403, detail="Chỉ tài khoản ĐHVT hoặc Admin được xác nhận gửi thủ công.")
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
