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
from datetime import UTC, datetime, timezone
import hashlib
import json
import os
import re
import unicodedata
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.rules import (
    clean_container,
    clean_phone,
    clean_plate,
    compact_plate,
    mask_phone,
    split_phones,
    validate_iso6346,
)
from src.infrastructure.models import (
    ActivityLog,
    Carrier,
    ContainerJob,
    Driver,
    TmsSyncLog,
    Trailer,
    TransportPlan,
    Vehicle,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiClient, TmsApiError
from src.observability.logging import get_logger

logger = get_logger(__name__)


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
    changed_fields: dict[str, Any] = field(default_factory=dict)
    before_values: dict[str, Any] = field(default_factory=dict)


def _norm_order(val: Optional[str]) -> str:
    """Chuẩn hóa loại lệnh về `'dong'` hoặc `'tra'` để so sánh nhất quán."""
    raw = (val or "").strip().lower()
    if raw in ("load", "dong", "lo", "xuat"):
        return "dong"
    if raw in ("return", "tra", "ro", "nhap"):
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


def extract_plan_expected_time(plan: Optional[TransportPlan]) -> Optional[str]:
    """Lấy thời gian dự kiến có mặt tại kho từ kế hoạch vận chuyển trong DB (`required_time` -> `points_json` -> `estimated_drop_time` -> `eta`)."""
    if plan is None:
        return None
    if plan.required_time and str(plan.required_time).strip():
        return str(plan.required_time).strip()
    if isinstance(plan.points_json, list):
        for pt in plan.points_json:
            if isinstance(pt, dict) and pt.get("required_time") and str(pt["required_time"]).strip():
                return str(pt["required_time"]).strip()
    if plan.estimated_drop_time and str(plan.estimated_drop_time).strip():
        return str(plan.estimated_drop_time).strip()
    if plan.eta and str(plan.eta).strip():
        return str(plan.eta).strip()
    return None


def resolve_job_expected_time(
    db: Session,
    job: Optional[ContainerJob],
    plan: Optional[TransportPlan] = None,
) -> Optional[str]:
    """Lấy thời gian dự kiến của ContainerJob; nếu trống thì tra ngược từ TransportPlan trong DB."""
    if job is not None:
        raw = job.raw_fields if isinstance(job.raw_fields, dict) else {}
        existing_eta = raw.get("eta") or raw.get("eta_text")
        if existing_eta and str(existing_eta).strip():
            return str(existing_eta).strip()
        if job.estimated_at:
            return job.estimated_at.strftime("%H:%M")

    if plan is not None:
        p_eta = extract_plan_expected_time(plan)
        if p_eta:
            return p_eta

    if job is None:
        return None

    raw = job.raw_fields if isinstance(job.raw_fields, dict) else {}
    pid = raw.get("transport_plan_id")
    if pid:
        try:
            linked_plan = db.get(TransportPlan, int(pid))
            p_eta = extract_plan_expected_time(linked_plan)
            if p_eta:
                return p_eta
        except (TypeError, ValueError):
            pass

    if job.container_no:
        cont_clean = clean_container(job.container_no) or job.container_no.strip().upper()
        stmt = (
            select(TransportPlan)
            .where(TransportPlan.container_no == cont_clean)
            .order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc())
        )
        for cand_plan in db.scalars(stmt.limit(5)).all():
            if job.customer_id and cand_plan.customer_id and job.customer_id != cand_plan.customer_id:
                continue
            p_eta = extract_plan_expected_time(cand_plan)
            if p_eta:
                return p_eta

    return None


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


def _is_default_carrier_group(group: ZaloGroup) -> bool:
    """Kiểm tra nhóm nguồn có phải nhóm nhà xe mặc định dùng để test toàn bộ nhà xe không."""
    default_gid = (settings.DEFAULT_CARRIER_GROUP_ID or "").strip()
    return bool(default_gid and group.zalo_group_id and group.zalo_group_id.strip() == default_gid)


def _filter_plans_for_carrier(plans: list[TransportPlan], group: ZaloGroup) -> list[TransportPlan]:
    """Lọc danh sách kế hoạch thuộc nhà xe của nhóm gửi (chặt theo carrier_id hoặc tên khi id trống)."""
    cid = int(group.carrier_id) if group.carrier_id and str(group.carrier_id).isdigit() else None
    group_cname = _norm_text(group.carrier_name)
    if cid is None and not group_cname and _is_default_carrier_group(group):
        return list(plans)
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
    is_default_carrier = _is_default_carrier_group(group)

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

    if not has_carrier_id and not has_carrier_name and not is_default_carrier:
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
        conflicts.append(
            f"Lệch khách hàng so với kế hoạch ({plan.customer_name or 'theo kế hoạch'} / {job.customer_hint or 'theo tin nhắn'})"
        )

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
    changed_map: dict[str, Any] = {}
    before_map: dict[str, Any] = {}

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
        clean_new = str(new_val).strip()
        if _is_blank(cur_val):
            before_map[attr_name] = None
            changed_map[attr_name] = clean_new
            setattr(plan, attr_name, clean_new)
            filled_fields.append(attr_name)
            return
        if normalizer(cur_val) == normalizer(new_val):
            return
        if allow_update and can_update_existing:
            before_map[attr_name] = str(cur_val)
            changed_map[attr_name] = clean_new
            updated_fields.append(
                {
                    "field": attr_name,
                    "label": label,
                    "old": str(cur_val),
                    "new": clean_new,
                }
            )
            setattr(plan, attr_name, clean_new)

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
        trailer_val = truck.trailer_plate
        if trailer_val:
            matched_tr = _match_active_trailer(db, trailer_val, plan.carrier_id)
            if matched_tr and matched_tr.license_plate:
                trailer_val = clean_plate(matched_tr.license_plate) or matched_tr.license_plate
        _apply_field(
            "planned_trailer_plate",
            "Biển số rơ-moóc",
            trailer_val,
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
        is_plan_derived_eta = (
            isinstance(raw.get("field_evidences"), dict)
            and raw["field_evidences"].get("eta_time") == "transport_plan"
        )
        prev_time = plan.required_time
        _apply_field(
            "required_time",
            "Giờ đến dự kiến",
            eta_val,
            lambda v: " ".join(str(v).lower().split()),
            allow_update=not is_plan_derived_eta,
        )
        if (not is_plan_derived_eta and (_is_blank(plan.eta) or plan.eta != plan.required_time)) or prev_time != plan.required_time:
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
    pending_field_names = list(dict.fromkeys([*filled_fields, *(u["field"] for u in updated_fields)]))
    job.raw_fields = {
        **raw,
        "transport_plan_id": plan.id,
        "local_plan_updated": True,
        "local_plan_version": plan.version,
        "tms_pending_fields": pending_field_names,
        "tms_before_values": mask_pii_payload(before_map),
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
                "updated_fields": mask_pii_payload({"items": updated_fields}).get("items", []),
                "sync": "PENDING",
            },
        )
    )
    return PlanSyncOutcome(
        mode="UPDATED" if updated_fields else "FILLED",
        plan_id=plan.id,
        filled_fields=filled_fields,
        updated_fields=updated_fields,
        changed_fields=changed_map,
        before_values=before_map,
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


def _mask_list_items(items: list[Any]) -> list[Any]:
    """Che SĐT trong danh sách giá trị lồng nhau phục vụ ghi log an toàn."""
    out: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            out.append(mask_pii_payload(item))
        elif isinstance(item, list):
            out.append(_mask_list_items(item))
        elif isinstance(item, str):
            out.append(mask_phone(item))
        else:
            out.append(item)
    return out


def mask_pii_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    """Che SĐT tài xế (`0903xxxx59`) và token nhạy cảm trong payload trước khi ghi log."""
    if not data:
        return {}
    masked: dict[str, Any] = {}
    for k, v in data.items():
        if "token" in k.lower() or "secret" in k.lower() or "password" in k.lower():
            masked[k] = "***"
        elif isinstance(v, dict):
            masked[k] = mask_pii_payload(v)
        elif isinstance(v, list):
            masked[k] = _mask_list_items(v)
        elif isinstance(v, str):
            masked[k] = mask_phone(v)
        else:
            masked[k] = v
    return masked


def _resolve_plan_carrier_id(db: Session, plan: TransportPlan) -> Optional[int]:
    """Xác định `carrier_id` nội bộ thuộc chuyến (không đoán khi mơ hồ)."""
    if plan.carrier_id is not None:
        return int(plan.carrier_id)
    cname = _norm_text(plan.fleet_partner or plan.carrier_name)
    if not cname:
        return None
    carriers = list(db.scalars(select(Carrier).where(Carrier.is_active.is_(True))).all())
    exact = [
        c
        for c in carriers
        if _norm_text(c.name) == cname or (c.code and _norm_text(c.code) == cname)
    ]
    return int(exact[0].id) if len(exact) == 1 else None


def _preserve_plate_text(raw_plate: str) -> str:
    """Chuẩn hóa biển số xe về dạng có dấu chấm (VD: '15H-008.14') khi gửi text sang TMS."""
    raw = " ".join((raw_plate or "").strip().upper().split())
    if not raw:
        return raw
    return clean_plate(raw) or raw


def resolve_vehicle_for_plan(
    db: Session,
    plan: TransportPlan,
    *,
    truck_plate: Optional[str] = None,
    requested_vehicle_id: Optional[int] = None,
) -> dict[str, Any]:
    """Tra cứu `vehicle_id` (`tms_vehicle_id`) đang hoạt động thuộc đúng nhà xe; thiếu thì gửi text biển số."""
    carrier_id = _resolve_plan_carrier_id(db, plan)
    raw_plate = str(truck_plate or "").strip()
    norm_cmp = compact_plate(raw_plate) if raw_plate else None
    preserved_plate = _preserve_plate_text(raw_plate) if raw_plate else None

    if requested_vehicle_id is not None:
        veh = db.scalar(
            select(Vehicle).where(
                Vehicle.tms_vehicle_id == int(requested_vehicle_id),
                Vehicle.is_active.is_(True),
                Vehicle.vehicle_type == 1,
            )
        )
        if veh is not None and (carrier_id is not None and veh.carrier_id == carrier_id):
            if not norm_cmp or compact_plate(veh.plate_no) == norm_cmp:
                return {
                    "vehicle_id": int(veh.tms_vehicle_id),
                    "resolution": "matched_by_id",
                }
        # `vehicle_id` không tồn tại, không hoạt động hoặc không khớp nhà xe -> rơi về tra theo biển số.
        if not norm_cmp:
            return {"vehicle_id": None, "resolution": "invalid_or_cross_carrier_vehicle_id"}

    if norm_cmp:
        veh_stmt = select(Vehicle).where(
            Vehicle.is_active.is_(True),
            Vehicle.vehicle_type == 1,
        )
        if carrier_id is not None:
            veh_stmt = veh_stmt.where(Vehicle.carrier_id == carrier_id)
        vehicles = list(db.scalars(veh_stmt).all())
        matched = [v for v in vehicles if compact_plate(v.plate_no) == norm_cmp]
        if len(matched) == 1:
            return {
                "vehicle_id": int(matched[0].tms_vehicle_id),
                "resolution": "matched_by_plate",
            }

    if preserved_plate:
        return {
            "vehicle_id": None,
            "planned_truck_plate": preserved_plate,
            "resolution": "plate_not_found_on_tms",
        }
    return {}


def _match_active_trailer(
    db: Session,
    trailer_plate: Optional[str],
    carrier_id: Optional[int] = None,
) -> Optional[Trailer]:
    """Tra cứu bản ghi rơ-moóc đang hoạt động trong bảng `trailers` theo biển số chuẩn hóa (hỗ trợ 4-5 số cuối)."""
    norm_cmp = compact_plate(trailer_plate) if trailer_plate else None
    if not norm_cmp:
        return None
    stmt = select(Trailer).where(
        Trailer.is_active.is_(True),
        Trailer.normalized_plate == norm_cmp,
    )
    if carrier_id is not None:
        scoped = list(db.scalars(stmt.where(Trailer.carrier_id == carrier_id)).all())
        if len(scoped) == 1:
            return scoped[0]
        if len(scoped) > 1:
            return None
    matches = list(db.scalars(stmt).all())
    if len(matches) == 1:
        return matches[0]

    # Hỗ trợ tra cứu 4-5 số cuối (VD: "30187" -> "29R-301.87") khi khớp duy nhất 1 mooc
    if not matches and norm_cmp.isdigit() and 4 <= len(norm_cmp) <= 5:
        suffix_stmt = select(Trailer).where(
            Trailer.is_active.is_(True),
            Trailer.normalized_plate.like(f"%{norm_cmp}"),
        )
        if carrier_id is not None:
            scoped_sfx = [
                t for t in db.scalars(suffix_stmt.where(Trailer.carrier_id == carrier_id)).all()
                if (t.normalized_plate or "").endswith(norm_cmp)
            ]
            if len(scoped_sfx) == 1:
                return scoped_sfx[0]
            if len(scoped_sfx) > 1:
                return None
        global_sfx = [
            t for t in db.scalars(suffix_stmt).all()
            if (t.normalized_plate or "").endswith(norm_cmp)
        ]
        if len(global_sfx) == 1:
            return global_sfx[0]
    return None


def resolve_trailer_from_catalog(
    db: Session,
    line: Any,
    carrier_id: Optional[int] = None,
) -> bool:
    """Dùng bảng `trailers` (đồng bộ từ `/carrier-moocs`) để phân biệt đầu kéo với mooc và chuẩn hóa biển mooc.

    Returns:
        bool: True nếu có chỉnh sửa `truck_plate` hoặc `trailer_plate` trên `line`.
    """
    changed = False
    eff_carrier_id = carrier_id or getattr(line, "carrier_id", None)

    if getattr(line, "truck_plate", None):
        truck_cmp = compact_plate(line.truck_plate)
        is_known_tractor = False
        if truck_cmp:
            tractor_rows = list(
                db.scalars(
                    select(Vehicle).where(
                        Vehicle.is_active.is_(True),
                        Vehicle.vehicle_type == 1,
                    )
                ).all()
            )
            is_known_tractor = any(compact_plate(v.plate_no) == truck_cmp for v in tractor_rows)

        if not is_known_tractor:
            matched_as_trailer = _match_active_trailer(db, line.truck_plate, eff_carrier_id)
            if matched_as_trailer is not None:
                if not getattr(line, "trailer_plate", None):
                    line.trailer_plate = (
                        clean_plate(matched_as_trailer.license_plate) or matched_as_trailer.license_plate
                    )
                line.truck_plate = None
                line.field_evidences["trailer_plate"] = "carrier_trailer_catalog_reclassified"
                if getattr(line, "carrier_id", None) is None and matched_as_trailer.carrier_id:
                    line.carrier_id = matched_as_trailer.carrier_id
                changed = True

    if getattr(line, "trailer_plate", None):
        matched_tr = _match_active_trailer(db, line.trailer_plate, eff_carrier_id)
        if matched_tr is not None:
            canon_tr = clean_plate(matched_tr.license_plate) or matched_tr.license_plate
            if canon_tr and line.trailer_plate != canon_tr:
                line.trailer_plate = canon_tr
                changed = True
            line.field_evidences["trailer_plate"] = "carrier_trailer_catalog"
            if getattr(line, "carrier_id", None) is None and matched_tr.carrier_id:
                line.carrier_id = matched_tr.carrier_id

    return changed


def resolve_trailer_for_plan(
    db: Session,
    plan: TransportPlan,
    *,
    trailer_plate: Optional[str] = None,
    requested_mooc_id: Optional[int] = None,
) -> dict[str, Any]:
    """Tra cứu `mooc_id` (`tms_mooc_id`) đang hoạt động từ bảng `trailers` giống luồng `resolve_vehicle_for_plan`."""
    carrier_id = _resolve_plan_carrier_id(db, plan)
    raw_plate = str(trailer_plate or "").strip()
    norm_cmp = compact_plate(raw_plate) if raw_plate else None
    preserved_plate = _preserve_plate_text(raw_plate) if raw_plate else None

    if requested_mooc_id is not None:
        tr = db.scalar(
            select(Trailer).where(
                Trailer.tms_mooc_id == int(requested_mooc_id),
                Trailer.is_active.is_(True),
            )
        )
        if tr is not None and (carrier_id is None or tr.carrier_id == carrier_id):
            if not norm_cmp or tr.normalized_plate == norm_cmp:
                return {
                    "mooc_id": int(tr.tms_mooc_id),
                    "resolution": "matched_by_id",
                }
        if not norm_cmp:
            return {"mooc_id": None, "resolution": "invalid_or_cross_carrier_mooc_id"}

    if norm_cmp:
        tr = _match_active_trailer(db, raw_plate, carrier_id)
        if tr is not None:
            return {
                "mooc_id": int(tr.tms_mooc_id),
                "resolution": "matched_by_plate",
            }

    if preserved_plate:
        return {
            "mooc_id": None,
            "planned_trailer_plate": preserved_plate,
            "resolution": "mooc_not_found_on_tms",
        }
    return {}


def resolve_driver_for_plan(
    db: Session,
    plan: TransportPlan,
    *,
    driver_name: Optional[str] = None,
    driver_phone: Optional[str] = None,
    requested_driver_id: Optional[int] = None,
) -> dict[str, Any]:
    """Tra cứu `driver_id` (`tms_driver_id`) thuộc đúng nhà xe theo ID / SĐT / tên không mơ hồ.

    Hỗ trợ tài xế có nhiều SĐT dạng `'09..1 | 09..2'`: khi có >= 2 SĐT, luôn gửi kèm `driver_phone`
    đầy đủ sang TMS (kèm `driver_id` nếu một trong các SĐT khớp duy nhất tài xế trong DB).
    """
    carrier_id = _resolve_plan_carrier_id(db, plan)
    clean_name = " ".join(str(driver_name).strip().split()) if driver_name and str(driver_name).strip() else None
    phone_list = split_phones(driver_phone) if driver_phone and str(driver_phone).strip() else []
    norm_phone = " | ".join(phone_list) if phone_list else None
    has_multi_phones = len(phone_list) >= 2
    phone_set = set(phone_list)

    drv_stmt = select(Driver).where(Driver.is_active.is_(True))
    if carrier_id is not None:
        drv_stmt = drv_stmt.where(Driver.carrier_id == carrier_id)
    carrier_drivers: list[Driver] = list(db.scalars(drv_stmt).all())

    if requested_driver_id is not None and carrier_drivers:
        drv = next((d for d in carrier_drivers if d.tms_driver_id == int(requested_driver_id)), None)
        if drv is not None:
            drv_phones = set(split_phones(drv.phone))
            phone_ok = not phone_set or bool(drv_phones & phone_set)
            name_ok = not clean_name or _norm_text(drv.full_name) == _norm_text(clean_name)
            if phone_ok and name_ok:
                out_id: dict[str, Any] = {"driver_id": int(drv.tms_driver_id), "resolution": "matched_by_id"}
                if has_multi_phones and norm_phone:
                    out_id["driver_phone"] = norm_phone
                return out_id

    if phone_set:
        by_phone = [d for d in carrier_drivers if set(split_phones(d.phone)) & phone_set]
        if len(by_phone) == 1:
            out_matched: dict[str, Any] = {
                "driver_id": int(by_phone[0].tms_driver_id),
                "resolution": "matched_by_phone_multi" if has_multi_phones else "matched_by_phone",
            }
            if has_multi_phones and norm_phone:
                out_matched["driver_phone"] = norm_phone
            return out_matched

    if clean_name:
        in_norm = _norm_text(clean_name)
        by_exact = [d for d in carrier_drivers if _norm_text(d.normalized_name or d.full_name) == in_norm]
        if len(by_exact) == 1:
            out_exact: dict[str, Any] = {
                "driver_id": int(by_exact[0].tms_driver_id),
                "resolution": "matched_by_exact_name",
            }
            if has_multi_phones and norm_phone:
                out_exact["driver_phone"] = norm_phone
            return out_exact
        if not norm_phone:
            return {
                "driver_name": clean_name,
                "resolution": "ambiguous_or_unmatched_name_only",
            }

    if norm_phone:
        out_unmatched: dict[str, Any] = {
            "driver_id": None,
            "driver_phone": norm_phone,
            "resolution": "phone_not_found_on_tms",
        }
        if clean_name:
            out_unmatched["driver_name"] = clean_name
        return out_unmatched

    return {}


def build_dispatch_assignment_payload(
    db: Session,
    plan: TransportPlan,
    *,
    changed_fields: dict[str, Any],
    requested_vehicle_id: Optional[int] = None,
    requested_mooc_id: Optional[int] = None,
    requested_driver_id: Optional[int] = None,
    before_values: Optional[dict[str, Any]] = None,
    previous_container_no: Optional[str] = None,
    allow_container_override: bool = False,
) -> tuple[Optional[dict[str, Any]], list[str], Optional[str]]:
    """Dựng payload cập nhật từng phần cho `POST /api/integrations/zalo/dispatch-assignment`.

    Chỉ đưa vào payload những field thực sự có trong `changed_fields`, tôn trọng quy tắc RO/LO
    của `container_no` và không tự ý gửi `null` để xóa dữ liệu cũ.
    """
    order_code = (plan.order_code or "").strip().upper()
    if not order_code:
        return None, [], "MISSING_ORDER_CODE"

    if not changed_fields and requested_vehicle_id is None and requested_mooc_id is None and requested_driver_id is None:
        return None, [], "NO_CHANGES"

    payload: dict[str, Any] = {"order_code": order_code}
    requested_fields: list[str] = []

    plate_val = changed_fields.get("planned_truck_plate") or changed_fields.get("truck_plate")
    if (plate_val and str(plate_val).strip()) or requested_vehicle_id is not None:
        veh_res = resolve_vehicle_for_plan(
            db,
            plan,
            truck_plate=str(plate_val) if plate_val else None,
            requested_vehicle_id=requested_vehicle_id,
        )
        if "vehicle_id" in veh_res:
            payload["vehicle_id"] = veh_res["vehicle_id"]
            requested_fields.append("vehicle_id")
        if veh_res.get("planned_truck_plate"):
            payload["planned_truck_plate"] = veh_res["planned_truck_plate"]
            requested_fields.append("planned_truck_plate")

    trailer_val = changed_fields.get("planned_trailer_plate") or changed_fields.get("trailer_plate")
    if (trailer_val and str(trailer_val).strip()) or requested_mooc_id is not None:
        tr_res = resolve_trailer_for_plan(
            db,
            plan,
            trailer_plate=str(trailer_val) if trailer_val else None,
            requested_mooc_id=requested_mooc_id,
        )
        if "mooc_id" in tr_res:
            payload["carrier_mooc_id"] = tr_res["mooc_id"]
            requested_fields.append("carrier_mooc_id")
        if tr_res.get("planned_trailer_plate"):
            payload["ro_mooc_no"] = tr_res["planned_trailer_plate"]
            requested_fields.append("ro_mooc_no")

    d_name = changed_fields.get("driver_name")
    d_phone = changed_fields.get("driver_phone")
    if (d_name and str(d_name).strip()) or (d_phone and str(d_phone).strip()) or requested_driver_id is not None:
        drv_res = resolve_driver_for_plan(
            db,
            plan,
            driver_name=str(d_name) if d_name else None,
            driver_phone=str(d_phone) if d_phone else None,
            requested_driver_id=requested_driver_id,
        )
        if "driver_id" in drv_res:
            payload["driver_id"] = drv_res["driver_id"]
            requested_fields.append("driver_id")
        if drv_res.get("driver_phone"):
            payload["driver_phone"] = drv_res["driver_phone"]
            requested_fields.append("driver_phone")
        if drv_res.get("driver_name"):
            payload["driver_name"] = drv_res["driver_name"]
            requested_fields.append("driver_name")

    if changed_fields.get("container_no") and str(changed_fields["container_no"]).strip():
        order_kind = _norm_order(plan.order_type)
        # Lệnh trả (RO) đã có container cố định trên TMS; không gửi `container_no`.
        if order_kind != "tra":
            raw_cont = str(changed_fields["container_no"]).strip()
            norm_cont = clean_container(raw_cont)
            if not norm_cont or not validate_iso6346(norm_cont):
                return None, list(requested_fields), f"INVALID_CONTAINER_FORMAT:{raw_cont}"
            prev_c = (
                clean_container(previous_container_no)
                if previous_container_no is not None
                else (
                    clean_container(str(before_values["container_no"]))
                    if before_values and "container_no" in before_values and before_values["container_no"]
                    else clean_container(plan.container_no)
                )
            )
            if prev_c and prev_c != norm_cont and not allow_container_override:
                return None, list(requested_fields), f"CONTAINER_OVERRIDE_BLOCKED:{prev_c}->{norm_cont}"
            payload["container_no"] = norm_cont
            requested_fields.append("container_no")

    if len(payload) <= 1:
        return None, [], "NO_UPDATABLE_TMS_FIELDS"

    return payload, requested_fields, None


def _derive_changed_fields_from_job(
    plan: TransportPlan,
    job: Optional[ContainerJob],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Suy xuất các field vừa được cập nhật từ `ContainerJob` và `raw_fields`."""
    if job is None:
        return {}, {}
    raw = dict(job.raw_fields or {}) if isinstance(job.raw_fields, dict) else {}
    truck = job.truck_record
    source_map: dict[str, Any] = {}
    if truck:
        if truck.truck_plate:
            source_map["planned_truck_plate"] = truck.truck_plate
        if truck.trailer_plate:
            source_map["planned_trailer_plate"] = truck.trailer_plate
        if truck.driver_name:
            source_map["driver_name"] = truck.driver_name
        if truck.driver_phone:
            source_map["driver_phone"] = truck.driver_phone
    if job.container_no:
        source_map["container_no"] = job.container_no

    pending_names = raw.get("tms_pending_fields")
    if isinstance(pending_names, list) and pending_names:
        filtered = {
            k: source_map.get(k) if source_map.get(k) is not None else getattr(plan, k, None)
            for k in pending_names
            if k in ("planned_truck_plate", "planned_trailer_plate", "driver_name", "driver_phone", "container_no")
            and (source_map.get(k) is not None or getattr(plan, k, None) is not None)
        }
        before_vals = raw.get("tms_before_values") if isinstance(raw.get("tms_before_values"), dict) else {}
        return filtered, dict(before_vals)

    proposal = raw.get("assistant_proposal")
    if isinstance(proposal, dict) and proposal:
        filtered = {
            k: v
            for k, v in proposal.items()
            if k in ("planned_truck_plate", "planned_trailer_plate", "driver_name", "driver_phone", "container_no") and v
        }
        return filtered, {}

    return source_map, {}


def _find_success_sync_by_idempotency_key(
    db: Session,
    *,
    job: Optional[ContainerJob],
    plan: TransportPlan,
    idemp_key: str,
) -> bool:
    """Kiểm tra đã từng đồng bộ thành công với cùng `idempotency_key` hay chưa."""
    if job is not None:
        existing_ok = db.scalar(
            select(TmsSyncLog).where(
                TmsSyncLog.container_job_id == job.id,
                TmsSyncLog.status == "SUCCESS",
                TmsSyncLog.request_data["idempotency_key"].as_string() == idemp_key,
            )
        )
        if existing_ok is not None:
            return True
    existing_act = db.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "TMS_DISPATCH_ASSIGNMENT_SYNC",
            ActivityLog.entity_type == "transport_plan",
            ActivityLog.entity_id == str(plan.id),
            ActivityLog.details["status"].as_string() == "SUCCESS",
            ActivityLog.details["idempotency_key"].as_string() == idemp_key,
        )
    )
    return existing_act is not None


def _refresh_local_plan_after_tms_write(
    db: Session,
    plan: TransportPlan,
    client: Optional[Any],
    actor_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """Tự động kéo lại kế hoạch ngày từ TMS về `transport_plans` ngay sau khi ghi thành công lên TMS."""
    if not settings.TMS_SYNC_ENABLED or plan.plan_date is None:
        return None
    from src.handlers.tms_auto_sync import tms_auto_sync
    from src.handlers.tms_plan_sync_service import sync_transport_plans_from_tms

    region = int(plan.region or 1)
    tms_auto_sync.track_date(plan.plan_date, region)

    pull_client = client if (client is not None and hasattr(client, "fetch_transport_plan_by_date")) else tms_auto_sync.get_client()
    if not hasattr(pull_client, "fetch_transport_plan_by_date"):
        return None
    if "PYTEST_CURRENT_TEST" in os.environ and getattr(type(pull_client), "fetch_transport_plan_by_date", None) is TmsApiClient.fetch_transport_plan_by_date:
        return None
    if isinstance(pull_client, TmsApiClient) and not pull_client.has_valid_credentials() and "PYTEST_CURRENT_TEST" not in os.environ:
        return None

    try:
        db.flush()
        pull_stats = sync_transport_plans_from_tms(
            db=db,
            plan_date=plan.plan_date,
            region=region,
            client=pull_client,
            auto_commit=False,
        )
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=actor_id or "vsico_bot",
                action="TMS_POST_WRITE_PLAN_REFRESHED",
                entity_type="transport_plan",
                entity_id=str(plan.id),
                details={
                    "order_code": plan.order_code,
                    "plan_date": plan.plan_date.isoformat(),
                    "region": region,
                    "total_synced": pull_stats.get("total_synced"),
                    "inserted": pull_stats.get("inserted"),
                    "updated": pull_stats.get("updated"),
                },
            )
        )
        tms_auto_sync.wake_up()
        return pull_stats
    except Exception as pull_exc:
        logger.warning(
            "Đã đẩy TMS thành công nhưng tự động kéo lại kế hoạch ngày %s thất bại (chờ chu kỳ nền): %s",
            plan.plan_date.isoformat(),
            mask_phone(str(pull_exc))[:300],
        )
        return None


def sync_plan_to_tms(
    db: Session,
    plan: TransportPlan,
    job: Optional[ContainerJob] = None,
    client: Optional[TmsApiClient] = None,
    *,
    changed_fields: Optional[dict[str, Any]] = None,
    before_values: Optional[dict[str, Any]] = None,
    requested_vehicle_id: Optional[int] = None,
    requested_driver_id: Optional[int] = None,
    previous_container_no: Optional[str] = None,
    allow_container_override: bool = False,
    correlation_id: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> str:
    """Đồng bộ cập nhật từng phần từ `TransportPlan` sang `be-tms` (`dispatch-assignment`).

    Tuyệt đối không giả trạng thái `SYNCED` khi cờ tắt, thiếu `order_code`, hoặc TMS trả lỗi.
    """
    if not settings.TMS_SYNC_ENABLED or not settings.TMS_WRITE_ENABLED:
        plan.tms_sync_status = "PENDING"
        if job is not None:
            job.tms_sync_status = "PENDING"
        return "PENDING"

    eff_changed = dict(changed_fields) if changed_fields is not None else None
    eff_before = dict(before_values) if before_values is not None else None
    if eff_changed is None:
        derived_changed, derived_before = _derive_changed_fields_from_job(plan, job)
        eff_changed = derived_changed
        if eff_before is None:
            eff_before = derived_before

    payload, requested_fields, skip_reason = build_dispatch_assignment_payload(
        db,
        plan,
        changed_fields=eff_changed or {},
        requested_vehicle_id=requested_vehicle_id,
        requested_driver_id=requested_driver_id,
        before_values=eff_before,
        previous_container_no=previous_container_no,
        allow_container_override=allow_container_override,
    )
    if skip_reason or payload is None:
        logger.info(
            "Bỏ qua đồng bộ TMS cho kế hoạch ID=%s (order_code=%s): %s",
            plan.id,
            plan.order_code,
            skip_reason,
        )
        if skip_reason and skip_reason.startswith(("INVALID_CONTAINER_FORMAT:", "CONTAINER_OVERRIDE_BLOCKED:")):
            plan.tms_sync_status = "FAILED"
            if job is not None:
                job.tms_sync_status = "FAILED"
            return "FAILED"
        plan.tms_sync_status = "PENDING"
        if job is not None:
            job.tms_sync_status = "PENDING"
        return "PENDING"

    payload_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:10]
    idemp_key = f"tms-write:{plan.id}:{payload['order_code']}:v{plan.version or 1}:{payload_digest}"
    corr_id = correlation_id or f"zalo-tms-{plan.id}-{uuid4().hex[:8]}"

    if _find_success_sync_by_idempotency_key(db, job=job, plan=plan, idemp_key=idemp_key):
        plan.tms_sync_status = "SYNCED"
        if job is not None:
            job.tms_sync_status = "SYNCED"
        return "SYNCED"

    orig_msg = db.get(ZaloMessage, job.message_id) if (job is not None and job.message_id) else None
    audit_base: dict[str, Any] = {
        "order_code": payload["order_code"],
        "requested_fields": requested_fields,
        "before_values": mask_pii_payload(eff_before or {}),
        "after_values": mask_pii_payload(payload),
        "message_id": str(orig_msg.id) if orig_msg else None,
        "zalo_message_id": orig_msg.zalo_message_id if orig_msg else None,
        "group_id": orig_msg.group_id if orig_msg else plan.group_id,
        "sender_id": actor_id or (orig_msg.sender_id if orig_msg else None),
        "carrier_id": str(plan.carrier_id) if plan.carrier_id is not None else None,
        "correlation_id": corr_id,
        "idempotency_key": idemp_key,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    log_request_data = {**mask_pii_payload(payload), "idempotency_key": idemp_key, "correlation_id": corr_id}

    tms_client = client or TmsApiClient()
    try:
        if hasattr(tms_client, "push_dispatch_assignment"):
            http_code, resp_data = tms_client.push_dispatch_assignment(
                payload,
                idempotency_key=idemp_key,
                correlation_id=corr_id,
            )
        else:
            http_code, resp_data = tms_client.push_dispatch_update(
                payload,
                idempotency_key=idemp_key,
            )
        plan.tms_sync_status = "SYNCED"
        masked_resp = mask_pii_payload(resp_data if isinstance(resp_data, dict) else {"data": resp_data})
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=audit_base["sender_id"] or "vsico_bot",
                action="TMS_DISPATCH_ASSIGNMENT_SYNC",
                entity_type="transport_plan",
                entity_id=str(plan.id),
                details={
                    **audit_base,
                    "http_status": http_code,
                    "tms_result": masked_resp,
                    "status": "SUCCESS",
                },
            )
        )
        if job is not None:
            job.tms_sync_status = "SYNCED"
            db.add(
                TmsSyncLog(
                    id=snowflake.generate(),
                    container_job_id=job.id,
                    operation="PUSH_DISPATCH_ASSIGNMENT",
                    request_data=log_request_data,
                    response_data=masked_resp,
                    http_status=http_code,
                    status="SUCCESS",
                )
            )
        _refresh_local_plan_after_tms_write(db, plan, tms_client, audit_base["sender_id"])
        return "SYNCED"
    except Exception as exc:
        http_status = getattr(exc, "status_code", None) if isinstance(exc, TmsApiError) else None
        is_retryable = getattr(exc, "is_retryable", False) if isinstance(exc, TmsApiError) else False
        resp_body = getattr(exc, "response_body", None) if isinstance(exc, TmsApiError) else None
        masked_err_body = (
            mask_pii_payload(resp_body)
            if isinstance(resp_body, dict)
            else mask_phone(str(resp_body or ""))[:300]
            if resp_body
            else None
        )
        safe_err = mask_phone(str(exc))[:500]
        plan.tms_sync_status = "FAILED"
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=audit_base["sender_id"] or "vsico_bot",
                action="TMS_DISPATCH_ASSIGNMENT_SYNC",
                entity_type="transport_plan",
                entity_id=str(plan.id),
                details={
                    **audit_base,
                    "http_status": http_status,
                    "tms_result": masked_err_body,
                    "error": safe_err,
                    "retryable": is_retryable,
                    "status": "FAILED",
                },
            )
        )
        if job is not None:
            job.tms_sync_status = "FAILED"
            db.add(
                TmsSyncLog(
                    id=snowflake.generate(),
                    container_job_id=job.id,
                    operation="PUSH_DISPATCH_ASSIGNMENT",
                    request_data=log_request_data,
                    response_data=masked_err_body if isinstance(masked_err_body, dict) else None,
                    http_status=http_status,
                    status="FAILED",
                    error_message=safe_err,
                )
            )
        return "FAILED"
