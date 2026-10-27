from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class ZaloWebhookPayload:
    """Mô hình dữ liệu đại diện cho payload JSON thô của Zalo Webhook (Zalo Schema Isolation).

    Theo Quy tắc kiến trúc 1.2 (Cô lập Zalo Payload):
    Cấu trúc thô của Zalo chỉ được phép xuất hiện tại tầng giao tiếp API và Ingestion Normalizer.
    Từ tầng nghiệp vụ trở đi, toàn bộ hệ thống chỉ sử dụng mô hình nội bộ `InboundMessage`.

    Attributes:
        app_id (str): Mã ứng dụng Zalo OA gửi webhook.
        event_name (str): Tên loại sự kiện Zalo (ví dụ: 'user_send_text', 'user_send_image').
        group_id (str): Mã định danh nhóm chat Zalo nơi phát sinh sự kiện tin nhắn.
        sender (Dict[str, Any]): Thông tin đối tượng gửi tin (chứa 'id', 'name',...).
        timestamp (str): Dấu thời gian phát sinh sự kiện từ phía Zalo OA.
        message (Dict[str, Any]): Cấu trúc nội dung tin nhắn (chứa 'msg_id', 'text', 'attachments',...).
    """
    app_id: str
    event_name: str
    group_id: str
    sender: Dict[str, Any]
    timestamp: str
    message: Dict[str, Any]
