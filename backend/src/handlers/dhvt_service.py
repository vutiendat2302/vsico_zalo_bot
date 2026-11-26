"""Dịch vụ điều phối thông báo và leo thang giữa Bot và Điều hành vận tải (ĐHVT).

Tuân thủ đặc tả Mục II.1.3a, 2.3a và 2.3c trong `backend/zalo.md`:
1. Chống trùng lặp ca duyệt (`create_or_merge_review_case`): gộp ca đang mở cùng `case_type` và `container`.
2. Gửi thông báo một chiều vào nhóm Zalo ĐHVT theo đúng 3 form mẫu chuẩn (không dùng icon/emoji):
   - Form 1 (`review_case`): Ca cần duyệt kèm container, nhà xe, lý do, gợi ý và link Web `/reviews`.
   - Form 2 (`pending_outbound`): Tin gửi khách đang ở trạng thái chờ duyệt kèm link Web `/results`.
   - Form 3 (`system_alert`): Cảnh báo hệ thống / lỗi gửi Zalo / lỗi đồng bộ TMS / quá hạn.
3. Lưu thói quen kho (`WarehouseAlias`) khi ĐHVT xác nhận ánh xạ kho trên Web.
4. Kiểm tra quá hạn (`BotReply`, `ReviewCase`, `OutboundMessage`) để nhắc ĐHVT và leo thang Admin.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import re
import unicodedata
from typing import Any, Iterator, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.short_link import ShortEntityKind, encode_short_token
from src.domain.enums import (
    CorrectionStatus,
    GroupRole,
    OutboundStatus,
    ReviewStatus,
)
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    Carrier,
    ContainerJob,
    OutboundMessage,
    ReviewCase,
    TransportPlan,
    TruckRecord,
    WarehouseAlias,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher


_CASE_TYPE_LABELS: dict[str, str] = {
    "OUTBOUND_PENDING_APPROVAL": "Duyệt gửi thông báo khách hàng",
    "group_manual_review": "Tin chờ ĐHVT duyệt trước khi gửi khách",
    "GROUP_MANUAL_REVIEW": "Tin chờ ĐHVT duyệt trước khi gửi khách",
    "REVIEW_CHANGE_AFTER_SENT": "Đề xuất cập nhật sau khi đã báo khách",
    "UPDATE_REQUIRES_APPROVAL": "Nhà xe cập nhật chuyến đã phát hành",
    "UPDATE_INCOMPLETE": "Cập nhật thông tin xe còn thiếu",
    "PLAN_FIELD_CONFLICT": "Thông tin nhà xe báo lệch với kế hoạch",
    "PLAN_SYNC_REQUIRED": "Nhiều kế hoạch trùng khớp, cần chọn 1 lệnh",
    "CARRIER_MISMATCH": "Lệch nhà xe phụ trách kế hoạch",
    "SHIPPING_NOT_FOUND": "Chưa tìm thấy kế hoạch phù hợp",
    "ROUTING_NOT_FOUND": "Chưa xác định nhóm khách hàng",
    "OUTBOUND_SEND_FAILED": "Gửi thông báo Zalo tới khách hàng chưa thành công",
    "CANCEL_REQUEST": "Nhà xe đề nghị hủy chuyến",
    "CUSTOMER_CHANGE_REQUEST": "Khách hàng yêu cầu thay đổi/hủy chuyến",
    "missing_fields": "Thiếu hoặc sai thông tin điều xe",
    "MISSING_FIELDS": "Thiếu hoặc sai thông tin điều xe",
    "invalid_check_digit": "Số container chưa đúng chuẩn kiểm tra",
    "INVALID_CHECK_DIGIT": "Số container chưa đúng chuẩn kiểm tra",
    "MISSING_INFO": "Thiếu thông tin điều phối",
    "WAREHOUSE_LOW_CONFIDENCE": "Cần xác nhận kho đóng/trả",
    "AMBIGUOUS_PLAN": "Nhiều kế hoạch trùng khớp",
    "AMBIGUOUS_SUPPLEMENT": "Tin bổ sung chưa rõ chuyến",
    "MISSING_CONTAINER_FOR_UPDATE": "Yêu cầu đổi xe chưa rõ số container",
    "PLAN_CONFLICT": "Xung đột thông tin kế hoạch",
    "INVALID_CONTAINER_CHECKDIGIT": "Số container chưa đúng chuẩn kiểm tra",
    "DUPLICATE_OR_CONFLICT": "Trùng lặp / xung đột dữ liệu",
    "CARRIER_CHANGE_REQUEST": "Nhà xe đề nghị đổi thông tin",
    "CARRIER_CANCEL_OR_ISSUE": "Nhà xe báo hủy / sự cố",
    "CARRIER_CORRECTION_OVERDUE": "Nhà xe quá hạn bổ sung",
    "COMBINED_RO_LO_REVIEW": "Lệnh đóng kết hợp (RO + LO) chờ duyệt",
    "COMBINED_LO_PENDING_CONFIRM": "Lệnh đóng kết hợp chờ xác nhận",
    "ZALO_OA_HEALTH_ALERT": "Cảnh báo sự cố kết nối Zalo OA",
    "OTHER": "Cần ĐHVT kiểm tra",
}

_CASE_TYPE_LABELS_OVERRIDE: dict[str, str] = {
    "COMBINED_RO_LO_REVIEW": "Lệnh đóng kết hợp chờ xác nhận",
}

_WARNING_CODE_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("MISSING_TRUCK_PLATE", "Biển số xe đầu kéo chưa hợp lệ"),
    ("INVALID_TRUCK_PLATE_FORMAT", "Biển số xe đầu kéo chưa đúng định dạng 5 chữ số"),
    ("MISSING_TRAILER_PLATE", "Chưa có biển số rơ-moóc"),
    ("INVALID_TRAILER_PLATE_FORMAT", "Biển số rơ-moóc chưa đúng định dạng 5 chữ số"),
    ("MISSING_DRIVER_NAME", "Chưa có tên tài xế"),
    ("MISSING_DRIVER_PHONE", "Chưa có SĐT tài xế"),
    ("INVALID_DRIVER_PHONE", "Số điện thoại tài xế chưa đúng định dạng 10 số"),
    ("MISSING_CONTAINER_NO", "Chưa có số container"),
    ("PENDING_CONTAINER_NO", "Nhà xe đang chờ cấp số container"),
    ("INVALID_CONTAINER_FORMAT", "Số container chưa đúng định dạng tiêu chuẩn"),
    ("AMBIGUOUS_VEHICLE_CONTAINER_MAPPING", "Chưa xác định rõ xe nào tương ứng với container"),
)

_SHELL_WARNING_VI: dict[str, str] = {
    "empty_drop": "chỉ định hạ rỗng (không tự ghép đóng hàng)",
    "over_combined": "vượt số lượng ghép kết hợp",
    "other_requested": "đã được đơn vị khác đăng ký",
    "soc": "vỏ thuộc sở hữu chủ hàng",
}

_ACTIVE_ALERT_BATCH: ContextVar[Optional[list[dict[str, Any]]]] = ContextVar(
    "dhvt_active_alert_batch", default=None
)


def humanize_reason_text(reason: Optional[str]) -> str:
    """Chuyển các mã cảnh báo kỹ thuật sang câu tiếng Việt tự nhiên, tuyệt đối không lộ mã hệ thống."""
    if not reason:
        return ""
    text = str(reason)
    # Gỡ các ngoặc mã kỹ thuật như (empty_drop), (APPROVED), (REJECTED), (SOC), (RO + LO)
    for code, vi in _SHELL_WARNING_VI.items():
        text = re.sub(
            rf"cảnh báo cấm ghép\s*\(\s*{re.escape(code)}\s*\)",
            f"cảnh báo {vi}",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(rf"\(\s*{re.escape(code)}\s*\)", f"({vi})", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(\s*Trạng thái:\s*[A-Z_]+\s*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(\s*(?:APPROVED|REJECTED|PENDING|SYNCED|NOOP|RO\s*\+\s*LO)\s*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"ISO6346_CHECK_DIGIT_MISMATCH\(expected=\d,actual=\d\)",
        "Số container chưa đúng chữ số kiểm tra tiêu chuẩn",
        text,
    )
    text = re.sub(
        r"TRAILER_PLATE_IN_TRUCK_POSITION\(([^)]+)\)",
        r"Biển \1 có thể đang được nhập nhầm vào vị trí biển xe đầu kéo",
        text,
    )
    for code, vi in _WARNING_CODE_TRANSLATIONS:
        text = text.replace(code, vi)
    text = re.sub(r"\s*\|\s*Lan\s*\d+\s*:\s*", "; ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(" ;,")
    return text


def humanize_reason_bullets(
    reason: Optional[str],
    details: Optional[dict[str, Any]] = None,
) -> tuple[str, list[str], bool]:
    """Phân tích lý do thô thành câu dẫn và danh sách bullet tiếng Việt tự nhiên, không lặp lại log kỹ thuật.

    Returns:
        tuple[str, list[str], bool]: `(câu_dẫn, danh_sách_bullet, có_nhiều_lần_kiểm_tra)`.
    """
    raw = str(reason or "").strip()
    det = details or {}
    occ = int(det.get("occurrence_count", 1) or 1)
    is_multi_check = occ > 1 or bool(re.search(r"\bLan\s*[2-9]\b", raw, re.IGNORECASE))
    intro = (
        "Qua các lần kiểm tra, hệ thống đã ghi nhận một số thông tin cần đối chiếu:"
        if is_multi_check
        else "Hệ thống chưa thể xác nhận đầy đủ thông tin do:"
    )

    bullets: list[str] = []
    recognized_defect = False

    trailer_in_truck = re.findall(r"TRAILER_PLATE_IN_TRUCK_POSITION\(([^)]+)\)", raw)
    has_missing_truck = "MISSING_TRUCK_PLATE" in raw or "INVALID_TRUCK_PLATE_FORMAT" in raw
    has_missing_trailer = "MISSING_TRAILER_PLATE" in raw
    has_invalid_trailer = "INVALID_TRAILER_PLATE_FORMAT" in raw
    has_missing_driver = "MISSING_DRIVER_NAME" in raw
    has_missing_phone = "MISSING_DRIVER_PHONE" in raw
    has_invalid_phone = "INVALID_DRIVER_PHONE" in raw or "10 số bắt đầu bằng 0" in raw.lower()
    has_ambiguous_map = "AMBIGUOUS_VEHICLE_CONTAINER_MAPPING" in raw
    has_missing_cont = "MISSING_CONTAINER_NO" in raw
    has_pending_cont = "PENDING_CONTAINER_NO" in raw
    has_invalid_cont = "INVALID_CONTAINER_FORMAT" in raw or "ISO6346_CHECK_DIGIT_MISMATCH" in raw

    if trailer_in_truck:
        recognized_defect = True
        bullets.append("Biển số xe đầu kéo chưa hợp lệ.")
        for pl in dict.fromkeys(p.strip() for p in trailer_in_truck if p.strip()):
            bullets.append(f"Biển {pl} có thể đang được nhập nhầm vào vị trí biển xe đầu kéo.")
    elif has_missing_truck:
        recognized_defect = True
        bullets.append("Biển số xe đầu kéo chưa hợp lệ hoặc còn thiếu.")

    if has_invalid_cont:
        recognized_defect = True
        bullets.append("Số container chưa đúng định dạng tiêu chuẩn.")
    elif has_missing_cont:
        recognized_defect = True
        bullets.append("Chưa có số container.")
    elif has_pending_cont:
        recognized_defect = True
        bullets.append("Nhà xe đang chờ cấp số container.")

    if has_invalid_trailer:
        recognized_defect = True
        bullets.append("Biển số rơ-moóc chưa hợp lệ.")

    # Gom gọn các mục còn thiếu (rơ-moóc, tên tài xế, SĐT tài xế) thành câu tự nhiên
    missing_group: list[str] = []
    if has_missing_trailer:
        missing_group.append("rơ-moóc")
    if has_missing_driver:
        missing_group.append("tên")
    if has_missing_phone:
        missing_group.append("SĐT")

    if len(missing_group) >= 2:
        recognized_defect = True
        if missing_group == ["rơ-moóc", "tên", "SĐT"]:
            bullets.append("Chưa có đầy đủ thông tin rơ-moóc, tên và SĐT tài xế.")
        elif missing_group == ["tên", "SĐT"]:
            bullets.append("Chưa có đầy đủ tên và SĐT tài xế.")
        elif missing_group == ["rơ-moóc", "tên"]:
            bullets.append("Chưa có đầy đủ thông tin rơ-moóc và tên tài xế.")
        else:
            bullets.append("Chưa có đầy đủ thông tin rơ-moóc và SĐT tài xế.")
    elif len(missing_group) == 1:
        recognized_defect = True
        if has_missing_trailer:
            bullets.append("Chưa có biển số rơ-moóc.")
        elif has_missing_driver:
            bullets.append("Chưa có tên tài xế.")
        elif has_missing_phone:
            bullets.append("Chưa có số điện thoại tài xế.")

    if has_invalid_phone:
        recognized_defect = True
        bullets.append("Số điện thoại tài xế chưa đúng định dạng 10 số.")

    if has_ambiguous_map:
        recognized_defect = True
        bullets.append("Chưa xác định rõ xe nào tương ứng với container.")

    if not recognized_defect and raw:
        clean = humanize_reason_text(raw)
        if clean:
            if not clean.endswith((".", "!", "?")):
                clean += "."
            bullets.append(clean)

    return intro, list(dict.fromkeys(bullets)), is_multi_check


def _resolve_reviewer_display_name(
    actor_display: Optional[str],
    fallback_sender_name: Optional[str] = None,
) -> str:
    """Lấy tên hiển thị rõ ràng của người duyệt, ưu tiên tên thật thay vì tên hệ thống mặc định."""
    clean_actor = (actor_display or "").strip()
    clean_sender = (fallback_sender_name or "").strip()
    generic_names = {"", "quản trị viên hệ thống", "admin", "đhvt", "system", "vsico_bot"}
    if clean_actor and clean_actor.lower() not in generic_names:
        return clean_actor
    if clean_sender and clean_sender.lower() not in generic_names:
        return clean_sender
    return clean_actor or "ĐHVT"

_ORDER_TYPE_LABELS: dict[str, str] = {
    "dong": "Đóng hàng",
    "tra": "Trả hàng",
    "answer": "Trả lời",
}


def _to_int_id(value: Any) -> Optional[int]:
    """Chuyển đổi giá trị ID dạng chuỗi/số sang số nguyên an toàn."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_order_label(order_code: Optional[str], order_type: Optional[str]) -> Optional[str]:
    """Hiển thị mã lệnh kèm tên loại lệnh tiếng Việt gọn gàng."""
    type_label = _ORDER_TYPE_LABELS.get((order_type or "").strip().lower())
    code = (order_code or "").strip().upper()
    if code and type_label:
        return f"{code} ({type_label})"
    if code:
        return code
    return type_label


def _normalize_alias_key(text: str) -> str:
    """Chuẩn hóa bí danh kho về chữ thường không dấu gọn khoảng trắng."""
    decomposed = unicodedata.normalize("NFD", (text or "").strip())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.replace("đ", "d").replace("Đ", "D").lower().split())


class DhvtNotificationService:
    """Bộ điều phối thông báo và hàng đợi ĐHVT trên Web lẫn nhóm Zalo nội bộ."""

    @classmethod
    def find_dhvt_group(cls, db: Session) -> Optional[ZaloGroup]:
        """Tìm nhóm Zalo ĐHVT nội bộ đang hoạt động."""
        return db.scalar(
            select(ZaloGroup)
            .where(
                ZaloGroup.group_role.in_([GroupRole.DHVT.value, "dhvt"]),
                ZaloGroup.is_active == True,  # noqa: E712
                ZaloGroup.is_test == False,  # noqa: E712
            )
            .order_by(ZaloGroup.id.asc())
        )

    @classmethod
    def _is_real_dispatch_enabled(cls, dhvt_group: Optional[ZaloGroup], is_test_msg: bool) -> bool:
        """Kiểm tra điều kiện an toàn để gửi thông báo thực tế vào nhóm ĐHVT."""
        if is_test_msg or not settings.AUTO_DISPATCH_OUTBOUND or not dhvt_group:
            return False
        gid = (dhvt_group.zalo_group_id or "").strip()
        if not gid or gid.startswith(("test_", "pytest_", "dummy_")):
            return False
        return bool(dhvt_group.is_active and not dhvt_group.is_test)

    @classmethod
    def _web_url(cls, path: str) -> str:
        """Tạo liên kết tuyệt đối dẫn tới màn hình xử lý trên Web quản lý."""
        base = (settings.FRONTEND_BASE_URL or "http://localhost:3001").rstrip("/")
        clean_path = path if path.startswith("/") else f"/{path}"
        return f"{base}{clean_path}"

    @classmethod
    def _short_entity_path(cls, kind: ShortEntityKind, entity_id: int | str) -> str:
        """Tạo đường dẫn rút gọn không lộ ID/đường dẫn hệ thống cho ca duyệt hoặc outbound."""
        tok = encode_short_token(kind, int(entity_id), settings.short_link_secret)
        return f"/{tok}"

    @classmethod
    def _short_entity_url(cls, kind: ShortEntityKind, entity_id: int | str) -> str:
        """Tạo URL rút gọn đầy đủ dẫn thẳng tới chi tiết bản duyệt trên Web."""
        return cls._web_url(cls._short_entity_path(kind, entity_id))

    @classmethod
    def _resolve_review_case_context(
        cls,
        db: Optional[Session],
        case_obj: ReviewCase,
        container_no: Optional[str] = None,
        carrier_name: Optional[str] = None,
    ) -> dict[str, Optional[str]]:
        """Tra cứu đầy đủ tên hiển thị thân thiện (nguồn nhóm Zalo, người gửi, mã lệnh RO/LO, khách, kho, nhà xe, xe/moóc/tài xế)."""
        details = dict(case_obj.details or {})
        cont = (container_no or details.get("container_no") or "").strip().upper() or None
        order_code: Optional[str] = str(details.get("order_code") or "").strip() or None
        order_type: Optional[str] = str(details.get("order_type") or "").strip() or None
        secondary_order_label: Optional[str] = None
        if details.get("ro_order_code") and details.get("lo_order_code"):
            secondary_order_label = (
                f"Trả {details.get('ro_order_code')} + Đóng kết hợp {details.get('lo_order_code')}"
            )
        customer_name: Optional[str] = str(details.get("customer_name") or "").strip() or None
        warehouse_name: Optional[str] = str(details.get("warehouse_name") or "").strip() or None
        resolved_carrier: Optional[str] = (carrier_name or str(details.get("carrier_name") or "")).strip() or None
        source_group_name: Optional[str] = str(details.get("source_group_name") or "").strip() or None
        sender_name: Optional[str] = str(details.get("sender_name") or "").strip() or None
        truck_plate: Optional[str] = str(details.get("truck_plate") or "").strip() or None
        trailer_plate: Optional[str] = str(details.get("trailer_plate") or "").strip() or None
        driver_name: Optional[str] = str(details.get("driver_name") or "").strip() or None
        driver_phone: Optional[str] = str(details.get("driver_phone") or "").strip() or None
        target_group_name: Optional[str] = None

        if db is None:
            veh_parts = [p for p in (truck_plate, f"Moóc {trailer_plate}" if trailer_plate else None, driver_name, driver_phone) if p]
            return {
                "order_label": secondary_order_label or _format_order_label(order_code, order_type),
                "container_no": cont,
                "customer_name": customer_name,
                "warehouse_name": warehouse_name,
                "carrier_name": resolved_carrier,
                "source_group_name": source_group_name,
                "sender_name": sender_name,
                "vehicle_driver": " | ".join(veh_parts) or None,
            }

        plan_id = _to_int_id(details.get("selected_plan_id") or details.get("transport_plan_id"))
        plan = db.get(TransportPlan, plan_id) if plan_id else None
        if plan:
            order_code = order_code or (plan.order_code or None)
            order_type = order_type or (plan.order_type or None)
            cont = cont or (plan.container_no or "").strip().upper() or None
            customer_name = customer_name or (plan.customer_name or None)
            warehouse_name = warehouse_name or (plan.warehouse_name or plan.delivery_address or None)
            resolved_carrier = resolved_carrier or (plan.carrier_name or plan.fleet_partner or None)
            truck_plate = truck_plate or (plan.planned_truck_plate or None)
            trailer_plate = trailer_plate or (plan.planned_trailer_plate or None)
            driver_name = driver_name or (plan.driver_name or None)
            driver_phone = driver_phone or (plan.driver_phone or None)
            if not resolved_carrier and plan.carrier_id:
                c_obj = db.get(Carrier, plan.carrier_id)
                if c_obj and c_obj.name:
                    resolved_carrier = c_obj.name

        sec_plan_id = _to_int_id(details.get("secondary_plan_id"))
        if sec_plan_id and not secondary_order_label:
            sec_plan = db.get(TransportPlan, sec_plan_id)
            if sec_plan and plan:
                p1_lbl = _format_order_label(sec_plan.order_code, sec_plan.order_type) or str(sec_plan.id)
                p2_lbl = _format_order_label(plan.order_code, plan.order_type) or str(plan.id)
                secondary_order_label = f"{p1_lbl} + {p2_lbl}"

        if case_obj.container_job_id:
            job = db.get(ContainerJob, case_obj.container_job_id)
            if job:
                cont = cont or (job.container_no or "").strip().upper() or None
                order_type = order_type or (job.order_type or None)
                customer_name = customer_name or (job.customer_hint or None)
                warehouse_name = warehouse_name or (job.warehouse_hint or None)
                if job.truck_record_id:
                    tr = db.get(TruckRecord, job.truck_record_id)
                    if tr:
                        truck_plate = truck_plate or (tr.truck_plate or None)
                        trailer_plate = trailer_plate or (tr.trailer_plate or None)
                        driver_name = driver_name or (tr.driver_name or None)
                        driver_phone = driver_phone or (tr.driver_phone or None)

        outbound_id = _to_int_id(details.get("outbound_message_id"))
        if outbound_id:
            outbound = db.get(OutboundMessage, outbound_id)
            if outbound and outbound.target_group_id:
                tg = db.get(ZaloGroup, outbound.target_group_id)
                if tg and tg.name:
                    target_group_name = tg.name

        if not resolved_carrier:
            carrier_id = _to_int_id(details.get("carrier_id"))
            if carrier_id:
                c_obj = db.get(Carrier, carrier_id)
                if c_obj and c_obj.name:
                    resolved_carrier = c_obj.name

        if case_obj.message_id:
            msg = db.get(ZaloMessage, case_obj.message_id)
            if msg:
                if not sender_name:
                    sender_name = (msg.sender_name or "").strip() or None
                if msg.group_id:
                    src_grp = db.scalar(
                        select(ZaloGroup).where(ZaloGroup.zalo_group_id == msg.group_id)
                    )
                    if src_grp:
                        if not source_group_name:
                            source_group_name = (src_grp.name or src_grp.zalo_group_id or "").strip() or None
                        if not resolved_carrier:
                            if src_grp.carrier_name:
                                resolved_carrier = src_grp.carrier_name
                            else:
                                grp_carrier_id = _to_int_id(src_grp.carrier_id)
                                if grp_carrier_id:
                                    c_obj = db.get(Carrier, grp_carrier_id)
                                    if c_obj and c_obj.name:
                                        resolved_carrier = c_obj.name
                            if not resolved_carrier and (src_grp.group_role or "").upper() in ("SOURCE", "CARRIER"):
                                resolved_carrier = src_grp.name or None
                    elif not source_group_name:
                        source_group_name = msg.group_id

        customer_display = customer_name or target_group_name
        if warehouse_name and len(warehouse_name) > 70:
            warehouse_name = warehouse_name[:67].rstrip() + "..."
        primary_veh = " - ".join(p for p in (truck_plate, driver_name) if p)
        extra_veh = [
            p
            for p in (
                f"Moóc {trailer_plate}" if trailer_plate else None,
                driver_phone,
            )
            if p
        ]
        vehicle_driver = " | ".join(p for p in (primary_veh, *extra_veh) if p) or None

        return {
            "order_label": secondary_order_label or _format_order_label(order_code, order_type),
            "container_no": cont,
            "customer_name": customer_display,
            "warehouse_name": warehouse_name,
            "carrier_name": resolved_carrier,
            "source_group_name": source_group_name,
            "sender_name": sender_name,
            "vehicle_driver": vehicle_driver,
        }

    @classmethod
    def render_review_case_alert(
        cls,
        case_obj: ReviewCase,
        db: Optional[Session] = None,
        container_no: Optional[str] = None,
        carrier_name: Optional[str] = None,
        suggestion: Optional[str] = None,
        priority: str = "NORMAL",
    ) -> str:
        """Form 1: Thông báo ca cần duyệt gửi nhóm ĐHVT theo chuẩn `[VSICO] - ...` thân thiện, rõ vấn đề."""
        link = cls._short_entity_url("r", case_obj.id)
        case_label = _CASE_TYPE_LABELS_OVERRIDE.get(
            case_obj.case_type, _CASE_TYPE_LABELS.get(case_obj.case_type, "Cần ĐHVT kiểm tra")
        )
        ctx = cls._resolve_review_case_context(
            db=db,
            case_obj=case_obj,
            container_no=container_no,
            carrier_name=carrier_name,
        )
        intro, bullets, is_multi_check = humanize_reason_bullets(
            case_obj.reason,
            case_obj.details if isinstance(case_obj.details, dict) else None,
        )

        if is_multi_check or len(bullets) >= 3:
            header = "[VSICO] - 🔎 Cần rà soát thông tin vận chuyển"
        elif case_obj.case_type == "COMBINED_RO_LO_REVIEW":
            header = "[VSICO] - ⚠️ Cần duyệt lệnh đóng kết hợp"
        elif case_obj.case_type in ("missing_fields", "INVALID_CONTAINER_CHECKDIGIT"):
            header = "[VSICO] - ⚠️ Cần xác nhận thông tin điều xe"
        else:
            header = f"[VSICO] - ⚠️ {case_label}"

        sections: list[str] = [header]

        src_parts = [
            f"Nhóm {ctx['source_group_name']}" if ctx.get("source_group_name") else "",
            f"Nhà xe: {ctx['carrier_name']}" if ctx.get("carrier_name") else "",
            f"Người gửi: {ctx['sender_name']}" if ctx.get("sender_name") else "",
        ]
        src_line = " · ".join(p for p in src_parts if p)
        if src_line:
            sections.append(f"Từ: {src_line}")

        info_lines: list[str] = []
        if ctx.get("container_no"):
            info_lines.append(f"📦 Container: {ctx['container_no']}")
        if ctx.get("order_label"):
            info_lines.append(f"• Lệnh liên quan: {ctx['order_label']}")
        party_parts = [
            f"Khách hàng: {ctx['customer_name']}" if ctx.get("customer_name") else "",
            f"Kho: {ctx['warehouse_name']}" if ctx.get("warehouse_name") else "",
        ]
        party_line = " · ".join(p for p in party_parts if p)
        if party_line:
            info_lines.append(f"• {party_line}")
        if ctx.get("vehicle_driver"):
            info_lines.append(f"• Xe & Tài xế: {ctx['vehicle_driver'].replace(' | ', ' · ')}")
        if info_lines:
            sections.append("\n".join(info_lines))

        if bullets:
            bullet_block = intro + "\n" + "\n".join(f"• {b}" for b in bullets)
            sections.append(bullet_block)

        if suggestion:
            sections.append(f"Gợi ý: {humanize_reason_text(suggestion)}")

        sections.append(
            "Thao tác nhanh (trả lời/quote tin nhắn này):\n"
            "• Duyệt: duyệt\n"
            "• Sửa thông tin: sửa <biển số / tài xế / SĐT / số cont>\n"
            "• Từ chối: từ chối <lý do>\n"
            f"🔗 {link}"
        )
        return "\n\n".join(sections)

    @classmethod
    def render_batched_review_cases_alert(
        cls,
        cases: list[dict[str, Any]],
        db: Optional[Session] = None,
    ) -> str:
        """Gom nhiều ca cần duyệt phát sinh cùng lúc cho nhóm ĐHVT thành 1 tin nhắn tổng hợp duy nhất."""
        if len(cases) == 1:
            c = cases[0]
            return cls.render_review_case_alert(
                case_obj=c["case_obj"],
                db=db,
                container_no=c.get("container_no"),
                carrier_name=c.get("carrier_name"),
                suggestion=c.get("suggestion"),
                priority=c.get("priority") or "NORMAL",
            )

        first_ctx = cls._resolve_review_case_context(
            db=db,
            case_obj=cases[0]["case_obj"],
            container_no=cases[0].get("container_no"),
            carrier_name=cases[0].get("carrier_name"),
        )
        src_parts = [
            f"Nhóm {first_ctx['source_group_name']}" if first_ctx.get("source_group_name") else "",
            f"Nhà xe: {first_ctx['carrier_name']}" if first_ctx.get("carrier_name") else "",
            f"Người gửi: {first_ctx['sender_name']}" if first_ctx.get("sender_name") else "",
        ]
        src_line = " · ".join(p for p in src_parts if p)

        sections: list[str] = [f"[VSICO] - ⚠️ Có {len(cases)} yêu cầu điều xe cần ĐHVT kiểm tra"]
        if src_line:
            sections.append(f"Từ: {src_line}")

        item_blocks: list[str] = []
        for idx, item in enumerate(cases[:10], start=1):
            rc: ReviewCase = item["case_obj"]
            ctx = cls._resolve_review_case_context(
                db=db,
                case_obj=rc,
                container_no=item.get("container_no"),
                carrier_name=item.get("carrier_name"),
            )
            _, bullets, _ = humanize_reason_bullets(
                rc.reason, rc.details if isinstance(rc.details, dict) else None
            )
            link = cls._short_entity_url("r", rc.id)
            title_parts = [
                f"📦 Container: {ctx['container_no']}" if ctx.get("container_no") else _CASE_TYPE_LABELS.get(rc.case_type, "Chuyến xe"),
                ctx["order_label"] if ctx.get("order_label") else "",
            ]
            head = " · ".join(p for p in title_parts if p)
            b_lines = "\n".join(f"   • {b}" for b in bullets[:3])
            block = f"{idx}. {head}"
            if b_lines:
                block += f"\n{b_lines}"
            block += f"\n   🔗 {link}"
            item_blocks.append(block)
        if len(cases) > 10:
            item_blocks.append(f"... và {len(cases) - 10} yêu cầu khác trên Web quản lý.")
        sections.append("\n\n".join(item_blocks))
        sections.append("Nhờ anh/chị ĐHVT kiểm tra và hỗ trợ xử lý các yêu cầu trên nhé.")
        return "\n\n".join(sections)

    @classmethod
    def render_overdue_review_alert(
        cls,
        case_obj: ReviewCase,
        remind_count: int,
        db: Optional[Session] = None,
    ) -> str:
        """Render tin nhắc quá hạn / leo thang Admin cho 1 ca duy nhất theo mẫu thân thiện `[VSICO] - ...`."""
        link = cls._short_entity_url("r", case_obj.id)
        ctx = cls._resolve_review_case_context(db=db, case_obj=case_obj)
        intro, bullets, is_multi_check = humanize_reason_bullets(
            case_obj.reason, case_obj.details if isinstance(case_obj.details, dict) else None
        )
        audience = "Admin" if remind_count >= 2 else "ĐHVT"
        overdue_label = f"quá hạn xử lý lần {remind_count}" if remind_count >= 2 else "chờ xử lý hơn 30 phút"

        if is_multi_check or len(bullets) >= 3:
            sections = ["[VSICO] - 🔎 Cần rà soát thông tin vận chuyển"]
            if ctx.get("container_no"):
                sections.append(f"📦 Container: {ctx['container_no']}")
            elif ctx.get("order_label"):
                sections.append(f"📦 Lệnh: {ctx['order_label']}")
            if bullets:
                sections.append(intro + "\n" + "\n".join(f"• {b}" for b in bullets))
            sections.append(f"⏳ Yêu cầu đã {overdue_label}.")
            sections.append(
                f"Nhờ anh/chị {audience} kiểm tra lại thông tin hiện tại và hỗ trợ cập nhật các mục còn thiếu nhé."
            )
            sections.append(f"🔗 {link}")
            return "\n\n".join(sections)

        sections = ["[VSICO] - ⚠️ Cần xác nhận thông tin điều xe"]
        if ctx.get("container_no"):
            sections.append(f"📦 Container: {ctx['container_no']}")
        elif ctx.get("order_label"):
            sections.append(f"📦 Lệnh: {ctx['order_label']}")
        if bullets:
            sections.append(intro + "\n" + "\n".join(f"• {b}" for b in bullets))
        sections.append(
            f"Yêu cầu đã {overdue_label}. Nhờ anh/chị {audience} hỗ trợ kiểm tra nhé."
        )
        sections.append(f"🔗 {link}")
        return "\n\n".join(sections)

    @classmethod
    def render_batched_overdue_alert(
        cls,
        overdue_items: list[dict[str, Any]],
        db: Optional[Session] = None,
    ) -> str:
        """Gom nhiều yêu cầu quá hạn cùng lúc vào 1 thông báo duy nhất cho nhóm ĐHVT / Admin."""
        if len(overdue_items) == 1:
            item = overdue_items[0]
            if item["kind"] == "review_case":
                return cls.render_overdue_review_alert(item["case_obj"], item["remind_count"], db=db)
            return (
                "[VSICO] - ⚠️ Tin gửi khách hàng chờ duyệt quá hạn\n\n"
                f"• Nhóm khách hàng: {item['group_label']}\n"
                f"⏳ Tin đã chờ duyệt quá {item['label']}.\n\n"
                f"Nhờ anh/chị {'Admin' if item['remind_count'] >= 2 else 'ĐHVT'} hỗ trợ kiểm tra nhé.\n\n"
                f"🔗 {item['link']}"
            )

        has_admin = any(int(it.get("remind_count", 1)) >= 2 for it in overdue_items)
        audience = "Admin / ĐHVT" if has_admin else "ĐHVT"
        sections = [f"[VSICO] - ⚠️ Có {len(overdue_items)} yêu cầu quá hạn cần kiểm tra"]
        blocks: list[str] = []
        for idx, item in enumerate(overdue_items[:10], start=1):
            if item["kind"] == "review_case":
                rc: ReviewCase = item["case_obj"]
                ctx = cls._resolve_review_case_context(db=db, case_obj=rc)
                _, bullets, _ = humanize_reason_bullets(
                    rc.reason, rc.details if isinstance(rc.details, dict) else None
                )
                link = cls._short_entity_url("r", rc.id)
                tag = f"Quá hạn lần {item['remind_count']}" if item["remind_count"] >= 2 else "Chờ > 30 phút"
                head = (
                    f"📦 Container: {ctx['container_no']} ({tag})"
                    if ctx.get("container_no")
                    else f"📦 {_CASE_TYPE_LABELS.get(rc.case_type, 'Yêu cầu điều xe')} ({tag})"
                )
                summary_txt = " ".join(bullets[:2])
                block = f"{idx}. {head}"
                if summary_txt:
                    block += f"\n   • {summary_txt}"
                block += f"\n   🔗 {link}"
                blocks.append(block)
            else:
                tag = f"Quá hạn lần {item['remind_count']}" if item["remind_count"] >= 2 else "Chờ > 30 phút"
                blocks.append(
                    f"{idx}. 📢 Tin chờ duyệt gửi {item['group_label']} ({tag})\n"
                    f"   🔗 {item['link']}"
                )
        if len(overdue_items) > 10:
            blocks.append(f"... và {len(overdue_items) - 10} yêu cầu quá hạn khác trên Web quản lý.")
        sections.append("\n\n".join(blocks))
        sections.append(f"Nhờ anh/chị {audience} kiểm tra và hỗ trợ xử lý các yêu cầu trên nhé.")
        return "\n\n".join(sections)

    @classmethod
    def render_pending_outbound_alert(
        cls,
        outbound: OutboundMessage,
        target_group_name: str,
        containers: list[str],
        reason: str,
        review_case_id: Optional[int] = None,
        source_group_name: Optional[str] = None,
        carrier_name: Optional[str] = None,
        sender_name: Optional[str] = None,
    ) -> str:
        """Form 2: Thông báo tin chờ duyệt gửi nhóm Zalo ĐHVT theo chuẩn `[VSICO] - ...`."""
        if review_case_id:
            link = cls._short_entity_url("r", review_case_id)
        else:
            link = cls._short_entity_url("o", outbound.id)
        cont_str = ", ".join(c for c in containers if c) or "Chưa rõ"
        order_label = _format_order_label(None, outbound.order_type) or outbound.order_type
        sections = ["[VSICO] - ⚠️ Tin gửi khách hàng đang chờ duyệt"]
        src_parts = [
            f"Nhóm {source_group_name}" if source_group_name else "",
            f"Nhà xe: {carrier_name}" if carrier_name else "",
            f"Người gửi: {sender_name}" if sender_name else "",
        ]
        src_line = " · ".join(p for p in src_parts if p)
        if src_line:
            sections.append(f"Từ: {src_line}")
        sections.append(
            "\n".join(
                [
                    f"📦 Container: {cont_str} · Lệnh: {order_label}",
                    f"• Nhóm khách hàng: {target_group_name}",
                    f"• Lý do chờ: {humanize_reason_text(reason)}",
                ]
            )
        )
        sections.append(
            "Thao tác nhanh (trả lời/quote tin nhắn này):\n"
            "• Duyệt: duyệt\n"
            "• Sửa thông tin: sửa <biển số / tài xế / SĐT / số cont>\n"
            "• Từ chối: từ chối <lý do>\n"
            f"🔗 {link}"
        )
        return "\n\n".join(sections)

    @classmethod
    def render_system_alert(
        cls,
        title: str,
        body: str,
        web_path: str = "/reviews",
    ) -> str:
        """Form 3: Cảnh báo hệ thống gửi nhóm Zalo ĐHVT theo chuẩn `[VSICO] - ⚙️ ...`."""
        link = cls._web_url(web_path)
        return (
            f"[VSICO] - ⚙️ {title}\n\n"
            f"{humanize_reason_text(body)}\n\n"
            f"🔗 Kiểm tra trên Web: {link}"
        )

    @classmethod
    def begin_alert_batch(cls) -> tuple[Any, list[dict[str, Any]]]:
        """Mở bộ đệm gom cảnh báo ĐHVT trong cùng 1 tin nhắn đa chuyến mà không cần lồng thụt dòng."""
        bucket: list[dict[str, Any]] = []
        token = _ACTIVE_ALERT_BATCH.set(bucket)
        return token, bucket

    @classmethod
    def end_alert_batch(
        cls,
        db: Session,
        token: Any,
        bucket: list[dict[str, Any]],
        is_test_msg: bool = False,
    ) -> None:
        """Đóng bộ đệm gom cảnh báo ĐHVT và phát duy nhất 1 tin nhắn tổng hợp nếu có phát sinh ca."""
        _ACTIVE_ALERT_BATCH.reset(token)
        if bucket:
            cls._flush_alert_batch(db, bucket, is_test_msg=is_test_msg)

    @classmethod
    @contextmanager
    def batch_dhvt_alerts(cls, db: Session, is_test_msg: bool = False) -> Iterator[list[dict[str, Any]]]:
        """Gom toàn bộ thông báo ca cần duyệt phát sinh trong cùng 1 tin nhắn/lô gửi thành 1 tin duy nhất."""
        bucket: list[dict[str, Any]] = []
        token = _ACTIVE_ALERT_BATCH.set(bucket)
        try:
            yield bucket
        finally:
            _ACTIVE_ALERT_BATCH.reset(token)
            if bucket:
                cls._flush_alert_batch(db, bucket, is_test_msg=is_test_msg)

    @classmethod
    def _flush_alert_batch(
        cls,
        db: Session,
        bucket: list[dict[str, Any]],
        is_test_msg: bool = False,
    ) -> None:
        """Phát 1 tin nhắn tổng hợp (hoặc 1 tin đơn nếu chỉ có 1 ca) cho toàn bộ lô cảnh báo ĐHVT."""
        alert_text = cls.render_batched_review_cases_alert(bucket, db=db)
        dhvt_group = cls.find_dhvt_group(db)
        zalo_mid: Optional[str] = None
        if cls._is_real_dispatch_enabled(dhvt_group, is_test_msg):
            ok, z_mid, _ = ZaloDispatcher.send_to_group(
                group_id=dhvt_group.zalo_group_id,
                message=alert_text,
            )
            if ok and z_mid:
                zalo_mid = z_mid
        for item in bucket:
            rc: ReviewCase = item["case_obj"]
            if zalo_mid:
                updated_d = dict(rc.details or {})
                updated_d["dhvt_zalo_msg_id"] = zalo_mid
                rc.details = updated_d
            db.add(
                ActivityLog(
                    id=snowflake.generate(),
                    actor_id="vsico_bot",
                    action="DHVT_REVIEW_ALERT",
                    entity_type="review_case",
                    entity_id=str(rc.id),
                    details={
                        "case_type": rc.case_type,
                        "container_no": item.get("container_no"),
                        "dhvt_zalo_msg_id": zalo_mid,
                        "batched_count": len(bucket),
                        "preview": alert_text,
                    },
                )
            )

    @classmethod
    def create_or_merge_review_case(
        cls,
        db: Session,
        message_id: int,
        case_type: str,
        reason: str,
        container_job_id: Optional[int] = None,
        container_no: Optional[str] = None,
        carrier_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        suggestion: Optional[str] = None,
        priority: str = "NORMAL",
        is_test_msg: bool = False,
        notify_zalo: bool = True,
    ) -> tuple[ReviewCase, bool]:
        """Tạo ca duyệt mới hoặc gộp vào ca PENDING đang mở cùng `container` và `case_type`.

        Returns:
            tuple[ReviewCase, bool]: `(review_case, is_newly_created)`.
        """
        existing: Optional[ReviewCase] = None
        if container_job_id:
            existing = db.scalar(
                select(ReviewCase)
                .where(
                    ReviewCase.container_job_id == container_job_id,
                    ReviewCase.case_type == case_type,
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                )
                .order_by(ReviewCase.id.desc())
            )
        if existing is None and container_no:
            open_same_type = list(
                db.scalars(
                    select(ReviewCase)
                    .where(
                        ReviewCase.case_type == case_type,
                        ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                    )
                    .order_by(ReviewCase.id.desc())
                    .limit(20)
                ).all()
            )
            norm_cont = container_no.strip().upper()
            for cand in open_same_type:
                cand_cont = str((cand.details or {}).get("container_no") or "").strip().upper()
                if not cand_cont and cand.container_job_id:
                    cj = db.get(ContainerJob, cand.container_job_id)
                    cand_cont = (cj.container_no or "").strip().upper() if cj else ""
                if cand_cont == norm_cont:
                    existing = cand
                    break

        now = datetime.now(timezone.utc)
        due_at = (now + timedelta(minutes=30 if priority == "HIGH" else 60)).isoformat()

        if existing is not None:
            merged_details = dict(existing.details or {})
            occ = int(merged_details.get("occurrence_count", 1)) + 1
            merged_details.update(details or {})
            merged_details["occurrence_count"] = occ
            merged_details["last_seen_at"] = now.isoformat()
            if container_no:
                merged_details["container_no"] = container_no.strip().upper()
            if suggestion:
                merged_details["suggestion"] = suggestion
            merged_details["priority"] = priority
            existing.details = merged_details
            if reason and reason not in (existing.reason or ""):
                existing.reason = f"{existing.reason} | Lan {occ}: {reason}"
            db.flush()
            return existing, False

        init_details = dict(details or {})
        init_details.setdefault("priority", priority)
        init_details.setdefault("due_at", due_at)
        init_details.setdefault("occurrence_count", 1)
        if container_no:
            init_details.setdefault("container_no", container_no.strip().upper())
        if suggestion:
            init_details.setdefault("suggestion", suggestion)

        rc = ReviewCase(
            id=snowflake.generate(),
            message_id=message_id,
            container_job_id=container_job_id,
            case_type=case_type,
            reason=reason,
            details=init_details,
            status=ReviewStatus.PENDING.value,
        )
        db.add(rc)
        db.flush()

        if notify_zalo:
            active_batch = _ACTIVE_ALERT_BATCH.get()
            if active_batch is not None:
                active_batch.append(
                    {
                        "case_obj": rc,
                        "container_no": container_no,
                        "carrier_name": carrier_name,
                        "suggestion": suggestion,
                        "priority": priority,
                    }
                )
            else:
                alert_text = cls.render_review_case_alert(
                    case_obj=rc,
                    db=db,
                    container_no=container_no,
                    carrier_name=carrier_name,
                    suggestion=suggestion,
                    priority=priority,
                )
                dhvt_group = cls.find_dhvt_group(db)
                zalo_mid: Optional[str] = None
                if cls._is_real_dispatch_enabled(dhvt_group, is_test_msg):
                    ok, z_mid, _ = ZaloDispatcher.send_to_group(
                        group_id=dhvt_group.zalo_group_id,
                        message=alert_text,
                    )
                    if ok and z_mid:
                        zalo_mid = z_mid
                        updated_d = dict(rc.details or {})
                        updated_d["dhvt_zalo_msg_id"] = z_mid
                        rc.details = updated_d

                db.add(
                    ActivityLog(
                        id=snowflake.generate(),
                        actor_id="vsico_bot",
                        action="DHVT_REVIEW_ALERT",
                        entity_type="review_case",
                        entity_id=str(rc.id),
                        details={
                            "case_type": case_type,
                            "container_no": container_no,
                            "dhvt_zalo_msg_id": zalo_mid,
                            "preview": alert_text,
                        },
                    )
                )
        return rc, True

    @classmethod
    def notify_pending_outbound(
        cls,
        db: Session,
        outbound: OutboundMessage,
        target_group_name: str,
        containers: list[str],
        reason: str,
        is_test_msg: bool = False,
        review_case_id: Optional[int] = None,
    ) -> Optional[str]:
        """Gửi Form 2 báo nhóm Zalo ĐHVT khi có tin chờ duyệt, luôn hiển thị rõ Tên nhóm Zalo nguồn."""
        from src.infrastructure.models import OutboundMessageItem

        resolved_rc_id = review_case_id
        if resolved_rc_id is None and outbound.id:
            resolved_rc_id = db.scalar(
                select(ReviewCase.id)
                .join(OutboundMessageItem, OutboundMessageItem.container_job_id == ReviewCase.container_job_id)
                .where(
                    OutboundMessageItem.outbound_message_id == outbound.id,
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                )
                .order_by(ReviewCase.id.desc())
                .limit(1)
            )
        source_group_name: Optional[str] = None
        carrier_name: Optional[str] = None
        sender_name: Optional[str] = None
        if resolved_rc_id:
            rc_obj = db.get(ReviewCase, resolved_rc_id)
            if rc_obj is not None:
                rc_ctx = cls._resolve_review_case_context(db=db, case_obj=rc_obj)
                source_group_name = rc_ctx.get("source_group_name")
                carrier_name = rc_ctx.get("carrier_name")
                sender_name = rc_ctx.get("sender_name")
        if not source_group_name and outbound.id:
            first_job = db.scalar(
                select(ContainerJob)
                .join(OutboundMessageItem, OutboundMessageItem.container_job_id == ContainerJob.id)
                .where(OutboundMessageItem.outbound_message_id == outbound.id)
                .limit(1)
            )
            if first_job and first_job.message_id:
                orig_m = db.get(ZaloMessage, first_job.message_id)
                if orig_m:
                    sender_name = sender_name or orig_m.sender_name
                    if orig_m.group_id:
                        sg = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == orig_m.group_id))
                        source_group_name = (sg.name if sg and sg.name else orig_m.group_id)
                        carrier_name = carrier_name or (sg.carrier_name if sg else None)

        alert_text = cls.render_pending_outbound_alert(
            outbound=outbound,
            target_group_name=target_group_name,
            containers=containers,
            reason=reason,
            review_case_id=resolved_rc_id,
            source_group_name=source_group_name,
            carrier_name=carrier_name,
            sender_name=sender_name,
        )
        dhvt_group = cls.find_dhvt_group(db)
        zalo_mid: Optional[str] = None
        if cls._is_real_dispatch_enabled(dhvt_group, is_test_msg):
            ok, z_mid, _ = ZaloDispatcher.send_to_group(
                group_id=dhvt_group.zalo_group_id,
                message=alert_text,
            )
            if ok and z_mid:
                zalo_mid = z_mid
                outbound.review_zalo_msg_id = z_mid
                if resolved_rc_id:
                    rc_obj = db.get(ReviewCase, resolved_rc_id)
                    if rc_obj is not None:
                        updated_d = dict(rc_obj.details or {})
                        updated_d["dhvt_zalo_msg_id"] = z_mid
                        rc_obj.details = updated_d

        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id="vsico_bot",
                action="DHVT_PENDING_OUTBOUND_ALERT",
                entity_type="outbound_message",
                entity_id=str(outbound.id),
                details={
                    "target_group_name": target_group_name,
                    "source_group_name": source_group_name,
                    "carrier_name": carrier_name,
                    "containers": containers,
                    "reason": reason,
                    "dhvt_zalo_msg_id": zalo_mid,
                },
            )
        )
        return zalo_mid

    @classmethod
    def render_dhvt_review_decision(
        cls,
        db: Session,
        *,
        case_obj: ReviewCase,
        action_verb: str,
        actor_display: str,
        reason: Optional[str] = None,
    ) -> str:
        """Render thống nhất 1 tin nhắn duy nhất xác nhận quyết định duyệt/sửa/từ chối/hủy của ĐHVT."""
        ctx = cls._resolve_review_case_context(db=db, case_obj=case_obj)
        reviewer = _resolve_reviewer_display_name(actor_display)
        verb_lower = (action_verb or "").strip().lower()
        if "từ chối" in verb_lower or "hủy" in verb_lower:
            title = "[VSICO] - ✅ Đã từ chối / hủy yêu cầu"
            footer = "Hệ thống đã ghi nhận và phản hồi tới nhà xe."
        else:
            title = f"[VSICO] - ✅ Đã {action_verb} cập nhật kế hoạch"
            footer = "Hệ thống đã đồng bộ thông tin lên TMS và phản hồi tới nhà xe."

        info_lines: list[str] = []
        if ctx.get("container_no"):
            info_lines.append(f"📦 Container: {ctx['container_no']}")
        if ctx.get("order_label"):
            info_lines.append(f"• Lệnh: {ctx['order_label']}")
        src_parts = [
            f"Nhóm {ctx['source_group_name']}" if ctx.get("source_group_name") else "",
            f"Nhà xe: {ctx['carrier_name']}" if ctx.get("carrier_name") else "",
        ]
        src_line = " · ".join(p for p in src_parts if p)
        if src_line:
            info_lines.append(f"• Từ: {src_line}")
        if ctx.get("vehicle_driver"):
            info_lines.append(f"• Xe & Tài xế: {ctx['vehicle_driver'].replace(' | ', ' · ')}")
        info_lines.append(f"• Người duyệt: {reviewer}")
        if reason:
            info_lines.append(f"• Lý do: {humanize_reason_text(reason)}")

        return f"{title}\n\n" + "\n".join(info_lines) + f"\n\n{footer}"

    @classmethod
    def broadcast_dhvt_review_decision(
        cls,
        db: Session,
        *,
        case_obj: ReviewCase,
        action_verb: str,
        actor_display: str,
        reason: Optional[str] = None,
        is_test_msg: bool = False,
        send_zalo: bool = True,
    ) -> Optional[str]:
        """Phát thông báo công khai vào nhóm Zalo ĐHVT theo chuẩn `[VSICO] - ✅ ...`, ghi rõ tên người duyệt."""
        reviewer = _resolve_reviewer_display_name(actor_display)
        msg_text = cls.render_dhvt_review_decision(
            db=db,
            case_obj=case_obj,
            action_verb=action_verb,
            actor_display=reviewer,
            reason=reason,
        )
        dhvt_group = cls.find_dhvt_group(db)
        zalo_mid: Optional[str] = None
        if send_zalo and cls._is_real_dispatch_enabled(dhvt_group, is_test_msg):
            quote_id = (case_obj.details or {}).get("dhvt_zalo_msg_id") if isinstance(case_obj.details, dict) else None
            ok, z_mid, _ = ZaloDispatcher.send_to_group(
                group_id=dhvt_group.zalo_group_id,
                message=msg_text,
                quote_msg_id=str(quote_id) if quote_id else None,
            )
            if not ok and quote_id:
                ok, z_mid, _ = ZaloDispatcher.send_to_group(
                    group_id=dhvt_group.zalo_group_id,
                    message=msg_text,
                )
            if ok:
                zalo_mid = z_mid
        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id=reviewer,
                action="DHVT_DECISION_BROADCAST",
                entity_type="review_case",
                entity_id=str(case_obj.id),
                details={
                    "action_verb": action_verb,
                    "actor_display": reviewer,
                    "message": msg_text,
                    "dhvt_zalo_msg_id": zalo_mid,
                },
            )
        )
        return zalo_mid

    @classmethod
    def notify_system_alert(
        cls,
        db: Session,
        title: str,
        body: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        web_path: str = "/reviews",
        dedup_minutes: int = 30,
        is_test_msg: bool = False,
        details: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Gửi Form 3 cảnh báo hệ thống vào nhóm ĐHVT có chống spam trùng trong cửa sổ thời gian."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=dedup_minutes)
        recent_same = db.scalar(
            select(ActivityLog.id).where(
                ActivityLog.action == title,
                ActivityLog.entity_type == entity_type,
                ActivityLog.entity_id == (entity_id or ""),
                ActivityLog.created_at >= cutoff,
            )
        )
        effective_path = web_path
        if web_path == "/reviews" and entity_id:
            if entity_type == "review_case":
                eid = _to_int_id(entity_id)
                if eid:
                    effective_path = cls._short_entity_path("r", eid)
            elif entity_type == "outbound_message":
                eid = _to_int_id(entity_id)
                if eid:
                    effective_path = cls._short_entity_path("o", eid)
            elif entity_type == "container_job":
                job_id_int = _to_int_id(entity_id)
                if job_id_int:
                    linked_rc_id = db.scalar(
                        select(ReviewCase.id)
                        .where(ReviewCase.container_job_id == job_id_int)
                        .order_by(ReviewCase.id.desc())
                        .limit(1)
                    )
                    if linked_rc_id:
                        effective_path = cls._short_entity_path("r", linked_rc_id)
        alert_text = cls.render_system_alert(title=title, body=body, web_path=effective_path)
        dhvt_group = cls.find_dhvt_group(db)
        dispatched = False
        zalo_mid: Optional[str] = None
        if recent_same is None and cls._is_real_dispatch_enabled(dhvt_group, is_test_msg):
            ok, z_mid, _ = ZaloDispatcher.send_to_group(
                group_id=dhvt_group.zalo_group_id,
                message=alert_text,
            )
            dispatched = ok
            zalo_mid = z_mid

        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id="vsico_bot",
                action=title,
                entity_type=entity_type,
                entity_id=entity_id or "",
                details={
                    "message": body,
                    "dedup_suppressed": recent_same is not None,
                    "dhvt_zalo_msg_id": zalo_mid,
                    **(details or {}),
                },
            )
        )
        return dispatched

    @classmethod
    def record_warehouse_habit(
        cls,
        db: Session,
        warehouse_hint: Optional[str],
        warehouse_id: Optional[int],
    ) -> Optional[WarehouseAlias]:
        """Lưu thói quen ánh xạ địa chỉ nhà xe -> kho vào `warehouse_aliases` khi ĐHVT duyệt."""
        if not warehouse_hint or not warehouse_id:
            return None
        clean_hint = warehouse_hint.strip()
        norm_hint = _normalize_alias_key(clean_hint)
        if len(norm_hint) < 2:
            return None
        existing = db.scalar(
            select(WarehouseAlias).where(WarehouseAlias.normalized_alias == norm_hint)
        )
        if existing:
            if existing.warehouse_id != warehouse_id:
                existing.warehouse_id = warehouse_id
                existing.source = "human_review"
            return existing

        alias = WarehouseAlias(
            id=snowflake.generate(),
            warehouse_id=warehouse_id,
            alias=clean_hint[:255],
            normalized_alias=norm_hint[:255],
            source="human_review",
        )
        db.add(alias)
        return alias

    @classmethod
    def _is_test_record(cls, db: Session, message_id: Optional[int]) -> bool:
        """Kiểm tra bản ghi có xuất phát từ tin nhắn test hoặc nhóm kiểm thử hay không."""
        if not message_id:
            return False
        msg = db.get(ZaloMessage, message_id)
        if not msg:
            return False
        if isinstance(msg.raw_payload, dict) and msg.raw_payload.get("is_test"):
            return True
        gid = str(msg.group_id or "").lower()
        if gid.startswith(("pytest_", "test_", "grp_test_", "dummy_", "proxy_")):
            return True
        grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == msg.group_id))
        if grp and grp.is_test:
            return True
        return False

    @classmethod
    def check_overdue_escalations(cls, db: Session, is_test_msg: bool = False) -> dict[str, int]:
        """Quét các phản hồi nhà xe, ca duyệt và tin chờ duyệt quá hạn, gom nhiều mục thành 1 thông báo duy nhất."""
        now = datetime.now(timezone.utc)
        fresh_window = now - timedelta(hours=24)
        overdue_replies = 0
        reminded_reviews = 0
        reminded_outbounds = 0
        admin_escalations = 0
        overdue_batch: list[dict[str, Any]] = []

        # 1. Nhà xe quá hạn 30 phút sửa tin nhắn (`bot_replies`) -> tạo ReviewCase (không nhân đôi nếu đã có ca mở)
        expired_replies = list(
            db.scalars(
                select(BotReply).where(
                    BotReply.status.in_([CorrectionStatus.PENDING.value, "PENDING"]),
                    BotReply.fix_deadline < now,
                    BotReply.fix_deadline >= fresh_window,
                ).limit(50)
            ).all()
        )
        new_overdue_cases: list[dict[str, Any]] = []
        for br in expired_replies:
            if not is_test_msg and cls._is_test_record(db, br.message_id):
                continue
            br.status = CorrectionStatus.CANCELLED.value
            overdue_replies += 1
            existing_open_rc = db.scalar(
                select(ReviewCase.id).where(
                    ReviewCase.message_id == br.message_id,
                    ReviewCase.case_type == "CARRIER_CORRECTION_OVERDUE",
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                ).limit(1)
            )
            if existing_open_rc is not None:
                continue
            rc_created, is_new = cls.create_or_merge_review_case(
                db=db,
                message_id=br.message_id,
                case_type="CARRIER_CORRECTION_OVERDUE",
                reason="Nhà xe quá hạn 30 phút chưa bổ sung thông tin theo nhắc nhở của Bot.",
                details={"bot_reply_id": br.id, "sender_id": br.sender_id},
                suggestion="Liên hệ trực tiếp nhà xe hoặc kiểm tra lại tin gốc trên Web.",
                priority="HIGH",
                is_test_msg=is_test_msg,
                notify_zalo=False,
            )
            if is_new:
                new_overdue_cases.append(
                    {
                        "case_obj": rc_created,
                        "container_no": None,
                        "carrier_name": None,
                        "suggestion": "Liên hệ trực tiếp nhà xe hoặc kiểm tra lại tin gốc trên Web.",
                        "priority": "HIGH",
                    }
                )
        if new_overdue_cases:
            cls._flush_alert_batch(db, new_overdue_cases, is_test_msg=is_test_msg)

        # 2. Ca ReviewCase chờ xử lý quá hạn (> 30 phút, trong cửa sổ 24h gần nhất) -> gom 1 thông báo
        review_cutoff = now - timedelta(minutes=30)
        stale_reviews = list(
            db.scalars(
                select(ReviewCase).where(
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                    ReviewCase.created_at < review_cutoff,
                    ReviewCase.created_at >= fresh_window,
                ).limit(50)
            ).all()
        )
        for rc in stale_reviews:
            if not is_test_msg and cls._is_test_record(db, rc.message_id):
                continue
            details = dict(rc.details or {})
            remind_count = int(details.get("reminder_count", 0))
            if remind_count >= 2:
                # Đã leo thang Admin lần 2 -> không lặp lại liên tục gây spam nhóm
                continue
            last_reminded = details.get("last_reminded_at")
            if last_reminded:
                try:
                    last_dt = datetime.fromisoformat(str(last_reminded))
                    if (now - last_dt) < timedelta(minutes=30):
                        continue
                except ValueError:
                    pass
            remind_count += 1
            details["reminder_count"] = remind_count
            details["last_reminded_at"] = now.isoformat()
            rc.details = details
            reminded_reviews += 1
            if remind_count >= 2:
                admin_escalations += 1
            overdue_batch.append(
                {
                    "kind": "review_case",
                    "case_obj": rc,
                    "remind_count": remind_count,
                    "entity_type": "review_case",
                    "entity_id": str(rc.id),
                }
            )

        # 3. Tin gửi khách chờ duyệt quá hạn (> 30 phút, trong cửa sổ 24h gần nhất) -> gom chung vào lô
        stale_outbounds = list(
            db.scalars(
                select(OutboundMessage).where(
                    OutboundMessage.status.in_([OutboundStatus.PENDING_APPROVAL.value, "cho_duyet"]),
                    OutboundMessage.created_at < review_cutoff,
                    OutboundMessage.created_at >= fresh_window,
                ).limit(50)
            ).all()
        )
        for ob in stale_outbounds:
            if not is_test_msg and ob.target_group and ob.target_group.is_test:
                continue
            existing_rem = db.scalar(
                select(func.count(ActivityLog.id)).where(
                    ActivityLog.entity_type == "outbound_message",
                    ActivityLog.entity_id == str(ob.id),
                    ActivityLog.action.in_(["NHAC TIN CHO DUYET QUA HAN", "LEO THANG ADMIN - TIN CHO DUYET QUA HAN"]),
                )
            ) or 0
            if existing_rem >= 2:
                continue
            recent_rem = db.scalar(
                select(ActivityLog.id).where(
                    ActivityLog.entity_type == "outbound_message",
                    ActivityLog.entity_id == str(ob.id),
                    ActivityLog.action.in_(["NHAC TIN CHO DUYET QUA HAN", "LEO THANG ADMIN - TIN CHO DUYET QUA HAN"]),
                    ActivityLog.created_at >= review_cutoff,
                )
            )
            if recent_rem:
                continue
            reminded_outbounds += 1
            rem_level = existing_rem + 1
            if rem_level >= 2:
                admin_escalations += 1
            group_label = ob.target_group.name if ob.target_group and ob.target_group.name else "Khách hàng"
            overdue_batch.append(
                {
                    "kind": "outbound",
                    "outbound": ob,
                    "group_label": group_label,
                    "remind_count": rem_level,
                    "label": "2 lượt nhắc" if rem_level >= 2 else "30 phút",
                    "link": cls._short_entity_url("o", ob.id),
                    "entity_type": "outbound_message",
                    "entity_id": str(ob.id),
                }
            )

        # Phát duy nhất 1 thông báo tổng hợp cho toàn bộ các mục quá hạn trong chu kỳ này
        if overdue_batch:
            batched_text = cls.render_batched_overdue_alert(overdue_batch, db=db)
            dhvt_group = cls.find_dhvt_group(db)
            zalo_mid: Optional[str] = None
            if cls._is_real_dispatch_enabled(dhvt_group, is_test_msg):
                ok, z_mid, _ = ZaloDispatcher.send_to_group(
                    group_id=dhvt_group.zalo_group_id,
                    message=batched_text,
                )
                if ok:
                    zalo_mid = z_mid
            for item in overdue_batch:
                if item["kind"] == "review_case":
                    act_name = (
                        "LEO THANG ADMIN - CA DUYET QUA HAN"
                        if item["remind_count"] >= 2
                        else "NHAC CA CHO DUYET QUA HAN"
                    )
                else:
                    act_name = (
                        "LEO THANG ADMIN - TIN CHO DUYET QUA HAN"
                        if item["remind_count"] >= 2
                        else "NHAC TIN CHO DUYET QUA HAN"
                    )
                db.add(
                    ActivityLog(
                        id=snowflake.generate(),
                        actor_id="vsico_bot",
                        action=act_name,
                        entity_type=item["entity_type"],
                        entity_id=item["entity_id"],
                        details={
                            "batched_count": len(overdue_batch),
                            "dhvt_zalo_msg_id": zalo_mid,
                            "preview": batched_text,
                        },
                    )
                )

        db.commit()
        return {
            "overdue_carrier_replies": overdue_replies,
            "reminded_review_cases": reminded_reviews,
            "reminded_pending_outbounds": reminded_outbounds,
            "admin_escalations": admin_escalations,
        }
