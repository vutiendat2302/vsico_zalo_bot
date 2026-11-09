"""Module Cổng Tiếp Nhận Sự Kiện Tin Nhắn Thời Gian Thực (Zalo Webhook Gateway).

Cung cấp các endpoint `POST /webhook` và `POST /webhook/zalo` để `zca-js` 
đẩy tin nhắn mới (cả chat trực tiếp 1-1 và chat trong Group) sang Backend.
Ngay khi nhận được, hệ thống lưu bản ghi thô vào MySQL và kích hoạt hàng đợi FIFO
(Vào Trước - Ra Trước) để bóc tách và lưu kết quả ngay lập tức.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import ZcaWebhookPayload
from src.config.settings import settings
from src.infrastructure.database import get_db
from src.infrastructure.models import BotReply, OutboundMessage, OutboundMessageItem, ZaloGroup
from src.ingestion.normalizer import WebhookIngestor

router = APIRouter(tags=["1. Zalo Webhook & Ingestion"])


def _verify_webhook_secret(x_webhook_secret: Optional[str]) -> None:
    """Kiểm tra mã bí mật `x-webhook-secret` trong HTTP Header (nếu được cấu hình trong `.env`).

    Args:
        x_webhook_secret (Optional[str]): Giá trị header `x-webhook-secret` từ client.

    Raises:
        HTTPException: Mã 401 nếu chữ ký bí mật không khớp.
    """
    if settings.ZALO_SECRET_KEY and x_webhook_secret != settings.ZALO_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid X-Webhook-Secret")


@router.post("/webhook")
@router.post("/webhook/zalo")
def receive_zalo_webhook(
    payload: ZcaWebhookPayload,
    db: Session = Depends(get_db),
    x_webhook_secret: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Tiếp nhận tin nhắn thời gian thực từ `zca-js`, lưu thô và bóc tách tuần tự theo FIFO.

    Args:
        payload (ZcaWebhookPayload): Dữ liệu JSON của tin nhắn Zalo.
        db (Session): Phiên làm việc cơ sở dữ liệu MySQL.
        x_webhook_secret (Optional[str]): Header bảo mật tùy chọn.

    Returns:
        dict[str, Any]: Kết quả tiếp nhận, trạng thái FIFO và danh sách xe/container vừa bóc tách.
    """
    _verify_webhook_secret(x_webhook_secret)

    msg, is_duplicate = WebhookIngestor.ingest_webhook_payload(
        db=db,
        payload_dict=payload.model_dump(),
    )

    trucks_summary = [
        {
            "id": t.id,
            "truck_plate": t.truck_plate,
            "trailer_plate": t.trailer_plate,
            "driver_name": t.driver_name,
            "driver_phone": t.driver_phone,
        }
        for t in msg.truck_records
    ]
    containers_summary = [
        {
            "id": c.id,
            "line_no": c.line_no or 1,
            "source_format": (c.raw_fields or {}).get("source_format"),
            "plan_date": (c.raw_fields or {}).get("plan_date"),
            "container_no": c.container_no,
            "container_size": c.container_size,
            "seal_no": c.seal_no,
            "order_type": c.order_type,
            "warehouse_hint": c.warehouse_hint,
            "customer_hint": c.customer_hint,
            "eta": (c.raw_fields or {}).get("eta"),
            "match_source": (c.raw_fields or {}).get("match_source") or c.match_method,
            "check_digit_valid": c.container_check_digit_valid,
            "validation_status": c.validation_status,
            "warnings": (c.raw_fields or {}).get("warnings", []),
            "canonical_record": (c.raw_fields or {}).get("canonical_record"),
        }
        for c in msg.container_jobs
    ]

    carrier_reply = db.scalar(
        select(BotReply.reply_text)
        .where(BotReply.message_id == msg.id)
        .order_by(BotReply.id.desc())
    )

    action_label = "DUPLICATE_MESSAGE" if is_duplicate else "PROCESSED_FIFO"

    # Chỉ gửi các tin đáp ứng đầy đủ các trường thông tin chính (processing_status == "processed")
    # Nếu thiếu hoặc sai, chuyển chờ duyệt và customer_notifications = []
    customer_notifications: list[dict[str, Any]] = []
    if msg.processing_status == "processed":
        for c in msg.container_jobs:
            stmt = (
                select(OutboundMessage)
                .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
                .where(
                    OutboundMessageItem.container_job_id == c.id,
                    OutboundMessage.status == "da_gui",
                )
            )
            out_msg = db.scalar(stmt)
            if out_msg:
                target_zg = db.get(ZaloGroup, out_msg.target_group_id)
                target_group_str = target_zg.zalo_group_id if target_zg else msg.group_id
                customer_notifications.append({
                    "target_group_id": target_group_str,
                    "message_text": out_msg.content,
                    "cont": c.container_no,
                    "shipping_id": f"SHP-{c.id}",
                    "send_status": "SENT",
                })

    return {
        "ok": True,
        "status": "DUPLICATE" if is_duplicate else "ENQUEUED_AND_PROCESSED_FIFO",
        "record_id": msg.id,
        "zalo_message_id": msg.zalo_message_id,
        "group_id": msg.group_id,
        "sender_id": msg.sender_id,
        "processing_status": msg.processing_status,
        "trucks_count": len(trucks_summary),
        "containers_count": len(containers_summary),
        "trucks": trucks_summary,
        "containers": containers_summary,
        "reply_to_carrier": carrier_reply,
        "data": {
            "id": msg.id,
            "msg_id": msg.zalo_message_id,
            "action": action_label,
            "processing_status": msg.processing_status,
            "total_vehicles": len(trucks_summary),
            "reply_to_carrier": carrier_reply,
            "customer_notifications": customer_notifications,
            "trucks": trucks_summary,
            "containers": containers_summary,
        },
    }
