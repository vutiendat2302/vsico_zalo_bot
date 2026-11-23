"""Module Các REST API Truy Vấn Tin Nhắn, Kết Quả Bóc Tách & Thống Kê Taxonomy (Bảng 1 & Bảng 2).

Cung cấp đầy đủ 4 nhóm API truy vấn tin nhắn kèm dữ liệu xe (`trucks`), container (`containers`)
và phân loại Taxonomy (`T01` -> `T40`), cùng API thống kê tổng hợp Bảng 1 & Bảng 2:
1. Lấy tất cả các tin nhắn: `GET /api/messages`
2. Lấy tất cả tin nhắn theo User ID: `GET /api/messages/user/{user_id}`
3. Lấy tất cả tin nhắn theo Group ID: `GET /api/messages/group/{group_id}`
4. Lấy tất cả tin nhắn của một User trong một Group:
   - `GET /api/messages/group/{group_id}/user/{user_id}`
   - `GET /api/messages/user/{user_id}/group/{group_id}`
5. Thống kê số tin theo Bảng 1 (1.1->1.6) & Bảng 2 (T01->T40):
   - `GET /api/messages/statistics`
"""

from datetime import datetime
import re
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.api.schemas import (
    ContainerJobOut,
    MessageItemOut,
    MessageListResponse,
    TruckRecordOut,
)
from src.config.settings import settings
from src.domain.enums import (
    Intent,
    MessageStatus,
    OutboundStatus,
    ReviewStatus,
    RoutingStatus,
    TmsSyncStatus,
    ValidationStatus,
)
from src.handlers.extraction_handler import ExtractionHandler
from src.handlers.plan_sync_service import resolve_job_expected_time
from src.infrastructure.database import get_db
from src.infrastructure.fifo_queue import fifo_queue
from src.infrastructure.models import (
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TruckRecord,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.zalo_dispatcher import ZaloDispatcher
from src.outbound.templates import format_arrival_time_display

router = APIRouter(prefix="/api/messages", tags=["2. Truy Vấn Tin Nhắn & Thống Kê Taxonomy"])


def parse_flexible_datetime(
    raw_value: Optional[str],
    is_end_of_range: bool = False,
) -> Optional[datetime]:
    """Chuyển đổi chuỗi thời gian từ Query Parameter sang đối tượng `datetime`.

    Hỗ trợ linh hoạt nhiều định dạng:
    - Chuẩn ISO-8601: `2026-10-27T08:30:00`, `2026-10-27 08:30:00`, `2026-10-27 08:30`
    - Chỉ nhập ngày (`YYYY-MM-DD` hoặc `DD/MM/YYYY`):
      + Nếu là mốc bắt đầu (`is_end_of_range=False`): Tự động lấy `00:00:00`.
      + Nếu là mốc kết thúc (`is_end_of_range=True`): Tự động mở rộng đến `23:59:59.999999`.
    - Định dạng Việt Nam: `27/10/2026 14:30:00` hoặc `27/10/2026`
    - Epoch timestamp (giây hoặc mili-giây).

    Args:
        raw_value (Optional[str]): Chuỗi thời gian người dùng nhập trên URL.
        is_end_of_range (bool): Cờ đánh dấu đây là mốc kết thúc (`to_time` / `end_time`).

    Returns:
        Optional[datetime]: Đối tượng `datetime` hoặc None nếu người dùng không nhập.

    Raises:
        HTTPException: Mã 400 nếu chuỗi thời gian sai định dạng.
    """
    if raw_value is None or not str(raw_value).strip():
        return None

    text = str(raw_value).strip()

    if text.isdigit():
        val = float(text)
        if val > 1e11:
            val = val / 1000.0
        return datetime.fromtimestamp(val)

    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
            if is_end_of_range:
                return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Thời gian không hợp lệ: '{raw_value}'. Vui lòng dùng YYYY-MM-DD hoặc YYYY-MM-DD HH:MM:SS.",
            ) from exc

    vn_date_match = re.match(
        r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$",
        text,
    )
    if vn_date_match:
        day = int(vn_date_match.group(1))
        month = int(vn_date_match.group(2))
        year = int(vn_date_match.group(3))
        has_time = vn_date_match.group(4) is not None
        hour = int(vn_date_match.group(4) or (23 if is_end_of_range else 0))
        minute = int(vn_date_match.group(5) or (59 if is_end_of_range else 0))
        second = int(vn_date_match.group(6) or (59 if (is_end_of_range and not has_time) else 0))
        micro = 999999 if (is_end_of_range and not has_time) else 0
        try:
            return datetime(year, month, day, hour, minute, second, micro)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Ngày tháng không hợp lệ: '{raw_value}'.",
            ) from exc

    try:
        cleaned = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Định dạng thời gian không hợp lệ: '{raw_value}'. "
                "Hỗ trợ: 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS', 'DD/MM/YYYY', hoặc ISO-8601."
            ),
        ) from exc


def serialize_message(
    msg: ZaloMessage,
    group_name: Optional[str] = None,
    db: Optional[Session] = None,
) -> MessageItemOut:
    """Chuyển đổi bản ghi ORM `ZaloMessage` kèm các xe, container và Taxonomy sang Schema trả về API.

    Args:
        msg (ZaloMessage): Đối tượng ORM `ZaloMessage` từ cơ sở dữ liệu.
        group_name (Optional[str]): Tên hiển thị của nhóm Zalo tương ứng.
        db (Optional[Session]): Phiên DB tùy chọn để tự động bổ sung thời gian dự kiến từ kế hoạch nếu bản ghi cũ còn trống.

    Returns:
        MessageItemOut: Đối tượng dữ liệu chuẩn hóa trả về JSON.
    """
    taxonomy: Optional[dict[str, Any]] = None
    containers: list[ContainerJobOut] = []
    eta_by_truck_id: dict[int, str] = {}
    fallback_msg_eta: Optional[str] = None

    for c in sorted(msg.container_jobs, key=lambda x: ((x.line_no or 1), x.id)):
        c_raw = c.raw_fields or {}
        if taxonomy is None and c_raw.get("taxonomy"):
            taxonomy = c_raw.get("taxonomy")
        c_eta = c_raw.get("eta") or (resolve_job_expected_time(db, c) if db is not None else None)
        if c_eta:
            if c.truck_record_id:
                eta_by_truck_id.setdefault(c.truck_record_id, c_eta)
            if fallback_msg_eta is None:
                fallback_msg_eta = c_eta
        canon = c_raw.get("canonical_record")
        if isinstance(canon, dict) and c_eta and not canon.get("eta"):
            canon = {**canon, "eta": c_eta}
        containers.append(
            ContainerJobOut(
                id=c.id,
                truck_record_id=c.truck_record_id,
                line_no=c.line_no or 1,
                source_format=c_raw.get("source_format"),
                plan_date=c_raw.get("plan_date"),
                container_no=c.container_no,
                container_size=c.container_size,
                seal_no=c.seal_no,
                booking_no=c_raw.get("booking_no"),
                order_type=c.order_type,
                warehouse_hint=c.warehouse_hint,
                customer_hint=c.customer_hint,
                eta=c_eta,
                estimated_at=c.estimated_at,
                match_source=c_raw.get("match_source") or c.match_method,
                check_digit_valid=c.container_check_digit_valid,
                validation_status=c.validation_status,
                routing_status=c.routing_status,
                tms_sync_status=c.tms_sync_status,
                warnings=c_raw.get("warnings", []),
                canonical_record=canon,
            )
        )

    trucks: list[TruckRecordOut] = []
    for t in sorted(msg.truck_records, key=lambda x: x.id):
        t_raw = t.raw_data or {}
        est_raw = t_raw.get("estimated_at")
        est_dt = None
        if isinstance(est_raw, str):
            try:
                est_dt = datetime.fromisoformat(est_raw)
            except ValueError:
                est_dt = None
        trucks.append(
            TruckRecordOut(
                id=t.id,
                truck_plate=t.truck_plate,
                trailer_plate=t.trailer_plate,
                driver_name=t.driver_name,
                driver_phone=t.driver_phone,
                eta_text=t_raw.get("eta_text") or t_raw.get("eta") or eta_by_truck_id.get(t.id) or fallback_msg_eta,
                estimated_at=est_dt,
                note=t_raw.get("note"),
                status=t_raw.get("status", "active"),
            )
        )

    if taxonomy is None and msg.extraction_runs:
        latest_run = sorted(msg.extraction_runs, key=lambda r: r.id)[-1]
        if latest_run.output_data and "taxonomy" in latest_run.output_data:
            taxonomy = latest_run.output_data["taxonomy"]

    effective_group_name = group_name
    if not effective_group_name and msg.group_id:
        if str(msg.group_id).startswith("direct_"):
            effective_group_name = f"Chat 1-1 ({msg.sender_name or msg.sender_id})"

    return MessageItemOut(
        id=str(msg.id),
        zalo_message_id=msg.zalo_message_id,
        group_id=msg.group_id,
        group_name=effective_group_name,
        sender_id=msg.sender_id,
        sender_name=msg.sender_name,
        message_type=msg.message_type,
        raw_text=msg.message_text,
        sent_at=msg.zalo_sent_at,
        received_at=msg.received_at,
        processing_status=msg.processing_status,
        taxonomy=taxonomy,
        trucks=trucks,
        containers=containers,
    )


def query_messages_with_filters(
    db: Session,
    user_id: Optional[str] = None,
    group_id: Optional[str] = None,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    search: Optional[str] = None,
) -> MessageListResponse:
    """Thực thi truy vấn danh sách tin nhắn kết hợp lọc theo User, Group và Khoảng thời gian.

    Args:
        db (Session): Phiên làm việc SQLAlchemy.
        user_id (Optional[str]): Mã người gửi (`sender_id`) cần lọc.
        group_id (Optional[str]): Mã nhóm (`group_id`) cần lọc.
        from_time (Optional[str]): Chuỗi thời gian bắt đầu.
        to_time (Optional[str]): Chuỗi thời gian kết thúc.
        start_time (Optional[str]): Bí danh tương đương `from_time`.
        end_time (Optional[str]): Bí danh tương đương `to_time`.
        status (Optional[str]): Trạng thái xử lý cần lọc (nếu có).
        limit (Optional[int]): Giới hạn số bản ghi trả về (mặc định None = lấy tất cả).
        offset (int): Vị trí bắt đầu phân trang.

    Returns:
        MessageListResponse: Kết quả truy vấn kèm tổng số bản ghi và danh sách chi tiết.
    """
    fifo_queue.drain_fifo(db)

    effective_from_raw = from_time or start_time
    effective_to_raw = to_time or end_time

    from_dt = parse_flexible_datetime(effective_from_raw, is_end_of_range=False)
    to_dt = parse_flexible_datetime(effective_to_raw, is_end_of_range=True)

    if from_dt and to_dt and from_dt > to_dt:
        raise HTTPException(
            status_code=400,
            detail=f"Thời gian bắt đầu ({from_dt}) không được lớn hơn thời gian kết thúc ({to_dt}).",
        )

    stmt = (
        select(ZaloMessage)
        .options(
            selectinload(ZaloMessage.truck_records),
            selectinload(ZaloMessage.container_jobs),
            selectinload(ZaloMessage.extraction_runs),
        )
    )

    if user_id:
        stmt = stmt.where(ZaloMessage.sender_id == user_id)
    if group_id:
        stmt = stmt.where(ZaloMessage.group_id == group_id)
    if status:
        norm_status = MessageStatus(status).value
        stmt = stmt.where(ZaloMessage.processing_status.in_([norm_status, status.lower(), status.upper()]))
    if search and search.strip():
        term = f"%{search.strip()}%"
        search_filter = or_(
            ZaloMessage.message_text.ilike(term),
            ZaloMessage.sender_name.ilike(term),
            ZaloMessage.sender_id.ilike(term),
            ZaloMessage.group_id.ilike(term),
            ZaloMessage.truck_records.any(TruckRecord.truck_plate.ilike(term)),
            ZaloMessage.container_jobs.any(ContainerJob.container_no.ilike(term)),
        )
        stmt = stmt.where(search_filter)

    effective_time_col = func.coalesce(ZaloMessage.zalo_sent_at, ZaloMessage.received_at)
    if from_dt is not None:
        stmt = stmt.where(effective_time_col >= from_dt)
    if to_dt is not None:
        stmt = stmt.where(effective_time_col <= to_dt)

    # Đếm tổng số bản ghi khớp bộ lọc để hỗ trợ phân trang chuẩn xác
    count_stmt = select(func.count(ZaloMessage.id))
    if user_id:
        count_stmt = count_stmt.where(ZaloMessage.sender_id == user_id)
    if group_id:
        count_stmt = count_stmt.where(ZaloMessage.group_id == group_id)
    if status:
        norm_status = MessageStatus(status).value
        count_stmt = count_stmt.where(ZaloMessage.processing_status.in_([norm_status, status.lower(), status.upper()]))
    if search and search.strip():
        term = f"%{search.strip()}%"
        search_filter = or_(
            ZaloMessage.message_text.ilike(term),
            ZaloMessage.sender_name.ilike(term),
            ZaloMessage.sender_id.ilike(term),
            ZaloMessage.group_id.ilike(term),
            ZaloMessage.truck_records.any(TruckRecord.truck_plate.ilike(term)),
            ZaloMessage.container_jobs.any(ContainerJob.container_no.ilike(term)),
        )
        count_stmt = count_stmt.where(search_filter)
    if from_dt is not None:
        count_stmt = count_stmt.where(effective_time_col >= from_dt)
    if to_dt is not None:
        count_stmt = count_stmt.where(effective_time_col <= to_dt)

    total_count = db.scalar(count_stmt) or 0

    # Ưu tiên tin nhắn mới nhất lên đầu để người dùng dễ theo dõi
    stmt = stmt.order_by(ZaloMessage.id.desc())

    if offset > 0:
        stmt = stmt.offset(offset)
    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)

    records = list(db.scalars(stmt).all())
    group_ids = {r.group_id for r in records if r.group_id and not str(r.group_id).startswith("direct_")}
    group_name_map: dict[str, str] = {}
    if group_ids:
        groups = list(db.scalars(select(ZaloGroup).where(ZaloGroup.zalo_group_id.in_(group_ids))).all())
        group_name_map = {g.zalo_group_id: g.name for g in groups if g.name}

    serialized = [serialize_message(r, group_name_map.get(r.group_id), db=db) for r in records]

    return MessageListResponse(
        ok=True,
        status="OK",
        total=total_count,
        total_returned=len(serialized),
        filters={
            "user_id": user_id,
            "group_id": group_id,
            "from_time": from_dt.isoformat() if from_dt else None,
            "to_time": to_dt.isoformat() if to_dt else None,
            "status": status,
        },
        messages=serialized,
    )


@router.get("/statistics")
def get_taxonomy_statistics(
    user_id: Optional[str] = Query(default=None, description="Lọc theo User ID (tùy chọn)"),
    group_id: Optional[str] = Query(default=None, description="Lọc theo Group ID (tùy chọn)"),
    from_time: Optional[str] = Query(default=None, description="Thời gian bắt đầu (tùy chọn)"),
    to_time: Optional[str] = Query(default=None, description="Thời gian kết thúc (tùy chọn)"),
    start_time: Optional[str] = Query(default=None, description="Bí danh của from_time"),
    end_time: Optional[str] = Query(default=None, description="Bí danh của to_time"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """API Thống Kê Bảng 1 (1.1->1.6) & Bảng 2 (T01->T40) theo số ID tin nhắn riêng biệt.

    - Đếm số ID tin nhắn riêng biệt chứa từng hạng mục trong Bảng 1 (không đếm trùng nếu 1 tin có nhiều xe).
    - Thống kê số tin cho từng mã `T01` -> `T40` trong Bảng 2 (cả theo `primary_type` và `all_matched_types`).
    """
    msg_list_res = query_messages_with_filters(
        db=db,
        user_id=user_id,
        group_id=group_id,
        from_time=from_time,
        to_time=to_time,
        start_time=start_time,
        end_time=end_time,
    )
    messages_data = [
        {
            "id": m.id,
            "zalo_message_id": m.zalo_message_id,
            "raw_text": m.raw_text or "",
            "taxonomy": m.taxonomy or {},
        }
        for m in msg_list_res.messages
    ]
    report = MessageTaxonomyAnalyzer.build_statistics_report(messages_data)
    return {
        "ok": True,
        "status": "OK",
        "filters": msg_list_res.filters,
        **report,
    }


@router.get("", response_model=MessageListResponse)
def get_all_messages(
    user_id: Optional[str] = Query(default=None, description="Lọc theo User ID người gửi"),
    group_id: Optional[str] = Query(default=None, description="Lọc theo Group ID Zalo"),
    search: Optional[str] = Query(default=None, description="Tìm kiếm theo từ khóa (nội dung, biển số, container, người gửi)"),
    from_time: Optional[str] = Query(
        default=None,
        description="Thời gian bắt đầu (VD: '2026-10-27' hoặc '2026-10-27 08:00:00'). Bỏ trống để lấy hết.",
    ),
    to_time: Optional[str] = Query(
        default=None,
        description="Thời gian kết thúc (VD: '2026-10-27' hoặc '2026-10-27 23:59:59'). Bỏ trống để lấy hết.",
    ),
    start_time: Optional[str] = Query(default=None, description="Bí danh của from_time"),
    end_time: Optional[str] = Query(default=None, description="Bí danh của to_time"),
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái xử lý"),
    limit: Optional[int] = Query(default=None, ge=1, le=5000, description="Giới hạn số lượng trả về"),
    offset: int = Query(default=0, ge=0, description="Vị trí phân trang"),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """API 1: Lấy tất cả các tin nhắn trong hệ thống (kèm thông tin xe, container & Taxonomy)."""
    return query_messages_with_filters(
        db=db,
        user_id=user_id,
        group_id=group_id,
        from_time=from_time,
        to_time=to_time,
        start_time=start_time,
        end_time=end_time,
        status=status,
        limit=limit,
        offset=offset,
        search=search,
    )


@router.get("/user/{user_id}", response_model=MessageListResponse)
def get_messages_by_user_id(
    user_id: str,
    from_time: Optional[str] = Query(
        default=None,
        description="Thời gian bắt đầu (VD: '2026-10-27' hoặc '2026-10-27 08:00:00'). Bỏ trống để lấy hết.",
    ),
    to_time: Optional[str] = Query(
        default=None,
        description="Thời gian kết thúc (VD: '2026-10-27' hoặc '2026-10-27 23:59:59'). Bỏ trống để lấy hết.",
    ),
    start_time: Optional[str] = Query(default=None, description="Bí danh của from_time"),
    end_time: Optional[str] = Query(default=None, description="Bí danh của to_time"),
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái xử lý"),
    limit: Optional[int] = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """API 2: Lấy tất cả tin nhắn được gửi bởi một User ID (`sender_id`), cả nhắn riêng và nhắn trong Group."""
    return query_messages_with_filters(
        db=db,
        user_id=user_id,
        from_time=from_time,
        to_time=to_time,
        start_time=start_time,
        end_time=end_time,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/group/{group_id}", response_model=MessageListResponse)
def get_messages_by_group_id(
    group_id: str,
    from_time: Optional[str] = Query(
        default=None,
        description="Thời gian bắt đầu (VD: '2026-10-27' hoặc '2026-10-27 08:00:00'). Bỏ trống để lấy hết.",
    ),
    to_time: Optional[str] = Query(
        default=None,
        description="Thời gian kết thúc (VD: '2026-10-27' hoặc '2026-10-27 23:59:59'). Bỏ trống để lấy hết.",
    ),
    start_time: Optional[str] = Query(default=None, description="Bí danh của from_time"),
    end_time: Optional[str] = Query(default=None, description="Bí danh của to_time"),
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái xử lý"),
    limit: Optional[int] = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """API 3: Lấy tất cả tin nhắn thuộc về một Group ID (`group_id`)."""
    return query_messages_with_filters(
        db=db,
        group_id=group_id,
        from_time=from_time,
        to_time=to_time,
        start_time=start_time,
        end_time=end_time,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/group/{group_id}/user/{user_id}", response_model=MessageListResponse)
@router.get("/group/{group_id}/users/{user_id}", response_model=MessageListResponse)
@router.get("/user/{user_id}/group/{group_id}", response_model=MessageListResponse)
@router.get("/users/{user_id}/group/{group_id}", response_model=MessageListResponse)
def get_messages_by_user_in_group(
    group_id: str,
    user_id: str,
    from_time: Optional[str] = Query(
        default=None,
        description="Thời gian bắt đầu (VD: '2026-10-27' hoặc '2026-10-27 08:00:00'). Bỏ trống để lấy hết.",
    ),
    to_time: Optional[str] = Query(
        default=None,
        description="Thời gian kết thúc (VD: '2026-10-27' hoặc '2026-10-27 23:59:59'). Bỏ trống để lấy hết.",
    ),
    start_time: Optional[str] = Query(default=None, description="Bí danh của from_time"),
    end_time: Optional[str] = Query(default=None, description="Bí danh của to_time"),
    status: Optional[str] = Query(default=None, description="Lọc theo trạng thái xử lý"),
    limit: Optional[int] = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """API 4: Lấy tất cả tin nhắn của một User (`user_id`) nhắn bên trong một Group (`group_id`)."""
    return query_messages_with_filters(
        db=db,
        user_id=user_id,
        group_id=group_id,
        from_time=from_time,
        to_time=to_time,
        start_time=start_time,
        end_time=end_time,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/process-fifo")
def trigger_fifo_processing(
    force: bool = Query(
        default=False,
        description="Bật True để bỏ qua thời gian chờ 60 giây của nhóm và xử lý ngay",
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Kích hoạt thủ công tiến trình vét và bóc tách các tin nhắn tồn đọng theo đúng thứ tự FIFO."""
    processed_ids = fifo_queue.drain_fifo(db, force=force)
    return {
        "ok": True,
        "status": "OK",
        "force": force,
        "processed_count": len(processed_ids),
        "processed_message_ids_fifo_order": processed_ids,
        "queue_stats": fifo_queue.stats(),
    }


@router.get("/detail/{message_id}")
def get_message_detail(
    message_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lấy chi tiết toàn diện một tin nhắn theo `id` (số nguyên) hoặc `zalo_message_id` (chuỗi).

    Trả về đầy đủ thông tin tin nhắn gốc, lịch sử chạy bóc tách (`extraction_runs`),
    danh sách xe (`trucks`), danh sách container kèm `canonical_record` (`containers`),
    danh sách trường hợp cần rà soát (`review_cases`) và tin nhắn phản hồi nhà xe (`bot_replies`).
    """
    fifo_queue.drain_fifo(db)

    stmt = select(ZaloMessage).options(
        selectinload(ZaloMessage.truck_records),
        selectinload(ZaloMessage.container_jobs),
        selectinload(ZaloMessage.extraction_runs),
        selectinload(ZaloMessage.review_cases),
        selectinload(ZaloMessage.bot_replies),
    )
    msg: Optional[ZaloMessage] = None
    if message_id.isdigit():
        msg = db.scalar(stmt.where(ZaloMessage.id == int(message_id)))
    if msg is None:
        msg = db.scalar(stmt.where(ZaloMessage.zalo_message_id == message_id))
    # Fallback cứu nguy nếu client JavaScript cũ bị làm tròn 2 chữ số cuối của Snowflake ID 64-bit
    if msg is None and message_id.isdigit() and len(message_id) >= 17 and message_id.endswith("00"):
        prefix = int(message_id[:-2])
        range_start = prefix * 100
        range_end = range_start + 100
        msg = db.scalar(stmt.where(ZaloMessage.id >= range_start, ZaloMessage.id < range_end))

    if msg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy tin nhắn với ID hoặc zalo_message_id = '{message_id}'.",
        )

    zg = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == msg.group_id))
    grp_name = zg.name if zg and zg.name else None
    serialized = serialize_message(msg, grp_name, db=db)
    runs_out = [
        {
            "id": str(r.id),
            "model_name": r.model_name,
            "used_ai": str(r.model_name or "").startswith("ai-fallback:"),
            "status": r.status,
            "output_data": r.output_data,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in sorted(msg.extraction_runs, key=lambda x: x.id)
    ]
    reviews_out = [
        {
            "id": str(rv.id),
            "container_job_id": str(rv.container_job_id) if rv.container_job_id else None,
            "case_type": rv.case_type,
            "reason": rv.reason,
            "status": rv.status,
        }
        for rv in sorted(msg.review_cases, key=lambda x: x.id)
    ]
    replies_out = [
        {
            "id": str(rp.id),
            "sender_id": rp.sender_id,
            "reply_text": rp.reply_text,
            "status": rp.status,
            "fix_deadline": rp.fix_deadline.isoformat() if rp.fix_deadline else None,
        }
        for rp in sorted(msg.bot_replies, key=lambda x: x.id)
    ]

    # Lấy danh sách tin nhắn Outbound gửi đến nhóm khách hàng liên kết với các cont của tin này
    job_ids = [c.id for c in msg.container_jobs]
    outbound_messages_out = []
    if job_ids:
        stmt_out = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(OutboundMessageItem.container_job_id.in_(job_ids))
            .distinct()
        )
        out_rows = list(db.scalars(stmt_out).all())
        fallback_eta = next((c.eta for c in serialized.containers if c.eta), None)
        for om in out_rows:
            zg = om.target_group
            content_str = om.content or ""
            if fallback_eta and "- Giờ đến dự kiến: Chưa có" in content_str:
                content_str = content_str.replace(
                    "- Giờ đến dự kiến: Chưa có",
                    f"- Giờ đến dự kiến: {format_arrival_time_display(fallback_eta)}",
                )
            outbound_messages_out.append({
                "id": str(om.id),
                "target_group_id": str(om.target_group_id),
                "target_zalo_group_id": zg.zalo_group_id if zg else None,
                "target_group_name": zg.name if zg and zg.name else "Nhóm khách hàng",
                "order_type": om.order_type,
                "message_kind": om.message_kind or "initial",
                "attempt_count": om.attempt_count or 0,
                "content": content_str,
                "status": om.status,
                "zalo_message_id": om.zalo_message_id,
                "sent_at": om.sent_at.isoformat() if om.sent_at else None,
                "approved_at": om.approved_at.isoformat() if om.approved_at else None,
                "last_error": om.last_error,
            })

    return {
        "ok": True,
        "status": "OK",
        "message": serialized.model_dump(),
        "extraction_runs": runs_out,
        "review_cases": reviews_out,
        "bot_replies": replies_out,
        "outbound_messages": outbound_messages_out,
    }


@router.post("/{message_id}/approve")
def approve_message_by_dhvt(
    message_id: int,
    operator_name: str = Query(default="Điều độ viên ĐHVT", description="Tên người phê duyệt"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """API dành cho Điều độ viên (ĐHVT) duyệt tin nhắn:

    1. Gửi toàn bộ các OutboundMessage đang ở trạng thái 'cho_duyet' ra nhóm Zalo đích (qua ZaloDispatcher).
    2. Cập nhật OutboundMessage: status = 'da_gui', attempt_count += 1, sent_at = now, zalo_message_id.
    3. Cập nhật ReviewCase: status = 'approved', resolved_at = now, resolved_by = operator_name.
    4. Cập nhật ContainerJob: validation_status = 'valid', routing_status = 'routed', tms_sync_status = 'synced'.
    5. Cập nhật ZaloMessage: processing_status = 'processed'.
    """
    msg = db.get(ZaloMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy tin nhắn ID={message_id}.")

    now = datetime.now()

    # 1. Cập nhật các ca ReviewCase liên quan
    for rc in db.scalars(
        select(ReviewCase).where(
            ReviewCase.message_id == message_id,
            ReviewCase.status == "pending",
        )
    ).all():
        rc.status = "approved"
        rc.resolved_at = now
        rc.resolved_by = operator_name

    # 2. Cập nhật ContainerJob
    for cj in msg.container_jobs:
        cj.validation_status = "valid"
        cj.routing_status = "routed"
        cj.tms_sync_status = "synced"

    # 3. Gửi toàn bộ OutboundMessage đang chờ duyệt
    job_ids = [c.id for c in msg.container_jobs]
    sent_outbounds = []
    send_warnings = []
    is_real_msg = not (
        (msg.group_id and ("test_" in msg.group_id or "pytest_" in msg.group_id))
        or (msg.zalo_message_id and (msg.zalo_message_id.startswith("test_") or msg.zalo_message_id.startswith("pytest_")))
        or (msg.sender_id and (msg.sender_id.startswith("test_") or msg.sender_id.startswith("pytest_")))
    )

    real_dest_grp = None
    if is_real_msg:
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

    if job_ids:
        stmt_out = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id.in_(job_ids),
                OutboundMessage.status.in_([
                    OutboundStatus.PENDING_APPROVAL.value,
                    OutboundStatus.IGNORED_DUPLICATE.value,
                    OutboundStatus.FAILED.value,
                    "cho_duyet",
                    "bo_qua_trung_lap",
                    "that_bai",
                ]),
            )
            .distinct()
        )
        for out_msg in db.scalars(stmt_out).all():
            if out_msg.content and "- Giờ đến dự kiến: Chưa có" in out_msg.content:
                for cj in msg.container_jobs:
                    resolved_eta = resolve_job_expected_time(db, cj)
                    if resolved_eta:
                        out_msg.content = out_msg.content.replace(
                            "- Giờ đến dự kiến: Chưa có",
                            f"- Giờ đến dự kiến: {format_arrival_time_display(resolved_eta)}",
                        )
                        break
            target_grp = out_msg.target_group
            target_gid = target_grp.zalo_group_id if target_grp else None

            # Tự động chuyển hướng sang nhóm thật nếu là tin nhắn thực tế mà đích đang trỏ mock group
            if is_real_msg and (not target_gid or target_gid.startswith("test_") or target_gid.startswith("grp_test_") or (target_grp and target_grp.is_test)):
                if real_dest_grp:
                    out_msg.target_group_id = real_dest_grp.id
                    target_grp = real_dest_grp
                    target_gid = real_dest_grp.zalo_group_id

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
                    send_warnings.append(f"Gửi nhóm {target_gid} thất bại: {send_err}")
                    continue

            # Nếu tin nhắn đến từ cuộc hội thoại cá nhân 1-1, gửi phản hồi duyệt thành công trực tiếp cho người gửi
            if msg.sender_id and is_real_msg:
                if not msg.group_id or msg.group_id.startswith("direct_"):
                    direct_content = (
                        f"✅ [VSICO ĐÃ PHÊ DUYỆT]\n"
                        f"Tin nhắn của bạn đã được {operator_name} phê duyệt thành công!\n\n"
                        f"Nội dung thông báo:\n{out_msg.content}"
                    )
                    u_ok, _, u_err = ZaloDispatcher.send_to_user(
                        user_id=msg.sender_id,
                        message=direct_content,
                    )
                    if not u_ok:
                        logger.warning("Không thể gửi tin riêng cho người gửi %s: %s", msg.sender_id, u_err)

            out_msg.status = OutboundStatus.SENT.value
            out_msg.approved_by = operator_name
            out_msg.approved_at = now
            out_msg.sent_at = now
            out_msg.attempt_count = (out_msg.attempt_count or 0) + 1
            out_msg.zalo_message_id = real_zalo_msg_id or out_msg.zalo_message_id or f"zalo_oa_{uuid4().hex[:16]}"
            out_msg.last_error = None
            sent_outbounds.append({
                "outbound_id": out_msg.id,
                "target_group_id": target_gid,
                "zalo_message_id": out_msg.zalo_message_id,
                "status": out_msg.status,
            })

    # 4. Đổi trạng thái tin nhắn gốc thành PROCESSED
    msg.processing_status = MessageStatus.PROCESSED.value
    db.commit()
    db.refresh(msg)

    ret_msg = f"ĐHVT đã duyệt tin nhắn #{message_id} thành công! Đã gửi {len(sent_outbounds)} thông báo tới Zalo."
    if send_warnings:
        ret_msg += f" Cảnh báo gửi Zalo: {'; '.join(send_warnings)}"

    return {
        "ok": True,
        "message": ret_msg,
        "message_id": message_id,
        "processing_status": msg.processing_status,
        "outbounds_dispatched": sent_outbounds,
        "warnings": send_warnings,
    }


class RejectMessagePayload(BaseModel):
    """Payload lý do từ chối tin nhắn."""
    reason: Optional[str] = Field(default="ĐHVT từ chối tin nhắn điều xe.", description="Lý do từ chối")


@router.post("/{message_id}/reject")
def reject_message_by_dhvt(
    message_id: int,
    payload: Optional[RejectMessagePayload] = Body(default=None),
    operator_name: str = Query(default="Điều độ viên ĐHVT", description="Tên người từ chối"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """API dành cho Điều độ viên (ĐHVT) từ chối tin nhắn:

    1. Cập nhật toàn bộ các ca ReviewCase liên quan thành 'rejected'.
    2. Cập nhật ContainerJob: validation_status = 'rejected', routing_status = 'cancelled', tms_sync_status = 'failed'.
    3. Hủy toàn bộ OutboundMessage đang chờ duyệt: status = 'huy'.
    4. Cập nhật ZaloMessage: processing_status = 'cancelled'.
    """
    msg = db.get(ZaloMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy tin nhắn ID={message_id}.")

    reject_reason = (
        payload.reason
        if (payload and payload.reason and payload.reason.strip())
        else "ĐHVT từ chối tin nhắn điều xe."
    )
    now = datetime.now()

    # 1. Cập nhật các ca ReviewCase liên quan
    for rc in db.scalars(
        select(ReviewCase).where(
            ReviewCase.message_id == message_id,
            ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
        )
    ).all():
        rc.status = ReviewStatus.REJECTED.value
        rc.resolved_at = now
        rc.resolved_by = operator_name
        rc.reason = f"{rc.reason or ''} [ĐHVT từ chối: {reject_reason}]"

    # 2. Cập nhật ContainerJob
    for cj in msg.container_jobs:
        cj.validation_status = ValidationStatus.REJECTED.value
        cj.routing_status = RoutingStatus.CANCELLED.value
        cj.tms_sync_status = TmsSyncStatus.FAILED.value

    # 3. Hủy toàn bộ OutboundMessage đang chờ duyệt
    job_ids = [c.id for c in msg.container_jobs]
    cancelled_outbounds = []
    if job_ids:
        stmt_out = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id.in_(job_ids),
                OutboundMessage.status.in_([OutboundStatus.PENDING_APPROVAL.value, "cho_duyet"]),
            )
            .distinct()
        )
        for out_msg in db.scalars(stmt_out).all():
            out_msg.status = OutboundStatus.CANCELLED.value
            out_msg.last_error = f"ĐHVT từ chối duyệt: {reject_reason}"
            cancelled_outbounds.append(out_msg.id)

    # 4. Đổi trạng thái tin nhắn gốc thành CANCELLED
    msg.processing_status = MessageStatus.CANCELLED.value
    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": f"ĐHVT đã từ chối tin nhắn #{message_id} thành công! Đã hủy {len(cancelled_outbounds)} thông báo gửi Zalo.",
        "message_id": message_id,
        "processing_status": msg.processing_status,
        "cancelled_outbounds": cancelled_outbounds,
    }
