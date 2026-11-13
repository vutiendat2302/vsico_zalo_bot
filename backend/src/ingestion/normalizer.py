"""Module Tiếp Nhận, Chuẩn Hóa & Chống Trùng Lặp Tin Nhắn (Ingestion & Normalization Layer).

Xử lý sự kiện Webhook đẩy sang từ `zca-js` (hỗ trợ cả tin nhắn trực tiếp 1-1
và tin nhắn trong Group Zalo, cũng như cả 2 định dạng payload lồng và phẳng):
1. Chuẩn hóa dữ liệu đầu vào (`zalo_message_id`, `group_id`, `sender_id`, `zalo_sent_at`).
3. Tự động khởi tạo/cập nhật thông tin nhóm hoặc hội thoại trực tiếp trong `zalo_groups`.
4. Lưu ngay lập tức bản ghi thô vào `zalo_messages` và đẩy vào hàng đợi `FIFOExtractionQueue`
   để bóc tách tuần tự theo nguyên tắc Vào Trước - Ra Trước (FIFO) thời gian thực.
"""

from datetime import datetime
from typing import Any, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.enums import GroupRole, MessageStatus, SendMode
from src.infrastructure.fifo_queue import fifo_queue
from src.infrastructure.models import ZaloGroup, ZaloMessage
from src.observability.logging import get_logger

logger = get_logger(__name__)


class WebhookIngestor:
    """Bộ tiếp nhận sự kiện tin nhắn Zalo thời gian thực và kích hoạt hàng đợi FIFO."""

    @classmethod
    def parse_timestamp(cls, raw_ts: Optional[Any]) -> Optional[datetime]:
        """Chuyển đổi giá trị thời gian từ Zalo (epoch milliseconds/seconds hoặc ISO-8601) sang `datetime`.

        Args:
            raw_ts (Optional[Any]): Giá trị thời gian thô từ payload Zalo.

        Returns:
            Optional[datetime]: Đối tượng `datetime` tương ứng hoặc None nếu không hợp lệ.
        """
        if raw_ts is None or raw_ts == "":
            return None
        try:
            if isinstance(raw_ts, (int, float)) or (isinstance(raw_ts, str) and raw_ts.strip().isdigit()):
                val = float(raw_ts)
                if val > 1e11:
                    val = val / 1000.0
                return datetime.fromtimestamp(val)
            if isinstance(raw_ts, str):
                cleaned = raw_ts.strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(cleaned)
                return dt.replace(tzinfo=None)
        except Exception:
            return None
        return None

    @classmethod
    def ingest_webhook_payload(
        cls,
        db: Session,
        payload_dict: dict[str, Any],
    ) -> tuple[ZaloMessage, bool]:
        """Tiếp nhận payload từ `zca-js`, lưu thô vào MySQL và thực thi bóc tách FIFO ngay lập tức.

        Hỗ trợ đồng thời:
        - Cấu trúc lồng từ `zca-js`: `sender: {id, name}`, `message: {msg_id, text}`
        - Cấu trúc phẳng từ API/Postman: `msg_id`, `sender_id`, `sender_name`, `text`

        Args:
            db (Session): Phiên làm việc SQLAlchemy.
            payload_dict (dict[str, Any]): Dữ liệu JSON nhận được từ endpoint `/webhook`.

        Returns:
            tuple[ZaloMessage, bool]: Cặp `(bản ghi ZaloMessage đã xử lý, is_duplicate)`.
        """
        nested_msg = payload_dict.get("message") or {}
        nested_sender = payload_dict.get("sender") or {}

        msg_id = str(
            payload_dict.get("msg_id")
            or nested_msg.get("msg_id")
            or f"auto_{uuid.uuid4().hex[:12]}"
        ).strip()

        sender_id = str(
            payload_dict.get("sender_id")
            or nested_sender.get("id")
            or "unknown_user"
        ).strip()

        sender_name = (
            payload_dict.get("sender_name")
            or nested_sender.get("name")
            or ""
        ).strip() or None

        raw_group_id = str(payload_dict.get("group_id") or "").strip()
        group_name = (payload_dict.get("group_name") or "").strip() or None
        quote_msg_id = (
            payload_dict.get("quote_msg_id")
            or nested_msg.get("quote_msg_id")
            or None
        )

        text = payload_dict.get("text")
        if text is None:
            text = payload_dict.get("message_text")
        if text is None:
            text = nested_msg.get("text") or nested_msg.get("message_text") or ""

        # Phân biệt tin nhắn nhắn trực tiếp (Direct 1-1) và tin nhắn nhắn trong Group Zalo
        if not raw_group_id:
            group_id = f"direct_{sender_id}"
            effective_group_name = group_name or f"Direct Chat - {sender_name or sender_id}"
            group_role = "DIRECT_CHAT"
        else:
            group_id = raw_group_id
            effective_group_name = group_name or f"Zalo Group {group_id}"
            group_role = (
                "DIRECT_CHAT"
                if group_id.startswith("direct_")
                else GroupRole.SOURCE.value
            )

        # 1. Kiểm tra chống trùng lặp (Deduplication) theo `zalo_message_id`
        existing_msg: Optional[ZaloMessage] = db.scalar(
            select(ZaloMessage).where(ZaloMessage.zalo_message_id == msg_id)
        )
        if existing_msg is not None:
            if existing_msg.processing_status in (
                MessageStatus.RECEIVED.value,
                MessageStatus.QUEUED.value,
            ):
                fifo_queue.enqueue(existing_msg.id)
                db.refresh(existing_msg)
            return existing_msg, True

        # 2. Tự động đăng ký hoặc cập nhật thông tin Nhóm / Hội thoại trong `zalo_groups`
        zalo_group = db.scalar(
            select(ZaloGroup).where(ZaloGroup.zalo_group_id == group_id)
        )
        is_mock_group = (
            group_id.startswith("test_")
            or group_id.startswith("pytest_")
            or "pytest_" in group_id
            or "test_" in group_id
            or (msg_id and (msg_id.startswith("test_") or msg_id.startswith("pytest_")))
            or (sender_id and (sender_id.startswith("test_") or sender_id.startswith("pytest_")))
        )
        if zalo_group is None:
            zalo_group = ZaloGroup(
                zalo_group_id=group_id,
                name=effective_group_name,
                group_role=group_role,
                send_mode=SendMode.AUTO.value,
                is_active=True,
                is_test=is_mock_group,
            )
            db.add(zalo_group)
            db.flush()
        elif group_name and zalo_group.name != group_name:
            zalo_group.name = group_name
            db.flush()

        # 3. Lưu ngay lập tức tin nhắn thô (raw message) vào bảng `zalo_messages`
        from src.infrastructure.ocr.paddle_client import PaddleOCRClient

        zalo_sent_at = cls.parse_timestamp(payload_dict.get("timestamp"))
        has_text = bool(text and text.strip())
        has_image = PaddleOCRClient.is_image_payload(payload_dict)

        if has_image:
            msg_type = "image"
        elif has_text:
            msg_type = "text"
        else:
            msg_type = "non_text"

        initial_status = (
            MessageStatus.QUEUED.value
            if (has_text or has_image)
            else MessageStatus.IGNORED_NON_TEXT.value
        )

        new_msg = ZaloMessage(
            zalo_message_id=msg_id,
            group_id=group_id,
            sender_id=sender_id,
            sender_name=sender_name,
            quote_msg_id=str(quote_msg_id) if quote_msg_id else None,
            message_type=msg_type,
            message_text=text,
            raw_payload=payload_dict,
            zalo_sent_at=zalo_sent_at,
            processing_status=initial_status,
        )
        db.add(new_msg)
        db.commit()
        db.refresh(new_msg)

        # 4. Đưa vào hàng đợi FIFO (Vào Trước - Ra Trước) và bóc tách ngay lập tức (Real-time)
        if has_text or has_image:
            fifo_queue.enqueue(new_msg.id)
            db.refresh(new_msg)

        return new_msg, False
