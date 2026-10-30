"""Module Các REST API Rà Soát & Phê Duyệt Lỗi Dữ Liệu (Review & Approvals APIs).

Quản lý danh sách các trường hợp dữ liệu xe/container có cảnh báo nghiệp vụ
cần sự kiểm tra và phê duyệt từ nhân viên điều độ (Human-in-the-Loop):
1. Danh sách các ca chờ duyệt: `GET /api/reviews`
2. Phê duyệt ca: `POST /api/reviews/{review_id}/approve`
3. Từ chối ca: `POST /api/reviews/{review_id}/reject`
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.infrastructure.database import get_db
from src.infrastructure.models import (
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    ZaloMessage,
)
from src.infrastructure.zalo_dispatcher import ZaloDispatcher

router = APIRouter(prefix="/api/reviews", tags=["5. Rà Soát & Phê Duyệt (Reviews & Approvals)"])


class RejectPayload(BaseModel):
    """Schema lý do từ chối phê duyệt."""

    reason: Optional[str] = Field(default="Dữ liệu không chính xác theo kiểm tra thủ công.", description="Lý do từ chối")


@router.get("")
def list_review_cases(
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái: 'pending', 'approved', 'rejected'"),
    case_type: Optional[str] = Query(default=None, description="Lọc theo loại: 'invalid_check_digit', 'missing_fields'..."),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lấy danh sách các trường hợp cần rà soát kèm ngữ cảnh tin nhắn và container."""
    stmt = select(ReviewCase).options(selectinload(ReviewCase.message))

    if status:
        stmt = stmt.where(ReviewCase.status == status.strip().lower())
    if case_type:
        stmt = stmt.where(ReviewCase.case_type == case_type.strip().lower())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(ReviewCase.id.desc()).offset(offset).limit(limit)
    cases = list(db.scalars(stmt).all())

    results = []
    for c in cases:
        msg = c.message
        job = db.get(ContainerJob, c.container_job_id) if c.container_job_id else None
        results.append(
            {
                "id": c.id,
                "message_id": c.message_id,
                "container_job_id": c.container_job_id,
                "case_type": c.case_type,
                "reason": c.reason,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                "resolved_by": c.resolved_by,
                "message_context": {
                    "zalo_message_id": msg.zalo_message_id if msg else None,
                    "sender_name": msg.sender_name or (msg.sender_id if msg else None),
                    "group_id": msg.group_id if msg else None,
                    "raw_text": msg.message_text if msg else None,
                    "sent_at": (msg.zalo_sent_at or msg.received_at).isoformat() if msg else None,
                }
                if msg
                else None,
                "container_details": {
                    "container_no": job.container_no if job else None,
                    "container_size": job.container_size if job else None,
                    "seal_no": job.seal_no if job else None,
                    "order_type": job.order_type if job else None,
                    "customer_hint": job.customer_hint if job else None,
                    "warehouse_hint": job.warehouse_hint if job else None,
                    "validation_status": job.validation_status if job else None,
                    "warnings": (job.raw_fields or {}).get("warnings", []) if job else [],
                }
                if job
                else None,
            }
        )

    return {
        "ok": True,
        "status": "OK",
        "total": total,
        "total_returned": len(results),
        "reviews": results,
    }


@router.post("/{review_id}/approve")
def approve_review_case(
    review_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phê duyệt chấp nhận trường hợp dữ liệu sau khi nhân viên đã kiểm tra thủ công.

    - Đổi trạng thái `review_cases.status = 'approved'`.
    - Cập nhật `container_jobs.validation_status = 'valid'`.
    - Nếu toàn bộ các ca rà soát của tin nhắn đều đã được duyệt, chuyển `zalo_messages.processing_status = 'processed'`.
    """
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")

    case_obj.status = "approved"
    case_obj.resolved_at = datetime.now()
    case_obj.resolved_by = "admin_reviewer"

    # Cập nhật container_job và các OutboundMessage tương ứng
    jobs_to_update: list[ContainerJob] = []
    if case_obj.container_job_id:
        job = db.get(ContainerJob, case_obj.container_job_id)
        if job:
            jobs_to_update.append(job)
    elif case_obj.message_id:
        c_jobs = list(db.scalars(select(ContainerJob).where(ContainerJob.message_id == case_obj.message_id)).all())
        jobs_to_update.extend(c_jobs)

    for job in jobs_to_update:
        job.validation_status = "valid"
        job.routing_status = "routed"
        job.tms_sync_status = "synced"
        out_stmt = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id == job.id,
                OutboundMessage.status == "cho_duyet",
            )
        )
        for out_msg in db.scalars(out_stmt):
            target_grp = out_msg.target_group
            target_gid = target_grp.zalo_group_id if target_grp else None
            real_zalo_msg_id = None
            if target_gid and (
                (target_gid.isdigit() and target_gid != "2001000000000000001")
                or (not (target_grp and target_grp.is_test) and not target_gid.startswith("grp_test_") and not target_gid.startswith("test_") and not target_gid.startswith("pytest_"))
            ):
                send_ok, real_zalo_msg_id, send_err = ZaloDispatcher.send_to_group(
                    group_id=target_gid,
                    message=out_msg.content,
                )
                if not send_ok:
                    out_msg.status = "that_bai"
                    out_msg.last_error = f"Lỗi gửi Zalo: {send_err}"
                    continue

            out_msg.status = "da_gui"
            out_msg.approved_by = "admin_reviewer"
            out_msg.approved_at = datetime.now(timezone.utc)
            out_msg.sent_at = datetime.now(timezone.utc)
            out_msg.attempt_count += 1
            out_msg.last_error = None
            out_msg.zalo_message_id = real_zalo_msg_id or out_msg.zalo_message_id or f"zalo_oa_approved_{uuid4().hex[:12]}"

    # Kiểm tra xem tin nhắn còn ca rà soát nào đang 'pending' không
    pending_count = db.scalar(
        select(func.count(ReviewCase.id)).where(
            ReviewCase.message_id == case_obj.message_id,
            ReviewCase.status == "pending",
            ReviewCase.id != case_obj.id,
        )
    ) or 0

    if pending_count == 0 and case_obj.message_id:
        msg = db.get(ZaloMessage, case_obj.message_id)
        if msg:
            msg.processing_status = "processed"

    db.commit()
    return {
        "ok": True,
        "status": "APPROVED",
        "review_id": review_id,
        "message": f"Đã phê duyệt thành công ca rà soát ID={review_id}.",
    }


@router.post("/{review_id}/reject")
def reject_review_case(
    review_id: int,
    payload: RejectPayload = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Từ chối chấp nhận bản ghi dữ liệu do sai lệch không thể sửa chữa."""
    case_obj = db.get(ReviewCase, review_id)
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca rà soát ID={review_id}.")

    case_obj.status = "rejected"
    case_obj.resolved_at = datetime.now()
    case_obj.resolved_by = "admin_reviewer"
    case_obj.reason = f"{case_obj.reason or ''} [Từ chối: {payload.reason}]"

    db.commit()
    return {
        "ok": True,
        "status": "REJECTED",
        "review_id": review_id,
        "message": f"Đã từ chối ca rà soát ID={review_id}.",
    }
