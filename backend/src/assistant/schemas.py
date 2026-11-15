"""Hợp đồng nội bộ của bộ định tuyến và công cụ trợ lý."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["CUSTOMER", "CARRIER", "DHVT"]


class Entities(BaseModel):
    """Tham số tra cứu; không cho phép AI đưa vào quyền hoặc SQL."""

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
    order_type: str | None = Field(default=None, max_length=16)
    region: int | None = Field(default=None, ge=1, le=3)
    group_by_region: bool | None = None
    case_id: str | None = Field(default=None, pattern=r"^\d{1,19}$")
    assigned: bool | None = None


class ToolCall(BaseModel):
    """Đề xuất công cụ qua local hoặc LLM; backend kiểm tra lại quyền."""

    model_config = ConfigDict(extra="forbid")
    intent: str = "UNKNOWN"
    confidence: float = Field(default=0, ge=0, le=1)
    route_source: Literal["local_rule", "local_nlp", "llm"] = "local_rule"
    entities: Entities = Field(default_factory=Entities)
    needs_clarification: bool = False


class RouteScope(BaseModel):
    """Một tuyến khách hàng được phép xem, giữ nguyên giới hạn loại lệnh."""

    customer_id: int
    warehouse_id: int | None = None
    order_type: str | None = None


class ScopeContext(BaseModel):
    """Danh tính được dựng từ DB, không nhận từ nội dung tin hoặc LLM."""

    model_config = ConfigDict(frozen=True)
    role: Role
    group_id: int
    zalo_group_id: str
    sender_id: str
    carrier_id: int | None = None
    user_id: int | None = None
    routes: tuple[RouteScope, ...] = ()
    reference_time: datetime


class AssistantReply(BaseModel):
    """Kết quả công cụ không chứa ORM, kèm trạng thái để lưu audit."""

    text: str
    needs_review: bool = False
    plan_ids: list[str] = Field(default_factory=list)
