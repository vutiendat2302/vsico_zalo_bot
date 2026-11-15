"""Kiểm thử local-first và các biên chống tự ghép sai."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from src.domain.models import ExtractedContainerLine
from src.handlers.plan_resolution_engine import PlanResolutionEngine
from src.parsing.local_nlp_extractor import message_dates


def plan(**values):
    """Tạo kế hoạch kiểm thử không truy cập dữ liệu vận hành."""
    data = {
        "id": 1,
        "plan_date": date(2026, 11, 15),
        "carrier_id": 10,
        "order_type": "LOAD",
        "container_no": None,
        "container_size": "40",
        "planned_truck_plate": None,
        "customer_id": 1,
        "warehouse_id": 1,
        "customer_name": "Khách A",
        "warehouse_name": "Kho A",
        "delivery_address": None,
        "required_time": "07:00",
        "booking_no": None,
        "container_warning": None,
        "container_ownership": 1,
    }
    data.update(values)
    return SimpleNamespace(**data)


def test_relative_time_from_original_timestamp():
    """Tin UTC sát nửa đêm được quy đổi sang ngày Việt Nam trước khi cộng ngày."""
    assert message_dates("mai đóng", datetime(2026, 11, 14, 18, tzinfo=UTC)) == ["2026-11-16"]
    assert message_dates("xe đi", datetime(2026, 11, 15, 20)) == ["2026-11-15", "2026-11-16"]


def test_single_slot_without_evidence_is_not_auto():
    """Một slot duy nhất không đồng nghĩa đủ căn cứ tự ghép."""
    result = PlanResolutionEngine.resolve(
        ExtractedContainerLine(order_type="LOAD"), [plan()], 10, ["2026-11-15"]
    )
    assert result.action == "ASK_CARRIER"


def test_wrong_carrier_cannot_win_with_booking():
    """Booking đúng không vượt qua điều kiện nhà xe."""
    line = ExtractedContainerLine(order_type="LOAD", booking_no="123")
    result = PlanResolutionEngine.resolve(
        line, [plan(carrier_id=20, booking_no="123")], 10, ["2026-11-15"]
    )
    assert result.action == "ESCALATE_DHVT_WEB"
    assert "CARRIER_MISMATCH" in result.candidates[0].exclusions


def test_tied_warehouse_requires_question():
    """Hai lệnh cùng kho không được chọn dòng đầu tiên."""
    line = ExtractedContainerLine(order_type="LOAD", warehouse_hint="Kho A")
    result = PlanResolutionEngine.resolve(line, [plan(), plan(id=2)], 10, ["2026-11-15"])
    assert result.action == "ASK_CARRIER"


def test_shadow_keeps_strong_load_proposal_for_web():
    """Lệnh đóng khó cần xác nhận dữ liệu thật trước khi bật tự ghi."""
    line = ExtractedContainerLine(order_type="LOAD", warehouse_hint="Kho A", eta_time="07:00")
    result = PlanResolutionEngine.resolve(line, [plan()], 10, ["2026-11-15"])
    assert result.action == "ESCALATE_DHVT_WEB"
    assert result.selected_plan_id == "1"
