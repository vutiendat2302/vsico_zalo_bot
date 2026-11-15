"""Schema intent trợ lý; AI không nhận SQL, quyền hoặc kết nối cơ sở dữ liệu."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class AssistantIntentRequest(BaseModel):
    """Tập công cụ đóng do backend cung cấp cùng ngày gốc của tin nhắn."""

    model_config = ConfigDict(extra="forbid")
    message_text: str = Field(max_length=8000)
    allowed_tools: list[str] = Field(min_length=1, max_length=36)
    reference_date: date


class AssistantEntities(BaseModel):
    """Chỉ cho phép tham số tìm kiếm, không chứa thông tin cấp quyền."""

    model_config = ConfigDict(extra="forbid")
    plan_date: date | None = None
    container_no: str | None = Field(default=None, max_length=16)
    plate_no: str | None = Field(default=None, max_length=32)
    order_code: str | None = Field(default=None, max_length=32)
    booking_no: str | None = Field(default=None, max_length=64)
    bill_of_lading_no: str | None = Field(default=None, max_length=64)
    warehouse_name: str | None = Field(default=None, max_length=255)
    customer_name: str | None = Field(default=None, max_length=255)
    carrier_name: str | None = Field(default=None, max_length=255)
    forwarder_name: str | None = Field(default=None, max_length=128)
    province_name: str | None = Field(default=None, max_length=128)
    case_id: str | None = Field(default=None, pattern=r"^\d{1,19}$")
    assigned: bool | None = None


class AssistantIntentCall(BaseModel):
    """Ý định đã kiểm schema, chưa được cấp quyền thực thi."""

    model_config = ConfigDict(extra="forbid")
    intent: str = "UNKNOWN"
    confidence: float = Field(default=0, ge=0, le=1)
    entities: AssistantEntities = Field(default_factory=AssistantEntities)
    needs_clarification: bool = True


class AssistantIntentResponse(BaseModel):
    """Kết quả và số đo thực tế của một lần gọi provider."""

    call: AssistantIntentCall
    model_name: str
    prompt_version: str = "assistant-intent-v1"
    latency_ms: int = Field(default=0, ge=0)
