"""Xác thực vai trò và tạo bộ lọc SQL bắt buộc cho kế hoạch."""

from datetime import UTC, datetime

from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from src.infrastructure.models import Carrier, RouteMap, TransportPlan, User, ZaloGroup, ZaloMessage

from .schemas import RouteScope, ScopeContext


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
        cid = str(group.carrier_id or "")
        carrier = db.get(Carrier, int(cid)) if cid.isdigit() else None
        if not carrier or not carrier.is_active:
            raise PermissionError(
                "Nhóm chưa được liên kết với Nhà xe đang hoạt động. Vui lòng liên hệ ĐHVT."
            )
        carrier_id = carrier.id
    elif role == "DHVT":
        users = list(
            db.scalars(
                select(User).where(
                    User.zalo_user_id == message.sender_id,
                    User.is_active.is_(True),
                    func.lower(User.role).in_(["admin", "dhvt"]),
                    User.zalo_info_id == group.id,
                )
            ).all()
        )
        if len(users) != 1:
            raise PermissionError(
                "Tài khoản Zalo chưa được gắn duy nhất với nhân viên ĐHVT của nhóm."
            )
        user_id = users[0].id
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
    """Ép phạm vi trên SQL; group_id mặc định không phải quyền xem dữ liệu khách."""
    if scope.role == "DHVT":
        return true() if scope.user_id else false()
    if scope.role == "CARRIER":
        return TransportPlan.carrier_id == scope.carrier_id if scope.carrier_id else false()
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
    return or_(*conditions) if conditions else false()
