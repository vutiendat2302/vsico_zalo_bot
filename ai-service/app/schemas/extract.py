"""Schemas Pydantic cho bóc tách thực thể & phân loại ý định hội thoại."""

from typing import Any

from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    """Payload gửi từ backend sang ai-service để bóc tách thông tin tin nhắn."""

    message_text: str = Field(..., description="Nội dung tin nhắn đầu vào (sẽ được che SĐT trước khi gọi LLM)")
    sender_id: str | None = Field(None, description="Zalo sender ID")
    group_id: str | None = Field(None, description="Zalo group ID")
    carrier_id: int | None = Field(None, description="ID nhà xe liên kết")
    message_type: str = Field(default="text", description="Loại tin nhắn: text | image | ocr_text")
    quote_message: str | None = Field(None, description="Tin nhắn được trích dẫn (quote)")
    context_messages: list[str] = Field(default_factory=list, description="Một vài tin nhắn gần nhất cùng người gửi")
    active_plans: list[dict[str, Any]] = Field(default_factory=list, description="Kế hoạch đang chạy để đối chiếu")


class ExtractedEntity(BaseModel):
    """Thực thể đơn lẻ bóc tách từ tin nhắn."""

    plate_number: str | None = Field(None, description="Biển số đầu kéo")
    trailer_number: str | None = Field(None, description="Biển số rơ-moóc")
    driver_name: str | None = Field(None, description="Tên tài xế")
    driver_phone: str | None = Field(None, description="Số điện thoại tài xế")
    container_no: str | None = Field(None, description="Số container")
    container_size: str | None = Field(None, description="Kích thước container (20/40/45)")
    seal_no: str | None = Field(None, description="Số seal/chì")
    booking_no: str | None = Field(None, description="Số booking / vận đơn")
    order_type: str | None = Field(None, description="Loại lệnh: LOAD | RETURN")
    customer_name: str | None = Field(None, description="Tên khách hàng nếu có")
    warehouse_name: str | None = Field(None, description="Địa chỉ/tên kho nhập")
    eta: str | None = Field(None, description="Giờ hẹn đóng/trả")
    plan_date: str | None = Field(None, description="Ngày dự kiến (YYYY-MM-DD)")
    evidence: str | None = Field(None, description="Đoạn văn bản gốc làm bằng chứng bóc tách")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Độ tin cậy bóc tách")


class ExtractResponse(BaseModel):
    """Kết quả bóc tách trả về cho backend."""

    intent: str = Field(
        default="PARSE_TRUCK_INFO",
        description="Ý định chuẩn: PARSE_TRUCK_INFO | SUPPLEMENT | UPDATE_REQUEST | CANCEL_REQUEST | IGNORE_CHAT",
    )
    is_multi_vehicle: bool = Field(default=False, description="Có phải tin nhắn đa xe/đa lệnh không")
    items: list[ExtractedEntity] = Field(default_factory=list, description="Danh sách các xe/lệnh đã bóc tách")
    model_name: str = Field(..., description="Tên model AI thực thi")
    prompt_version: str = Field(default="ai_extract_v2.0", description="Phiên bản prompt đã sử dụng")
    raw_masked_text: str | None = Field(None, description="Nội dung đã che SĐT dùng khi gọi LLM")
    latency_ms: int = Field(default=0, description="Thời gian phản hồi tính bằng ms")
