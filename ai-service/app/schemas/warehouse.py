"""Schemas Pydantic cho giải thuật Map Địa chỉ Kho nhiều tầng."""

from typing import Any

from pydantic import BaseModel, Field


class MatchWarehouseRequest(BaseModel):
    """Payload gửi yêu cầu map kho."""

    raw_address: str = Field(..., description="Địa chỉ hoặc tên kho do nhà xe nhập tự do")
    carrier_id: int | None = Field(None, description="ID nhà xe phục vụ tra cứu thói quen")
    customer_id: int | None = Field(None, description="ID khách hàng để giới hạn kho ứng viên")
    candidate_warehouses: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Danh sách kho ứng viên từ backend",
    )


class MatchWarehouseResponse(BaseModel):
    """Kết quả map địa chỉ kho."""

    matched: bool = Field(default=False, description="Đã tìm thấy kho khớp hay chưa")
    warehouse_id: int | None = Field(None, description="ID kho tìm thấy")
    warehouse_name: str | None = Field(None, description="Tên chuẩn của kho")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Độ tin cậy của thuật toán map")
    source: str = Field(
        default="unresolved",
        description="Nguồn map: plan_cont | habit | fuzzy | vector | llm | unresolved",
    )
