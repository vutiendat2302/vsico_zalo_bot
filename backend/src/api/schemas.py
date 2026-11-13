"""Module Định Nghĩa Cấu Trúc Dữ Liệu Đầu Vào / Đầu Ra HTTP (API Pydantic Schemas).

Bao gồm các Schema nhận payload từ `zca-js` Webhook (hỗ trợ cả cấu trúc lồng `sender`/`message`
của `bridge.js` lẫn cấu trúc phẳng) và các Schema trả về kết quả tin nhắn kèm dữ liệu
xe đầu kéo (`truck_records`), container (`container_jobs`) và phân loại Taxonomy (Bảng 1 & Bảng 2).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class FormErrorItem(BaseModel):
    """Mô tả chi tiết lỗi xác thực dữ liệu của từng trường trong form."""

    field: str = Field(..., description="Tên trường dữ liệu gặp lỗi (e.g. username, password, email)")
    message: str = Field(..., description="Thông báo lỗi tiếng Việt dễ hiểu cho người dùng")
    code: str = Field(default="invalid", description="Mã lỗi hệ thống chuẩn hóa (e.g. missing, min_length, invalid_value)")


class ApiResponse(BaseModel, Generic[T]):
    """Cấu trúc phản hồi API chuẩn hóa toàn hệ thống (Standard API Response Envelope)."""

    ok: bool = Field(default=True, description="Trạng thái thực thi API: True (thành công) / False (thất bại)")
    status_code: int = Field(default=200, description="Mã trạng thái HTTP (200, 201, 400, 422, 500...)")
    message: str = Field(default="Thao tác thành công.", description="Thông điệp phản hồi cho người dùng")
    detail: Optional[str] = Field(default=None, description="Trường tương thích ngược cho client đọc qua detail")
    data: Optional[T] = Field(default=None, description="Dữ liệu chính trả về của API")
    errors: list[FormErrorItem] = Field(default_factory=list, description="Danh sách chi tiết lỗi form validation (nếu có)")
    meta: Optional[dict[str, Any]] = Field(default=None, description="Thông tin bổ sung (phân trang: page, page_size, total...)")


class ZcaWebhookPayload(BaseModel):
    """Cấu trúc JSON Payload gửi từ `zca-js` sang cổng `/webhook`.

    Chuẩn hóa theo cấu trúc lồng DATA_CONTRACT (`sender`, `message`).
    Thuộc tính `extra="allow"` vẫn cho phép tiếp nhận các trường mở rộng
    hoặc định dạng rút gọn phẳng khi gọi từ client nội bộ.
    """

    model_config = ConfigDict(extra="allow")

    app_id: Optional[str] = Field(
        default="zca_personal_bot",
        description="Mã định danh ứng dụng cầu nối Zalo (mặc định: 'zca_personal_bot')",
    )
    event_name: Optional[str] = Field(
        default="user_send_text",
        description="Tên sự kiện: 'user_send_text' (văn bản) hoặc 'user_send_image' (hình ảnh)",
    )
    group_id: Optional[str] = Field(
        default="",
        description="Mã nhóm Zalo (nếu nhắn trực tiếp 1-1 có thể để trống, hệ thống tự quy đổi sang direct_<sender_id>)",
    )
    group_name: Optional[str] = Field(default=None, description="Tên hiển thị của nhóm Zalo")
    sender: Optional[dict[str, Any]] = Field(
        default=None,
        description="Thông tin người gửi từ zca-js ({'id': '...', 'name': '...'})",
    )
    timestamp: Optional[Any] = Field(
        default=None,
        description="Thời điểm gửi tin nhắn (epoch milliseconds/seconds hoặc chuỗi ISO-8601)",
    )
    quote_msg_id: Optional[str] = Field(
        default=None,
        description="Mã tin nhắn cũ được trích dẫn/trả lời (nếu có - T31)",
    )
    message: Optional[dict[str, Any]] = Field(
        default=None,
        description="Nội dung tin nhắn từ zca-js ({'msg_id': '...', 'text': '...', 'image_url': '...'})",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Đường dẫn URL hình ảnh điều xe / lệnh đóng trả (HTTP/HTTPS)",
    )
    image_base64: Optional[str] = Field(
        default=None,
        description="Chuỗi Base64 của hình ảnh gửi trực tiếp qua API",
    )
    attachments: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Danh sách tệp đính kèm theo chuẩn sự kiện Zalo",
    )
    raw_payload: Optional[dict[str, Any]] = Field(
        default=None,
        description="Dữ liệu JSON nguyên bản từ sự kiện Zalo (`message.data`)",
    )


class TruckRecordOut(BaseModel):
    """Thông tin xe đầu kéo và tài xế đã bóc tách thuộc về một tin nhắn (bảng `truck_records`)."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str = Field(..., description="ID xe dạng chuỗi tránh tràn số JS")
    message_id: Optional[str] = None
    extraction_run_id: Optional[str] = None
    truck_plate: Optional[str] = None
    trailer_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    eta_text: Optional[str] = None
    estimated_at: Optional[datetime] = None
    note: Optional[str] = None
    status: str = "ACTIVE"
    raw_data: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class ContainerJobOut(BaseModel):
    """Thông tin tác vụ container đã bóc tách và kiểm tra ISO 6346 (bảng `container_jobs`)."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str = Field(..., description="ID container job dạng chuỗi tránh tràn số JS")
    message_id: Optional[str] = None
    extraction_run_id: Optional[str] = None
    truck_record_id: Optional[str] = None
    parent_job_id: Optional[str] = None
    is_update: Optional[bool] = None
    line_no: int
    line_text: Optional[str] = None
    source_format: Optional[str] = None
    plan_date: Optional[str] = None
    container_no: Optional[str] = None
    container_size: Optional[str] = None
    seal_no: Optional[str] = None
    booking_no: Optional[str] = None
    order_type: Optional[str] = None
    warehouse_hint: Optional[str] = None
    customer_hint: Optional[str] = None
    customer_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    eta: Optional[str] = None
    estimated_at: Optional[datetime] = None
    match_method: Optional[str] = None
    match_source: Optional[str] = None
    ai_confidence: Optional[Decimal] = None
    note: Optional[str] = None
    check_digit_valid: Optional[bool] = None
    validation_status: str
    routing_status: str
    tms_sync_status: str
    warnings: list[str] = Field(default_factory=list)
    canonical_record: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MessageItemOut(BaseModel):
    """Thông tin chi tiết một tin nhắn Zalo kèm danh sách xe, container và phân loại Taxonomy (bảng `zalo_messages`)."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str = Field(..., description="Snowflake ID 64-bit dạng chuỗi tránh tràn số JS")
    zalo_message_id: str
    group_id: str
    group_name: Optional[str] = None
    sender_id: str
    sender_name: Optional[str] = None
    quote_msg_id: Optional[str] = None
    message_type: str
    raw_text: Optional[str] = None
    sent_at: Optional[datetime] = None
    received_at: datetime
    processing_status: str
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    taxonomy: Optional[dict[str, Any]] = None
    trucks: list[TruckRecordOut] = Field(default_factory=list)
    containers: list[ContainerJobOut] = Field(default_factory=list)


class MessageListResponse(BaseModel):
    """Cấu trúc phản hồi chuẩn cho các API truy vấn danh sách tin nhắn."""

    ok: bool = True
    status: str = "OK"
    total: int
    total_returned: int
    filters: dict[str, Any]
    messages: list[MessageItemOut]


class TransportPlanBase(BaseModel):
    """Cấu trúc dữ liệu cơ sở cho bản ghi Kế hoạch vận chuyển hàng ngày."""

    model_config = ConfigDict(from_attributes=True)

    plan_date: date = Field(..., description="Ngày kế hoạch (YYYY-MM-DD)")
    stt: Optional[int] = Field(default=None, description="Số thứ tự trong file")
    route_name: Optional[str] = Field(default=None, description="Tuyến vận chuyển (VD: 'HP - Tân Quang')")
    cargo_io_type: Optional[str] = Field(default=None, description="Cột Hàng: 'I' (Nhập) hoặc 'X' (Xuất)")
    order_type: str = Field(default="RETURN", description="Loại lệnh: 'LOAD' (Đóng/Xuất) hoặc 'RETURN' (Trả/Nhập)")
    container_no: Optional[str] = Field(default=None, description="Số container")
    seal_no: Optional[str] = Field(default=None, description="Số chì niêm phong")
    container_size: Optional[str] = Field(default=None, description="Kích cỡ: '20' hoặc '40'")
    cargo_weight: Optional[Decimal] = Field(default=None, description="Tải trọng cả vỏ (tấn)")
    required_time: Optional[str] = Field(default=None, description="Yêu cầu thời gian có mặt (VD: '7h', '9h')")
    customer_name: Optional[str] = Field(default=None, description="Tên khách hàng (VD: 'Logitem', 'DC', 'Asia')")
    cargo_type: Optional[str] = Field(default=None, description="Loại hàng hóa (VD: 'Mỳ', 'Nguyên liệu')")
    vessel_voyage: Optional[str] = Field(default=None, description="Chuyến tàu/Số (VD: 'Prosper 2633N')")
    empty_depot: Optional[str] = Field(default=None, description="Bãi nâng/hạ vỏ")
    full_depot: Optional[str] = Field(default=None, description="Bãi nâng/hạ hàng (VD: 'PTSC')")
    estimated_drop_time: Optional[str] = Field(default=None, description="Giờ dự kiến hạ hàng")
    fleet_partner: Optional[str] = Field(default=None, description="Đội xe phân công (VD: 'Tuấn Hưng', 'Phương Anh HP')")
    planned_truck_plate: Optional[str] = Field(default=None, description="Số xe dự kiến (VD: '29C-445.41')")
    delivery_address: Optional[str] = Field(default=None, description="Địa chỉ đóng/ trả hàng kèm liên hệ thủ kho")
    group_id: Optional[str] = Field(
        default="6469608867469758994",
        description="ID nhóm Zalo nhận thông báo (mặc định map: '6469608867469758994')",
    )
    operator_staff: Optional[str] = Field(default=None, description="Cán bộ giao nhận")
    notes: Optional[str] = Field(default=None, description="Ghi chú điều vận")
    extra_fee_notes: Optional[str] = Field(default=None, description="Phát sinh chi phí")


class TransportPlanCreate(BaseModel):
    """Schema tạo mới một bản ghi Kế hoạch vận chuyển."""

    plan_date: date
    stt: Optional[int] = None
    route_name: Optional[str] = None
    cargo_io_type: Optional[str] = None
    order_type: Optional[str] = None  # Nếu không truyền, tự suy luận từ cargo_io_type ('I' -> 'tra', 'X' -> 'dong')
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    container_size: Optional[str] = None
    cargo_weight: Optional[Decimal] = None
    required_time: Optional[str] = None
    customer_name: Optional[str] = None
    cargo_type: Optional[str] = None
    vessel_voyage: Optional[str] = None
    empty_depot: Optional[str] = None
    full_depot: Optional[str] = None
    estimated_drop_time: Optional[str] = None
    fleet_partner: Optional[str] = None
    planned_truck_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    delivery_address: Optional[str] = None
    group_id: Optional[str] = "6469608867469758994"
    operator_staff: Optional[str] = None
    notes: Optional[str] = None
    extra_fee_notes: Optional[str] = None


class TransportPlanUpdate(BaseModel):
    """Schema cập nhật bản ghi Kế hoạch vận chuyển."""

    plan_date: Optional[date] = None
    stt: Optional[int] = None
    route_name: Optional[str] = None
    cargo_io_type: Optional[str] = None
    order_type: Optional[str] = None
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    container_size: Optional[str] = None
    cargo_weight: Optional[Decimal] = None
    required_time: Optional[str] = None
    customer_name: Optional[str] = None
    cargo_type: Optional[str] = None
    vessel_voyage: Optional[str] = None
    empty_depot: Optional[str] = None
    full_depot: Optional[str] = None
    estimated_drop_time: Optional[str] = None
    fleet_partner: Optional[str] = None
    planned_truck_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    delivery_address: Optional[str] = None
    group_id: Optional[str] = None
    operator_staff: Optional[str] = None
    notes: Optional[str] = None
    extra_fee_notes: Optional[str] = None


class PlanVehicleUpdate(BaseModel):
    """Cập nhật xe trên kế hoạch với phiên bản chống ghi đè; không gửi TMS."""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    planned_truck_plate: Optional[str] = Field(default=None, max_length=64)
    driver_name: Optional[str] = Field(default=None, max_length=128)
    driver_phone: Optional[str] = Field(default=None, pattern=r"^0[0-9]{9}$")
    container_no: Optional[str] = Field(default=None, max_length=16)
    seal_no: Optional[str] = Field(default=None, max_length=64)
    container_size: Optional[str] = Field(default=None, max_length=16)
    required_time: Optional[str] = Field(default=None, max_length=64)
    carrier_id: Optional[int] = Field(default=None, gt=0)


class TransportPlanOut(TransportPlanBase):
    """Schema chi tiết một bản ghi Kế hoạch vận chuyển trả về API (bảng `transport_plans`)."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    group_name: Optional[str] = None
    carrier_id: Optional[int] = None
    version: int = 1
    tms_sync_status: str = "NOT_STARTED"
    id: str = Field(..., description="Snowflake ID 64-bit dạng chuỗi tránh tràn số JS")
    customer_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    address: Optional[str] = None
    carrier_name: Optional[str] = None
    eta: Optional[str] = None
    combine_note: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TransportPlanListResponse(BaseModel):
    """Cấu trúc phản hồi danh sách Kế hoạch vận chuyển kèm bộ lọc."""

    ok: bool = True
    status: str = "OK"
    total: int
    total_returned: int
    filters: dict[str, Any]
    plans: list[TransportPlanOut]


class TransportPlanImportResponse(BaseModel):
    """Cấu trúc phản hồi kết quả Import file Kế hoạch vận chuyển (CSV / Excel)."""

    ok: bool = True
    status: str = "OK"
    message: str
    plan_date: Optional[str] = None
    total_imported: int
    total_skipped: int
    default_group_id_applied: str = "6469608867469758994"
    sample_imported: list[TransportPlanOut] = Field(default_factory=list)


class TransportPlanRandomizeResponse(BaseModel):
    """Cấu trúc phản hồi kết quả Random nhóm Zalo cho Kế hoạch vận chuyển."""

    ok: bool = True
    status: str = "OK"
    message: str
    total_updated: int
    group_distribution: dict[str, int] = Field(default_factory=dict)


# ==============================================================================
# SCHEMAS CHO PHÂN HỆ NGƯỜI DÙNG & XÁC THỰC (USERS & AUTH)
# ==============================================================================


class UserCreate(BaseModel):
    """Dữ liệu yêu cầu tạo mới tài khoản người dùng nội bộ.

    Mặc định:
    - password: '123456'
    - zalo_user_id: '6691387223255581446'
    - zalo_info_id: 3073804738540831090
    - role: 'DHVT'
    - is_active: True
    """

    username: str = Field(..., min_length=2, max_length=64, description="Tên đăng nhập")
    password: Optional[str] = Field(default="123456", min_length=6, description="Mật khẩu đăng nhập")
    full_name: Optional[str] = Field(default=None, max_length=255, description="Họ và tên đầy đủ")
    role: Optional[str] = Field(default="DHVT", description="Phân quyền: 'ADMIN' hoặc 'DHVT'")
    email: Optional[str] = Field(default=None, max_length=255, description="Email công ty")
    zalo_user_id: Optional[str] = Field(
        default="6691387223255581446",
        max_length=128,
        description="ID tài khoản Zalo cá nhân",
    )
    zalo_info_id: Optional[int] = Field(
        default=3073804738540831090,
        description="ID nhóm Zalo ĐHVT nội bộ liên kết",
    )
    tms_user_id: Optional[int] = Field(default=None, description="Khóa đồng bộ người dùng từ TMS")
    forwarder_id: Optional[int] = Field(default=None, description="ID đơn vị Forwarder phụ trách")
    is_active: Optional[bool] = Field(default=True, description="Trạng thái kích hoạt tài khoản")


class UserUpdate(BaseModel):
    """Dữ liệu yêu cầu cập nhật thông tin tài khoản."""

    full_name: Optional[str] = Field(default=None, max_length=255)
    role: Optional[str] = Field(default=None, description="'ADMIN' hoặc 'DHVT'")
    email: Optional[str] = Field(default=None, max_length=255)
    zalo_user_id: Optional[str] = Field(default=None, max_length=128)
    zalo_info_id: Optional[int] = Field(default=None)
    tms_user_id: Optional[int] = Field(default=None)
    forwarder_id: Optional[int] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
    password: Optional[str] = Field(default=None, min_length=6, description="Mật khẩu mới nếu muốn đổi")


class UserOut(BaseModel):
    """Cấu trúc dữ liệu người dùng trả về trong phản hồi API."""

    id: str = Field(..., description="Snowflake ID 64-bit dạng chuỗi")
    username: str
    full_name: str
    role: str
    email: Optional[str] = None
    zalo_user_id: Optional[str] = None
    zalo_info_id: Optional[str] = None
    tms_user_id: Optional[str] = None
    forwarder_id: Optional[str] = None
    is_active: bool
    last_login_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class UserResponse(ApiResponse[UserOut]):
    """Cấu trúc phản hồi chi tiết một người dùng theo chuẩn ApiResponse."""

    pass


class UserListResponse(ApiResponse[list[UserOut]]):
    """Cấu trúc phản hồi danh sách người dùng có phân trang theo chuẩn ApiResponse."""

    total: Optional[int] = None
    page: Optional[int] = None
    page_size: Optional[int] = None
    items: Optional[list[UserOut]] = None


class LoginRequest(BaseModel):
    """Dữ liệu yêu cầu đăng nhập hệ thống."""

    username: str = Field(..., description="Tên đăng nhập hoặc Email")
    password: str = Field(..., min_length=1, description="Mật khẩu")


class LoginData(BaseModel):
    """Dữ liệu trả về sau khi đăng nhập thành công."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LoginResponse(ApiResponse[LoginData]):
    """Cấu trúc phản hồi đăng nhập thành công theo chuẩn ApiResponse."""

    access_token: Optional[str] = None
    token_type: Optional[str] = "bearer"
    user: Optional[UserOut] = None


# ==============================================================================
# SCHEMAS ĐỒNG BỘ TOÀN BỘ CÁC BẢNG DANH MỤC, RUNTIME & LƯU TRỮ (DB SCHEMA)
# ==============================================================================


class ZaloGroupOut(BaseModel):
    """Thông tin nhóm Zalo quản lý trong hệ thống (bảng `zalo_groups`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    zalo_group_id: str
    name: Optional[str] = None
    group_role: str = Field(default="SOURCE", description="SOURCE | DESTINATION | DHVT | CUSTOMER | CARRIER")
    carrier_id: Optional[str] = None
    carrier_name: Optional[str] = None
    send_mode: str = Field(default="AUTO", description="AUTO (Tự động) | MANUAL (Chờ duyệt)")
    is_test: bool = False
    is_active: bool = True
    expires_at: Optional[datetime] = None
    created_at: datetime


class CarrierOut(BaseModel):
    """Thông tin nhà xe / đội xe chuẩn đồng bộ từ TMS (bảng `carriers`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tms_carrier_id: Optional[int] = None
    code: Optional[str] = None
    name: str
    short_name: Optional[str] = None
    normalized_name: str
    tax_code: Optional[str] = None
    is_active: bool = True
    synced_at: Optional[datetime] = None
    created_at: datetime


class CustomerOut(BaseModel):
    """Thông tin khách hàng chuẩn đồng bộ từ TMS (bảng `customers`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tms_customer_id: str
    name: str
    normalized_name: str
    is_active: bool = True
    synced_at: Optional[datetime] = None


class WarehouseOut(BaseModel):
    """Thông tin kho đóng/trả hàng chuẩn đồng bộ từ TMS (bảng `warehouses`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tms_warehouse_id: str
    customer_id: Optional[int] = None
    name: str
    normalized_name: str
    address: Optional[str] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    is_active: bool = True
    synced_at: Optional[datetime] = None


class CustomerAliasOut(BaseModel):
    """Tên gọi tắt / bí danh của khách hàng (bảng `customer_aliases`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    alias: str
    normalized_alias: str
    source: str = "manual"
    created_at: datetime


class WarehouseAliasOut(BaseModel):
    """Tên gọi tắt / bí danh của kho hàng (bảng `warehouse_aliases`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    alias: str
    normalized_alias: str
    source: str = "manual"
    created_at: datetime


class RouteMapOut(BaseModel):
    """Quy tắc định tuyến Khách hàng + Kho + Loại lệnh -> Nhóm Zalo nhận (bảng `route_maps`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    warehouse_id: Optional[int] = None
    order_type: Optional[str] = None
    zalo_group_id: int
    priority: int = 1
    is_active: bool = True
    created_at: datetime


class ExtractionRunOut(BaseModel):
    """Lịch sử một lượt chạy bóc tách dữ liệu AI hoặc Rule (bảng `extraction_runs`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    model_name: str
    prompt_version: str
    input_data: dict[str, Any]
    output_data: Optional[dict[str, Any]] = None
    status: str = Field(..., description="SUCCESS | FAILED | PARTIAL")
    error_message: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class ReviewCaseOut(BaseModel):
    """Ca rà soát / phê duyệt thủ công dành cho ĐHVT (bảng `review_cases`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    container_job_id: Optional[int] = None
    case_type: str
    reason: str
    details: Optional[dict[str, Any]] = None
    status: str = Field(default="PENDING", description="PENDING | APPROVED | REJECTED | RESOLVED | SYNC_FAILED")
    assigned_to: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution: Optional[dict[str, Any]] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None


class BotReplyOut(BaseModel):
    """Tin nhắn Bot nhắc lỗi nhà xe kèm hạn sửa 30 phút (bảng `bot_replies`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    sender_id: str
    zalo_msg_id: Optional[str] = None
    reply_text: str
    fix_deadline: datetime
    status: str = Field(default="PENDING", description="PENDING | SENT | RESOLVED | CANCELLED")
    sent_at: Optional[datetime] = None
    created_at: datetime


class OutboundMessageItemOut(BaseModel):
    """Liên kết container thuộc về một tin nhắn gửi đi (bảng `outbound_message_items`)."""

    model_config = ConfigDict(from_attributes=True)

    outbound_message_id: int
    container_job_id: int


class OutboundMessageOut(BaseModel):
    """Tin nhắn thông báo kết quả gửi ra nhóm Zalo khách hàng (bảng `outbound_messages`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    target_group_id: int
    order_type: str
    message_kind: str = "initial"
    content: str
    idempotency_key: str
    review_zalo_msg_id: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    status: str = Field(
        default="PENDING_APPROVAL",
        description="PENDING_APPROVAL | PENDING_SEND | SENT | FAILED | CANCELLED | IGNORED_DUPLICATE",
    )
    attempt_count: int = 0
    zalo_message_id: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None
    items: list[OutboundMessageItemOut] = Field(default_factory=list)


class TmsSyncLogOut(BaseModel):
    """Nhật ký gọi API đồng bộ dữ liệu sang phần mềm be-tms (bảng `tms_sync_logs`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    container_job_id: int
    operation: str
    request_data: Optional[dict[str, Any]] = None
    response_data: Optional[dict[str, Any]] = None
    http_status: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime


class ActivityLogOut(BaseModel):
    """Nhật ký kiểm toán thao tác của người dùng và hệ thống (bảng `activity_logs`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    created_at: datetime


class FileRecordOut(BaseModel):
    """Thông tin metadata tệp tin và đối tượng lưu trữ trên MinIO S3 (bảng `files`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_key: str
    bucket: str
    object_key: str
    original_name: Optional[str] = None
    mime_type: str
    size_bytes: int
    sha256: str
    source_type: str
    source_url: Optional[str] = None
    message_id: Optional[int] = None
    storage_status: str = Field(default="PENDING", description="PENDING | STORED | FAILED | DELETED")
    meta: Optional[dict[str, Any]] = None
    created_at: datetime
    deleted_at: Optional[datetime] = None


class MessageDraftOut(BaseModel):
    """Bản nháp gom các tin nhắn rời rạc theo nhóm và người gửi (bảng `message_drafts`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    zalo_info_id: int
    carrier_id: Optional[int] = None
    group_id: str
    sender_id: str
    status: str = Field(default="OPEN", description="OPEN | FLUSHED | WAITING_REPLY | EXPIRED | CANCELLED")
    entities: dict[str, Any]
    first_message_id: int
    last_message_id: int
    message_count: int = 1
    expires_at: datetime
    flushed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
