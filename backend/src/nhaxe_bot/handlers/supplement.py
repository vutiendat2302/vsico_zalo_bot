"""Module Xử Lý Bổ Sung Dữ Liệu (Supplement Use Case Handler).

Chịu trách nhiệm tiếp nhận các tin nhắn gửi số seal, số chì hoặc giờ đến
được bổ sung sau đó cho các chuyến xe đang ở trạng thái chờ (`HOLD_WAIT_SUPPLEMENT`).
"""

from typing import List, Dict, Any
from ..ingestion.models import InboundMessage
from ..parsing.fields.container import extract_containers
from .base import BaseHandler


class SupplementHandler(BaseHandler):
    """Use Case Handler xử lý thông tin bổ sung cho chuyến xe đang tạm giữ."""

    def handle(self, inbound: InboundMessage, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi nghiệp vụ tiếp nhận và gộp dữ liệu bổ sung.

        Args:
            inbound (InboundMessage): Thông điệp nội bộ từ Queue Worker.
            context (Dict[str, Any]): Dữ liệu ngữ cảnh bổ sung.

        Returns:
            List[Dict[str, Any]]: Bản ghi thông báo tiếp nhận bổ sung cho container.
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
            "action": "SUPPLEMENT",
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
            "admin_alert": False,
            "admin_message": None,
            "reason": f"Tiếp nhận thông tin bổ sung cho cont {target_cont}",
        }
        return [row]
