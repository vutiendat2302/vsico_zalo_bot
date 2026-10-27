"""Module Xử Lý Hủy Chuyến Xe (Cancel Trip Use Case Handler).

Chịu trách nhiệm tiếp nhận và xử lý các tin nhắn báo hủy chuyến từ nhà xe:
- Trích xuất số container bị hủy (nếu có).
- Kích hoạt chuông cảnh báo khẩn cấp tới Điều hành Vận tải (`admin_alert: True`).
- Ghi nhận thông điệp cảnh báo (`admin_message`) để hiển thị trực tiếp trên Dashboard TMS.
"""

from typing import List, Dict, Any
from ..ingestion.models import InboundMessage
from ..parsing.fields.container import extract_containers
from .base import BaseHandler


class CancelTripHandler(BaseHandler):
    """Use Case Handler xử lý yêu cầu hủy chuyến xe từ nhà xe."""

    def handle(self, inbound: InboundMessage, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi nghiệp vụ tiếp nhận yêu cầu hủy chuyến và báo động ĐHVT.

        Args:
            inbound (InboundMessage): Thông điệp nội bộ từ Queue Worker.
            context (Dict[str, Any]): Dữ liệu ngữ cảnh bổ sung.

        Returns:
            List[Dict[str, Any]]: Bản ghi thông báo hủy chuyến kèm cờ admin_alert = True.
        """
        conts = extract_containers(inbound.raw_text)
        target_cont = conts[0] if conts else None

        row: Dict[str, Any] = {
            "seq": inbound.seq,
            "msg_id": inbound.msg_id,
            "received_at": inbound.received_at.isoformat(),
            "group_id": inbound.group_id,
            "sender_id": inbound.sender_id,
            "carrier_id": inbound.carrier_id or "UNKNOWN",
            "action": "CANCEL_REQUEST",
            "xe_index": None,
            "loai_hint": None,
            "cont": target_cont,
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
            "reply_to_carrier": None,
            "admin_alert": True,
            "admin_message": f"Nhà xe yêu cầu hủy chuyến: {inbound.raw_text}",
            "reason": "Yêu cầu hủy chuyến xe, chuyển Admin xử lý",
        }
        return [row]
