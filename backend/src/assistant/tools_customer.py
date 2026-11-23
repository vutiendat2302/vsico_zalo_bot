"""Công cụ khách hàng: tra cứu có phạm vi, yêu cầu thay đổi chỉ tạo ca Web."""

import re

from sqlalchemy import Integer, String, func, select
from sqlalchemy.orm import Session

from src.infrastructure.models import (
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    TransportPlan,
    ZaloMessage,
)

from .intent_router import normalize
from .queries import plan_outbounds, plans_statement, scoped_cases, scoped_jobs_statement
from .response_formatter import NOT_FOUND, customer_job_line, format_plans
from .schemas import AssistantReply, Entities, ScopeContext, ToolCall


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
    date_label = (
        f" | {call.entities.plan_date.strftime('%d/%m')}"
        if call.entities.plan_date
        else ""
    )
    assigned_pct = f"{(assigned / total) * 100:.1f}%".replace(".", ",") if total else "0,0%"
    unassigned = total - assigned
    unassigned_pct = f"{(unassigned / total) * 100:.1f}%".replace(".", ",") if total else "0,0%"

    ret_sizes: dict[str, int] = {}
    load_sizes: dict[str, int] = {}
    ret_total = 0
    load_total = 0
    for kind, size, count, _ in rows:
        k_low = (kind or "").strip().lower()
        sz = (size or "").strip()
        if k_low in ("tra", "return", "ro"):
            ret_total += count
            if sz:
                ret_sizes[sz] = ret_sizes.get(sz, 0) + count
        elif k_low in ("dong", "load", "lo"):
            load_total += count
            if sz:
                load_sizes[sz] = load_sizes.get(sz, 0) + count

    def _fmt_sizes(size_map: dict[str, int]) -> str:
        """Định dạng danh sách cỡ container ngắn gọn (VD: 9 cont 20' · 62 cont 40')."""
        if not size_map:
            return ""
        parts = [f"{cnt} cont {sz}'" for sz, cnt in sorted(size_map.items())]
        return " (" + " · ".join(parts) + ")"

    ret_pct = f"{(ret_total / total) * 100:.1f}%".replace(".", ",") if total else "0,0%"
    load_pct = f"{(load_total / total) * 100:.1f}%".replace(".", ",") if total else "0,0%"

    breakdown_lines: list[str] = []
    if ret_total:
        breakdown_lines.append(f"• Lệnh trả: {ret_total} ({ret_pct}){_fmt_sizes(ret_sizes)}")
    if load_total:
        breakdown_lines.append(f"• Lệnh đóng: {load_total} ({load_pct}){_fmt_sizes(load_sizes)}")

    lines = [
        f"[VSICO] - 📊 KẾ HOẠCH VẬN CHUYỂN{date_label}",
        "",
        f"🚛 {total} lệnh vận chuyển",
        f"✅ Đã bố trí xe: {assigned} ({assigned_pct})",
        f"⏳ Chưa có xe: {unassigned} ({unassigned_pct})",
        f"📢 Đã phát hành thông báo: {sent}",
    ]
    if breakdown_lines:
        lines.extend(["", "Phân loại:", *breakdown_lines])
    return AssistantReply(text="\n".join(lines))


def _booking_count_line(db: Session, scope: ScopeContext, entities: Entities) -> tuple[str | None, list[str]]:
    """Đếm nhanh tổng số lệnh và số đã có xe cho Booking hoặc B/L khi khách hỏi số lượng."""
    filter_e = Entities(
        plan_date=entities.plan_date,
        booking_no=entities.booking_no,
        bill_of_lading_no=entities.bill_of_lading_no,
    )
    sub = plans_statement(scope, filter_e).subquery()
    row = db.execute(
        select(
            func.count(),
            func.sum(
                (func.length(func.trim(func.coalesce(sub.c.planned_truck_plate, ""))) > 0).cast(
                    Integer
                )
            ),
        )
    ).one()
    total = int(row[0] or 0)
    if total == 0:
        return None, []
    assigned = int(row[1] or 0)
    label = (
        f"Booking {entities.booking_no}"
        if entities.booking_no
        else f"B/L {entities.bill_of_lading_no}"
    )
    sample_ids = [
        str(pid) for pid in db.scalars(select(sub.c.id).limit(20)).all()
    ]
    return (
        f"{label}: tổng {total} lệnh (đã có xe: {assigned}, chưa có xe: {total - assigned}).",
        sample_ids,
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
                f"Yêu cầu ({(c.details or {}).get('order_code') or c.container_no or (c.details or {}).get('booking_no') or c.case_type}): {c.status}"
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
    is_count_booking = bool(
        (call.entities.booking_no or call.entities.bill_of_lading_no)
        and re.search(
            r"\b(may|bao nhieu)\s+(xe|chuyen|lenh|cont)\b",
            normalize(message.message_text or ""),
        )
    )
    has_specific_trip = bool(
        call.entities.container_no or call.entities.order_code or call.entities.plate_no
    )
    if name in ("customer_query_schedule", "customer_get_trip_detail", "customer_get_vehicle_driver") and is_count_booking:
        count_line, count_plan_ids = _booking_count_line(db, scope, call.entities)
        if not has_specific_trip:
            if not count_line:
                return AssistantReply(text=NOT_FOUND)
            return AssistantReply(
                text=count_line,
                plan_ids=count_plan_ids,
            )
        # Khi hỏi cả số lượng Booking và chi tiết 1 cont/lệnh cụ thể, tách truy vấn chi tiết để không bị trôi bởi danh sách Booking.
        trip_entities = call.entities.model_copy(
            update={"booking_no": None, "bill_of_lading_no": None}
        )
        trip_plans = list(
            db.scalars(plans_statement(scope, trip_entities).order_by(TransportPlan.id).limit(21)).all()
        )
        trip_reply = format_plans(
            trip_plans,
            f"Kế hoạch {trip_entities.plan_date}:" if trip_entities.plan_date else "Thông tin tra cứu:",
            detail=True,
        )
        if not trip_plans:
            jobs = list(
                db.scalars(
                    scoped_jobs_statement(scope, trip_entities)
                    .order_by(ContainerJob.id.desc())
                    .limit(3)
                ).all()
            )
            if jobs:
                trip_reply.text = "Thông tin tra cứu:\n" + "\n".join(customer_job_line(j) for j in jobs)
        if count_line and trip_plans:
            return AssistantReply(
                text=count_line + "\n" + trip_reply.text,
                plan_ids=list(dict.fromkeys(count_plan_ids + trip_reply.plan_ids)),
            )
        if count_line:
            return AssistantReply(
                text=count_line + "\nKhông tìm thấy chuyến khớp mã cont/lệnh còn lại trong phạm vi nhóm.",
                plan_ids=count_plan_ids,
            )
        return trip_reply

    default_title = (
        f"Kế hoạch {call.entities.plan_date}:"
        if call.entities.plan_date
        else ("Thông tin container:" if call.entities.container_no else "Kế hoạch tra cứu:")
    )
    reply = format_plans(
        plans,
        default_title,
        detail=name.endswith(("get_trip_detail", "get_vehicle_driver")),
    )

    if not plans and name.endswith(("get_trip_detail", "get_vehicle_driver")):
        jobs = list(
            db.scalars(
                scoped_jobs_statement(scope, call.entities)
                .order_by(ContainerJob.id.desc())
                .limit(3)
            ).all()
        )
        if jobs:
            reply.text = "Thông tin container:\n" + "\n".join(customer_job_line(j) for j in jobs)
    return reply
