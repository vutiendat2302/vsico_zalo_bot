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
import re
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
from src.domain.rules import clean_container, clean_phone, clean_plate, compact_plate, is_valid_phone_list
from src.domain.short_link import decode_short_token
from src.handlers.carrier_flow_service import CarrierFlowService
from src.handlers.dhvt_service import DhvtNotificationService, humanize_reason_text
from src.validation.validators import ContainerValidator
from src.handlers.plan_sync_service import (
    extract_plan_expected_time,
    resolve_job_expected_time,
    resolve_plan_detailed,
    sync_combined_ro_to_lo_plans,
    sync_job_to_local_plan,
    sync_plan_to_tms,
)
from src.infrastructure.database import get_db
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    ContainerJob,
    Customer,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    Trailer,
    TransportPlan,
    TruckRecord,
    User,
    Vehicle,
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
    secondary_plan_id: Optional[int] = Field(default=None, description="ID kế hoạch thứ 2 (lệnh trả gốc RO khi ghép RO -> LO)")
    expected_version: Optional[int] = Field(default=None, ge=1, description="Phiên bản kế hoạch kỳ vọng (Optimistic Lock)")
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
    skip_dhvt_zalo_broadcast: bool = Field(
        default=False,
        description="Bỏ qua broadcast Zalo ĐHVT khi phản hồi đã gửi trực tiếp trong nhóm ĐHVT",
    )


class RejectPayload(BaseModel):
    """Schema lý do từ chối phê duyệt."""

    reason: Optional[str] = Field(
        default="Dữ liệu không chính xác theo kiểm tra thủ công.",
        description="Lý do từ chối",
    )
    operator_name: Optional[str] = Field(default=None)
    skip_dhvt_zalo_broadcast: bool = Field(
        default=False,
        description="Bỏ qua broadcast Zalo ĐHVT khi phản hồi đã gửi trực tiếp trong nhóm ĐHVT",
    )


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
        or (orig_msg.sender_id and orig_msg.sender_id.startswith("pytest_"))
    )


def _resolve_actor(current_user: Optional[User], override_name: Optional[str] = None) -> str:
    """Lấy danh tính người thao tác từ JWT hoặc tên dự phòng khi chạy test không token."""
    if current_user:
        return current_user.username
    if override_name and override_name.strip():
        return override_name.strip()
    return "admin_reviewer"


def _ensure_reviewer_role(current_user: Optional[User]) -> None:
    """Chặn người dùng không thuộc vai trò ĐHVT/Admin thực hiện thao tác duyệt/sửa trên Web."""
    if current_user and current_user.role.upper() not in ("ADMIN", "DHVT"):
        raise HTTPException(
            status_code=403,
            detail="Chỉ tài khoản ĐHVT hoặc Admin được phép xử lý ca rà soát.",
        )


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


def _load_outbound_previews_for_cases(
    db: Session,
    cases: list[ReviewCase],
) -> dict[int, dict[str, Any]]:
    """Nạp hàng loạt bản nháp/thông báo gửi khách gắn với các ca rà soát."""
    if not cases:
        return {}

    explicit_om_ids: set[int] = set()
    job_ids: set[int] = set()
    for c in cases:
        if c.container_job_id:
            job_ids.add(c.container_job_id)
        details = c.details if isinstance(c.details, dict) else {}
        om_raw = details.get("outbound_message_id")
        if om_raw is not None:
            try:
                explicit_om_ids.add(int(om_raw))
            except (ValueError, TypeError):
                pass

    om_by_id: dict[int, OutboundMessage] = {}
    if explicit_om_ids:
        for om in db.scalars(select(OutboundMessage).where(OutboundMessage.id.in_(explicit_om_ids))).all():
            om_by_id[om.id] = om

    om_by_job: dict[int, list[OutboundMessage]] = {}
    if job_ids:
        rows = db.execute(
            select(OutboundMessageItem.container_job_id, OutboundMessage)
            .join(OutboundMessage, OutboundMessage.id == OutboundMessageItem.outbound_message_id)
            .where(OutboundMessageItem.container_job_id.in_(job_ids))
            .order_by(OutboundMessage.id.desc())
        ).all()
        for jid, om in rows:
            om_by_id.setdefault(om.id, om)
            om_by_job.setdefault(jid, []).append(om)

    tg_ids = {om.target_group_id for om in om_by_id.values() if om.target_group_id}
    tg_names: dict[int, str] = (
        {
            g.id: (g.name or g.zalo_group_id)
            for g in db.scalars(select(ZaloGroup).where(ZaloGroup.id.in_(tg_ids))).all()
        }
        if tg_ids
        else {}
    )

    priority_statuses = {
        OutboundStatus.PENDING_APPROVAL.value,
        "cho_duyet",
        OutboundStatus.FAILED.value,
        "that_bai",
        OutboundStatus.PENDING_SEND.value,
    }
    previews: dict[int, dict[str, Any]] = {}
    for c in cases:
        chosen: Optional[OutboundMessage] = None
        details = c.details if isinstance(c.details, dict) else {}
        if details.get("outbound_message_id") is not None:
            try:
                chosen = om_by_id.get(int(details["outbound_message_id"]))
            except (ValueError, TypeError):
                chosen = None
        if chosen is None and c.container_job_id:
            candidates = [
                om
                for om in om_by_job.get(c.container_job_id, [])
                if om.status not in (OutboundStatus.CANCELLED.value, "huy", OutboundStatus.IGNORED_DUPLICATE.value)
            ]
            for om in candidates:
                if om.status in priority_statuses:
                    chosen = om
                    break
            if chosen is None and candidates:
                chosen = candidates[0]
        if chosen is not None:
            previews[c.id] = {
                "id": str(chosen.id),
                "status": chosen.status,
                "message_kind": chosen.message_kind,
                "target_group_name": tg_names.get(chosen.target_group_id),
                "content": chosen.content,
                "last_error": chosen.last_error,
            }
    return previews


_INCOMPLETE_REVIEW_CASE_TYPES = {
    "missing_fields",
    "MISSING_FIELDS",
    "invalid_check_digit",
    "INVALID_CHECK_DIGIT",
    "UPDATE_INCOMPLETE",
    "AMBIGUOUS_SUPPLEMENT",
    "MISSING_CONTAINER_FOR_UPDATE",
}

_ACTION_EXEMPT_CASE_TYPES = {
    "CANCEL_REQUEST",
    "CARRIER_CANCEL_OR_ISSUE",
    "CUSTOMER_CHANGE_REQUEST",
    "OUTBOUND_SEND_FAILED",
}


def _is_review_ready_5_fields(
    *,
    eff_truck: Optional[str],
    eff_trailer: Optional[str],
    eff_cont: Optional[str],
    eff_driver: Optional[str],
    eff_phone: Optional[str],
) -> bool:
    """Kiểm tra ca duyệt đã đầy đủ và hợp lệ cả 5 trường bắt buộc của nhà xe hay chưa."""
    probe = ExtractedContainerLine(
        truck_plate=clean_plate(eff_truck) if eff_truck else None,
        trailer_plate=clean_plate(eff_trailer) if eff_trailer else None,
        container_no=clean_container(eff_cont) if eff_cont else None,
        driver_name=eff_driver.strip() if eff_driver else None,
        driver_phone=clean_phone(eff_phone) if eff_phone else None,
    )
    ContainerValidator.validate_line(probe)
    is_complete, _missing = OutboundTemplateBuilder.check_core_fields_completeness(probe)
    return is_complete


def _build_review_customer_output_preview(
    case_obj: ReviewCase,
    details_dict: dict[str, Any],
    linked_plan: Optional[TransportPlan],
    *,
    eff_cont: Optional[str],
    eff_size: Optional[str],
    eff_seal: Optional[str],
    eff_order: Optional[str],
    eff_cust_hint: Optional[str],
    eff_wh_hint: Optional[str],
    eff_truck: Optional[str],
    eff_trailer: Optional[str],
    eff_driver: Optional[str],
    eff_phone: Optional[str],
    eff_eta: Optional[str],
    eff_cust_tms_id: Optional[str] = None,
    target_group_name: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Tạo bản xem trước tin nhắn đầu ra sẽ gửi nhóm khách hàng (giống định dạng trang Kết quả gửi)."""
    if not any([eff_cont, eff_truck, eff_driver, eff_cust_hint, eff_wh_hint]):
        return None

    preview_line = ExtractedContainerLine(
        line_no=1,
        plan_date=linked_plan.plan_date.isoformat() if linked_plan and linked_plan.plan_date else details_dict.get("plan_date"),
        container_no=eff_cont,
        container_size=eff_size,
        seal_no=eff_seal,
        order_type=eff_order or "dong",
        customer_hint=eff_cust_hint,
        warehouse_hint=eff_wh_hint,
        truck_plate=eff_truck,
        trailer_plate=eff_trailer,
        driver_name=eff_driver,
        driver_phone=eff_phone,
        eta_time=eff_eta,
    )
    cust_disp = eff_cust_hint or (linked_plan.customer_name if linked_plan else None) or "Quý khách hàng"
    wh_disp = eff_wh_hint or (linked_plan.warehouse_name or linked_plan.delivery_address if linked_plan else None) or "Theo kế hoạch"
    plan_dt = linked_plan.plan_date if linked_plan else None

    req_action = str(details_dict.get("requested_action") or "").upper()
    is_cancel = case_obj.case_type == "CANCEL_REQUEST" or (
        case_obj.case_type in ("CARRIER_CANCEL_OR_ISSUE", "CUSTOMER_CHANGE_REQUEST") and req_action == "CANCEL"
    )
    raw_changes = details_dict.get("changes") if isinstance(details_dict.get("changes"), list) else []

    if is_cancel:
        content = OutboundTemplateBuilder.build_cancel_notification(
            line=preview_line,
            reason=case_obj.reason or "Theo yêu cầu điều vận",
            customer_name=cust_disp,
            warehouse_name=wh_disp,
            customer_id=eff_cust_tms_id,
            plan_date=plan_dt,
        )
        kind = "cancel"
    elif raw_changes or case_obj.case_type in ("REVIEW_CHANGE_AFTER_SENT", "UPDATE_REQUIRES_APPROVAL"):
        content = OutboundTemplateBuilder.build_update_notification(
            line=preview_line,
            changes_list=[str(x) for x in raw_changes] or ["- Cập nhật thông tin xe/tài xế"],
            customer_name=cust_disp,
            warehouse_name=wh_disp,
            customer_id=eff_cust_tms_id,
            plan_date=plan_dt,
        )
        kind = "update"
    else:
        content = OutboundTemplateBuilder.build_customer_notification(
            line=preview_line,
            customer_name=cust_disp,
            warehouse_name=wh_disp,
            customer_id=eff_cust_tms_id,
            plan_date=plan_dt,
        )
        kind = "initial"

    return {
        "id": f"preview-{case_obj.id}",
        "status": "PREVIEW",
        "message_kind": kind,
        "target_group_name": target_group_name or "Nhóm Zalo khách hàng",
        "content": content,
        "last_error": None,
    }


@router.get("")
def list_review_cases(
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái: 'PENDING', 'APPROVED', 'REJECTED'"),
    case_type: Optional[str] = Query(default=None, description="Lọc theo loại ca rà soát"),
    review_id: Optional[int] = Query(default=None, description="Lấy trực tiếp một ca theo ID"),
    outbound_id: Optional[int] = Query(default=None, description="Tìm ca duyệt theo ID outbound"),
    short_token: Optional[str] = Query(default=None, description="Mã liên kết rút gọn ẩn thông tin hệ thống"),
    ready_only: bool = Query(default=True, description="Chỉ lấy các ca đã đầy đủ 5 trường bắt buộc từ nhà xe"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lấy danh sách các trường hợp cần rà soát kèm ngữ cảnh tin nhắn và container."""
    stmt = select(ReviewCase).options(selectinload(ReviewCase.message))

    invalid_short_token = False
    if short_token is not None:
        decoded = decode_short_token(short_token, settings.short_link_secret)
        if decoded is None:
            invalid_short_token = True
        else:
            tok_kind, tok_id = decoded
            if tok_kind == "r":
                review_id = tok_id
            else:
                outbound_id = tok_id

    if invalid_short_token:
        stmt = stmt.where(ReviewCase.id == -1)
    elif review_id is not None:
        stmt = stmt.where(ReviewCase.id == review_id)
    elif outbound_id is not None:
        om_job_ids = list(
            db.scalars(
                select(OutboundMessageItem.container_job_id).where(
                    OutboundMessageItem.outbound_message_id == outbound_id
                )
            ).all()
        )
        if om_job_ids:
            stmt = stmt.where(ReviewCase.container_job_id.in_(om_job_ids))
        else:
            stmt = stmt.where(ReviewCase.id == -1)

    is_direct_lookup = invalid_short_token or review_id is not None or outbound_id is not None
    if status and not is_direct_lookup:
        norm_status = ReviewStatus(status).value
        stmt = stmt.where(ReviewCase.status.in_([norm_status, status.strip().lower(), status.strip().upper()]))
    if case_type:
        ct = case_type.strip()
        stmt = stmt.where(ReviewCase.case_type.in_([ct, ct.lower(), ct.upper()]))
    elif ready_only and not is_direct_lookup:
        stmt = stmt.where(~ReviewCase.case_type.in_(list(_INCOMPLETE_REVIEW_CASE_TYPES)))

    filter_in_python = bool(ready_only and not case_type and not is_direct_lookup)
    if filter_in_python:
        cases = list(db.scalars(stmt.order_by(ReviewCase.id.desc()).limit(max(500, offset + limit))).all())
        total = 0
    else:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(count_stmt) or 0
        cases = list(db.scalars(stmt.order_by(ReviewCase.id.desc()).offset(offset).limit(limit)).all())

    # Nạp hàng loạt TransportPlan ứng viên để bổ sung `plan_date` và `required_time` (cả cho ca cũ đã lưu trước đó)
    cand_plan_ids: set[int] = set()
    parent_job_ids: set[int] = set()
    direct_job_map: dict[int, ContainerJob] = {}
    for c in cases:
        if c.container_job_id:
            j = db.get(ContainerJob, c.container_job_id)
            if j:
                direct_job_map[c.container_job_id] = j
                if j.parent_job_id:
                    parent_job_ids.add(j.parent_job_id)
                j_pid = (j.raw_fields or {}).get("transport_plan_id") if isinstance(j.raw_fields, dict) else None
                if j_pid:
                    try:
                        cand_plan_ids.add(int(j_pid))
                    except (ValueError, TypeError):
                        pass
        details_dict = c.details if isinstance(c.details, dict) else {}
        for pk in ("transport_plan_id", "plan_id", "selected_plan_id"):
            if details_dict.get(pk):
                try:
                    cand_plan_ids.add(int(details_dict[pk]))
                except (ValueError, TypeError):
                    pass
        for item in (
            details_dict.get("candidate_plans")
            or (details_dict.get("resolution") or {}).get("candidates")
            or []
        ):
            if isinstance(item, dict) and item.get("plan_id"):
                try:
                    cand_plan_ids.add(int(item["plan_id"]))
                except (ValueError, TypeError):
                    pass
        for pid in details_dict.get("candidate_plan_ids") or []:
            try:
                cand_plan_ids.add(int(pid))
            except (ValueError, TypeError):
                pass

    parent_job_map: dict[int, ContainerJob] = (
        {
            pj.id: pj
            for pj in db.scalars(select(ContainerJob).where(ContainerJob.id.in_(parent_job_ids))).all()
        }
        if parent_job_ids
        else {}
    )
    cand_plan_lookup: dict[int, TransportPlan] = (
        {
            p.id: p
            for p in db.scalars(
                select(TransportPlan).where(TransportPlan.id.in_(cand_plan_ids))
            ).all()
        }
        if cand_plan_ids
        else {}
    )
    cust_ids = {
        j.customer_id
        for j in [*direct_job_map.values(), *parent_job_map.values()]
        if j.customer_id
    } | {p.customer_id for p in cand_plan_lookup.values() if p.customer_id}
    wh_ids = {
        j.warehouse_id
        for j in [*direct_job_map.values(), *parent_job_map.values()]
        if j.warehouse_id
    } | {p.warehouse_id for p in cand_plan_lookup.values() if p.warehouse_id}
    customers_map: dict[int, Customer] = (
        {
            cu.id: cu
            for cu in db.scalars(select(Customer).where(Customer.id.in_(cust_ids))).all()
        }
        if cust_ids
        else {}
    )
    customer_names: dict[int, str] = {cid: cu.name for cid, cu in customers_map.items() if cu.name}
    plan_group_zids = {p.group_id for p in cand_plan_lookup.values() if p.group_id}
    target_grp_names_by_zid: dict[str, str] = (
        {
            g.zalo_group_id: (g.name or g.zalo_group_id)
            for g in db.scalars(select(ZaloGroup).where(ZaloGroup.zalo_group_id.in_(plan_group_zids))).all()
        }
        if plan_group_zids
        else {}
    )
    warehouse_names: dict[int, str] = (
        {
            wh.id: wh.name
            for wh in db.scalars(select(Warehouse).where(Warehouse.id.in_(wh_ids))).all()
            if wh.name
        }
        if wh_ids
        else {}
    )
    outbound_previews = _load_outbound_previews_for_cases(db, cases)

    results = []
    for c in cases:
        msg = c.message
        job = direct_job_map.get(c.container_job_id) if c.container_job_id else None
        parent_job = parent_job_map.get(job.parent_job_id) if (job and job.parent_job_id) else None
        details_dict = c.details if isinstance(c.details, dict) else {}
        linked_plan: Optional[TransportPlan] = None
        for pk in (
            details_dict.get("selected_plan_id"),
            details_dict.get("transport_plan_id"),
            details_dict.get("plan_id"),
            (job.raw_fields or {}).get("transport_plan_id") if job and isinstance(job.raw_fields, dict) else None,
        ):
            if pk:
                try:
                    linked_plan = cand_plan_lookup.get(int(pk))
                    if linked_plan:
                        break
                except (ValueError, TypeError):
                    pass

        truck_rec = job.truck_record if job else None
        parent_truck = parent_job.truck_record if parent_job else None
        if truck_rec is None and msg and msg.truck_records:
            truck_rec = msg.truck_records[0]

        prop_changes = details_dict.get("proposed_changes") if isinstance(details_dict.get("proposed_changes"), dict) else {}
        eff_cust_id = (
            (job.customer_id if job else None)
            or (parent_job.customer_id if parent_job else None)
            or (linked_plan.customer_id if linked_plan else None)
        )
        eff_wh_id = (
            (job.warehouse_id if job else None)
            or (parent_job.warehouse_id if parent_job else None)
            or (linked_plan.warehouse_id if linked_plan else None)
        )
        eff_cont = (
            prop_changes.get("container_no")
            or (job.container_no if job else None)
            or (parent_job.container_no if parent_job else None)
            or (linked_plan.container_no if linked_plan else None)
            or details_dict.get("container_no")
        )
        eff_size = (
            (job.container_size if job else None)
            or (parent_job.container_size if parent_job else None)
            or (linked_plan.container_size if linked_plan else None)
            or details_dict.get("container_size")
        )
        eff_seal = (
            prop_changes.get("seal_no")
            or (job.seal_no if job else None)
            or (parent_job.seal_no if parent_job else None)
            or (linked_plan.seal_no if linked_plan else None)
            or details_dict.get("seal_no")
        )
        eff_order = (
            (job.order_type if job else None)
            or (parent_job.order_type if parent_job else None)
            or (linked_plan.order_type if linked_plan else None)
            or details_dict.get("order_type")
        )
        eff_cust_hint = (
            (job.customer_hint if job else None)
            or (customer_names.get(eff_cust_id) if eff_cust_id else None)
            or (linked_plan.customer_name if linked_plan else None)
            or (parent_job.customer_hint if parent_job else None)
            or details_dict.get("customer_hint")
        )
        eff_wh_hint = (
            (job.warehouse_hint if job else None)
            or (warehouse_names.get(eff_wh_id) if eff_wh_id else None)
            or ((linked_plan.warehouse_name or linked_plan.delivery_address) if linked_plan else None)
            or (parent_job.warehouse_hint if parent_job else None)
            or details_dict.get("warehouse_hint")
        )
        eff_truck = (
            prop_changes.get("planned_truck_plate")
            or (truck_rec.truck_plate if truck_rec else None)
            or (parent_truck.truck_plate if parent_truck else None)
            or (linked_plan.planned_truck_plate if linked_plan else None)
            or details_dict.get("truck_plate")
        )
        eff_trailer = (
            prop_changes.get("planned_trailer_plate")
            or (truck_rec.trailer_plate if truck_rec else None)
            or (parent_truck.trailer_plate if parent_truck else None)
            or (linked_plan.planned_trailer_plate if linked_plan else None)
            or details_dict.get("trailer_plate")
        )
        eff_driver = (
            prop_changes.get("driver_name")
            or (truck_rec.driver_name if truck_rec else None)
            or (parent_truck.driver_name if parent_truck else None)
            or (linked_plan.driver_name if linked_plan else None)
            or details_dict.get("driver_name")
        )
        eff_phone = (
            prop_changes.get("driver_phone")
            or (truck_rec.driver_phone if truck_rec else None)
            or (parent_truck.driver_phone if parent_truck else None)
            or (linked_plan.driver_phone if linked_plan else None)
            or details_dict.get("driver_phone")
        )
        eff_eta = (
            (resolve_job_expected_time(db, job) if job else None)
            or (resolve_job_expected_time(db, parent_job) if parent_job else None)
            or (extract_plan_expected_time(linked_plan) if linked_plan else None)
            or details_dict.get("eta")
        )

        merged_msgs = details_dict.get("merged_messages") if isinstance(details_dict.get("merged_messages"), list) else []
        display_raw_text = msg.message_text if msg else None
        if merged_msgs:
            clean_parts = [str(x).strip() for x in merged_msgs if str(x).strip()]
            if display_raw_text and display_raw_text.strip() not in clean_parts:
                clean_parts.append(display_raw_text.strip())
            if clean_parts:
                display_raw_text = "\n---\n".join(clean_parts)
        elif details_dict.get("proposal_text"):
            prop_txt = str(details_dict["proposal_text"]).strip()
            if prop_txt and prop_txt != (display_raw_text or "").strip():
                display_raw_text = f"{prop_txt}\n[Xác nhận] {(display_raw_text or '').strip()}".strip()
        raw_candidates_src = (
            details_dict.get("candidate_plans")
            or (details_dict.get("resolution") or {}).get("candidates")
            or []
        )
        raw_candidates: list[dict[str, Any]] = []
        for cand_item in raw_candidates_src:
            if not isinstance(cand_item, dict):
                continue
            cand_copy = dict(cand_item)
            try:
                p_obj = cand_plan_lookup.get(int(cand_copy["plan_id"])) if cand_copy.get("plan_id") else None
            except (ValueError, TypeError):
                p_obj = None
            if p_obj:
                if not cand_copy.get("plan_date") and p_obj.plan_date:
                    cand_copy["plan_date"] = p_obj.plan_date.isoformat()
                if not cand_copy.get("required_time"):
                    cand_copy["required_time"] = extract_plan_expected_time(p_obj)
            raw_candidates.append(cand_copy)
        if not raw_candidates and details_dict.get("candidate_plan_ids"):
            for pid in details_dict.get("candidate_plan_ids", [])[:10]:
                try:
                    p_obj = cand_plan_lookup.get(int(pid))
                    if p_obj:
                        raw_candidates.append(
                            {
                                "plan_id": str(p_obj.id),
                                "order_code": p_obj.order_code,
                                "order_type": p_obj.order_type,
                                "customer_name": p_obj.customer_name,
                                "warehouse_name": p_obj.warehouse_name or p_obj.delivery_address,
                                "container_no": p_obj.container_no,
                                "plan_date": p_obj.plan_date.isoformat() if p_obj.plan_date else None,
                                "required_time": extract_plan_expected_time(p_obj),
                                "version": p_obj.version,
                                "score": 70,
                                "evidences": ["candidate_plan_id"],
                                "exclusions": [],
                            }
                        )
                except (ValueError, TypeError):
                    pass
        if filter_in_python and c.case_type not in _ACTION_EXEMPT_CASE_TYPES:
            if not _is_review_ready_5_fields(
                eff_truck=eff_truck,
                eff_trailer=eff_trailer,
                eff_cont=eff_cont,
                eff_driver=eff_driver,
                eff_phone=eff_phone,
            ):
                continue

        cust_obj_row = customers_map.get(eff_cust_id) if eff_cust_id else None
        preview_obj = outbound_previews.get(c.id)
        if preview_obj is None:
            plan_tgt_name = (
                target_grp_names_by_zid.get(linked_plan.group_id)
                if linked_plan and linked_plan.group_id
                else None
            )
            preview_obj = _build_review_customer_output_preview(
                case_obj=c,
                details_dict=details_dict,
                linked_plan=linked_plan,
                eff_cont=eff_cont,
                eff_size=eff_size,
                eff_seal=eff_seal,
                eff_order=eff_order,
                eff_cust_hint=eff_cust_hint,
                eff_wh_hint=eff_wh_hint,
                eff_truck=eff_truck,
                eff_trailer=eff_trailer,
                eff_driver=eff_driver,
                eff_phone=eff_phone,
                eff_eta=eff_eta,
                eff_cust_tms_id=str(cust_obj_row.tms_customer_id) if cust_obj_row and cust_obj_row.tms_customer_id else None,
                target_group_name=plan_tgt_name,
            )

        results.append(
            {
                "id": str(c.id),
                "message_id": str(c.message_id),
                "container_job_id": str(c.container_job_id) if c.container_job_id is not None else None,
                "case_type": c.case_type,
                "reason": humanize_reason_text(c.reason) or c.reason,
                "status": c.status,
                "assigned_to": c.assigned_to,
                "priority": details_dict.get("priority", "NORMAL"),
                "candidate_plans": raw_candidates,
                "details": details_dict,
                "resolution": c.resolution,
                "outbound_preview": preview_obj,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                "resolved_by": c.resolved_by,
                "message_context": {
                    "zalo_message_id": msg.zalo_message_id if msg else None,
                    "sender_name": msg.sender_name or (msg.sender_id if msg else None),
                    "group_id": msg.group_id if msg else None,
                    "raw_text": display_raw_text,
                    "sent_at": (msg.zalo_sent_at or msg.received_at).isoformat() if msg else None,
                }
                if msg
                else None,
                "container_details": {
                    "container_no": eff_cont,
                    "container_size": eff_size,
                    "seal_no": eff_seal,
                    "order_type": eff_order,
                    "customer_id": eff_cust_id,
                    "warehouse_id": eff_wh_id,
                    "customer_hint": eff_cust_hint,
                    "warehouse_hint": eff_wh_hint,
                    "truck_plate": eff_truck,
                    "trailer_plate": eff_trailer,
                    "driver_name": eff_driver,
                    "driver_phone": eff_phone,
                    "eta": eff_eta,
                    "validation_status": job.validation_status if job else None,
                    "warnings": (job.raw_fields or {}).get("warnings", []) if job else [],
                }
                if (job or linked_plan or any(v is not None for v in (eff_cont, eff_truck, eff_driver, eff_phone, eff_cust_hint, eff_wh_hint)))
                else None,
            }
        )

    if filter_in_python:
        total = len(results)
        results = results[offset : offset + limit]

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
    _ensure_reviewer_role(current_user)
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
    _ensure_reviewer_role(current_user)
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


def _parse_optional_int(value: Any) -> Optional[int]:
    """Chuyển đổi an toàn giá trị số nguyên (kể cả chuỗi Snowflake ID)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_cancel_target_group_id(
    db: Session,
    *,
    customer_id: Optional[int],
    warehouse_id: Optional[int],
    order_type: Optional[str],
    source_group: Optional[ZaloGroup],
    orig_msg: Optional[ZaloMessage],
    plan: Optional[TransportPlan],
    customer_hint: Optional[str] = None,
) -> Optional[int]:
    """Xác định nhóm Zalo khách hàng nhận thông báo hủy chuyến (ưu tiên plan.group_id, RouteMap, rồi source_group nếu là nhóm khách)."""
    plan_gid = str(plan.group_id).strip() if plan and plan.group_id else None
    target_gid, _ = CarrierFlowService.find_target_zalo_group_safe(
        db=db,
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        order_type=order_type,
        source_group_id_str=orig_msg.group_id if orig_msg else None,
        plan_group_id_str=plan_gid,
        customer_hint=customer_hint,
    )
    if target_gid is None and plan_gid:
        target_gid, _ = CarrierFlowService.find_target_zalo_group_safe(
            db=db,
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            order_type=order_type,
            source_group_id_str=orig_msg.group_id if orig_msg else None,
            plan_group_id_str=None,
            customer_hint=customer_hint,
        )
    if (
        target_gid is None
        and source_group is not None
        and source_group.is_active
        and (source_group.group_role or "").upper() in (GroupRole.CUSTOMER.value, GroupRole.DESTINATION.value)
    ):
        target_gid = source_group.id
    return target_gid


def _apply_plan_cancel_update(
    db: Session,
    *,
    plan: TransportPlan,
    case_obj: ReviewCase,
    actor: str,
    cancel_reason: str,
    now: datetime,
    container_no: Optional[str],
    updated_plan_ids: list[int],
) -> None:
    """Cập nhật ghi chú hủy chuyến, tăng version và ghi ActivityLog cho TransportPlan."""
    if plan.id in updated_plan_ids:
        return
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
            details={"review_case_id": case_obj.id, "container_no": container_no, "reason": cancel_reason},
        )
    )


def _create_cancel_outbound_for_target(
    db: Session,
    *,
    target_gid: int,
    order_type: Optional[str],
    cancel_text: str,
    idempotency_key: str,
    actor: str,
    now: datetime,
    job_id: Optional[int] = None,
) -> int:
    """Tạo bản ghi OutboundMessage thông báo hủy chuyến (tái sử dụng nếu trùng idempotency_key)."""
    existing_om = db.scalar(select(OutboundMessage).where(OutboundMessage.idempotency_key == idempotency_key))
    if existing_om:
        return existing_om.id
    cancel_om = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=target_gid,
        order_type=order_type or "tra",
        message_kind="cancel",
        content=cancel_text,
        idempotency_key=idempotency_key,
        status=OutboundStatus.PENDING_SEND.value,
        approved_by=actor,
        approved_at=now,
        attempt_count=0,
    )
    db.add(cancel_om)
    db.flush()
    if job_id is not None:
        db.add(OutboundMessageItem(outbound_message_id=cancel_om.id, container_job_id=job_id))
    return cancel_om.id


def _resolve_plan_for_cancel_case(
    db: Session,
    case_obj: ReviewCase,
    payload: Optional[ReviewApprovePayload],
) -> Optional[TransportPlan]:
    """Tìm TransportPlan gắn với ca hủy chuyến khi chưa có bản ghi ContainerJob."""
    details = case_obj.details if isinstance(case_obj.details, dict) else {}
    plan_id = _parse_optional_int(
        (payload.selected_plan_id if payload and payload.selected_plan_id else None)
        or details.get("selected_plan_id")
        or details.get("transport_plan_id")
    )
    if plan_id is not None:
        plan = db.get(TransportPlan, plan_id)
        if plan is not None:
            return plan
    cont = str(details.get("container_no") or "").strip().upper()
    if cont:
        return db.scalar(
            select(TransportPlan)
            .where(TransportPlan.container_no == cont)
            .order_by(TransportPlan.id.desc())
        )
    return None


def _approve_cancel_request_case(
    db: Session,
    case_obj: ReviewCase,
    jobs: list[ContainerJob],
    orig_msg: Optional[ZaloMessage],
    actor: str,
    payload: Optional[ReviewApprovePayload],
    is_real_msg: bool,
) -> dict[str, Any]:
    """Xác nhận hủy chuyến: cập nhật local TransportPlan, phát hành thông báo hủy mẫu default_huy.txt và phản hồi nhà xe/khách hàng."""
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
    details = case_obj.details if isinstance(case_obj.details, dict) else {}
    cancelled_labels: list[str] = []

    target_jobs = list(jobs)
    if not target_jobs and details.get("container_no"):
        fallback_job = db.scalar(
            select(ContainerJob)
            .where(ContainerJob.container_no == str(details.get("container_no")).upper())
            .order_by(ContainerJob.id.desc())
        )
        if fallback_job:
            target_jobs.append(fallback_job)

    for job in target_jobs:
        if job.container_no:
            cancelled_labels.append(job.container_no)
        job.validation_status = ValidationStatus.REJECTED.value
        job.routing_status = RoutingStatus.CANCELLED.value
        job.tms_sync_status = TmsSyncStatus.PENDING.value

        # Hủy các outbound chờ duyệt cũ của container này
        for stale in db.scalars(
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id == job.id,
                OutboundMessage.status.in_([
                    OutboundStatus.PENDING_APPROVAL.value,
                    "cho_duyet",
                    OutboundStatus.FAILED.value,
                    "that_bai",
                ]),
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
        if plan is None and len(target_jobs) == 1:
            plan = _resolve_plan_for_cancel_case(db, case_obj, payload)
        if plan is not None:
            _apply_plan_cancel_update(
                db,
                plan=plan,
                case_obj=case_obj,
                actor=actor,
                cancel_reason=cancel_reason,
                now=now,
                container_no=job.container_no or plan.container_no,
                updated_plan_ids=updated_plan_ids,
            )

        # Tạo thông báo hủy chuyến gửi khách hàng dùng template default_huy.txt
        cust_id = job.customer_id or (plan.customer_id if plan else None)
        wh_id = job.warehouse_id or (plan.warehouse_id if plan else None)
        eff_order_type = job.order_type or (plan.order_type if plan else None) or "tra"
        cust_hint = job.customer_hint or (plan.customer_name if plan else None)
        wh_hint = job.warehouse_hint or (plan.warehouse_name if plan else None)
        cust_obj = db.get(Customer, cust_id) if cust_id else None
        wh_obj = db.get(Warehouse, wh_id) if wh_id else None
        tr = job.truck_record
        note_parts = (
            [p for p in [f"Lệnh {plan.order_code}" if plan.order_code else None, f"Booking {plan.booking_no}" if plan.booking_no else None] if p]
            if plan
            else []
        )
        line = ExtractedContainerLine(
            line_no=job.line_no or 1,
            plan_date=plan.plan_date.isoformat() if plan and plan.plan_date else None,
            container_no=job.container_no or (plan.container_no if plan else None),
            container_size=job.container_size or (plan.container_size if plan else None),
            seal_no=job.seal_no or (plan.seal_no if plan else None),
            order_type=eff_order_type,
            warehouse_hint=wh_hint,
            customer_hint=cust_hint,
            truck_plate=(tr.truck_plate if tr else None) or (plan.planned_truck_plate if plan else None),
            trailer_plate=(tr.trailer_plate if tr else None) or (plan.planned_trailer_plate if plan else None),
            driver_name=(tr.driver_name if tr else None) or (plan.driver_name if plan else None),
            driver_phone=(tr.driver_phone if tr else None) or (plan.driver_phone if plan else None),
            note="; ".join(note_parts) if note_parts else None,
        )
        cancel_text = (
            payload.outbound_content.strip()
            if (payload and payload.outbound_content and payload.outbound_content.strip())
            else OutboundTemplateBuilder.build_cancel_notification(
                line=line,
                reason=cancel_reason,
                customer_name=cust_obj.name if cust_obj else (cust_hint or "Quý khách hàng"),
                warehouse_name=wh_obj.name if wh_obj else (wh_hint or "Kho khách hàng"),
                customer_id=cust_obj.tms_customer_id if cust_obj else None,
                plan_date=plan.plan_date if plan else None,
            )
        )
        target_gid = _resolve_cancel_target_group_id(
            db,
            customer_id=cust_id,
            warehouse_id=wh_id,
            order_type=eff_order_type,
            source_group=source_group,
            orig_msg=orig_msg,
            plan=plan,
            customer_hint=cust_hint,
        )
        if target_gid:
            om_id = _create_cancel_outbound_for_target(
                db,
                target_gid=target_gid,
                order_type=eff_order_type,
                cancel_text=cancel_text,
                idempotency_key=f"outbound:cancel:{case_obj.id}:{job.id}",
                actor=actor,
                now=now,
                job_id=job.id,
            )
            pending_send_ids.append(om_id)

    # Nếu chưa có ContainerJob (VD: yêu cầu hủy gắn trực tiếp với TransportPlan), vẫn cập nhật plan và tạo thông báo gửi khách
    if not target_jobs:
        plan = _resolve_plan_for_cancel_case(db, case_obj, payload)
        if plan is not None:
            _apply_plan_cancel_update(
                db,
                plan=plan,
                case_obj=case_obj,
                actor=actor,
                cancel_reason=cancel_reason,
                now=now,
                container_no=plan.container_no,
                updated_plan_ids=updated_plan_ids,
            )
            plan_label = plan.container_no or plan.order_code or plan.booking_no
            if plan_label:
                cancelled_labels.append(plan_label)
            cust_obj = db.get(Customer, plan.customer_id) if plan.customer_id else None
            wh_obj = db.get(Warehouse, plan.warehouse_id) if plan.warehouse_id else None
            note_parts = [p for p in [f"Lệnh {plan.order_code}" if plan.order_code else None, f"Booking {plan.booking_no}" if plan.booking_no else None] if p]
            line = ExtractedContainerLine(
                line_no=1,
                plan_date=plan.plan_date.isoformat() if plan.plan_date else None,
                container_no=plan.container_no,
                container_size=plan.container_size,
                seal_no=plan.seal_no,
                order_type=plan.order_type or "tra",
                warehouse_hint=plan.warehouse_name or plan.delivery_address,
                customer_hint=plan.customer_name,
                truck_plate=plan.planned_truck_plate,
                trailer_plate=plan.planned_trailer_plate,
                driver_name=plan.driver_name,
                driver_phone=plan.driver_phone,
                note="; ".join(note_parts) if note_parts else None,
            )
            cancel_text = (
                payload.outbound_content.strip()
                if (payload and payload.outbound_content and payload.outbound_content.strip())
                else OutboundTemplateBuilder.build_cancel_notification(
                    line=line,
                    reason=cancel_reason,
                    customer_name=cust_obj.name if cust_obj else (plan.customer_name or "Quý khách hàng"),
                    warehouse_name=wh_obj.name if wh_obj else (plan.warehouse_name or "Kho khách hàng"),
                    customer_id=cust_obj.tms_customer_id if cust_obj else None,
                    plan_date=plan.plan_date,
                )
            )
            target_gid = _resolve_cancel_target_group_id(
                db,
                customer_id=plan.customer_id,
                warehouse_id=plan.warehouse_id,
                order_type=plan.order_type,
                source_group=source_group,
                orig_msg=orig_msg,
                plan=plan,
                customer_hint=plan.customer_name,
            )
            if target_gid:
                om_id = _create_cancel_outbound_for_target(
                    db,
                    target_gid=target_gid,
                    order_type=plan.order_type,
                    cancel_text=cancel_text,
                    idempotency_key=f"outbound:cancel:{case_obj.id}:plan:{plan.id}",
                    actor=actor,
                    now=now,
                )
                pending_send_ids.append(om_id)
        else:
            target_gid = _resolve_cancel_target_group_id(
                db,
                customer_id=None,
                warehouse_id=None,
                order_type=None,
                source_group=source_group,
                orig_msg=orig_msg,
                plan=None,
                customer_hint=details.get("group_name"),
            )
            if target_gid:
                raw_cont = str(details.get("container_no") or "").strip().upper() or None
                if raw_cont:
                    cancelled_labels.append(raw_cont)
                line = ExtractedContainerLine(
                    line_no=1,
                    container_no=raw_cont,
                    order_type="tra",
                    customer_hint=details.get("group_name") or (source_group.name if source_group else None),
                )
                cancel_text = (
                    payload.outbound_content.strip()
                    if (payload and payload.outbound_content and payload.outbound_content.strip())
                    else OutboundTemplateBuilder.build_cancel_notification(
                        line=line,
                        reason=cancel_reason,
                        customer_name=details.get("group_name") or (source_group.name if source_group else "Quý khách hàng"),
                        warehouse_name="Kho khách hàng",
                    )
                )
                om_id = _create_cancel_outbound_for_target(
                    db,
                    target_gid=target_gid,
                    order_type="tra",
                    cancel_text=cancel_text,
                    idempotency_key=f"outbound:cancel:{case_obj.id}:case",
                    actor=actor,
                    now=now,
                )
                pending_send_ids.append(om_id)

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
            cont_lbl = ", ".join(cancelled_labels) or "chuyến xe"
            ZaloDispatcher.send_to_group(
                group_id=orig_msg.group_id,
                message=(
                    "[VSICO] - ✅ Đã xác nhận hủy chuyến\n\n"
                    f"📦 Chuyến: {cont_lbl}\n"
                    f"• Người xử lý: {actor}\n"
                    f"• Lý do: {cancel_reason}"
                ),
                quote_msg_id=orig_msg.zalo_message_id,
            )

    DhvtNotificationService.broadcast_dhvt_review_decision(
        db=db,
        case_obj=case_obj,
        action_verb="xác nhận hủy chuyến",
        actor_display=actor,
        reason=cancel_reason,
        is_test_msg=not is_real_msg,
        send_zalo=not bool(payload and payload.skip_dhvt_zalo_broadcast),
    )
    db.commit()

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
    _ensure_reviewer_role(current_user)
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")
    if case_obj.status in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value, "approved", "rejected"):
        raise HTTPException(status_code=409, detail="Ca rà soát đã được xử lý hoàn tất trước đó.")

    actor = _resolve_actor(current_user, payload.operator_name if payload else None)
    # Đề xuất trợ lý phải được duyệt bằng tài khoản Web và còn đúng phiên bản.
    proposal = case_obj.details or {}
    expected_ver = (payload.expected_version if payload else None) or proposal.get("expected_version")
    if proposal.get("expected_version") is not None:
        if not current_user or current_user.role.lower() not in ("admin", "dhvt"):
            raise HTTPException(status_code=403, detail="Cần tài khoản ĐHVT/Admin để duyệt đề xuất trợ lý.")
    if expected_ver is not None:
        plan_id = (payload.selected_plan_id if payload and payload.selected_plan_id else None) or proposal.get("transport_plan_id") or proposal.get("selected_plan_id")
        proposed_plan = db.scalar(select(TransportPlan).where(TransportPlan.id == int(plan_id)).with_for_update().execution_options(populate_existing=True)) if plan_id else None
        if not proposed_plan or proposed_plan.version != int(expected_ver):
            raise HTTPException(status_code=409, detail="Kế hoạch đã thay đổi; kiểm tra lại đề xuất trước khi duyệt.")
    _ensure_not_locked_by_other(case_obj, actor, current_user)

    jobs_to_update: list[ContainerJob] = []
    if case_obj.container_job_id:
        job = db.get(ContainerJob, case_obj.container_job_id)
        if job:
            jobs_to_update.append(job)
    elif case_obj.message_id:
        c_jobs = list(db.scalars(select(ContainerJob).where(ContainerJob.message_id == case_obj.message_id)).all())
        jobs_to_update.extend(c_jobs)

    if not jobs_to_update and case_obj.message_id and (
        (payload and payload.selected_plan_id)
        or proposal.get("selected_plan_id")
        or proposal.get("transport_plan_id")
    ):
        prop_changes = proposal.get("proposed_changes") if isinstance(proposal.get("proposed_changes"), dict) else {}
        tr_new = TruckRecord(
            id=snowflake.generate(),
            message_id=case_obj.message_id,
            truck_plate=(payload.truck_plate if payload and payload.truck_plate else None)
            or prop_changes.get("planned_truck_plate")
            or proposal.get("truck_plate"),
            driver_name=(payload.driver_name if payload and payload.driver_name else None)
            or prop_changes.get("driver_name")
            or proposal.get("driver_name"),
            driver_phone=(payload.driver_phone if payload and payload.driver_phone else None)
            or prop_changes.get("driver_phone")
            or proposal.get("driver_phone"),
        )
        db.add(tr_new)
        db.flush()
        synth_job = ContainerJob(
            id=snowflake.generate(),
            message_id=case_obj.message_id,
            truck_record_id=tr_new.id,
            container_no=(payload.container_no if payload and payload.container_no else None)
            or prop_changes.get("container_no")
            or proposal.get("container_no"),
            seal_no=(payload.seal_no if payload and payload.seal_no else None)
            or prop_changes.get("seal_no")
            or proposal.get("seal_no"),
            order_type=(payload.order_type if payload and payload.order_type else None)
            or proposal.get("order_type")
            or "dong",
            warehouse_hint=proposal.get("warehouse_hint"),
            customer_hint=proposal.get("customer_hint"),
            validation_status=ValidationStatus.VALID.value,
            routing_status=RoutingStatus.PENDING.value,
            tms_sync_status=TmsSyncStatus.PENDING.value,
            raw_fields={"created_from_review": str(case_obj.id)},
        )
        db.add(synth_job)
        db.flush()
        synth_job.truck_record = tr_new
        case_obj.container_job_id = synth_job.id
        jobs_to_update.append(synth_job)

    orig_msg = db.get(ZaloMessage, case_obj.message_id) if case_obj.message_id else None
    is_real_msg = _is_real_source_message(orig_msg)

    # Nhánh riêng: Phê duyệt yêu cầu hủy chuyến (từ Nhà xe hoặc Khách hàng)
    details = case_obj.details if isinstance(case_obj.details, dict) else {}
    req_action = str(details.get("requested_action") or "").upper()
    is_customer_cancel = case_obj.case_type == "CUSTOMER_CHANGE_REQUEST" and (
        req_action == "CANCEL"
        or (not req_action and case_obj.priority == "HIGH")
        or (payload is not None and bool(payload.cancel_reason and payload.cancel_reason.strip()))
    )
    if (
        case_obj.case_type == "CANCEL_REQUEST"
        or (case_obj.case_type == "CARRIER_CANCEL_OR_ISSUE" and req_action == "CANCEL")
        or is_customer_cancel
    ):
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
    tms_sync_statuses: dict[str, str] = {}
    pending_send_ids: list[int] = []
    habit_recorded_any = False

    explicit_cont_override = bool(payload and payload.container_no and payload.container_no.strip())

    for job in jobs_to_update:
        fields_changed, habit_recorded = _apply_payload_edits_to_job(db, job, payload)
        habit_recorded_any = habit_recorded_any or habit_recorded

        job.validation_status = ValidationStatus.VALID.value
        job.routing_status = RoutingStatus.ROUTED.value
        job.tms_sync_status = TmsSyncStatus.PENDING.value

        # Đồng bộ trực tiếp lên TransportPlan được chọn hoặc khớp duy nhất
        selected_plan: Optional[TransportPlan] = None
        target_pid = (
            (payload.selected_plan_id if payload and payload.selected_plan_id else None)
            or proposal.get("selected_plan_id")
            or proposal.get("transport_plan_id")
        )
        if target_pid:
            selected_plan = db.get(TransportPlan, int(target_pid))
            if not selected_plan and payload and payload.selected_plan_id:
                raise HTTPException(
                    status_code=404,
                    detail=f"Không tìm thấy kế hoạch ID={payload.selected_plan_id}.",
                )
        else:
            plan_res = resolve_plan_detailed(db, job, source_group, for_update=True)
            selected_plan = plan_res.plan

        secondary_pid = (
            (payload.secondary_plan_id if payload and payload.secondary_plan_id else None)
            or proposal.get("secondary_plan_id")
            or (proposal.get("resolution") or {}).get("secondary_plan_id")
        )
        secondary_plan: Optional[TransportPlan] = (
            db.get(TransportPlan, int(secondary_pid)) if secondary_pid else None
        )

        tr = job.truck_record
        eff_truck_plate = (tr.truck_plate if tr and tr.truck_plate else None) or (
            selected_plan.planned_truck_plate if selected_plan else None
        )
        eff_trailer_plate = (tr.trailer_plate if tr and tr.trailer_plate else None) or (
            selected_plan.planned_trailer_plate if selected_plan else None
        )
        eff_driver_name = (tr.driver_name if tr and tr.driver_name else None) or (
            selected_plan.driver_name if selected_plan else None
        )
        eff_driver_phone = (tr.driver_phone if tr and tr.driver_phone else None) or (
            selected_plan.driver_phone if selected_plan else None
        )
        if tr is not None:
            if not tr.truck_plate and eff_truck_plate:
                tr.truck_plate = clean_plate(eff_truck_plate) or eff_truck_plate
            if not tr.trailer_plate and eff_trailer_plate:
                tr.trailer_plate = clean_plate(eff_trailer_plate) or eff_trailer_plate
            if not tr.driver_name and eff_driver_name:
                tr.driver_name = eff_driver_name
            if not tr.driver_phone and eff_driver_phone:
                tr.driver_phone = eff_driver_phone

        # Chặn duyệt gửi khách và chặn đẩy TMS nếu thông tin xe/moóc/tài xế/SĐT vẫn đang thiếu hoặc sai định dạng
        approval_defects: list[str] = []
        norm_eff_truck = clean_plate(eff_truck_plate) if eff_truck_plate else None
        if not norm_eff_truck:
            approval_defects.append("Biển số xe đang trống")
        elif not re.match(r"^\d{2}[A-Z]{1,2}-\d{3}\.\d{2}$", norm_eff_truck):
            known_veh = db.scalar(
                select(Vehicle.id).where(
                    Vehicle.is_active.is_(True),
                    Vehicle.plate_no.in_([eff_truck_plate, norm_eff_truck, compact_plate(norm_eff_truck) or ""]),
                )
            )
            if not known_veh:
                approval_defects.append(f"Biển số xe '{eff_truck_plate}' sai định dạng (cần đủ 5 chữ số)")

        if eff_trailer_plate:
            norm_eff_trailer = clean_plate(eff_trailer_plate) or eff_trailer_plate
            if not re.match(r"^\d{2}[A-Z]?R[M]?-\d{3}\.\d{2}$", norm_eff_trailer):
                known_tr = db.scalar(
                    select(Trailer.id).where(
                        Trailer.is_active.is_(True),
                        Trailer.normalized_plate == (compact_plate(norm_eff_trailer) or ""),
                    )
                )
                if not known_tr:
                    approval_defects.append(f"Biển số rơ-moóc '{eff_trailer_plate}' sai định dạng (cần đủ 5 chữ số)")

        if not eff_driver_name or len(str(eff_driver_name).strip()) < 2:
            approval_defects.append("Tên tài xế đang trống")

        norm_eff_phone = clean_phone(eff_driver_phone) if eff_driver_phone else None
        if not norm_eff_phone:
            approval_defects.append("SĐT tài xế đang trống")
        elif not is_valid_phone_list(norm_eff_phone):
            approval_defects.append(f"SĐT tài xế '{eff_driver_phone}' không hợp lệ (cần đúng 10 chữ số bắt đầu bằng 0)")

        if approval_defects:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail=f"Không thể duyệt gửi khách khi dữ liệu còn thiếu/sai: {'; '.join(approval_defects)}. Vui lòng sửa đúng thông tin trước khi duyệt.",
            )

        sync_outcomes: list[Any] = []
        if selected_plan is not None:
            if not job.container_no and selected_plan.container_no:
                job.container_no = selected_plan.container_no
            if not job.container_size and selected_plan.container_size:
                job.container_size = selected_plan.container_size
            if not job.seal_no and selected_plan.seal_no:
                job.seal_no = selected_plan.seal_no
            if not job.customer_id and selected_plan.customer_id:
                job.customer_id = selected_plan.customer_id
            if not job.customer_hint and selected_plan.customer_name:
                job.customer_hint = selected_plan.customer_name
            if not job.warehouse_id and selected_plan.warehouse_id:
                job.warehouse_id = selected_plan.warehouse_id
            if (
                (payload is None or payload.save_warehouse_habit)
                and selected_plan.warehouse_id
                and (job.warehouse_hint or proposal.get("warehouse_hint"))
            ):
                hint_str = str(job.warehouse_hint or proposal.get("warehouse_hint")).strip()
                alias_rec = DhvtNotificationService.record_warehouse_habit(
                    db, hint_str, selected_plan.warehouse_id
                )
                habit_recorded_any = habit_recorded_any or (alias_rec is not None)
            if not job.warehouse_hint and selected_plan.delivery_address:
                job.warehouse_hint = selected_plan.delivery_address
            if secondary_plan is not None and secondary_plan.id != selected_plan.id:
                ro_p = secondary_plan if (secondary_plan.order_type or "").lower() in ("tra", "return", "ro") else selected_plan
                lo_p = selected_plan if ro_p is secondary_plan else secondary_plan
                ro_out, lo_out = sync_combined_ro_to_lo_plans(
                    db=db,
                    job=job,
                    ro_plan=ro_p,
                    lo_plan=lo_p,
                    actor_id=actor,
                    allow_plan_override=True,
                )
                sync_outcomes.extend([ro_out, lo_out])
                synced_plan_ids.extend([ro_out.plan_id, lo_out.plan_id])
                if ro_out.mode in ("FILLED", "UPDATED"):
                    tms_sync_statuses[str(ro_p.id)] = sync_plan_to_tms(
                        db,
                        ro_p,
                        job=job,
                        changed_fields=ro_out.changed_fields,
                        before_values=ro_out.before_values,
                        allow_container_override=False,
                        actor_id=actor,
                    )
                if lo_out.mode in ("FILLED", "UPDATED"):
                    prev_c = (
                        lo_out.before_values.get("container_no")
                        if "container_no" in lo_out.before_values
                        else lo_p.container_no
                    )
                    tms_sync_statuses[str(lo_p.id)] = sync_plan_to_tms(
                        db,
                        lo_p,
                        job=job,
                        changed_fields=lo_out.changed_fields,
                        before_values=lo_out.before_values,
                        previous_container_no=prev_c,
                        allow_container_override=explicit_cont_override,
                        actor_id=actor,
                    )
            else:
                sync_out = sync_job_to_local_plan(
                    db=db,
                    job=job,
                    plan=selected_plan,
                    allow_plan_override=True,
                    actor_id=actor,
                )
                sync_outcomes.append(sync_out)
                synced_plan_ids.append(sync_out.plan_id)
                pending_names = (
                    (job.raw_fields or {}).get("tms_pending_fields")
                    if isinstance(job.raw_fields, dict)
                    else None
                )
                if sync_out.mode in ("FILLED", "UPDATED"):
                    prev_c = (
                        sync_out.before_values.get("container_no")
                        if "container_no" in sync_out.before_values
                        else selected_plan.container_no
                    )
                    tms_sync_statuses[str(selected_plan.id)] = sync_plan_to_tms(
                        db,
                        selected_plan,
                        job=job,
                        changed_fields=sync_out.changed_fields,
                        before_values=sync_out.before_values,
                        previous_container_no=prev_c,
                        allow_container_override=explicit_cont_override,
                        actor_id=actor,
                    )
                elif pending_names:
                    tms_sync_statuses[str(selected_plan.id)] = sync_plan_to_tms(
                        db,
                        selected_plan,
                        job=job,
                        allow_container_override=explicit_cont_override,
                        actor_id=actor,
                    )

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
        raw_f = dict(job.raw_fields) if isinstance(job.raw_fields, dict) else {}
        is_plan_derived_eta = (
            isinstance(raw_f.get("field_evidences"), dict)
            and raw_f["field_evidences"].get("eta_time") == "transport_plan"
        )
        eff_eta = (
            (payload.eta.strip() if payload and payload.eta and payload.eta.strip() else None)
            or (None if is_plan_derived_eta else raw_f.get("eta"))
            or extract_plan_expected_time(selected_plan)
            or extract_plan_expected_time(secondary_plan)
            or resolve_job_expected_time(db, job, selected_plan)
        )
        if eff_eta and raw_f.get("eta") != eff_eta:
            raw_f["eta"] = eff_eta
            raw_f["eta_text"] = raw_f.get("eta_text") or eff_eta
            job.raw_fields = raw_f
        if tr is not None and eff_eta:
            tr_raw = dict(tr.raw_data) if isinstance(tr.raw_data, dict) else {}
            if not tr_raw.get("eta"):
                tr_raw["eta"] = eff_eta
                tr_raw["eta_text"] = tr_raw.get("eta_text") or eff_eta
                tr.raw_data = tr_raw

        rebuilt_line = ExtractedContainerLine(
            line_no=job.line_no or 1,
            plan_date=(
                selected_plan.plan_date.isoformat()
                if selected_plan and selected_plan.plan_date
                else raw_f.get("plan_date")
            ),
            container_no=job.container_no or (selected_plan.container_no if selected_plan else None),
            container_size=job.container_size or (selected_plan.container_size if selected_plan else None),
            seal_no=job.seal_no or (selected_plan.seal_no if selected_plan else None),
            order_type=job.order_type or (selected_plan.order_type if selected_plan else None) or "tra",
            warehouse_hint=wh_obj.name if wh_obj else (job.warehouse_hint or (selected_plan.warehouse_name or selected_plan.delivery_address if selected_plan else None)),
            customer_hint=cust_obj.name if cust_obj else (job.customer_hint or (selected_plan.customer_name if selected_plan else None)),
            truck_plate=norm_eff_truck,
            trailer_plate=clean_plate(eff_trailer_plate) if eff_trailer_plate else None,
            driver_name=eff_driver_name,
            driver_phone=norm_eff_phone,
            eta_time=eff_eta,
        )
        change_labels = {
            "planned_truck_plate": "Biển số xe",
            "truck_plate": "Biển số xe",
            "planned_trailer_plate": "Biển số rơ-moóc",
            "trailer_plate": "Biển số rơ-moóc",
            "driver_name": "Lái xe",
            "driver_phone": "SĐT tài xế",
            "container_no": "Số container",
            "seal_no": "Số chì",
            "eta": "Giờ dự kiến",
            "required_time": "Giờ dự kiến",
            "delivery_address": "Điểm giao/nhận",
        }
        changes_list: list[str] = []
        seen_change_labels: set[str] = set()
        for so in sync_outcomes:
            for fk, new_v in (getattr(so, "changed_fields", None) or {}).items():
                lbl = change_labels.get(fk)
                if not lbl or lbl in seen_change_labels:
                    continue
                old_v = (getattr(so, "before_values", None) or {}).get(fk)
                old_str = str(old_v).strip() if old_v not in (None, "") else "Chưa có"
                new_str = str(new_v).strip() if new_v not in (None, "") else "Chưa có"
                if old_str != new_str:
                    changes_list.append(f"- {lbl}: {old_str} -> {new_str}")
                    seen_change_labels.add(lbl)
        if not changes_list and isinstance(proposal.get("proposed_changes"), dict):
            for fk, new_v in proposal["proposed_changes"].items():
                lbl = change_labels.get(fk)
                if not lbl or lbl in seen_change_labels:
                    continue
                new_str = str(new_v).strip() if new_v not in (None, "") else "Chưa có"
                changes_list.append(f"- {lbl}: -> {new_str}")
                seen_change_labels.add(lbl)

        prior_sent_exists = False
        if selected_plan is not None or job.container_no:
            sent_out_q = (
                select(OutboundMessage.id)
                .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
                .join(ContainerJob, OutboundMessageItem.container_job_id == ContainerJob.id)
                .where(
                    OutboundMessage.status == OutboundStatus.SENT.value,
                    OutboundMessage.message_kind != "answer",
                    ContainerJob.id != job.id,
                    ContainerJob.container_no == (job.container_no or (selected_plan.container_no if selected_plan else "")),
                )
                .limit(1)
            )
            prior_sent_exists = db.scalar(sent_out_q) is not None

        is_update_outbound = bool(
            case_obj.case_type == "REVIEW_CHANGE_AFTER_SENT"
            or (changes_list and prior_sent_exists)
        )
        cust_name_disp = cust_obj.name if cust_obj else (job.customer_hint or "Quý khách hàng")
        wh_name_disp = wh_obj.name if wh_obj else (job.warehouse_hint or "Kho khách hàng")
        cust_tms_id = cust_obj.tms_customer_id if cust_obj else None
        plan_dt = selected_plan.plan_date if selected_plan else None
        if is_update_outbound:
            rebuilt_content = OutboundTemplateBuilder.build_update_notification(
                line=rebuilt_line,
                changes_list=changes_list or ["- Cập nhật thông tin điều vận"],
                customer_name=cust_name_disp,
                warehouse_name=wh_name_disp,
                customer_id=cust_tms_id,
                plan_date=plan_dt,
            )
        else:
            rebuilt_content = OutboundTemplateBuilder.build_customer_notification(
                line=rebuilt_line,
                customer_name=cust_name_disp,
                warehouse_name=wh_name_disp,
                customer_id=cust_tms_id,
                plan_date=plan_dt,
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
            if target_id is None and not synced_plan_ids:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Chưa có định tuyến khách hàng hoặc kế hoạch TMS hợp lệ; cập nhật danh mục trước khi duyệt.",
                )
            if target_id is not None:
                new_om = OutboundMessage(
                    id=snowflake.generate(),
                    target_group_id=target_id,
                    order_type=job.order_type or "tra",
                    message_kind="update" if is_update_outbound else "thong_bao_xe",
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
            elif (fields_changed or selected_plan is not None or is_update_outbound) and (
                out_msg.message_kind != "update" or is_update_outbound
            ):
                out_msg.content = rebuilt_content
                if is_update_outbound:
                    out_msg.message_kind = "update"
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
        "tms_sync_statuses": tms_sync_statuses,
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
        plates = [j.truck_record.truck_plate for j in jobs_to_update if j.truck_record and j.truck_record.truck_plate]
        order_codes = []
        for pid in synced_plan_ids:
            p_obj = db.get(TransportPlan, pid)
            if p_obj and p_obj.order_code and p_obj.order_code not in order_codes:
                order_codes.append(p_obj.order_code)
        order_txt = f"chuyến {', '.join(order_codes)}" if order_codes else "chuyến xe"
        cont_txt = f" - Cont {', '.join(conts)}" if conts else ""
        plate_txt = f" - Xe {', '.join(plates)}" if plates else ""
        ZaloDispatcher.send_to_group(
            group_id=orig_msg.group_id,
            message=(
                "[VSICO] - ✅ Đã xác nhận thông tin điều xe\n\n"
                f"• Lệnh: {order_txt}{cont_txt}{plate_txt}\n\n"
                "Hệ thống đã cập nhật kế hoạch vận chuyển."
            ),
            quote_msg_id=orig_msg.zalo_message_id,
        )

    from src.handlers.dhvt_service import _resolve_reviewer_display_name

    actor_display = _resolve_reviewer_display_name(
        payload.operator_name if payload and getattr(payload, "operator_name", None) else None,
        current_user.full_name if current_user and current_user.full_name else actor,
    )
    has_manual_edits = bool(
        payload
        and any(
            getattr(payload, f, None)
            for f in ("truck_plate", "trailer_plate", "driver_name", "driver_phone", "container_no", "seal_no")
        )
    )
    DhvtNotificationService.broadcast_dhvt_review_decision(
        db=db,
        case_obj=case_obj,
        action_verb="sửa và duyệt" if has_manual_edits else "duyệt",
        actor_display=actor_display,
        is_test_msg=not is_real_msg,
        send_zalo=not bool(payload and payload.skip_dhvt_zalo_broadcast),
    )
    db.commit()

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
    _ensure_reviewer_role(current_user)
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")
    if case_obj.status in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value, "approved", "rejected"):
        raise HTTPException(status_code=409, detail="Ca rà soát đã được xử lý hoàn tất trước đó.")

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
                OutboundMessage.status.in_([
                    OutboundStatus.PENDING_APPROVAL.value,
                    "cho_duyet",
                    OutboundStatus.FAILED.value,
                    "that_bai",
                ]),
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

    source_group = (
        db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == orig_msg.group_id))
        if orig_msg
        else None
    )
    reject_outbound_id: Optional[int] = None
    if (
        source_group
        and source_group.is_active
        and (source_group.group_role or "").upper() in (GroupRole.CUSTOMER.value, GroupRole.DESTINATION.value)
    ):
        details = case_obj.details if isinstance(case_obj.details, dict) else {}
        plan = _resolve_plan_for_cancel_case(db, case_obj, None)
        conts = ", ".join(j.container_no for j in jobs_to_cancel if j.container_no)
        detail_conts = details.get("containers") if isinstance(details.get("containers"), list) else []
        target_label = (
            conts
            or (plan.order_code if plan and plan.order_code else None)
            or (plan.container_no if plan and plan.container_no else None)
            or (plan.booking_no if plan and plan.booking_no else None)
            or (str(details.get("container_no")).strip() if details.get("container_no") else None)
            or (", ".join(str(c) for c in detail_conts if c) if detail_conts else None)
            or "chuyến vận chuyển"
        )
        reject_key = f"outbound:reject:{case_obj.id}"
        existing_reject_om = db.scalar(
            select(OutboundMessage).where(OutboundMessage.idempotency_key == reject_key)
        )
        if existing_reject_om:
            reject_outbound_id = existing_reject_om.id
        else:
            order_type = (
                (jobs_to_cancel[0].order_type if jobs_to_cancel else None)
                or (plan.order_type if plan else None)
                or "tra"
            )
            reject_om = OutboundMessage(
                id=snowflake.generate(),
                target_group_id=source_group.id,
                order_type=order_type,
                message_kind="answer",
                content=(
                    f"[VSICO] ĐHVT chưa thể thực hiện yêu cầu thay đổi/hủy cho {target_label}. "
                    f"Lý do: {reject_reason}. Vui lòng liên hệ ĐHVT nếu cần hỗ trợ thêm."
                ),
                idempotency_key=reject_key,
                status=OutboundStatus.PENDING_SEND.value,
                approved_by=actor,
                approved_at=now,
                attempt_count=0,
            )
            db.add(reject_om)
            db.flush()
            reject_outbound_id = reject_om.id
        case_obj.resolution = {
            **(case_obj.resolution or {}),
            "reject_outbound_ids": [reject_outbound_id],
        }

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
        if source_group and not source_group.is_test:
            if reject_outbound_id is not None:
                from src.infrastructure.outbox_worker import drain_outbox

                drain_outbox(lambda: nullcontext(db), [reject_outbound_id])
            elif source_group.group_role.upper() in (GroupRole.CARRIER.value, GroupRole.SOURCE.value):
                conts = ", ".join(j.container_no for j in jobs_to_cancel if j.container_no) or "lượt xe"
                ZaloDispatcher.send_to_group(
                    group_id=orig_msg.group_id,
                    message=(
                        "[VSICO] - ⚠️ Cần kiểm tra lại thông tin điều xe\n\n"
                        f"📦 Chuyến: {conts}\n"
                        f"• Lý do từ chối: {reject_reason}\n\n"
                        "Anh/chị vui lòng rà soát và gửi lại giúp hệ thống nhé."
                    ),
                    quote_msg_id=orig_msg.zalo_message_id,
                )

    from src.handlers.dhvt_service import _resolve_reviewer_display_name

    actor_display = _resolve_reviewer_display_name(
        payload.operator_name if payload and getattr(payload, "operator_name", None) else None,
        current_user.full_name if current_user and current_user.full_name else actor,
    )
    DhvtNotificationService.broadcast_dhvt_review_decision(
        db=db,
        case_obj=case_obj,
        action_verb="từ chối",
        actor_display=actor_display,
        reason=reject_reason,
        is_test_msg=not (orig_msg and _is_real_source_message(orig_msg)),
        send_zalo=not bool(payload and payload.skip_dhvt_zalo_broadcast),
    )
    db.commit()

    return {
        "ok": True,
        "status": "REJECTED",
        "review_id": review_id,
        "message": f"Đã từ chối ca rà soát ID={review_id} và hủy thông báo gửi khách thành công.",
    }
