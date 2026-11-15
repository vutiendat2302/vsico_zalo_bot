"""Đối chiếu và cập nhật kế hoạch vận chuyển nội bộ (`transport_plans`) khi chưa kết nối TMS.

Tuân thủ quy tắc Mục II.1.1 & S -> C1 trong `backend/zalo.md`:
1. Tìm duy nhất 1 dòng kế hoạch thuộc nhà xe theo `container_no`; nếu chưa thấy cont,
   kiểm tra xem nhà xe có duy nhất 1 dòng trống `container_no` khớp loại lệnh để gán cont mới.
2. So sánh từng trường giữa thông tin xe báo và dòng kế hoạch hiện có:
   - Trường trên `transport_plans` đang trống: Điền mới giá trị (`FILL`).
   - Trường trên `transport_plans` đã có dữ liệu và giống hệt: Không ghi trùng (`NOOP`).
   - Trường xe/tài xế/giờ hẹn đã có và khác hợp lệ: Cập nhật đè khi thỏa điều kiện (`UPDATE`),
     tăng `version`, đặt `tms_sync_status = 'PENDING'` và ghi rõ `cũ -> mới` vào `activity_logs`.
   - Lệch trường cố định của kế hoạch (như `seal_no` có sẵn, `order_type`, `customer_id`):
     Không tự ý ghi đè; trả trạng thái `CONFLICT` để tạo ca chờ ĐHVT xử lý trên Web.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import unicodedata
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.rules import clean_container, clean_phone, compact_plate, mask_phone
from src.infrastructure.models import (
    ActivityLog,
    ContainerJob,
    TmsSyncLog,
    TransportPlan,
    ZaloGroup,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiClient, TmsApiError


@dataclass
class PlanResolutionResult:
    """Kết quả tìm dòng kế hoạch nội bộ khớp với chuyến xe."""

    plan: Optional[TransportPlan]
    status: str
    reason: Optional[str] = None
    candidate_plan_ids: list[int] = field(default_factory=list)


@dataclass
class PlanSyncOutcome:
    """Kết quả đồng bộ dữ liệu ContainerJob lên bảng `transport_plans`."""

    mode: str  # FILLED | UPDATED | NOOP | CONFLICT
    plan_id: int
    filled_fields: list[str] = field(default_factory=list)
    updated_fields: list[dict[str, str]] = field(default_factory=list)
    conflict_reasons: list[str] = field(default_factory=list)


def _norm_order(val: Optional[str]) -> str:
    """Chuẩn hóa loại lệnh về `'dong'` hoặc `'tra'` để so sánh nhất quán."""
    raw = (val or "").strip().lower()
    if raw in ("load", "dong", "xuat"):
        return "dong"
    if raw in ("return", "tra", "nhap"):
        return "tra"
    return raw


def _norm_text(val: Optional[str]) -> str:
    """Chuẩn hóa chuỗi tiếng Việt không dấu viết thường phục vụ so sánh tên nhà xe."""
    if not val:
        return ""
    decomposed = unicodedata.normalize("NFD", val.strip())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.replace("đ", "d").replace("Đ", "D").lower().split())


def _is_blank(val: Optional[str]) -> bool:
    """Kiểm tra giá trị chuỗi trên kế hoạch có đang trống hay không."""
    return val is None or not str(val).strip()


def _narrow_plans_by_context(plans: list[TransportPlan], job: ContainerJob) -> list[TransportPlan]:
    """Thu hẹp danh sách kế hoạch ứng viên theo khách hàng, kho và loại lệnh của job."""
    candidates = list(plans)
    if len(candidates) <= 1:
        return candidates

    job_order = _norm_order(job.order_type)
    if job_order:
        matched_order = [p for p in candidates if _norm_order(p.order_type) == job_order]
        if matched_order:
            candidates = matched_order

    if len(candidates) > 1 and job.customer_id:
        matched_cust = [p for p in candidates if p.customer_id == job.customer_id]
        if matched_cust:
            candidates = matched_cust

    if len(candidates) > 1 and job.warehouse_id:
        matched_wh = [p for p in candidates if p.warehouse_id == job.warehouse_id]
        if matched_wh:
            candidates = matched_wh

    return candidates


def _filter_plans_for_carrier(plans: list[TransportPlan], group: ZaloGroup) -> list[TransportPlan]:
    """Lọc danh sách kế hoạch thuộc nhà xe của nhóm gửi (chặt theo carrier_id hoặc tên khi id trống)."""
    cid = int(group.carrier_id) if group.carrier_id and str(group.carrier_id).isdigit() else None
    group_cname = _norm_text(group.carrier_name)
    matched: list[TransportPlan] = []
    for plan in plans:
        if plan.carrier_id is not None:
            if cid is not None and plan.carrier_id == cid:
                matched.append(plan)
        elif group_cname:
            p_cname = _norm_text(plan.fleet_partner or plan.carrier_name)
            if p_cname and (group_cname in p_cname or p_cname in group_cname):
                matched.append(plan)
    return matched


def resolve_plan_detailed(
    db: Session,
    job: ContainerJob,
    group: ZaloGroup,
    for_update: bool = True,
) -> PlanResolutionResult:
    """Tìm duy nhất dòng kế hoạch thuộc nhà xe theo container hoặc gán dòng trống khớp loại lệnh."""
    cid = int(group.carrier_id) if group.carrier_id and str(group.carrier_id).isdigit() else None
    has_carrier_id = cid is not None
    has_carrier_name = bool(_norm_text(group.carrier_name))

    raw = dict(job.raw_fields or {})
    linked_id = raw.get("transport_plan_id")
    if linked_id:
        stmt_linked = select(TransportPlan).where(TransportPlan.id == int(linked_id))
        if for_update:
            stmt_linked = stmt_linked.with_for_update()
        linked_plan = db.scalar(stmt_linked)
        if linked_plan:
            if cid is None or linked_plan.carrier_id is None or linked_plan.carrier_id == cid:
                return PlanResolutionResult(plan=linked_plan, status="MATCHED_LINKED")

    cont = clean_container(job.container_no) if job.container_no else None
    if cont:
        stmt_cont = select(TransportPlan).where(TransportPlan.container_no == cont)
        if for_update:
            stmt_cont = stmt_cont.with_for_update()
        all_cont_plans = list(db.scalars(stmt_cont).all())
        if has_carrier_id or has_carrier_name:
            by_cont = _filter_plans_for_carrier(all_cont_plans, group)
            if not by_cont:
                # Cho phép khớp kế hoạch chưa gán nhà xe (carrier_id IS NULL và không ghi fleet_partner)
                by_cont = [
                    p
                    for p in all_cont_plans
                    if p.carrier_id is None and not _norm_text(p.fleet_partner or p.carrier_name)
                ]
        else:
            by_cont = all_cont_plans
        by_cont = _narrow_plans_by_context(by_cont, job)
        if len(by_cont) == 1:
            return PlanResolutionResult(plan=by_cont[0], status="MATCHED_CONTAINER")
        if len(by_cont) > 1:
            return PlanResolutionResult(
                plan=None,
                status="MULTIPLE_PLANS",
                reason=f"Tìm thấy {len(by_cont)} dòng kế hoạch trùng cont {cont}.",
                candidate_plan_ids=[p.id for p in by_cont],
            )

    if not has_carrier_id and not has_carrier_name:
        return PlanResolutionResult(
            plan=None,
            status="CARRIER_UNREGISTERED",
            reason="Nhóm nguồn chưa được gán nhà xe phụ trách.",
        )

    # Bước J2: Không thấy cont -> kiểm tra xem nhà xe có duy nhất 1 dòng kế hoạch trống cont khớp loại lệnh không
    job_order = _norm_order(job.order_type)
    stmt_empty = select(TransportPlan).where(
        or_(TransportPlan.container_no.is_(None), TransportPlan.container_no == "")
    )
    if for_update:
        stmt_empty = stmt_empty.with_for_update()
    empty_candidates = _filter_plans_for_carrier(list(db.scalars(stmt_empty).all()), group)
    if job_order:
        empty_candidates = [p for p in empty_candidates if _norm_order(p.order_type) == job_order]
    empty_candidates = _narrow_plans_by_context(empty_candidates, job)

    if len(empty_candidates) == 1:
        return PlanResolutionResult(plan=empty_candidates[0], status="EMPTY_CONTAINER_SLOT")
    if len(empty_candidates) > 1:
        return PlanResolutionResult(
            plan=None,
            status="MULTIPLE_EMPTY_PLANS",
            reason=f"Nhà xe có {len(empty_candidates)} dòng kế hoạch đang trống container; cần ĐHVT chọn đúng dòng.",
            candidate_plan_ids=[p.id for p in empty_candidates],
        )

    return PlanResolutionResult(
        plan=None,
        status="NO_MATCHING_PLAN",
        reason=f"Không tìm thấy dòng kế hoạch phù hợp cho container {cont or 'N/A'} của nhà xe.",
    )


def resolve_plan(db: Session, job: ContainerJob, group: ZaloGroup) -> TransportPlan | None:
    """Chọn duy nhất kế hoạch thuộc nhà xe; giữ tương thích ngược cho caller hiện có."""
    return resolve_plan_detailed(db=db, job=job, group=group, for_update=True).plan


def sync_job_to_local_plan(
    db: Session,
    job: ContainerJob,
    plan: TransportPlan,
    allow_plan_override: bool = False,
    actor_id: str = "vsico_bot",
) -> PlanSyncOutcome:
    """Điền mới các trường trống và cập nhật trường xe đã có trên `transport_plans` khi thỏa mãn.

    Quy tắc:
    - Nếu kế hoạch đã có sẵn `seal_no`, `order_type`, `customer_id` khác với tin báo và chưa được ĐHVT
      xác nhận ghi đè (`allow_plan_override=False`): trả `CONFLICT`, không tự ghi đè.
    - Nếu trường trên kế hoạch đang trống: điền mới (`filled_fields`).
    - Nếu trường xe/tài xế/giờ hẹn trên kế hoạch đã có giá trị khác và bản ghi đạt `VALID` (hoặc ĐHVT duyệt):
      cập nhật mới và lưu diff `cũ -> mới` (`updated_fields`).
    - Nếu mọi trường giống hệt: không tăng `version` (`NOOP`).
    """
    raw = dict(job.raw_fields or {})
    conflicts: list[str] = []

    if plan.customer_id and job.customer_id and plan.customer_id != job.customer_id and not allow_plan_override:
        conflicts.append(f"Lệch khách hàng so với kế hoạch (#{plan.customer_id} / #{job.customer_id})")

    plan_seal_norm = re.sub(r"[^A-Za-z0-9]", "", plan.seal_no or "").upper()
    job_seal_norm = re.sub(r"[^A-Za-z0-9]", "", job.seal_no or "").upper()
    if plan_seal_norm and job_seal_norm and plan_seal_norm != job_seal_norm and not allow_plan_override:
        conflicts.append(f"Lệch số chì kế hoạch (Kế hoạch: {plan.seal_no} / Báo xe: {job.seal_no})")

    if conflicts:
        return PlanSyncOutcome(
            mode="CONFLICT",
            plan_id=plan.id,
            conflict_reasons=conflicts,
        )

    can_update_existing = allow_plan_override or (job.validation_status == "VALID")
    truck = job.truck_record
    eta_val = str(raw.get("eta") or "").strip() or (
        job.estimated_at.strftime("%H:%M %d/%m/%Y") if job.estimated_at else None
    )

    filled_fields: list[str] = []
    updated_fields: list[dict[str, str]] = []

    def _apply_field(
        attr_name: str,
        label: str,
        new_val: Optional[str],
        normalizer: Any,
        allow_update: bool = True,
    ) -> None:
        if _is_blank(new_val):
            return
        cur_val = getattr(plan, attr_name)
        if _is_blank(cur_val):
            setattr(plan, attr_name, str(new_val).strip())
            filled_fields.append(attr_name)
            return
        if normalizer(cur_val) == normalizer(new_val):
            return
        if allow_update and can_update_existing:
            updated_fields.append(
                {
                    "field": attr_name,
                    "label": label,
                    "old": str(cur_val),
                    "new": str(new_val).strip(),
                }
            )
            setattr(plan, attr_name, str(new_val).strip())

    _apply_field(
        "container_no",
        "Số container",
        clean_container(job.container_no) if job.container_no else None,
        lambda v: clean_container(str(v)) or "",
        allow_update=allow_plan_override,
    )
    _apply_field(
        "container_size",
        "Kích thước container",
        job.container_size,
        lambda v: str(v).strip().upper(),
        allow_update=True,
    )
    _apply_field(
        "seal_no",
        "Số chì",
        job.seal_no,
        lambda v: re.sub(r"[^A-Za-z0-9]", "", str(v)).upper(),
        allow_update=allow_plan_override,
    )

    if truck:
        _apply_field(
            "planned_truck_plate",
            "Biển số xe",
            truck.truck_plate,
            lambda v: compact_plate(str(v)) or "",
            allow_update=True,
        )
        _apply_field(
            "driver_name",
            "Tài xế",
            truck.driver_name,
            lambda v: " ".join(str(v).lower().split()),
            allow_update=True,
        )
        _apply_field(
            "driver_phone",
            "SĐT tài xế",
            truck.driver_phone,
            lambda v: clean_phone(str(v)) or re.sub(r"\D", "", str(v)),
            allow_update=True,
        )

    if eta_val:
        prev_time = plan.required_time
        _apply_field(
            "required_time",
            "Giờ đến dự kiến",
            eta_val,
            lambda v: " ".join(str(v).lower().split()),
            allow_update=True,
        )
        if _is_blank(plan.eta) or plan.eta != plan.required_time or prev_time != plan.required_time:
            plan.eta = plan.required_time

    if plan.warehouse_id is None and job.warehouse_id:
        plan.warehouse_id = job.warehouse_id
        filled_fields.append("warehouse_id")
    if plan.customer_id is None and job.customer_id:
        plan.customer_id = job.customer_id
        filled_fields.append("customer_id")

    if not filled_fields and not updated_fields:
        if raw.get("transport_plan_id") != plan.id:
            job.raw_fields = {**raw, "transport_plan_id": plan.id}
        return PlanSyncOutcome(mode="NOOP", plan_id=plan.id)

    plan.version += 1
    plan.tms_sync_status = "PENDING"
    plan.updated_at = datetime.now(timezone.utc)
    job.tms_sync_status = "PENDING"
    job.raw_fields = {
        **raw,
        "transport_plan_id": plan.id,
        "local_plan_updated": True,
        "local_plan_version": plan.version,
    }

    action_name = "PLAN_VEHICLE_UPDATED" if updated_fields else "PLAN_VEHICLE_FILLED"
    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=actor_id,
            action=action_name,
            entity_type="transport_plan",
            entity_id=str(plan.id),
            details={
                "job_id": str(job.id),
                "container_no": plan.container_no,
                "version": plan.version,
                "filled_fields": filled_fields,
                "updated_fields": updated_fields,
                "sync": "PENDING",
            },
        )
    )
    return PlanSyncOutcome(
        mode="UPDATED" if updated_fields else "FILLED",
        plan_id=plan.id,
        filled_fields=filled_fields,
        updated_fields=updated_fields,
    )


def update_local_plan(db: Session, job: ContainerJob, plan: TransportPlan) -> PlanSyncOutcome:
    """Wrapper tương thích ngược: đồng bộ ContainerJob vào kế hoạch nội bộ."""
    return sync_job_to_local_plan(db=db, job=job, plan=plan)


def sync_combined_ro_to_lo_plans(
    db: Session,
    job: ContainerJob,
    ro_plan: TransportPlan,
    lo_plan: TransportPlan,
    actor_id: str = "bot",
    allow_plan_override: bool = False,
) -> tuple[PlanSyncOutcome, PlanSyncOutcome]:
    """Đồng bộ nguyên tử (Atomic Dual-Plan Sync) cho chuyến kết hợp từ lệnh trả (RO) sang lệnh đóng (LO)."""
    # 1. Kiểm tra cảnh báo vỏ trên lệnh trả nếu chưa được ĐHVT override trên Web
    if not allow_plan_override:
        if ro_plan.container_ownership == 2 or ro_plan.container_warning in (
            "empty_drop",
            "other_requested",
            "soc",
            "over_combined",
        ):
            warn_lbl = "soc" if ro_plan.container_ownership == 2 else str(ro_plan.container_warning)
            conflict = [f"Vỏ trả {ro_plan.container_no} bị chặn ghép kết hợp ({warn_lbl})."]
            return (
                PlanSyncOutcome(mode="CONFLICT", plan_id=ro_plan.id, conflict_reasons=conflict),
                PlanSyncOutcome(mode="CONFLICT", plan_id=lo_plan.id, conflict_reasons=conflict),
            )
        if (
            ro_plan.carrier_id
            and lo_plan.carrier_id
            and ro_plan.carrier_id != lo_plan.carrier_id
        ):
            conflict = ["Lệnh trả và lệnh đóng thuộc hai nhà xe khác nhau; không tự động ghép vỏ."]
            return (
                PlanSyncOutcome(mode="CONFLICT", plan_id=ro_plan.id, conflict_reasons=conflict),
                PlanSyncOutcome(mode="CONFLICT", plan_id=lo_plan.id, conflict_reasons=conflict),
            )

    # 2. Lấy số container từ RO sang job và LO nếu LO chưa có container
    shared_cont = clean_container(job.container_no or ro_plan.container_no)
    if shared_cont and not job.container_no:
        job.container_no = shared_cont

    # 3. Đồng bộ chặng RO (không ghi đè seal của lệnh đóng vào RO nếu RO đã có seal riêng)
    saved_job_order_type = job.order_type
    saved_job_seal = job.seal_no
    try:
        job.order_type = ro_plan.order_type or "tra"
        if ro_plan.seal_no and saved_job_seal and ro_plan.seal_no != saved_job_seal:
            job.seal_no = ro_plan.seal_no
        ro_outcome = sync_job_to_local_plan(
            db=db,
            job=job,
            plan=ro_plan,
            allow_plan_override=allow_plan_override,
            actor_id=actor_id,
        )
    finally:
        job.order_type = saved_job_order_type
        job.seal_no = saved_job_seal

    if ro_outcome.mode == "CONFLICT":
        return ro_outcome, PlanSyncOutcome(
            mode="CONFLICT",
            plan_id=lo_plan.id,
            conflict_reasons=list(ro_outcome.conflict_reasons),
        )

    # 4. Đồng bộ chặng LO (điền container lấy từ RO, xe, tài xế, seal mới của lệnh đóng)
    try:
        job.order_type = lo_plan.order_type or "dong"
        lo_outcome = sync_job_to_local_plan(
            db=db,
            job=job,
            plan=lo_plan,
            allow_plan_override=allow_plan_override,
            actor_id=actor_id,
        )
    finally:
        job.order_type = saved_job_order_type

    if lo_outcome.mode != "CONFLICT":
        raw_f = dict(job.raw_fields or {}) if isinstance(job.raw_fields, dict) else {}
        raw_f["transport_plan_id"] = lo_plan.id
        raw_f["secondary_plan_id"] = ro_plan.id
        raw_f["combined_ro_lo"] = True
        job.raw_fields = raw_f
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=actor_id,
                action="COMBINED_RO_LO_SYNCED",
                entity_type="transport_plan",
                entity_id=str(lo_plan.id),
                details={
                    "job_id": str(job.id),
                    "ro_plan_id": str(ro_plan.id),
                    "lo_plan_id": str(lo_plan.id),
                    "container_no": shared_cont,
                    "ro_mode": ro_outcome.mode,
                    "lo_mode": lo_outcome.mode,
                },
            )
        )
    return ro_outcome, lo_outcome


def mask_pii_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    """Che SĐT tài xế (`0903xxxx59`) trong payload trước khi ghi vào bảng `tms_sync_logs`."""
    if not data:
        return {}
    masked: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            masked[k] = mask_pii_payload(v)
        elif isinstance(v, str) and ("phone" in k.lower() or "sdt" in k.lower()):
            masked[k] = mask_phone(v)
        elif isinstance(v, str):
            masked[k] = mask_phone(v)
        else:
            masked[k] = v
    return masked


def sync_plan_to_tms(
    db: Session,
    plan: TransportPlan,
    job: Optional[ContainerJob] = None,
    client: Optional[TmsApiClient] = None,
) -> str:
    """Đồng bộ chiều ghi từ `TransportPlan` sang `be-tms` có kiểm soát phiên bản, idempotency và che PII.

    Tuyệt đối không giả trạng thái `SYNCED` khi `TMS_SYNC_ENABLED` hoặc `TMS_WRITE_ENABLED` đang tắt.
    """
    if not settings.TMS_SYNC_ENABLED or not settings.TMS_WRITE_ENABLED:
        plan.tms_sync_status = "PENDING"
        if job is not None:
            job.tms_sync_status = "PENDING"
        return "PENDING"

    idemp_key = f"tms-write:{plan.id}:v{plan.version or 1}"
    if job is not None:
        existing_ok = db.scalar(
            select(TmsSyncLog).where(
                TmsSyncLog.container_job_id == job.id,
                TmsSyncLog.status == "SUCCESS",
                TmsSyncLog.request_data["idempotency_key"].as_string() == idemp_key,
            )
        )
        if existing_ok is not None:
            plan.tms_sync_status = "SYNCED"
            job.tms_sync_status = "SYNCED"
            return "SYNCED"

    raw_payload: dict[str, Any] = {
        "idempotency_key": idemp_key,
        "plan_id": str(plan.id),
        "tms_order_id": plan.tms_order_id,
        "order_code": plan.order_code,
        "version": plan.version or 1,
        "container_no": plan.container_no,
        "seal_no": plan.seal_no,
        "planned_truck_plate": plan.planned_truck_plate,
        "driver_name": plan.driver_name,
        "driver_phone": plan.driver_phone,
        "required_time": plan.required_time,
    }
    tms_client = client or TmsApiClient()
    try:
        http_code, resp_data = tms_client.push_dispatch_update(
            raw_payload, idempotency_key=idemp_key
        )
        plan.tms_sync_status = "SYNCED"
        if job is not None:
            job.tms_sync_status = "SYNCED"
            db.add(
                TmsSyncLog(
                    id=snowflake.generate(),
                    container_job_id=job.id,
                    operation="PUSH_DISPATCH_UPDATE",
                    request_data=mask_pii_payload(raw_payload),
                    response_data=mask_pii_payload(resp_data),
                    http_status=http_code,
                    status="SUCCESS",
                )
            )
        return "SYNCED"
    except Exception as exc:
        http_status = getattr(exc, "status_code", None) if isinstance(exc, TmsApiError) else None
        plan.tms_sync_status = "FAILED"
        if job is not None:
            job.tms_sync_status = "FAILED"
            db.add(
                TmsSyncLog(
                    id=snowflake.generate(),
                    container_job_id=job.id,
                    operation="PUSH_DISPATCH_UPDATE",
                    request_data=mask_pii_payload(raw_payload),
                    response_data=None,
                    http_status=http_status,
                    status="FAILED",
                    error_message=str(exc)[:500],
                )
            )
        return "FAILED"
