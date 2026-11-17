"""Nhà xe tra cứu và xác nhận thay đổi đúng kế hoạch, người gửi và phiên bản."""

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.domain.rules import clean_phone, clean_plate, compact_plate, validate_iso6346
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    ContainerJob,
    Driver,
    MessageDraft,
    TransportPlan,
    TruckRecord,
    Vehicle,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake

from .intent_router import CONTAINER_RE, PLATE_RE, normalize, strip_zalo_mentions
from .queries import plan_jobs, plan_outbounds, plans_statement, scoped_cases
from .response_formatter import NOT_FOUND, format_plans
from .schemas import AssistantReply, ScopeContext, ToolCall
from .scope_resolver import is_default_carrier_group, plan_scope, resolve_scope
from .tools_customer import summary

ORDER_CODE_MULTI_RE = re.compile(r"\b(?:RO|LO)\d{3,8}\b", re.IGNORECASE)

DRAFT_KIND = "assistant_vehicle_change"


def create_job_snapshot(
    db: Session,
    message: ZaloMessage,
    plan: TransportPlan,
    changes: dict[str, Any],
    *,
    review: bool = False,
) -> ContainerJob:
    """Tạo phiên bản báo xe riêng để không sửa lịch sử tin đã phát hành."""
    truck = TruckRecord(
        id=snowflake.generate(),
        message_id=message.id,
        truck_plate=changes.get("planned_truck_plate", plan.planned_truck_plate),
        driver_name=changes.get("driver_name", plan.driver_name),
        driver_phone=changes.get("driver_phone", plan.driver_phone),
    )
    db.add(truck)
    db.flush()
    job = ContainerJob(
        id=snowflake.generate(),
        message_id=message.id,
        truck_record_id=truck.id,
        container_no=changes.get("container_no", plan.container_no),
        container_size=plan.container_size,
        seal_no=changes.get("seal_no", plan.seal_no),
        order_type=plan.order_type,
        customer_id=plan.customer_id,
        warehouse_id=plan.warehouse_id,
        is_update=True,
        validation_status="PENDING",
        routing_status="PENDING",
        tms_sync_status="NOT_STARTED" if review else "PENDING",
        raw_fields={
            "transport_plan_id": str(plan.id),
            "expected_plan_version": plan.version,
            "assistant_proposal": changes,
            "eta": changes.get("eta"),
        },
    )
    db.add(job)
    db.flush()
    return job


def create_request(
    db: Session,
    scope: ScopeContext,
    message: ZaloMessage,
    plan: TransportPlan,
    case_type: str,
    changes: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AssistantReply:
    """Lưu đề xuất vào ca Web có scope và diff, không sửa kế hoạch khi cần duyệt."""
    job = (
        create_job_snapshot(db, message, plan, changes, review=True)
        if changes is not None
        else None
    )
    from .reviews import create_scoped_review

    case = create_scoped_review(
        db,
        message,
        case_type,
        reason or (message.message_text or "")[:1000],
        details={
            "group_id": scope.zalo_group_id,
            "sender_id": scope.sender_id,
            "carrier_id": str(scope.carrier_id) if scope.carrier_id else None,
            "transport_plan_id": str(plan.id),
            "container_no": plan.container_no,
            "expected_version": plan.version,
            "proposed_changes": changes or {},
            "requested_action": "CANCEL"
            if "huy" in normalize(message.message_text or "")
            else "CHANGE",
        },
        container_job_id=job.id if job else None,
        priority="HIGH"
        if case_type == "CARRIER_CANCEL_OR_ISSUE" or "huy" in normalize(message.message_text or "")
        else "NORMAL",
    )
    target_label = (
        plan.order_code
        or plan.container_no
        or plan.booking_no
        or plan.warehouse_name
        or plan.customer_name
        or "chuyến vận chuyển"
    )
    return AssistantReply(
        text=f"Đã ghi nhận yêu cầu cho {target_label}, chờ ĐHVT xử lý trên Web. Kế hoạch chưa bị thay đổi.",
        needs_review=True,
    )


def proposed_changes(db: Session, scope: ScopeContext, text: str) -> dict[str, Any]:
    """Chỉ lấy trường tường minh từ tin nhắn; chuẩn hóa SĐT `0/+84/84` và không đoán ID khi trùng tên."""
    result = {}
    plates = PLATE_RE.findall(text)
    if plates:
        raw_p = re.sub(r"\s+", " ", plates[-1].strip()).upper()
        result["planned_truck_plate"] = clean_plate(raw_p) or raw_p
    raw_phones = re.findall(r"(?<!\d)(?:\+?84[\s.\-]?|0)\d(?:[\s.\-]?\d){8}(?!\d)", text)
    phones = [
        cleaned
        for raw_ph in raw_phones
        if (cleaned := clean_phone(raw_ph)) and re.fullmatch(r"0\d{9}", cleaned)
    ]
    if len(set(phones)) > 1:
        raise ValueError("Có nhiều SĐT; vui lòng ghi rõ một tài xế cần cập nhật.")
    if phones:
        result["driver_phone"] = phones[0]
    conts = CONTAINER_RE.findall(text)
    if conts:
        if not validate_iso6346(conts[-1]):
            raise ValueError(
                "Số container chưa đúng ISO 6346; vui lòng kiểm tra lại, hệ thống không tự sửa số."
            )
        result["container_no"] = conts[-1].upper()
    seal = re.search(r"\b(?:chì|chi|seal)\s+(?:là\s+|la\s+)?([A-Za-z0-9-]+)", text, re.IGNORECASE)
    if seal and normalize(seal[1]) not in ("bao", "sau", "chua", "dung", "cu", "moi"):
        result["seal_no"] = seal[1].upper()
    name = re.search(
        r"(?:tài xế|tai xe|lái xe|lai xe|tài|tai|tx)\s+([^\d,;\n]+)", text, re.IGNORECASE
    )
    if name:
        value = re.split(
            r"\b(?:sđt|sdt|cont|chì|chi|seal|nhé|nhe|hẹn|hen)\b", name[1], flags=re.IGNORECASE
        )[0].strip()
        value = re.sub(r"^(?:sang|là|la|thành|thanh)\s+", "", value, flags=re.IGNORECASE).strip()
        if value:
            result["driver_name"] = value
    if scope.carrier_id:
        drivers = list(
            db.scalars(
                select(Driver).where(Driver.carrier_id == scope.carrier_id, Driver.is_active.is_(True))
            ).all()
        )
    elif is_default_carrier_group(scope.zalo_group_id):
        drivers = list(db.scalars(select(Driver).where(Driver.is_active.is_(True))).all())
    else:
        drivers = []
    matches = [
        d
        for d in drivers
        if (
            result.get("driver_name")
            and (
                normalize(d.full_name) == normalize(result["driver_name"])
                or normalize(d.full_name).endswith(" " + normalize(result["driver_name"]))
            )
        )
        or (result.get("driver_phone") and clean_phone(d.phone) == result["driver_phone"])
    ]
    if len(matches) == 1:
        d = matches[0]
        if result.get("driver_name") and not (
            normalize(d.full_name) == normalize(result["driver_name"])
            or normalize(d.full_name).endswith(" " + normalize(result["driver_name"]))
        ):
            # Nếu SĐT khớp duy nhất tài xế nhưng tên không khớp, giữ nguyên cả hai để TMS xác thực.
            return result
        if (
            result.get("driver_phone")
            and d.phone
            and clean_phone(d.phone) != result["driver_phone"]
        ):
            return result
        result.setdefault("driver_name", d.full_name)
        if d.phone:
            result.setdefault("driver_phone", clean_phone(d.phone))
    return result


def resolve_update_target(
    db: Session, scope: ScopeContext, call: ToolCall, message: ZaloMessage
) -> list[TransportPlan]:
    """Chỉ chọn mục tiêu duy nhất qua mã lệnh, xe cũ, quote hoặc lịch sử chính người gửi."""
    e = call.entities.model_copy(deep=True)
    if e.order_code:
        e.plate_no = e.container_no = None
    elif (
        len(PLATE_RE.findall(message.message_text or "")) < 2
        and call.intent != "carrier_supplement_trip"
    ):
        e.plate_no = None
    has_key = bool(e.order_code or e.container_no or e.plate_no)
    if has_key:
        return list(
            db.scalars(
                plans_statement(scope, e)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
    now = datetime.now()
    stmt = (
        select(ContainerJob)
        .join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
        .where(
            ZaloMessage.group_id == scope.zalo_group_id, ZaloMessage.sender_id == scope.sender_id
        )
    )
    if message.quote_msg_id:
        stmt = stmt.where(ZaloMessage.zalo_message_id == message.quote_msg_id)
    else:
        stmt = stmt.where(ZaloMessage.created_at >= now - timedelta(minutes=30))
    ids = {(j.raw_fields or {}).get("transport_plan_id") for j in db.scalars(stmt).all()}
    ids.discard(None)
    return (
        list(
            db.scalars(
                select(TransportPlan)
                .where(plan_scope(scope), TransportPlan.id.in_(ids))
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        if ids
        else []
    )


def apply_change(
    db: Session,
    scope: ScopeContext,
    message: ZaloMessage,
    plan: TransportPlan,
    changes: dict[str, Any],
) -> AssistantReply:
    """Hậu kiểm tại lúc xác nhận, khóa kế hoạch và cập nhật nguyên tử kèm audit."""
    changes = {k: v for k, v in changes.items() if getattr(plan, k) != v}
    if not changes:
        return AssistantReply(
            text="Thông tin đã trùng với kế hoạch; không ghi lặp hoặc tăng phiên bản."
        )
    if changes.get("container_no") and not validate_iso6346(changes["container_no"]):
        raise ValueError("Số container không hợp lệ.")
    if plan.order_type.lower() in ("tra", "return", "ro") and any(
        k in changes and getattr(plan, k) for k in ("container_no", "seal_no")
    ):
        return create_request(
            db,
            scope,
            message,
            plan,
            "PLAN_FIELD_CONFLICT",
            changes,
            "Nhà xe báo lệch cont/chì gốc của lệnh trả.",
        )
    # Khóa xe trong danh mục nhà xe (nếu có) và kiểm tra trùng xe cùng ngày; không từ chối chỉ vì thiếu `vehicle_id`.
    if plate := changes.get("planned_truck_plate"):
        target_cid = scope.carrier_id or plan.carrier_id
        if target_cid:
            list(
                db.scalars(
                    select(Vehicle)
                    .where(Vehicle.is_active.is_(True), Vehicle.vehicle_type == 1, Vehicle.carrier_id == target_cid)
                    .order_by(Vehicle.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).all()
            )
        other_plans = list(
            db.scalars(
                select(TransportPlan).where(
                    plan_scope(scope),
                    TransportPlan.plan_date == plan.plan_date,
                    TransportPlan.id != plan.id,
                )
            ).all()
        )
        # Chưa có thời lượng vận chuyển: nhiều chuyến cùng đầu kéo cần ĐHVT kiểm tra, không khẳng định trùng lịch.
        if any(
            compact_plate(p.planned_truck_plate or "") == compact_plate(plate) for p in other_plans
        ):
            return create_request(
                db,
                scope,
                message,
                plan,
                "PLAN_FIELD_CONFLICT",
                changes,
                "Xe mới đã có lệnh khác cùng ngày; cần kiểm tra tính khả thi lịch.",
            )
    outbounds = plan_outbounds(db, plan)
    if any(o.status in ("SENT", "SENDING", "PENDING_SEND", "PENDING_APPROVAL") for o in outbounds):
        return create_request(
            db,
            scope,
            message,
            plan,
            "REVIEW_CHANGE_AFTER_SENT",
            changes,
            "Chuyến đã phát hành hoặc có tin đang chờ gửi; cần duyệt đính chính trên Web.",
        )
    if changes.get("container_no"):
        # Hai chặng RO/LO dùng chung cont cần giữ nguyên quyết định của bộ ghép; không tự tạo ghép khi sửa.
        others = list(
            db.scalars(
                select(TransportPlan).where(
                    TransportPlan.container_no == changes["container_no"],
                    TransportPlan.plan_date == plan.plan_date,
                    TransportPlan.id != plan.id,
                )
            ).all()
        )
        if others:
            return create_request(
                db,
                scope,
                message,
                plan,
                "PLAN_FIELD_CONFLICT",
                changes,
                "Container đã có trên lệnh khác; cần kiểm tra ghép chặng.",
            )
    before_values = {k: getattr(plan, k) for k in changes}
    prev_container_no = plan.container_no
    diff = [{"field": k, "old": getattr(plan, k), "new": v} for k, v in changes.items()]
    for k, v in changes.items():
        setattr(plan, k, v)
    plan.version += 1
    plan.tms_sync_status = "PENDING"
    job = create_job_snapshot(db, message, plan, changes)
    from src.handlers.plan_sync_service import mask_pii_payload, sync_plan_to_tms

    sync_status = sync_plan_to_tms(
        db,
        plan,
        job=job,
        changed_fields=changes,
        before_values=before_values,
        previous_container_no=prev_container_no,
        actor_id=scope.sender_id,
    )
    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=scope.sender_id,
            action="PLAN_VEHICLE_UPDATED",
            entity_type="transport_plan",
            entity_id=str(plan.id),
            details={
                "message_id": str(message.id),
                "job_id": str(job.id),
                "version": plan.version,
                "updated_fields": mask_pii_payload({"items": diff}).get("items", []),
                "confirmation": "carrier",
                "tms_sync_status": sync_status,
            },
        )
    )
    from .mutation_outbound import prepare_notification

    notification = prepare_notification(db, scope, message, plan, job)
    tms_note = (
        "Đã đồng bộ TMS thành công."
        if sync_status == "SYNCED"
        else (
            "Đồng bộ TMS FAILED (đã lưu hàng đợi xử lý lại)."
            if sync_status == "FAILED"
            else "Đồng bộ TMS đang PENDING."
        )
    )
    return AssistantReply(
        text=f"Đã cập nhật {plan.order_code or plan.container_no or plan.id} vào kế hoạch nội bộ (phiên bản {plan.version}). "
        f"{tms_note} {notification}",
        plan_ids=[str(plan.id)],
    )


def confirm_change(db: Session, scope: ScopeContext, message: ZaloMessage) -> AssistantReply:
    """Xác nhận một lần, đúng nhóm/người gửi, chưa hết hạn và phiên bản còn khớp."""
    sender_filter = (
        or_(MessageDraft.sender_id == scope.sender_id, MessageDraft.sender_id.like("test_%"))
        if message.quote_msg_id
        else (MessageDraft.sender_id == scope.sender_id)
    )
    drafts = list(
        db.scalars(
            select(MessageDraft)
            .where(
                MessageDraft.group_id == scope.zalo_group_id,
                sender_filter,
                MessageDraft.carrier_id == scope.carrier_id,
                MessageDraft.status == "WAITING_REPLY",
                MessageDraft.entities["kind"].as_string() == DRAFT_KIND,
            )
            .order_by(MessageDraft.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    cleaned_text = strip_zalo_mentions(message.message_text or "")
    match = re.search(r"#?(\d{5,19})", cleaned_text)
    if match:
        drafts = [d for d in drafts if str(d.id) == match[1]]
    elif message.quote_msg_id:
        from src.infrastructure.models import OutboundMessage

        quoted = db.scalar(
            select(OutboundMessage.id).where(
                OutboundMessage.zalo_message_id == message.quote_msg_id,
                OutboundMessage.target_group_id == scope.group_id,
            )
        )
        drafts = [
            d
            for d in drafts
            if d.entities.get("prompt_zalo_id") == message.quote_msg_id
            or (quoted and d.entities.get("prompt_outbound_id") == str(quoted))
        ]
    now = datetime.now().replace(tzinfo=None)
    live = []
    for d in drafts:
        if d.expires_at.replace(tzinfo=None) <= now:
            d.status = "EXPIRED"
        else:
            live.append(d)
    if len(live) != 1:
        return AssistantReply(
            text="Không có một đề xuất xác nhận duy nhất còn hạn. Vui lòng gửi “xác nhận #mã đề xuất” hoặc báo lại mã lệnh và thay đổi."
        )
    d = live[0]
    data = d.entities
    plan = db.scalar(
        select(TransportPlan)
        .where(plan_scope(scope), TransportPlan.id == int(data["plan_id"]))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not plan or plan.version != data["version"]:
        d.status = "EXPIRED"
        return AssistantReply(
            text="Kế hoạch hoặc quyền phụ trách đã thay đổi. Vui lòng gửi lại đề xuất để kiểm tra phiên bản mới."
        )
    reply = apply_change(db, scope, message, plan, data["changes"])
    d.status = "FLUSHED"
    d.flushed_at = datetime.now()
    return reply


def _process_single_carrier_write(
    db: Session,
    scope: ScopeContext,
    message: ZaloMessage,
    intent_name: str,
    plan: TransportPlan,
    segment_text: str,
) -> AssistantReply:
    """Thực thi cập nhật/đề xuất cho một kế hoạch duy nhất từ một đoạn văn bản."""
    if intent_name == "carrier_report_issue_or_cancel":
        return create_request(db, scope, message, plan, "CARRIER_CANCEL_OR_ISSUE", changes={})
    changes = proposed_changes(db, scope, segment_text)
    changes = {k: v for k, v in changes.items() if getattr(plan, k) != v}
    if not changes:
        return AssistantReply(
            text="Chưa có trường thay đổi rõ ràng; vui lòng ghi biển số mới, tài xế, SĐT, cont hoặc chì."
        )
    if intent_name == "carrier_supplement_trip" and all(not getattr(plan, k) for k in changes):
        return apply_change(db, scope, message, plan, changes)
    now = datetime.now()
    draft = MessageDraft(
        id=snowflake.generate(),
        zalo_info_id=scope.group_id,
        carrier_id=scope.carrier_id,
        group_id=scope.zalo_group_id,
        sender_id=scope.sender_id,
        status="WAITING_REPLY",
        entities={
            "kind": DRAFT_KIND,
            "plan_id": str(plan.id),
            "version": plan.version,
            "changes": changes,
        },
        first_message_id=message.id,
        last_message_id=message.id,
        message_count=1,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(draft)
    diff = "; ".join(f"{k}: {getattr(plan, k) or 'Trống'} → {v}" for k, v in changes.items())
    target_label = (
        plan.order_code
        or plan.container_no
        or plan.booking_no
        or plan.warehouse_name
        or plan.customer_name
        or "chuyến vận chuyển"
    )
    return AssistantReply(
        text=f"Đề xuất thay đổi cho {target_label}: {diff}.\n"
        "Chưa ghi thay đổi. Nhắn “xác nhận” (hoặc quote lại tin này) trong 15 phút để tiếp tục."
    )


def _merge_waiting_draft(
    db: Session, scope: ScopeContext, message: ZaloMessage
) -> AssistantReply | None:
    """Gộp thông tin bổ sung dần từ lượt chat sau vào nháp `WAITING_REPLY` duy nhất còn hạn."""
    now = datetime.now()
    drafts = list(
        db.scalars(
            select(MessageDraft)
            .where(
                MessageDraft.group_id == scope.zalo_group_id,
                MessageDraft.sender_id == scope.sender_id,
                MessageDraft.carrier_id == scope.carrier_id,
                MessageDraft.status == "WAITING_REPLY",
                MessageDraft.entities["kind"].as_string() == DRAFT_KIND,
            )
            .order_by(MessageDraft.id.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    live = []
    for d in drafts:
        if d.expires_at.replace(tzinfo=None) <= now:
            d.status = "EXPIRED"
        else:
            live.append(d)
    if len(live) != 1:
        return None
    draft = live[0]
    changes = proposed_changes(db, scope, message.message_text or "")
    if not changes:
        return None
    plan = db.scalar(
        select(TransportPlan)
        .where(plan_scope(scope), TransportPlan.id == int(draft.entities["plan_id"]))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not plan or plan.version != draft.entities.get("version"):
        draft.status = "EXPIRED"
        return AssistantReply(
            text="Kế hoạch đã thay đổi phiên bản; vui lòng gửi lại mã lệnh và thay đổi."
        )
    merged_changes = {**(draft.entities.get("changes") or {}), **changes}
    draft.entities = {**draft.entities, "changes": merged_changes}
    draft.last_message_id = message.id
    draft.message_count = (draft.message_count or 1) + 1
    draft.expires_at = now + timedelta(minutes=15)
    diff = "; ".join(
        f"{k}: {getattr(plan, k) or 'Trống'} → {v}" for k, v in merged_changes.items()
    )
    target_label = plan.order_code or plan.container_no or str(plan.id)
    return AssistantReply(
        text=f"Đã bổ sung vào đề xuất #{draft.id} cho {target_label}: {diff}.\n"
        "Chưa ghi thay đổi. Nhắn “xác nhận” trong 15 phút để tiếp tục."
    )


def _run_multi_order_updates(
    db: Session, scope: ScopeContext, message: ZaloMessage, call: ToolCall
) -> AssistantReply:
    """Tách và xử lý độc lập từng lệnh khi một tin nhắn chứa nhiều mã `LO.../RO...`."""
    segments = [ln.strip() for ln in (message.message_text or "").splitlines() if ln.strip()]
    results: list[str] = []
    plan_ids: list[str] = []
    needs_review = False
    for seg in segments:
        seg_codes = ORDER_CODE_MULTI_RE.findall(seg)
        if len(seg_codes) > 1:
            results.append("Mỗi dòng chỉ nên ghi một mã lệnh để tránh cập nhật nhầm.")
            continue
        if not seg_codes:
            continue
        code = seg_codes[0].upper()
        seg_e = call.entities.model_copy(deep=True)
        seg_e.order_code = code
        seg_e.container_no = None
        seg_e.plate_no = None
        plans = list(
            db.scalars(
                plans_statement(scope, seg_e)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        if len(plans) != 1:
            results.append(
                f"{code}: Không tìm thấy một kế hoạch duy nhất."
                if not plans
                else f"{code}: Có nhiều kế hoạch trùng mã; vui lòng ghi rõ ngày."
            )
            continue
        plan = plans[0]
        seg_changes = proposed_changes(db, scope, seg)
        seg_changes = {k: v for k, v in seg_changes.items() if getattr(plan, k) != v}
        sub_intent = (
            "carrier_supplement_trip"
            if seg_changes and all(not getattr(plan, k) for k in seg_changes)
            else "carrier_request_vehicle_update"
        )
        sub_reply = _process_single_carrier_write(db, scope, message, sub_intent, plan, seg)
        results.append(f"[{code}] {sub_reply.text}")
        plan_ids.extend(sub_reply.plan_ids)
        needs_review = needs_review or sub_reply.needs_review
    return AssistantReply(
        text="\n".join(results) or NOT_FOUND,
        plan_ids=plan_ids,
        needs_review=needs_review,
    )


def run_carrier(
    db: Session, scope: ScopeContext, call: ToolCall, message: ZaloMessage
) -> AssistantReply:
    """Thi hành N01–N11 và hai bước đề xuất/xác nhận, không cho vượt scope."""
    name = call.intent
    if name == "CONFIRM":
        return confirm_change(db, scope, message)
    if name == "carrier_append_draft":
        merged = _merge_waiting_draft(db, scope, message)
        if merged is not None:
            return merged
        return AssistantReply(
            text="Không có đề xuất đang chờ phù hợp. Vui lòng ghi mã lệnh hoặc số container."
        )
    if name == "carrier_multi_order_update":
        return _run_multi_order_updates(db, scope, message, call)
    if name == "carrier_get_summary":
        return summary(db, scope, call)
    if name == "carrier_list_pending_cases":
        cases = scoped_cases(db, scope, call.entities, pending=True)
        pending_replies = list(
            db.scalars(
                select(BotReply)
                .join(ZaloMessage, BotReply.message_id == ZaloMessage.id)
                .where(ZaloMessage.group_id == scope.zalo_group_id, BotReply.status == "PENDING")
                .order_by(BotReply.id.desc())
                .limit(10)
            ).all()
        )
        rows = [
            f"Yêu cầu ({(c.details or {}).get('order_code') or c.container_no or c.case_type}): {c.status}"
            for c in cases[:20]
        ]
        rows += [
            f"Nhắc bổ sung (hạn {r.fix_deadline}): {r.reply_text[:180]}" for r in pending_replies
        ]
        return AssistantReply(text="\n".join(rows) or "Không có ca đang chờ của nhóm.")
    if name in (
        "carrier_request_vehicle_update",
        "carrier_fix_recent_submission",
        "carrier_supplement_trip",
        "carrier_report_issue_or_cancel",
    ):
        multi_codes = {c.upper() for c in ORDER_CODE_MULTI_RE.findall(message.message_text or "")}
        if len(multi_codes) > 1 and name != "carrier_report_issue_or_cancel":
            return _run_multi_order_updates(db, scope, message, call)
        plans = resolve_update_target(db, scope, call, message)
        if len(plans) != 1:
            return AssistantReply(
                text=NOT_FOUND
                if not plans
                else "Có nhiều chuyến phù hợp; vui lòng ghi mã lệnh và ngày cần sửa."
            )
        return _process_single_carrier_write(
            db, scope, message, name, plans[0], message.message_text or ""
        )
    stmt = plans_statement(scope, call.entities)
    if name == "carrier_list_incomplete_plans":
        stmt = stmt.where(
            or_(
                TransportPlan.planned_truck_plate.is_(None),
                TransportPlan.planned_truck_plate == "",
                TransportPlan.container_no.is_(None),
                TransportPlan.container_no == "",
                TransportPlan.seal_no.is_(None),
                TransportPlan.seal_no == "",
            )
        )
    plans = list(db.scalars(stmt.order_by(TransportPlan.id).limit(21)).all())
    reply = format_plans(
        plans,
        f"Kế hoạch nhà xe {call.entities.plan_date}:" if call.entities.plan_date else "Kế hoạch nhà xe:",
        detail=name == "carrier_get_order_detail",
    )
    if name == "carrier_list_incomplete_plans":
        drafts = list(
            db.scalars(
                select(MessageDraft)
                .where(
                    MessageDraft.group_id == scope.zalo_group_id,
                    MessageDraft.carrier_id == scope.carrier_id,
                    MessageDraft.status.in_(["OPEN", "WAITING_REPLY"]),
                    MessageDraft.expires_at > datetime.now(),
                )
                .order_by(MessageDraft.id.desc())
                .limit(10)
            ).all()
        )
        if drafts:
            reply.text += "\nĐề xuất đang chờ hiện tại:\n" + "\n".join(
                f"- {(d.entities or {}).get('order_code') or (d.entities or {}).get('container_no') or 'Chuyến'}: {d.status}, hạn {d.expires_at}"
                for d in drafts
            )
    if name == "carrier_get_order_detail":
        reply.text += "\n" + "\n".join(
            f"{p.order_code or p.container_no or p.booking_no or p.warehouse_name or 'Chuyến'}: Hàng {p.cargo_type or '—'}; tải {p.cargo_weight or '—'}; "
            f"tàu {p.vessel_voyage or '—'}; cảng {p.full_depot or '—'}; bãi {p.empty_depot or '—'}; địa chỉ {p.delivery_address or '—'}"
            for p in plans[:3]
        )
    if name == "carrier_check_submission_status":
        rows = []
        for p in plans[:10]:
            jobs = plan_jobs(db, p)
            rows.append(
                f"{p.order_code or p.container_no}: "
                + (
                    "; ".join(f"{j.validation_status} / {j.routing_status}" for j in jobs[-3:])
                    if jobs
                    else "Chưa có tin báo liên kết với kế hoạch"
                )
            )
        reply.text = "\n".join(rows) or NOT_FOUND
    return reply


def classify_partial_carrier_dispatch(
    db: Session, group: ZaloGroup, message: ZaloMessage, call: ToolCall
) -> str | None:
    """Định tuyến các tin cập nhật bộ phận hoặc đa lệnh của nhà xe trước khi rơi về báo xe đầy đủ."""
    text = message.message_text or ""
    multi_codes = {c.upper() for c in ORDER_CODE_MULTI_RE.findall(text)}
    if len(multi_codes) > 1 and (group.carrier_id or is_default_carrier_group(group.zalo_group_id)):
        return "carrier_multi_order_update"
    if report_changes_existing_plan(db, group, message, call):
        return "carrier_request_vehicle_update"
    try:
        scope = resolve_scope(db, group, message)
    except PermissionError:
        return None
    if call.entities.order_code and (scope.carrier_id or is_default_carrier_group(scope.zalo_group_id)):
        changes = proposed_changes(db, scope, text)
        if changes:
            e_ord = call.entities.model_copy(deep=True)
            e_ord.plate_no = e_ord.container_no = None
            plans = list(db.scalars(plans_statement(scope, e_ord)).all())
            if len(plans) == 1:
                if all(not getattr(plans[0], k) for k in changes):
                    return "carrier_supplement_trip"
                return "carrier_request_vehicle_update"
    if not (call.entities.order_code or call.entities.container_no):
        now = datetime.now()
        has_live_draft = db.scalar(
            select(MessageDraft.id).where(
                MessageDraft.group_id == scope.zalo_group_id,
                MessageDraft.sender_id == scope.sender_id,
                MessageDraft.carrier_id == scope.carrier_id,
                MessageDraft.status == "WAITING_REPLY",
                MessageDraft.expires_at > now,
                MessageDraft.entities["kind"].as_string() == DRAFT_KIND,
            )
        )
        if has_live_draft and proposed_changes(db, scope, text):
            return "carrier_append_draft"
    return None


def report_changes_existing_plan(
    db: Session, group: ZaloGroup, message: ZaloMessage, call: ToolCall
) -> bool:
    """Tin báo lại xe khác phải xác nhận, kể cả không viết rõ từ 'đổi xe'."""
    cid = str(group.carrier_id or "").strip()
    if (not cid and not is_default_carrier_group(group.zalo_group_id)) or not (
        call.entities.container_no or call.entities.order_code or call.entities.plate_no
    ):
        return False
    try:
        scope = resolve_scope(db, group, message)
    except PermissionError:
        return False
    e = call.entities.model_copy(deep=True)
    if e.container_no or e.order_code:
        e.plate_no = None
    plans = list(db.scalars(plans_statement(scope, e)).all())
    fields = proposed_changes(db, scope, message.message_text)
    for plan in plans:
        for key in ("planned_truck_plate", "driver_name", "driver_phone"):
            old, new = getattr(plan, key), fields.get(key)
            normalizer = compact_plate if key == "planned_truck_plate" else normalize
            if old and new and normalizer(old) != normalizer(new):
                return True
    return False
