"""Module Xử Lý Tin Nhắn Chưa Xác Định & Chat Thường (Unknown & Chat Use Case Handler).

Xử lý các tình huống:
- Tin nhắn chào hỏi thông thường (`IGNORE_CHAT`): Im lặng bỏ qua.
- Tin nhắn yêu cầu đổi nhưng không rõ cont (`ASK_WHICH_CONT`): Tự động hỏi lại nhà xe.
- Tin nhắn cập nhật tiến độ giao nhận (`MANUAL_REVIEW`): Chuyển Admin xem xét.
- Tin nhắn bị từ chối từ tầng Ingestion (người lạ, nhóm lạ, không phải text, trùng tin).
"""

from typing import List, Dict, Any
from ..ingestion.models import InboundMessage
from .base import BaseHandler


class UnknownHandler(BaseHandler):
    """Use Case Handler xử lý các tin nhắn không rõ intent, chat thông thường hoặc hỏi lại nhà xe."""

    def handle(self, inbound: InboundMessage, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi nghiệp vụ phản hồi cho các loại tin nhắn ngoại lệ / không phải báo xe.

        Args:
            inbound (InboundMessage): Thông điệp nội bộ cần xử lý.
            context (Dict[str, Any]): Ngữ cảnh chứa action phân loại từ Router.

        Returns:
            List[Dict[str, Any]]: Bản ghi kết quả định tuyến.
        """
        action = inbound.action or context.get("action", "IGNORE_CHAT")
        admin_alert = inbound.admin_alert
        admin_message = inbound.admin_message
        reply_to_carrier = None
        reason = None

        if action == "ASK_WHICH_CONT":
            admin_alert = True
            admin_message = (
                "Nhà xe yêu cầu đổi/sửa thông tin nhưng không nêu rõ số cont hoặc biển số xe"
            )
            reply_to_carrier = "Vui lòng cho biết bạn muốn đổi thông tin cho số cont hoặc biển số nào?"
            reason = "Hỏi lại nhà xe số cont cần cập nhật"
        elif action == "MANUAL_REVIEW":
            reason = "Tin cập nhật tiến độ vận hành, chuyển Admin xem xét"
        elif action == "IGNORE_CHAT":
            reason = "Tin nhắn trao đổi thông thường, bỏ qua không phản hồi"
        elif action == "DUPLICATE_MESSAGE":
            reason = inbound.drop_reason or "Bỏ qua do trùng lặp msg_id"
        else:
            reason = inbound.drop_reason or "Bỏ qua sự kiện không xử lý"

        row: Dict[str, Any] = {
            "seq": inbound.seq,
            "msg_id": inbound.msg_id,
            "received_at": inbound.received_at.isoformat(),
            "group_id": inbound.group_id,
            "sender_id": inbound.sender_id,
            "carrier_id": inbound.carrier_id or "UNKNOWN",
            "action": action,
            "xe_index": None,
            "loai_hint": None,
            "cont": None,
            "seal": None,
            "bien_so": None,
            "tai_xe": None,
            "sdt": None,
            "gio_den": None,
            "warnings": [],
            "status": None,
            "in_shipping": None,
            "shipping_id": None,
            "khach_hang_id": None,
            "ten_khach_hang": None,
            "zalo_group_id_gui": None,
            "send_status": None,
            "notification_text": None,
            "reply_to_carrier": reply_to_carrier,
            "admin_alert": admin_alert,
            "admin_message": admin_message,
            "reason": reason,
        }
        return [row]
