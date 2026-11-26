"""Điểm vào trợ lý dùng chung, nối registry với outbox và audit hiện có."""

from datetime import datetime, timedelta
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.infrastructure.ai_service_client import AIServiceClient
from src.infrastructure.models import (
    ActivityLog,
    ExtractionRun,
    MessageDraft,
    OutboundMessage,
    ReviewCase,
    TransportPlan,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake

from .intent_router import ZALO_MENTION_RE, local_date, normalize, route_local
from .queries import enrich_catalog
from .schemas import AssistantReply, ScopeContext, ToolCall
from .scope_resolver import is_default_carrier_group, resolve_scope
from .tool_registry import WRITE_TOOLS, allowed_tools, execute


def _apply_short_term_memory(
    db: Session, scope: ScopeContext, call: ToolCall, raw_text: str
) -> None:
    """Giải tham chiếu hội thoại ngắn hạn (5-10 phút) như 'lệnh đầu', 'cái thứ 2', 'cái cuối'."""
    norm = normalize(raw_text)
    ordinal_idx: int | None = None
    if re.search(r"\b(lenh dau|cai dau|so 1|thu 1|thu nhat|dau tien)\b", norm):
        ordinal_idx = 0
    elif re.search(r"\b(thu 2|thu hai|so 2|cai thu 2)\b", norm):
        ordinal_idx = 1
    elif re.search(r"\b(thu 3|thu ba|so 3|cai thu 3)\b", norm):
        ordinal_idx = 2
    elif re.search(r"\b(cai cuoi|lenh cuoi|cuoi cung)\b", norm):
        ordinal_idx = -1
    if ordinal_idx is None:
        return
    if call.entities.order_code or call.entities.container_no or call.entities.case_id:
        return

    ctx_draft = db.scalar(
        select(MessageDraft)
        .where(
            MessageDraft.group_id == scope.zalo_group_id,
            MessageDraft.sender_id == scope.sender_id,
            MessageDraft.entities["kind"].as_string() == "assistant_conv_context",
            MessageDraft.expires_at > datetime.now().replace(tzinfo=None),
        )
        .order_by(MessageDraft.id.desc())
    )
    if not ctx_draft:
        return
    plan_ids = list((ctx_draft.entities or {}).get("plan_ids") or [])
    if not plan_ids:
        return
    try:
        chosen_pid = plan_ids[ordinal_idx]
    except IndexError:
        return
    if str(chosen_pid).isdigit():
        plan = db.get(TransportPlan, int(chosen_pid))
        if plan:
            if plan.order_code:
                call.entities.order_code = plan.order_code
            elif plan.container_no:
                call.entities.container_no = plan.container_no
            if call.intent == "UNKNOWN":
                call.intent = (
                    "dhvt_get_order_or_cont_detail"
                    if scope.role == "DHVT"
                    else "carrier_get_order_detail"
                )


def _save_short_term_memory(
    db: Session, scope: ScopeContext, message: ZaloMessage, reply: AssistantReply
) -> None:
    """Lưu danh sách `plan_ids` vừa tra cứu vào bộ nhớ hội thoại 10 phút cho `(group_id, sender_id)`."""
    if not reply.plan_ids or not scope.group_id:
        return
    existing = db.scalar(
        select(MessageDraft)
        .where(
            MessageDraft.group_id == scope.zalo_group_id,
            MessageDraft.sender_id == scope.sender_id,
            MessageDraft.entities["kind"].as_string() == "assistant_conv_context",
        )
        .order_by(MessageDraft.id.desc())
    )
    now = datetime.now()
    if existing is not None:
        existing.last_message_id = message.id
        existing.entities = {"kind": "assistant_conv_context", "plan_ids": reply.plan_ids[:20]}
        existing.expires_at = now + timedelta(minutes=10)
        existing.status = "OPEN"
    else:
        db.add(
            MessageDraft(
                id=snowflake.generate(),
                zalo_info_id=scope.group_id,
                group_id=scope.zalo_group_id,
                sender_id=scope.sender_id,
                carrier_id=scope.carrier_id,
                first_message_id=message.id,
                last_message_id=message.id,
                message_count=1,
                status="OPEN",
                entities={"kind": "assistant_conv_context", "plan_ids": reply.plan_ids[:20]},
                expires_at=now + timedelta(minutes=10),
            )
        )


def _build_dhvt_conversation_context(
    db: Session, group: ZaloGroup, message: ZaloMessage
) -> dict[str, object]:
    """Thu thập bối cảnh hội thoại thực của nhóm ĐHVT (tin quote, ca duyệt PENDING, @mention, 5 tin gần nhất)."""
    raw_text = message.message_text or ""
    is_bot_mentioned = bool(ZALO_MENTION_RE.search(raw_text))
    has_question_mark = "?" in raw_text
    quoted_text: str | None = None
    has_quoted_pending_case = False

    if message.quote_msg_id:
        q_mid = str(message.quote_msg_id).strip()
        q_out = db.scalar(
            select(OutboundMessage).where(
                (OutboundMessage.zalo_message_id == q_mid) | (OutboundMessage.review_zalo_msg_id == q_mid)
            )
        )
        if q_out and q_out.content:
            quoted_text = q_out.content
        else:
            q_msg = db.scalar(select(ZaloMessage).where(ZaloMessage.zalo_message_id == q_mid))
            if q_msg and q_msg.message_text:
                quoted_text = q_msg.message_text

        open_cases = list(
            db.scalars(
                select(ReviewCase)
                .where(ReviewCase.status.in_(["PENDING", "pending"]))
                .order_by(ReviewCase.id.desc())
                .limit(30)
            ).all()
        )
        for rc in open_cases:
            d = rc.details if isinstance(rc.details, dict) else {}
            if str(d.get("dhvt_zalo_msg_id") or "") == q_mid:
                has_quoted_pending_case = True
                if not quoted_text:
                    quoted_text = f"Ca duyệt chờ xử lý: {rc.reason or ''}"
                break
            if q_out and str(d.get("outbound_message_id") or "") == str(q_out.id):
                has_quoted_pending_case = True
                break

    has_pending_review_case = has_quoted_pending_case
    if not has_pending_review_case:
        cutoff_rc = datetime.now() - timedelta(minutes=10)
        has_pending_review_case = (
            db.scalar(
                select(ReviewCase.id)
                .where(
                    ReviewCase.status.in_(["PENDING", "pending"]),
                    ReviewCase.created_at >= cutoff_rc,
                )
                .limit(1)
            )
            is not None
        )

    cutoff_msg = datetime.now() - timedelta(minutes=5)
    recent_rows = list(
        db.scalars(
            select(ZaloMessage)
            .where(
                ZaloMessage.group_id == group.zalo_group_id,
                ZaloMessage.id < message.id,
                ZaloMessage.created_at >= cutoff_msg,
            )
            .order_by(ZaloMessage.id.desc())
            .limit(5)
        ).all()
    )
    recent_messages = [
        f"{(r.sender_name or 'ĐHVT')}: {(r.message_text or '').strip()}"
        for r in reversed(recent_rows)
        if (r.message_text or "").strip()
    ]
    return {
        "is_bot_mentioned": is_bot_mentioned,
        "has_question_mark": has_question_mark,
        "is_addressed_to_bot": bool(is_bot_mentioned or message.quote_msg_id or has_question_mark),
        "quoted_text": quoted_text,
        "has_quoted_pending_case": has_quoted_pending_case,
        "has_pending_review_case": has_pending_review_case,
        "recent_messages": recent_messages,
    }


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
    dhvt_ctx: dict[str, object] = (
        _build_dhvt_conversation_context(db, group, message)
        if role == "DHVT"
        else {
            "is_bot_mentioned": bool(ZALO_MENTION_RE.search(message.message_text or "")),
            "has_question_mark": "?" in (message.message_text or ""),
            "is_addressed_to_bot": True,
            "quoted_text": None,
            "has_quoted_pending_case": False,
            "has_pending_review_case": False,
            "recent_messages": [],
        }
    )
    call = None
    try:
        initial = route_local(
            message.message_text,
            role,
            message.zalo_sent_at or message.created_at,
            has_quoted_pending_case=bool(dhvt_ctx["has_quoted_pending_case"]),
            is_bot_mentioned=bool(dhvt_ctx["is_bot_mentioned"]),
        )
        if role == "CARRIER" and initial.intent == "REPORT_DISPATCH":
            from .tools_carrier import classify_partial_carrier_dispatch

            routed_intent = classify_partial_carrier_dispatch(db, group, message, initial)
            if not routed_intent:
                return False
            initial.intent = routed_intent
        scope = resolve_scope(db, group, message)
        call = initial
        _apply_short_term_memory(db, scope, call, message.message_text or "")
        if call.intent == "carrier_supplement_trip" and not call.entities.order_code:
            from src.handlers.carrier_flow_service import CarrierFlowService
            from src.parsing.trip_parser import TripParser

            parsed_supp = TripParser.parse_message(
                message.message_text or "",
                reference_time=message.zalo_sent_at or message.created_at,
            )
            supp_job, _supp_reply = CarrierFlowService.find_pending_supplement_target(
                db, message, parsed_supp
            )
            if supp_job is not None:
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
            # Nếu ĐHVT hỏi kế hoạch / chi tiết một tỉnh cụ thể (đã nhận diện từ danh mục DB)
            # mà không yêu cầu gom thống kê toàn hệ thống -> tách riêng sang `dhvt_get_province_plans`
            if (
                scope.role == "DHVT"
                and call.entities.province_name
                and not call.entities.group_by_region
                and call.intent in ("dhvt_get_daily_overview", "UNKNOWN")
            ):
                norm_q = normalize(message.message_text or "")
                is_system_agg = bool(
                    re.search(r"\b(theo tinh|tung tinh|phan bo tinh|tat ca cac tinh|toan bo)\b", norm_q)
                )
                if not is_system_agg:
                    call.intent = "dhvt_get_province_plans"
                    call.confidence = max(call.confidence, 0.9)
            # Nếu định tuyến nhầm vào `dhvt_get_province_plans` nhưng hoàn toàn không khớp tỉnh nào và có cue thống kê -> quay lại overview
            elif (
                scope.role == "DHVT"
                and call.intent == "dhvt_get_province_plans"
                and not call.entities.province_name
                and not ambiguous
            ):
                norm_q = normalize(message.message_text or "")
                if re.search(r"\b(thong ke|tong quan|tong hop|ke hoach)\b", norm_q) and not re.search(
                    r"\b(tinh|tp|thanh pho)\b", norm_q
                ):
                    call.intent = "dhvt_get_daily_overview"
                    call.confidence = max(call.confidence, 0.9)
        if call.intent == "UNKNOWN":
            phobert_candidates: list[dict[str, object]] = []
            if scope.role == "DHVT":
                from src.parsing.local_nlp_extractor import PhoBertLocalNlpEngine

                pb_res = PhoBertLocalNlpEngine.get_instance().classify_dhvt_intent(
                    message.message_text or "",
                    has_quoted_pending_case=bool(dhvt_ctx["has_quoted_pending_case"]),
                    is_bot_mentioned=bool(dhvt_ctx["is_bot_mentioned"]),
                    has_question_mark=bool(dhvt_ctx["has_question_mark"]),
                )
                phobert_candidates = pb_res.top_candidates
                # Trao đổi nội bộ không gọi bot (không @mention, không quote, không '?') và PhoBERT nghiêng về chat nội bộ -> im lặng
                if not dhvt_ctx["is_addressed_to_bot"] and pb_res.intent == "INTERNAL_CHAT_IGNORE":
                    message.processing_status = "PROCESSED"
                    db.commit()
                    return True
                proposed = AIServiceClient.assistant_intent(
                    message.message_text,
                    allowed_tools(scope),
                    local_date(scope.reference_time).isoformat(),
                    role=scope.role,
                    quoted_message=str(dhvt_ctx["quoted_text"]) if dhvt_ctx["quoted_text"] else None,
                    recent_messages=list(dhvt_ctx["recent_messages"]) if isinstance(dhvt_ctx["recent_messages"], list) else None,
                    is_bot_mentioned=bool(dhvt_ctx["is_bot_mentioned"]),
                    has_pending_review_case=bool(dhvt_ctx["has_pending_review_case"]),
                    phobert_candidates=phobert_candidates,
                )
            else:
                proposed = AIServiceClient.assistant_intent(
                    message.message_text,
                    allowed_tools(scope),
                    local_date(scope.reference_time).isoformat(),
                )
            if proposed:
                try:
                    parsed = ToolCall.model_validate(proposed["call"])
                    valid_llm_intents = set(allowed_tools(scope)) | {"IGNORE", "BLOCK_WRITE"}
                    if parsed.intent in valid_llm_intents:
                        call = parsed
                        call.route_source = "llm"
                        if call.intent not in ("IGNORE", "BLOCK_WRITE") and call.entities.plan_date is None:
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
                        prompt_version=str(proposed.get("prompt_version") or "assistant-intent-v2"),
                        input_data={"purpose": "assistant_intent", "phobert_candidates": phobert_candidates},
                        output_data={
                            "intent": call.intent,
                            "extractor_type": "llm",
                            "latency_ms": proposed.get("latency_ms"),
                        },
                        status="SUCCESS" if call.intent != "UNKNOWN" else "FAILED",
                    )
                )
        if call.intent == "IGNORE" or (
            scope.role == "DHVT" and call.intent == "UNKNOWN" and not dhvt_ctx["is_addressed_to_bot"]
        ):
            message.processing_status = "PROCESSED"
            db.commit()
            return True
        if call.intent == "BLOCK_WRITE":
            norm_blk = normalize(message.message_text or "")
            if re.search(r"\b(xoa|delete|clear|reset|drop)\b", norm_blk):
                reply = AssistantReply(
                    text="Hệ thống không hỗ trợ thao tác xóa hoặc sửa hàng loạt dữ liệu kế hoạch qua Zalo. "
                    f"Vui lòng thao tác trên Web quản lý: {settings.FRONTEND_BASE_URL.rstrip('/')}/plans"
                )
            else:
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
            scope.role == "CUSTOMER"
            and not scope.routes
            and db.scalar(
                select(TransportPlan.id)
                .where(TransportPlan.group_id == scope.zalo_group_id)
                .limit(1)
            )
            is None
        ):
            reply = AssistantReply(
                text="Nhóm khách hàng chưa được cấu hình RouteMap định tuyến. Vui lòng liên hệ ĐHVT để gán tuyến."
            )
        elif (
            scope.role == "CARRIER"
            and not scope.carrier_id
            and not is_default_carrier_group(scope.zalo_group_id)
            and db.scalar(
                select(TransportPlan.id)
                .where(TransportPlan.group_id == scope.zalo_group_id)
                .limit(1)
            )
            is None
        ):
            reply = AssistantReply(
                text="Nhóm Zalo này chưa được liên kết với Nhà xe trong hệ thống. Vui lòng liên hệ ĐHVT để gắn Nhà xe cho nhóm."
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
            _save_short_term_memory(db, scope, message, reply)
    except (PermissionError, ValueError) as exc:
        reply = AssistantReply(text=str(exc))
    outbound = _send_or_queue_group_reply(
        db, group, message, reply.text[:1950], order_type="ANSWER", dispatch=False
    )
    extra_outbound_ids: list[int] = []
    for extra_part in reply.extra_texts:
        clean_part = (extra_part or "").strip()
        if not clean_part:
            continue
        extra_ob = _send_or_queue_group_reply(
            db, group, message, clean_part[:1950], order_type="ANSWER", dispatch=False
        )
        extra_outbound_ids.append(extra_ob.id)
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
                "extra_outbound_ids": [str(eid) for eid in extra_outbound_ids],
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
    from src.handlers.carrier_flow_service import CarrierFlowService

    if settings.AUTO_DISPATCH_OUTBOUND and not CarrierFlowService.is_test_message(message, group):
        from contextlib import nullcontext

        from src.infrastructure.models import ReviewCase
        from src.infrastructure.outbox_worker import drain_outbox

        alerts = [
            int(c.details["alert_outbound_id"])
            for c in db.scalars(select(ReviewCase).where(ReviewCase.message_id == message.id)).all()
            if (c.details or {}).get("alert_outbound_id")
        ]
        drain_outbox(lambda: nullcontext(db), [outbound.id, *extra_outbound_ids, *alerts])
    return True
