"""Chuẩn bị phát hành sau cập nhật kế hoạch; chỉ ghi outbox trong transaction."""

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.domain.models import ExtractedContainerLine
from src.domain.rules import validate_iso6346
from src.infrastructure.models import (
    BotReply,
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    RouteMap,
    TransportPlan,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.outbound.templates import OutboundTemplateBuilder

from .schemas import ScopeContext


def prepare_notification(
    db: Session, scope: ScopeContext, message: ZaloMessage, plan: TransportPlan, job: ContainerJob
) -> str:
    """Chỉ phát hành khi đủ trường và đúng một tuyến khách; không gọi mạng trong transaction."""
    line = ExtractedContainerLine(
        line_no=1,
        line_text=message.message_text or "",
        truck_plate=plan.planned_truck_plate,
        driver_name=plan.driver_name,
        driver_phone=plan.driver_phone,
        container_no=plan.container_no,
        container_size=plan.container_size,
        seal_no=plan.seal_no,
        order_type=plan.order_type,
        customer_code_or_id=plan.customer_id,
        warehouse_code_or_id=plan.warehouse_id,
        customer_hint=plan.customer_name,
        warehouse_hint=plan.warehouse_name or plan.delivery_address,
    )
    complete, missing = OutboundTemplateBuilder.check_core_fields_completeness(line)
    if not complete or not validate_iso6346(plan.container_no):
        job.validation_status = "NEEDS_REVIEW"
        job.routing_status = "PENDING"
        warning = "Đang chờ bổ sung: " + ", ".join(missing or ["số cont hợp lệ"]) + "."
        db.add(
            BotReply(
                id=snowflake.generate(),
                message_id=message.id,
                sender_id=scope.sender_id,
                reply_text=warning,
                fix_deadline=datetime.now() + timedelta(minutes=30),
                status="PENDING",
            )
        )
        return warning
    job.validation_status = "VALID"
    aliases = (
        ["load", "dong", "lo"]
        if plan.order_type.lower() in ("load", "dong", "lo")
        else ["return", "tra", "ro"]
    )
    routes = list(
        db.scalars(
            select(RouteMap).where(
                RouteMap.is_active.is_(True),
                RouteMap.customer_id == plan.customer_id,
                or_(RouteMap.warehouse_id == plan.warehouse_id, RouteMap.warehouse_id.is_(None)),
                or_(func.lower(RouteMap.order_type).in_(aliases), RouteMap.order_type.is_(None)),
            )
        ).all()
    )
    groups = [db.get(ZaloGroup, rid) for rid in {r.zalo_group_id for r in routes}]
    groups = [
        g
        for g in groups
        if g and g.is_active and g.group_role.upper() in ("CUSTOMER", "DESTINATION")
    ]
    source = db.get(ZaloGroup, scope.group_id)
    if len(groups) != 1:
        job.routing_status = "NEEDS_REVIEW"
        from .reviews import create_scoped_review

        create_scoped_review(
            db,
            message,
            "ROUTING_NOT_FOUND",
            "Thông tin đã đủ nhưng chưa có duy nhất một nhóm khách hợp lệ trong RouteMap.",
            details={"transport_plan_id": str(plan.id), "container_no": job.container_no},
            container_job_id=job.id,
        )
        return "Thông tin đã đủ, chờ ĐHVT chọn đúng tuyến gửi khách trên Web."
    target = groups[0]
    manual = source.send_mode.upper() == "MANUAL" or target.send_mode.upper() == "MANUAL"
    content = OutboundTemplateBuilder.build_customer_notification(
        line=line,
        customer_name=plan.customer_name or "Quý khách",
        warehouse_name=plan.warehouse_name or plan.delivery_address or "",
    )
    outbound = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=target.id,
        order_type=plan.order_type,
        message_kind="supplement",
        content=content,
        idempotency_key=f"assistant-plan:{plan.id}:v{plan.version}",
        status="PENDING_APPROVAL" if manual else "PENDING_SEND",
        attempt_count=0,
    )
    db.add(outbound)
    db.flush()
    db.add(OutboundMessageItem(outbound_message_id=outbound.id, container_job_id=job.id))
    job.routing_status = "ROUTED"
    if manual:
        from .reviews import create_scoped_review

        create_scoped_review(
            db,
            message,
            "OUTBOUND_PENDING_APPROVAL",
            "Tuyến yêu cầu ĐHVT duyệt gửi trên Web.",
            details={
                "transport_plan_id": str(plan.id),
                "container_no": job.container_no,
                "outbound_message_id": str(outbound.id),
            },
            container_job_id=job.id,
        )
    return (
        "Thông báo khách đang chờ duyệt trên Web."
        if manual
        else "Thông báo khách đã vào hàng đợi gửi."
    )
