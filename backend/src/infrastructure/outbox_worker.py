"""Phát hành thông báo đã lưu DB, sau khi đồng bộ kế hoạch nội bộ (FILL / UPDATE)."""

from datetime import UTC, datetime

from sqlalchemy import select

from src.config.settings import settings
from src.handlers.dhvt_service import DhvtNotificationService
from src.handlers.plan_sync_service import resolve_plan_detailed, sync_job_to_local_plan
from src.infrastructure.database import SessionLocal
from src.infrastructure.models import ActivityLog, ContainerJob, OutboundMessage, ZaloGroup
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher


def drain_outbox(session_factory=SessionLocal, only_ids: list[int] | None = None) -> None:
    """Khóa từng thông báo, cập nhật kế hoạch trước khi gửi; không tự gửi lại khi chưa rõ kết quả."""
    if only_ids is not None and not only_ids:
        return

    with session_factory() as db:
        stmt = (
            select(OutboundMessage.id)
            .where(OutboundMessage.status == "PENDING_SEND")
            .order_by(OutboundMessage.id)
        )
        if only_ids is not None:
            stmt = stmt.where(OutboundMessage.id.in_(only_ids))
        ids = list(db.scalars(stmt.limit(100)).all())

    for oid in ids:
        with session_factory() as db:
            out = db.scalar(
                select(OutboundMessage)
                .where(OutboundMessage.id == oid, OutboundMessage.status == "PENDING_SEND")
                .with_for_update(skip_locked=True)
            )
            if out is None:
                continue

            target = out.target_group
            if not target or not target.is_active or (
                target.group_role.upper() not in ("CUSTOMER", "DESTINATION")
                and out.message_kind != "answer"
            ):
                out.status = "PENDING_APPROVAL"
                out.last_error = "Nhóm đích không hợp lệ hoặc đã khóa."
                db.commit()
                continue

            manual_approved = bool(out.approved_by and out.approved_by != "auto_system")
            valid = bool(out.items) or out.message_kind in ("answer", "cancel")
            failed_job = None
            fail_case_type = "PLAN_SYNC_REQUIRED"
            fail_reason = "Cần xác định duy nhất kế hoạch thuộc nhà xe trên Web."

            if out.message_kind not in ("answer", "cancel"):
                for item in out.items:
                    job = item.container_job
                    source = (
                        db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == job.message.group_id))
                        if job
                        else None
                    )
                    is_superseded = bool(
                        job and db.scalar(select(ContainerJob.id).where(ContainerJob.parent_job_id == job.id).limit(1))
                    )
                    if not job or job.validation_status != "VALID":
                        valid = False
                        failed_job = job
                        fail_reason = "Dữ liệu điều xe chưa hợp lệ hoặc chưa đủ trường cốt lõi."
                        break
                    if is_superseded and not manual_approved:
                        valid = False
                        failed_job = job
                        fail_reason = "Bản ghi điều xe đã có phiên bản cập nhật mới hơn."
                        break

                    plan_res = (
                        resolve_plan_detailed(db, job, source, for_update=True)
                        if (source and source.is_active and source.group_role.upper() in ("SOURCE", "CARRIER"))
                        else None
                    )
                    if plan_res is None or plan_res.plan is None:
                        if not manual_approved:
                            valid = False
                            failed_job = job
                            fail_reason = (
                                plan_res.reason
                                if plan_res
                                else "Chưa cập nhật kế hoạch: cần xác định đúng nhà xe và kế hoạch trên Web."
                            )
                            break
                    else:
                        sync_outcome = sync_job_to_local_plan(
                            db,
                            job,
                            plan_res.plan,
                            allow_plan_override=manual_approved,
                            actor_id=out.approved_by or "vsico_bot",
                        )
                        if sync_outcome.mode == "CONFLICT" and not manual_approved:
                            valid = False
                            failed_job = job
                            fail_case_type = "PLAN_FIELD_CONFLICT"
                            fail_reason = "; ".join(sync_outcome.conflict_reasons) or "Xung đột dữ liệu với kế hoạch."
                            break

            if not valid:
                out.status = "PENDING_APPROVAL"
                out.last_error = fail_reason
                if failed_job:
                    DhvtNotificationService.create_or_merge_review_case(
                        db=db,
                        message_id=failed_job.message_id,
                        case_type=fail_case_type,
                        reason=fail_reason,
                        container_job_id=failed_job.id,
                        container_no=failed_job.container_no,
                        details={"outbound_message_id": out.id},
                        is_test_msg=bool(target.is_test),
                        notify_zalo=True,
                    )
                DhvtNotificationService.notify_pending_outbound(
                    db=db,
                    outbound=out,
                    target_group_name=target.name,
                    containers=[
                        it.container_job.container_no
                        for it in out.items
                        if it.container_job and it.container_job.container_no
                    ],
                    reason=fail_reason,
                    is_test_msg=bool(target.is_test),
                )
                db.commit()
                continue

            if not settings.AUTO_DISPATCH_OUTBOUND or target.is_test:
                db.commit()
                continue

            # Trạng thái SENDING bền vững ngăn tự gửi lại nếu tiến trình chết sau khi Zalo nhận.
            out.status = "SENDING"
            out.attempt_count += 1
            group_id, content = target.zalo_group_id, out.content
            db.commit()

            try:
                if group_id.startswith("direct_"):
                    ok, message_id, error = ZaloDispatcher.send_to_user(user_id=group_id[7:], message=content)
                else:
                    ok, message_id, error = ZaloDispatcher.send_to_group(group_id=group_id, message=content)
            except Exception:
                ok, message_id, error = False, None, "Không xác định kết quả gửi; kiểm tra Zalo trước khi gửi lại."

            if not ok:
                for item in out.items:
                    if item.container_job:
                        DhvtNotificationService.create_or_merge_review_case(
                            db=db,
                            message_id=item.container_job.message_id,
                            case_type="OUTBOUND_SEND_FAILED",
                            reason=error or "Gửi Zalo thất bại.",
                            container_job_id=item.container_job_id,
                            container_no=item.container_job.container_no,
                            details={"outbound_message_id": out.id},
                            is_test_msg=bool(target.is_test),
                            notify_zalo=True,
                        )
                        item.container_job.message.processing_status = "NEEDS_REVIEW"
                DhvtNotificationService.notify_system_alert(
                    db=db,
                    title="LOI GUI THONG BAO ZALO KHACH HANG",
                    body=(
                        f"Nhóm đích: {target.name} ({group_id})\n"
                        f"Outbound ID: {out.id}\n"
                        f"Lỗi: {error or 'Không xác định'}"
                    ),
                    entity_type="outbound_message",
                    entity_id=str(out.id),
                    web_path="/results",
                    is_test_msg=bool(target.is_test),
                    details={"outbound_message_id": out.id, "group_id": group_id},
                )
            else:
                db.add(
                    ActivityLog(
                        id=snowflake.generate(),
                        actor_id="vsico_bot",
                        action="OUTBOUND_DISPATCHED",
                        entity_type="outbound_message",
                        entity_id=str(out.id),
                        details={"group_id": group_id, "zalo_message_id": message_id},
                    )
                )

            out.status = "SENT" if ok else "FAILED"
            out.zalo_message_id = message_id if ok else None
            out.sent_at = datetime.now(UTC) if ok else None
            out.last_error = None if ok else error
            for item in out.items:
                if item.container_job:
                    item.container_job.routing_status = "SENT" if ok else "NEEDS_REVIEW"
            db.commit()
