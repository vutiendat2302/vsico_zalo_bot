"""Xác thực vai trò và tạo bộ lọc SQL bắt buộc cho kế hoạch."""

from datetime import UTC, datetime

from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from src.config.settings import settings
from src.infrastructure.models import Carrier, RouteMap, TransportPlan, User, ZaloGroup, ZaloMessage

from .schemas import RouteScope, ScopeContext


def is_default_carrier_group(zalo_group_id: str | None) -> bool:
    """Kiểm tra nhóm Zalo có phải nhóm nhà xe mặc định áp dụng cho toàn bộ nhà xe khi test hay không."""
    default_gid = (settings.DEFAULT_CARRIER_GROUP_ID or "").strip()
    return bool(default_gid and zalo_group_id and zalo_group_id.strip() == default_gid)


def _find_carrier_by_group_ref(db: Session, raw_carrier_id: str) -> Carrier | None:
    """Tìm nhà xe theo Snowflake id, tms_carrier_id hoặc mã code trên zalo_groups.carrier_id."""
    cid_str = raw_carrier_id.strip()
    filters = [Carrier.code == cid_str]
    if cid_str.isdigit():
        cid_int = int(cid_str)
        filters.append(Carrier.id == cid_int)
        filters.append(Carrier.tms_carrier_id == cid_int)
    return db.scalar(select(Carrier).where(or_(*filters)))


def resolve_scope(db: Session, group: ZaloGroup, message: ZaloMessage) -> ScopeContext:
    """Từ chối nhóm không hoạt động, nhà xe chưa gắn và nhân viên không hợp lệ."""
    roles = {
        "SOURCE": "CARRIER",
        "CARRIER": "CARRIER",
        "CUSTOMER": "CUSTOMER",
        "DESTINATION": "CUSTOMER",
        "DHVT": "DHVT",
    }
    role = roles.get((group.group_role or "").upper())
    if not group.is_active or not role or message.group_id != group.zalo_group_id:
        raise PermissionError("Nhóm chưa được cấu hình quyền tra cứu.")
    carrier_id = user_id = None
    routes = ()
    if role == "CARRIER":
        cid = str(group.carrier_id or "").strip()
        if cid:
            carrier = _find_carrier_by_group_ref(db, cid)
            if not carrier or not carrier.is_active:
                raise PermissionError(
                    "Nhóm chưa được liên kết với Nhà xe đang hoạt động. Vui lòng liên hệ ĐHVT."
                )
            carrier_id = carrier.id
    elif role == "DHVT":
        by_sender = list(
            db.scalars(select(User).where(User.zalo_user_id == message.sender_id)).all()
        )
        if by_sender:
            users = [
                u
                for u in by_sender
                if u.is_active
                and (u.role or "").lower() in ("admin", "dhvt")
                and (u.zalo_info_id == group.id or u.zalo_info_id is None)
            ]
            if len(users) != 1:
                raise PermissionError(
                    "Tài khoản Zalo chưa được gắn duy nhất với nhân viên ĐHVT của nhóm."
                )
            user_id = users[0].id
        elif not group.is_test:
            has_registered_staff = db.scalar(
                select(User.id)
                .where(
                    User.zalo_info_id == group.id,
                    User.is_active.is_(True),
                )
                .limit(1)
            )
            if has_registered_staff is not None:
                raise PermissionError(
                    "Tài khoản Zalo của bạn chưa được gắn với nhân viên ĐHVT đang hoạt động trong hệ thống."
                )
    else:
        routes = tuple(
            RouteScope(
                customer_id=r.customer_id, warehouse_id=r.warehouse_id, order_type=r.order_type
            )
            for r in db.scalars(
                select(RouteMap).where(
                    RouteMap.zalo_group_id == group.id, RouteMap.is_active.is_(True)
                )
            ).all()
        )
    return ScopeContext(
        role=role,
        group_id=group.id,
        zalo_group_id=group.zalo_group_id,
        sender_id=message.sender_id,
        carrier_id=carrier_id,
        user_id=user_id,
        routes=routes,
        reference_time=message.zalo_sent_at or message.created_at or datetime.now(UTC),
    )


def plan_scope(scope: ScopeContext) -> ColumnElement[bool]:
    """Ép phạm vi trên SQL: ưu tiên RouteMap/carrier_id, nếu chưa gắn thì kiểm tra nhóm test mặc định hoặc group_id."""
    if scope.role == "DHVT":
        return true()
    if scope.role == "CARRIER":
        if scope.carrier_id:
            return TransportPlan.carrier_id == scope.carrier_id
        if is_default_carrier_group(scope.zalo_group_id):
            return true()
        return TransportPlan.group_id == scope.zalo_group_id
    conditions = []
    for route in scope.routes:
        terms = [TransportPlan.customer_id == route.customer_id]
        if route.warehouse_id is not None:
            terms.append(TransportPlan.warehouse_id == route.warehouse_id)
        if route.order_type:
            order = route.order_type.lower()
            aliases = (
                ["load", "dong", "lo"]
                if order in ("load", "dong", "lo")
                else (["return", "tra", "ro"] if order in ("return", "tra", "ro") else [order])
            )
            terms.append(func.lower(TransportPlan.order_type).in_(aliases))
        conditions.append(and_(*terms))
    if conditions:
        return or_(*conditions)
    return TransportPlan.group_id == scope.zalo_group_id
