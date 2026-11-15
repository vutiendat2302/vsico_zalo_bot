"""Công cụ khách hàng: tra cứu có phạm vi, yêu cầu thay đổi chỉ tạo ca Web."""

from sqlalchemy import Integer, String, func, select
from sqlalchemy.orm import Session

from src.infrastructure.models import (
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    TransportPlan,
    ZaloMessage,
)

from .queries import plan_outbounds, plans_statement, scoped_cases, scoped_jobs_statement
from .response_formatter import NOT_FOUND, format_plans, job_line
from .schemas import AssistantReply, ScopeContext, ToolCall


def summary(db: Session, scope: ScopeContext, call: ToolCall) -> AssistantReply:
    """Đếm toàn bộ kết quả bằng SQL, không lấy số lượng từ trang hiển thị."""
    sub = plans_statement(scope, call.entities).subquery()
    rows = db.execute(
        select(
            sub.c.order_type,
            sub.c.container_size,
            func.count(),
            func.sum(
                (func.length(func.trim(func.coalesce(sub.c.planned_truck_plate, ""))) > 0).cast(
                    Integer
                )
            ),
        ).group_by(sub.c.order_type, sub.c.container_size)
    ).all()
    if not rows:
        return AssistantReply(text=NOT_FOUND)
    total = sum(r[2] for r in rows)
    assigned = sum(int(r[3] or 0) for r in rows)
    sent_stmt = (
        select(func.count(func.distinct(ContainerJob.raw_fields["transport_plan_id"].as_string())))
        .select_from(ContainerJob)
        .join(OutboundMessageItem)
        .join(OutboundMessage)
        .where(
            ContainerJob.raw_fields["transport_plan_id"]
            .as_string()
            .in_(select(func.cast(sub.c.id, String))),
            OutboundMessage.status == "SENT",
            OutboundMessage.message_kind != "answer",
        )
    )
    if scope.role == "CUSTOMER":
        sent_stmt = sent_stmt.where(OutboundMessage.target_group_id == scope.group_id)
    sent = db.scalar(sent_stmt) or 0
    return AssistantReply(
        text=f"Tổng quan kế hoạch vận chuyển {call.entities.plan_date}: {total} lệnh.\n"
        f"Đã có xe: {assigned}; chưa có xe: {total - assigned}; đã phát hành thông báo: {sent} lệnh.\n"
        + "\n".join(f"{kind} / {size or 'Chưa rõ cỡ'}: {count}" for kind, size, count, _ in rows)
    )


def run_customer(
    db: Session, scope: ScopeContext, call: ToolCall, message: ZaloMessage
) -> AssistantReply:
    """Thi hành nhóm công cụ C01–C09 sau khi registry đã kiểm quyền."""
    name = call.intent
    if name.endswith("get_summary"):
        return summary(db, scope, call)
    if name.endswith("get_request_status"):
        cases = scoped_cases(db, scope, call.entities)
        return AssistantReply(
            text="\n".join(
                f"Ca #{c.id}: {c.status}"
                + (
                    f" — {(c.resolution or {}).get('reason')}"
                    if (c.resolution or {}).get("reason")
                    else ""
                )
                for c in cases[:20]
            )
            or NOT_FOUND
        )
    if name.endswith("create_change_request") and call.entities.order_code:
        call.entities.plate_no = call.entities.container_no = None
    plans = list(
        db.scalars(plans_statement(scope, call.entities).order_by(TransportPlan.id).limit(21)).all()
    )
    if name.endswith("create_change_request"):
        from .tools_carrier import create_request

        if (
            not (call.entities.container_no or call.entities.order_code or call.entities.plate_no)
            or len(plans) != 1
        ):
            return AssistantReply(
                text=NOT_FOUND
                if not plans
                else "Vui lòng ghi mã lệnh hoặc số cont của một chuyến cần thay đổi."
            )
        return create_request(db, scope, message, plans[0], "CUSTOMER_CHANGE_REQUEST")
    if name.endswith("get_trip_changes"):
        lines = []
        for p in plans:
            sent = [
                o
                for o in plan_outbounds(db, p)
                if o.status == "SENT"
                and o.message_kind == "update"
                and o.target_group_id == scope.group_id
            ]
            if sent:
                lines.append(
                    f"{p.order_code or p.container_no}: đã phát hành đính chính lúc {sent[-1].sent_at}.\n{sent[-1].content}"
                )
        return AssistantReply(
            text="\n".join(lines[:20]) or "Chưa có thay đổi đã phát hành trong phạm vi tra cứu."
        )
    reply = format_plans(
        plans,
        f"Kế hoạch {call.entities.plan_date}:",
        detail=name.endswith(("get_trip_detail", "get_vehicle_driver")),
    )

    if name.endswith(("get_trip_detail", "get_vehicle_driver")):
        jobs = list(
            db.scalars(
                scoped_jobs_statement(scope, call.entities)
                .order_by(ContainerJob.id.desc())
                .limit(3)
            ).all()
        )
        if jobs:
            if not plans:
                reply.text = "Thông tin nhà xe đã báo trong phạm vi nhóm:"
            reply.text += "\n" + "\n".join(
                job_line(j, mask_phone=name.endswith("get_trip_detail")) for j in jobs
            )
    return reply
