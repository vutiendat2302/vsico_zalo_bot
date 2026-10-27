"""Module Ngoại Lệ Hệ Thống & Miền Nghiệp Vụ (System & Domain Exceptions).

Định nghĩa hệ thống phân cấp ngoại lệ CarrierBotError và các mã lỗi chuẩn:
- E1xx: Lỗi đầu vào (Chữ ký không hợp lệ E100, Schema không hợp lệ E101).
- E2xx: Lỗi dữ liệu nghiệp vụ (Đọc kế hoạch shipping E200, Không tìm thấy cont E201).
- E3xx: Lỗi gửi thông báo ngoại vi (Gửi Zalo thất bại E300).
- E4xx: Lỗi nghiệp vụ miền (Validation container, nhà xe không khớp E422).
- E999: Lỗi nội bộ không lường trước.
"""

from typing import Optional


class CarrierBotError(Exception):
    """Lớp ngoại lệ cơ sở cho toàn bộ hệ thống nhaxe-bot.

    Attributes:
        code (str): Mã lỗi định danh theo chuẩn E... (ví dụ: 'E100', 'E200', 'E999').
        message (str): Mô tả chi tiết nguyên nhân phát sinh lỗi.
        retryable (bool): Cờ đánh dấu lỗi có thể thử lại an toàn (Idempotent Retry) hay không.
        http_status (int): Mã trạng thái HTTP tương ứng khi phản hồi REST API.
    """

    def __init__(
        self,
        code: str = "E999",
        message: str = "Lỗi hệ thống ngoài dự kiến",
        retryable: bool = False,
        http_status: int = 500,
    ) -> None:
        """Khởi tạo ngoại lệ CarrierBotError.

        Args:
            code (str, optional): Mã lỗi định danh. Mặc định là 'E999'.
            message (str, optional): Thông điệp mô tả lỗi.
            retryable (bool, optional): Khả năng thử lại. Mặc định là False.
            http_status (int, optional): Mã trạng thái HTTP. Mặc định là 500.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status


# ============================================================================
# NHÓM E1xx: LỖI ĐẦU VÀO (AUTHENTICATION / SCHEMA / INPUT)
# ============================================================================


class InvalidSignatureError(CarrierBotError):
    """Mã E100: Chữ ký số Zalo bảo mật không hợp lệ hoặc thiếu trong request header."""

    def __init__(self, message: str = "Chữ ký bảo mật không hợp lệ"):
        """Khởi tạo lỗi chữ ký sai với mã HTTP 401."""
        super().__init__(
            code="E100",
            message=message,
            retryable=False,
            http_status=401,
        )


class InvalidSchemaError(CarrierBotError):
    """Mã E101: Dữ liệu payload HTTP không đúng schema hoặc thiếu các trường bắt buộc."""

    def __init__(self, message: str = "Payload JSON không đúng định dạng schema bắt buộc"):
        """Khởi tạo lỗi schema sai với mã HTTP 400."""
        super().__init__(
            code="E101",
            message=message,
            retryable=False,
            http_status=400,
        )


# ============================================================================
# NHÓM E2xx: LỖI DỮ LIỆU & KẾ HOẠCH VẬN CHUYỂN (SHIPPING / DATA INTEGRITY)
# ============================================================================


class ShippingDataError(CarrierBotError):
    """Mã E200: Lỗi đọc tệp dữ liệu, sai định dạng file CSV hoặc hỏng cấu trúc kế hoạch shipping."""

    def __init__(self, message: str = "Lỗi nạp hoặc xử lý dữ liệu kế hoạch shipping"):
        """Khởi tạo lỗi kế hoạch shipping với mã HTTP 422."""
        super().__init__(
            code="E200",
            message=message,
            retryable=False,
            http_status=422,
        )


class ShippingNotFoundError(CarrierBotError):
    """Mã E201: Số container không tìm thấy trong kế hoạch shipping đã nạp."""

    def __init__(self, message: str = "Không tìm thấy thông tin container trong kế hoạch"):
        """Khởi tạo lỗi không tìm thấy đơn shipping với mã HTTP 422."""
        super().__init__(
            code="E201",
            message=message,
            retryable=False,
            http_status=422,
        )


# ============================================================================
# NHÓM E3xx: LỖI GỬI THÔNG BÁO NGOẠI VI (OUTBOUND / ZALO DELIVERY)
# ============================================================================


class OutboundSendError(CarrierBotError):
    """Mã E300: Lỗi gửi tin nhắn qua kênh Zalo OpenAPI sau khi đã thử lại tối đa."""

    def __init__(self, message: str = "Lỗi kết nối hoặc gửi thông báo qua kênh Zalo OpenAPI"):
        """Khởi tạo lỗi gửi Zalo với mã HTTP 500 và đánh dấu retryable=True."""
        super().__init__(
            code="E300",
            message=message,
            retryable=True,
            http_status=500,
        )


# ============================================================================
# NHÓM E4xx / DOMAIN ERROR: LỖI NGHIỆP VỤ MIỀN (BUSINESS VALIDATION ERRORS)
# ============================================================================


class DomainError(CarrierBotError):
    """Lớp ngoại lệ cơ sở cho tất cả lỗi thuộc miền nghiệp vụ nhaxe-bot."""

    def __init__(self, message: str = "Lỗi nghiệp vụ xử lý chuyến xe"):
        """Khởi tạo lỗi nghiệp vụ với mã E422 và HTTP 422."""
        super().__init__(
            code="E422",
            message=message,
            retryable=False,
            http_status=422,
        )


class ContainerValidationError(DomainError):
    """Ngoại lệ phát sinh khi số container không đúng định dạng hoặc sai số kiểm tra ISO 6346."""

    def __init__(self, message: str = "Số container không hợp lệ hoặc sai số kiểm tra ISO 6346"):
        """Khởi tạo lỗi container không hợp lệ."""
        super().__init__(message=message)


class CarrierMismatchError(DomainError):
    """Ngoại lệ phát sinh khi nhà xe gửi tin không khớp với phân công trong kế hoạch Shipping."""

    def __init__(self, message: str = "Nhà xe gửi tin không đúng với phân công trong kế hoạch"):
        """Khởi tạo lỗi phân công nhà xe không khớp."""
        super().__init__(message=message)


class TripNotFoundError(DomainError):
    """Ngoại lệ phát sinh khi không tìm thấy chuyến xe tương ứng trong hệ thống lưu trữ."""

    def __init__(self, message: str = "Không tìm thấy chuyến xe tương ứng trong hệ thống"):
        """Khởi tạo lỗi không tìm thấy chuyến xe."""
        super().__init__(message=message)


# ============================================================================
# NHÓM E999: LỖI HỆ THỐNG NGOÀI DỰ KIẾN (INTERNAL UNHANDLED EXCEPTIONS)
# ============================================================================


class InternalServerError(CarrierBotError):
    """Mã E999: Lỗi hệ thống nội bộ phát sinh ngoài ý muốn (chưa được phân loại)."""

    def __init__(self, message: str = "Lỗi hệ thống ngoài dự kiến"):
        """Khởi tạo lỗi nội bộ không lường trước với mã HTTP 500 và retryable=True."""
        super().__init__(
            code="E999",
            message=message,
            retryable=True,
            http_status=500,
        )
