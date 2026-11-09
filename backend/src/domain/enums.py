"""Module Định Nghĩa Các Tập Hằng Số & Kiểu Liệt Kê Nghiệp Vụ (Domain Enums).

Thống nhất toàn bộ giá trị trạng thái trong hệ thống để tránh việc mỗi module tự đặt tên
trạng thái khác nhau khi ghi vào cơ sở dữ liệu MySQL.
"""

from enum import Enum


class MessageStatus(str, Enum):
    """Trạng thái xử lý của tin nhắn gốc trong bảng `zalo_messages`."""

    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    IGNORED_NON_TEXT = "bo_qua_anh"
    IGNORED_CHAT = "ignored_chat"
    FAILED = "failed"


class ValidationStatus(str, Enum):
    """Trạng thái kiểm tra tính hợp lệ của container trong bảng `container_jobs`."""

    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    NEEDS_REVIEW = "needs_review"


class RoutingStatus(str, Enum):
    """Trạng thái định tuyến nhóm nhận của container trong bảng `container_jobs`."""

    PENDING = "pending"
    RESOLVED = "resolved"
    NEEDS_REVIEW = "needs_review"
    SENT = "sent"


class TmsSyncStatus(str, Enum):
    """Trạng thái đồng bộ dữ liệu sang phần mềm PM TMS (`be-tms`)."""

    NOT_STARTED = "not_started"
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class OrderType(str, Enum):
    """Loại lệnh vận chuyển container (Đóng hàng xuất hoặc Trả hàng nhập)."""

    DONG = "load"
    TRA = "return"


class Intent(str, Enum):
    """Ý định của người gửi trong tin nhắn Zalo."""

    PARSE_TRUCK_INFO = "PARSE"
    UPDATE_REQUEST = "UPDATE_REQUEST"
    SUPPLEMENT = "SUPPLEMENT"
    CANCEL_REQUEST = "CANCEL_REQUEST"
    APPROVE_OUTBOUND = "APPROVE_OUTBOUND"
    EDIT_PENDING = "EDIT_PENDING"
    IGNORE_CHAT = "IGNORE_CHAT"
