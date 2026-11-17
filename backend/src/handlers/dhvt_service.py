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

from datetime import datetime, timedelta, timezone
import unicodedata
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
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
    "ROUTING_NOT_FOUND": "Chưa xác định nhóm khách hàng",
    "MISSING_INFO": "Thiếu thông tin điều phối",
    "WAREHOUSE_LOW_CONFIDENCE": "Cần xác nhận kho đóng/trả",
    "AMBIGUOUS_PLAN": "Nhiều kế hoạch trùng khớp",
    "PLAN_CONFLICT": "Xung đột thông tin kế hoạch",
    "INVALID_CONTAINER_CHECKDIGIT": "Sai số container (ISO 6346)",
    "DUPLICATE_OR_CONFLICT": "Trùng lặp / xung đột dữ liệu",
    "CARRIER_CHANGE_REQUEST": "Nhà xe đề nghị đổi thông tin",
    "CARRIER_CANCEL_OR_ISSUE": "Nhà xe báo hủy / sự cố",
    "CARRIER_CORRECTION_OVERDUE": "Nhà xe quá hạn bổ sung",
    "OTHER": "Cần ĐHVT kiểm tra",
}

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
    def _resolve_review_case_context(
        cls,
        db: Optional[Session],
        case_obj: ReviewCase,
        container_no: Optional[str] = None,
        carrier_name: Optional[str] = None,
    ) -> dict[str, Optional[str]]:
        """Tra cứu tên hiển thị thân thiện (mã lệnh, khách, kho, nhà xe, xe/tài xế) cho ca duyệt."""
        details = dict(case_obj.details or {})
        cont = (container_no or details.get("container_no") or "").strip().upper() or None
        order_code: Optional[str] = str(details.get("order_code") or "").strip() or None
        order_type: Optional[str] = str(details.get("order_type") or "").strip() or None
        customer_name: Optional[str] = str(details.get("customer_name") or "").strip() or None
        warehouse_name: Optional[str] = str(details.get("warehouse_name") or "").strip() or None
        resolved_carrier: Optional[str] = (carrier_name or str(details.get("carrier_name") or "")).strip() or None
        truck_plate: Optional[str] = str(details.get("truck_plate") or "").strip() or None
        driver_name: Optional[str] = str(details.get("driver_name") or "").strip() or None
        target_group_name: Optional[str] = None

        if db is None:
            return {
                "order_label": _format_order_label(order_code, order_type),
                "container_no": cont,
                "customer_name": customer_name,
                "warehouse_name": warehouse_name,
                "carrier_name": resolved_carrier,
                "vehicle_driver": " - ".join(p for p in (truck_plate, driver_name) if p) or None,
            }

        plan_id = _to_int_id(details.get("transport_plan_id"))
        plan = db.get(TransportPlan, plan_id) if plan_id else None
        if plan:
            order_code = order_code or (plan.order_code or None)
            order_type = order_type or (plan.order_type or None)
            cont = cont or (plan.container_no or "").strip().upper() or None
            customer_name = customer_name or (plan.customer_name or None)
            warehouse_name = warehouse_name or (plan.warehouse_name or plan.delivery_address or None)
            resolved_carrier = resolved_carrier or (plan.carrier_name or plan.fleet_partner or None)
            truck_plate = truck_plate or (plan.planned_truck_plate or None)
            driver_name = driver_name or (plan.driver_name or None)
            if not resolved_carrier and plan.carrier_id:
                c_obj = db.get(Carrier, plan.carrier_id)
                if c_obj and c_obj.name:
                    resolved_carrier = c_obj.name

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
                        driver_name = driver_name or (tr.driver_name or None)

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

        if not resolved_carrier and case_obj.message_id:
            msg = db.get(ZaloMessage, case_obj.message_id)
            if msg and msg.group_id:
                src_grp = db.scalar(
                    select(ZaloGroup).where(ZaloGroup.zalo_group_id == msg.group_id)
                )
                if src_grp:
                    if src_grp.carrier_name:
                        resolved_carrier = src_grp.carrier_name
                    else:
                        grp_carrier_id = _to_int_id(src_grp.carrier_id)
                        if grp_carrier_id:
                            c_obj = db.get(Carrier, grp_carrier_id)
                            if c_obj and c_obj.name:
                                resolved_carrier = c_obj.name
                    if not resolved_carrier and (src_grp.group_role or "").upper() == "SOURCE":
                        resolved_carrier = src_grp.name or None

        customer_display = customer_name or target_group_name
        if warehouse_name and len(warehouse_name) > 70:
            warehouse_name = warehouse_name[:67].rstrip() + "..."
        vehicle_driver = " - ".join(p for p in (truck_plate, driver_name) if p) or None

        return {
            "order_label": _format_order_label(order_code, order_type),
            "container_no": cont,
            "customer_name": customer_display,
            "warehouse_name": warehouse_name,
            "carrier_name": resolved_carrier,
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
        """Form 1: Thông báo ca cần duyệt gọn gàng bằng tiếng Việt, chỉ hiển thị tên/mã nghiệp vụ."""
        link = cls._web_url("/reviews")
        case_label = _CASE_TYPE_LABELS.get(case_obj.case_type, case_obj.case_type)
        header = (
            f"[VSICO - ƯU TIÊN CAO] Ca cần duyệt - {case_label}"
            if (priority or "").upper() == "HIGH"
            else f"[VSICO] Ca cần duyệt - {case_label}"
        )
        ctx = cls._resolve_review_case_context(
            db=db,
            case_obj=case_obj,
            container_no=container_no,
            carrier_name=carrier_name,
        )

        lines = [header]
        order_parts = [
            f"Lệnh: {ctx['order_label']}" if ctx.get("order_label") else "",
            f"Cont: {ctx['container_no']}" if ctx.get("container_no") else "",
        ]
        order_line = " | ".join(p for p in order_parts if p)
        if order_line:
            lines.append(order_line)

        party_parts = [
            f"Khách hàng: {ctx['customer_name']}" if ctx.get("customer_name") else "",
            f"Kho: {ctx['warehouse_name']}" if ctx.get("warehouse_name") else "",
        ]
        party_line = " | ".join(p for p in party_parts if p)
        if party_line:
            lines.append(party_line)

        transport_parts = [
            f"Nhà xe: {ctx['carrier_name']}" if ctx.get("carrier_name") else "",
            f"Xe: {ctx['vehicle_driver']}" if ctx.get("vehicle_driver") else "",
        ]
        transport_line = " | ".join(p for p in transport_parts if p)
        if transport_line:
            lines.append(transport_line)

        if case_obj.reason:
            lines.append(f"Lý do: {case_obj.reason}")
        if suggestion:
            lines.append(f"Gợi ý: {suggestion}")
        lines.append(f"Xử lý trên Web: {link}")
        return "\n".join(lines)

    @classmethod
    def render_pending_outbound_alert(
        cls,
        outbound: OutboundMessage,
        target_group_name: str,
        containers: list[str],
        reason: str,
    ) -> str:
        """Form 2: Thông báo tin gửi khách đang chờ duyệt trên Web gửi nhóm Zalo ĐHVT."""
        link = cls._web_url("/results")
        cont_str = ", ".join(c for c in containers if c) or "Chưa rõ"
        order_label = _format_order_label(None, outbound.order_type) or outbound.order_type
        lines = [
            "[VSICO - TIN CHO DUYET]",
            f"Nhóm khách hàng: {target_group_name}",
            f"Container: {cont_str} | Lệnh: {order_label}",
            f"Lý do chờ: {reason}",
            f"Duyệt phát hành trên Web: {link}",
        ]
        return "\n".join(lines)

    @classmethod
    def render_system_alert(
        cls,
        title: str,
        body: str,
        web_path: str = "/reviews",
    ) -> str:
        """Form 3: Cảnh báo hệ thống / lỗi gửi Zalo / lỗi TMS / quá hạn gửi nhóm Zalo ĐHVT."""
        link = cls._web_url(web_path)
        return (
            f"[VSICO - CẢNH BÁO HỆ THỐNG] {title}\n"
            f"{body}\n"
            f"Kiểm tra trên Web: {link}"
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
    ) -> Optional[str]:
        """Gửi Form 2 báo nhóm Zalo ĐHVT khi có tin gửi khách chuyển sang PENDING_APPROVAL."""
        alert_text = cls.render_pending_outbound_alert(
            outbound=outbound,
            target_group_name=target_group_name,
            containers=containers,
            reason=reason,
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

        db.add(
            ActivityLog(
                id=snowflake.generate(),
                actor_id="vsico_bot",
                action="DHVT_PENDING_OUTBOUND_ALERT",
                entity_type="outbound_message",
                entity_id=str(outbound.id),
                details={
                    "target_group_name": target_group_name,
                    "containers": containers,
                    "reason": reason,
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
        alert_text = cls.render_system_alert(title=title, body=body, web_path=web_path)
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
    def check_overdue_escalations(cls, db: Session, is_test_msg: bool = False) -> dict[str, int]:
        """Quét các phản hồi nhà xe, ca duyệt và tin chờ duyệt quá hạn để nhắc ĐHVT / leo thang Admin."""
        now = datetime.now(timezone.utc)
        overdue_replies = 0
        reminded_reviews = 0
        reminded_outbounds = 0
        admin_escalations = 0

        # 1. Nhà xe quá hạn 30 phút sửa tin nhắn (`bot_replies`) -> tạo ReviewCase + báo ĐHVT
        expired_replies = list(
            db.scalars(
                select(BotReply).where(
                    BotReply.status.in_([CorrectionStatus.PENDING.value, "PENDING"]),
                    BotReply.fix_deadline < now,
                ).limit(50)
            ).all()
        )
        for br in expired_replies:
            br.status = CorrectionStatus.CANCELLED.value
            overdue_replies += 1
            cls.create_or_merge_review_case(
                db=db,
                message_id=br.message_id,
                case_type="CARRIER_CORRECTION_OVERDUE",
                reason="Nhà xe quá hạn 30 phút chưa bổ sung thông tin theo nhắc nhở của Bot.",
                details={"bot_reply_id": br.id, "sender_id": br.sender_id},
                suggestion="Liên hệ trực tiếp nhà xe hoặc kiểm tra lại tin gốc trên Web.",
                priority="HIGH",
                is_test_msg=is_test_msg,
            )

        # 2. Ca ReviewCase chờ xử lý quá hạn (> 30 phút) -> nhắc lần 1 ĐHVT, quá lần 2 báo Admin
        review_cutoff = now - timedelta(minutes=30)
        stale_reviews = list(
            db.scalars(
                select(ReviewCase).where(
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                    ReviewCase.created_at < review_cutoff,
                ).limit(50)
            ).all()
        )
        for rc in stale_reviews:
            details = dict(rc.details or {})
            remind_count = int(details.get("reminder_count", 0))
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
            case_label = _CASE_TYPE_LABELS.get(rc.case_type, rc.case_type)
            cont_label = str((rc.details or {}).get("container_no") or "").strip()
            case_desc = f"{case_label} - Cont {cont_label}" if cont_label else case_label
            if remind_count >= 2:
                admin_escalations += 1
                cls.notify_system_alert(
                    db=db,
                    title="LEO THANG ADMIN - CA DUYET QUA HAN",
                    body=f"Ca duyệt ({case_desc}) đã quá hạn xử lý lần {remind_count}. Lý do: {rc.reason}",
                    entity_type="review_case",
                    entity_id=str(rc.id),
                    web_path="/reviews",
                    is_test_msg=is_test_msg,
                )
            else:
                cls.notify_system_alert(
                    db=db,
                    title="NHAC CA CHO DUYET QUA HAN",
                    body=f"Ca duyệt ({case_desc}) đang chờ ĐHVT xử lý hơn 30 phút.",
                    entity_type="review_case",
                    entity_id=str(rc.id),
                    web_path="/reviews",
                    is_test_msg=is_test_msg,
                )

        # 3. Tin gửi khách chờ duyệt quá hạn (> 30 phút) -> nhắc ĐHVT / leo thang Admin
        stale_outbounds = list(
            db.scalars(
                select(OutboundMessage).where(
                    OutboundMessage.status.in_([OutboundStatus.PENDING_APPROVAL.value, "cho_duyet"]),
                    OutboundMessage.created_at < review_cutoff,
                ).limit(50)
            ).all()
        )
        for ob in stale_outbounds:
            existing_rem = db.scalar(
                select(func.count(ActivityLog.id)).where(
                    ActivityLog.entity_type == "outbound_message",
                    ActivityLog.entity_id == str(ob.id),
                    ActivityLog.action.in_(["NHAC TIN CHO DUYET QUA HAN", "LEO THANG ADMIN - TIN CHO DUYET QUA HAN"]),
                )
            ) or 0
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
            group_label = ob.target_group.name if ob.target_group and ob.target_group.name else "Khách hàng"
            if existing_rem >= 1:
                admin_escalations += 1
                cls.notify_system_alert(
                    db=db,
                    title="LEO THANG ADMIN - TIN CHO DUYET QUA HAN",
                    body=f"Tin gửi nhóm {group_label} đã chờ duyệt quá 2 lượt nhắc.",
                    entity_type="outbound_message",
                    entity_id=str(ob.id),
                    web_path="/results",
                    is_test_msg=is_test_msg,
                )
            else:
                cls.notify_system_alert(
                    db=db,
                    title="NHAC TIN CHO DUYET QUA HAN",
                    body=f"Tin gửi nhóm {group_label} đang ở trạng thái chờ duyệt quá 30 phút.",
                    entity_type="outbound_message",
                    entity_id=str(ob.id),
                    web_path="/results",
                    is_test_msg=is_test_msg,
                )

        db.commit()
        return {
            "overdue_carrier_replies": overdue_replies,
            "reminded_review_cases": reminded_reviews,
            "reminded_pending_outbounds": reminded_outbounds,
            "admin_escalations": admin_escalations,
        }
