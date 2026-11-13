"""Dịch vụ nghiệp vụ chuyên biệt cho luồng Nhà xe - Bot - Khách hàng - ĐHVT.

Tách biệt các bước xử lý nghiệp vụ sâu theo đặc tả luồng Zalo (`docs/zalo.md`):
1. Lưu metadata file ảnh Zalo vào bảng `files` phục vụ truy vết OCR/MinIO.
2. Định danh nhóm Zalo nhà xe (`zalo_groups`), đối soát đơn vị vận tải (`carriers`)
   và kiểm tra quyền sở hữu chuyến/shipping (`transport_plans`).
3. Đối chiếu địa chỉ kho qua `ai-service` (`/api/v1/match-warehouse`) khi chưa có cont.
4. Xử lý phản hồi trích dẫn (`quote_msg_id`) và gộp bổ sung thông tin thiếu vào `ContainerJob` / `BotReply`.
5. Xử lý yêu cầu Sửa/Đổi xe/Đổi tài xế (`UPDATE_REQUEST`) và Hủy chuyến (`CANCEL_REQUEST`).
6. Cảnh báo ĐHVT qua `activity_logs` / nhóm nội bộ và tạo `ReviewCase` khi gửi Zalo lỗi 3 lần.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.enums import (
    CorrectionStatus,
    GroupRole,
    MessageDraftStatus,
    MessageStatus,
    OrderType,
    OutboundStatus,
    ReviewStatus,
    RoutingStatus,
    SendMode,
    StorageStatus,
    TmsSyncStatus,
    ValidationStatus,
)
from contextlib import nullcontext
from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_container, clean_phone, clean_plate, compact_plate
from src.handlers.dhvt_service import DhvtNotificationService
from src.handlers.plan_sync_service import resolve_plan_detailed, sync_job_to_local_plan
from src.infrastructure.ai_service_client import AIServiceClient
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    Carrier,
    ContainerJob,
    Customer,
    FileRecord,
    MessageDraft,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TransportPlan,
    TruckRecord,
    User,
    Warehouse,
    WarehouseAlias,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher
from src.observability.logging import get_logger
from src.outbound.templates import OutboundTemplateBuilder
from src.validation.validators import ContainerValidator

logger = get_logger(__name__)


def normalize_vi_text(text: str | None) -> str:
    """Chuẩn hóa chuỗi tiếng Việt về không dấu chữ thường để đối soát tên nhà xe/kho."""
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", str(text))
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", stripped).strip().lower()


@dataclass
class CarrierContext:
    """Ngữ cảnh định danh nhà xe và nhóm gửi tin nhắn."""

    source_group: ZaloGroup | None = None
    carrier: Carrier | None = None
    numeric_carrier_id: int | None = None
    carrier_names: set[str] = field(default_factory=set)
    is_internal_user: bool = False
    is_test_msg: bool = False
    is_blocked_inactive: bool = False
    is_unregistered_group: bool = False


@dataclass
class CarrierPlanCheck:
    """Kết quả đối chiếu kế hoạch (`transport_plans`) và quyền sở hữu của nhà xe."""

    matched_plan: TransportPlan | None = None
    is_carrier_mismatch: bool = False
    is_shipping_missing: bool = False
    reason: str | None = None


class CarrierFlowService:
    """Tập hợp phương thức điều phối luồng Bot - Nhà xe bảo đảm clean code và không trùng lặp."""

    @staticmethod
    def is_test_message(message: ZaloMessage, source_group: ZaloGroup | None = None) -> bool:
        """Nhận diện tin nhắn mô phỏng/kiểm thử để không gửi nhầm ra nhóm Zalo thật bên ngoài."""
        raw_p = message.raw_payload or {}
        gid = message.group_id or ""
        zmid = message.zalo_message_id or ""
        sid = message.sender_id or ""
        return bool(
            raw_p.get("is_test")
            or raw_p.get("is_simulation")
            or raw_p.get("is_test_runner")
            or (source_group and source_group.is_test)
            or gid.startswith(("test_", "grp_test_", "pytest_"))
            or zmid.startswith(("test_", "pytest_"))
            or "TC-" in zmid
            or "_m1" in zmid
            or sid.startswith(("test_", "pytest_"))
        )

    @staticmethod
    def _is_dispatchable_real_group(
        target_gid: str | None,
        target_grp: ZaloGroup | None,
        is_test_msg: bool,
    ) -> bool:
        """Kiểm tra có được phép phát hành tin nhắn thật ra Zalo Bridge hay không."""
        if not settings.AUTO_DISPATCH_OUTBOUND or not target_gid or is_test_msg:
            return False
        if target_grp and target_grp.is_test:
            return False
        if target_gid == "2001000000000000001":
            return False
        return not target_gid.startswith(("grp_test_", "test_", "pytest_", "direct_"))

    @classmethod
    def record_image_file_metadata(
        cls,
        db: Session,
        message: ZaloMessage,
        payload_dict: dict[str, Any],
        image_input: str | None,
        ocr_meta: dict[str, Any] | None = None,
    ) -> None:
        """Lưu metadata tệp ảnh Zalo vào bảng `files` để đồng bộ MinIO và truy vết OCR."""
        if not image_input:
            return
        existing = db.scalar(select(FileRecord.id).where(FileRecord.message_id == message.id))
        if existing is not None:
            return

        raw_str = str(image_input).strip()
        raw_bytes = raw_str.encode("utf-8", errors="ignore")
        sha = hashlib.sha256(raw_bytes).hexdigest()
        is_data_uri = raw_str.startswith("data:") or (len(raw_str) > 256 and not raw_str.startswith("http"))
        mime = "image/png" if "png" in raw_str[:64].lower() else "image/jpeg"

        record = FileRecord(
            id=snowflake.generate(),
            file_key=f"zalo_img_{message.id}_{sha[:12]}",
            bucket=settings.MINIO_BUCKET_NAME or "vsico-zalo-files",
            object_key=f"inbound/{message.group_id}/{message.id}.jpg",
            original_name=f"zalo_{message.zalo_message_id}.jpg",
            mime_type=mime,
            size_bytes=len(raw_bytes),
            sha256=sha,
            source_type="ZALO_IMAGE",
            source_url=None if is_data_uri else raw_str[:1000],
            message_id=message.id,
            storage_status=StorageStatus.PENDING.value,
            meta={
                "group_id": message.group_id,
                "sender_id": message.sender_id,
                "ocr": ocr_meta or {},
            },
        )
        db.add(record)
        db.flush()

    @classmethod
    def resolve_carrier_context(cls, db: Session, message: ZaloMessage) -> CarrierContext:
        """Xác định thông tin nhóm Zalo nhà xe, bản ghi `carriers` và quyền người gửi."""
        source_group = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == message.group_id))
        is_test = cls.is_test_message(message, source_group)
        ctx = CarrierContext(source_group=source_group, is_test_msg=is_test)

        internal_user = db.scalar(
            select(User).where(User.zalo_user_id == message.sender_id, User.is_active == True)
        )
        ctx.is_internal_user = internal_user is not None

        if source_group:
            if not is_test and not source_group.is_active:
                ctx.is_blocked_inactive = True
            if source_group.carrier_name:
                norm_g_carrier = normalize_vi_text(source_group.carrier_name)
                if norm_g_carrier:
                    ctx.carrier_names.add(norm_g_carrier)
            if source_group.carrier_id:
                cid_str = str(source_group.carrier_id).strip()
                carrier_filters = [Carrier.code == cid_str]
                if cid_str.isdigit():
                    cid_int = int(cid_str)
                    carrier_filters.append(Carrier.id == cid_int)
                    carrier_filters.append(Carrier.tms_carrier_id == cid_int)
                carrier = db.scalar(select(Carrier).where(or_(*carrier_filters)))
                if carrier:
                    ctx.carrier = carrier
                    ctx.numeric_carrier_id = carrier.id
                    for cand in (carrier.name, carrier.short_name, carrier.normalized_name, carrier.code):
                        norm_c = normalize_vi_text(cand)
                        if norm_c:
                            ctx.carrier_names.add(norm_c)
        elif not is_test:
            # Nếu hệ thống đã khai báo nhóm nhà xe thật mà tin đến từ nhóm lạ chưa đăng ký -> đánh dấu cảnh báo
            registered_carrier_count = db.scalar(
                select(func.count(ZaloGroup.id)).where(
                    ZaloGroup.is_test == False,
                    ZaloGroup.is_active == True,
                    ZaloGroup.group_role.in_([GroupRole.SOURCE.value, GroupRole.CARRIER.value]),
                )
            ) or 0
            if registered_carrier_count > 0 and not (message.group_id or "").startswith("direct_"):
                ctx.is_unregistered_group = True

        return ctx

    @classmethod
    def log_activity(
        cls,
        db: Session,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Ghi nhật ký thao tác hệ thống và người dùng vào bảng `activity_logs`."""
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

    @classmethod
    def alert_dhvt(
        cls,
        db: Session,
        title: str,
        body: str,
        entity_type: str,
        entity_id: str | None,
        is_test_msg: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Ghi log cảnh báo và gửi tin tới nhóm ĐHVT nội bộ qua DhvtNotificationService (mẫu 3)."""
        DhvtNotificationService.notify_system_alert(
            db=db,
            title=title,
            body=body,
            entity_type=entity_type,
            entity_id=entity_id,
            web_path="/reviews",
            dedup_minutes=30,
            is_test_msg=is_test_msg,
            details=details,
        )

    @classmethod
    def create_send_failed_alert(
        cls,
        db: Session,
        message: ZaloMessage,
        container_job: ContainerJob,
        outbound_msg: OutboundMessage,
        target_group_name: str,
        error_text: str,
        is_test_msg: bool,
    ) -> ReviewCase:
        """Tạo ca rà soát khẩn cấp và báo ĐHVT khi gửi Zalo thất bại sau 3 lần thử."""
        rc, _created = DhvtNotificationService.create_or_merge_review_case(
            db=db,
            message_id=message.id,
            case_type="OUTBOUND_SEND_FAILED",
            reason=f"Gửi thông báo cont {container_job.container_no or ''} tới nhóm '{target_group_name}' thất bại sau 3 lần thử: {error_text}",
            container_job_id=container_job.id,
            container_no=container_job.container_no,
            details={
                "outbound_message_id": outbound_msg.id,
                "container_no": container_job.container_no,
                "target_group_id": outbound_msg.target_group_id,
                "error": error_text,
            },
            suggestion="Kiểm tra nội dung trên Web (/results), gửi thủ công và bấm 'Đã gửi thủ công'.",
            priority="HIGH",
            is_test_msg=is_test_msg,
            notify_zalo=True,
        )
        cls.alert_dhvt(
            db=db,
            title="LOI GUI TIN ZALO KHACH HANG",
            body=(
                f"Không thể gửi thông báo cont {container_job.container_no or 'N/A'} "
                f"tới nhóm {target_group_name} sau 3 lần thử.\n"
                f"Lỗi: {error_text}\n"
                f"Vui lòng copy nội dung trên Web để gửi thủ công và bấm 'Đã gửi thủ công'."
            ),
            entity_type="outbound_message",
            entity_id=str(outbound_msg.id),
            is_test_msg=is_test_msg,
        )
        return rc

    @classmethod
    def sync_job_with_local_plan_or_review(
        cls,
        db: Session,
        job: ContainerJob,
        source_group: ZaloGroup | None,
        is_test_msg: bool,
    ) -> bool:
        """Đồng bộ ContainerJob lên TransportPlan cục bộ (điền trống/cập nhật) hoặc tạo ReviewCase nếu xung đột."""
        if not source_group or not source_group.is_active:
            return True
        plan_res = resolve_plan_detailed(db, job, source_group, for_update=True)
        if plan_res.plan is not None:
            outcome = sync_job_to_local_plan(
                db=db,
                job=job,
                plan=plan_res.plan,
                allow_plan_override=False,
                actor_id="vsico_bot",
            )
            if outcome.mode == "CONFLICT":
                plan_has_driver = bool(plan_res.plan.planned_truck_plate or plan_res.plan.driver_name)
                reasons_str = "; ".join(outcome.conflict_reasons) or "Xung đột dữ liệu cố định trên kế hoạch."
                DhvtNotificationService.create_or_merge_review_case(
                    db=db,
                    message_id=job.message_id,
                    case_type="PLAN_FIELD_CONFLICT",
                    reason=reasons_str,
                    container_job_id=job.id,
                    container_no=job.container_no,
                    details={
                        "plan_id": outcome.plan_id,
                        "conflicts": outcome.conflict_reasons,
                        "plan_has_driver": plan_has_driver,
                    },
                    suggestion="ĐHVT đối chiếu lại số chì/loại lệnh với nhà xe và duyệt trên Web.",
                    priority="HIGH",
                    is_test_msg=is_test_msg,
                    notify_zalo=True,
                )
                orig_msg = db.get(ZaloMessage, job.message_id)
                if orig_msg:
                    if not plan_has_driver:
                        carrier_warn = (
                            f"[VSICO Bot] Thông tin cont {job.container_no or ''} bị lệch so với kế hoạch "
                            f"({reasons_str}). Anh/chị vui lòng kiểm tra lại và quote tin này để xác nhận/sửa lại cho đúng."
                        )
                    else:
                        carrier_warn = (
                            f"[VSICO Bot] Đề xuất cập nhật cont {job.container_no or ''} có điểm lệch với kế hoạch "
                            f"({reasons_str}). Hệ thống đã chuyển ĐHVT kiểm tra đối chiếu."
                        )
                    conflict_reply = BotReply(
                        id=snowflake.generate(),
                        message_id=orig_msg.id,
                        sender_id=orig_msg.sender_id,
                        reply_text=carrier_warn,
                        fix_deadline=datetime.now(UTC) + timedelta(minutes=30),
                        status=CorrectionStatus.PENDING.value,
                    )
                    db.add(conflict_reply)
                    db.flush()
                    if cls._is_dispatchable_real_group(orig_msg.group_id, source_group, is_test_msg):
                        ok_send, z_mid, _ = ZaloDispatcher.send_to_group(
                            group_id=orig_msg.group_id,
                            message=carrier_warn,
                            quote_msg_id=orig_msg.zalo_message_id,
                        )
                        if not ok_send and orig_msg.zalo_message_id:
                            ok_send, z_mid, _ = ZaloDispatcher.send_to_group(
                                group_id=orig_msg.group_id,
                                message=carrier_warn,
                            )
                        if ok_send and z_mid:
                            conflict_reply.zalo_msg_id = z_mid
                            conflict_reply.sent_at = datetime.now(UTC)
                return False
            return True

        if plan_res.status in ("MULTIPLE_PLANS", "MULTIPLE_EMPTY_PLANS"):
            DhvtNotificationService.create_or_merge_review_case(
                db=db,
                message_id=job.message_id,
                case_type="PLAN_SYNC_REQUIRED",
                reason=plan_res.reason,
                container_job_id=job.id,
                container_no=job.container_no,
                details={"candidate_plan_ids": plan_res.candidate_plan_ids, "status": plan_res.status},
                suggestion="ĐHVT chọn đúng 1 dòng kế hoạch trên Web để ghép xe.",
                is_test_msg=is_test_msg,
                notify_zalo=True,
            )
            return False

        return True

    @classmethod
    def supersede_pending_outbounds_for_container(
        cls,
        db: Session,
        container_no: str | None,
        keep_outbound_id: int | None = None,
    ) -> int:
        """Đóng các bản nháp thông báo PENDING_APPROVAL cũ của cùng container khi có bản cập nhật mới."""
        if not container_no:
            return 0
        stmt = (
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .join(ContainerJob, OutboundMessageItem.container_job_id == ContainerJob.id)
            .where(
                ContainerJob.container_no == container_no,
                OutboundMessage.status == OutboundStatus.PENDING_APPROVAL.value,
            )
        )
        if keep_outbound_id is not None:
            stmt = stmt.where(OutboundMessage.id != keep_outbound_id)
        count = 0
        for stale in db.scalars(stmt).all():
            stale.status = OutboundStatus.CANCELLED.value
            stale.last_error = "Đã thay thế bằng bản cập nhật thông tin xe mới hơn."
            count += 1
        return count

    @classmethod
    def load_active_plans_for_ai(cls, db: Session, raw_text: str, carrier_id: int | None = None) -> list[dict[str, Any]]:
        """Nạp tối đa 5 kế hoạch liên quan làm ngữ cảnh gọn nhẹ (tiết kiệm token) cho `ai-service` /extract."""
        if carrier_id is None:
            return []
        mentioned_conts = [
            f"{m.group(1).upper()}{m.group(2)}"
            for m in re.finditer(r"\b([A-Za-z]{4})[\s\-]?(\d{7})\b", raw_text or "")
        ]
        stmt = select(TransportPlan).where(TransportPlan.carrier_id == carrier_id).order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc())
        if mentioned_conts:
            stmt = stmt.where(TransportPlan.container_no.in_(mentioned_conts))
        plans = list(db.scalars(stmt.limit(5)).all())
        return [
            {
                "plan_id": p.id,
                "plan_date": p.plan_date.isoformat() if p.plan_date else None,
                "container_no": p.container_no,
                "order_type": p.order_type,
                "customer_name": p.customer_name,
                "delivery_address": p.delivery_address or p.address,
                "fleet_partner": p.fleet_partner or p.carrier_name,
            }
            for p in plans
        ]

    @classmethod
    def verify_plan_and_carrier(
        cls,
        db: Session,
        line: ExtractedContainerLine,
        carrier_ctx: CarrierContext,
        matched_cust_id: int | None,
    ) -> CarrierPlanCheck:
        """Kiểm tra khớp kế hoạch vận chuyển (`transport_plans`, kể cả slot trống cont J2 và kế hoạch chưa gán nhà xe)."""
        if not line.container_no:
            return CarrierPlanCheck(is_shipping_missing=True, reason="Thiếu số container.")

        norm_cont = line.container_no.strip().upper()

        if carrier_ctx.numeric_carrier_id is None:
            stmt_any = select(TransportPlan).where(TransportPlan.container_no == norm_cont)
            if line.transport_plan_id:
                stmt_any = stmt_any.where(TransportPlan.id == line.transport_plan_id)
            if matched_cust_id:
                stmt_any = stmt_any.where(TransportPlan.customer_id == matched_cust_id)
            plans_any = list(db.scalars(stmt_any).all())
            if len(plans_any) == 1:
                return CarrierPlanCheck(matched_plan=plans_any[0])
            if len(plans_any) > 1:
                return CarrierPlanCheck(
                    is_shipping_missing=True,
                    reason="Tìm thấy nhiều dòng kế hoạch trùng số container; cần ĐHVT chọn 1 dòng trên Web.",
                )
            return CarrierPlanCheck(
                is_shipping_missing=True,
                reason="Không tìm thấy kế hoạch vận chuyển cho số container này.",
            )

        stmt = select(TransportPlan).where(
            TransportPlan.container_no == norm_cont,
            or_(
                TransportPlan.carrier_id == carrier_ctx.numeric_carrier_id,
                TransportPlan.carrier_id.is_(None),
            ),
        )
        if line.transport_plan_id:
            stmt = stmt.where(TransportPlan.id == line.transport_plan_id)
        if matched_cust_id:
            stmt = stmt.where(TransportPlan.customer_id == matched_cust_id)
        plans = list(db.scalars(stmt).all())
        if len(plans) == 1:
            return CarrierPlanCheck(matched_plan=plans[0])
        if len(plans) > 1:
            return CarrierPlanCheck(
                is_shipping_missing=True,
                reason="Tìm thấy nhiều dòng kế hoạch trùng số container của nhà xe; cần ĐHVT chọn 1 dòng trên Web.",
            )

        other = db.scalar(
            select(TransportPlan.id)
            .where(
                TransportPlan.container_no == norm_cont,
                TransportPlan.carrier_id.is_not(None),
                TransportPlan.carrier_id != carrier_ctx.numeric_carrier_id,
            )
            .limit(1)
        )
        if other:
            return CarrierPlanCheck(is_carrier_mismatch=True, reason="Kế hoạch không thuộc nhà xe gửi tin.")

        # Bước J2: Tìm kế hoạch chưa cấp số container thuộc đúng nhà xe (ưu tiên lọc theo khách và loại lệnh)
        empty_stmt = select(TransportPlan).where(
            TransportPlan.carrier_id == carrier_ctx.numeric_carrier_id,
            or_(TransportPlan.container_no.is_(None), TransportPlan.container_no == ""),
        )
        if matched_cust_id:
            empty_stmt = empty_stmt.where(TransportPlan.customer_id == matched_cust_id)
        empty_slots = list(db.scalars(empty_stmt.order_by(TransportPlan.id.desc())).all())
        if len(empty_slots) > 1 and line.order_type:
            norm_o = normalize_vi_text(line.order_type)
            want_dong = norm_o in ("dong", "load", "export", "xuat")
            order_filtered = [
                p
                for p in empty_slots
                if (normalize_vi_text(p.order_type) in ("dong", "load", "export", "xuat")) == want_dong
            ]
            if order_filtered:
                empty_slots = order_filtered

        if len(empty_slots) == 1:
            return CarrierPlanCheck(matched_plan=empty_slots[0])
        if len(empty_slots) > 1:
            return CarrierPlanCheck(
                is_shipping_missing=True,
                reason="Tìm thấy nhiều dòng kế hoạch chưa có container của nhà xe; cần ĐHVT chọn 1 dòng trên Web.",
            )

        return CarrierPlanCheck(
            is_shipping_missing=True,
            reason="Không có duy nhất kế hoạch thuộc nhà xe; cần ĐHVT đối chiếu trên Web.",
        )

    @classmethod
    def match_warehouse_via_ai_if_needed(
        cls,
        db: Session,
        line: ExtractedContainerLine,
        carrier_ctx: CarrierContext,
        customer_id: int | None,
    ) -> int | None:
        """Gọi `ai-service` map địa chỉ kho đa tầng khi chưa khớp được kho từ kế hoạch hoặc từ điển."""
        if not line.warehouse_hint:
            return None
        warehouses = list(db.scalars(select(Warehouse).where(Warehouse.is_active == True).limit(100)).all())
        if not warehouses:
            return None

        aliases = list(db.scalars(select(WarehouseAlias)).all())
        alias_by_wh: dict[int, list[str]] = {}
        for al in aliases:
            alias_by_wh.setdefault(al.warehouse_id, []).append(al.alias)

        candidates = [
            {
                "id": w.id,
                "customer_id": w.customer_id,
                "name": w.name,
                "normalized_name": w.normalized_name,
                "address": w.address,
                "aliases": alias_by_wh.get(w.id, []),
            }
            for w in warehouses
        ]
        res = AIServiceClient.match_warehouse(
            raw_address=line.warehouse_hint,
            carrier_id=carrier_ctx.numeric_carrier_id,
            customer_id=customer_id,
            candidate_warehouses=candidates,
        )
        if res and res.matched and res.warehouse_id:
            wh_obj = db.get(Warehouse, res.warehouse_id)
            if wh_obj:
                line.warehouse_code_or_id = wh_obj.tms_warehouse_id or wh_obj.id
                line.match_source = f"ai_{res.source}"
                return wh_obj.id
        return None

    @classmethod
    def find_target_zalo_group_safe(
        cls,
        db: Session,
        customer_id: int | None,
        warehouse_id: int | None,
        order_type: str | None,
        source_group_id_str: str | None = None,
        plan_group_id_str: str | None = None,
        customer_hint: str | None = None,
    ) -> tuple[int | None, str | None]:
        """Xác định nhóm Zalo khách hàng an toàn; tuyệt đối không đoán mò nhóm khi thiếu định tuyến ở môi trường thật."""
        from src.infrastructure.models import RouteMap

        src_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == source_group_id_str)) if source_group_id_str else None
        is_test_mode = bool(src_grp and src_grp.is_test) or bool(
            source_group_id_str and source_group_id_str.startswith(("test_", "grp_test_", "pytest_"))
        )

        # 1. Nhóm đích chỉ định từ TransportPlan
        if plan_group_id_str:
            clean_gid = str(plan_group_id_str).strip()
            zg = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == clean_gid))
            if (zg and zg.is_active and is_test_mode == bool(zg.is_test)
                    and zg.group_role.upper() in ("CUSTOMER", "DESTINATION")):
                return zg.id, zg.zalo_group_id
            return None, None

        # 2. Bảng định tuyến RouteMap
        if customer_id:
            stmt = (
                select(RouteMap.zalo_group_id, ZaloGroup.zalo_group_id)
                .join(ZaloGroup, RouteMap.zalo_group_id == ZaloGroup.id)
                .where(RouteMap.customer_id == customer_id, RouteMap.is_active == True,
                       ZaloGroup.is_active == True, ZaloGroup.is_test == is_test_mode,
                       ZaloGroup.group_role.in_(["CUSTOMER", "DESTINATION"]))
                .order_by(RouteMap.priority.desc())
            )
            if warehouse_id:
                stmt = stmt.where(or_(RouteMap.warehouse_id == warehouse_id, RouteMap.warehouse_id.is_(None)))
            if order_type:
                stmt = stmt.where(or_(RouteMap.order_type == order_type, RouteMap.order_type.is_(None)))
            row = db.execute(stmt).first()
            if row:
                return row[0], row[1]

        return None, None

    @classmethod
    def find_pending_supplement_target(
        cls,
        db: Session,
        message: ZaloMessage,
        lines: list[ExtractedContainerLine],
    ) -> tuple[ContainerJob | None, BotReply | None]:
        """Tìm ca `ContainerJob` đang chờ bổ sung dựa trên `quote_msg_id` hoặc `BotReply` còn hạn 30 phút."""
        now = datetime.now(UTC)
        matched_reply: BotReply | None = None
        parent_msg: ZaloMessage | None = None

        if message.quote_msg_id:
            matched_reply = db.scalar(
                select(BotReply).where(BotReply.zalo_msg_id == message.quote_msg_id)
            )
            if matched_reply:
                parent_msg = db.get(ZaloMessage, matched_reply.message_id)
            else:
                parent_msg = db.scalar(
                    select(ZaloMessage).where(ZaloMessage.zalo_message_id == message.quote_msg_id)
                )

        # Nếu không quote trực tiếp `zalo_msg_id`, kiểm tra `BotReply` đang chờ cùng sender + group trong hạn 30p
        if not parent_msg:
            recent_reply = db.scalar(
                select(BotReply)
                .join(ZaloMessage, BotReply.message_id == ZaloMessage.id)
                .where(
                    ZaloMessage.group_id == message.group_id,
                    BotReply.sender_id == message.sender_id,
                    BotReply.status.in_([CorrectionStatus.PENDING.value, OutboundStatus.SENT.value]),
                    BotReply.fix_deadline >= now,
                )
                .order_by(BotReply.id.desc())
            )
            # Chỉ tự ghép khi tin mới mang tính chất bổ sung ngắn (thiếu biển số hoặc thiếu cont mới)
            if recent_reply and lines:
                first = lines[0]
                is_partial_supplement = (
                    not (first.truck_plate and first.container_no and first.driver_name and first.seal_no)
                    
                )
                if is_partial_supplement:
                    matched_reply = recent_reply
                    parent_msg = db.get(ZaloMessage, recent_reply.message_id)

        if not parent_msg or parent_msg.group_id != message.group_id:
            return None, None

        incomplete_jobs = list(
            db.scalars(
                select(ContainerJob)
                .where(
                    ContainerJob.message_id == parent_msg.id,
                    ContainerJob.validation_status.in_([
                        ValidationStatus.NEEDS_REVIEW.value,
                        ValidationStatus.INVALID.value,
                        ValidationStatus.PENDING.value,
                    ]),
                )
                .order_by(ContainerJob.line_no.asc(), ContainerJob.id.asc())
            ).all()
        )
        if not incomplete_jobs:
            return None, matched_reply

        # Chỉ hợp nhất khi xác định duy nhất một chuyến trong cùng nhóm.
        if parent_msg.group_id != message.group_id or len(lines) != 1:
            return None, matched_reply
        mentioned_conts = {ln.container_no for ln in lines if ln.container_no}
        if mentioned_conts:
            incomplete_jobs = [job for job in incomplete_jobs if job.container_no in mentioned_conts]
        if lines[0].truck_plate:
            incomplete_jobs = [job for job in incomplete_jobs if job.truck_record and
                               compact_plate(job.truck_record.truck_plate or "") == compact_plate(lines[0].truck_plate)]
        if len(incomplete_jobs) == 1:
            return incomplete_jobs[0], matched_reply
        return None, matched_reply

    @classmethod
    def merge_line_into_job(
        cls,
        db: Session,
        target_job: ContainerJob,
        incoming_line: ExtractedContainerLine,
        persist: bool = True,
    ) -> ExtractedContainerLine:
        """Gộp thông tin mới nhận vào `ContainerJob` + `TruckRecord` đang thiếu và thẩm định lại."""
        truck = target_job.truck_record

        merged_plate = incoming_line.truck_plate or (truck.truck_plate if truck else None)
        merged_trailer = incoming_line.trailer_plate or (truck.trailer_plate if truck else None)
        merged_driver = incoming_line.driver_name or (truck.driver_name if truck else None)
        merged_phone = incoming_line.driver_phone or (truck.driver_phone if truck else None)
        merged_cont = incoming_line.container_no or target_job.container_no
        merged_size = incoming_line.canonical_cont_size or incoming_line.container_size or target_job.container_size
        merged_seal = incoming_line.seal_no or target_job.seal_no
        merged_order = incoming_line.order_type or target_job.order_type
        merged_cust_hint = incoming_line.customer_hint or target_job.customer_hint
        merged_wh_hint = incoming_line.warehouse_hint or target_job.warehouse_hint
        raw_f = dict(target_job.raw_fields or {})

        merged_line = ExtractedContainerLine(
            line_no=target_job.line_no or 1,
            line_text=f"{target_job.line_text or ''}\n[BO SUNG] {incoming_line.line_text or ''}".strip(),
            source_format=raw_f.get("source_format") or incoming_line.source_format,
            plan_date=incoming_line.plan_date or raw_f.get("plan_date"),
            truck_plate=clean_plate(merged_plate) if merged_plate else None,
            raw_truck_plate=merged_plate,
            trailer_plate=clean_plate(merged_trailer) if merged_trailer else None,
            driver_name=merged_driver,
            driver_phone=clean_phone(merged_phone) if merged_phone else None,
            container_no=clean_container(merged_cont) if merged_cont else None,
            container_size=merged_size,
            seal_no=merged_seal,
            order_type=merged_order,
            warehouse_hint=merged_wh_hint,
            customer_hint=merged_cust_hint,
            customer_code_or_id=target_job.customer_id or merged_cust_hint,
            warehouse_code_or_id=target_job.warehouse_id or merged_wh_hint,
            eta_time=incoming_line.eta_time or raw_f.get("eta"),
            estimated_at=incoming_line.estimated_at or target_job.estimated_at,
            note=incoming_line.note or target_job.note,
            confidence=max(float(target_job.ai_confidence or 0.0), float(incoming_line.confidence)),
        )

        validated = ContainerValidator.validate_all([merged_line])[0]
        if not persist:
            return validated

        if truck:
            truck.truck_plate = validated.truck_plate
            truck.trailer_plate = validated.trailer_plate
            truck.driver_name = validated.driver_name
            truck.driver_phone = validated.driver_phone

        target_job.is_update = True
        target_job.container_no = validated.container_no
        target_job.container_size = validated.canonical_cont_size or validated.container_size
        target_job.seal_no = validated.seal_no
        target_job.order_type = validated.order_type
        target_job.warehouse_hint = validated.warehouse_hint
        target_job.customer_hint = validated.customer_hint
        target_job.estimated_at = validated.estimated_at
        target_job.note = validated.note
        target_job.container_check_digit_valid = validated.check_digit_valid
        raw_f.pop("local_plan_updated", None)
        raw_f["eta"] = validated.eta_time
        raw_f["warnings"] = validated.warnings
        raw_f["canonical_record"] = validated.to_canonical_record()
        target_job.raw_fields = raw_f
        return validated

    @classmethod
    def handle_cancel_request(
        cls,
        db: Session,
        message: ZaloMessage,
        lines: list[ExtractedContainerLine],
        carrier_ctx: CarrierContext,
    ) -> ZaloMessage:
        """Xử lý yêu cầu hủy chuyến/bỏ xe từ nhà xe và cảnh báo ĐHVT xử lý ngay."""
        conts = [ln.container_no for ln in lines if ln.container_no]
        matched_jobs: list[ContainerJob] = []
        if conts:
            matched_jobs = list(
                db.scalars(
                    select(ContainerJob)
                    .join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
                    .where(ContainerJob.container_no.in_(conts), ZaloMessage.group_id == message.group_id)
                    .order_by(ContainerJob.id.desc())
                ).all()
            )
        elif message.quote_msg_id:
            quoted_msg = db.scalar(select(ZaloMessage).where(ZaloMessage.zalo_message_id == message.quote_msg_id))
            if quoted_msg and quoted_msg.group_id == message.group_id:
                matched_jobs = list(quoted_msg.container_jobs)

        carrier_name = None
        if carrier_ctx.source_group and carrier_ctx.source_group.carrier_id:
            car = db.get(Carrier, carrier_ctx.source_group.carrier_id)
            carrier_name = car.name if car else None

        if matched_jobs:
            for idx, job in enumerate(matched_jobs):
                DhvtNotificationService.create_or_merge_review_case(
                    db=db,
                    message_id=message.id,
                    case_type="CANCEL_REQUEST",
                    reason=f"Nhà xe yêu cầu hủy chuyến container {job.container_no or 'N/A'}: {message.message_text}",
                    container_job_id=job.id,
                    container_no=job.container_no,
                    carrier_name=carrier_name,
                    details={"container_no": job.container_no, "raw_text": message.message_text},
                    suggestion="ĐHVT xác nhận hủy với khách hàng và duyệt trên Web để gửi thông báo hủy.",
                    priority="HIGH",
                    is_test_msg=carrier_ctx.is_test_msg,
                    notify_zalo=(idx == 0),
                )
        else:
            DhvtNotificationService.create_or_merge_review_case(
                db=db,
                message_id=message.id,
                case_type="CANCEL_REQUEST",
                reason=f"Nhà xe yêu cầu hủy chuyến (chưa xác định container): {message.message_text}",
                carrier_name=carrier_name,
                details={"raw_text": message.message_text},
                suggestion="ĐHVT kiểm tra tin gốc, xác định container và duyệt hủy trên Web.",
                priority="HIGH",
                is_test_msg=carrier_ctx.is_test_msg,
                notify_zalo=True,
            )

        cls.alert_dhvt(
            db=db,
            title="YEU CAU HUY CHUYEN TU NHA XE",
            body=(
                f"Nhóm: {carrier_ctx.source_group.name if carrier_ctx.source_group else message.group_id}\n"
                f"Nội dung: {message.message_text}\n"
                f"Container liên quan: {', '.join(conts) if conts else 'Chưa rõ'}"
            ),
            entity_type="zalo_message",
            entity_id=str(message.id),
            is_test_msg=carrier_ctx.is_test_msg,
        )
        message.processing_status = MessageStatus.NEEDS_REVIEW.value
        db.commit()
        db.refresh(message)
        return message

    @classmethod
    def handle_update_request(
        cls,
        db: Session,
        message: ZaloMessage,
        lines: list[ExtractedContainerLine],
        carrier_ctx: CarrierContext,
        enrich_fn: Any,
    ) -> ZaloMessage | None:
        """Thực thi luồng Nhà xe sửa / đổi xe / đổi tài xế theo đặc tả `docs/zalo.md` Mục 2b.

        Trả về `None` nếu không tìm thấy bản ghi gốc cần cập nhật để hệ thống xử lý như tin mới.
        """
        incoming = lines[0] if lines else ExtractedContainerLine(line_text=message.message_text or "")

        # 1. Xác định container mục tiêu cần sửa từ số cont hoặc từ tin được trích dẫn (quote)
        target_job: ContainerJob | None = None
        if incoming.container_no:
            target_job = db.scalar(
                select(ContainerJob)
                .join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
                .where(ContainerJob.container_no == incoming.container_no.strip().upper(), ZaloMessage.group_id == message.group_id)
                .order_by(ContainerJob.id.desc())
            )
        elif message.quote_msg_id:
            quoted_msg = db.scalar(
                select(ZaloMessage).where(ZaloMessage.zalo_message_id == message.quote_msg_id)
            )
            if quoted_msg and quoted_msg.group_id == message.group_id and len(quoted_msg.container_jobs) == 1:
                target_job = quoted_msg.container_jobs[0]

        # Nếu tin nói "đổi xe / sửa lại" nhưng KHÔNG có số container và KHÔNG quote tin có cont -> hỏi lại nhà xe
        if not incoming.container_no and target_job is None:
            clarify_text = OutboundTemplateBuilder.build_clarify_container_reply()
            reply = BotReply(
                id=snowflake.generate(),
                message_id=message.id,
                sender_id=message.sender_id,
                reply_text=clarify_text,
                fix_deadline=datetime.now(UTC) + timedelta(minutes=30),
                status=CorrectionStatus.PENDING.value,
            )
            db.add(reply)
            db.flush()

            if cls._is_dispatchable_real_group(message.group_id, carrier_ctx.source_group, carrier_ctx.is_test_msg):
                ok, z_mid, _ = ZaloDispatcher.send_to_group(
                    group_id=message.group_id,
                    message=clarify_text,
                    quote_msg_id=message.zalo_message_id,
                )
                if ok:
                    reply.zalo_msg_id = z_mid
                    reply.sent_at = datetime.now(UTC)

            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    case_type="MISSING_CONTAINER_FOR_UPDATE",
                    reason=f"Nhà xe yêu cầu đổi xe/cập nhật nhưng thiếu số container: {message.message_text}",
                    details={"raw_text": message.message_text},
                    status=ReviewStatus.PENDING.value,
                )
            )
            cls.alert_dhvt(
                db=db,
                title="YEU CAU DOI XE THIEU SO CONT",
                body=f"Nội dung: {message.message_text}\nBot đã tự động hỏi lại nhà xe số container cần sửa.",
                entity_type="zalo_message",
                entity_id=str(message.id),
                is_test_msg=carrier_ctx.is_test_msg,
            )
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        if target_job is None:
            return None

        # 2. Chống sửa sau khi chuyến đã hủy hoặc hoàn thành -> giữ lại cho Admin/ĐHVT duyệt
        target_raw = dict(target_job.raw_fields or {})
        if target_job.routing_status in (RoutingStatus.CANCELLED.value, RoutingStatus.SENT.value) or target_raw.get("trip_completed"):
            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    container_job_id=target_job.id,
                    case_type="UPDATE_REQUIRES_APPROVAL",
                    reason=f"Nhà xe yêu cầu cập nhật cho cont {target_job.container_no} sau khi đã báo khách hoặc chuyến hoàn thành/hủy.",
                    details={"raw_text": message.message_text},
                    status=ReviewStatus.PENDING.value,
                )
            )
            cls.alert_dhvt(
                db=db,
                title="CAP NHAT SAU HOAN THANH CHUYEN",
                body=f"Cont {target_job.container_no}: {message.message_text}",
                entity_type="container_job",
                entity_id=str(target_job.id),
                is_test_msg=carrier_ctx.is_test_msg,
            )
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        # 3. Hợp nhất dữ liệu thay đổi trên nền dữ liệu cũ & tính danh sách khác biệt
        prev_truck = target_job.truck_record
        old_plate = prev_truck.truck_plate if prev_truck else None
        old_driver = prev_truck.driver_name if prev_truck else None
        old_phone = prev_truck.driver_phone if prev_truck else None
        old_seal = target_job.seal_no
        old_eta = target_raw.get("eta")

        merged_line = cls.merge_line_into_job(db, target_job, incoming, persist=False)
        merged_line.carrier_id = carrier_ctx.numeric_carrier_id
        wh_id, cust_id, _, _, _ = enrich_fn(db, merged_line)
        if not wh_id and merged_line.warehouse_hint:
            wh_id = cls.match_warehouse_via_ai_if_needed(db, merged_line, carrier_ctx, cust_id)
        if wh_id:
            target_job.warehouse_id = wh_id
        if cust_id:
            target_job.customer_id = cust_id

        changes_list: list[str] = []
        if (compact_plate(old_plate) or "") != (compact_plate(merged_line.truck_plate) or ""):
            changes_list.append(f"- Biển số xe: {old_plate or 'Chưa có'} -> {merged_line.truck_plate}")
        if " ".join((old_driver or "").lower().split()) != " ".join((merged_line.driver_name or "").lower().split()):
            changes_list.append(f"- Lái xe: {old_driver or 'Chưa có'} -> {merged_line.driver_name}")
        if re.sub(r"\D", "", old_phone or "") != re.sub(r"\D", "", merged_line.driver_phone or ""):
            changes_list.append(f"- SĐT: {old_phone or 'Chưa có'} -> {merged_line.driver_phone}")
        if re.sub(r"[^A-Za-z0-9]", "", old_seal or "").upper() != re.sub(r"[^A-Za-z0-9]", "", merged_line.seal_no or "").upper():
            changes_list.append(f"- Số chì: {old_seal or 'Chưa có'} -> {merged_line.seal_no}")
        if (old_eta or "") != (merged_line.eta_time or "") and merged_line.eta_time:
            changes_list.append(f"- Giờ đến dự kiến: {old_eta or 'Chưa có'} -> {merged_line.eta_time}")

        # Tạo bản ghi ContainerJob mới gắn parent_job_id để lưu lịch sử phiên bản
        new_version = int(target_raw.get("version") or 1) + 1
        new_truck = TruckRecord(
            id=snowflake.generate(),
            message_id=message.id,
            truck_plate=merged_line.truck_plate,
            trailer_plate=merged_line.trailer_plate,
            driver_name=merged_line.driver_name,
            driver_phone=merged_line.driver_phone,
            raw_data={"plate_compact": merged_line.plate_compact, "eta": merged_line.eta_time, "version": new_version},
        )
        db.add(new_truck)
        db.flush()

        updated_job = ContainerJob(
            id=snowflake.generate(),
            message_id=message.id,
            truck_record_id=new_truck.id,
            parent_job_id=target_job.id,
            is_update=True,
            line_no=1,
            line_text=message.message_text,
            container_no=merged_line.container_no,
            container_size=merged_line.canonical_cont_size or merged_line.container_size,
            seal_no=merged_line.seal_no,
            order_type=merged_line.order_type or OrderType.LOAD.value,
            warehouse_hint=merged_line.warehouse_hint,
            customer_hint=merged_line.customer_hint,
            customer_id=cust_id or target_job.customer_id,
            warehouse_id=wh_id or target_job.warehouse_id,
            match_method=merged_line.match_source,
            container_check_digit_valid=merged_line.check_digit_valid,
            validation_status=merged_line.validation_status,
            routing_status=RoutingStatus.PENDING.value,
            tms_sync_status=TmsSyncStatus.NOT_STARTED.value,
            raw_fields={
                "transport_plan_id": merged_line.transport_plan_id,
                "version": new_version,
                "changes": changes_list,
                "eta": merged_line.eta_time,
                "warnings": merged_line.warnings,
                "canonical_record": merged_line.to_canonical_record(),
            },
        )
        db.add(updated_job)
        db.flush()

        is_complete, missing = OutboundTemplateBuilder.check_core_fields_completeness(merged_line)
        if not is_complete:
            warn_reply = OutboundTemplateBuilder.build_carrier_warning_reply([merged_line])
            bot_reply = BotReply(
                id=snowflake.generate(),
                message_id=message.id,
                sender_id=message.sender_id,
                reply_text=warn_reply,
                fix_deadline=datetime.now(UTC) + timedelta(minutes=30),
                status=CorrectionStatus.PENDING.value,
            )
            db.add(bot_reply)
            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    container_job_id=updated_job.id,
                    case_type="UPDATE_INCOMPLETE",
                    reason=f"Bản cập nhật còn thiếu/sai: {', '.join(missing)}",
                    details=merged_line.to_dict(),
                    status=ReviewStatus.PENDING.value,
                )
            )
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        # 4. Nếu không có gì thay đổi so với lần gửi trước -> bỏ qua chống spam
        if not changes_list:
            target_gid, _ = cls.find_target_zalo_group_safe(
                db=db,
                customer_id=updated_job.customer_id,
                warehouse_id=updated_job.warehouse_id,
                order_type=updated_job.order_type,
                source_group_id_str=message.group_id,
                plan_group_id_str=merged_line.target_group_id,
                customer_hint=merged_line.customer_hint,
            )
            if target_gid:
                db.add(
                    OutboundMessage(
                        id=snowflake.generate(),
                        target_group_id=target_gid,
                        order_type=updated_job.order_type or OrderType.LOAD.value,
                        message_kind="duplicate",
                        content="Thông tin cập nhật không thay đổi so với thông báo đã gửi.",
                        idempotency_key=f"outbound_upd_dup_{message.id}_{uuid4().hex[:8]}",
                        status=OutboundStatus.IGNORED_DUPLICATE.value,
                    )
                )
            message.processing_status = MessageStatus.PROCESSED.value
            db.commit()
            db.refresh(message)
            return message

        # 5. Soạn và gửi THÔNG BÁO CẬP NHẬT ra nhóm khách hàng
        cust_obj = db.get(Customer, updated_job.customer_id) if updated_job.customer_id else None
        wh_obj = db.get(Warehouse, updated_job.warehouse_id) if updated_job.warehouse_id else None
        cust_name = cust_obj.name if cust_obj else (merged_line.customer_hint or "Quý khách hàng")
        wh_name = wh_obj.name if wh_obj else (merged_line.warehouse_hint or "Kho khách hàng")

        update_text = OutboundTemplateBuilder.build_update_notification(
            line=merged_line,
            changes_list=changes_list,
            customer_name=cust_name,
            warehouse_name=wh_name,
            customer_id=cust_obj.tms_customer_id if cust_obj else None,
        )
        target_gid, target_zalo_gid = cls.find_target_zalo_group_safe(
            db=db,
            customer_id=updated_job.customer_id,
            warehouse_id=updated_job.warehouse_id,
            order_type=updated_job.order_type,
            source_group_id_str=message.group_id,
            plan_group_id_str=merged_line.target_group_id,
            customer_hint=merged_line.customer_hint,
        )
        if not target_gid:
            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    container_job_id=updated_job.id,
                    case_type="ROUTING_NOT_FOUND",
                    reason=f"Không tìm thấy nhóm Zalo khách hàng cho cập nhật cont {updated_job.container_no}.",
                    details={"changes": changes_list},
                    status=ReviewStatus.PENDING.value,
                )
            )
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        # 5b. Đồng bộ lên bảng kế hoạch vận chuyển cục bộ (điền trống hoặc cập nhật xe/tài xế)
        if not cls.sync_job_with_local_plan_or_review(
            db=db,
            job=updated_job,
            source_group=carrier_ctx.source_group,
            is_test_msg=carrier_ctx.is_test_msg,
        ):
            updated_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        target_grp = db.get(ZaloGroup, target_gid)
        is_manual = (target_grp and target_grp.send_mode == SendMode.MANUAL.value) or (
            carrier_ctx.source_group and carrier_ctx.source_group.send_mode == SendMode.MANUAL.value
        )

        out_status = OutboundStatus.PENDING_APPROVAL.value if is_manual else OutboundStatus.PENDING_SEND.value
        now = datetime.now(UTC)

        outbound = OutboundMessage(
            id=snowflake.generate(),
            target_group_id=target_gid,
            order_type=updated_job.order_type or OrderType.LOAD.value,
            message_kind="update",
            content=update_text,
            idempotency_key=f"outbound:update:{message.id}:{updated_job.id}",
            status=out_status,
            attempt_count=0,
        )
        db.add(outbound)
        db.flush()
        db.add(OutboundMessageItem(outbound_message_id=outbound.id, container_job_id=updated_job.id))
        cls.supersede_pending_outbounds_for_container(db, updated_job.container_no, keep_outbound_id=outbound.id)

        updated_job.validation_status = ValidationStatus.VALID.value
        updated_job.routing_status = RoutingStatus.ROUTED.value
        confirm_text = OutboundTemplateBuilder.build_update_confirm_reply(
            container_no=updated_job.container_no or "",
            changes_list=changes_list,
        )
        confirm_reply = BotReply(
            id=snowflake.generate(),
            message_id=message.id,
            sender_id=message.sender_id,
            reply_text=confirm_text,
            fix_deadline=now + timedelta(minutes=30),
            status=CorrectionStatus.RESOLVED.value,
        )
        db.add(confirm_reply)

        if not is_manual and cls._is_dispatchable_real_group(message.group_id, carrier_ctx.source_group, carrier_ctx.is_test_msg):
            ok, c_mid, _ = ZaloDispatcher.send_to_group(
                group_id=message.group_id,
                message=confirm_text,
                quote_msg_id=message.zalo_message_id,
            )
            if ok:
                confirm_reply.zalo_msg_id = c_mid
                confirm_reply.sent_at = now

        if is_manual:
            DhvtNotificationService.notify_pending_outbound(
                db=db,
                outbound=outbound,
                target_group_name=target_grp.name if target_grp else str(target_zalo_gid),
                containers=[updated_job.container_no] if updated_job.container_no else [],
                reason=f"Bản cập nhật xe/lái xe cont {updated_job.container_no or 'N/A'} cần duyệt gửi khách.",
                is_test_msg=carrier_ctx.is_test_msg,
            )
        else:
            cls.alert_dhvt(
                db=db,
                title="CAP NHAT THONG TIN XE",
                body=f"Cont {updated_job.container_no}: {'; '.join(c.lstrip('- ') for c in changes_list)}",
                entity_type="container_job",
                entity_id=str(updated_job.id),
                is_test_msg=carrier_ctx.is_test_msg,
            )

        message.processing_status = MessageStatus.NEEDS_REVIEW.value if is_manual else MessageStatus.PROCESSED.value
        db.commit()

        if (
            not is_manual
            and out_status == OutboundStatus.PENDING_SEND.value
            and not carrier_ctx.is_test_msg
            and target_grp
            and not target_grp.is_test
            and settings.AUTO_DISPATCH_OUTBOUND
        ):
            from src.infrastructure.outbox_worker import drain_outbox

            drain_outbox(lambda: nullcontext(db), [outbound.id])
            db.refresh(outbound)
            db.refresh(updated_job)
            db.refresh(message)
            if outbound.status == OutboundStatus.SENT.value:
                updated_job.routing_status = RoutingStatus.SENT.value
                message.processing_status = MessageStatus.PROCESSED.value
                db.commit()
            elif outbound.status in (OutboundStatus.FAILED.value, OutboundStatus.PENDING_APPROVAL.value):
                message.processing_status = MessageStatus.NEEDS_REVIEW.value
                db.commit()

        db.refresh(message)
        return message

    @classmethod
    def process_supplement_into_job(
        cls,
        db: Session,
        message: ZaloMessage,
        target_job: ContainerJob,
        matched_reply: BotReply | None,
        incoming_line: ExtractedContainerLine,
        carrier_ctx: CarrierContext,
        enrich_fn: Any,
    ) -> ZaloMessage:
        """Gộp thông tin bổ sung vào ca `ContainerJob` đang thiếu, thẩm định lại và gửi khách nếu đủ."""
        now = datetime.now(UTC)
        merged_line = cls.merge_line_into_job(db, target_job, incoming_line)
        merged_line.carrier_id = carrier_ctx.numeric_carrier_id

        wh_id, cust_id, _, _, _ = enrich_fn(db, merged_line)
        if not wh_id and merged_line.warehouse_hint:
            wh_id = cls.match_warehouse_via_ai_if_needed(db, merged_line, carrier_ctx, cust_id)
        if wh_id:
            target_job.warehouse_id = wh_id
        if cust_id:
            target_job.customer_id = cust_id

        plan_check = cls.verify_plan_and_carrier(db, merged_line, carrier_ctx, target_job.customer_id)
        if plan_check.is_carrier_mismatch or plan_check.is_shipping_missing:
            case_type = "CARRIER_MISMATCH" if plan_check.is_carrier_mismatch else "SHIPPING_NOT_FOUND"
            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    container_job_id=target_job.id,
                    case_type=case_type,
                    reason=plan_check.reason or "Không khớp kế hoạch hoặc nhà xe.",
                    details=merged_line.to_dict(),
                    status=ReviewStatus.PENDING.value,
                )
            )
            cls.alert_dhvt(
                db=db,
                title=case_type,
                body=plan_check.reason or "",
                entity_type="container_job",
                entity_id=str(target_job.id),
                is_test_msg=carrier_ctx.is_test_msg,
            )
            target_job.validation_status = ValidationStatus.NEEDS_REVIEW.value
            target_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        is_complete, _missing_fields = OutboundTemplateBuilder.check_core_fields_completeness(merged_line)
        if not is_complete:
            target_job.validation_status = ValidationStatus.NEEDS_REVIEW.value
            warn_text = OutboundTemplateBuilder.build_carrier_warning_reply([merged_line])
            new_reply = BotReply(
                id=snowflake.generate(),
                message_id=message.id,
                sender_id=message.sender_id,
                reply_text=warn_text,
                fix_deadline=now + timedelta(minutes=30),
                status=CorrectionStatus.PENDING.value,
            )
            db.add(new_reply)
            db.flush()
            if cls._is_dispatchable_real_group(message.group_id, carrier_ctx.source_group, carrier_ctx.is_test_msg):
                ok, z_mid, _ = ZaloDispatcher.send_to_group(
                    group_id=message.group_id,
                    message=warn_text,
                    quote_msg_id=message.zalo_message_id,
                )
                if ok:
                    new_reply.zalo_msg_id = z_mid
                    new_reply.sent_at = now
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        # Đủ và hợp lệ toàn bộ -> Đóng BotReply & ReviewCase cũ liên quan
        target_job.validation_status = ValidationStatus.VALID.value
        if matched_reply:
            matched_reply.status = CorrectionStatus.RESOLVED.value
        for br in db.scalars(
            select(BotReply).where(
                BotReply.message_id == target_job.message_id,
                BotReply.status.in_([CorrectionStatus.PENDING.value, OutboundStatus.SENT.value]),
            )
        ).all():
            br.status = CorrectionStatus.RESOLVED.value

        for rc in db.scalars(
            select(ReviewCase).where(
                ReviewCase.container_job_id == target_job.id,
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
            )
        ).all():
            rc.status = ReviewStatus.RESOLVED.value
            rc.resolved_by = "carrier_supplement"
            rc.resolved_at = now

        for draft in db.scalars(
            select(MessageDraft).where(
                MessageDraft.group_id == message.group_id,
                MessageDraft.sender_id == message.sender_id,
                MessageDraft.status.in_([MessageDraftStatus.OPEN.value, MessageDraftStatus.WAITING_REPLY.value]),
            )
        ).all():
            draft.status = MessageDraftStatus.FLUSHED.value
            draft.flushed_at = now

        cust_obj = db.get(Customer, target_job.customer_id) if target_job.customer_id else None
        wh_obj = db.get(Warehouse, target_job.warehouse_id) if target_job.warehouse_id else None
        notif_text = OutboundTemplateBuilder.build_customer_notification(
            line=merged_line,
            customer_name=cust_obj.name if cust_obj else (merged_line.customer_hint or "Quý khách hàng"),
            warehouse_name=wh_obj.name if wh_obj else (merged_line.warehouse_hint or "Kho khách hàng"),
            customer_id=cust_obj.tms_customer_id if cust_obj else None,
        )
        target_gid, target_zalo_gid = cls.find_target_zalo_group_safe(
            db=db,
            customer_id=target_job.customer_id,
            warehouse_id=target_job.warehouse_id,
            order_type=target_job.order_type,
            source_group_id_str=message.group_id,
            plan_group_id_str=merged_line.target_group_id,
            customer_hint=merged_line.customer_hint,
        )

        if not target_gid:
            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    container_job_id=target_job.id,
                    case_type="ROUTING_NOT_FOUND",
                    reason=f"Bổ sung đủ dữ liệu nhưng chưa tìm thấy nhóm Zalo khách hàng cho cont {target_job.container_no}.",
                    details=merged_line.to_dict(),
                    status=ReviewStatus.PENDING.value,
                )
            )
            target_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        if not cls.sync_job_with_local_plan_or_review(
            db=db,
            job=target_job,
            source_group=carrier_ctx.source_group,
            is_test_msg=carrier_ctx.is_test_msg,
        ):
            target_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        target_grp = db.get(ZaloGroup, target_gid)
        is_manual = (target_grp and target_grp.send_mode == SendMode.MANUAL.value) or (
            carrier_ctx.source_group and carrier_ctx.source_group.send_mode == SendMode.MANUAL.value
        )

        out_status = OutboundStatus.PENDING_APPROVAL.value if is_manual else OutboundStatus.PENDING_SEND.value
        outbound = OutboundMessage(
            id=snowflake.generate(),
            target_group_id=target_gid,
            order_type=target_job.order_type or OrderType.LOAD.value,
            message_kind="supplement",
            content=notif_text,
            idempotency_key=f"outbound:supplement:{message.id}:{target_job.id}",
            status=out_status,
            attempt_count=0,
        )
        db.add(outbound)
        db.flush()
        db.add(OutboundMessageItem(outbound_message_id=outbound.id, container_job_id=target_job.id))

        target_job.routing_status = RoutingStatus.ROUTED.value
        parent_msg = db.get(ZaloMessage, target_job.message_id)
        if parent_msg:
            parent_msg.processing_status = MessageStatus.PROCESSED.value
        if is_manual:
            DhvtNotificationService.notify_pending_outbound(
                db=db,
                outbound=outbound,
                target_group_name=target_grp.name if target_grp else str(target_zalo_gid),
                containers=[target_job.container_no] if target_job.container_no else [],
                reason=f"Bổ sung đủ dữ liệu cont {target_job.container_no or 'N/A'} cần ĐHVT duyệt gửi khách.",
                is_test_msg=carrier_ctx.is_test_msg,
            )
        cls.log_activity(
            db=db,
            actor_id=message.sender_id,
            action="SUPPLEMENT_RESOLVED",
            entity_type="container_job",
            entity_id=str(target_job.id),
            details={"container_no": target_job.container_no, "outbound_status": out_status},
        )
        message.processing_status = MessageStatus.NEEDS_REVIEW.value if is_manual else MessageStatus.PROCESSED.value
        db.commit()

        if (
            not is_manual
            and out_status == OutboundStatus.PENDING_SEND.value
            and not carrier_ctx.is_test_msg
            and target_grp
            and not target_grp.is_test
            and settings.AUTO_DISPATCH_OUTBOUND
        ):
            from src.infrastructure.outbox_worker import drain_outbox

            drain_outbox(lambda: nullcontext(db), [outbound.id])
            db.refresh(outbound)
            db.refresh(target_job)
            db.refresh(message)
            if outbound.status == OutboundStatus.SENT.value:
                target_job.routing_status = RoutingStatus.SENT.value
                message.processing_status = MessageStatus.PROCESSED.value
                db.commit()
            elif outbound.status in (OutboundStatus.FAILED.value, OutboundStatus.PENDING_APPROVAL.value):
                message.processing_status = MessageStatus.NEEDS_REVIEW.value
                db.commit()

        db.refresh(message)
        return message
