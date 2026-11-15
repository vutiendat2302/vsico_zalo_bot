"""Truy vấn dùng chung luôn bắt đầu bằng phạm vi đã xác thực."""

import re

from sqlalchemy import Select, String, func, or_, select
from sqlalchemy.orm import Session

from src.domain.rules import compact_plate
from src.infrastructure.models import (
    ContainerJob,
    CustomerAlias,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TransportPlan,
    Vehicle,
    WarehouseAlias,
    ZaloMessage,
)

from .intent_router import normalize
from .schemas import Entities, ScopeContext
from .scope_resolver import is_default_carrier_group, plan_scope


def plans_statement(scope: ScopeContext, e: Entities) -> Select[tuple[TransportPlan]]:
    """Tạo truy vấn kế hoạch và ép mọi điều kiện khách/nhà xe tại SQL."""
    stmt = select(TransportPlan).where(plan_scope(scope))
    if e.plan_date:
        stmt = stmt.where(TransportPlan.plan_date == e.plan_date)
    id_filters = []
    for key in ("container_no", "order_code", "booking_no", "bill_of_lading_no"):
        if value := getattr(e, key):
            id_filters.append(func.upper(getattr(TransportPlan, key)) == value.upper())
    if id_filters:
        stmt = stmt.where(or_(*id_filters))
    for key in (
        "warehouse_name",
        "customer_name",
        "carrier_name",
        "forwarder_name",
        "province_name",
    ):
        if value := getattr(e, key):
            stmt = stmt.where(getattr(TransportPlan, key) == value)
    if e.region is not None:
        stmt = stmt.where(TransportPlan.region == e.region)
    if e.order_type:
        if e.order_type.upper() in ("LOAD", "DONG", "LO"):
            stmt = stmt.where(func.lower(TransportPlan.order_type).in_(["dong", "load", "lo"]))
        elif e.order_type.upper() in ("RETURN", "TRA", "RO"):
            stmt = stmt.where(func.lower(TransportPlan.order_type).in_(["tra", "return", "ro"]))
    if e.plate_no:
        plate = compact_plate(e.plate_no)
        column = func.upper(
            func.replace(
                func.replace(func.replace(TransportPlan.planned_truck_plate, "-", ""), ".", ""),
                " ",
                "",
            )
        )
        stmt = stmt.where(column == plate)
    if e.assigned is not None:
        empty = or_(
            TransportPlan.planned_truck_plate.is_(None),
            func.trim(TransportPlan.planned_truck_plate) == "",
        )
        stmt = stmt.where(~empty if e.assigned else empty)
    return stmt


def enrich_catalog(
    db: Session, scope: ScopeContext, e: Entities, text: str
) -> tuple[Entities, bool]:
    """Nhận diện tên/alias từ chính tập kế hoạch được phép xem; mơ hồ thì hỏi lại."""
    e = e.model_copy(deep=True)
    n = " " + normalize(text) + " "
    ambiguous = False
    unresolved_hints: set[str] = set()
    base = select(TransportPlan).where(plan_scope(scope))
    if e.plan_date is not None:
        base = base.where(TransportPlan.plan_date == e.plan_date)
    plans = list(db.scalars(base).all())
    for attr in (
        "warehouse_name",
        "customer_name",
        "carrier_name",
        "forwarder_name",
        "province_name",
    ):
        values = {getattr(p, attr) for p in plans if getattr(p, attr)}
        matches = [v for v in values if " " + normalize(v) + " " in n]
        if not matches and attr == "province_name":
            matches = [
                v
                for v in values
                if (
                    stripped := re.sub(r"^(?:tinh|thanh pho|tp)\s+", "", normalize(v)).strip()
                )
                and len(stripped) >= 4
                and " " + stripped + " " in n
            ]
        if not matches:
            label = {
                "warehouse_name": "kho",
                "customer_name": "khach",
                "carrier_name": "nha xe",
                "forwarder_name": "forwarder",
                "province_name": "tinh",
            }[attr]
            hint = re.search(
                r"(?<!gui )\b"
                + label
                + r"\s+(.+?)(?=\s+(?:mai|hom|co|may|bao|chay|tong|ngay|luc)|[?,;]|$)",
                normalize(text),
            )
            if (
                hint
                and hint[1].strip()
                not in (
                    "nao",
                    "hang",
                    "chua",
                    "cu",
                    "co",
                    "bao",
                    "that bai",
                    "da",
                    "dang",
                )
                and not (attr == "province_name" and hint[1].strip() in ("thanh", "khac"))
            ):
                token = hint[1].strip()
                matches = [v for v in values if " " + token + " " in " " + normalize(v) + " "]
                if not matches:
                    unresolved_hints.add(attr)
                elif len(matches) > 1:
                    ambiguous = True
        if matches:
            longest = max(len(normalize(v)) for v in matches)
            matches = [v for v in matches if len(normalize(v)) == longest]
            if len(matches) == 1:
                setattr(e, attr, matches[0])
            else:
                ambiguous = True
    for model, id_attr, name_attr in [
        (WarehouseAlias, "warehouse_id", "warehouse_name"),
        (CustomerAlias, "customer_id", "customer_name"),
    ]:
        ids = {getattr(p, id_attr) for p in plans if getattr(p, id_attr)}
        if not ids or getattr(e, name_attr):
            continue
        aliases = db.scalars(select(model).where(getattr(model, id_attr).in_(ids))).all()
        matched_ids = {
            getattr(a, id_attr) for a in aliases if a.alias and " " + normalize(a.alias) + " " in n
        }
        if len(matched_ids) == 1:
            names = {getattr(p, name_attr) for p in plans if getattr(p, id_attr) in matched_ids}
            names.discard(None)
            if len(names) == 1:
                setattr(e, name_attr, names.pop())
            else:
                ambiguous = True
        elif matched_ids:
            ambiguous = True
    if e.plate_no and re.fullmatch(r"[\d.]{4,6}", e.plate_no):
        if scope.role != "CARRIER" or (
            not scope.carrier_id and not is_default_carrier_group(scope.zalo_group_id)
        ):
            return e, True
        veh_stmt = select(Vehicle).where(Vehicle.is_active.is_(True), Vehicle.vehicle_type == 1)
        if scope.carrier_id:
            veh_stmt = veh_stmt.where(Vehicle.carrier_id == scope.carrier_id)
        vehicles = db.scalars(veh_stmt).all()
        matches = {
            v.plate_no
            for v in vehicles
            if compact_plate(v.plate_no).endswith(compact_plate(e.plate_no))
        }
        if len(matches) == 1:
            e.plate_no = matches.pop()
        else:
            ambiguous = True
    return e, ambiguous or any(not getattr(e, attr) for attr in unresolved_hints)


def scoped_cases(
    db: Session, scope: ScopeContext, e: Entities, pending: bool = False
) -> list[ReviewCase]:
    """Ca khách chỉ của đúng nhóm; ca nhà xe còn đối chiếu nguồn tin gốc."""
    stmt = select(ReviewCase).join(ZaloMessage, ReviewCase.message_id == ZaloMessage.id)
    if scope.role != "DHVT":
        stmt = stmt.where(ZaloMessage.group_id == scope.zalo_group_id)
    if e.case_id:
        stmt = stmt.where(ReviewCase.id == int(e.case_id))
    if pending:
        stmt = stmt.where(ReviewCase.status == "PENDING")
    return list(
        db.scalars(
            stmt.order_by(ReviewCase.created_at.desc(), ReviewCase.id.desc()).limit(21)
        ).all()
    )


def plan_jobs(db: Session, plan: TransportPlan) -> list[ContainerJob]:
    """Liên kết job bằng plan_id đã lưu, tránh dùng số cont trùng hai chặng."""
    return list(
        db.scalars(
            select(ContainerJob)
            .where(ContainerJob.raw_fields["transport_plan_id"].as_string() == str(plan.id))
            .order_by(ContainerJob.id)
        ).all()
    )


def plan_outbounds(db: Session, plan: TransportPlan) -> list[OutboundMessage]:
    """Tra thông báo qua quan hệ job và kế hoạch, không suy từ số cont."""
    ids = [j.id for j in plan_jobs(db, plan)]
    if not ids:
        return []
    return list(
        db.scalars(
            select(OutboundMessage)
            .join(OutboundMessageItem)
            .where(OutboundMessageItem.container_job_id.in_(ids))
        )
        .unique()
        .all()
    )


def scoped_jobs_statement(scope: ScopeContext, e: Entities) -> Select[tuple[ContainerJob]]:
    """Tra tin báo chưa khớp kế hoạch nhưng vẫn giữ phạm vi nguồn hoặc RouteMap."""
    from datetime import datetime, time, timedelta

    from sqlalchemy import and_, false

    from src.infrastructure.models import TruckRecord, ZaloGroup

    stmt = select(ContainerJob).join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
    if scope.role == "CUSTOMER":
        if scope.routes:
            terms = []
            for r in scope.routes:
                filters = [ContainerJob.customer_id == r.customer_id]
                if r.warehouse_id is not None:
                    filters.append(ContainerJob.warehouse_id == r.warehouse_id)
                if r.order_type:
                    kinds = (
                        ["load", "dong", "lo"]
                        if r.order_type.lower() in ("load", "dong", "lo")
                        else ["return", "tra", "ro"]
                    )
                    filters.append(func.lower(ContainerJob.order_type).in_(kinds))
                terms.append(and_(*filters))
            stmt = stmt.where(or_(*terms))
        else:
            plan_ids_sq = select(func.cast(TransportPlan.id, String)).where(
                TransportPlan.group_id == scope.zalo_group_id
            )
            stmt = stmt.where(
                ContainerJob.raw_fields["transport_plan_id"].as_string().in_(plan_ids_sq)
            )
    elif scope.role == "CARRIER":
        if scope.carrier_id:
            stmt = stmt.join(ZaloGroup, ZaloGroup.zalo_group_id == ZaloMessage.group_id).where(
                ZaloGroup.carrier_id == str(scope.carrier_id), ZaloGroup.is_active.is_(True)
            )
        else:
            stmt = stmt.where(ZaloMessage.group_id == scope.zalo_group_id)
    if e.plan_date:
        start = datetime.combine(e.plan_date, time.min)
        stmt = stmt.where(
            ZaloMessage.created_at >= start, ZaloMessage.created_at < start + timedelta(days=1)
        )
    if e.container_no:
        stmt = stmt.where(ContainerJob.container_no == e.container_no)
    if e.plate_no:
        stmt = stmt.join(TruckRecord, ContainerJob.truck_record_id == TruckRecord.id).where(
            func.upper(func.replace(func.replace(TruckRecord.truck_plate, "-", ""), ".", ""))
            == compact_plate(e.plate_no)
        )
    if e.order_code or e.booking_no:
        ids = plans_statement(scope, e).with_only_columns(TransportPlan.id)
        stmt = stmt.where(
            ContainerJob.raw_fields["transport_plan_id"]
            .as_string()
            .in_(select(func.cast(ids.subquery().c.id, String)))
        )
    return stmt
