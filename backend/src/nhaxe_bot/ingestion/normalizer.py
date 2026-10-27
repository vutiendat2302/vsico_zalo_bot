"""Module Chuẩn Hóa Payload Tiếp Nhận (Ingestion Normalizer).

Đóng vai trò Adapter chuyển đổi cấu trúc payload thô của bên thứ ba (Zalo Webhook)
thành đối tượng chuẩn hóa nội bộ `InboundMessage`. Đảm bảo cô lập dữ liệu ngoại vi
ngay tại tầng tiếp nhận, không cho cấu trúc thô của Zalo lọt vào tầng nghiệp vụ.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from ..config.settings import TZ_VN
from ..domain.models import Carrier
from .models import InboundMessage
from .deduplicator import Deduplicator
from .filters import IngestionFilter


class IngestionNormalizer:
    """Bộ chuyển đổi và chuẩn hóa dữ liệu tiếp nhận từ Webhook sang InboundMessage."""

    def __init__(self, carriers_map: Dict[str, Carrier], deduplicator: Deduplicator):
        """Khởi tạo bộ chuẩn hóa tiếp nhận.

        Args:
            carriers_map (Dict[str, Carrier]): Danh bạ ánh xạ thông tin các đơn vị vận tải.
            deduplicator (Deduplicator): Bộ lọc chống trùng lặp thông điệp theo msg_id.
        """
        self.carriers_map = carriers_map
        self.deduplicator = deduplicator

    def normalize(self, seq: int, raw_payload: Dict[str, Any]) -> InboundMessage:
        """Chuyển đổi một payload thô của sự kiện Webhook Zalo thành đối tượng InboundMessage.

        Quy trình xử lý tuần tự 3 bước kiểm tra:
        1. **Kiểm tra loại sự kiện**: Nếu không phải 'user_send_text' (ví dụ: ảnh, sticker),
           đánh dấu `is_valid = False` với hành động 'IGNORE_NON_TEXT'.
        2. **Kiểm tra chống trùng**: Kiểm tra `msg_id` qua Deduplicator. Nếu trùng lặp,
           đánh dấu `is_valid = False` với hành động 'DUPLICATE_MESSAGE'.
        3. **Xác thực an ninh**: Phân giải mã nhà xe và kiểm tra người gửi ủy quyền. Nếu không
           hợp lệ, đánh dấu `is_valid = False` kèm cờ cảnh báo `admin_alert` (nếu là người lạ).

        Args:
            seq (int): Số thứ tự của thông điệp trong phiên xử lý.
            raw_payload (Dict[str, Any]): Dữ liệu JSON thô nhận từ máy chủ Zalo OA.

        Returns:
            InboundMessage: Đối tượng thông điệp nội bộ hoàn chỉnh đã qua xác thực.
        """
        event_name = raw_payload.get("event_name", "user_send_text")
        group_id = str(raw_payload.get("group_id", ""))
        sender_info = raw_payload.get("sender", {})
        sender_id = str(sender_info.get("id", ""))
        sender_name = str(sender_info.get("name", ""))
        message_data = raw_payload.get("message", {})
        msg_id = str(message_data.get("msg_id", f"gen_{seq}"))
        raw_text = str(message_data.get("text", "")).strip()
        quote_msg_id = (
            raw_payload.get("quote_msg_id")
            or message_data.get("quote_msg_id")
            or str(message_data.get("quote", {}).get("globalMsgId", ""))
            or None
        )

        # Chuẩn hóa thời gian nhận tin từ timestamp epoch millisecond sang GMT+7
        ts_epoch = raw_payload.get("timestamp")
        try:
            received_at = (
                datetime.fromtimestamp(int(ts_epoch) / 1000.0, TZ_VN)
                if ts_epoch
                else datetime.now(TZ_VN)
            )
        except Exception:
            received_at = datetime.now(TZ_VN)

        # 1. Kiểm tra sự kiện hỗ trợ (chỉ nhận tin nhắn văn bản)
        if not IngestionFilter.check_event_supported(event_name):
            return InboundMessage(
                seq=seq,
                msg_id=msg_id,
                raw_text=raw_text,
                group_id=group_id,
                sender_id=sender_id,
                event_name=event_name,
                received_at=received_at,
                is_valid=False,
                action="IGNORE_NON_TEXT",
                drop_reason="Sự kiện không phải tin nhắn văn bản (user_send_text)",
            )

        # 2. Kiểm tra trùng lặp msg_id (Idempotency)
        if self.deduplicator.is_duplicate(msg_id):
            return InboundMessage(
                seq=seq,
                msg_id=msg_id,
                raw_text=raw_text,
                group_id=group_id,
                sender_id=sender_id,
                event_name=event_name,
                received_at=received_at,
                is_valid=False,
                action="DUPLICATE_MESSAGE",
                drop_reason=f"Bỏ qua do trùng lặp msg_id ({msg_id})",
            )

        # 3. Kiểm tra nhà xe & tài khoản người gửi ủy quyền
        carrier_id, reject_action, reject_reason = IngestionFilter.resolve_carrier(
            group_id, sender_id, self.carriers_map
        )
        if reject_action:
            is_unknown_sender = reject_action == "IGNORE_UNKNOWN_SENDER"
            return InboundMessage(
                seq=seq,
                msg_id=msg_id,
                raw_text=raw_text,
                group_id=group_id,
                sender_id=sender_id,
                event_name=event_name,
                received_at=received_at,
                is_valid=False,
                carrier_id=carrier_id,
                action=reject_action,
                drop_reason=reject_reason,
                admin_alert=is_unknown_sender,
                admin_message=(
                    f"Cảnh báo người lạ gửi tin trong nhóm {group_id}: {raw_text}"
                    if is_unknown_sender
                    else None
                ),
            )

        # Đánh dấu msg_id đã được duyệt thành công để chống trùng cho các tin sau
        self.deduplicator.mark_seen(msg_id)

        # Thông điệp hợp lệ sẵn sàng đẩy vào hàng đợi
        return InboundMessage(
            seq=seq,
            msg_id=msg_id,
            raw_text=raw_text,
            group_id=group_id,
            sender_id=sender_id,
            event_name=event_name,
            received_at=received_at,
            carrier_id=carrier_id,
            is_valid=True,
            timestamp=str(ts_epoch) if ts_epoch else received_at.isoformat(),
            quote_msg_id=quote_msg_id,
            sender_name=sender_name,
        )
