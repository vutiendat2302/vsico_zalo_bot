"""Danh mục công cụ đóng; quyền thực thi không phụ thuộc đề xuất của AI."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.infrastructure.models import ZaloMessage

from .schemas import AssistantReply, ScopeContext, ToolCall
from .tools_carrier import run_carrier
from .tools_customer import run_customer
from .tools_dhvt import run_dhvt

CUSTOMER_TOOLS = (
    "customer_get_trip_detail",
    "customer_list_trips_by_date",
    "customer_list_trips_by_status",
    "customer_get_vehicle_driver",
    "customer_query_schedule",
    "customer_get_summary",
    "customer_get_trip_changes",
    "customer_create_change_request",
    "customer_get_request_status",
)
CARRIER_TOOLS = (
    "carrier_list_plans_by_date",
    "carrier_list_incomplete_plans",
    "carrier_get_order_detail",
    "carrier_get_vehicle_schedule",
    "carrier_check_submission_status",
    "carrier_supplement_trip",
    "carrier_request_vehicle_update",
    "carrier_fix_recent_submission",
    "carrier_list_pending_cases",
    "carrier_report_issue_or_cancel",
    "carrier_get_summary",
)
DHVT_TOOLS = (
    "dhvt_get_daily_overview",
    "dhvt_get_unassigned_plans",
    "dhvt_get_order_or_cont_detail",
    "dhvt_get_vehicle_trips",
    "dhvt_get_entity_stats",
    "dhvt_detect_duplicate_vehicles",
    "dhvt_get_container_warnings",
    "dhvt_get_validation_failures",
    "dhvt_get_delivery_and_sync_errors",
    "dhvt_get_priority_digest",
    "dhvt_explain_review_case",
    "dhvt_analyze_change_impact",
    "dhvt_get_audit_timeline",
    "dhvt_get_bot_performance",
)
WRITE_TOOLS = frozenset(
    {
        "customer_create_change_request",
        "carrier_supplement_trip",
        "carrier_request_vehicle_update",
        "carrier_fix_recent_submission",
        "carrier_report_issue_or_cancel",
        "CONFIRM",
    }
)


@dataclass(frozen=True)
class ToolSpec:
    """Metadata công cụ để kiểm quyền và giới hạn fallback chỉ đọc."""

    name: str
    allowed_roles: frozenset[str]
    description: str
    read_only: bool = True


REGISTRY = {
    name: ToolSpec(name, frozenset([role]), name.replace("_", " "), name not in WRITE_TOOLS)
    for role, names in [
        ("CUSTOMER", CUSTOMER_TOOLS),
        ("CARRIER", CARRIER_TOOLS),
        ("DHVT", DHVT_TOOLS),
    ]
    for name in names
}
REGISTRY["get_role_help"] = ToolSpec(
    "get_role_help", frozenset(["CUSTOMER", "CARRIER", "DHVT"]), "Hướng dẫn theo vai trò"
)
REGISTRY["CONFIRM"] = ToolSpec(
    "CONFIRM", frozenset(["CARRIER"]), "Xác nhận đề xuất của chính nhà xe", False
)


def allowed_tools(scope: ScopeContext) -> list[str]:
    """Chỉ cung cấp công cụ đọc đúng vai trò cho bộ phân tích LLM."""
    return [t.name for t in REGISTRY.values() if scope.role in t.allowed_roles and t.read_only]


def execute(
    db: Session, scope: ScopeContext, call: ToolCall, message: ZaloMessage
) -> AssistantReply:
    """Kiểm quyền lại ở biên thực thi, kể cả khi tool được gọi trực tiếp."""
    spec = REGISTRY.get(call.intent)
    if not spec or scope.role not in spec.allowed_roles:
        raise PermissionError("Công cụ không được phép trong vai trò hiện tại.")
    if call.route_source == "llm" and not spec.read_only:
        raise PermissionError("AI không được trực tiếp yêu cầu thay đổi dữ liệu.")
    if call.needs_clarification or call.confidence < 0.8:
        return AssistantReply(
            text="Chưa đủ rõ để tra cứu. Vui lòng ghi mã lệnh, cont, biển số hoặc ngày cụ thể."
        )
    if call.intent == "get_role_help":
        examples = {
            "CUSTOMER": "Mai có chuyến nào? | Booking B123 mấy xe? | Cont … xe nào chở? | Xin đổi giờ LO2447 | Ca #… xong chưa?",
            "CARRIER": "Hôm nay có chuyến nào? | Lệnh nào thiếu chì? | Xe 447.22 chạy chuyến nào? | LO2447 đổi sang xe … | xác nhận #mã đề xuất",
            "DHVT": "Hôm nay bao nhiêu chuyến? | Ca chờ | Xe nào trùng giờ? | Tại sao ca #… cần duyệt? | Tỷ lệ dùng LLM hôm nay?",
        }
        return AssistantReply(
            text=examples[scope.role]
            + "\nGiờ đến là giờ kế hoạch. ĐHVT xử lý duyệt/sửa/hủy trên Web."
        )
    runner = {"CUSTOMER": run_customer, "CARRIER": run_carrier, "DHVT": run_dhvt}[scope.role]
    return runner(db, scope, call, message)
