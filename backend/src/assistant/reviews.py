"""Ca trợ lý giữ phạm vi tin gốc; thông báo ĐHVT được lưu bền vững trước khi gửi."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.handlers.dhvt_service import DhvtNotificationService
from src.infrastructure.models import (
    ActivityLog,
    OutboundMessage,
    ReviewCase,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake


def create_scoped_review(
    db: Session,
    message: ZaloMessage,
    case_type: str,
    reason: str,
    details: dict[str, Any],
    container_job_id: int | None = None,
    priority: str = "NORMAL",
) -> ReviewCase:
    """Không gộp ca bằng số cont xuyên nhóm/chặng; chỉ tạo thông báo qua outbox."""
    case, _ = DhvtNotificationService.create_or_merge_review_case(
        db=db,
        message_id=message.id,
        case_type=case_type,
        reason=reason,
        details=details,
        container_job_id=container_job_id,
        container_no=None,
        priority=priority,
        notify_zalo=False,
    )
    target = DhvtNotificationService.find_dhvt_group(db)
    text = DhvtNotificationService.render_review_case_alert(
        case, container_no=details.get("container_no"), priority=priority
    )
    source = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == message.group_id))
    if target and source and not (source.is_test and not target.is_test):
        out = OutboundMessage(
            id=snowflake.generate(),
            target_group_id=target.id,
            order_type="ANSWER",
            message_kind="answer",
            content=text,
            idempotency_key=f"assistant-review:{case.id}",
            status="PENDING_SEND",
            attempt_count=0,
        )
        db.add(out)
        case.details = {**case.details, "alert_outbound_id": str(out.id)}
    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=message.sender_id,
            action="ASSISTANT_REVIEW_CREATED",
            entity_type="review_case",
            entity_id=str(case.id),
            details={
                "source_group_id": message.group_id,
                "plan_id": details.get("transport_plan_id"),
            },
        )
    )
    return case
