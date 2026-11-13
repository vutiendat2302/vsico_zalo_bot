"""Module Định Nghĩa Các Tập Hằng Số & Kiểu Liệt Kê Nghiệp Vụ (Domain Enums).

Thống nhất toàn bộ giá trị trạng thái trong hệ thống:
- Tất cả Enums đều sử dụng tiếng Anh chuẩn, viết hoa toàn bộ (ENGLISH, FULL UPPERCASE).
"""

from enum import Enum
from typing import Optional


class UpperStrEnum(str, Enum):
    """Lớp Enum chuỗi cơ sở chuẩn hóa giá trị về chữ in hoa tiếng Anh."""

    @classmethod
    def _missing_(cls, value: object) -> Optional["UpperStrEnum"]:
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper or member.name == val_upper:
                    return member
        return None


class MessageStatus(UpperStrEnum):
    """Trạng thái xử lý của tin nhắn gốc trong bảng `zalo_messages`."""

    RECEIVED = "RECEIVED"  # Tin mới nhận từ Zalo Webhook, chưa xử lý
    QUEUED = "QUEUED"  # Đã đưa vào hàng đợi FIFO chờ bóc tách
    PROCESSING = "PROCESSING"  # Đang trong tiến trình bóc tách dữ liệu
    PROCESSED = "PROCESSED"  # Đã bóc tách thành công đầy đủ thông tin
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Cần ĐHVT rà soát thủ công do thiếu hoặc sai thông tin
    IGNORED_NON_TEXT = "IGNORED_NON_TEXT"  # Bỏ qua do không phải văn bản hoặc ảnh lệnh
    IGNORED_CHAT = "IGNORED_CHAT"  # Bỏ qua do là tin nhắn trò chuyện thông thường
    FAILED = "FAILED"  # Xử lý tin nhắn thất bại do lỗi hệ thống
    CANCELLED = "CANCELLED"  # Tin nhắn bị ĐHVT từ chối hoặc hủy bỏ
    DUPLICATE = "DUPLICATE"  # Tin nhắn trùng lặp với tin đã nhận trước đó


class ValidationStatus(UpperStrEnum):
    """Trạng thái kiểm tra tính hợp lệ của container trong bảng `container_jobs`."""

    PENDING = "PENDING"  # Đang chờ thẩm định tính hợp lệ
    VALID = "VALID"  # Dữ liệu hợp lệ (chuẩn ISO 6346 Modulo 11)
    INVALID = "INVALID"  # Dữ liệu không hợp lệ hoặc sai số kiểm tra cont
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Cần ĐHVT can thiệp kiểm tra lại thủ công
    REJECTED = "REJECTED"  # ĐHVT từ chối tiếp nhận container này


class RoutingStatus(UpperStrEnum):
    """Trạng thái định tuyến nhóm nhận của container trong bảng `container_jobs`."""

    PENDING = "PENDING"  # Đang chờ xác định nhóm Zalo đích
    RESOLVED = "RESOLVED"  # Đã tìm thấy nhóm Zalo khách hàng tương ứng
    ROUTED = "ROUTED"  # Đã định tuyến thành công tới nhóm nhận tin
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Không tìm thấy nhóm đích, chờ ĐHVT chỉ định
    SENT = "SENT"  # Đã phát hành thông báo tới nhóm Zalo đích
    CANCELLED = "CANCELLED"  # Hủy định tuyến hoặc hủy chuyến


class TmsSyncStatus(UpperStrEnum):
    """Trạng thái đồng bộ dữ liệu sang phần mềm PM TMS (`be-tms`)."""

    NOT_STARTED = "NOT_STARTED"  # Chưa bắt đầu đồng bộ sang TMS
    PENDING = "PENDING"  # Đang chờ lượt đẩy dữ liệu sang TMS
    SYNCED = "SYNCED"  # Đã đồng bộ dữ liệu thành công sang TMS
    FAILED = "FAILED"  # Đồng bộ sang TMS thất bại sau các lần thử
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Gặp lỗi nghiệp vụ, cần ĐHVT đối soát thủ công


class OrderType(UpperStrEnum):
    """Loại lệnh vận chuyển container (Đóng hàng xuất LOAD hoặc Trả hàng nhập RETURN)."""

    LOAD = "LOAD"  # Lệnh đóng hàng xuất (lấy cont rỗng đóng hàng mang ra cảng)
    RETURN = "RETURN"  # Lệnh trả hàng nhập (nhận cont có hàng hạ bãi hoặc trả vỏ)


class Intent(UpperStrEnum):
    """Ý định của người gửi trong tin nhắn Zalo."""

    PARSE = "PARSE_TRUCK_INFO"  # Bí danh của lệnh bóc tách thông tin điều xe
    PARSE_TRUCK_INFO = "PARSE_TRUCK_INFO"  # Nhận diện và bóc tách thông tin xe, tài xế, cont
    UPDATE_REQUEST = "UPDATE_REQUEST"  # Yêu cầu cập nhật, đổi xe, đổi tài xế, đổi giờ
    SUPPLEMENT = "SUPPLEMENT"  # Tin nhắn bổ sung thông tin còn thiếu (số cont, seal...)
    CANCEL_REQUEST = "CANCEL_REQUEST"  # Yêu cầu hủy chuyến hoặc hủy điều xe
    APPROVE_OUTBOUND = "APPROVE_OUTBOUND"  # ĐHVT duyệt phát hành tin thông báo ra nhóm khách
    EDIT_PENDING = "EDIT_PENDING"  # Yêu cầu chỉnh sửa thông tin ca đang chờ duyệt
    IGNORE_CHAT = "IGNORE_CHAT"  # Tin nhắn trò chuyện, chào hỏi, không liên quan vận tải


class UserRole(UpperStrEnum):
    """Vai trò phân quyền của người dùng trong hệ thống."""

    ADMIN = "ADMIN"  # Quản trị viên toàn quyền hệ thống (quản lý user, cấu hình)
    DHVT = "DHVT"  # Nhân viên Điều hành vận tải (rà soát tin nhắn, duyệt thông báo)


class SendMode(UpperStrEnum):
    """Chế độ gửi tin nhắn của nhóm Zalo."""

    AUTO = "AUTO"  # Tự động gửi tin ra nhóm khách khi đủ dữ liệu
    MANUAL = "MANUAL"  # Thủ công, mọi tin nhắn đều phải qua ĐHVT duyệt trước khi gửi


class GroupRole(UpperStrEnum):
    """Vai trò chức năng của nhóm Zalo trong luồng điều vận."""

    SOURCE = "SOURCE"  # Nhóm Zalo nhà xe (nơi nhận tin điều xe đầu vào)
    DESTINATION = "DESTINATION"  # Nhóm Zalo khách hàng (nơi phát hành thông báo kết quả)
    DHVT = "DHVT"  # Nhóm Zalo nội bộ của bộ phận Điều hành vận tải
    CUSTOMER = "CUSTOMER"  # Nhóm khách hàng doanh nghiệp nhận báo xe
    CARRIER = "CARRIER"  # Nhóm đối tác vận tải / nhà xe vệ tinh


class OutboundStatus(UpperStrEnum):
    """Trạng thái phát hành tin nhắn kết quả trong bảng `outbound_messages`."""

    PENDING_APPROVAL = "PENDING_APPROVAL"  # Chờ ĐHVT duyệt trên Web trước khi phát hành
    SENDING = "SENDING"  # Đang gửi; kết quả chưa rõ phải đối soát trước khi gửi lại
    PENDING_SEND = "PENDING_SEND"  # Đã duyệt, chờ worker phát hành ra Zalo
    SENT = "SENT"  # Đã gửi tin nhắn thông báo thành công vào nhóm Zalo
    FAILED = "FAILED"  # Gửi tin tới Zalo thất bại (lỗi mạng hoặc token)
    CANCELLED = "CANCELLED"  # Tin nhắn bị ĐHVT hủy bỏ, không gửi nữa
    IGNORED_DUPLICATE = "IGNORED_DUPLICATE"  # Bỏ qua do trùng lặp nội dung với tin đã gửi trước đó


class ReviewStatus(UpperStrEnum):
    """Trạng thái ca rà soát của ĐHVT trong bảng `review_cases`."""

    PENDING = "PENDING"  # Ca rà soát đang chờ ĐHVT xử lý
    APPROVED = "APPROVED"  # ĐHVT đã phê duyệt chấp nhận dữ liệu
    REJECTED = "REJECTED"  # ĐHVT từ chối dữ liệu (do thông tin sai lệch)
    RESOLVED = "RESOLVED"  # Đã xử lý xong cảnh báo hoặc bổ sung đủ thông tin
    SYNC_FAILED = "SYNC_FAILED"  # Đã duyệt nhưng đồng bộ sang TMS bị lỗi, chờ gửi lại


class StorageStatus(UpperStrEnum):
    """Trạng thái lưu trữ tệp tin trong MinIO/S3 tại bảng `files`."""

    PENDING = "PENDING"  # Tệp tin đang chờ tải lên MinIO/S3
    STORED = "STORED"  # Tệp tin đã được lưu trữ an toàn trong MinIO/S3
    FAILED = "FAILED"  # Lưu trữ tệp tin thất bại
    DELETED = "DELETED"  # Tệp tin đã bị xóa khỏi hệ thống lưu trữ


class MessageDraftStatus(UpperStrEnum):
    """Trạng thái bản nháp tin nhắn chờ gom trong bảng `message_drafts`."""

    OPEN = "OPEN"  # Bản nháp đang mở, tiếp tục gom các tin nhắn liên tiếp
    FLUSHED = "FLUSHED"  # Đã gom đủ thông tin và chuyển thành chuyến hoàn chỉnh
    WAITING_REPLY = "WAITING_REPLY"  # Đã hỏi nhà xe thông tin còn thiếu, chờ phản hồi
    EXPIRED = "EXPIRED"  # Quá thời gian gom tin (hết hạn nháp)
    CANCELLED = "CANCELLED"  # Bản nháp bị hủy bỏ


class CorrectionStatus(UpperStrEnum):
    """Trạng thái chờ sửa lỗi của tin nhắn trong bảng `pending_corrections`."""

    PENDING = "PENDING"  # Đang chờ nhà xe phản hồi sửa lỗi hoặc bổ sung thông tin
    RESOLVED = "RESOLVED"  # Nhà xe đã bổ sung hoặc sửa lỗi thành công
    CANCELLED = "CANCELLED"  # Đã hủy yêu cầu sửa lỗi (quá hạn hoặc chuyển ĐHVT)


class ExtractionRunStatus(UpperStrEnum):
    """Kết quả chạy tiến trình bóc tách trong bảng `extraction_runs`."""

    SUCCESS = "SUCCESS"  # Bóc tách thành công toàn bộ thông tin
    FAILED = "FAILED"  # Bóc tách thất bại
    PARTIAL = "PARTIAL"  # Bóc tách thành công một phần thông tin
