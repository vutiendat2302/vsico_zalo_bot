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
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.api.schemas import (
    ContainerJobOut,
    MessageItemOut,
    MessageListResponse,
    TruckRecordOut,
)
from src.config.settings import settings
from src.domain.enums import Intent, MessageStatus, ValidationStatus
from src.handlers.extraction_handler import ExtractionHandler
from src.infrastructure.database import get_db
from src.infrastructure.fifo_queue import fifo_queue
from src.infrastructure.models import (
    ContainerJob,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.zalo_dispatcher import ZaloDispatcher
from src.messaging.classifier import IntentClassifier
from src.outbound.templates import OutboundTemplateBuilder
from src.parsing.ai_fallback import AIFallbackExtractor
from src.parsing.trip_parser import TripParser
from src.validation.taxonomy import MessageTaxonomyAnalyzer
from src.validation.validators import ContainerValidator

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


def serialize_message(msg: ZaloMessage) -> MessageItemOut:
    """Chuyển đổi bản ghi ORM `ZaloMessage` kèm các xe, container và Taxonomy sang Schema trả về API.

    Args:
        msg (ZaloMessage): Đối tượng ORM `ZaloMessage` từ cơ sở dữ liệu.

    Returns:
        MessageItemOut: Đối tượng dữ liệu chuẩn hóa trả về JSON.
    """
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
                eta_text=t_raw.get("eta_text"),
                estimated_at=est_dt,
                note=t_raw.get("note"),
                status=t_raw.get("status", "active"),
            )
        )

    taxonomy: Optional[dict[str, Any]] = None
    containers: list[ContainerJobOut] = []
    for c in sorted(msg.container_jobs, key=lambda x: ((x.line_no or 1), x.id)):
        c_raw = c.raw_fields or {}
        if taxonomy is None and c_raw.get("taxonomy"):
            taxonomy = c_raw.get("taxonomy")
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
                eta=c_raw.get("eta"),
                estimated_at=c.estimated_at,
                match_source=c_raw.get("match_source") or c.match_method,
                check_digit_valid=c.container_check_digit_valid,
                validation_status=c.validation_status,
                routing_status=c.routing_status,
                tms_sync_status=c.tms_sync_status,
                warnings=c_raw.get("warnings", []),
                canonical_record=c_raw.get("canonical_record"),
            )
        )

    if taxonomy is None and msg.extraction_runs:
        latest_run = sorted(msg.extraction_runs, key=lambda r: r.id)[-1]
        if latest_run.output_data and "taxonomy" in latest_run.output_data:
            taxonomy = latest_run.output_data["taxonomy"]

    return MessageItemOut(
        id=msg.id,
        zalo_message_id=msg.zalo_message_id,
        group_id=msg.group_id,
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
        stmt = stmt.where(ZaloMessage.processing_status == status)

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
        count_stmt = count_stmt.where(ZaloMessage.processing_status == status)
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
    serialized = [serialize_message(r) for r in records]

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
def trigger_fifo_processing(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Kích hoạt thủ công tiến trình vét và bóc tách các tin nhắn tồn đọng theo đúng thứ tự FIFO."""
    processed_ids = fifo_queue.drain_fifo(db)
    return {
        "ok": True,
        "status": "OK",
        "processed_count": len(processed_ids),
        "processed_message_ids_fifo_order": processed_ids,
        "queue_stats": fifo_queue.stats(),
    }


class TestParseRequest(BaseModel):
    """Schema đầu vào cho API kiểm thử trực tiếp bộ đọc F1 / F2 / F3 / Bảng 6.2."""

    text: str = Field(
        ...,
        description="Nội dung tin nhắn cần kiểm thử bóc tách (F1, F2, F3 hoặc Tự do).",
        examples=["1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2621051 chì 23333878"],
    )
    timestamp: Optional[str] = Field(
        default="2026-10-09T07:30:00",
        description="Thời điểm gửi tin nhắn giả lập (dùng để suy luận plan_date cho F1/F3).",
    )
    allow_ai_fallback: bool = Field(
        default=False,
        description="Cho phép gọi AI (ZCB-10) nếu tin không theo F1/F2/F3. Mặc định False để kiểm thử thuần Rule-based.",
    )


def execute_single_parse_test(
    db: Session,
    raw_text: str,
    timestamp_str: Optional[str] = "2026-10-09T07:30:00",
    allow_ai_fallback: bool = False,
) -> dict[str, Any]:
    """Thực thi kiểm thử trọn vẹn luồng Đọc hiểu & Định tuyến (F1/F2/F3, Bảng 6.2, định tuyến AI ZCB-10).

    Args:
        db (Session): Phiên làm việc cơ sở dữ liệu để đối chiếu danh mục/alias.
        raw_text (str): Nội dung tin nhắn đầu vào.
        timestamp_str (Optional[str]): Mốc thời gian gửi tin.
        allow_ai_fallback (bool): Có gọi thật AI Fallback khi tin là `tu_do` hay không.

    Returns:
        dict[str, Any]: Kết quả chi tiết gồm `source_format`, `used_ai`, `route_to_ai_zcb10`,
            `canonical_records`, `warnings`, `reply_to_carrier` và `taxonomy`.
    """
    ref_time = parse_flexible_datetime(timestamp_str) or datetime(2026, 10, 9, 7, 30, 0)
    clean_text = (raw_text or "").strip()

    # 1. Bộ lọc 2 tầng chặn tin nhắn xã giao (TC-16)
    intent = IntentClassifier.classify(clean_text)
    if intent == Intent.IGNORE_CHAT:
        taxonomy = MessageTaxonomyAnalyzer.analyze(
            raw_text=clean_text,
            intent=intent,
            lines=[],
        )
        return {
            "ok": True,
            "intent": intent.value,
            "processing_status": MessageStatus.IGNORED_CHAT.value,
            "source_format": None,
            "used_ai": False,
            "route_to_ai_zcb10": False,
            "model_name": "fast-gatekeeper-v2",
            "canonical_records": [],
            "validation_results": [],
            "warnings": [],
            "reply_to_carrier": None,
            "taxonomy": taxonomy,
        }

    # 2. Bóc tách bằng Bộ đọc F1 / F2 / F3 / Tự do
    extracted_lines = TripParser.parse_message(clean_text, reference_time=ref_time)
    validated_lines = ContainerValidator.validate_all(extracted_lines)
    used_ai = False
    model_name = "vsico-hybrid-rule-v2"

    # Kiểm tra điều kiện chuyển bước AI (ZCB-10): Tin không theo F1/F2/F3 và thiếu trường cốt lõi
    needs_ai_zcb10 = (
        all(ln.source_format == "tu_do" for ln in validated_lines)
        and all(not ln.truck_plate and not ln.container_no for ln in validated_lines)
    )

    if needs_ai_zcb10 and allow_ai_fallback and settings.AI_ENABLED and settings.AI_API_KEY:
        ai_lines = AIFallbackExtractor.extract_with_ai(clean_text, reference_time=ref_time)
        if ai_lines:
            validated_lines = ContainerValidator.validate_all(ai_lines)
            used_ai = True
            model_name = f"ai-fallback:{settings.AI_PROVIDER}:{settings.AI_MODEL_NAME}"

    # 3. Đối chiếu danh mục Khách hàng / Alias / Kho / Kế hoạch
    any_u_wh = False
    any_u_cust = False
    any_amb = False
    for line in validated_lines:
        _, _, u_wh, u_cust, amb = ExtractionHandler._enrich_from_catalog_and_plans(db, line)
        any_u_wh = any_u_wh or u_wh
        any_u_cust = any_u_cust or u_cust
        any_amb = any_amb or amb

    taxonomy = MessageTaxonomyAnalyzer.analyze(
        raw_text=clean_text,
        intent=intent,
        lines=validated_lines,
        unmatched_warehouse=any_u_wh,
        unmatched_customer=any_u_cust,
        ambiguous_route_match=any_amb,
    )

    all_warnings: list[str] = []
    validation_results: list[dict[str, Any]] = []
    for ln in validated_lines:
        all_warnings.extend(ln.warnings)
        validation_results.append(
            {
                "line_no": ln.line_no,
                "source_format": ln.source_format,
                "truck_plate": ln.truck_plate,
                "trailer_plate": ln.trailer_plate,
                "driver_name": ln.driver_name,
                "driver_phone": ln.driver_phone,
                "container_no": ln.container_no,
                "check_digit_valid": ln.check_digit_valid,
                "seal_no": ln.seal_no,
                "validation_status": ln.validation_status,
                "warnings": ln.warnings,
            }
        )

    has_error = any(
        ln.validation_status in (ValidationStatus.INVALID.value, ValidationStatus.NEEDS_REVIEW.value)
        for ln in validated_lines
    )
    reply_text = OutboundTemplateBuilder.build_carrier_warning_reply(validated_lines) if has_error else ""

    return {
        "ok": True,
        "intent": intent.value,
        "processing_status": (
            MessageStatus.NEEDS_REVIEW.value if has_error else MessageStatus.PROCESSED.value
        ),
        "source_format": validated_lines[0].source_format if validated_lines else "tu_do",
        "used_ai": used_ai,
        "route_to_ai_zcb10": needs_ai_zcb10,
        "model_name": model_name,
        "canonical_records": [ln.to_canonical_record() for ln in validated_lines],
        "validation_results": validation_results,
        "warnings": all_warnings,
        "reply_to_carrier": reply_text or None,
        "taxonomy": taxonomy,
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

    if msg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy tin nhắn với ID hoặc zalo_message_id = '{message_id}'.",
        )

    serialized = serialize_message(msg)
    runs_out = [
        {
            "id": r.id,
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
            "id": rv.id,
            "container_job_id": rv.container_job_id,
            "case_type": rv.case_type,
            "reason": rv.reason,
            "status": rv.status,
        }
        for rv in sorted(msg.review_cases, key=lambda x: x.id)
    ]
    replies_out = [
        {
            "id": rp.id,
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
        for om in out_rows:
            zg = om.target_group
            outbound_messages_out.append({
                "id": om.id,
                "target_group_id": om.target_group_id,
                "target_zalo_group_id": zg.zalo_group_id if zg else None,
                "target_group_name": zg.name if zg else f"Nhóm #{om.target_group_id}",
                "order_type": om.order_type,
                "message_kind": om.message_kind or "initial",
                "attempt_count": om.attempt_count or 0,
                "content": om.content,
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
                OutboundMessage.status.in_(["cho_duyet", "bo_qua_trung_lap", "that_bai"]),
            )
            .distinct()
        )
        for out_msg in db.scalars(stmt_out).all():
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

            out_msg.status = "da_gui"
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

    # 4. Đổi trạng thái tin nhắn gốc thành 'processed'
    msg.processing_status = "processed"
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
            ReviewCase.status == "pending",
        )
    ).all():
        rc.status = "rejected"
        rc.resolved_at = now
        rc.resolved_by = operator_name
        rc.reason = f"{rc.reason or ''} [ĐHVT từ chối: {reject_reason}]"

    # 2. Cập nhật ContainerJob
    for cj in msg.container_jobs:
        cj.validation_status = "rejected"
        cj.routing_status = "cancelled"
        cj.tms_sync_status = "failed"

    # 3. Hủy toàn bộ OutboundMessage đang chờ duyệt
    job_ids = [c.id for c in msg.container_jobs]
    cancelled_outbounds = []
    if job_ids:
        stmt_out = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id.in_(job_ids),
                OutboundMessage.status == "cho_duyet",
            )
            .distinct()
        )
        for out_msg in db.scalars(stmt_out).all():
            out_msg.status = "huy"
            out_msg.last_error = f"ĐHVT từ chối duyệt: {reject_reason}"
            cancelled_outbounds.append(out_msg.id)

    # 4. Đổi trạng thái tin nhắn gốc thành 'cancelled'
    msg.processing_status = "cancelled"
    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": f"ĐHVT đã từ chối tin nhắn #{message_id} thành công! Đã hủy {len(cancelled_outbounds)} thông báo gửi Zalo.",
        "message_id": message_id,
        "processing_status": msg.processing_status,
        "cancelled_outbounds": cancelled_outbounds,
    }


@router.post("/test-parse")
def test_parse_message_api(
    payload: TestParseRequest = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """API Kiểm Thử Nhanh Module Đọc Hiểu & Định Tuyến (F1, F2, F3, Bảng 6.2, ZCB-10).

    Cho phép truyền bất kỳ văn bản tin nhắn nào vào để kiểm tra ngay lập tức:
    - Định dạng nhận diện (`F1`, `F2`, `F3`, `tu_do`)
    - Bản ghi chuẩn 15 trường (`canonical_records`)
    - Kết quả kiểm tra từng trường theo Bảng 6.2 (`validation_results`, `warnings`)
    - Tin nhắn nhắc lỗi nhà xe (`reply_to_carrier`)
    - Cờ `used_ai` và `route_to_ai_zcb10`
    """
    return execute_single_parse_test(
        db=db,
        raw_text=payload.text,
        timestamp_str=payload.timestamp,
        allow_ai_fallback=payload.allow_ai_fallback,
    )


@router.get("/test-suite/dat-module")
@router.post("/test-suite/dat-module")
def run_dat_module_test_suite(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """API Chạy Tự Động Bộ Kiểm Thử Module Đọc Hiểu & Định Tuyến (`TC-01` -> `TC-08` và `TC-16`).

    Kiểm tra toàn bộ yêu cầu của module Đọc hiểu và định tuyến:
    - Bộ đọc F1 (`TC-01`, `TC-02`, `TC-03`): tách biển số, tài xế, SĐT, cont, chì.
    - Bộ đọc F2 (`TC-04`) và F3 (`TC-05`) theo nhãn, xử lý các chỗ khó ở mục 2.
    - Chuẩn hóa và kiểm tra từng trường theo Bảng 6.2 (`TC-06` sai ISO 6346, `TC-07` SĐT 9 số,
      `TC-08` biển rơ-moóc `15R01234` ở vị trí đầu kéo), trả về danh sách lỗi (`warnings` + `reply_to_carrier`).
    - Bộ lọc tin xã giao (`TC-16`): bỏ qua, không gọi AI.
    - Khẳng định 100% các ca `TC-01` -> `TC-08` và `TC-16` chạy đúng mà **không cần gọi AI (`used_ai = False`)**.
    """
    test_cases: list[dict[str, Any]] = [
        {
            "tc_id": "TC-01",
            "title": "F1 chuẩn nhà xe miền Bắc (tách biển số, tài xế, SĐT, cont, chì)",
            "input_text": "1 xe 15C17066/ Phạm Văn Huynh đt:  0986713346 / VSIU2621051 chì 23333878",
            "timestamp": "2026-10-09T07:30:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F1"
                and len(r["canonical_records"]) == 1
                and r["canonical_records"][0]["plate"] == "15C17066"
                and r["canonical_records"][0]["driver_name"] == "Phạm Văn Huynh"
                and r["canonical_records"][0]["driver_phone"] == "0986713346"
                and r["canonical_records"][0]["cont_no"] == "VSIU2621051"
                and r["canonical_records"][0]["seal_no"] == "23333878"
                and r["validation_results"][0]["check_digit_valid"] is True
                and r["warnings"] == []
            ),
        },
        {
            "tc_id": "TC-02",
            "title": "F1 SĐT dính liền tên tài xế, không có chữ 'đt:', chữ 'h' thường trong biển số",
            "input_text": "2 Xe 15h00642 / Đoàn Văn Biên 0984457785/ VSIU2321938 chì 23333310",
            "timestamp": "2026-10-09T07:30:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F1"
                and len(r["canonical_records"]) == 1
                and r["canonical_records"][0]["plate"] == "15H00642"
                and r["canonical_records"][0]["driver_name"] == "Đoàn Văn Biên"
                and r["canonical_records"][0]["driver_phone"] == "0984457785"
                and r["canonical_records"][0]["cont_no"] == "VSIU2321938"
                and r["canonical_records"][0]["seal_no"] == "23333310"
                and r["validation_results"][0]["check_digit_valid"] is True
                and r["warnings"] == []
            ),
        },
        {
            "tc_id": "TC-03",
            "title": "F1 có dấu hai chấm sau chữ 'xe:' (3 xe: 15H06722/...)",
            "input_text": "3 xe: 15H06722/ Đào Đức Thoại đt:  0364461978/ VSIU2323000 chì 23333330",
            "timestamp": "2026-10-09T07:30:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F1"
                and len(r["canonical_records"]) == 1
                and r["canonical_records"][0]["plate"] == "15H06722"
                and r["canonical_records"][0]["driver_name"] == "Đào Đức Thoại"
                and r["canonical_records"][0]["driver_phone"] == "0364461978"
                and r["canonical_records"][0]["cont_no"] == "VSIU2323000"
                and r["canonical_records"][0]["seal_no"] == "23333330"
                and r["validation_results"][0]["check_digit_valid"] is True
                and r["warnings"] == []
            ),
        },
        {
            "tc_id": "TC-04",
            "title": "F2 form ĐHVT HCM (dấu chấm trước ngày, nhãn kép Đóng/Trả, 1x20, alias Nhựa Long An, seal trống, 8h)",
            "input_text": (
                "Đầu ĐHVT HCM đang gửi nội dung xe trả hàng:\n"
                "1.  Ngày: .9/10/2026 : Đóng , Trả hàng: Tra 1x20 Nhựa Long An\n"
                "- Tên lái xe: Nguyên Thanh Phong\n"
                "- Sđt: 0931142873\n"
                "-  Số xe: 50H-04915\n"
                "- Số cont : VSIU2620327\n"
                "-  Số seal:\n"
                "- Thời gian xe đến kho: 8h"
            ),
            "timestamp": "2026-10-08T18:00:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F2"
                and len(r["canonical_records"]) == 1
                and r["canonical_records"][0]["plan_date"] == "2026-10-09"
                and r["canonical_records"][0]["order_type"] == "tra"
                and r["canonical_records"][0]["customer_raw"] == "Nhựa Long An"
                and r["canonical_records"][0]["customer_id"] is not None
                and r["canonical_records"][0]["match_source"] == "customer_alias"
                and r["canonical_records"][0]["plate"] == "50H04915"
                and r["canonical_records"][0]["driver_name"] == "Nguyên Thanh Phong"
                and r["canonical_records"][0]["driver_phone"] == "0931142873"
                and r["canonical_records"][0]["cont_no"] == "VSIU2620327"
                and r["canonical_records"][0]["cont_size"] == "20"
                and r["canonical_records"][0]["seal_no"] is None
                and r["canonical_records"][0]["eta"] == "08:00"
                and r["warnings"] == []
            ),
        },
        {
            "tc_id": "TC-05",
            "title": "F3 cú pháp mẫu VSICO (có dòng Lệnh, SĐT, Điểm đóng/trả, Số chì trống)",
            "input_text": (
                "Khách hàng: Nhựa Á Đông\n"
                "Lệnh: Trả\n"
                "Biển số xe: 50H-04915\n"
                "Tên lái xe: Nguyễn Thanh Phong\n"
                "SĐT: 0931142873\n"
                "Số cont: VSIU2620327\n"
                "Số chì:\n"
                "Điểm đóng/trả: Kho Nhựa Á Đông – Long An\n"
                "Thời gian dự kiến đến kho: 08:00"
            ),
            "timestamp": "2026-10-09T07:00:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F3"
                and len(r["canonical_records"]) == 1
                and r["canonical_records"][0]["plan_date"] == "2026-10-09"
                and r["canonical_records"][0]["order_type"] == "tra"
                and r["canonical_records"][0]["customer_raw"] == "Nhựa Á Đông"
                and r["canonical_records"][0]["location_raw"] == "Kho Nhựa Á Đông – Long An"
                and r["canonical_records"][0]["plate"] == "50H04915"
                and r["canonical_records"][0]["driver_name"] == "Nguyễn Thanh Phong"
                and r["canonical_records"][0]["driver_phone"] == "0931142873"
                and r["canonical_records"][0]["cont_no"] == "VSIU2620327"
                and r["canonical_records"][0]["seal_no"] is None
                and r["canonical_records"][0]["eta"] == "08:00"
                and r["warnings"] == []
            ),
        },
        {
            "tc_id": "TC-06",
            "title": "Kiểm tra Bảng 6.2: Số container sai chữ số kiểm tra cuối theo ISO 6346 (VSIU2323001)",
            "input_text": "1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2323001 chì 23333878",
            "timestamp": "2026-10-09T07:30:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F1"
                and r["canonical_records"][0]["cont_no"] == "VSIU2323001"
                and r["validation_results"][0]["check_digit_valid"] is False
                and any(w.startswith("ISO6346_CHECK_DIGIT_MISMATCH") for w in r["warnings"])
                and r["reply_to_carrier"] is not None
                and "VSIU2323000" in r["reply_to_carrier"]
            ),
        },
        {
            "tc_id": "TC-07",
            "title": "Kiểm tra Bảng 6.2: SĐT tài xế thiếu chữ số (9 số: 098457785)",
            "input_text": "1 xe 15C17066/ Phạm Văn Huynh đt: 098457785 / VSIU2621051 chì 23333878",
            "timestamp": "2026-10-09T07:30:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F1"
                and r["canonical_records"][0]["driver_name"] == "Phạm Văn Huynh"
                and r["canonical_records"][0]["driver_phone"] == "098457785"
                and "INVALID_DRIVER_PHONE" in r["warnings"]
                and r["reply_to_carrier"] is not None
            ),
        },
        {
            "tc_id": "TC-08",
            "title": "Kiểm tra Bảng 6.2: Biển số rơ-moóc (15R01234) đặt ở vị trí biển số xe đầu kéo",
            "input_text": "1 xe 15R01234/ Phạm Văn Huynh đt: 0986713346 / VSIU2621051 chì 23333878",
            "timestamp": "2026-10-09T07:30:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["source_format"] == "F1"
                and r["canonical_records"][0]["plate"] is None
                and r["validation_results"][0]["trailer_plate"] == "15R-012.34"
                and "MISSING_TRUCK_PLATE" in r["warnings"]
                and any(w.startswith("TRAILER_PLATE_IN_TRUCK_POSITION") for w in r["warnings"])
                and r["reply_to_carrier"] is not None
            ),
        },
        {
            "tc_id": "TC-16",
            "title": "Bộ lọc 2 tầng: Tin nhắn xã giao ('ok anh, để em báo tài') -> Bỏ qua, không gọi AI",
            "input_text": "ok anh, để em báo tài",
            "timestamp": "2026-10-09T07:30:00",
            "verify": lambda r: (
                r["used_ai"] is False
                and r["processing_status"] == "ignored_chat"
                and r["canonical_records"] == []
                and r["reply_to_carrier"] is None
            ),
        },
    ]

    results_out: list[dict[str, Any]] = []
    passed_count = 0
    ai_calls_count = 0

    for tc in test_cases:
        res = execute_single_parse_test(
            db=db,
            raw_text=tc["input_text"],
            timestamp_str=tc["timestamp"],
            allow_ai_fallback=False,
        )
        passed = bool(tc["verify"](res))
        if passed:
            passed_count += 1
        if res["used_ai"]:
            ai_calls_count += 1
        results_out.append(
            {
                "tc_id": tc["tc_id"],
                "title": tc["title"],
                "passed": passed,
                "used_ai": res["used_ai"],
                "source_format": res["source_format"],
                "processing_status": res["processing_status"],
                "input_text": tc["input_text"],
                "canonical_records": res["canonical_records"],
                "warnings": res["warnings"],
                "reply_to_carrier": res["reply_to_carrier"],
            }
        )

    return {
        "ok": passed_count == len(test_cases),
        "module_owner": "Đạt – Module Đọc hiểu và định tuyến",
        "total_cases": len(test_cases),
        "passed_cases": passed_count,
        "failed_cases": len(test_cases) - passed_count,
        "ai_calls_count": ai_calls_count,
        "summary": (
            f"PASS {passed_count}/{len(test_cases)} test cases (TC-01 -> TC-08, TC-16), "
            f"số lần gọi AI = {ai_calls_count} (đạt chuẩn 100% Rule-based không cần gọi AI)."
        ),
        "results": results_out,
    }
