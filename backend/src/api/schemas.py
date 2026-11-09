"""Module Định Nghĩa Cấu Trúc Dữ Liệu Đầu Vào / Đầu Ra HTTP (API Pydantic Schemas).

Bao gồm các Schema nhận payload từ `zca-js` Webhook (hỗ trợ cả cấu trúc lồng `sender`/`message`
của `bridge.js` lẫn cấu trúc phẳng) và các Schema trả về kết quả tin nhắn kèm dữ liệu
xe đầu kéo (`truck_records`), container (`container_jobs`) và phân loại Taxonomy (Bảng 1 & Bảng 2).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ZcaWebhookPayload(BaseModel):
    """Cấu trúc JSON Payload gửi từ `zca-js` hoặc Postman sang cổng `/webhook`."""

    model_config = ConfigDict(extra="allow")

    msg_id: Optional[str] = Field(default=None, description="Mã định danh tin nhắn duy nhất từ Zalo")
    group_id: Optional[str] = Field(
        default="",
        description="Mã nhóm Zalo (nếu nhắn trực tiếp 1-1 có thể để trống, hệ thống tự quy đổi sang direct_<sender_id>)",
    )
    group_name: Optional[str] = Field(default=None, description="Tên hiển thị của nhóm Zalo")
    sender_id: Optional[str] = Field(default=None, description="Mã định danh người gửi Zalo (User ID)")
    sender_name: Optional[str] = Field(default=None, description="Tên hiển thị của người gửi")
    text: Optional[str] = Field(default=None, description="Nội dung văn bản thô của tin nhắn")
    timestamp: Optional[Any] = Field(
        default=None,
        description="Thời điểm gửi tin nhắn (epoch milliseconds/seconds hoặc chuỗi ISO-8601)",
    )
    quote_msg_id: Optional[str] = Field(
        default=None,
        description="Mã tin nhắn cũ được trích dẫn/trả lời (nếu có - T31)",
    )
    sender: Optional[dict[str, Any]] = Field(
        default=None,
        description="Đối tượng người gửi theo chuẩn DATA_CONTRACT của zca-js ({'id': ..., 'name': ...})",
    )
    message: Optional[dict[str, Any]] = Field(
        default=None,
        description="Đối tượng nội dung tin nhắn theo chuẩn DATA_CONTRACT của zca-js ({'msg_id': ..., 'text': ...})",
    )
    raw_payload: Optional[dict[str, Any]] = Field(
        default=None,
        description="Toàn bộ dữ liệu JSON nguyên bản từ sự kiện Zalo",
    )
    event_name: Optional[str] = Field(
        default="user_send_text",
        description="Tên sự kiện: 'user_send_text' (văn bản) hoặc 'user_send_image' (hình ảnh)",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Đường dẫn URL hình ảnh điều xe / lệnh đóng trả (HTTP/HTTPS)",
    )
    image_base64: Optional[str] = Field(
        default=None,
        description="Chuỗi Base64 của hình ảnh nếu gửi trực tiếp qua API",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Đường dẫn tệp ảnh cục bộ trên máy chủ (nếu có)",
    )
    attachments: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Danh sách tệp đính kèm theo chuẩn sự kiện Zalo",
    )
    mock_ocr_text: Optional[str] = Field(
        default=None,
        description="Dữ liệu văn bản giả lập OCR dùng cho kịch bản kiểm thử tự động (Unit Test)",
    )


class TruckRecordOut(BaseModel):
    """Thông tin xe đầu kéo và tài xế đã bóc tách thuộc về một tin nhắn."""

    id: int
    truck_plate: Optional[str] = None
    trailer_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    eta_text: Optional[str] = None
    estimated_at: Optional[datetime] = None
    note: Optional[str] = None
    status: str


class ContainerJobOut(BaseModel):
    """Thông tin tác vụ container đã bóc tách và kiểm tra ISO 6346 thuộc về một tin nhắn."""

    id: int
    truck_record_id: Optional[int] = None
    line_no: int
    source_format: Optional[str] = None
    plan_date: Optional[str] = None
    container_no: Optional[str] = None
    container_size: Optional[str] = None
    seal_no: Optional[str] = None
    booking_no: Optional[str] = None
    order_type: Optional[str] = None
    warehouse_hint: Optional[str] = None
    customer_hint: Optional[str] = None
    eta: Optional[str] = None
    estimated_at: Optional[datetime] = None
    match_source: Optional[str] = None
    check_digit_valid: Optional[bool] = None
    validation_status: str
    routing_status: str
    tms_sync_status: str
    warnings: list[str] = Field(default_factory=list)
    canonical_record: Optional[dict[str, Any]] = None


class MessageItemOut(BaseModel):
    """Thông tin chi tiết một tin nhắn Zalo kèm danh sách xe, container và phân loại Taxonomy."""

    id: int
    zalo_message_id: str
    group_id: str
    group_name: Optional[str] = None
    sender_id: str
    sender_name: Optional[str] = None
    message_type: str
    raw_text: Optional[str] = None
    sent_at: Optional[datetime] = None
    received_at: datetime
    processing_status: str
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
    order_type: str = Field(default="tra", description="Loại lệnh: 'dong' (Xuất) hoặc 'tra' (Nhập/Mở)")
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
    delivery_address: Optional[str] = None
    group_id: Optional[str] = None
    operator_staff: Optional[str] = None
    notes: Optional[str] = None
    extra_fee_notes: Optional[str] = None


class TransportPlanOut(TransportPlanBase):
    """Schema chi tiết một bản ghi Kế hoạch vận chuyển trả về API."""

    id: int
    customer_id: Optional[int] = None
    warehouse_id: Optional[int] = None
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

