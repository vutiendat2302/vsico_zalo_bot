"""Module Định nghĩa Các Kiểu Dữ Liệu Liệt Kê (Domain Enums).

Chứa toàn bộ các hằng số định danh nghiệp vụ thuần túy của hệ thống nhaxe-bot,
bao gồm phân loại ý định (Intent), trạng thái chuyến xe (TripStatus), trạng thái
gửi tin (SendStatus), loại đơn hàng (OrderType) và kết quả khớp đơn (MatchStatus).
"""

from enum import Enum


class Intent(str, Enum):
    """Liệt kê các ý định (Intents) nhận diện từ tin nhắn của nhà xe.

    Hệ thống phân cấp thứ tự ưu tiên xử lý:
    CANCEL_REQUEST > UPDATE_REQUEST > ASK_WHICH_CONT > SUPPLEMENT > PARSE > IGNORE_CHAT.
    """

    PARSE = "PARSE"
    """Tin nhắn chứa thông tin điều phối xe mới hợp lệ cần bóc tách dữ liệu."""

    UPDATE_REQUEST = "UPDATE_REQUEST"
    """Tin nhắn yêu cầu đổi tài xế, đổi xe hoặc sửa số seal của chuyến đã gửi."""

    CANCEL_REQUEST = "CANCEL_REQUEST"
    """Tin nhắn báo hủy chuyến do xe hỏng hoặc sự cố bất khả kháng."""

    SUPPLEMENT = "SUPPLEMENT"
    """Tin nhắn gửi bổ sung thông tin còn thiếu (số seal, giờ đến) cho chuyến đang chờ."""

    ASK_WHICH_CONT = "ASK_WHICH_CONT"
    """Tin nhắn yêu cầu đổi thông tin nhưng không nêu rõ số container hoặc biển số xe."""

    MANUAL_REVIEW = "MANUAL_REVIEW"
    """Tin nhắn báo cáo tiến độ (đã giao xong, đang vào kho) cần người xem xét."""

    IGNORE_CHAT = "IGNORE_CHAT"
    """Tin nhắn chào hỏi, cảm ơn, giao tiếp thông thường không liên quan đến chuyến xe."""

    DUPLICATE_MESSAGE = "DUPLICATE_MESSAGE"
    """Tin nhắn bị trùng lặp mã định danh msg_id đã xử lý trước đó."""

    IGNORE_UNKNOWN_SENDER = "IGNORE_UNKNOWN_SENDER"
    """Tin nhắn gửi từ tài khoản người dùng lạ chưa được nhà xe ủy quyền."""

    IGNORE_UNKNOWN_GROUP = "IGNORE_UNKNOWN_GROUP"
    """Tin nhắn nhận từ nhóm Zalo chưa đăng ký trong danh mục nhà xe."""

    IGNORE_NON_TEXT = "IGNORE_NON_TEXT"
    """Sự kiện webhook không phải văn bản (ảnh chụp, sticker, tệp đính kèm)."""

    ERROR = "ERROR"
    """Lỗi phát sinh ngoài ý muốn trong quá trình xử lý tin nhắn."""


class TripStatus(str, Enum):
    """Trạng thái tính hợp lệ nội bộ của chuyến xe sau bước validation."""

    READY = "ready"
    """Chuyến xe có đầy đủ các trường dữ liệu hợp lệ và sẵn sàng gửi khách."""

    NEED_SUPPLEMENT = "need_supplement"
    """Chuyến xe còn thiếu ít nhất một trường bắt buộc (ví dụ: thiếu seal hoặc giờ đến)."""

    NEED_ADMIN = "need_admin"
    """Chuyến xe gặp lỗi nghiệp vụ nghiêm trọng (sai nhà xe, cont không có trong kế hoạch)."""


class SendStatus(str, Enum):
    """Trạng thái kết xuất thông báo gửi đi (Outbound Sending Status)."""

    SENT_DRY_RUN = "SENT_DRY_RUN"
    """Đã soạn thông báo thành công và ghi nhận gửi vào nhóm khách hàng (mô phỏng)."""

    SENT_DRY_RUN_UPDATE = "SENT_DRY_RUN_UPDATE"
    """Đã soạn và gửi thông báo cập nhật thay đổi tài xế/biển số cho khách hàng."""

    HOLD_WAIT_SUPPLEMENT = "HOLD_WAIT_SUPPLEMENT"
    """Tạm giữ chuyến xe, không gửi khách và tạo tin nhắn yêu cầu nhà xe bổ sung."""

    HOLD_ADMIN = "HOLD_ADMIN"
    """Tạm giữ chuyến xe và chuyển cảnh báo cho Điều hành Vận tải (ĐHVT) can thiệp."""

    DEFER_PHASE2_DONG = "DEFER_PHASE2_DONG"
    """Lệnh đóng hàng, ghi nhận và tạm hoãn xử lý tự động trong Giai đoạn 1."""

    SKIPPED_NO_CHANGE = "SKIPPED_NO_CHANGE"
    """Bỏ qua việc gửi tin do nhà xe nhắn lại thông tin y hệt bản đã gửi trước đó."""


class OrderType(str, Enum):
    """Phân loại hướng luân chuyển container."""

    TRA = "tra"
    """Lệnh trả container hàng hoặc rỗng về kho/cảng."""

    DONG = "dong"
    """Lệnh bốc đóng hàng vào container."""


class MatchStatus(str, Enum):
    """Kết quả đối chiếu container giữa tin nhắn nhà xe và bảng Shipping của VSICO."""

    MATCH = "MATCH"
    """Tìm thấy container trong bảng Shipping và đúng nhà xe được phân công."""

    NOT_FOUND = "NOT_FOUND"
    """Số container không tồn tại trong danh mục kế hoạch vận chuyển."""

    WRONG_CARRIER = "WRONG_CARRIER"
    """Container có trong bảng Shipping nhưng được phân công cho đơn vị vận tải khác."""
