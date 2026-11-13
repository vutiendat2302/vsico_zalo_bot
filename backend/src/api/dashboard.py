"""Module Các REST API Bảng Điều Khiển Giám Sát & Đo Lường (Dashboard & Metrics APIs).

Cung cấp toàn bộ chỉ số vận hành thời gian thực phục vụ giao diện Frontend:
1. Thống kê tổng quan KPI: Tổng tin vào, đã xử lý, cần duyệt, tin đã gửi, tin rác đã chặn.
2. Trạng thái hàng đợi FIFO và tải hệ thống (Queue size, Worker status).
3. Trạng thái điều tiết hạn mức Zalo OA (Rate limit, tokens, throttling).
4. Phân bố tin nhắn theo ngày, trạng thái và tỷ lệ lệnh Đóng / Trả.
5. Danh sách hoạt động tin nhắn mới nhất.
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from src.infrastructure.database import get_db
from src.infrastructure.fifo_queue import fifo_queue
from src.infrastructure.models import (
    BotReply,
    ContainerJob,
    ExtractionRun,
    ReviewCase,
    TransportPlan,
    TruckRecord,
    ZaloMessage,
)
from src.infrastructure.throttler import outbound_throttler

router = APIRouter(prefix="/api/dashboard", tags=["4. Bảng Điều Khiển Giám Sát (Dashboard & Metrics)"])


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Lấy toàn bộ chỉ số KPI vận hành thực tế từ cơ sở dữ liệu MySQL (không dùng dữ liệu giả lập)."""
    # 1. Thống kê trạng thái tin nhắn
    msg_stats = db.execute(
        select(
            func.count(ZaloMessage.id).label("total"),
            func.sum(case((ZaloMessage.processing_status == "processed", 1), else_=0)).label("processed"),
            func.sum(case((ZaloMessage.processing_status == "needs_review", 1), else_=0)).label("needs_review"),
            func.sum(case((ZaloMessage.processing_status == "ignored_chat", 1), else_=0)).label("ignored_chat"),
            func.sum(
                case((ZaloMessage.processing_status.in_(["received", "queued", "processing"]), 1), else_=0)
            ).label("queued"),
        )
    ).first()

    total_msgs = int(msg_stats.total or 0) if msg_stats else 0
    processed_msgs = int(msg_stats.processed or 0) if msg_stats else 0
    needs_review_msgs = int(msg_stats.needs_review or 0) if msg_stats else 0
    ignored_msgs = int(msg_stats.ignored_chat or 0) if msg_stats else 0
    queued_msgs = int(msg_stats.queued or 0) if msg_stats else 0

    # 2. Thống kê tác vụ xe, container, kế hoạch, phản hồi nhà xe, trường hợp duyệt
    total_trucks = db.scalar(select(func.count(TruckRecord.id))) or 0
    total_conts = db.scalar(select(func.count(ContainerJob.id))) or 0
    total_plans = db.scalar(select(func.count(TransportPlan.id))) or 0

    # Tin phản hồi bot gửi cho nhà xe (cảnh báo thiếu trường / sai số cont)
    total_replies_sent = db.scalar(select(func.count(BotReply.id))) or 0
    total_reviews_pending = db.scalar(
        select(func.count(ReviewCase.id)).where(ReviewCase.status == "pending")
    ) or 0

    # 3. Thống kê Kế hoạch theo loại lệnh Đóng / Trả
    plans_by_order = db.execute(
        select(
            TransportPlan.order_type,
            func.count(TransportPlan.id),
        ).group_by(TransportPlan.order_type)
    ).all()
    plans_order_summary = {ot: cnt for ot, cnt in plans_by_order if ot}

    # 4. Thống kê tin nhắn theo ngày (7 ngày gần nhất)
    effective_date_col = func.date(func.coalesce(ZaloMessage.zalo_sent_at, ZaloMessage.received_at))
    daily_stats_query = (
        select(
            effective_date_col.label("msg_date"),
            func.count(ZaloMessage.id).label("total"),
            func.sum(case((ZaloMessage.processing_status == "processed", 1), else_=0)).label("processed"),
            func.sum(case((ZaloMessage.processing_status == "needs_review", 1), else_=0)).label("needs_review"),
            func.sum(case((ZaloMessage.processing_status == "ignored_chat", 1), else_=0)).label("ignored"),
        )
        .group_by(effective_date_col)
        .order_by(effective_date_col.desc())
        .limit(14)
    )
    daily_rows = db.execute(daily_stats_query).all()
    daily_list = [
        {
            "date": str(row.msg_date) if row.msg_date else "N/A",
            "total": int(row.total or 0),
            "processed": int(row.processed or 0),
            "needs_review": int(row.needs_review or 0),
            "ignored": int(row.ignored or 0),
        }
        for row in daily_rows
    ]

    # 5. Danh sách 10 tin nhắn gần nhất
    recent_msgs_query = (
        select(ZaloMessage)
        .options(
            selectinload(ZaloMessage.truck_records),
            selectinload(ZaloMessage.container_jobs),
        )
        .order_by(ZaloMessage.id.desc())
        .limit(10)
    )
    recent_records = list(db.scalars(recent_msgs_query).all())

    recent_out = []
    for m in recent_records:
        plates = [t.truck_plate for t in m.truck_records if t.truck_plate]
        conts = [c.container_no for c in m.container_jobs if c.container_no]
        customers = [c.customer_hint for c in m.container_jobs if c.customer_hint]
        recent_out.append(
            {
                "id": str(m.id),
                "zalo_message_id": m.zalo_message_id,
                "group_id": m.group_id,
                "sender_name": m.sender_name or m.sender_id,
                "raw_text": m.message_text,
                "sent_at": m.zalo_sent_at.isoformat() if m.zalo_sent_at else m.received_at.isoformat(),
                "processing_status": m.processing_status,
                "truck_plates": plates,
                "containers": conts,
                "customers": customers,
            }
        )

    # 6. Tỷ lệ xử lý thành công
    processed_rate = round((processed_msgs / total_msgs * 100), 1) if total_msgs > 0 else 0.0

    return {
        "ok": True,
        "status": "OK",
        "timestamp": datetime.now().isoformat(),
        "kpi": {
            "total_messages_received": total_msgs,
            "processed_messages": processed_msgs,
            "needs_review_messages": needs_review_msgs,
            "ignored_chat_messages": ignored_msgs,
            "queued_messages": queued_msgs,
            "processed_rate_percent": processed_rate,
            "total_trucks_extracted": total_trucks,
            "total_containers_extracted": total_conts,
            "total_plans_registered": total_plans,
            "bot_replies_sent": total_replies_sent,
            "reviews_pending": total_reviews_pending,
        },
        "plans_summary": {
            "total": total_plans,
            "dong": plans_order_summary.get("dong", 0),
            "tra": plans_order_summary.get("tra", 0),
        },
        "fifo_queue": fifo_queue.stats(),
        "rate_limiter": outbound_throttler.get_metrics(),
        "daily_breakdown": daily_list,
        "recent_messages": recent_out,
    }
