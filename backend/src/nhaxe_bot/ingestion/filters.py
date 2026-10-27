"""Module Bộ Lọc Cửa Ngõ Tiếp Nhận (Ingestion Security & Event Filters).

Thực hiện thẩm định sơ bộ các sự kiện gửi đến webhook:
- Kiểm tra loại sự kiện có được hệ thống hỗ trợ không (chỉ nhận text).
- Phân giải nhóm Zalo sang đơn vị vận tải (Carrier ID).
- Xác thực an ninh: Kiểm tra người gửi có nằm trong danh sách nhân sự được ủy quyền của nhà xe không.
"""

from typing import Dict, Any, Tuple, Optional
from ..domain.models import Carrier


class IngestionFilter:
    """Bộ lọc bảo vệ và phân giải ngữ cảnh tại cửa ngõ tiếp nhận Webhook."""

    @staticmethod
    def check_event_supported(event_name: str) -> bool:
        """Kiểm tra xem loại sự kiện từ Zalo Webhook có được hỗ trợ xử lý hay không.

        Args:
            event_name (str): Tên sự kiện webhook (ví dụ: 'user_send_text', 'user_send_image').

        Returns:
            bool: True nếu là tin nhắn văn bản ('user_send_text'), False đối với hình ảnh/file.
        """
        return event_name == "user_send_text"

    @staticmethod
    def resolve_carrier(
        group_id: str,
        sender_id: str,
        carriers_map: Dict[str, Carrier],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Phân giải mã nhà xe từ group_id và xác thực danh tính người gửi (sender_id).

        Quy trình kiểm tra:
        1. Tìm kiếm xem `group_id` có thuộc danh bạ nhóm Zalo của nhà xe nào không.
           - Nếu không tìm thấy: Trả về hành động từ chối 'IGNORE_UNKNOWN_GROUP'.
        2. Nếu tìm thấy nhà xe, kiểm tra xem `sender_id` có nằm trong danh sách nhân sự
           được ủy quyền (`sender_ids`) của nhà xe đó không.
           - Nếu có danh sách ủy quyền nhưng `sender_id` không khớp: Trả về 'IGNORE_UNKNOWN_SENDER'.
        3. Nếu hợp lệ: Trả về mã nhà xe tương ứng.

        Args:
            group_id (str): Mã định danh nhóm Zalo nhận tin nhắn.
            sender_id (str): Mã định danh tài khoản Zalo của người gửi tin.
            carriers_map (Dict[str, Carrier]): Danh bạ metadata các nhà xe đối tác của VSICO.

        Returns:
            Tuple[Optional[str], Optional[str], Optional[str]]:
                - carrier_id (Optional[str]): Mã nhà xe nếu hợp lệ (ví dụ: 'NX01'), ngược lại None.
                - reject_action (Optional[str]): Mã hành động từ chối nếu bị chặn ('IGNORE_UNKNOWN_GROUP', 'IGNORE_UNKNOWN_SENDER').
                - reject_reason (Optional[str]): Thông điệp giải thích lý do từ chối.
        """
        matched_carrier: Optional[Carrier] = None
        for c in carriers_map.values():
            if c.group_id == group_id:
                matched_carrier = c
                break

        # Trường hợp 1: Nhóm Zalo chưa được đăng ký trong hệ thống
        if not matched_carrier:
            return None, "IGNORE_UNKNOWN_GROUP", f"Nhóm Zalo {group_id} chưa được đăng ký trong hệ thống"

        # Trường hợp 2: Tài khoản người gửi không nằm trong danh sách ủy quyền của nhà xe
        if matched_carrier.sender_ids and sender_id not in matched_carrier.sender_ids:
            return (
                None,
                "IGNORE_UNKNOWN_SENDER",
                f"Người gửi {sender_id} không thuộc danh sách ủy quyền của {matched_carrier.carrier_id}",
            )

        # Trường hợp 3: Hợp lệ hoàn toàn
        return matched_carrier.carrier_id, None, None
