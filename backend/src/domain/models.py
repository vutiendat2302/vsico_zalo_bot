"""Module Định Nghĩa Các Thực Thể Nghiệp Vụ Thuần Khiết & Bản Ghi Chuẩn (Pure Domain Models).

Chứa lớp dữ liệu `ExtractedContainerLine` biểu diễn thông tin xe và container sau khi bóc tách,
đồng thời hỗ trợ xuất ra đúng cấu trúc **Bản ghi chuẩn (Canonical Record)** cho cả 3 định dạng
`F1`, `F2`, `F3` và `tu_do`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.domain.rules import compact_plate


@dataclass
class ExtractedContainerLine:
    """Thông tin một dòng xe / container bóc tách được từ tin nhắn nhà xe (mỗi container 1 bản ghi)."""

    line_no: int = 1
    line_text: str = ""
    source_format: str = "tu_do"  # 'F1', 'F2', 'F3' hoặc 'tu_do'
    plan_date: Optional[str] = None  # 'YYYY-MM-DD'
    truck_plate: Optional[str] = None  # Dạng chuẩn hiển thị: '50H-049.15'
    raw_truck_plate: Optional[str] = None  # Dạng gốc trong tin: '50H-04915' hoặc '15C17066'
    trailer_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    container_no: Optional[str] = None
    container_size: Optional[str] = None  # '20', '40', '45'...
    seal_no: Optional[str] = None
    booking_no: Optional[str] = None
    order_type: Optional[str] = None  # 'dong' hoặc 'tra'
    inferred_order_type: bool = False
    warehouse_hint: Optional[str] = None  # location_raw
    customer_hint: Optional[str] = None  # customer_raw
    customer_code_or_id: Optional[Any] = None  # Mã khách sau khi tra cứu
    warehouse_code_or_id: Optional[Any] = None  # Mã kho sau khi tra cứu
    match_source: str = "unmatched"  # 'transport_plan', 'customer_alias', 'direct_match', 'unmatched'
    eta_text: Optional[str] = None
    eta_time: Optional[str] = None  # Chuẩn 'HH:MM' (ví dụ: '08:00')
    estimated_at: Optional[datetime] = None
    is_time_vague: bool = False
    is_container_pending: bool = False
    is_seal_pending: bool = False
    has_conflicting_mapping: bool = False
    note: Optional[str] = None
    confidence: float = 0.95
    check_digit_valid: Optional[bool] = None
    target_group_id: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    validation_status: str = "pending"

    @property
    def plate_compact(self) -> Optional[str]:
        """Biển số đầu kéo viết liền chuẩn hóa cho Bản ghi chuẩn (ví dụ: '50H04915', '15C17066')."""
        return compact_plate(self.truck_plate or self.raw_truck_plate)

    @property
    def canonical_cont_size(self) -> Optional[str]:
        """Kích cỡ container rút gọn về '20' / '40' / '45' cho Bản ghi chuẩn."""
        if not self.container_size:
            return None
        for sz in ("20", "40", "45"):
            if self.container_size.startswith(sz):
                return sz
        return self.container_size

    def to_canonical_record(self) -> dict[str, Any]:
        """Xuất ra đúng cấu trúc 'Bản ghi chuẩn' (mỗi container một bản ghi) theo đặc tả Mục 2."""
        return {
            "source_format": self.source_format,
            "plan_date": self.plan_date,
            "order_type": self.order_type,
            "customer_raw": self.customer_hint,
            "customer_id": self.customer_code_or_id,
            "location_raw": self.warehouse_hint,
            "warehouse_id": self.warehouse_code_or_id,
            "plate": self.plate_compact,
            "driver_name": self.driver_name,
            "driver_phone": self.driver_phone,
            "cont_no": self.container_no,
            "cont_size": self.canonical_cont_size,
            "seal_no": self.seal_no,
            "eta": self.eta_time,
            "match_source": self.match_source,
        }

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi toàn bộ thuộc tính dòng container kèm `canonical_record` sang từ điển JSON."""
        return {
            "line_no": self.line_no,
            "line_text": self.line_text,
            "source_format": self.source_format,
            "plan_date": self.plan_date,
            "truck_plate": self.truck_plate,
            "plate": self.plate_compact,
            "raw_truck_plate": self.raw_truck_plate,
            "trailer_plate": self.trailer_plate,
            "driver_name": self.driver_name,
            "driver_phone": self.driver_phone,
            "container_no": self.container_no,
            "container_size": self.container_size,
            "cont_size": self.canonical_cont_size,
            "seal_no": self.seal_no,
            "booking_no": self.booking_no,
            "order_type": self.order_type,
            "inferred_order_type": self.inferred_order_type,
            "warehouse_hint": self.warehouse_hint,
            "customer_hint": self.customer_hint,
            "customer_id": self.customer_code_or_id,
            "warehouse_id": self.warehouse_code_or_id,
            "match_source": self.match_source,
            "eta_text": self.eta_text,
            "eta": self.eta_time,
            "estimated_at": self.estimated_at.isoformat() if self.estimated_at else None,
            "is_time_vague": self.is_time_vague,
            "is_container_pending": self.is_container_pending,
            "is_seal_pending": self.is_seal_pending,
            "has_conflicting_mapping": self.has_conflicting_mapping,
            "note": self.note,
            "confidence": self.confidence,
            "check_digit_valid": self.check_digit_valid,
            "warnings": self.warnings,
            "validation_status": self.validation_status,
            "canonical_record": self.to_canonical_record(),
        }
