"""Module Định Nghĩa Các Thực Thể Nghiệp Vụ Thuần Khiết & Bản Ghi Chuẩn (Pure Domain Models).

Chứa lớp dữ liệu `ExtractedContainerLine` biểu diễn thông tin xe và container sau khi bóc tách,
đồng thời hỗ trợ xuất ra đúng cấu trúc **Bản ghi chuẩn (Canonical Record)** cho cả 3 định dạng
`F1`, `F2`, `F3` và `tu_do`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.domain.enums import ValidationStatus
from src.domain.rules import compact_plate


@dataclass
class ExtractedContainerLine:
    """Thông tin một dòng xe / container bóc tách được từ tin nhắn nhà xe (mỗi container 1 bản ghi)."""

    line_no: int = 1
    line_text: str = ""
    source_format: str = "tu_do"  # 'F1', 'F2', 'F3' hoặc 'tu_do'
    plan_date: Optional[str] = None  # 'YYYY-MM-DD'
    truck_plate: Optional[str] = None  # Dạng chuẩn hiển thị: '50H-049.15'
    raw_truck_plate: Optional[str] = None  # Dạng thô ban đầu từ tin nhắn
    trailer_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    container_no: Optional[str] = None
    container_size: Optional[str] = None  # '20', '40', '45'...
    seal_no: Optional[str] = None
    booking_no: Optional[str] = None
    order_type: Optional[str] = None  # 'LOAD' hoặc 'RETURN'
    inferred_order_type: bool = False
    warehouse_hint: Optional[str] = None
    customer_hint: Optional[str] = None
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
    evidence: Optional[str] = None
    confidence: float = 0.95
    check_digit_valid: Optional[bool] = None
    target_group_id: Optional[str] = None
    carrier_id: Optional[int] = None
    transport_plan_id: Optional[int] = None
    warnings: list[str] = field(default_factory=list)
    validation_status: str = ValidationStatus.PENDING.value

    @property
    def plate_compact(self) -> Optional[str]:
        """Biển số đầu kéo viết liền chuẩn hóa (ví dụ: '50H04915', '15C17066')."""
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
        """Xuất ra Bản ghi chuẩn tinh gọn gồm các trường cốt lõi đồng bộ DB/TMS."""
        return {
            "plan_date": self.plan_date,
            "order_type": self.order_type,
            "customer_id": self.customer_code_or_id,
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
        """Chuyển đổi các thông tin quan trọng của dòng container sang từ điển JSON."""
        return {
            "line_no": self.line_no,
            "plate": self.plate_compact,
            "driver_name": self.driver_name,
            "driver_phone": self.driver_phone,
            "container_no": self.container_no,
            "cont_size": self.canonical_cont_size,
            "seal_no": self.seal_no,
            "booking_no": self.booking_no,
            "order_type": self.order_type,
            "customer_id": self.customer_code_or_id,
            "warehouse_id": self.warehouse_code_or_id,
            "eta": self.eta_time,
            "confidence": self.confidence,
            "check_digit_valid": self.check_digit_valid,
            "validation_status": self.validation_status,
            "warnings": self.warnings,
        }
