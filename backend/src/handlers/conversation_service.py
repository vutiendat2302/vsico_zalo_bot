"""Xử lý hội thoại cho nhóm Khách hàng (hỏi đáp theo RouteMap, đề xuất đổi/hủy) và nhóm ĐHVT nội bộ (tra cứu chỉ đọc, từ chối lệnh duyệt qua Zalo)."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.enums import (
    MessageStatus,
    OutboundStatus,
    ReviewStatus,
)
from src.domain.rules import compact_plate
from src.handlers.dhvt_service import DhvtNotificationService
from src.infrastructure.models import (
    ActivityLog,
    Carrier,
    ContainerJob,
    Customer,
    OutboundMessage,
    ReviewCase,
    RouteMap,
    TransportPlan,
    TruckRecord,
    User,
    Warehouse,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher

logger = logging.getLogger(__name__)

_CONTAINER_RE = re.compile(r"\b([A-Za-z]{4})[\s\-]?(\d{7})\b")
_SHORT_CONTAINER_RE = re.compile(r"\b([A-Za-z]{4})[\s\-]?(\d{5,6})\b(?!\d)")
_PLATE_RE = re.compile(r"\b(\d{2}[A-Za-z]{1,2}[\-\.\s]?\d{3,5}(?:[\-\.\s]?\d{1,2})?)\b")
_CASE_ID_RE = re.compile(r"(?:ca|review|case|id)\s*#?\s*(\d{5,})", re.IGNORECASE)

# Chuẩn câu trả lời giống hệt nhau giữa "không tồn tại" và "nằm ngoài phạm vi RouteMap" để chống dò chéo khách hàng.
_CUSTOMER_LOOKUP_NOT_FOUND_TEXT = (
    "Hiện tại VSICO chưa ghi nhận thông tin điều xe cho mã tra cứu Quý khách cung cấp "
    "trong phạm vi tuyến phụ trách của nhóm. Quý khách vui lòng kiểm tra lại mã container/biển số "
    "hoặc liên hệ bộ phận Điều hành vận tải để được hỗ trợ."
)

_CUSTOMER_ACK_WORDS = frozenset(
    {
        "ok",
        "oki",
        "okie",
        "oke",
        "cam on",
        "cảm ơn",
        "thanks",
        "thank",
        "tks",
        "vang",
        "vâng",
        "da",
        "dạ",
        "da nhan",
        "đã nhận",
        "ok em",
        "ok ban",
        "ok bạn",
        "ok anh",
        "ok chi",
        "ok chị",
    }
)

_CUSTOMER_CHANGE_KEYWORDS = (
    "doi gio",
    "đổi giờ",
    "doi kho",
    "đổi kho",
    "doi cont",
    "đổi cont",
    "doi xe",
    "đổi xe",
    "doi chuyen",
    "đổi chuyến",
    "huy chuyen",
    "hủy chuyến",
    "huy don",
    "hủy đơn",
    "bo chuyen",
    "bỏ chuyến",
    "thay doi",
    "thay đổi",
    "chuyen gio",
    "chuyển giờ",
    "lui gio",
    "lùi giờ",
    "doi ngay",
    "dời ngày",
    "hoan",
    "hoãn",
    "sua thong tin",
    "sửa thông tin",
    "xin doi",
    "xin đổi",
    "xin huy",
    "xin hủy",
)

_CUSTOMER_CHANGE_REGEX = re.compile(
    r"\b(?:đổi|doi|hủy|huy|hoãn|hoan|lùi|lui|dời|doi|sửa|sua|thay)\b",
    re.IGNORECASE,
)

_CUSTOMER_QUESTION_KEYWORDS = (
    "?",
    "xe nao",
    "xe nào",
    "toi chua",
    "tới chưa",
    "den chua",
    "đến chưa",
    "may gio",
    "mấy giờ",
    "khi nao",
    "khi nào",
    "bao gio",
    "bao giờ",
    "o dau",
    "ở đâu",
    "bien so",
    "biển số",
    "tai xe",
    "tài xế",
    "lai xe",
    "lái xe",
    "sdt",
    "sđt",
    "so dien thoai",
    "số điện thoại",
    "so seal",
    "số seal",
    "so chi",
    "số chì",
    "trang thai",
    "trạng thái",
    "tinh hinh",
    "tình hình",
    "tra cuu",
    "tra cứu",
    "kiem tra",
    "kiểm tra",
    "cho hoi",
    "cho hỏi",
    "co xe",
    "có xe",
    "xin thong tin",
    "xin thông tin",
    "thong tin",
    "thông tin",
    "hom nay",
    "hôm nay",
    "ngay mai",
    "ngày mai",
    "nhung cont",
    "những cont",
    "cac cont",
    "các cont",
    "cont nao",
    "cont nào",
    "so cont",
    "số cont",
    "container",
    "ke hoach",
    "kế hoạch",
    "lich trinh",
    "lịch trình",
    "xem giup",
    "xem giúp",
    "cho xem",
    "gui giup",
    "gửi giúp",
    "bao nhieu",
    "bao nhiêu",
    "da co",
    "đã có",
    "co chua",
    "có chưa",
    "chua thay",
    "chưa thấy",
    "cap nhat",
    "cập nhật",
    "check",
)

_CARRIER_DISPATCH_SIGNAL_RE = re.compile(
    r"(?:\b0\d{9}\b|\b(?:seal|số chì|so chi|đổi xe|doi xe|bổ sung|bo sung|hủy chuyến|huy chuyen|"
    r"báo xe|bao xe|nhận lệnh|nhan lenh|đóng hàng|dong hang|trả hàng|tra hang)\b)",
    re.IGNORECASE,
)

_CARRIER_QA_KEYWORDS = (
    "?",
    "xin thong tin",
    "xin thông tin",
    "thong tin",
    "thông tin",
    "hom nay",
    "hôm nay",
    "nhung cont",
    "những cont",
    "cac cont",
    "các cont",
    "cont nao",
    "cont nào",
    "ke hoach",
    "kế hoạch",
    "lich trinh",
    "lịch trình",
    "tra cuu",
    "tra cứu",
    "kiem tra",
    "kiểm tra",
    "cho hoi",
    "cho hỏi",
    "trang thai",
    "trạng thái",
    "o dau",
    "ở đâu",
    "may gio",
    "mấy giờ",
    "bao gio",
    "bao giờ",
    "bao nhieu",
    "bao nhiêu",
    "xe nao",
    "xe nào",
    "kho nao",
    "kho nào",
    "tuyen nao",
    "tuyến nào",
    "check",
)

_DHVT_APPROVAL_EXACT_TOKENS = frozenset(
    {
        "ok",
        "oki",
        "okie",
        "oke",
        "ok em",
        "ok nhe",
        "ok nhé",
        "duyet",
        "duyệt",
        "chot",
        "chốt",
        "dong y",
        "đồng ý",
        "xac nhan",
        "xác nhận",
        "cho gui",
        "cho gửi",
        "gui di",
        "gửi đi",
        "tu choi",
        "từ chối",
        "approve",
        "reject",
        "confirm",
    }
)

_DHVT_COMMAND_PREFIX_RE = re.compile(
    r"^\s*(?:duyệt|duyet|từ chối|tu choi|hủy|huy|sửa|sua|đổi|doi|"
    r"xác nhận|xac nhan|chốt|chot|cho gửi|cho gui|approve|reject)\b",
    re.IGNORECASE,
)

_DHVT_LOOKUP_QUESTION_RE = re.compile(
    r"(?:\?|bao nhiêu|bao nhieu|danh sách|danh sach|xem|tra cứu|tra cuu|liệt kê|liet ke|thống kê|thong ke)",
    re.IGNORECASE,
)


def _normalize_text(text: Optional[str]) -> str:
    """Chuẩn hóa khoảng trắng và chữ thường để đối chiếu từ khóa ổn định."""
    return " ".join((text or "").lower().strip().split())


def _extract_containers(text: Optional[str]) -> list[str]:
    """Trích xuất danh sách mã container dạng 4 chữ + 7 số từ văn bản."""
    if not text:
        return []
    seen: list[str] = []
    for prefix, digits in _CONTAINER_RE.findall(text):
        cont = f"{prefix.upper()}{digits}"
        if cont not in seen:
            seen.append(cont)
    return seen


def _extract_invalid_length_containers(text: Optional[str]) -> list[str]:
    """Trích xuất các mã có dạng 4 chữ + 5-6 số (thiếu chữ số chuẩn ISO 6346) để phản hồi nhắc lại."""
    if not text:
        return []
    valid = set(_extract_containers(text))
    seen: list[str] = []
    for prefix, digits in _SHORT_CONTAINER_RE.findall(text):
        code = f"{prefix.upper()}{digits}"
        if code not in valid and code not in seen:
            seen.append(code)
    return seen


def _extract_plates(text: Optional[str]) -> list[str]:
    """Trích xuất danh sách biển số xe dạng chuẩn hóa không dấu gạch/chấm."""
    if not text:
        return []
    seen: list[str] = []
    for raw in _PLATE_RE.findall(text):
        comp = compact_plate(raw)
        if not comp:
            continue
        digit_count = sum(1 for ch in comp if ch.isdigit())
        if digit_count < 6:
            continue
        if comp not in seen:
            seen.append(comp)
    return seen


def _mask_phone_for_customer(phone: Optional[str]) -> str:
    """Hiển thị đầy đủ SĐT tài xế khi trả lời nhóm khách hàng (không che/mã hóa)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits:
        return digits
    cleaned = (phone or "").strip()
    return cleaned if cleaned else "Chưa cập nhật"


def _record_activity(
    db: Session,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Ghi nhật ký kiểm toán vào bảng activity_logs."""
    db.add(
        ActivityLog(
            id=snowflake.generate(),
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


def _send_or_queue_group_reply(
    db: Session,
    group: ZaloGroup,
    source_message: ZaloMessage,
    reply_text: str,
    order_type: str = "ANSWER",
) -> OutboundMessage:
    """Lưu phản hồi vào outbound_messages và phát trực tiếp qua ZaloDispatcher nếu là nhóm thật."""
    outbound = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=group.id,
        order_type=order_type,
        message_kind="answer",
        content=reply_text,
        idempotency_key=f"answer_{source_message.id}_{snowflake.generate()}",
        status=OutboundStatus.PENDING_SEND.value,
    )
    db.add(outbound)
    db.flush()

    if not group.is_test and settings.AUTO_DISPATCH_OUTBOUND:
        ok, zalo_msg_id, error = ZaloDispatcher.send_to_group(
            group_id=group.zalo_group_id,
            message=reply_text,
            quote_msg_id=source_message.zalo_message_id,
        )
        outbound.attempt_count += 1
        if ok:
            outbound.status = OutboundStatus.SENT.value
            outbound.zalo_message_id = zalo_msg_id
            outbound.sent_at = datetime.now(UTC)
            outbound.last_error = None
        else:
            outbound.status = OutboundStatus.FAILED.value
            outbound.last_error = error or "Gửi phản hồi Zalo thất bại."
            DhvtNotificationService.notify_system_alert(
                db=db,
                title="LOI GUI PHAN HOI HOI DAP ZALO",
                body=(
                    f"Nhóm: {group.name} ({group.zalo_group_id})\n"
                    f"Outbound ID: {outbound.id}\n"
                    f"Lỗi: {outbound.last_error}"
                ),
                entity_type="outbound_message",
                entity_id=str(outbound.id),
                web_path="/results",
                is_test_msg=bool(group.is_test),
                details={"outbound_message_id": outbound.id, "group_id": group.zalo_group_id},
            )
    return outbound


def _build_routemap_scope_filter(entity_cls: Any, routes: list[RouteMap]):
    """Tạo điều kiện lọc SQLAlchemy bảo đảm dữ liệu nằm gọn trong RouteMap active của nhóm."""
    if not routes:
        return None
    clauses = []
    for r in routes:
        parts = [entity_cls.customer_id == r.customer_id]
        if r.warehouse_id is not None:
            parts.append(entity_cls.warehouse_id == r.warehouse_id)
        if r.order_type:
            parts.append(entity_cls.order_type == r.order_type)
        clauses.append(and_(*parts))
    return or_(*clauses)


def _format_customer_job_summary(db: Session, job: ContainerJob) -> str:
    """Định dạng thông tin điều xe trả lời khách hàng (luôn che 6 số cuối SĐT)."""
    truck = job.truck_record
    wh = db.get(Warehouse, job.warehouse_id) if job.warehouse_id else None
    raw = job.raw_fields if isinstance(job.raw_fields, dict) else {}
    eta = raw.get("eta") or raw.get("eta_time") or "Đang cập nhật"
    plate = truck.truck_plate if truck and truck.truck_plate else "Chưa điều xe"
    trailer = truck.trailer_plate if truck and truck.trailer_plate else None
    driver = truck.driver_name if truck and truck.driver_name else "Chưa cập nhật"
    masked_phone = _mask_phone_for_customer(truck.driver_phone if truck else None)
    seal = job.seal_no or "Chưa cập nhật"
    size = job.container_size or "N/A"
    wh_label = wh.name if wh else (job.warehouse_hint or "Theo kế hoạch")
    vehicle_line = f"Biển số xe: {plate}" + (f" / Mooc: {trailer}" if trailer else "")
    return (
        f"- Container: {job.container_no or 'Chưa cấp số'} ({size})\n"
        f"  {vehicle_line}\n"
        f"  Tài xế: {driver} - SĐT: {masked_phone}\n"
        f"  Số chì: {seal} | Kho: {wh_label} | Dự kiến: {eta}"
    )


def _format_customer_plan_summary(db: Session, plan: TransportPlan) -> str:
    """Định dạng thông tin từ kế hoạch vận chuyển khi chưa có bản ghi điều xe hoàn chỉnh."""
    wh = db.get(Warehouse, plan.warehouse_id) if plan.warehouse_id else None
    plate = plan.planned_truck_plate or "Chưa điều xe"
    driver = plan.driver_name or "Chưa cập nhật"
    masked_phone = _mask_phone_for_customer(plan.driver_phone)
    seal = plan.seal_no or "Chưa cập nhật"
    size = plan.container_size or "N/A"
    eta = plan.eta or plan.estimated_drop_time or "Đang cập nhật"
    wh_label = wh.name if wh else (plan.delivery_address or plan.address or "Theo kế hoạch")
    return (
        f"- Container: {plan.container_no or 'Chưa cấp số'} ({size})\n"
        f"  Biển số xe: {plate}\n"
        f"  Tài xế: {driver} - SĐT: {masked_phone}\n"
        f"  Số chì: {seal} | Kho: {wh_label} | Dự kiến: {eta}"
    )


def _find_scoped_customer_records(
    db: Session,
    routes: list[RouteMap],
    containers: list[str],
    plates: list[str],
    limit: int = 5,
    group_zalo_id: Optional[str] = None,
) -> tuple[list[ContainerJob], list[TransportPlan]]:
    """Truy vấn ContainerJob và TransportPlan nằm đúng phạm vi RouteMap hoặc gán trực tiếp cho nhóm khách hàng."""
    job_scope = _build_routemap_scope_filter(ContainerJob, routes) if routes else None
    plan_scope = _build_routemap_scope_filter(TransportPlan, routes) if routes else None
    if group_zalo_id:
        direct_plan_clause = TransportPlan.group_id == group_zalo_id
        plan_scope = or_(plan_scope, direct_plan_clause) if plan_scope is not None else direct_plan_clause

    if job_scope is None and plan_scope is None:
        return [], []

    superseded_subq = select(ContainerJob.parent_job_id).where(ContainerJob.parent_job_id.is_not(None))
    job_stmt = (
        select(ContainerJob)
        .where(job_scope, ~ContainerJob.id.in_(superseded_subq))
        .order_by(ContainerJob.id.desc())
    ) if job_scope is not None else None
    plan_stmt = (
        select(TransportPlan).where(plan_scope).order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc())
        if plan_scope is not None
        else None
    )

    if containers:
        if job_stmt is not None:
            job_stmt = job_stmt.where(ContainerJob.container_no.in_(containers))
        if plan_stmt is not None:
            plan_stmt = plan_stmt.where(TransportPlan.container_no.in_(containers))
    elif plates:
        if job_stmt is not None:
            truck_match_ids = [
                tr.id
                for tr in db.scalars(select(TruckRecord).order_by(TruckRecord.id.desc()).limit(300)).all()
                if compact_plate(tr.truck_plate) in plates
            ]
            if truck_match_ids:
                job_stmt = job_stmt.where(ContainerJob.truck_record_id.in_(truck_match_ids))
            else:
                job_stmt = job_stmt.where(ContainerJob.id == -1)

        matched_plans: list[TransportPlan] = []
        if plan_stmt is not None:
            all_scoped_plans = list(db.scalars(plan_stmt.limit(100)).all())
            matched_plans = [p for p in all_scoped_plans if compact_plate(p.planned_truck_plate) in plates]
        matched_jobs = list(db.scalars(job_stmt.limit(limit)).all()) if job_stmt is not None else []
        return matched_jobs, matched_plans[:limit]

    matched_jobs = list(db.scalars(job_stmt.limit(limit)).all()) if job_stmt is not None else []
    matched_plans = list(db.scalars(plan_stmt.limit(limit)).all()) if plan_stmt is not None else []
    return matched_jobs, matched_plans


def _check_unscoped_existence(
    db: Session,
    containers: list[str],
    plates: list[str],
) -> bool:
    """Kiểm tra nội bộ xem mã tra cứu có thuộc khách hàng khác hay không tồn tại (chỉ để ghi Audit)."""
    if containers:
        if db.scalar(select(ContainerJob.id).where(ContainerJob.container_no.in_(containers)).limit(1)):
            return True
        if db.scalar(select(TransportPlan.id).where(TransportPlan.container_no.in_(containers)).limit(1)):
            return True
    if plates:
        for tr in db.scalars(select(TruckRecord).order_by(TruckRecord.id.desc()).limit(300)).all():
            if compact_plate(tr.truck_plate) in plates:
                return True
        for pl in db.scalars(select(TransportPlan).order_by(TransportPlan.id.desc()).limit(300)).all():
            if compact_plate(pl.planned_truck_plate) in plates:
                return True
    return False


def _handle_customer_group_message(
    db: Session,
    message: ZaloMessage,
    group: ZaloGroup,
) -> bool:
    """Điều phối tin nhắn đến từ nhóm Khách hàng (1.2b & 2.2c)."""
    raw_text = (message.message_text or "").strip()
    norm_text = _normalize_text(raw_text)

    if not raw_text or message.sender_id in ("bot", "vsico_bot"):
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    # 1. Tin nhắn xác nhận/cảm ơn lịch sự -> không tạo ca và không trả lời thừa
    if norm_text in _CUSTOMER_ACK_WORDS:
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CUSTOMER_ACK",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id, "text": raw_text},
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    routes = list(
        db.scalars(
            select(RouteMap).where(
                RouteMap.zalo_group_id == group.id,
                RouteMap.is_active.is_(True),
            )
        ).all()
    )
    containers = _extract_containers(raw_text)
    short_conts = _extract_invalid_length_containers(raw_text)
    plates = _extract_plates(raw_text)

    # 2. Đề xuất thay đổi / hủy từ khách hàng -> KHÔNG tự ý sửa dữ liệu, chuyển ĐHVT qua ReviewCase
    is_change_req = any(kw in norm_text for kw in _CUSTOMER_CHANGE_KEYWORDS) or bool(
        _CUSTOMER_CHANGE_REGEX.search(norm_text)
    )
    if is_change_req and not ("?" in raw_text and "có " in norm_text and "không" in norm_text):
        jobs, plans = _find_scoped_customer_records(
            db, routes, containers, plates, limit=1, group_zalo_id=group.zalo_group_id
        )
        primary_job = jobs[0] if jobs else None
        primary_plan = plans[0] if plans else None

        carrier_name = None
        if primary_plan and primary_plan.carrier_id:
            car = db.get(Carrier, primary_plan.carrier_id)
            carrier_name = car.name if car else None

        is_urgent_cancel = "hủy" in norm_text or "huy" in norm_text or "bỏ" in norm_text
        case_obj, _created = DhvtNotificationService.create_or_merge_review_case(
            db=db,
            message_id=message.id,
            case_type="CUSTOMER_CHANGE_REQUEST",
            reason=f"Khách hàng nhóm {group.name} yêu cầu thay đổi/hủy: {raw_text[:280]}",
            container_job_id=primary_job.id if primary_job else None,
            container_no=containers[0] if containers else (primary_job.container_no if primary_job else None),
            carrier_name=carrier_name,
            details={
                "group_id": group.zalo_group_id,
                "group_name": group.name,
                "sender_id": message.sender_id,
                "sender_name": message.sender_name,
                "containers": containers,
                "plates": plates,
                "transport_plan_id": primary_plan.id if primary_plan else None,
                "raw_text": raw_text,
            },
            suggestion="ĐHVT kiểm tra kế hoạch, xác nhận với nhà xe và xử lý trên Web.",
            priority="HIGH" if is_urgent_cancel else "NORMAL",
            is_test_msg=bool(group.is_test),
            notify_zalo=True,
        )
        ack_reply = (
            f"VSICO đã ghi nhận đề xuất từ Quý khách (Ca #{case_obj.id}) và chuyển bộ phận "
            "Điều hành vận tải kiểm tra, phản hồi lại trong thời gian sớm nhất."
        )
        _send_or_queue_group_reply(db, group, message, ack_reply, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CUSTOMER_CHANGE_REQUEST_LOGGED",
            entity_type="review_case",
            entity_id=str(case_obj.id),
            details={"group_id": group.zalo_group_id, "containers": containers},
        )
        message.processing_status = MessageStatus.NEEDS_REVIEW.value
        db.commit()
        return True

    # 3. Câu hỏi / tra cứu thông tin xe & container theo đúng phạm vi RouteMap
    is_question = bool(
        containers
        or short_conts
        or plates
        or any(kw in norm_text for kw in _CUSTOMER_QUESTION_KEYWORDS)
    )
    if not is_question:
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CUSTOMER_CHAT_IGNORED",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id},
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    has_plan_scope = (
        db.scalar(select(TransportPlan.id).where(TransportPlan.group_id == group.zalo_group_id).limit(1))
        is not None
    )
    if not routes and not has_plan_scope:
        no_route_reply = (
            "Hiện tại nhóm chưa được cấu hình tuyến khách hàng (RouteMap) nên Bot chưa thể "
            "tra cứu dữ liệu. Quý khách vui lòng liên hệ bộ phận Điều hành vận tải để được hỗ trợ."
        )
        _send_or_queue_group_reply(db, group, message, no_route_reply, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CUSTOMER_QA_NO_ROUTEMAP",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id, "raw_text": raw_text},
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    if short_conts and not containers and not plates:
        invalid_cont_reply = (
            f"Mã container {', '.join(short_conts)} chưa đúng chuẩn 11 ký tự (4 chữ + 7 số). "
            "Quý khách vui lòng kiểm tra lại và gửi đầy đủ số container để Bot tra cứu chính xác."
        )
        _send_or_queue_group_reply(db, group, message, invalid_cont_reply, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CUSTOMER_QA_INVALID_CONTAINER",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id, "short_containers": short_conts},
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    jobs, plans = _find_scoped_customer_records(
        db, routes, containers, plates, limit=5, group_zalo_id=group.zalo_group_id
    )

    # Ưu tiên hiển thị theo container để tránh trùng giữa ContainerJob và TransportPlan cùng cont
    lines_out: list[str] = []
    shown_conts: set[str] = set()
    for job in jobs:
        key = (job.container_no or "").upper()
        if key and key in shown_conts:
            continue
        if key:
            shown_conts.add(key)
        lines_out.append(_format_customer_job_summary(db, job))

    for plan in plans:
        key = (plan.container_no or "").upper()
        if key and key in shown_conts:
            continue
        if key:
            shown_conts.add(key)
        lines_out.append(_format_customer_plan_summary(db, plan))

    if lines_out:
        reply_text = "Thông tin điều xe hiện tại:\n" + "\n".join(lines_out[:5])
        _send_or_queue_group_reply(db, group, message, reply_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CUSTOMER_QA_ANSWERED",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={
                "group_id": group.zalo_group_id,
                "containers": containers,
                "plates": plates,
                "result_count": len(lines_out),
            },
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    # Không tìm thấy trong phạm vi RouteMap -> câu trả lời BẮT BUỘC giống hệt nhau
    exists_other_scope = _check_unscoped_existence(db, containers, plates)
    audit_action = "CUSTOMER_QA_OUT_OF_SCOPE" if exists_other_scope else "CUSTOMER_QA_NOT_FOUND"
    _record_activity(
        db,
        actor_id=message.sender_id,
        action=audit_action,
        entity_type="zalo_message",
        entity_id=str(message.id),
        details={
            "group_id": group.zalo_group_id,
            "containers": containers,
            "plates": plates,
            "raw_text": raw_text,
        },
    )

    # Nếu khách hàng hỏi lặp lại mã chưa có dữ liệu từ lần thứ 2 trong 60 phút -> leo thang ĐHVT
    since_cutoff = datetime.now(UTC) - timedelta(minutes=60)
    recent_miss_logs = list(
        db.scalars(
            select(ActivityLog).where(
                ActivityLog.action.in_(["CUSTOMER_QA_NOT_FOUND", "CUSTOMER_QA_OUT_OF_SCOPE"]),
                ActivityLog.created_at >= since_cutoff,
            )
        ).all()
    )
    same_group_misses = [
        lg
        for lg in recent_miss_logs
        if isinstance(lg.details, dict) and lg.details.get("group_id") == group.zalo_group_id
    ]
    if len(same_group_misses) >= 2:
        DhvtNotificationService.create_or_merge_review_case(
            db=db,
            message_id=message.id,
            case_type="CUSTOMER_REPEATED_INQUIRY",
            reason=(
                f"Khách hàng nhóm {group.name} hỏi lại {len(same_group_misses)} lần "
                f"về thông tin chưa có trong tuyến: {raw_text[:200]}"
            ),
            container_no=containers[0] if containers else None,
            details={
                "group_id": group.zalo_group_id,
                "group_name": group.name,
                "inquiry_count": len(same_group_misses),
                "containers": containers,
                "plates": plates,
                "out_of_scope": exists_other_scope,
            },
            suggestion="ĐHVT kiểm tra lại kế hoạch hoặc phân bổ RouteMap cho nhóm khách hàng.",
            is_test_msg=bool(group.is_test),
            notify_zalo=True,
        )

    _send_or_queue_group_reply(db, group, message, _CUSTOMER_LOOKUP_NOT_FOUND_TEXT, order_type="ANSWER")
    message.processing_status = MessageStatus.PROCESSED.value
    db.commit()
    return True


def _resolve_dhvt_deeplink(db: Session, message: ZaloMessage, raw_text: str) -> str:
    """Tìm đường dẫn Web cụ thể từ nội dung lệnh hoặc tin nhắn được quote tại nhóm ĐHVT."""
    base = settings.FRONTEND_BASE_URL.rstrip("/")

    # 1. Trích từ mã ca trong tin nhắn người dùng
    m_case = _CASE_ID_RE.search(raw_text)
    if m_case:
        cid = int(m_case.group(1))
        if db.get(ReviewCase, cid):
            return f"{base}/reviews/{cid}"

    # 2. Trích từ tin nhắn mà ĐHVT đang quote (ReviewCase Form 1 / Pending Outbound Form 2)
    if message.quote_msg_id:
        for rc_cand in db.scalars(
            select(ReviewCase)
            .where(ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]))
            .order_by(ReviewCase.id.desc())
            .limit(100)
        ).all():
            if isinstance(rc_cand.details, dict) and rc_cand.details.get("dhvt_zalo_msg_id") == message.quote_msg_id:
                return f"{base}/reviews/{rc_cand.id}"

        quoted_out = db.scalar(
            select(OutboundMessage).where(
                or_(
                    OutboundMessage.zalo_message_id == message.quote_msg_id,
                    OutboundMessage.review_zalo_msg_id == message.quote_msg_id,
                )
            )
        )
        if quoted_out and quoted_out.review_zalo_msg_id == message.quote_msg_id:
            return f"{base}/results?highlight={quoted_out.id}"
        quoted_text = quoted_out.content if quoted_out else ""
        if not quoted_text:
            quoted_in = db.scalar(
                select(ZaloMessage).where(ZaloMessage.zalo_message_id == message.quote_msg_id)
            )
            quoted_text = quoted_in.message_text or "" if quoted_in else ""

        if quoted_out and quoted_out.message_kind == "dhvt_alert":
            m_out_case = _CASE_ID_RE.search(quoted_text)
            if m_out_case:
                cid = int(m_out_case.group(1))
                if db.get(ReviewCase, cid):
                    return f"{base}/reviews/{cid}"

        m_qcase = _CASE_ID_RE.search(quoted_text)
        if m_qcase:
            cid = int(m_qcase.group(1))
            if db.get(ReviewCase, cid):
                return f"{base}/reviews/{cid}"
        if "cho gui" in _normalize_text(quoted_text) or "chờ gửi" in _normalize_text(quoted_text) or "/results" in quoted_text:
            return f"{base}/results"

        q_conts = _extract_containers(quoted_text)
        if q_conts:
            rc = db.scalar(
                select(ReviewCase)
                .join(ContainerJob, ReviewCase.container_job_id == ContainerJob.id)
                .where(
                    ContainerJob.container_no.in_(q_conts),
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                )
                .order_by(ReviewCase.id.desc())
            )
            if rc:
                return f"{base}/reviews/{rc.id}"

    # 3. Trích theo container xuất hiện trong câu lệnh
    conts = _extract_containers(raw_text)
    if conts:
        rc = db.scalar(
            select(ReviewCase)
            .join(ContainerJob, ReviewCase.container_job_id == ContainerJob.id)
            .where(
                ContainerJob.container_no.in_(conts),
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
            )
            .order_by(ReviewCase.id.desc())
        )
        if rc:
            return f"{base}/reviews/{rc.id}"

    return f"{base}/reviews"


def _format_dhvt_container_report(db: Session, containers: list[str]) -> str:
    """Tổng hợp đầy đủ thông tin nội bộ theo số container cho nhóm ĐHVT (giữ nguyên SĐT)."""
    sections: list[str] = []
    superseded_subq = select(ContainerJob.parent_job_id).where(ContainerJob.parent_job_id.is_not(None))

    for cont in containers[:5]:
        job = db.scalar(
            select(ContainerJob)
            .where(ContainerJob.container_no == cont, ~ContainerJob.id.in_(superseded_subq))
            .order_by(ContainerJob.id.desc())
        )
        plan = db.scalar(
            select(TransportPlan).where(TransportPlan.container_no == cont).order_by(TransportPlan.id.desc())
        )
        if not job and not plan:
            sections.append(f"Container {cont}: Chưa có dữ liệu điều xe hoặc kế hoạch.")
            continue

        parts = [f"Container {cont}:"]
        if job:
            tr = job.truck_record
            cust = db.get(Customer, job.customer_id) if job.customer_id else None
            wh = db.get(Warehouse, job.warehouse_id) if job.warehouse_id else None
            raw = job.raw_fields if isinstance(job.raw_fields, dict) else {}
            parts.append(
                f"  Điều xe (#Job {job.id}): Xe {tr.truck_plate if tr else 'N/A'}"
                f" | Mooc {tr.trailer_plate if tr and tr.trailer_plate else 'N/A'}"
                f" | Tài xế {tr.driver_name if tr else 'N/A'}"
                f" ({tr.driver_phone if tr and tr.driver_phone else 'N/A'})"
            )
            parts.append(
                f"  Khách: {cust.name if cust else (job.customer_hint or 'N/A')}"
                f" | Kho: {wh.name if wh else (job.warehouse_hint or 'N/A')}"
                f" | Seal: {job.seal_no or 'Chưa có'}"
                f" | Hợp lệ: {job.validation_status}"
            )
            if raw.get("local_plan_sync_mode"):
                parts.append(f"  Đồng bộ kế hoạch cục bộ: {raw.get('local_plan_sync_mode')}")

            open_cases = list(
                db.scalars(
                    select(ReviewCase).where(
                        ReviewCase.container_job_id == job.id,
                        ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                    )
                ).all()
            )
            if open_cases:
                parts.append(
                    "  Ca chờ duyệt: "
                    + ", ".join(f"#{c.id} ({c.case_type})" for c in open_cases)
                )

        if plan:
            car = db.get(Carrier, plan.carrier_id) if plan.carrier_id else None
            parts.append(
                f"  Kế hoạch (#Plan {plan.id} v{plan.version}): Nhà xe {car.name if car else 'N/A'}"
                f" | Xe {plan.planned_truck_plate or 'Trống'}"
                f" | TMS: {plan.tms_sync_status}"
            )
        sections.append("\n".join(parts))

    return "\n\n".join(sections)


def _format_dhvt_plate_report(db: Session, plates: list[str]) -> str:
    """Tra cứu các chuyến gắn với biển số xe theo dữ liệu điều xe và kế hoạch gần nhất."""
    sections: list[str] = []
    recent_trucks = list(db.scalars(select(TruckRecord).order_by(TruckRecord.id.desc()).limit(300)).all())
    recent_plans = list(db.scalars(select(TransportPlan).order_by(TransportPlan.id.desc()).limit(300)).all())

    for pl in plates[:3]:
        matched_lines: list[str] = []
        for tr in recent_trucks:
            if compact_plate(tr.truck_plate) != pl:
                continue
            for job in tr.container_jobs:
                cust = db.get(Customer, job.customer_id) if job.customer_id else None
                matched_lines.append(
                    f"  - Cont {job.container_no or 'N/A'} | Tài xế {tr.driver_name or 'N/A'} "
                    f"({tr.driver_phone or 'N/A'}) | Khách {cust.name if cust else 'N/A'}"
                )
        for plan in recent_plans:
            if compact_plate(plan.planned_truck_plate) != pl:
                continue
            car = db.get(Carrier, plan.carrier_id) if plan.carrier_id else None
            matched_lines.append(
                f"  - Kế hoạch #{plan.id} | Cont {plan.container_no or 'Chưa cấp'} "
                f"| Nhà xe {car.name if car else 'N/A'} | Seal {plan.seal_no or 'N/A'}"
            )
        if matched_lines:
            sections.append(f"Biển số {pl}:\n" + "\n".join(matched_lines[:6]))
        else:
            sections.append(f"Biển số {pl}: Chưa ghi nhận điều xe hoặc kế hoạch gần đây.")
    return "\n\n".join(sections)


def _format_dhvt_pending_reviews_report(db: Session) -> str:
    """Thống kê ca rà soát và tin nhắn chờ duyệt gửi khách hàng hiện còn tồn đọng."""
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    pending_cases = list(
        db.scalars(
            select(ReviewCase)
            .where(ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]))
            .order_by(ReviewCase.id.desc())
            .limit(10)
        ).all()
    )
    total_cases = (
        db.scalar(
            select(func.count(ReviewCase.id)).where(
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"])
            )
        )
        or 0
    )
    pending_out = (
        db.scalar(
            select(func.count(OutboundMessage.id)).where(
                OutboundMessage.status == OutboundStatus.PENDING_APPROVAL.value
            )
        )
        or 0
    )

    lines = [
        f"Tổng hợp hàng chờ ĐHVT: {total_cases} ca rà soát | {pending_out} tin chờ duyệt gửi khách."
    ]
    for rc in pending_cases[:5]:
        cj = db.get(ContainerJob, rc.container_job_id) if rc.container_job_id else None
        cont = cj.container_no if cj else None
        if not cont and isinstance(rc.details, dict):
            cont = rc.details.get("container_no")
        prio = rc.details.get("priority", "NORMAL") if isinstance(rc.details, dict) else "NORMAL"
        lines.append(f"- Ca #{rc.id} [{prio}] {rc.case_type} | Cont: {cont or 'N/A'} | {rc.status}")
    lines.append(f"Mở Web xử lý: {base}/reviews")
    return "\n".join(lines)


def _format_dhvt_plans_report(db: Session) -> str:
    """Thống kê nhanh tiến độ khớp xe trên bảng kế hoạch vận chuyển cục bộ."""
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    total = db.scalar(select(func.count(TransportPlan.id))) or 0
    assigned = (
        db.scalar(
            select(func.count(TransportPlan.id)).where(TransportPlan.planned_truck_plate.is_not(None))
        )
        or 0
    )
    missing_cont = (
        db.scalar(
            select(func.count(TransportPlan.id)).where(TransportPlan.container_no.is_(None))
        )
        or 0
    )
    unassigned = max(0, total - assigned)
    return (
        "Tổng quan kế hoạch vận chuyển:\n"
        f"- Tổng kế hoạch: {total}\n"
        f"- Đã cập nhật biển số xe: {assigned}\n"
        f"- Chưa có xe: {unassigned}\n"
        f"- Chưa cấp số container: {missing_cont}\n"
        f"Xem chi tiết tại: {base}/plans"
    )


def _handle_dhvt_group_message(
    db: Session,
    message: ZaloMessage,
    group: ZaloGroup,
) -> bool:
    """Điều phối tin nhắn trong nhóm ĐHVT nội bộ (1.3b & 2.3d): chỉ đọc, cấm duyệt qua Zalo."""
    raw_text = (message.message_text or "").strip()
    norm_text = _normalize_text(raw_text)

    if not raw_text or message.sender_id in ("bot", "vsico_bot"):
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    user = db.scalar(select(User).where(User.zalo_user_id == message.sender_id))
    base = settings.FRONTEND_BASE_URL.rstrip("/")

    # 1. Phát hiện lệnh thao tác nghiệp vụ / quote "ok" -> BẮT BUỘC TỪ CHỐI VÀ DẪN LINK WEB
    is_quote_approval = bool(message.quote_msg_id and norm_text in _DHVT_APPROVAL_EXACT_TOKENS)
    is_direct_approval_token = norm_text in _DHVT_APPROVAL_EXACT_TOKENS
    is_command_prefix = bool(_DHVT_COMMAND_PREFIX_RE.match(norm_text)) and not _DHVT_LOOKUP_QUESTION_RE.search(
        norm_text
    )

    if is_quote_approval or is_direct_approval_token or is_command_prefix:
        deep_link = _resolve_dhvt_deeplink(db, message, raw_text)
        reject_text = (
            "Hệ thống không hỗ trợ thao tác duyệt, sửa, hủy hoặc cho gửi trực tiếp qua Zalo. "
            "Mọi thao tác xử lý của ĐHVT phải thực hiện trên Web quản lý để lưu vết kiểm toán.\n"
            f"Vui lòng thao tác tại: {deep_link}"
        )
        _send_or_queue_group_reply(db, group, message, reject_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=str(user.id) if user else message.sender_id,
            action="DHVT_ZALO_COMMAND_REJECTED",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={
                "group_id": group.zalo_group_id,
                "raw_text": raw_text,
                "quote_msg_id": message.quote_msg_id,
                "redirect_link": deep_link,
            },
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    # 2. Kiểm tra định danh nhân viên ĐHVT trước khi cho phép tra cứu dữ liệu nội bộ
    if user is None or not user.is_active:
        unauth_text = (
            "Tài khoản Zalo của bạn chưa được gắn với nhân viên ĐHVT đang hoạt động trong hệ thống. "
            f"Vui lòng liên hệ Admin hoặc đăng nhập Web để tra cứu: {base}/results"
        )
        _send_or_queue_group_reply(db, group, message, unauth_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="DHVT_UNREGISTERED_LOOKUP_BLOCKED",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id},
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    # 3. Tra cứu nội bộ chỉ đọc
    containers = _extract_containers(raw_text)
    short_conts = _extract_invalid_length_containers(raw_text)
    plates = _extract_plates(raw_text)
    reply_text: Optional[str] = None
    lookup_kind = "none"

    if containers:
        lookup_kind = "container"
        reply_text = _format_dhvt_container_report(db, containers)
    elif plates:
        lookup_kind = "plate"
        reply_text = _format_dhvt_plate_report(db, plates)
    elif any(
        kw in norm_text
        for kw in ("ca cho", "ca chờ", "pending", "can duyet", "cần duyệt", "hang cho", "hàng chờ", "ton dong", "tồn đọng")
    ):
        lookup_kind = "pending_reviews"
        reply_text = _format_dhvt_pending_reviews_report(db)
    elif any(
        kw in norm_text
        for kw in ("ke hoach", "kế hoạch", "nha xe", "nhà xe", "plan", "chua co xe", "chưa có xe")
    ):
        lookup_kind = "plans"
        reply_text = _format_dhvt_plans_report(db)
    elif any(kw in norm_text for kw in ("tra cuu", "tra cứu", "huong dan", "hướng dẫn", "help")):
        lookup_kind = "help"
        reply_text = (
            "Cú pháp tra cứu nội bộ ĐHVT (chỉ đọc):\n"
            "- Nhập số container (VD: TCNU1234567) để xem điều xe, kế hoạch, seal, ca chờ\n"
            "- Nhập biển số xe (VD: 15H-01234) để xem lịch trình xe\n"
            "- Nhắn 'ca cho' để xem tổng hợp ca rà soát và tin chờ duyệt\n"
            "- Nhắn 'ke hoach' để xem tiến độ ghép xe trên kế hoạch"
        )

    if reply_text:
        _send_or_queue_group_reply(db, group, message, reply_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=str(user.id),
            action="DHVT_INTERNAL_LOOKUP",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"lookup_kind": lookup_kind, "containers": containers, "plates": plates},
        )

    message.processing_status = MessageStatus.PROCESSED.value
    db.commit()
    return True


def _is_carrier_qa_message(raw_text: str, norm_text: str) -> bool:
    """Phân biệt tin hỏi đáp tra cứu ở nhóm Nhà xe với tin báo điều xe/bổ sung/đổi xe."""
    if _CARRIER_DISPATCH_SIGNAL_RE.search(raw_text):
        return False
    return any(kw in norm_text for kw in _CARRIER_QA_KEYWORDS)


def _handle_carrier_group_qa(
    db: Session,
    message: ZaloMessage,
    group: ZaloGroup,
) -> bool:
    """Xử lý tra cứu kế hoạch và container cho nhóm Nhà xe (`SOURCE`/`CARRIER`) khi có câu hỏi Q&A."""
    raw_text = (message.message_text or "").strip()
    norm_text = _normalize_text(raw_text)
    if not raw_text or message.sender_id in ("bot", "vsico_bot"):
        return False
    if not _is_carrier_qa_message(raw_text, norm_text):
        return False

    containers = _extract_containers(raw_text)
    short_conts = _extract_invalid_length_containers(raw_text)
    plates = _extract_plates(raw_text)

    if not group.carrier_id:
        reply_text = (
            "Nhóm Zalo này chưa được liên kết với Nhà xe trong hệ thống nên Bot chưa thể "
            "tra cứu kế hoạch hoặc container. Vui lòng liên hệ Điều hành vận tải để gắn Nhà xe cho nhóm."
        )
        _send_or_queue_group_reply(db, group, message, reply_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CARRIER_QA_UNASSIGNED",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id, "raw_text": raw_text},
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    if short_conts and not containers and not plates:
        reply_text = (
            f"Mã container {', '.join(short_conts)} chưa đúng chuẩn 11 ký tự (4 chữ + 7 số). "
            "Vui lòng kiểm tra và gửi lại mã container đầy đủ để Bot tra cứu chính xác."
        )
        _send_or_queue_group_reply(db, group, message, reply_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CARRIER_QA_INVALID_CONTAINER",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id, "short_containers": short_conts},
        )
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return True

    stmt = select(TransportPlan).where(TransportPlan.carrier_id == group.carrier_id)
    if containers:
        stmt = stmt.where(TransportPlan.container_no.in_(containers))
    elif plates:
        norm_plates = [compact_plate(p) for p in plates]
        stmt = stmt.where(
            or_(*[func.replace(func.replace(TransportPlan.planned_truck_plate, "-", ""), ".", "").in_(norm_plates)])
        )
    elif "hom nay" in norm_text or "hôm nay" in norm_text:
        stmt = stmt.where(TransportPlan.plan_date == datetime.now(UTC).date())

    plans = list(db.scalars(stmt.order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc()).limit(5)).all())
    if plans:
        lines_out = []
        for p in plans:
            cont_label = p.container_no or "Chưa gán cont"
            plate_label = p.planned_truck_plate or "Chưa gán xe"
            route_label = p.delivery_address or p.route_name or "Chưa có tuyến/kho"
            time_label = p.required_time or "Chưa rõ giờ"
            date_label = p.plan_date.isoformat() if p.plan_date else "—"
            lines_out.append(
                f"- [{date_label}] Cont {cont_label} | {p.order_type or '—'} | Xe: {plate_label} | {route_label} | Giờ YC: {time_label}"
            )
        reply_text = "Thông tin kế hoạch của nhà xe:\n" + "\n".join(lines_out)
        _send_or_queue_group_reply(db, group, message, reply_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CARRIER_QA_ANSWERED",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id, "carrier_id": str(group.carrier_id), "result_count": len(plans)},
        )
    else:
        reply_text = (
            "Hiện tại hệ thống chưa ghi nhận kế hoạch hoặc container phù hợp thuộc phạm vi nhà xe. "
            "Vui lòng kiểm tra lại mã tra cứu hoặc liên hệ Điều hành vận tải."
        )
        _send_or_queue_group_reply(db, group, message, reply_text, order_type="ANSWER")
        _record_activity(
            db,
            actor_id=message.sender_id,
            action="CARRIER_QA_NOT_FOUND",
            entity_type="zalo_message",
            entity_id=str(message.id),
            details={"group_id": group.zalo_group_id, "carrier_id": str(group.carrier_id), "containers": containers, "plates": plates},
        )

    message.processing_status = MessageStatus.PROCESSED.value
    db.commit()
    return True


def route_conversation(db: Session, message: ZaloMessage) -> bool:
    """
    Điều hướng tin nhắn sang luồng hội thoại Khách hàng, ĐHVT, hoặc hỏi đáp Nhà xe.

    Trả về True nếu tin nhắn đã được xử lý xong theo luồng hội thoại,
    hoặc False nếu tin nhắn cần đi tiếp vào luồng bóc tách điều xe.
    """
    group = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == message.group_id))
    if not group or not group.is_active:
        return False

    role = (group.group_role or "").upper()
    if role in ("CUSTOMER", "DESTINATION"):
        return _handle_customer_group_message(db, message, group)
    if role == "DHVT":
        return _handle_dhvt_group_message(db, message, group)
    if role in ("SOURCE", "CARRIER"):
        return _handle_carrier_group_qa(db, message, group)
    return False
