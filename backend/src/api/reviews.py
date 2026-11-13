"""Module Các REST API Rà Soát & Phê Duyệt Lỗi Dữ Liệu (Review & Approvals APIs).

Quản lý hàng đợi ca rà soát cho nhân viên Điều hành vận tải (ĐHVT & Admin):
1. Danh sách ca rà soát: `GET /api/reviews`
2. Nhận xử lý (Claim lock chống 2 người duyệt trùng): `POST /api/reviews/{review_id}/claim`
3. Chuyển giao ca cho ĐHVT khác: `POST /api/reviews/{review_id}/transfer`
4. Quét leo thang ca quá hạn: `POST /api/reviews/check-overdue`
5. Phê duyệt (có sửa trường, chọn kho/kế hoạch, lưu thói quen kho, hủy chuyến): `POST /api/reviews/{review_id}/approve`
6. Từ chối ca & phản hồi nhà xe: `POST /api/reviews/{review_id}/reject`
"""

from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.config.settings import settings
from src.domain.enums import (
    CorrectionStatus,
    GroupRole,
    MessageStatus,
    OutboundStatus,
    ReviewStatus,
    RoutingStatus,
    TmsSyncStatus,
    ValidationStatus,
)
from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_container, clean_phone, clean_plate
from src.handlers.carrier_flow_service import CarrierFlowService
from src.handlers.dhvt_service import DhvtNotificationService
from src.handlers.plan_sync_service import resolve_plan_detailed, sync_job_to_local_plan
from src.infrastructure.database import get_db
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    ContainerJob,
    Customer,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TransportPlan,
    TruckRecord,
    User,
    Warehouse,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.security import get_optional_current_user
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher
from src.observability.logging import get_logger
from src.outbound.templates import OutboundTemplateBuilder

logger = get_logger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["5. Rà Soát & Phê Duyệt (Reviews & Approvals)"])


class ClaimPayload(BaseModel):
    """Schema tùy chọn khi ĐHVT bấm nhận xử lý ca rà soát."""

    operator_name: Optional[str] = Field(default=None, description="Tên người nhận xử lý khi chưa qua JWT")


class TransferPayload(BaseModel):
    """Schema chuyển giao ca rà soát sang nhân viên ĐHVT khác."""

    target_username: str = Field(..., min_length=1, description="Username nhân viên nhận bàn giao")
    reason: Optional[str] = Field(default=None, description="Ghi chú bàn giao")


class ReviewApprovePayload(BaseModel):
    """Schema tùy chọn cho phép ĐHVT chỉnh sửa/chọn kho/chọn kế hoạch trước khi duyệt."""

    selected_plan_id: Optional[int] = Field(default=None, description="ID kế hoạch được ĐHVT chọn để đồng bộ")
    container_no: Optional[str] = Field(default=None)
    container_size: Optional[str] = Field(default=None)
    seal_no: Optional[str] = Field(default=None)
    order_type: Optional[str] = Field(default=None)
    warehouse_id: Optional[int] = Field(default=None, description="ID kho chính thức ĐHVT chọn")
    customer_id: Optional[int] = Field(default=None)
    truck_plate: Optional[str] = Field(default=None)
    trailer_plate: Optional[str] = Field(default=None)
    driver_name: Optional[str] = Field(default=None)
    driver_phone: Optional[str] = Field(default=None)
    eta: Optional[str] = Field(default=None)
    outbound_content: Optional[str] = Field(default=None, description="Nội dung gửi khách hàng tùy chỉnh")
    cancel_reason: Optional[str] = Field(default=None, description="Lý do hủy khi duyệt ca CANCEL_REQUEST")
    save_warehouse_habit: bool = Field(default=True, description="Lưu alias kho thành thói quen cho các lần sau")
    notify_carrier: bool = Field(default=True, description="Gửi xác nhận kết quả duyệt về nhóm nhà xe nếu là nhóm thật")
    operator_name: Optional[str] = Field(default=None)


class RejectPayload(BaseModel):
    """Schema lý do từ chối phê duyệt."""

    reason: Optional[str] = Field(
        default="Dữ liệu không chính xác theo kiểm tra thủ công.",
        description="Lý do từ chối",
    )
    operator_name: Optional[str] = Field(default=None)


def _is_real_source_message(orig_msg: Optional[ZaloMessage]) -> bool:
    """Xác định tin nhắn gốc có phải là nhóm Zalo vận hành thật hay không."""
    if not orig_msg:
        return False
    return not (
        (orig_msg.group_id and ("test_" in orig_msg.group_id or "pytest_" in orig_msg.group_id))
        or (
            orig_msg.zalo_message_id
            and (orig_msg.zalo_message_id.startswith("test_") or orig_msg.zalo_message_id.startswith("pytest_"))
        )
        or (
            orig_msg.sender_id
            and (orig_msg.sender_id.startswith("test_") or orig_msg.sender_id.startswith("pytest_"))
        )
    )


def _resolve_actor(current_user: Optional[User], override_name: Optional[str] = None) -> str:
    """Lấy danh tính người thao tác từ JWT hoặc tên dự phòng khi chạy test không token."""
    if current_user:
        return current_user.username
    if override_name and override_name.strip():
        return override_name.strip()
    return "admin_reviewer"


def _ensure_not_locked_by_other(
    case_obj: ReviewCase,
    actor: str,
    current_user: Optional[User],
) -> None:
    """Chặn ghi đè nếu ca đang được một ĐHVT khác nhận khóa xử lý."""
    is_admin = bool(current_user and current_user.role == "admin")
    if (
        case_obj.status in (ReviewStatus.PENDING.value, "pending")
        and case_obj.assigned_to
        and case_obj.assigned_to != actor
        and not is_admin
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Ca rà soát #{case_obj.id} đang được '{case_obj.assigned_to}' nhận xử lý.",
        )


@router.get("")
def list_review_cases(
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái: 'PENDING', 'APPROVED', 'REJECTED'"),
    case_type: Optional[str] = Query(default=None, description="Lọc theo loại ca rà soát"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lấy danh sách các trường hợp cần rà soát kèm ngữ cảnh tin nhắn và container."""
    stmt = select(ReviewCase).options(selectinload(ReviewCase.message))

    if status:
        norm_status = ReviewStatus(status).value
        stmt = stmt.where(ReviewCase.status.in_([norm_status, status.strip().lower(), status.strip().upper()]))
    if case_type:
        ct = case_type.strip()
        stmt = stmt.where(ReviewCase.case_type.in_([ct, ct.lower(), ct.upper()]))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(ReviewCase.id.desc()).offset(offset).limit(limit)
    cases = list(db.scalars(stmt).all())

    results = []
    for c in cases:
        msg = c.message
        job = db.get(ContainerJob, c.container_job_id) if c.container_job_id else None
        details_dict = c.details if isinstance(c.details, dict) else {}
        truck_rec = job.truck_record if job else None
        if truck_rec is None and msg and msg.truck_records:
            truck_rec = msg.truck_records[0]
        results.append(
            {
                "id": str(c.id),
                "message_id": str(c.message_id),
                "container_job_id": str(c.container_job_id) if c.container_job_id is not None else None,
                "case_type": c.case_type,
                "reason": c.reason,
                "status": c.status,
                "assigned_to": c.assigned_to,
                "priority": details_dict.get("priority", "NORMAL"),
                "details": details_dict,
                "resolution": c.resolution,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                "resolved_by": c.resolved_by,
                "message_context": {
                    "zalo_message_id": msg.zalo_message_id if msg else None,
                    "sender_name": msg.sender_name or (msg.sender_id if msg else None),
                    "group_id": msg.group_id if msg else None,
                    "raw_text": msg.message_text if msg else None,
                    "sent_at": (msg.zalo_sent_at or msg.received_at).isoformat() if msg else None,
                }
                if msg
                else None,
                "container_details": {
                    "container_no": job.container_no if job else None,
                    "container_size": job.container_size if job else None,
                    "seal_no": job.seal_no if job else None,
                    "order_type": job.order_type if job else None,
                    "customer_id": job.customer_id if job else None,
                    "warehouse_id": job.warehouse_id if job else None,
                    "customer_hint": job.customer_hint if job else None,
                    "warehouse_hint": job.warehouse_hint if job else None,
                    "truck_plate": (truck_rec.truck_plate if truck_rec else None) or details_dict.get("truck_plate"),
                    "driver_name": (truck_rec.driver_name if truck_rec else None) or details_dict.get("driver_name"),
                    "driver_phone": (truck_rec.driver_phone if truck_rec else None) or details_dict.get("driver_phone"),
                    "validation_status": job.validation_status if job else None,
                    "warnings": (job.raw_fields or {}).get("warnings", []) if job else [],
                }
                if job
                else None,
            }
        )

    return {
        "ok": True,
        "status": "OK",
        "total": total,
        "total_returned": len(results),
        "reviews": results,
    }


@router.post("/{review_id}/claim")
def claim_review_case(
    review_id: int,
    payload: Optional[ClaimPayload] = Body(default=None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Khóa nhận xử lý một ca rà soát để tránh nhiều ĐHVT xử lý trùng cùng lúc."""
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")
    if case_obj.status in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value, "approved", "rejected"):
        raise HTTPException(status_code=409, detail="Ca rà soát đã được xử lý hoàn tất trước đó.")

    claimer = _resolve_actor(current_user, payload.operator_name if payload else None)
    if (
        case_obj.status in (ReviewStatus.PENDING.value, "pending")
        and case_obj.assigned_to
        and case_obj.assigned_to != claimer
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Ca rà soát đang được '{case_obj.assigned_to}' nhận xử lý.",
        )

    now = datetime.now(UTC)
    case_obj.assigned_to = claimer
    new_details = dict(case_obj.details or {}) if isinstance(case_obj.details, dict) else {}
    new_details["claimed_at"] = now.isoformat()
    case_obj.details = new_details

    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=str(current_user.id) if current_user else claimer,
            action="REVIEW_CLAIMED",
            entity_type="review_case",
            entity_id=str(case_obj.id),
            details={"assigned_to": claimer},
        )
    )
    db.commit()
    return {
        "ok": True,
        "status": case_obj.status,
        "review_id": case_obj.id,
        "assigned_to": case_obj.assigned_to,
        "message": f"Đã nhận khóa xử lý ca #{review_id} cho {claimer}.",
    }


@router.post("/{review_id}/transfer")
def transfer_review_case(
    review_id: int,
    payload: TransferPayload,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Chuyển giao quyền xử lý ca rà soát sang một nhân viên ĐHVT khác đang hoạt động."""
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")
    if case_obj.status in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value, "approved", "rejected"):
        raise HTTPException(status_code=409, detail="Không thể chuyển giao ca đã xử lý xong.")

    target_user = db.scalar(
        select(User).where(User.username == payload.target_username.strip(), User.is_active == True)
    )
    if not target_user:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nhân viên hoạt động '{payload.target_username}'.")

    actor = _resolve_actor(current_user)
    prev_assignee = case_obj.assigned_to
    case_obj.assigned_to = target_user.username
    new_details = dict(case_obj.details or {}) if isinstance(case_obj.details, dict) else {}
    new_details["transferred_from"] = prev_assignee or actor
    new_details["transferred_at"] = datetime.now(UTC).isoformat()
    if payload.reason:
        new_details["transfer_reason"] = payload.reason
    case_obj.details = new_details

    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=str(current_user.id) if current_user else actor,
            action="REVIEW_TRANSFERRED",
            entity_type="review_case",
            entity_id=str(case_obj.id),
            details={"from": prev_assignee, "to": target_user.username, "reason": payload.reason},
        )
    )
    db.commit()
    return {
        "ok": True,
        "status": case_obj.status,
        "review_id": case_obj.id,
        "assigned_to": case_obj.assigned_to,
        "message": f"Đã chuyển giao ca #{review_id} sang {target_user.username}.",
    }


@router.post("/check-overdue")
def trigger_overdue_escalations(
    is_test_msg: bool = Query(default=False, description="Chế độ chạy kiểm thử không bắn tin Zalo thật"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Quét toàn bộ nhắc lỗi nhà xe, ca chờ duyệt và tin chờ gửi đã quá hạn để leo thang ĐHVT/Admin."""
    stats = DhvtNotificationService.check_overdue_escalations(db, is_test_msg=is_test_msg)
    db.commit()
    return {"ok": True, "status": "OK", **stats}


def _apply_payload_edits_to_job(
    db: Session,
    job: ContainerJob,
    payload: Optional[ReviewApprovePayload],
) -> tuple[bool, bool]:
    """Áp dụng các chỉnh sửa thủ công của ĐHVT lên ContainerJob, TruckRecord và thói quen kho."""
    if not payload:
        return False, False

    fields_changed = False
    habit_recorded = False

    if payload.container_no is not None and payload.container_no.strip():
        job.container_no = clean_container(payload.container_no) or payload.container_no.strip().upper()
        fields_changed = True
    if payload.container_size is not None and payload.container_size.strip():
        job.container_size = payload.container_size.strip()
        fields_changed = True
    if payload.seal_no is not None:
        job.seal_no = payload.seal_no.strip().upper() or None
        fields_changed = True
    if payload.order_type is not None and payload.order_type.strip():
        job.order_type = payload.order_type.strip().lower()
        fields_changed = True
    if payload.customer_id is not None:
        cust = db.get(Customer, payload.customer_id)
        if not cust:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy khách hàng ID={payload.customer_id}.")
        job.customer_id = cust.id
        fields_changed = True
    if payload.warehouse_id is not None:
        wh = db.get(Warehouse, payload.warehouse_id)
        if not wh:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy kho ID={payload.warehouse_id}.")
        job.warehouse_id = wh.id
        fields_changed = True
        if payload.save_warehouse_habit and job.warehouse_hint:
            alias_rec = DhvtNotificationService.record_warehouse_habit(db, job.warehouse_hint, wh.id)
            habit_recorded = alias_rec is not None

    truck_touched = any(
        val is not None
        for val in (payload.truck_plate, payload.trailer_plate, payload.driver_name, payload.driver_phone)
    )
    if truck_touched:
        tr = job.truck_record
        if tr is None:
            tr = TruckRecord(id=snowflake.generate(), message_id=job.message_id)
            db.add(tr)
            db.flush()
            job.truck_record_id = tr.id
            job.truck_record = tr
        if payload.truck_plate is not None:
            tr.truck_plate = clean_plate(payload.truck_plate) or payload.truck_plate.strip().upper()
            fields_changed = True
        if payload.trailer_plate is not None:
            tr.trailer_plate = clean_plate(payload.trailer_plate) or payload.trailer_plate.strip().upper()
            fields_changed = True
        if payload.driver_name is not None:
            tr.driver_name = payload.driver_name.strip() or None
            fields_changed = True
        if payload.driver_phone is not None:
            tr.driver_phone = clean_phone(payload.driver_phone) or payload.driver_phone.strip()
            fields_changed = True

    if payload.eta is not None:
        raw_f = dict(job.raw_fields or {}) if isinstance(job.raw_fields, dict) else {}
        raw_f["eta"] = payload.eta.strip()
        job.raw_fields = raw_f
        fields_changed = True

    return fields_changed, habit_recorded


def _approve_cancel_request_case(
    db: Session,
    case_obj: ReviewCase,
    jobs: list[ContainerJob],
    orig_msg: Optional[ZaloMessage],
    actor: str,
    payload: Optional[ReviewApprovePayload],
    is_real_msg: bool,
) -> dict[str, Any]:
    """Xác nhận hủy chuyến: cập nhật local TransportPlan, phát hành thông báo hủy mẫu default_huy.txt và phản hồi nhà xe."""
    now = datetime.now(UTC)
    cancel_reason = (
        (payload.cancel_reason.strip() if payload and payload.cancel_reason else None)
        or case_obj.reason
        or "Điều hành xác nhận hủy chuyến theo đề nghị."
    )
    source_group = (
        db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == orig_msg.group_id))
        if orig_msg
        else None
    )

    pending_send_ids: list[int] = []
    updated_plan_ids: list[int] = []

    target_jobs = list(jobs)
    if not target_jobs and isinstance(case_obj.details, dict) and case_obj.details.get("container_no"):
        fallback_job = db.scalar(
            select(ContainerJob)
            .where(ContainerJob.container_no == str(case_obj.details.get("container_no")).upper())
            .order_by(ContainerJob.id.desc())
        )
        if fallback_job:
            target_jobs.append(fallback_job)

    for job in target_jobs:
        job.validation_status = ValidationStatus.REJECTED.value
        job.routing_status = RoutingStatus.CANCELLED.value
        job.tms_sync_status = TmsSyncStatus.PENDING.value

        # Hủy các outbound chờ duyệt cũ của container này
        for stale in db.scalars(
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id == job.id,
                OutboundMessage.status.in_([OutboundStatus.PENDING_APPROVAL.value, "cho_duyet"]),
            )
        ).all():
            stale.status = OutboundStatus.CANCELLED.value
            stale.last_error = f"Đã hủy chuyến theo duyệt ĐHVT: {cancel_reason}"

        # Cập nhật TransportPlan cục bộ
        plan: Optional[TransportPlan] = None
        if payload and payload.selected_plan_id:
            plan = db.get(TransportPlan, payload.selected_plan_id)
        if plan is None:
            plan_res = resolve_plan_detailed(db, job, source_group, for_update=True)
            plan = plan_res.plan
        if plan is not None:
            plan.version = (plan.version or 1) + 1
            plan.tms_sync_status = TmsSyncStatus.PENDING.value
            stamp = now.strftime("%d/%m %H:%M")
            cancel_note = f"[HUY CHUYEN {stamp} - {actor}]: {cancel_reason}"
            plan.notes = f"{plan.notes}\n{cancel_note}".strip() if plan.notes else cancel_note
            updated_plan_ids.append(plan.id)
            db.add(
                ActivityLog(
                    id=snowflake.generate(),
                    actor_id=actor,
                    action="PLAN_CANCELLED_CONFIRMED",
                    entity_type="transport_plan",
                    entity_id=str(plan.id),
                    details={"review_case_id": case_obj.id, "container_no": job.container_no, "reason": cancel_reason},
                )
            )

        # Tạo thông báo hủy chuyến gửi khách hàng dùng template default_huy.txt
        cust_obj = db.get(Customer, job.customer_id) if job.customer_id else None
        wh_obj = db.get(Warehouse, job.warehouse_id) if job.warehouse_id else None
        tr = job.truck_record
        line = ExtractedContainerLine(
            line_no=job.line_no or 1,
            container_no=job.container_no,
            container_size=job.container_size,
            seal_no=job.seal_no,
            order_type=job.order_type or "tra",
            warehouse_hint=job.warehouse_hint,
            customer_hint=job.customer_hint,
            truck_plate=tr.truck_plate if tr else None,
            driver_name=tr.driver_name if tr else None,
            driver_phone=tr.driver_phone if tr else None,
        )
        cancel_text = (
            payload.outbound_content.strip()
            if (payload and payload.outbound_content and payload.outbound_content.strip())
            else OutboundTemplateBuilder.build_cancel_notification(
                line=line,
                reason=cancel_reason,
                customer_name=cust_obj.name if cust_obj else (job.customer_hint or "Quý khách hàng"),
                warehouse_name=wh_obj.name if wh_obj else (job.warehouse_hint or "Kho khách hàng"),
                customer_id=cust_obj.tms_customer_id if cust_obj else None,
            )
        )
        target_gid, _ = CarrierFlowService.find_target_zalo_group_safe(
            db=db,
            customer_id=job.customer_id,
            warehouse_id=job.warehouse_id,
            order_type=job.order_type,
            source_group_id_str=orig_msg.group_id if orig_msg else None,
            customer_hint=job.customer_hint,
        )
        if target_gid:
            cancel_om = OutboundMessage(
                id=snowflake.generate(),
                target_group_id=target_gid,
                order_type=job.order_type or "tra",
                message_kind="cancel",
                content=cancel_text,
                idempotency_key=f"outbound:cancel:{case_obj.id}:{job.id}",
                status=OutboundStatus.PENDING_SEND.value,
                approved_by=actor,
                approved_at=now,
                attempt_count=0,
            )
            db.add(cancel_om)
            db.flush()
            db.add(OutboundMessageItem(outbound_message_id=cancel_om.id, container_job_id=job.id))
            pending_send_ids.append(cancel_om.id)

    case_obj.status = ReviewStatus.APPROVED.value
    case_obj.resolved_at = now
    case_obj.resolved_by = actor
    case_obj.resolution = {
        "action": "CANCEL_CONFIRMED",
        "cancel_reason": cancel_reason,
        "updated_plan_ids": updated_plan_ids,
        "cancel_outbound_ids": pending_send_ids,
    }
    if orig_msg:
        orig_msg.processing_status = MessageStatus.PROCESSED.value

    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=actor,
            action="REVIEW_CANCEL_APPROVED",
            entity_type="review_case",
            entity_id=str(case_obj.id),
            details=case_obj.resolution,
        )
    )
    db.commit()

    if is_real_msg and settings.AUTO_DISPATCH_OUTBOUND:
        if pending_send_ids:
            from src.infrastructure.outbox_worker import drain_outbox

            drain_outbox(lambda: nullcontext(db), pending_send_ids)
        if (
            (payload is None or payload.notify_carrier)
            and orig_msg
            and source_group
            and not source_group.is_test
            and source_group.group_role.upper() in (GroupRole.CARRIER.value, GroupRole.SOURCE.value)
        ):
            cont_lbl = ", ".join(j.container_no for j in target_jobs if j.container_no) or "chuyến xe"
            ZaloDispatcher.send_to_group(
                group_id=orig_msg.group_id,
                message=f"[VSICO] ĐHVT đã xác nhận hủy {cont_lbl} và thông báo tới khách hàng. Lý do: {cancel_reason}",
                quote_msg_id=orig_msg.zalo_message_id,
            )

    return {
        "ok": True,
        "status": "APPROVED",
        "review_id": case_obj.id,
        "cancel_outbound_ids": pending_send_ids,
        "updated_plan_ids": updated_plan_ids,
        "message": f"Đã xác nhận hủy chuyến cho ca #{case_obj.id} và tạo thông báo hủy gửi khách.",
    }


@router.post("/{review_id}/approve")
def approve_review_case(
    review_id: int,
    payload: Optional[ReviewApprovePayload] = Body(default=None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phê duyệt ca rà soát (có thể sửa trường, chọn kho lưu thói quen, chọn plan hoặc duyệt hủy)."""
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")

    actor = _resolve_actor(current_user, payload.operator_name if payload else None)
    _ensure_not_locked_by_other(case_obj, actor, current_user)

    jobs_to_update: list[ContainerJob] = []
    if case_obj.container_job_id:
        job = db.get(ContainerJob, case_obj.container_job_id)
        if job:
            jobs_to_update.append(job)
    elif case_obj.message_id:
        c_jobs = list(db.scalars(select(ContainerJob).where(ContainerJob.message_id == case_obj.message_id)).all())
        jobs_to_update.extend(c_jobs)

    orig_msg = db.get(ZaloMessage, case_obj.message_id) if case_obj.message_id else None
    is_real_msg = _is_real_source_message(orig_msg)

    # Nhánh riêng: Phê duyệt yêu cầu hủy chuyến
    if case_obj.case_type == "CANCEL_REQUEST":
        return _approve_cancel_request_case(
            db=db,
            case_obj=case_obj,
            jobs=jobs_to_update,
            orig_msg=orig_msg,
            actor=actor,
            payload=payload,
            is_real_msg=is_real_msg,
        )

    now = datetime.now(UTC)
    case_obj.status = ReviewStatus.APPROVED.value
    case_obj.resolved_at = now
    case_obj.resolved_by = actor

    source_group = (
        db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == orig_msg.group_id))
        if orig_msg
        else None
    )

    synced_plan_ids: list[int] = []
    pending_send_ids: list[int] = []
    habit_recorded_any = False

    for job in jobs_to_update:
        fields_changed, habit_recorded = _apply_payload_edits_to_job(db, job, payload)
        habit_recorded_any = habit_recorded_any or habit_recorded

        job.validation_status = ValidationStatus.VALID.value
        job.routing_status = RoutingStatus.ROUTED.value
        job.tms_sync_status = TmsSyncStatus.PENDING.value

        # Đồng bộ trực tiếp lên TransportPlan được chọn hoặc khớp duy nhất
        selected_plan: Optional[TransportPlan] = None
        if payload and payload.selected_plan_id:
            selected_plan = db.get(TransportPlan, payload.selected_plan_id)
            if not selected_plan:
                raise HTTPException(
                    status_code=404,
                    detail=f"Không tìm thấy kế hoạch ID={payload.selected_plan_id}.",
                )
        else:
            plan_res = resolve_plan_detailed(db, job, source_group, for_update=True)
            selected_plan = plan_res.plan

        if selected_plan is not None:
            if not job.customer_id and selected_plan.customer_id:
                job.customer_id = selected_plan.customer_id
            if not job.customer_hint and selected_plan.customer_name:
                job.customer_hint = selected_plan.customer_name
            if not job.warehouse_id and selected_plan.warehouse_id:
                job.warehouse_id = selected_plan.warehouse_id
            if not job.warehouse_hint and selected_plan.delivery_address:
                job.warehouse_hint = selected_plan.delivery_address
            sync_out = sync_job_to_local_plan(
                db=db,
                job=job,
                plan=selected_plan,
                allow_plan_override=True,
                actor_id=actor,
            )
            synced_plan_ids.append(sync_out.plan_id)

        out_stmt = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id == job.id,
                OutboundMessage.status.in_(
                    [
                        OutboundStatus.PENDING_APPROVAL.value,
                        OutboundStatus.IGNORED_DUPLICATE.value,
                        OutboundStatus.FAILED.value,
                        OutboundStatus.SENT.value,
                        "cho_duyet",
                        "bo_qua_trung_lap",
                        "that_bai",
                        "da_gui",
                    ]
                ),
            )
        )
        out_messages = list(db.scalars(out_stmt).all())

        if not out_messages and orig_msg:
            alt_stmt = select(OutboundMessage).where(
                OutboundMessage.idempotency_key.like(f"outbound:{orig_msg.id}:%")
                | OutboundMessage.idempotency_key.like(f"outbound_{orig_msg.id}_%")
            )
            out_messages = list(db.scalars(alt_stmt).all())
            for om in out_messages:
                has_item = db.scalar(
                    select(OutboundMessageItem).where(
                        OutboundMessageItem.outbound_message_id == om.id,
                        OutboundMessageItem.container_job_id == job.id,
                    )
                )
                if not has_item:
                    db.add(OutboundMessageItem(outbound_message_id=om.id, container_job_id=job.id))
                    db.flush()

        cust_obj = db.get(Customer, job.customer_id) if job.customer_id else None
        wh_obj = db.get(Warehouse, job.warehouse_id) if job.warehouse_id else None
        tr = job.truck_record
        raw_f = job.raw_fields if isinstance(job.raw_fields, dict) else {}
        rebuilt_line = ExtractedContainerLine(
            line_no=job.line_no or 1,
            container_no=job.container_no,
            container_size=job.container_size,
            seal_no=job.seal_no,
            order_type=job.order_type or "tra",
            warehouse_hint=wh_obj.name if wh_obj else job.warehouse_hint,
            customer_hint=cust_obj.name if cust_obj else job.customer_hint,
            truck_plate=tr.truck_plate if tr else None,
            trailer_plate=tr.trailer_plate if tr else None,
            driver_name=tr.driver_name if tr else None,
            driver_phone=tr.driver_phone if tr else None,
            eta_time=raw_f.get("eta"),
        )
        rebuilt_content = OutboundTemplateBuilder.build_customer_notification(
            line=rebuilt_line,
            customer_name=cust_obj.name if cust_obj else (job.customer_hint or "Quý khách hàng"),
            warehouse_name=wh_obj.name if wh_obj else (job.warehouse_hint or "Kho khách hàng"),
            customer_id=cust_obj.tms_customer_id if cust_obj else None,
        )

        if not out_messages:
            target_id, _ = CarrierFlowService.find_target_zalo_group_safe(
                db,
                job.customer_id,
                job.warehouse_id,
                job.order_type,
                source_group_id_str=orig_msg.group_id if orig_msg else None,
                plan_group_id_str=selected_plan.group_id if selected_plan else None,
                customer_hint=job.customer_hint,
            )
            if target_id is None:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Chưa có định tuyến khách hàng hợp lệ; cập nhật danh mục trước khi duyệt.",
                )
            new_om = OutboundMessage(
                id=snowflake.generate(),
                target_group_id=target_id,
                order_type=job.order_type or "tra",
                message_kind="thong_bao_xe",
                content=(
                    payload.outbound_content.strip()
                    if (payload and payload.outbound_content and payload.outbound_content.strip())
                    else rebuilt_content
                ),
                idempotency_key=f"outbound:approved:{job.id}:{review_id}",
                status=OutboundStatus.PENDING_APPROVAL.value,
                attempt_count=0,
            )
            db.add(new_om)
            db.flush()
            db.add(OutboundMessageItem(outbound_message_id=new_om.id, container_job_id=job.id))
            db.flush()
            out_messages = [new_om]

        for out_msg in out_messages:
            if out_msg.status in ("SENT", "SENDING"):
                continue
            if payload and payload.outbound_content and payload.outbound_content.strip():
                out_msg.content = payload.outbound_content.strip()
            elif fields_changed:
                out_msg.content = rebuilt_content
            out_msg.status = OutboundStatus.PENDING_SEND.value
            out_msg.approved_by = actor
            out_msg.approved_at = now
            out_msg.sent_at = None
            out_msg.last_error = None
            pending_send_ids.append(out_msg.id)

    # Đóng các BotReply chờ nhà xe nếu ĐHVT đã duyệt xong tin này
    if case_obj.message_id:
        for br in db.scalars(
            select(BotReply).where(
                BotReply.message_id == case_obj.message_id,
                BotReply.status == CorrectionStatus.PENDING.value,
            )
        ).all():
            br.status = CorrectionStatus.RESOLVED.value

    pending_count = (
        db.scalar(
            select(func.count(ReviewCase.id)).where(
                ReviewCase.message_id == case_obj.message_id,
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                ReviewCase.id != case_obj.id,
            )
        )
        or 0
    )

    if pending_count == 0 and case_obj.message_id:
        msg = db.get(ZaloMessage, case_obj.message_id)
        if msg:
            msg.processing_status = MessageStatus.PROCESSED.value

    case_obj.resolution = {
        "action": "APPROVED",
        "resolved_by": actor,
        "synced_plan_ids": synced_plan_ids,
        "warehouse_habit_saved": habit_recorded_any,
        "outbound_ids": pending_send_ids,
    }
    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=str(current_user.id) if current_user else actor,
            action="REVIEW_APPROVED",
            entity_type="review_case",
            entity_id=str(case_obj.id),
            details=case_obj.resolution,
        )
    )
    db.commit()

    send_warnings: list[str] = []
    if is_real_msg and settings.AUTO_DISPATCH_OUTBOUND and pending_send_ids:
        from src.infrastructure.outbox_worker import drain_outbox

        drain_outbox(lambda: nullcontext(db), pending_send_ids)
        for oid in pending_send_ids:
            om = db.get(OutboundMessage, oid)
            if om and om.status == OutboundStatus.FAILED.value and om.last_error:
                send_warnings.append(f"Outbound #{oid}: {om.last_error}")

    if (
        is_real_msg
        and settings.AUTO_DISPATCH_OUTBOUND
        and (payload is None or payload.notify_carrier)
        and orig_msg
        and source_group
        and not source_group.is_test
        and source_group.group_role.upper() in (GroupRole.CARRIER.value, GroupRole.SOURCE.value)
    ):
        conts = [j.container_no for j in jobs_to_update if j.container_no]
        if conts:
            ZaloDispatcher.send_to_group(
                group_id=orig_msg.group_id,
                message=f"[VSICO] ĐHVT đã duyệt thông tin điều xe container {', '.join(conts)}.",
                quote_msg_id=orig_msg.zalo_message_id,
            )

    if send_warnings:
        return {
            "ok": True,
            "status": "APPROVED_WITH_WARNING",
            "review_id": review_id,
            "synced_plan_ids": synced_plan_ids,
            "message": f"Đã phê duyệt ca #{review_id} trong hệ thống. Tuy nhiên gửi Zalo cảnh báo: {'; '.join(send_warnings)}.",
            "warnings": send_warnings,
        }

    return {
        "ok": True,
        "status": "APPROVED",
        "review_id": review_id,
        "synced_plan_ids": synced_plan_ids,
        "warehouse_habit_saved": habit_recorded_any,
        "message": f"Đã phê duyệt thành công ca rà soát ID={review_id}.",
    }


@router.post("/{review_id}/reject")
def reject_review_case(
    review_id: int,
    payload: Optional[RejectPayload] = Body(default=None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Từ chối ca rà soát: hủy outbound chờ duyệt, đóng tin gốc và phản hồi nhà xe nếu là nhóm thật."""
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")

    actor = _resolve_actor(current_user, payload.operator_name if payload else None)
    _ensure_not_locked_by_other(case_obj, actor, current_user)

    reject_reason = (
        payload.reason
        if (payload and payload.reason and payload.reason.strip())
        else "Dữ liệu không chính xác theo kiểm tra thủ công."
    )
    now = datetime.now(UTC)

    case_obj.status = ReviewStatus.REJECTED.value
    case_obj.resolved_at = now
    case_obj.resolved_by = actor
    case_obj.reason = f"{case_obj.reason or ''} [Từ chối: {reject_reason}]"
    case_obj.resolution = {"action": "REJECTED", "reason": reject_reason, "resolved_by": actor}

    jobs_to_cancel: list[ContainerJob] = []
    if case_obj.container_job_id:
        job = db.get(ContainerJob, case_obj.container_job_id)
        if job:
            jobs_to_cancel.append(job)
    elif case_obj.message_id:
        c_jobs = list(db.scalars(select(ContainerJob).where(ContainerJob.message_id == case_obj.message_id)).all())
        jobs_to_cancel.extend(c_jobs)

    for job in jobs_to_cancel:
        job.validation_status = ValidationStatus.REJECTED.value
        job.routing_status = RoutingStatus.CANCELLED.value
        job.tms_sync_status = TmsSyncStatus.FAILED.value

        out_stmt = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id == job.id,
                OutboundMessage.status.in_([OutboundStatus.PENDING_APPROVAL.value, "cho_duyet"]),
            )
        )
        for out_msg in db.scalars(out_stmt).all():
            out_msg.status = OutboundStatus.CANCELLED.value
            out_msg.last_error = f"ĐHVT từ chối duyệt: {reject_reason}"

    if case_obj.message_id:
        for br in db.scalars(
            select(BotReply).where(
                BotReply.message_id == case_obj.message_id,
                BotReply.status == CorrectionStatus.PENDING.value,
            )
        ).all():
            br.status = CorrectionStatus.RESOLVED.value

    pending_count = (
        db.scalar(
            select(func.count(ReviewCase.id)).where(
                ReviewCase.message_id == case_obj.message_id,
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                ReviewCase.id != case_obj.id,
            )
        )
        or 0
    )

    orig_msg = db.get(ZaloMessage, case_obj.message_id) if case_obj.message_id else None
    if pending_count == 0 and orig_msg:
        orig_msg.processing_status = MessageStatus.CANCELLED.value

    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=str(current_user.id) if current_user else actor,
            action="REVIEW_REJECTED",
            entity_type="review_case",
            entity_id=str(case_obj.id),
            details={"reason": reject_reason, "rejected_by": actor},
        )
    )
    db.commit()

    if orig_msg and _is_real_source_message(orig_msg) and settings.AUTO_DISPATCH_OUTBOUND:
        source_group = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == orig_msg.group_id))
        if (
            source_group
            and not source_group.is_test
            and source_group.group_role.upper() in (GroupRole.CARRIER.value, GroupRole.SOURCE.value)
        ):
            conts = ", ".join(j.container_no for j in jobs_to_cancel if j.container_no) or "lượt xe"
            ZaloDispatcher.send_to_group(
                group_id=orig_msg.group_id,
                message=f"[VSICO] ĐHVT từ chối thông tin điều xe ({conts}). Lý do: {reject_reason}. Vui lòng kiểm tra và gửi lại.",
                quote_msg_id=orig_msg.zalo_message_id,
            )

    return {
        "ok": True,
        "status": "REJECTED",
        "review_id": review_id,
        "message": f"Đã từ chối ca rà soát ID={review_id} và hủy thông báo gửi khách thành công.",
    }
