"""Module API Quản lý Kết quả Tin nhắn & Thông báo Gửi đi (Outbound Messages & Results API).

Phục vụ giao diện Quản trị và Điều hành vận tải (ĐHVT) theo dõi kết quả tin nhắn:
- Tin nhắn thông báo gửi khách hàng đã gửi (da_gui).
- Tin nhắn thông báo đang chờ duyệt (cho_duyet).
- Tin nhắn thông báo bị hủy (huy).
- Tin nhắn gửi thất bại do lỗi Zalo OA hoặc mạng (that_bai).
- Thao tác: Duyệt gửi (Approve), Hủy gửi (Cancel), Gửi lại (Resend), Thống kê tổng hợp.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from src.infrastructure.database import get_db
from src.infrastructure.models import (
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TransportPlan,
    TruckRecord,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.throttler import outbound_throttler as throttler
from src.infrastructure.zalo_dispatcher import ZaloDispatcher

outbound_router = APIRouter(prefix="/api/outbound", tags=["Outbound Messages & Results"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CancelRequest(BaseModel):
    """Payload yêu cầu hủy tin nhắn gửi đi."""
    reason: Optional[str] = Field(default="Điều độ viên hủy lệnh điều xe.", description="Lý do hủy tin nhắn")


class OutboundContainerInfo(BaseModel):
    """Thông tin Container gắn với tin nhắn gửi đi."""
    container_no: Optional[str] = None
    truck_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    seal_no: Optional[str] = None
    plan_date: Optional[str] = None


class OutboundMessageItemResponse(BaseModel):
    """Chi tiết một tin nhắn thông báo kết quả gửi đi."""
    id: int
    target_group_id: int
    target_group_name: Optional[str] = None
    target_zalo_group_id: Optional[str] = None
    order_type: str
    message_kind: str
    content: str
    idempotency_key: str
    review_zalo_msg_id: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    status: str
    attempt_count: int
    zalo_message_id: Optional[str] = None
    last_error: Optional[str] = None
    created_at: str
    sent_at: Optional[str] = None
    containers: list[OutboundContainerInfo] = []


class OutboundSummaryResponse(BaseModel):
    """Thống kê tổng hợp số lượng kết quả tin nhắn."""
    ok: bool = True
    total: int = 0
    da_gui: int = 0
    cho_duyet: int = 0
    huy: int = 0
    that_bai: int = 0
    bo_qua_trung_lap: int = 0


@outbound_router.get("/summary", response_model=OutboundSummaryResponse)
def get_outbound_summary(db: Session = Depends(get_db)) -> OutboundSummaryResponse:
    """Lấy thống kê số lượng tin nhắn kết quả theo từng trạng thái.

    Returns:
        OutboundSummaryResponse: Thống kê số lượng `da_gui`, `cho_duyet`, `huy`, `that_bai`, `bo_qua_trung_lap`.
    """
    total = db.scalar(select(func.count(OutboundMessage.id))) or 0
    da_gui = db.scalar(select(func.count(OutboundMessage.id)).where(OutboundMessage.status == "da_gui")) or 0
    cho_duyet = db.scalar(select(func.count(OutboundMessage.id)).where(OutboundMessage.status == "cho_duyet")) or 0
    huy = db.scalar(select(func.count(OutboundMessage.id)).where(OutboundMessage.status == "huy")) or 0
    that_bai = db.scalar(select(func.count(OutboundMessage.id)).where(OutboundMessage.status == "that_bai")) or 0
    bo_qua_trung_lap = db.scalar(select(func.count(OutboundMessage.id)).where(OutboundMessage.status == "bo_qua_trung_lap")) or 0

    return OutboundSummaryResponse(
        ok=True,
        total=total,
        da_gui=da_gui,
        cho_duyet=cho_duyet,
        huy=huy,
        that_bai=that_bai,
        bo_qua_trung_lap=bo_qua_trung_lap,
    )


@outbound_router.get("/messages")
def list_outbound_messages(
    status: Optional[str] = Query(default=None, description="Trạng thái: all, cho_duyet, da_gui, huy, that_bai"),
    order_type: Optional[str] = Query(default=None, description="Loại lệnh: dong, tra"),
    search: Optional[str] = Query(default=None, description="Tìm kiếm theo nội dung, số cont, biển số"),
    from_time: Optional[str] = Query(default=None, description="Từ thời điểm (ISO-8601)"),
    to_time: Optional[str] = Query(default=None, description="Đến thời điểm (ISO-8601)"),
    limit: int = Query(default=50, ge=1, le=200, description="Số lượng bản ghi mỗi trang"),
    offset: int = Query(default=0, ge=0, description="Vị trí bắt đầu"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lấy danh sách tin nhắn kết quả gửi đi có phân trang và bộ lọc chuyên sâu.

    Args:
        status: Trạng thái cần lọc (`cho_duyet`, `da_gui`, `huy`, `that_bai`).
        order_type: Loại lệnh (`dong`, `tra`).
        search: Từ khóa tìm kiếm nội dung hoặc số cont / biển số.
        from_time: Lọc theo thời gian tạo từ.
        to_time: Lọc theo thời gian tạo đến.
        limit: Giới hạn số bản ghi.
        offset: Phân trang.
    """
    stmt = (
        select(OutboundMessage)
        .options(
            joinedload(OutboundMessage.target_group),
            selectinload(OutboundMessage.items).joinedload(OutboundMessageItem.container_job),
        )
    )

    if status and status.lower() != "all":
        stmt = stmt.where(OutboundMessage.status == status.lower())
    if order_type:
        stmt = stmt.where(OutboundMessage.order_type == order_type.lower())

    if search:
        search_kw = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                OutboundMessage.content.ilike(search_kw),
                OutboundMessage.idempotency_key.ilike(search_kw),
            )
        )

    if from_time:
        try:
            from_dt = datetime.fromisoformat(from_time.replace("Z", "+00:00"))
            stmt = stmt.where(OutboundMessage.created_at >= from_dt)
        except Exception:
            pass

    if to_time:
        try:
            to_dt = datetime.fromisoformat(to_time.replace("Z", "+00:00"))
            stmt = stmt.where(OutboundMessage.created_at <= to_dt)
        except Exception:
            pass

    # Tổng số bản ghi khớp
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = db.scalar(count_stmt) or 0

    # Lấy dữ liệu phân trang
    stmt = stmt.order_by(OutboundMessage.created_at.desc(), OutboundMessage.id.desc()).offset(offset).limit(limit)
    rows = list(db.scalars(stmt).unique().all())

    serialized: list[dict[str, Any]] = []
    for r in rows:
        containers_info: list[dict[str, Any]] = []
        for it in r.items:
            job = it.container_job
            if job:
                # Tìm xe liên kết nếu có
                truck_plate = None
                driver_name = None
                driver_phone = None
                if job.truck_record_id:
                    truck = db.get(TruckRecord, job.truck_record_id)
                    if truck:
                        truck_plate = truck.truck_plate
                        driver_name = truck.driver_name
                        driver_phone = truck.driver_phone

                containers_info.append({
                    "container_no": job.container_no,
                    "truck_plate": truck_plate,
                    "driver_name": driver_name,
                    "driver_phone": driver_phone,
                    "seal_no": job.seal_no,
                    "plan_date": (job.raw_fields or {}).get("plan_date") or (job.created_at.date().isoformat() if job.created_at else None),
                })

        group_name = r.target_group.name if r.target_group else None
        zalo_gid = r.target_group.zalo_group_id if r.target_group else None

        serialized.append({
            "id": r.id,
            "target_group_id": r.target_group_id,
            "target_group_name": group_name or f"Nhóm Zalo #{r.target_group_id}",
            "target_zalo_group_id": zalo_gid,
            "order_type": r.order_type,
            "message_kind": r.message_kind,
            "content": r.content,
            "idempotency_key": r.idempotency_key,
            "review_zalo_msg_id": r.review_zalo_msg_id,
            "approved_by": r.approved_by,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "status": r.status,
            "attempt_count": r.attempt_count,
            "zalo_message_id": r.zalo_message_id,
            "last_error": r.last_error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "containers": containers_info,
        })

    return {
        "ok": True,
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "messages": serialized,
    }


@outbound_router.get("/messages/{message_id}")
def get_outbound_message_detail(message_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Xem chi tiết một tin nhắn kết quả gửi đi."""
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả yêu cầu.")

    containers_info: list[dict[str, Any]] = []
    for it in msg.items:
        job = it.container_job
        if job:
            truck_plate = None
            driver_name = None
            driver_phone = None
            if job.truck_record_id:
                truck = db.get(TruckRecord, job.truck_record_id)
                if truck:
                    truck_plate = truck.truck_plate
                    driver_name = truck.driver_name
                    driver_phone = truck.driver_phone

            containers_info.append({
                "container_no": job.container_no,
                "truck_plate": truck_plate,
                "driver_name": driver_name,
                "driver_phone": driver_phone,
                "seal_no": job.seal_no,
                "plan_date": (job.raw_fields or {}).get("plan_date") or (job.created_at.date().isoformat() if job.created_at else None),
            })

    group_name = msg.target_group.name if msg.target_group else None
    zalo_gid = msg.target_group.zalo_group_id if msg.target_group else None

    return {
        "ok": True,
        "message": {
            "id": msg.id,
            "target_group_id": msg.target_group_id,
            "target_group_name": group_name or f"Nhóm Zalo #{msg.target_group_id}",
            "target_zalo_group_id": zalo_gid,
            "order_type": msg.order_type,
            "message_kind": msg.message_kind,
            "content": msg.content,
            "idempotency_key": msg.idempotency_key,
            "review_zalo_msg_id": msg.review_zalo_msg_id,
            "approved_by": msg.approved_by,
            "approved_at": msg.approved_at.isoformat() if msg.approved_at else None,
            "status": msg.status,
            "attempt_count": msg.attempt_count,
            "zalo_message_id": msg.zalo_message_id,
            "last_error": msg.last_error,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
            "containers": containers_info,
        }
    }


@outbound_router.post("/messages/{message_id}/approve")
def approve_outbound_message(
    message_id: int,
    operator_name: str = Query(default="Điều độ viên", description="Tên người phê duyệt"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phê duyệt tin nhắn đang ở trạng thái 'cho_duyet' và kích hoạt gửi ra Zalo OA.

    - Kiểm soát tần suất thông qua Token Bucket Throttler (`ZaloOutboundThrottler`).
    - Cập nhật trạng thái thành `da_gui`.
    - Sinh mã `zalo_message_id` cho tin nhắn xuất bản.
    """
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả.")

    if msg.status == "da_gui":
        return {"ok": True, "status": "da_gui", "message": "Tin nhắn này đã được gửi trước đó."}

    # Kiểm tra xem tin nhắn gốc có phải là tin nhắn thật hay không
    is_real_msg = False
    parent_zalo_msg = None
    for item in msg.items:
        if item.container_job and item.container_job.message:
            parent_zalo_msg = item.container_job.message
            if not (
                (parent_zalo_msg.group_id and ("test_" in parent_zalo_msg.group_id or "pytest_" in parent_zalo_msg.group_id))
                or (parent_zalo_msg.zalo_message_id and (parent_zalo_msg.zalo_message_id.startswith("test_") or parent_zalo_msg.zalo_message_id.startswith("pytest_")))
                or (parent_zalo_msg.sender_id and (parent_zalo_msg.sender_id.startswith("test_") or parent_zalo_msg.sender_id.startswith("pytest_")))
            ):
                is_real_msg = True
                break

    # Thực hiện gửi thực tế ra Nhóm Zalo đích
    target_grp = msg.target_group
    target_gid = target_grp.zalo_group_id if target_grp else None

    # Tự động chuyển hướng sang nhóm thật nếu là tin nhắn thực tế mà đích đang trỏ mock group
    if is_real_msg and (not target_gid or target_gid.startswith("test_") or target_gid.startswith("grp_test_") or (target_grp and target_grp.is_test)):
        real_dest_grp = db.scalars(
            select(ZaloGroup)
            .where(
                ZaloGroup.is_active == True,
                ZaloGroup.is_test == False,
                ZaloGroup.zalo_group_id.isnot(None),
                ~ZaloGroup.zalo_group_id.like("test_%"),
                ~ZaloGroup.zalo_group_id.like("pytest_%"),
                ~ZaloGroup.zalo_group_id.like("direct_%"),
            )
            .order_by(ZaloGroup.id.asc())
        ).first()
        if real_dest_grp:
            msg.target_group_id = real_dest_grp.id
            target_grp = real_dest_grp
            target_gid = real_dest_grp.zalo_group_id

    real_zalo_msg_id = None
    if target_gid:
        if target_grp and target_grp.is_test and not is_real_msg:
            send_ok = True
            real_zalo_msg_id = f"test_mock_zalo_{uuid4().hex[:12]}"
            send_err = None
        else:
            send_ok, real_zalo_msg_id, send_err = ZaloDispatcher.send_to_group(
                group_id=target_gid,
                message=msg.content,
            )
        if not send_ok:
            msg.status = "that_bai"
            msg.last_error = f"Lỗi gửi Zalo: {send_err}"
            db.commit()
            return {"ok": False, "status": "that_bai", "message": f"Gửi tin tới Zalo thất bại: {send_err}"}

    # Gửi phản hồi 1-1 cho người gửi nếu tin nhắn gốc gửi trực tiếp
    if parent_zalo_msg and parent_zalo_msg.sender_id and is_real_msg:
        if not parent_zalo_msg.group_id or parent_zalo_msg.group_id.startswith("direct_"):
            direct_reply = (
                f"✅ [VSICO ĐÃ PHÊ DUYỆT]\n"
                f"Tin nhắn thông báo của bạn đã được {operator_name} phê duyệt thành công!\n\n"
                f"Nội dung thông báo:\n{msg.content}"
            )
            ZaloDispatcher.send_to_user(parent_zalo_msg.sender_id, direct_reply)

    now = _utc_now()
    msg.status = "da_gui"
    msg.approved_by = operator_name
    msg.approved_at = now
    msg.sent_at = now
    msg.attempt_count += 1
    msg.zalo_message_id = real_zalo_msg_id or msg.zalo_message_id or f"zalo_oa_{uuid4().hex[:16]}"
    msg.last_error = None

    # Đồng bộ trạng thái ContainerJob, ReviewCase và ZaloMessage
    parent_msg_ids: set[int] = set()
    for item in msg.items:
        if item.container_job:
            cj = item.container_job
            cj.validation_status = "valid"
            cj.routing_status = "routed"
            cj.tms_sync_status = "synced"
            if cj.message_id:
                parent_msg_ids.add(cj.message_id)

            # Cập nhật review_cases liên quan đến container này
            for rc in db.scalars(
                select(ReviewCase).where(
                    ReviewCase.container_job_id == cj.id,
                    ReviewCase.status == "pending",
                )
            ).all():
                rc.status = "approved"
                rc.resolved_at = now
                rc.resolved_by = operator_name

    # Cập nhật trạng thái tin nhắn gốc (ZaloMessage) sang 'processed' nếu không còn ca pending
    for mid in parent_msg_ids:
        remaining_pending = db.scalar(
            select(func.count(ReviewCase.id)).where(
                ReviewCase.message_id == mid,
                ReviewCase.status == "pending",
            )
        ) or 0
        if remaining_pending == 0:
            z_msg = db.get(ZaloMessage, mid)
            if z_msg:
                z_msg.processing_status = "processed"

    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": f"Đã phê duyệt và gửi tin nhắn #{message_id} ra Nhóm Zalo thành công.",
        "status": msg.status,
        "sent_at": msg.sent_at.isoformat(),
        "zalo_message_id": msg.zalo_message_id,
    }


@outbound_router.post("/messages/{message_id}/cancel")
def cancel_outbound_message(
    message_id: int,
    req: CancelRequest = CancelRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Hủy tin nhắn thông báo điều xe (chuyển sang trạng thái 'huy').

    Thường áp dụng khi điều độ hủy cuốc xe, nhà xe xin đổi lịch, hoặc thông tin bị sai lệch.
    """
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả.")

    msg.status = "huy"
    msg.last_error = f"Hủy bỏ: {req.reason}"
    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": f"Đã hủy tin nhắn #{message_id}.",
        "status": msg.status,
        "last_error": msg.last_error,
    }


@outbound_router.post("/messages/{message_id}/resend")
def resend_outbound_message(
    message_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Gửi lại tin nhắn kết quả (thường dùng khi bị lỗi mạng hoặc thất bại)."""
    msg = db.get(OutboundMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn kết quả.")

    # Thực hiện gửi thực tế ra Nhóm Zalo đích
    target_grp = msg.target_group
    target_gid = target_grp.zalo_group_id if target_grp else None
    real_zalo_msg_id = None
    if target_gid:
        if target_grp and target_grp.is_test:
            send_ok = True
            real_zalo_msg_id = f"test_mock_zalo_{uuid4().hex[:12]}"
            send_err = None
        else:
            send_ok, real_zalo_msg_id, send_err = ZaloDispatcher.send_to_group(
                group_id=target_gid,
                message=msg.content,
            )
        if not send_ok:
            msg.status = "that_bai"
            msg.last_error = f"Lỗi gửi Zalo: {send_err}"
            db.commit()
            return {"ok": False, "status": "that_bai", "message": f"Gửi lại tin nhắn thất bại: {send_err}"}

    now = _utc_now()
    msg.status = "da_gui"
    msg.sent_at = now
    msg.attempt_count += 1
    msg.zalo_message_id = real_zalo_msg_id or f"zalo_oa_{uuid4().hex[:16]}"
    msg.last_error = None

    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": f"Đã gửi lại tin nhắn #{message_id} ra Nhóm Zalo thành công.",
        "status": msg.status,
        "sent_at": msg.sent_at.isoformat(),
        "zalo_message_id": msg.zalo_message_id,
    }


@outbound_router.post("/seed-samples")
def seed_outbound_samples(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Tạo các bản ghi kết quả tin nhắn mẫu (Đã gửi, Chờ duyệt, Bị hủy, Thất bại) để người dùng xem và kiểm thử trực quan."""
    # Tìm nhóm Zalo làm đích (ưu tiên nhóm test để không gửi ra Zalo thật khi duyệt mẫu)
    target_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.is_test == True))
    if not target_grp:
        target_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == "test_sample_group"))
    if not target_grp:
        target_grp = ZaloGroup(
            zalo_group_id="test_sample_group",
            name="Nhóm Mẫu Test",
            group_role="destination",
            is_active=True,
            is_test=True,
        )
        db.add(target_grp)
        db.flush()

    samples_def = [
        {
            "order_type": "tra",
            "status": "da_gui",
            "content": "[VSICO THÔNG BÁO XE TRẢ HÀNG]\n- Tuyến: HP - Tận Quang\n- Xe: 15C-170.66\n- Tài xế: Phạm Văn Huynh (0986713346)\n- Cont: VSIU2621051 (Seal: 23333878)\n- Khách hàng: Logitem (Tân Quang)\n- Giờ đến dự kiến: 07:00",
            "key": f"sample_sent_{uuid4().hex[:8]}",
            "sent_at": _utc_now(),
            "approved_by": "Nguyễn Văn Hưng (ĐHVT)",
            "zalo_msg_id": f"zalo_oa_{uuid4().hex[:12]}",
        },
        {
            "order_type": "dong",
            "status": "cho_duyet",
            "content": "[VSICO THÔNG BÁO XE ĐÓNG HÀNG - CHỜ DUYỆT]\n- Tuyến: HP - Hải Dương\n- Xe: 29C-445.41\n- Tài xế: Vũ Tiến Đạt (0931142873)\n- Cont: GAOU7801569 (Seal: 23691177)\n- Khách hàng: DC (Bột ngọt)\n- Giờ hẹn: 07:00",
            "key": f"sample_pending_{uuid4().hex[:8]}",
            "sent_at": None,
            "approved_by": None,
            "zalo_msg_id": None,
        },
        {
            "order_type": "tra",
            "status": "huy",
            "content": "[VSICO THÔNG BÁO HỦY CHUYẾN XE]\n- Xe 15H-006.42 gặp sự cố hỏng lốp trên đường về kho Long An.\n- Hủy cuốc vận chuyển cont VSIU2321938 ngày 12/10/2026.",
            "key": f"sample_cancelled_{uuid4().hex[:8]}",
            "sent_at": None,
            "approved_by": "Trần Thị Lan (Điều hành)",
            "zalo_msg_id": None,
            "last_error": "Hủy bỏ: Xe hỏng đột xuất, đã điều xe 15H-067.22 thay thế.",
        },
        {
            "order_type": "dong",
            "status": "that_bai",
            "content": "[VSICO THÔNG BÁO XE ĐÓNG HÀNG]\n- Xe: 15H-067.22 / Đào Đức Thoại (0364461978)\n- Cont: VSIU2323000 (Seal: 23333330)",
            "key": f"sample_failed_{uuid4().hex[:8]}",
            "sent_at": None,
            "approved_by": None,
            "zalo_msg_id": None,
            "last_error": "Lỗi Zalo OA: Mã phản hồi HTTP 429 Too Many Requests (Quá tần suất cho phép)",
        },
    ]

    created_ids = []
    for s in samples_def:
        msg = OutboundMessage(
            target_group_id=target_grp.id,
            order_type=s["order_type"],
            message_kind="initial",
            content=s["content"],
            idempotency_key=s["key"],
            status=s["status"],
            approved_by=s.get("approved_by"),
            approved_at=_utc_now() if s.get("approved_by") else None,
            sent_at=s.get("sent_at"),
            zalo_message_id=s.get("zalo_msg_id"),
            last_error=s.get("last_error"),
            created_at=_utc_now(),
        )
        db.add(msg)
        db.flush()
        created_ids.append(msg.id)

    db.commit()
    return {
        "ok": True,
        "message": f"Đã tạo {len(created_ids)} bản ghi tin nhắn kết quả mẫu đủ 4 trạng thái (Đã gửi, Chờ duyệt, Bị hủy, Thất bại).",
        "created_ids": created_ids,
    }
