"""Điểm vào trợ lý dùng chung, nối registry với outbox và audit hiện có."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.infrastructure.ai_service_client import AIServiceClient
from src.infrastructure.models import (
    ActivityLog,
    ExtractionRun,
    MessageDraft,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake

from .intent_router import local_date, route_local
from .queries import enrich_catalog
from .schemas import AssistantReply, ToolCall
from .scope_resolver import resolve_scope
from .tool_registry import WRITE_TOOLS, allowed_tools, execute


def handle_assistant(db: Session, message: ZaloMessage, group: ZaloGroup) -> bool:
    """Trả False chỉ khi cần chuyển tin báo xe sang pipeline bóc tách."""
    # Import tại biên để tránh vòng phụ thuộc với các hàm outbox tương thích cũ.
    from src.handlers.conversation_service import _send_or_queue_group_reply

    if not (message.message_text or "").strip() or message.sender_id in ("bot", "vsico_bot"):
        return False
    previous = db.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "ASSISTANT_EXECUTED",
            ActivityLog.entity_type == "zalo_message",
            ActivityLog.entity_id == str(message.id),
        )
    )
    if previous:
        message.processing_status = (
            "NEEDS_REVIEW" if (previous.details or {}).get("needs_review") else "PROCESSED"
        )
        db.commit()
        return True
    role = {"SOURCE": "CARRIER", "DESTINATION": "CUSTOMER"}.get(
        group.group_role.upper(), group.group_role.upper()
    )
    if role not in ("CARRIER", "CUSTOMER", "DHVT"):
        return False
    call = None
    try:
        initial = route_local(
            message.message_text, role, message.zalo_sent_at or message.created_at
        )
        if role == "CARRIER" and initial.intent == "REPORT_DISPATCH":
            from .tools_carrier import report_changes_existing_plan

            if not report_changes_existing_plan(db, group, message, initial):
                return False
            initial.intent = "carrier_request_vehicle_update"
        scope = resolve_scope(db, group, message)
        call = initial
        if call.intent == "carrier_supplement_trip" and message.quote_msg_id:
            from src.infrastructure.models import BotReply, ContainerJob, ZaloMessage

            from .tools_carrier import proposed_changes

            reply_source = db.scalar(
                select(BotReply)
                .join(ZaloMessage, BotReply.message_id == ZaloMessage.id)
                .where(
                    BotReply.zalo_msg_id == message.quote_msg_id,
                    BotReply.status == "PENDING",
                    ZaloMessage.group_id == scope.zalo_group_id,
                    ZaloMessage.sender_id == scope.sender_id,
                )
            )
            if reply_source:
                jobs = list(
                    db.scalars(
                        select(ContainerJob).where(
                            ContainerJob.message_id == reply_source.message_id
                        )
                    ).all()
                )
                fields = proposed_changes(db, scope, message.message_text)
                if len(jobs) == 1 and fields:
                    job = jobs[0]
                    truck = job.truck_record
                    current = {
                        "container_no": job.container_no,
                        "seal_no": job.seal_no,
                        "planned_truck_plate": truck.truck_plate if truck else None,
                        "driver_name": truck.driver_name if truck else None,
                        "driver_phone": truck.driver_phone if truck else None,
                    }
                    if all(not current[k] or current[k] == v for k, v in fields.items()):
                        return False
        if call.intent == "IGNORE":
            message.processing_status = "PROCESSED"
            db.commit()
            return True
        ambiguous = False
        if call.intent not in WRITE_TOOLS:
            before = call.entities.model_dump()
            call.entities, ambiguous = enrich_catalog(
                db, scope, call.entities, message.message_text
            )
            if call.entities.model_dump() != before:
                call.route_source = "local_nlp"
        if call.intent == "UNKNOWN":
            proposed = AIServiceClient.assistant_intent(
                message.message_text,
                allowed_tools(scope),
                local_date(scope.reference_time).isoformat(),
            )
            if proposed:
                try:
                    parsed = ToolCall.model_validate(proposed["call"])
                    if parsed.intent in allowed_tools(scope):
                        call = parsed
                        call.route_source = "llm"
                        if call.entities.plan_date is None:
                            call.entities.plan_date = route_local(
                                message.message_text, scope.role, scope.reference_time
                            ).entities.plan_date
                except (ValueError, KeyError, TypeError):
                    pass
                db.add(
                    ExtractionRun(
                        id=snowflake.generate(),
                        message_id=message.id,
                        model_name=proposed.get("model_name") or "assistant-unknown",
                        prompt_version="assistant-intent-v1",
                        input_data={"purpose": "assistant_intent"},
                        output_data={
                            "intent": call.intent,
                            "extractor_type": "llm",
                            "latency_ms": proposed.get("latency_ms"),
                        },
                        status="SUCCESS" if call.intent != "UNKNOWN" else "FAILED",
                    )
                )
        if call.intent == "BLOCK_WRITE":
            suffix = f"/reviews/{call.entities.case_id}" if call.entities.case_id else "/reviews"
            reply = AssistantReply(
                text="Hệ thống không hỗ trợ thao tác duyệt, sửa, hủy hoặc cho gửi trực tiếp qua Zalo. "
                f"Vui lòng thao tác trên Web: {settings.FRONTEND_BASE_URL.rstrip('/')}{suffix}"
            )
        elif call.intent == "UNSUPPORTED":
            reply = AssistantReply(
                text="Phase 1 chưa có nguồn GPS, trạng thái vào bãi/đến kho hoặc POD. "
                "Bot chỉ tra giờ hẹn/ETA theo kế hoạch; bạn có thể gửi mã lệnh để xem."
            )
        elif call.intent in ("MIXED", "CLARIFY", "UNKNOWN") or ambiguous:
            reply = AssistantReply(
                text="Tin nhắn chưa rõ hoặc gồm cả hỏi và sửa. Vui lòng ghi một mã lệnh/ngày và tách thông tin muốn tra cứu khỏi thay đổi cần xác nhận."
            )
        elif (
            re.search(r"\b[A-Za-z]{4}\d{5,6}\b", message.message_text)
            and not call.entities.container_no
        ):
            reply = AssistantReply(
                text="Số container cần đủ 11 ký tự (4 chữ + 7 số). Vui lòng kiểm tra lại."
            )
        elif call.intent in ("dhvt_get_entity_stats", "customer_query_schedule") and not any(
            getattr(call.entities, k)
            for k in (
                "warehouse_name",
                "customer_name",
                "carrier_name",
                "forwarder_name",
                "booking_no",
                "bill_of_lading_no",
            )
        ):
            reply = AssistantReply(
                text="Chưa nhận diện duy nhất khách/kho/nhà xe trong phạm vi kế hoạch. Vui lòng ghi tên đầy đủ hoặc mã lệnh."
            )
        else:
            reply = execute(db, scope, call, message)
    except (PermissionError, ValueError) as exc:
        reply = AssistantReply(text=str(exc))
    outbound = _send_or_queue_group_reply(
        db, group, message, reply.text[:1950], order_type="ANSWER", dispatch=False
    )
    # Nháp lưu khóa outbox để resolve quote cả khi worker gửi sau transaction này.
    for draft in db.scalars(
        select(MessageDraft).where(
            MessageDraft.first_message_id == message.id,
            MessageDraft.entities["kind"].as_string() == "assistant_vehicle_change",
        )
    ).all():
        draft.entities = {**draft.entities, "prompt_outbound_id": str(outbound.id)}
    action = "ASSISTANT_EXECUTED"
    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=message.sender_id,
            action=action,
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={
                "intent": call.intent if call else "DENIED",
                "source": call.route_source if call else "local_rule",
                "group_id": group.zalo_group_id,
                "role": role,
                "plan_ids": reply.plan_ids,
                "needs_review": reply.needs_review,
                "outbound_id": str(outbound.id),
            },
        )
    )
    # Giữ nhãn audit cũ để màn hình giám sát đang sử dụng tiếp tục hoạt động.
    if role == "DHVT" and (call is None or call.intent == "BLOCK_WRITE"):
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=message.sender_id,
                action="DHVT_ZALO_COMMAND_REJECTED" if call else "DHVT_UNREGISTERED_LOOKUP_BLOCKED",
                entity_type="zalo_message",
                entity_id=str(message.id),
                details={"group_id": group.zalo_group_id},
            )
        )
    message.processing_status = "NEEDS_REVIEW" if reply.needs_review else "PROCESSED"
    db.commit()
    if settings.AUTO_DISPATCH_OUTBOUND and not group.is_test:
        from contextlib import nullcontext

        from src.infrastructure.models import ReviewCase
        from src.infrastructure.outbox_worker import drain_outbox

        alerts = [
            int(c.details["alert_outbound_id"])
            for c in db.scalars(select(ReviewCase).where(ReviewCase.message_id == message.id)).all()
            if (c.details or {}).get("alert_outbound_id")
        ]
        drain_outbox(lambda: nullcontext(db), [outbound.id, *alerts])
    return True
