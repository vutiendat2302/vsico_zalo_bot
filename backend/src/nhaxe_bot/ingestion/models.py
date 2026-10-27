"""Module Định Nghĩa Dữ Liệu Tầng Tiếp Nhận (Ingestion Internal Models).

Chứa model dữ liệu nội bộ InboundMessage đại diện cho thông điệp đã được chuẩn hóa
từ cổng Webhook, độc lập hoàn toàn với cấu trúc payload thô của bên thứ ba (Zalo).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class InboundMessage:
    """Mô hình thông điệp tiếp nhận nội bộ (Internal Inbound Message).

    Được tạo ra tại tầng Ingestion sau khi bóc tách và chuẩn hóa từ Zalo Webhook Payload.
    Từ tầng này trở đi vào sâu trong hệ thống, mọi xử lý chỉ thao tác trên đối tượng này.

    Attributes:
        seq (int): Số thứ tự tuần tự của sự kiện trong phiên xử lý (bắt đầu từ 1).
        msg_id (str): Mã định danh duy nhất của tin nhắn (do Zalo cung cấp hoặc tự sinh).
        raw_text (str): Nội dung văn bản gốc của tin nhắn nhà xe.
        group_id (str): Mã định danh nhóm Zalo GMF nơi tin nhắn được gửi đến.
        sender_id (str): Mã định danh tài khoản người dùng Zalo đã gửi tin nhắn.
        event_name (str): Tên loại sự kiện Webhook (ví dụ: 'user_send_text').
        received_at (datetime): Thời điểm hệ thống tiếp nhận tin nhắn (chuẩn múi giờ GMT+7).
        carrier_id (Optional[str]): Mã nhà xe được phân giải từ group_id (ví dụ: 'NX01').
        is_valid (bool): Đánh dấu tin nhắn có hợp lệ để đẩy vào hàng đợi xử lý tiếp hay không.
        drop_reason (Optional[str]): Lý do từ chối tin nhắn nếu is_valid = False.
        action (Optional[str]): Hành động sơ bộ được gán khi bị từ chối sớm (ví dụ: 'IGNORE_NON_TEXT').
        admin_alert (bool): Cờ cảnh báo Điều hành Vận tải nếu phát hiện người lạ gửi tin.
        admin_message (Optional[str]): Nội dung cảnh báo người lạ trong nhóm nhà xe.
        junk_verdict (Optional[str]): Kết quả phân loại rác ('JUNK', 'SUSPECT', 'CANDIDATE').
        junk_reason (Optional[str]): Diễn giải lý do phân loại rác.
        request_id (Optional[str]): Mã định danh yêu cầu HTTP liên kết.
        timestamp (Optional[str]): Chuỗi mốc thời gian ISO hoặc epoch của tin nhắn gốc.
        quote_msg_id (Optional[str]): ID của tin nhắn được trích dẫn/reply nếu có.
        sender_name (Optional[str]): Tên hiển thị của người gửi tin nhắn.
    """

    seq: int
    msg_id: str
    raw_text: str
    group_id: str
    sender_id: str
    event_name: str
    received_at: datetime
    carrier_id: Optional[str] = None
    is_valid: bool = True
    drop_reason: Optional[str] = None
    action: Optional[str] = None
    admin_alert: bool = False
    admin_message: Optional[str] = None
    junk_verdict: Optional[str] = None
    junk_reason: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: Optional[str] = None
    quote_msg_id: Optional[str] = None
    sender_name: Optional[str] = None
