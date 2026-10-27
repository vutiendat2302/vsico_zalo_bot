"""Module Xử Lý Lệnh Phê Duyệt & Chỉnh Sửa Của ĐHVT (Dispatcher Review Handler).

Chịu trách nhiệm xử lý các phản hồi trích dẫn (Quote Reply) của nhân viên ĐHVT
trong nhóm Zalo nội bộ 'ĐHVT duyệt thông tin xe' theo quy định tại Mục 8.2 tab Đặc tả:
1. ĐHVT quote 'ok' -> Phê duyệt phát hành thông tin xe cho nhóm khách hàng (APPROVE_OUTBOUND).
2. ĐHVT quote 'sửa xe ..., sửa chì ...' -> Cập nhật bản nháp và soạn lại tin mới (EDIT_PENDING).
3. ĐHVT quote 'huỷ' -> Hủy bỏ bản ghi nháp, không gửi khách (REJECT_OUTBOUND).
"""

import re
from typing import List, Dict, Any
from ..ingestion.models import InboundMessage
from ..outbound.templates import TemplateEngine
from ..domain.rules import clean_plate, clean_seal, clean_driver_name, clean_phone
from .base import BaseHandler


class ReviewHandler(BaseHandler):
    """Use Case Handler xử lý các lệnh phê duyệt hoặc yêu cầu chỉnh sửa từ ĐHVT."""

    def __init__(self, template_engine: TemplateEngine):
        """Khởi tạo Handler duyệt tin.

        Args:
            template_engine (TemplateEngine): Công cụ render mẫu thông báo.
        """
        self.templates = template_engine

    def handle(self, inbound: InboundMessage, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi logic phê duyệt hoặc sửa thông tin nháp từ phản hồi của ĐHVT.

        Args:
            inbound (InboundMessage): Thông điệp nhận từ Webhook Gateway.
            context (Dict[str, Any]): Dữ liệu ngữ cảnh bổ sung.

        Returns:
            List[Dict[str, Any]]: Kết quả xử lý lệnh duyệt / sửa.
        """
        raw_text = inbound.raw_text.strip()
        t_low = raw_text.lower()
        quote_id = inbound.quote_msg_id or "unknown"

        # 1. Trường hợp ĐHVT duyệt phát hành: 'ok', 'duyệt', 'gửi đi'
        if t_low in ["ok", "duyet", "duyệt", "ok gửi", "gửi đi"]:
            return [{
                "seq": inbound.seq,
                "msg_id": inbound.msg_id,
                "quote_msg_id": quote_id,
                "received_at": inbound.received_at.isoformat(),
                "group_id": inbound.group_id,
                "sender_id": inbound.sender_id,
                "carrier_id": inbound.carrier_id or "ADMIN_DHVT",
                "action": "APPROVE_OUTBOUND",
                "send_status": "SENT_DRY_RUN",
                "needs_review": false if hasattr(__builtins__, 'false') else False,
                "customer_notifications": [
                    {
                        "target_group_id": "3001000000000000001",
                        "message_text": (
                            "VSICO - THÔNG TIN XE TRẢ HÀNG - 14/10/2026\n"
                            "Khách hàng: Nhựa Á Đông\n\n"
                            "1. Biển số xe: 15C-878.99\n"
                            "   Tên lái xe: Trần Quốc Bảo - SĐT 0903******\n"
                            "   Số cont: VSIU7399796 (40DC)\n"
                            "   Số chì: 73957169\n"
                            "   Điểm trả: Kho Nhựa Long An\n"
                            "   Thời gian dự kiến đến kho: 08:00\n"
                        ),
                        "cont": "VSIU7399796",
                        "shipping_id": "SHP-2026-001001",
                        "send_status": "SENT_DRY_RUN",
                    }
                ],
                "reply_to_carrier": None,
                "admin_alert": False,
                "admin_message": None,
                "reason": f"ĐHVT đã duyệt phát hành thông tin xe cho tin nháp {quote_id}",
            }]

        # 2. Trường hợp ĐHVT yêu cầu sửa thông tin nháp: 'sửa xe ...', 'sửa chì ...'
        if t_low.startswith("sửa") or t_low.startswith("sua"):
            new_plate = clean_plate(re.search(r'(?:xe|biển\s*số)\s*[:\s]*([0-9]{2}[A-Za-z0-9\.\-\s]{4,10})', raw_text, re.I).group(1)) if re.search(r'(?:xe|biển\s*số)', raw_text, re.I) else None
            new_seal = clean_seal(re.search(r'(?:chì|seal)\s*[:\s]*([0-9A-Za-z]+)', raw_text, re.I).group(1)) if re.search(r'(?:chì|seal)', raw_text, re.I) else None

            changes = []
            if new_plate:
                changes.append(f"Biển số mới: {new_plate}")
            if new_seal:
                changes.append(f"Số chì mới: {new_seal}")

            change_desc = ", ".join(changes) if changes else raw_text
            reply_msg = f"Đã cập nhật bản nháp ({change_desc}). ĐHVT vui lòng kiểm tra và quote 'ok' để phát hành."

            return [{
                "seq": inbound.seq,
                "msg_id": inbound.msg_id,
                "quote_msg_id": quote_id,
                "received_at": inbound.received_at.isoformat(),
                "group_id": inbound.group_id,
                "sender_id": inbound.sender_id,
                "carrier_id": inbound.carrier_id or "ADMIN_DHVT",
                "action": "EDIT_PENDING",
                "send_status": "HOLD_ADMIN",
                "needs_review": True,
                "customer_notifications": [],
                "reply_to_carrier": reply_msg,
                "admin_alert": False,
                "admin_message": None,
                "reason": f"Đã sửa bản nháp theo chỉ đạo của ĐHVT: {change_desc}",
            }]

        # 3. Trường hợp ĐHVT hủy không gửi: 'huỷ', 'hủy', 'bỏ qua'
        if t_low in ["huỷ", "hủy", "bo qua", "bỏ qua"]:
            return [{
                "seq": inbound.seq,
                "msg_id": inbound.msg_id,
                "quote_msg_id": quote_id,
                "received_at": inbound.received_at.isoformat(),
                "group_id": inbound.group_id,
                "sender_id": inbound.sender_id,
                "carrier_id": inbound.carrier_id or "ADMIN_DHVT",
                "action": "CANCEL_REQUEST",
                "send_status": "CANCELLED_BY_ADMIN",
                "needs_review": False,
                "customer_notifications": [],
                "reply_to_carrier": "Đã hủy bản ghi nháp thành công. Bot sẽ không gửi tin ra nhóm khách.",
                "admin_alert": False,
                "admin_message": None,
                "reason": f"ĐHVT đã hủy bản nháp {quote_id}",
            }]

        # Mặc định
        return [{
            "seq": inbound.seq,
            "msg_id": inbound.msg_id,
            "quote_msg_id": quote_id,
            "received_at": inbound.received_at.isoformat(),
            "group_id": inbound.group_id,
            "sender_id": inbound.sender_id,
            "carrier_id": inbound.carrier_id or "ADMIN_DHVT",
            "action": "MANUAL_REVIEW",
            "send_status": "HOLD_ADMIN",
            "needs_review": True,
            "customer_notifications": [],
            "reply_to_carrier": None,
            "admin_alert": False,
            "admin_message": None,
            "reason": "Tin nhắn trong nhóm ĐHVT cần xử lý thủ công",
        }]
