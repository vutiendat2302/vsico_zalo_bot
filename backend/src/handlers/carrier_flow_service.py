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
import os
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
from src.handlers.plan_sync_service import (
    extract_plan_expected_time,
    resolve_plan_detailed,
    sync_job_to_local_plan,
    sync_plan_to_tms,
)
from src.infrastructure.ai_service_client import AIServiceClient
from src.infrastructure.minio_client import minio_storage
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
    candidate_plans: list[TransportPlan] = field(default_factory=list)


class CarrierFlowService:
    """Tập hợp phương thức điều phối luồng Bot - Nhà xe bảo đảm clean code và không trùng lặp."""

    @staticmethod
    def is_manual_approval_required(
        source_group: ZaloGroup | None,
        target_group: ZaloGroup | None = None,
    ) -> bool:
        """Trả True nếu nhóm nhà xe (SOURCE) hoặc nhóm khách hàng (DESTINATION) đang ở chế độ Chờ duyệt (MANUAL)."""
        for grp in (source_group, target_group):
            if grp and grp.send_mode:
                try:
                    if SendMode(grp.send_mode).value == SendMode.MANUAL.value:
                        return True
                except ValueError:
                    if str(grp.send_mode).strip().upper() in ("MANUAL", "CHO_DUYET"):
                        return True
        return False

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
    def _decode_or_fetch_image_bytes(cls, raw_str: str) -> bytes | None:
        """Giải mã Base64/DataURI hoặc tải nhanh ảnh từ URL để đẩy lên MinIO (trả None nếu lỗi)."""
        import base64
        import urllib.request

        clean = raw_str.strip()
        if clean.startswith("data:") and ";base64," in clean:
            clean = clean.split(";base64,", 1)[1].strip()
        if not clean.startswith(("http://", "https://")) and len(clean) >= 16:
            try:
                return base64.b64decode(clean, validate=False)
            except Exception:
                return None

        if clean.startswith(("http://", "https://")):
            try:
                req = urllib.request.Request(
                    clean,
                    headers={
                        "User-Agent": "VSICO-Zalo-Bot/2.0",
                        "Referer": "https://chat.zalo.me/",
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if getattr(resp, "status", 200) == 200:
                        data = resp.read()
                        return data or None
            except Exception:
                return None
        return None

    @classmethod
    def record_image_file_metadata(
        cls,
        db: Session,
        message: ZaloMessage,
        payload_dict: dict[str, Any],
        image_input: str | None,
        ocr_meta: dict[str, Any] | None = None,
    ) -> None:
        """Lưu metadata và đồng bộ ảnh Zalo lên MinIO theo `<nhóm>/<người gửi>-<tên file>-<thời gian>`."""
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
        ext = "png" if mime == "image/png" else "jpg"

        grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == message.group_id))
        group_label = (grp.name if grp and grp.name else None) or payload_dict.get("group_name") or message.group_id
        sender_label = message.sender_name or (payload_dict.get("sender") or {}).get("name") or message.sender_id
        orig_name = f"zalo_{message.zalo_message_id}.{ext}"

        object_key = minio_storage.build_object_key(
            group_name=str(group_label),
            sender_name=str(sender_label),
            original_filename=orig_name,
            mime_type=mime,
            timestamp=message.received_at,
        )

        storage_status = StorageStatus.PENDING.value
        size_bytes = len(raw_bytes)
        bucket_name = settings.MINIO_BUCKET_NAME or "vsico-zalo-files"
        meta_payload: dict[str, Any] = {
            "group_id": message.group_id,
            "group_name": str(group_label),
            "sender_id": message.sender_id,
            "sender_name": str(sender_label),
            "ocr": ocr_meta or {},
        }

        img_bytes = cls._decode_or_fetch_image_bytes(raw_str)
        if img_bytes:
            if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif img_bytes[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            try:
                uploaded = minio_storage.upload_bytes(
                    object_key=object_key,
                    data=img_bytes,
                    content_type=mime,
                    bucket_name=bucket_name,
                )
                bucket_name = uploaded.bucket
                object_key = uploaded.object_key
                size_bytes = uploaded.size_bytes
                sha = uploaded.sha256
                storage_status = StorageStatus.STORED.value
                meta_payload["etag"] = uploaded.etag
            except Exception:
                # MinIO tạm thời ngoại tuyến trong môi trường kiểm thử: giữ PENDING không chặn luồng
                pass

        record = FileRecord(
            id=snowflake.generate(),
            file_key=f"zalo_img_{message.id}_{sha[:12]}",
            bucket=bucket_name,
            object_key=object_key,
            original_name=orig_name[:255],
            mime_type=mime,
            size_bytes=size_bytes,
            sha256=sha,
            source_type="ZALO_IMAGE",
            source_url=None if is_data_uri else raw_str[:1000],
            message_id=message.id,
            storage_status=storage_status,
            meta=meta_payload,
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
            suggestion="Mở mục Chờ duyệt (/reviews) để kiểm tra, duyệt gửi lại hoặc từ chối.",
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
        allow_tms_sync: bool = True,
    ) -> bool:
        """Đồng bộ ContainerJob lên TransportPlan cục bộ (điền trống/cập nhật) hoặc tạo ReviewCase nếu xung đột."""
        if not source_group or not source_group.is_active:
            return True
        pinned_plan: TransportPlan | None = None
        pinned_pid = (job.raw_fields or {}).get("transport_plan_id") if isinstance(job.raw_fields, dict) else None
        if pinned_pid and str(pinned_pid).isdigit():
            pinned_plan = db.get(TransportPlan, int(pinned_pid))
        if pinned_plan is not None:
            from types import SimpleNamespace
            plan_res = SimpleNamespace(plan=pinned_plan, status="PINNED", reason="", candidate_plan_ids=[pinned_plan.id])
        else:
            plan_res = resolve_plan_detailed(db, job, source_group, for_update=True)
        if plan_res.plan is not None:
            outcome = sync_job_to_local_plan(
                db=db,
                job=job,
                plan=plan_res.plan,
                allow_plan_override=False,
                actor_id="vsico_bot",
            )
            if outcome.mode in ("FILLED", "UPDATED") and allow_tms_sync:
                prev_cont = outcome.before_values.get("container_no") if "container_no" in outcome.before_values else plan_res.plan.container_no
                sync_plan_to_tms(
                    db=db,
                    plan=plan_res.plan,
                    job=job,
                    changed_fields=outcome.changed_fields,
                    before_values=outcome.before_values,
                    previous_container_no=prev_cont,
                    allow_container_override=False,
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
                "required_time": extract_plan_expected_time(p),
            }
            for p in plans
        ]

    @staticmethod
    def _filter_plans_by_order_type(
        plans: list[TransportPlan],
        order_type: str | None,
        strict: bool = False,
    ) -> list[TransportPlan]:
        """Lọc thu hẹp danh sách kế hoạch theo loại lệnh (`dong` / `tra`) khi có chỉ dẫn."""
        if (len(plans) <= 1 and not strict) or not order_type:
            return plans
        norm_o = normalize_vi_text(order_type)
        want_dong = norm_o in ("dong", "load", "export", "xuat")
        want_tra = norm_o in ("tra", "return", "import", "nhap")
        if not (want_dong or want_tra):
            return plans
        matched = [
            p
            for p in plans
            if (normalize_vi_text(p.order_type) in ("dong", "load", "export", "xuat")) == want_dong
        ]
        if strict:
            return matched
        return matched or plans

    @staticmethod
    def _filter_empty_slots_by_hints(
        slots: list[TransportPlan],
        line: ExtractedContainerLine,
        matched_cust_id: int | None,
    ) -> list[TransportPlan]:
        """Thu hẹp các lệnh chưa có số container theo khách hàng và từ khóa tên kho/khách."""
        if not slots:
            return []
        result = list(slots)
        if matched_cust_id:
            by_cust = [p for p in result if p.customer_id == matched_cust_id]
            if by_cust:
                result = by_cust

        hint_tokens: list[str] = []
        for raw_hint in (line.customer_hint, line.warehouse_hint):
            norm_h = normalize_vi_text(raw_hint or "")
            if norm_h:
                for tok in norm_h.split():
                    if len(tok) >= 3 and tok not in ("kho", "cong", "hang", "dong", "tra", "nhap", "xuat"):
                        hint_tokens.append(tok)

        if len(result) > 1 and hint_tokens:
            scored: list[tuple[int, TransportPlan]] = []
            for p in result:
                haystack = normalize_vi_text(
                    f"{p.customer_name or ''} {p.warehouse_name or ''} {p.delivery_address or ''}"
                )
                score = sum(1 for tok in set(hint_tokens) if tok in haystack)
                if score > 0:
                    scored.append((score, p))
            if scored:
                max_score = max(s for s, _ in scored)
                result = [p for s, p in scored if s == max_score]
        return result

    @classmethod
    def verify_plan_and_carrier(
        cls,
        db: Session,
        line: ExtractedContainerLine,
        carrier_ctx: CarrierContext,
        matched_cust_id: int | None,
    ) -> CarrierPlanCheck:
        """Kiểm tra khớp kế hoạch vận chuyển (`transport_plans`, kể cả slot trống cont J2 và lệnh chưa gán nhà xe)."""
        if not line.container_no:
            return CarrierPlanCheck(is_shipping_missing=True, reason="Thiếu số container.")
        if line.check_digit_valid is False or "INVALID_CONTAINER_FORMAT" in (line.warnings or []):
            return CarrierPlanCheck(
                is_shipping_missing=True,
                reason=f"Số container '{line.container_no}' không đúng định dạng hoặc sai chữ số kiểm tra ISO 6346.",
            )

        norm_cont = line.container_no.strip().upper()
        carrier_id = carrier_ctx.numeric_carrier_id

        stmt = select(TransportPlan).where(TransportPlan.container_no == norm_cont)
        if carrier_id is not None:
            stmt = stmt.where(
                or_(
                    TransportPlan.carrier_id == carrier_id,
                    TransportPlan.carrier_id.is_(None),
                )
            )
        if line.transport_plan_id:
            stmt = stmt.where(TransportPlan.id == line.transport_plan_id)
        elif matched_cust_id:
            stmt = stmt.where(TransportPlan.customer_id == matched_cust_id)

        plans = cls._filter_plans_by_order_type(
            list(db.scalars(stmt).all()),
            line.order_type,
            strict=bool(
                line.order_type
                and not line.inferred_order_type
                and (line.booking_no or (line.customer_hint and line.match_source != "transport_plan"))
            ),
        )
        if len(plans) == 1:
            return CarrierPlanCheck(matched_plan=plans[0])
        if len(plans) > 1:
            return CarrierPlanCheck(
                is_shipping_missing=True,
                reason="Tìm thấy nhiều dòng kế hoạch trùng số container; cần ĐHVT chọn 1 dòng trên Web.",
                candidate_plans=plans[:10],
            )

        if carrier_id is not None:
            other = db.scalar(
                select(TransportPlan.id)
                .where(
                    TransportPlan.container_no == norm_cont,
                    TransportPlan.carrier_id.is_not(None),
                    TransportPlan.carrier_id != carrier_id,
                )
                .limit(1)
            )
            if other:
                return CarrierPlanCheck(is_carrier_mismatch=True, reason="Kế hoạch không thuộc nhà xe gửi tin.")

        # Bước J2: Tìm kế hoạch chưa cấp số container (ưu tiên lệnh đóng LO khi khớp khách/kho/nhà xe)
        can_match_empty_slot = carrier_id is not None or bool(matched_cust_id or line.warehouse_hint or line.customer_hint)
        empty_candidates: list[TransportPlan] = []
        if can_match_empty_slot:
            empty_stmt = select(TransportPlan).where(
                or_(TransportPlan.container_no.is_(None), TransportPlan.container_no == "")
            )
            if carrier_id is not None:
                empty_stmt = empty_stmt.where(TransportPlan.carrier_id == carrier_id)
            if matched_cust_id:
                empty_stmt = empty_stmt.where(TransportPlan.customer_id == matched_cust_id)
            raw_slots = list(db.scalars(empty_stmt.order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc()).limit(100)).all())
            slots_by_type = cls._filter_plans_by_order_type(raw_slots, line.order_type or "dong")
            if line.booking_no:
                norm_bk = normalize_vi_text(line.booking_no)
                bk_slots = [
                    p
                    for p in slots_by_type
                    if p.booking_no and (
                        normalize_vi_text(p.booking_no) == norm_bk
                        or norm_bk in normalize_vi_text(p.booking_no)
                    )
                ]
                if bk_slots:
                    slots_by_type = bk_slots
            empty_slots = cls._filter_empty_slots_by_hints(slots_by_type, line, matched_cust_id)
            empty_candidates = empty_slots[:10]

            # Nếu chỉ có 1 lệnh rỗng khớp và đã có tín hiệu thu hẹp (nhà xe, khách hoặc kho khớp từ khóa), gán thẳng.
            has_narrowing_signal = carrier_id is not None or matched_cust_id is not None or bool(line.warehouse_hint or line.customer_hint)
            if len(empty_slots) == 1 and has_narrowing_signal:
                if carrier_id is not None or matched_cust_id is not None or (
                    empty_slots[0].warehouse_name
                    and any(
                        tok in normalize_vi_text(empty_slots[0].warehouse_name)
                        for tok in normalize_vi_text(line.warehouse_hint or "").split()
                        if len(tok) >= 4
                    )
                ):
                    return CarrierPlanCheck(matched_plan=empty_slots[0])

            if len(empty_slots) > 1:
                return CarrierPlanCheck(
                    is_shipping_missing=True,
                    reason="Tìm thấy nhiều dòng kế hoạch chưa có container phù hợp; cần ĐHVT chọn 1 dòng trên Web.",
                    candidate_plans=empty_candidates,
                )

        if not empty_candidates:
            # Gợi ý tối đa 10 lệnh đóng chưa có số cont mới nhất để ĐHVT chọn nhanh trên Web.
            fallback_stmt = (
                select(TransportPlan)
                .where(or_(TransportPlan.container_no.is_(None), TransportPlan.container_no == ""))
                .order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc())
                .limit(10)
            )
            empty_candidates = list(db.scalars(fallback_stmt).all())

        return CarrierPlanCheck(
            is_shipping_missing=True,
            reason=(
                "Không có duy nhất kế hoạch thuộc nhà xe; cần ĐHVT đối chiếu trên Web."
                if carrier_id is not None
                else "Không tìm thấy kế hoạch vận chuyển cho số container này."
            ),
            candidate_plans=empty_candidates,
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
    def resolve_job_from_quoted_message(
        cls,
        db: Session,
        group_id: str,
        quote_msg_id: str | None,
    ) -> ContainerJob | None:
        """Truy vết `ContainerJob` từ tin nhắn được quote (kể cả tin bổ sung cont, BotReply hoặc Outbound)."""
        if not quote_msg_id:
            return None

        # 1. Quote trực tiếp BotReply của Bot
        q_reply = db.scalar(select(BotReply).where(BotReply.zalo_msg_id == quote_msg_id))
        if q_reply:
            p_msg = db.get(ZaloMessage, q_reply.message_id)
            if p_msg and p_msg.group_id == group_id and len(p_msg.container_jobs) == 1:
                return p_msg.container_jobs[0]

        # 2. Quote trực tiếp OutboundMessage của Bot
        q_out = db.scalar(select(OutboundMessage).where(OutboundMessage.zalo_message_id == quote_msg_id))
        if q_out:
            out_jobs = [it.container_job for it in q_out.items if it.container_job is not None]
            if len(out_jobs) == 1:
                return out_jobs[0]

        # 3. Quote tin nhắn nhà xe trong nhóm
        quoted_msg = db.scalar(select(ZaloMessage).where(ZaloMessage.zalo_message_id == quote_msg_id))
        if not quoted_msg or quoted_msg.group_id != group_id:
            return None
        if len(quoted_msg.container_jobs) == 1:
            return quoted_msg.container_jobs[0]

        rc = db.scalar(
            select(ReviewCase)
            .where(ReviewCase.message_id == quoted_msg.id, ReviewCase.container_job_id.is_not(None))
            .order_by(ReviewCase.id.desc())
        )
        if rc and rc.container_job_id:
            rj = db.get(ContainerJob, rc.container_job_id)
            if rj:
                return rj

        # Tin được quote có thể là tin bổ sung chỉ ghi số cont (VD: "VSIU2463280") -> container_jobs nằm ở tin gốc
        q_text = quoted_msg.message_text or ""
        q_conts = {
            clean_container(f"{m.group(1)}{m.group(2)}")
            for m in re.finditer(r"\b([A-Za-z]{4})[\s.\-]?(\d{7})\b", q_text)
        }
        q_conts.discard(None)
        if len(q_conts) == 1:
            q_cont = next(iter(q_conts))
            found_by_cont = db.scalar(
                select(ContainerJob)
                .join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
                .where(
                    ZaloMessage.group_id == group_id,
                    ContainerJob.container_no == q_cont,
                    ContainerJob.validation_status != ValidationStatus.REJECTED.value,
                )
                .order_by(ContainerJob.id.desc())
            )
            if found_by_cont:
                return found_by_cont

        return None

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
                if parent_msg:
                    matched_reply = db.scalar(
                        select(BotReply)
                        .where(
                            BotReply.message_id == parent_msg.id,
                            BotReply.status.in_([CorrectionStatus.PENDING.value, OutboundStatus.SENT.value]),
                        )
                        .order_by(BotReply.id.desc())
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
                    not (first.truck_plate and first.trailer_plate and first.container_no and first.driver_name)
                    
                )
                if is_partial_supplement:
                    matched_reply = recent_reply
                    parent_msg = db.get(ZaloMessage, recent_reply.message_id)

        if not parent_msg or parent_msg.group_id != message.group_id:
            # Fallback bổ sung sau khi đơn đã hợp lệ (VD: nhà xe gửi thêm số chì 'VS998877' hoặc 'chì VS998877' trong 30p).
            # Tuyệt đối không cướp tin mới chứa mã cont (kể cả cont sai định dạng), biển đầu kéo, tên tài xế hoặc lỗi định dạng.
            if len(lines) == 1:
                from src.domain.patterns import deglue_transport_entities

                ln0 = lines[0]
                deglued_raw = deglue_transport_entities(message.message_text or "")
                has_raw_cont_or_plate = bool(
                    re.search(
                        r"(?<![A-Za-z0-9])[A-Za-z]{3}[UJZ](?:[ \t.\-]?\d){3,9}(?![A-Za-z0-9])",
                        deglued_raw,
                        re.IGNORECASE,
                    )
                    or re.search(
                        r"(?<![A-Za-z0-9])(?:1[124-9]|[2-9]\d)[ \t.\-/]{0,2}(?!RM?(?![A-Za-zĐđ]))[A-Za-zĐđ]{1,2}[ \t.\-/]{0,2}\d{4,5}(?!\d)",
                        deglued_raw,
                        re.IGNORECASE,
                    )
                )
                has_invalid_followup_format = (
                    ln0.check_digit_valid is False
                    or any(
                        w in (ln0.warnings or [])
                        for w in (
                            "INVALID_TRAILER_PLATE_FORMAT",
                            "INVALID_DRIVER_PHONE",
                            "INVALID_TRUCK_PLATE_FORMAT",
                            "INVALID_CONTAINER_FORMAT",
                        )
                    )
                )
                is_followup_field = bool(
                    (ln0.seal_no or ln0.trailer_plate or ln0.driver_phone)
                    and not ln0.truck_plate
                    and not ln0.container_no
                    and not ln0.driver_name
                    and not has_raw_cont_or_plate
                    and not has_invalid_followup_format
                )
                if is_followup_field:
                    # `ContainerJob.created_at` dùng `utc_now()` (naive GMT+7); lọc `parent_job_id IS NULL`
                    # để vẫn tìm được đơn gốc dù đã trải qua 1 lần gộp bổ sung (`is_update=True`).
                    local_cutoff = datetime.now() - timedelta(minutes=30)
                    recent_jobs = list(
                        db.scalars(
                            select(ContainerJob)
                            .join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
                            .where(
                                ZaloMessage.group_id == message.group_id,
                                ZaloMessage.sender_id == message.sender_id,
                                ContainerJob.created_at >= local_cutoff,
                                ContainerJob.parent_job_id.is_(None),
                                ContainerJob.validation_status != ValidationStatus.REJECTED.value,
                                ContainerJob.routing_status != RoutingStatus.CANCELLED.value,
                            )
                            .order_by(ContainerJob.id.desc())
                        ).all()
                    )
                    # Chỉ ghép bổ sung không quote khi thực sự điền vào ít nhất 1 trường đang TRỐNG trên đơn gần nhất
                    eligible_recent: list[ContainerJob] = []
                    for rj in recent_jobs:
                        rj_tr = rj.truck_record
                        fills_missing = bool(
                            (ln0.seal_no and not (rj.seal_no or "").strip())
                            or (ln0.trailer_plate and not (rj_tr and (rj_tr.trailer_plate or "").strip()))
                            or (ln0.driver_phone and not (rj_tr and (rj_tr.driver_phone or "").strip()))
                        )
                        if fills_missing:
                            eligible_recent.append(rj)
                    if ln0.seal_no and not ln0.trailer_plate and not ln0.driver_phone and len(eligible_recent) > 1:
                        no_seal_jobs = [j for j in eligible_recent if not j.seal_no]
                        if len(no_seal_jobs) == 1:
                            return no_seal_jobs[0], None
                    if len(eligible_recent) == 1:
                        return eligible_recent[0], None
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
        if not mentioned_conts and not message.quote_msg_id:
            from src.domain.patterns import deglue_transport_entities

            raw_cont_hints = {
                clean_container(m.group(0))
                for m in re.finditer(
                    r"(?<![A-Za-z0-9])[A-Za-z]{3}[UJZ](?:[ \t.\-]?\d){3,9}(?![A-Za-z0-9])",
                    deglue_transport_entities(message.message_text or ""),
                    re.IGNORECASE,
                )
            }
            raw_cont_hints.discard(None)
            mentioned_conts = raw_cont_hints
        if mentioned_conts:
            exact_cont_jobs = [job for job in incomplete_jobs if job.container_no in mentioned_conts]
            if exact_cont_jobs:
                incomplete_jobs = exact_cont_jobs
            else:
                incomplete_jobs = [job for job in incomplete_jobs if not job.container_no]
        if lines[0].truck_plate:
            plate_cmp = compact_plate(lines[0].truck_plate)
            exact_plate_jobs = [
                job for job in incomplete_jobs
                if job.truck_record and compact_plate(job.truck_record.truck_plate or "") == plate_cmp
            ]
            if exact_plate_jobs:
                incomplete_jobs = exact_plate_jobs
            else:
                incomplete_jobs = [
                    job for job in incomplete_jobs
                    if not (job.truck_record and job.truck_record.truck_plate)
                ]
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
            booking_no=incoming_line.booking_no or raw_f.get("booking_no"),
            order_type=merged_order,
            warehouse_hint=merged_wh_hint,
            customer_hint=merged_cust_hint,
            customer_code_or_id=target_job.customer_id or merged_cust_hint,
            warehouse_code_or_id=target_job.warehouse_id or merged_wh_hint,
            transport_plan_id=incoming_line.transport_plan_id or raw_f.get("transport_plan_id"),
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
            target_job = cls.resolve_job_from_quoted_message(db, message.group_id, message.quote_msg_id)

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

        # 2. Chống sửa sau khi chuyến đã hủy hoặc hoàn thành -> gộp toàn bộ thông tin cũ + phần thay đổi để ĐHVT duyệt
        target_raw = dict(target_job.raw_fields or {})
        if target_job.routing_status in (RoutingStatus.CANCELLED.value, RoutingStatus.SENT.value) or target_raw.get("trip_completed"):
            merged_preview = cls.merge_line_into_job(db, target_job, incoming, persist=False)
            prev_tr = target_job.truck_record
            preview_changes: list[str] = []
            if merged_preview.truck_plate and (compact_plate(prev_tr.truck_plate if prev_tr else None) or "") != (compact_plate(merged_preview.truck_plate) or ""):
                preview_changes.append(f"- Biển số xe: {(prev_tr.truck_plate if prev_tr else None) or 'Chưa có'} -> {merged_preview.truck_plate}")
            if merged_preview.trailer_plate and (compact_plate(prev_tr.trailer_plate if prev_tr else None) or "") != (compact_plate(merged_preview.trailer_plate) or ""):
                preview_changes.append(f"- Biển số rơ-moóc: {(prev_tr.trailer_plate if prev_tr else None) or 'Chưa có'} -> {merged_preview.trailer_plate}")
            if merged_preview.driver_name and " ".join(((prev_tr.driver_name if prev_tr else None) or "").lower().split()) != " ".join((merged_preview.driver_name or "").lower().split()):
                preview_changes.append(f"- Lái xe: {(prev_tr.driver_name if prev_tr else None) or 'Chưa có'} -> {merged_preview.driver_name}")
            if merged_preview.driver_phone and re.sub(r"\D", "", (prev_tr.driver_phone if prev_tr else None) or "") != re.sub(r"\D", "", merged_preview.driver_phone or ""):
                preview_changes.append(f"- SĐT: {(prev_tr.driver_phone if prev_tr else None) or 'Chưa có'} -> {merged_preview.driver_phone}")
            if merged_preview.seal_no and re.sub(r"[^A-Za-z0-9]", "", target_job.seal_no or "").upper() != re.sub(r"[^A-Za-z0-9]", "", merged_preview.seal_no or "").upper():
                preview_changes.append(f"- Số chì: {target_job.seal_no or 'Chưa có'} -> {merged_preview.seal_no}")

            existing_upd_rc = db.scalar(
                select(ReviewCase)
                .where(
                    ReviewCase.container_job_id == target_job.id,
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                )
                .order_by(ReviewCase.id.desc())
            )
            orig_job_msg = db.get(ZaloMessage, target_job.message_id) if target_job.message_id else None
            upd_details = {
                **merged_preview.to_dict(),
                "raw_text": message.message_text,
                "changes": preview_changes,
                "proposed_changes": {
                    k: v
                    for k, v in {
                        "planned_truck_plate": incoming.truck_plate,
                        "planned_trailer_plate": incoming.trailer_plate,
                        "driver_name": incoming.driver_name,
                        "driver_phone": incoming.driver_phone,
                        "seal_no": incoming.seal_no,
                        "container_no": incoming.container_no,
                    }.items()
                    if v
                },
                "merged_messages": [
                    t
                    for t in (
                        orig_job_msg.message_text.strip() if orig_job_msg and orig_job_msg.message_text else None,
                        (message.message_text or "").strip(),
                    )
                    if t
                ],
            }
            if existing_upd_rc is not None:
                merged_d = dict(existing_upd_rc.details or {})
                hist = list(merged_d.get("merged_messages") or [])
                for t in upd_details["merged_messages"]:
                    if t not in hist:
                        hist.append(t)
                merged_d.update(upd_details)
                merged_d["merged_messages"] = hist
                existing_upd_rc.details = merged_d
            else:
                DhvtNotificationService.create_or_merge_review_case(
                    db=db,
                    message_id=message.id,
                    case_type="UPDATE_REQUIRES_APPROVAL",
                    reason=f"Nhà xe yêu cầu cập nhật cho cont {target_job.container_no} sau khi đã báo khách hoặc chuyến hoàn thành/hủy.",
                    container_job_id=target_job.id,
                    container_no=target_job.container_no,
                    details=upd_details,
                    is_test_msg=carrier_ctx.is_test_msg,
                    notify_zalo=False,
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

        # Nếu chuyến gốc chưa gửi khách và đang có ca chờ duyệt mở cùng nhóm -> gộp thẳng vào ca cũ, không tạo form mới
        existing_pending_rc = db.scalar(
            select(ReviewCase)
            .where(
                ReviewCase.container_job_id == target_job.id,
                ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
            )
            .order_by(ReviewCase.id.desc())
        )
        if existing_pending_rc is not None:
            orig_job_msg = db.get(ZaloMessage, target_job.message_id) if target_job.message_id else None
            res_msg = cls.process_supplement_into_job(
                db=db,
                message=message,
                target_job=target_job,
                matched_reply=None,
                incoming_line=incoming,
                carrier_ctx=carrier_ctx,
                enrich_fn=enrich_fn,
            )
            for pending_rc in db.scalars(
                select(ReviewCase).where(
                    ReviewCase.container_job_id == target_job.id,
                    ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                )
            ).all():
                d_cur = dict(pending_rc.details or {})
                hist = list(d_cur.get("merged_messages") or [])
                for txt in (
                    orig_job_msg.message_text.strip() if orig_job_msg and orig_job_msg.message_text else None,
                    (message.message_text or "").strip(),
                ):
                    if txt and txt not in hist:
                        hist.append(txt)
                if hist:
                    d_cur["merged_messages"] = hist
                    pending_rc.details = d_cur
            db.commit()
            return res_msg

        # 3. Hợp nhất dữ liệu thay đổi trên nền dữ liệu cũ & tính danh sách khác biệt
        prev_truck = target_job.truck_record
        old_plate = prev_truck.truck_plate if prev_truck else None
        old_trailer = prev_truck.trailer_plate if prev_truck else None
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
        if (compact_plate(old_trailer) or "") != (compact_plate(merged_line.trailer_plate) or "") and merged_line.trailer_plate:
            changes_list.append(f"- Biển số rơ-moóc: {old_trailer or 'Chưa có'} -> {merged_line.trailer_plate}")
        if " ".join((old_driver or "").lower().split()) != " ".join((merged_line.driver_name or "").lower().split()):
            changes_list.append(f"- Lái xe: {old_driver or 'Chưa có'} -> {merged_line.driver_name}")
        if re.sub(r"\D", "", old_phone or "") != re.sub(r"\D", "", merged_line.driver_phone or ""):
            changes_list.append(f"- SĐT: {old_phone or 'Chưa có'} -> {merged_line.driver_phone}")
        if re.sub(r"[^A-Za-z0-9]", "", old_seal or "").upper() != re.sub(r"[^A-Za-z0-9]", "", merged_line.seal_no or "").upper():
            changes_list.append(f"- Số chì: {old_seal or 'Chưa có'} -> {merged_line.seal_no}")
        if incoming.eta_time and (old_eta or "") != (merged_line.eta_time or ""):
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
        if not merged_line.plan_date or not merged_line.eta_time:
            plan_res = resolve_plan_detailed(db, updated_job, carrier_ctx.source_group, for_update=False)
            if plan_res.plan:
                if not merged_line.plan_date and plan_res.plan.plan_date:
                    merged_line.plan_date = plan_res.plan.plan_date.isoformat()
                plan_eta = extract_plan_expected_time(plan_res.plan)
                if not merged_line.eta_time and plan_eta:
                    merged_line.eta_time = plan_eta
                    merged_line.eta_text = merged_line.eta_text or plan_eta
                    merged_line.field_evidences.setdefault("eta_time", "transport_plan")
                    upd_raw = dict(updated_job.raw_fields or {})
                    upd_raw["eta"] = plan_eta
                    upd_raw["field_evidences"] = merged_line.field_evidences
                    upd_raw["canonical_record"] = merged_line.to_canonical_record()
                    updated_job.raw_fields = upd_raw
                    if isinstance(new_truck.raw_data, dict):
                        new_truck.raw_data = {**new_truck.raw_data, "eta": plan_eta, "eta_text": plan_eta}

        update_text = OutboundTemplateBuilder.build_update_notification(
            line=merged_line,
            changes_list=changes_list,
            customer_name=cust_name,
            warehouse_name=wh_name,
            customer_id=cust_obj.tms_customer_id if cust_obj else None,
            plan_date=merged_line.plan_date,
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

        target_grp = db.get(ZaloGroup, target_gid)
        is_manual = cls.is_manual_approval_required(carrier_ctx.source_group, target_grp)

        # 5b. Chỉ đồng bộ lên bảng kế hoạch vận chuyển cục bộ & TMS khi nhóm ở chế độ AUTO.
        # Khi nhóm ở chế độ Chờ duyệt (MANUAL), giữ nguyên TransportPlan cho tới khi ĐHVT duyệt.
        if not is_manual:
            if not cls.sync_job_with_local_plan_or_review(
                db=db,
                job=updated_job,
                source_group=carrier_ctx.source_group,
                is_test_msg=carrier_ctx.is_test_msg,
                allow_tms_sync=True,
            ):
                updated_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                message.processing_status = MessageStatus.NEEDS_REVIEW.value
                db.commit()
                db.refresh(message)
                return message

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
            upd_pid = (updated_job.raw_fields or {}).get("transport_plan_id") if isinstance(updated_job.raw_fields, dict) else None
            manual_rc, _ = DhvtNotificationService.create_or_merge_review_case(
                db=db,
                message_id=message.id,
                case_type="group_manual_review",
                reason=f"Bản cập nhật xe/lái xe cont {updated_job.container_no or 'N/A'} cần ĐHVT duyệt trước khi cập nhật kế hoạch và gửi khách.",
                container_job_id=updated_job.id,
                container_no=updated_job.container_no,
                details={
                    "outbound_message_id": str(outbound.id),
                    "changes": changes_list,
                    **({"selected_plan_id": str(upd_pid), "transport_plan_id": str(upd_pid)} if upd_pid else {}),
                },
                suggestion="Mở mục Chờ duyệt để kiểm tra nội dung cập nhật và phát hành tới khách hàng.",
                is_test_msg=carrier_ctx.is_test_msg,
                notify_zalo=False,
            )
            DhvtNotificationService.notify_pending_outbound(
                db=db,
                outbound=outbound,
                target_group_name=target_grp.name if target_grp else str(target_zalo_gid),
                containers=[updated_job.container_no] if updated_job.container_no else [],
                reason=f"Bản cập nhật xe/lái xe cont {updated_job.container_no or 'N/A'} cần duyệt gửi khách.",
                is_test_msg=carrier_ctx.is_test_msg,
                review_case_id=manual_rc.id,
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
        old_truck = target_job.truck_record
        old_plate = old_truck.truck_plate if old_truck else None
        old_trailer = old_truck.trailer_plate if old_truck else None
        old_driver = old_truck.driver_name if old_truck else None
        old_phone = old_truck.driver_phone if old_truck else None
        old_seal = target_job.seal_no
        had_sent_outbound = target_job.routing_status == RoutingStatus.SENT.value or (
            db.scalar(
                select(OutboundMessage.id)
                .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
                .where(
                    OutboundMessageItem.container_job_id == target_job.id,
                    OutboundMessage.status == OutboundStatus.SENT.value,
                )
                .limit(1)
            )
            is not None
        )
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
        if plan_check.matched_plan is not None:
            mp = plan_check.matched_plan
            merged_line.transport_plan_id = merged_line.transport_plan_id or mp.id
            if not target_job.customer_id and mp.customer_id:
                target_job.customer_id = mp.customer_id
                merged_line.customer_code_or_id = mp.customer_id
            if not merged_line.customer_hint and mp.customer_name:
                merged_line.customer_hint = mp.customer_name
                target_job.customer_hint = target_job.customer_hint or mp.customer_name
            if not target_job.warehouse_id and mp.warehouse_id:
                target_job.warehouse_id = mp.warehouse_id
                merged_line.warehouse_code_or_id = mp.warehouse_id
            if not merged_line.warehouse_hint and (mp.warehouse_name or mp.delivery_address):
                wh_label = (mp.warehouse_name or mp.delivery_address or "")[:255]
                merged_line.warehouse_hint = wh_label
                target_job.warehouse_hint = target_job.warehouse_hint or wh_label
            if mp.order_type and (not merged_line.order_type or merged_line.inferred_order_type):
                mo = mp.order_type.strip().lower()
                merged_line.order_type = (
                    OrderType.LOAD.value if mo in ("load", "dong", "xuat")
                    else (OrderType.RETURN.value if mo in ("return", "tra", "nhap") else mp.order_type)
                )
                target_job.order_type = merged_line.order_type
            if mp.seal_no and not merged_line.seal_no:
                merged_line.seal_no = mp.seal_no
                target_job.seal_no = target_job.seal_no or mp.seal_no
            if mp.container_size and not merged_line.container_size:
                merged_line.container_size = mp.container_size
                target_job.container_size = target_job.container_size or mp.container_size
            if mp.planned_trailer_plate and not merged_line.trailer_plate:
                merged_line.trailer_plate = mp.planned_trailer_plate
                if target_job.truck_record and not target_job.truck_record.trailer_plate:
                    target_job.truck_record.trailer_plate = mp.planned_trailer_plate
            if mp.group_id and not merged_line.target_group_id:
                merged_line.target_group_id = str(mp.group_id).strip()
            if mp.plan_date:
                merged_line.plan_date = mp.plan_date.isoformat()
            plan_eta = extract_plan_expected_time(mp)
            t_raw = dict(target_job.raw_fields or {})
            t_raw["transport_plan_id"] = merged_line.transport_plan_id
            t_raw["plan_date"] = merged_line.plan_date
            if plan_eta and not merged_line.eta_time:
                merged_line.eta_time = plan_eta
                merged_line.eta_text = merged_line.eta_text or plan_eta
                merged_line.field_evidences.setdefault("eta_time", "transport_plan")
                t_raw["eta"] = plan_eta
                t_raw["eta_text"] = merged_line.eta_text
                if target_job.truck_record and isinstance(target_job.truck_record.raw_data, dict):
                    target_job.truck_record.raw_data = {
                        **target_job.truck_record.raw_data,
                        "eta": plan_eta,
                        "eta_text": plan_eta,
                    }
            t_raw["field_evidences"] = merged_line.field_evidences
            t_raw["canonical_record"] = merged_line.to_canonical_record()
            target_job.raw_fields = t_raw
        is_complete, _missing_fields = OutboundTemplateBuilder.check_core_fields_completeness(merged_line)
        if is_complete:
            # Khi bổ sung đã đủ thông tin cốt lõi, đóng BotReply và ca thiếu trường cũ của đơn gốc
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
                    ReviewCase.case_type.in_(["missing_fields", "invalid_check_digit"]),
                )
            ).all():
                rc.status = ReviewStatus.RESOLVED.value
                rc.resolved_by = "carrier_supplement"
                rc.resolved_at = now

        is_simple_cont_defect = (
            plan_check.is_shipping_missing
            and not plan_check.is_carrier_mismatch
            and (not merged_line.container_no or merged_line.check_digit_valid is False)
        )
        if (plan_check.is_carrier_mismatch or plan_check.is_shipping_missing) and not is_simple_cont_defect:
            if plan_check.is_carrier_mismatch:
                case_type = "CARRIER_MISMATCH"
            elif "nhiều dòng kế hoạch" in (plan_check.reason or ""):
                case_type = "PLAN_SYNC_REQUIRED"
            else:
                case_type = "SHIPPING_NOT_FOUND"
            case_details = merged_line.to_dict()
            if getattr(plan_check, "candidate_plans", None):
                case_details["candidate_plans"] = [
                    {
                        "plan_id": str(cp.id),
                        "order_code": cp.order_code,
                        "order_type": cp.order_type,
                        "customer_name": cp.customer_name,
                        "warehouse_name": cp.warehouse_name or cp.delivery_address,
                        "container_no": cp.container_no,
                        "plan_date": cp.plan_date.isoformat() if cp.plan_date else None,
                        "required_time": extract_plan_expected_time(cp),
                        "version": cp.version,
                        "score": 80,
                        "evidences": ["matching_slot" if not cp.container_no else "container_match"],
                        "exclusions": [],
                    }
                    for cp in plan_check.candidate_plans[:10]
                ]
            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    container_job_id=target_job.id,
                    case_type=case_type,
                    reason=plan_check.reason or "Không khớp kế hoạch hoặc nhà xe.",
                    details=case_details,
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
            target_job.validation_status = (
                ValidationStatus.VALID.value if is_complete else ValidationStatus.NEEDS_REVIEW.value
            )
            target_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

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
            # Nháp xác nhận đổi xe thuộc luồng riêng, không đóng khi bổ sung tin khác.
            if (draft.entities or {}).get("kind") == "assistant_vehicle_change":
                continue
            draft.status = MessageDraftStatus.FLUSHED.value
            draft.flushed_at = now

        cust_obj = db.get(Customer, target_job.customer_id) if target_job.customer_id else None
        wh_obj = db.get(Warehouse, target_job.warehouse_id) if target_job.warehouse_id else None
        changes_list: list[str] = []
        if had_sent_outbound:
            if (compact_plate(old_plate) or "") != (compact_plate(merged_line.truck_plate) or "") and merged_line.truck_plate:
                changes_list.append(f"- Biển số xe: {old_plate or 'Chưa có'} -> {merged_line.truck_plate}")
            if (compact_plate(old_trailer) or "") != (compact_plate(merged_line.trailer_plate) or "") and merged_line.trailer_plate:
                changes_list.append(f"- Biển số rơ-moóc: {old_trailer or 'Chưa có'} -> {merged_line.trailer_plate}")
            if " ".join((old_driver or "").lower().split()) != " ".join((merged_line.driver_name or "").lower().split()) and merged_line.driver_name:
                changes_list.append(f"- Lái xe: {old_driver or 'Chưa có'} -> {merged_line.driver_name}")
            if re.sub(r"\D", "", old_phone or "") != re.sub(r"\D", "", merged_line.driver_phone or "") and merged_line.driver_phone:
                changes_list.append(f"- SĐT: {old_phone or 'Chưa có'} -> {merged_line.driver_phone}")
            if re.sub(r"[^A-Za-z0-9]", "", old_seal or "").upper() != re.sub(r"[^A-Za-z0-9]", "", merged_line.seal_no or "").upper() and merged_line.seal_no:
                changes_list.append(f"- Số chì: {old_seal or 'Chưa có'} -> {merged_line.seal_no}")

        if had_sent_outbound and changes_list:
            notif_text = OutboundTemplateBuilder.build_update_notification(
                line=merged_line,
                changes_list=changes_list,
                customer_name=cust_obj.name if cust_obj else (merged_line.customer_hint or "Quý khách hàng"),
                warehouse_name=wh_obj.name if wh_obj else (merged_line.warehouse_hint or "Kho khách hàng"),
                customer_id=cust_obj.tms_customer_id if cust_obj else None,
                plan_date=merged_line.plan_date,
            )
        else:
            notif_text = OutboundTemplateBuilder.build_customer_notification(
                line=merged_line,
                customer_name=cust_obj.name if cust_obj else (merged_line.customer_hint or "Quý khách hàng"),
                warehouse_name=wh_obj.name if wh_obj else (merged_line.warehouse_hint or "Kho khách hàng"),
                customer_id=cust_obj.tms_customer_id if cust_obj else None,
                plan_date=merged_line.plan_date,
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

        target_grp = db.get(ZaloGroup, target_gid)
        is_manual = cls.is_manual_approval_required(carrier_ctx.source_group, target_grp)

        # Chỉ ghi trước TransportPlan & đồng bộ TMS khi nhóm ở chế độ AUTO
        if not is_manual:
            if not cls.sync_job_with_local_plan_or_review(
                db=db,
                job=target_job,
                source_group=carrier_ctx.source_group,
                is_test_msg=carrier_ctx.is_test_msg,
                allow_tms_sync=True,
            ):
                target_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                message.processing_status = MessageStatus.NEEDS_REVIEW.value
                db.commit()
                db.refresh(message)
                return message

        # Hủy các bản nháp chưa gửi cũ của chính job này trước khi tạo thông báo mới đã cập nhật
        for stale_out in db.scalars(
            select(OutboundMessage)
            .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
            .where(
                OutboundMessageItem.container_job_id == target_job.id,
                OutboundMessage.status.in_([OutboundStatus.PENDING_APPROVAL.value, OutboundStatus.PENDING_SEND.value]),
            )
        ).all():
            stale_out.status = OutboundStatus.CANCELLED.value
            stale_out.last_error = "Đã cập nhật bởi tin bổ sung mới hơn."

        out_status = OutboundStatus.PENDING_APPROVAL.value if is_manual else OutboundStatus.PENDING_SEND.value
        outbound = OutboundMessage(
            id=snowflake.generate(),
            target_group_id=target_gid,
            order_type=target_job.order_type or OrderType.LOAD.value,
            message_kind="update" if (had_sent_outbound and changes_list) else "supplement",
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
            supp_pid = (target_job.raw_fields or {}).get("transport_plan_id") if isinstance(target_job.raw_fields, dict) else None
            manual_rc, _ = DhvtNotificationService.create_or_merge_review_case(
                db=db,
                message_id=message.id,
                case_type="group_manual_review",
                reason=f"Bổ sung đủ dữ liệu cont {target_job.container_no or 'N/A'} cần ĐHVT duyệt trước khi cập nhật kế hoạch và gửi khách.",
                container_job_id=target_job.id,
                container_no=target_job.container_no,
                details={
                    "outbound_message_id": str(outbound.id),
                    **({"selected_plan_id": str(supp_pid), "transport_plan_id": str(supp_pid)} if supp_pid else {}),
                },
                suggestion="Mở mục Chờ duyệt để kiểm tra và phát hành tới khách hàng.",
                is_test_msg=carrier_ctx.is_test_msg,
                notify_zalo=False,
            )
            DhvtNotificationService.notify_pending_outbound(
                db=db,
                outbound=outbound,
                target_group_name=target_grp.name if target_grp else str(target_zalo_gid),
                containers=[target_job.container_no] if target_job.container_no else [],
                reason=f"Bổ sung đủ dữ liệu cont {target_job.container_no or 'N/A'} cần ĐHVT duyệt gửi khách.",
                is_test_msg=carrier_ctx.is_test_msg,
                review_case_id=manual_rc.id,
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

        # Gửi phản hồi xác nhận cho nhà xe khi đã bổ sung đủ thông tin
        if had_sent_outbound and changes_list:
            supp_confirm_text = OutboundTemplateBuilder.build_update_confirm_reply(
                container_no=target_job.container_no or "",
                changes_list=changes_list,
            )
        elif is_manual:
            supp_confirm_text = (
                f"[VSICO Bot] Đã nhận bổ sung đủ thông tin cont {target_job.container_no or ''}"
                f"{f' (xe {merged_line.truck_plate})' if merged_line.truck_plate else ''}, "
                "đang chờ ĐHVT duyệt gửi khách."
            )
        else:
            supp_confirm_text = (
                f"[VSICO Bot] Đã nhận bổ sung đủ thông tin cho cont {target_job.container_no or ''}"
                f"{f' (xe {merged_line.truck_plate})' if merged_line.truck_plate else ''}."
            )
        supp_confirm_reply = BotReply(
            id=snowflake.generate(),
            message_id=message.id,
            sender_id=message.sender_id,
            reply_text=supp_confirm_text,
            fix_deadline=now + timedelta(minutes=30),
            status=CorrectionStatus.RESOLVED.value,
        )
        db.add(supp_confirm_reply)
        if cls._is_dispatchable_real_group(message.group_id, carrier_ctx.source_group, carrier_ctx.is_test_msg):
            ok_s, s_mid, _ = ZaloDispatcher.send_to_group(
                group_id=message.group_id,
                message=supp_confirm_text,
                quote_msg_id=message.zalo_message_id,
            )
            if ok_s and s_mid:
                supp_confirm_reply.zalo_msg_id = s_mid
                supp_confirm_reply.sent_at = now
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

    # ------------------------------------------------------------------
    # Bổ sung nghiệp vụ Hạng mục 3 & 4: Lệnh kết hợp RO+LO, Gom tin 60s,
    # Danh thiếp Zalo (Contact Card) & Xác nhận OCR 5 trường
    # ------------------------------------------------------------------

    @staticmethod
    def extract_contact_card_text(raw_payload: dict[str, Any] | None) -> str:
        """Trích xuất tên và SĐT từ Danh thiếp Zalo (`contact` / `business_card`) trong payload đính kèm."""
        if not isinstance(raw_payload, dict):
            return ""
        candidates: list[dict[str, Any]] = []
        for top_key in ("contact", "business_card", "vcard", "user_contact"):
            top_val = raw_payload.get(top_key)
            if isinstance(top_val, dict):
                candidates.append({"type": top_key, "payload": top_val})
        attachments = raw_payload.get("attachments")
        if not attachments and isinstance(raw_payload.get("message"), dict):
            attachments = raw_payload["message"].get("attachments")
        if isinstance(attachments, list):
            candidates.extend(att for att in attachments if isinstance(att, dict))
        if not candidates:
            return ""
        parts: list[str] = []
        for att in candidates:
            atype = str(att.get("type") or "").lower()
            if atype not in ("contact", "business_card", "vcard", "user_contact"):
                continue
            p = att.get("payload") if isinstance(att.get("payload"), dict) else att
            name = (
                p.get("display_name")
                or p.get("name")
                or p.get("full_name")
                or p.get("title")
                or ""
            )
            phone = p.get("phone") or p.get("phone_number") or p.get("sdt") or ""
            frag = " ".join(x for x in (f"Tài xế: {str(name).strip()}" if name else "", f"SĐT: {str(phone).strip()}" if phone else "") if x)
            if frag:
                parts.append(frag)
        return "\n".join(parts)

    @classmethod
    def detect_combined_ro_lo_pair(
        cls,
        db: Session,
        line: ExtractedContainerLine,
        carrier_ctx: CarrierContext,
    ) -> tuple[TransportPlan | None, TransportPlan | None, bool]:
        """Phát hiện cặp lệnh kết hợp (RO + LO) dùng chung 1 số container trong kế hoạch.

        Returns:
            tuple[ro_plan, lo_plan, ro_has_tms_vehicle_info]:
                Nếu container chỉ có 1 lệnh đơn (chỉ RO hoặc chỉ LO độc lập) -> trả `(None, None, False)`.
        """
        if not line.container_no:
            return None, None, False
        norm_cont = clean_container(line.container_no) or line.container_no.strip().upper()
        stmt = select(TransportPlan).where(TransportPlan.container_no == norm_cont)
        if carrier_ctx.numeric_carrier_id is not None:
            stmt = stmt.where(
                or_(
                    TransportPlan.carrier_id == carrier_ctx.numeric_carrier_id,
                    TransportPlan.carrier_id.is_(None),
                )
            )
        plans = list(
            db.scalars(stmt.order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc())).all()
        )
        ro_plans = [p for p in plans if normalize_vi_text(p.order_type) in ("tra", "return", "ro", "nhap")]
        lo_plans = [p for p in plans if normalize_vi_text(p.order_type) in ("dong", "load", "lo", "xuat")]
        if not ro_plans or not lo_plans:
            return None, None, False

        ro_plan = ro_plans[0]
        lo_plan = lo_plans[0]
        ro_has_info = bool(
            (ro_plan.planned_truck_plate or "").strip()
            and ((ro_plan.driver_name or "").strip() or (ro_plan.driver_phone or "").strip())
        )
        return ro_plan, lo_plan, ro_has_info

    @classmethod
    def buffer_or_merge_carrier_fragment(
        cls,
        db: Session,
        message: ZaloMessage,
        lines: list[ExtractedContainerLine],
        carrier_ctx: CarrierContext,
    ) -> tuple[str, list[ExtractedContainerLine]]:
        """Bộ gom tin rời rạc 60 giây cho nhà xe (`carrier_fragment_buffer` trong `message_drafts`).

        - Nếu nhà xe gửi mảnh tin chưa đủ 5 trường (chỉ biển số+moóc, chỉ danh thiếp tài xế, chỉ số cont):
          đệm vào `MessageDraft` với TTL 60 giây và trả `("BUFFERED", [])` để không bắt lỗi vội.
        - Khi tin kế tiếp cùng `(group_id, sender_id)` gửi trong 60 giây: gộp trường vào bản nháp;
          ngay khi đủ cả 5 trường hợp lệ -> đóng bản nháp (`FLUSHED`) và trả `("MERGED_READY", [merged_line])`.
        - Nếu tin gốc đã đủ 5 trường hoặc là đa xe / quote -> trả `("PASSTHROUGH", lines)`.
        """
        raw_p = message.raw_payload or {}
        debounce_sec = int(getattr(settings, "CARRIER_DEBOUNCE_SECONDS", 60) or 60)
        group_delay = int(getattr(settings, "GROUP_PROCESS_DELAY_SECONDS", 0) or 0)
        in_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
        debounce_enabled = (
            debounce_sec > 0
            and carrier_ctx.source_group is not None
            and (
                bool(raw_p.get("enable_debounce")) or group_delay > 0
                if (carrier_ctx.is_test_msg or in_pytest)
                else True
            )
        )
        if not debounce_enabled or not lines or len(lines) != 1 or message.quote_msg_id:
            return "PASSTHROUGH", lines

        now = datetime.now()
        incoming = lines[0]
        is_comp_now, _ = OutboundTemplateBuilder.check_core_fields_completeness(incoming)

        open_draft = db.scalar(
            select(MessageDraft)
            .where(
                MessageDraft.group_id == message.group_id,
                MessageDraft.sender_id == message.sender_id,
                MessageDraft.status == MessageDraftStatus.OPEN.value,
                MessageDraft.entities["kind"].as_string() == "carrier_fragment_buffer",
            )
            .order_by(MessageDraft.id.desc())
        )
        if open_draft is not None and open_draft.expires_at:
            exp_naive = open_draft.expires_at.replace(tzinfo=None)
            if exp_naive <= now.replace(tzinfo=None):
                open_draft.status = MessageDraftStatus.EXPIRED.value
                open_draft = None

        if open_draft is None:
            if is_comp_now:
                return "PASSTHROUGH", lines
            # Tin đã có >= 3 trường nhưng chứa lỗi cứng (container sai định dạng/check-digit, biển số/SĐT sai)
            # -> không đệm 60s mà đi thẳng để phản hồi báo lỗi ngay cho nhà xe.
            attempted_slots = sum(
                1
                for val in (
                    incoming.truck_plate,
                    incoming.trailer_plate,
                    incoming.container_no,
                    incoming.driver_name,
                    incoming.driver_phone,
                )
                if val
            )
            has_hard_format_defect = bool(
                incoming.check_digit_valid is False
                or any(
                    w in (incoming.warnings or [])
                    for w in (
                        "INVALID_CONTAINER_FORMAT",
                        "INVALID_TRUCK_PLATE_FORMAT",
                        "INVALID_TRAILER_PLATE_FORMAT",
                        "INVALID_DRIVER_PHONE",
                    )
                )
            )
            if has_hard_format_defect and attempted_slots >= 3:
                return "PASSTHROUGH", lines
            # Chỉ đệm nếu mảnh tin chứa ít nhất 1 thực thể điều vận (biển số / moóc / cont / tài xế / SĐT)
            has_fragment_entity = bool(
                incoming.truck_plate
                or incoming.trailer_plate
                or incoming.container_no
                or incoming.driver_name
                or incoming.driver_phone
            )
            if not has_fragment_entity:
                return "PASSTHROUGH", lines

            # Nếu tin nhắn đã chờ đủ cửa sổ 60s ở FIFO và KHÔNG còn tin kế tiếp của cùng người gửi đang chờ trong queue:
            # cho đi thẳng để phản hồi nhắc bổ sung luôn, tránh cộng dồn chờ 60s + 60s = 120s.
            group_delay = int(getattr(settings, "GROUP_PROCESS_DELAY_SECONDS", 0) or 0)
            if group_delay > 0 and not raw_p.get("enable_debounce"):
                more_queued = db.scalar(
                    select(ZaloMessage.id)
                    .where(
                        ZaloMessage.group_id == message.group_id,
                        ZaloMessage.sender_id == message.sender_id,
                        ZaloMessage.id > message.id,
                        ZaloMessage.processing_status.in_(
                            [MessageStatus.RECEIVED.value, MessageStatus.QUEUED.value]
                        ),
                    )
                    .limit(1)
                )
                msg_ts = message.received_at or message.created_at
                msg_naive = msg_ts.astimezone().replace(tzinfo=None) if (msg_ts and msg_ts.tzinfo) else msg_ts
                waited_enough = bool(
                    msg_naive and (now - msg_naive) >= timedelta(seconds=group_delay)
                )
                if more_queued is None and waited_enough:
                    return "PASSTHROUGH", lines

            draft_entities = {
                "kind": "carrier_fragment_buffer",
                "texts": [(message.message_text or "").strip()],
                "message_ids": [str(message.id)],
                "fields": {
                    "truck_plate": incoming.truck_plate,
                    "raw_truck_plate": incoming.raw_truck_plate,
                    "trailer_plate": incoming.trailer_plate,
                    "driver_name": incoming.driver_name,
                    "driver_phone": incoming.driver_phone,
                    "container_no": incoming.container_no,
                    "container_size": incoming.canonical_cont_size or incoming.container_size,
                    "seal_no": incoming.seal_no,
                    "order_type": incoming.order_type,
                    "customer_hint": incoming.customer_hint,
                    "warehouse_hint": incoming.warehouse_hint,
                    "eta_time": incoming.eta_time,
                    "plan_date": incoming.plan_date,
                },
            }
            db.add(
                MessageDraft(
                    id=snowflake.generate(),
                    zalo_info_id=carrier_ctx.source_group.id,
                    group_id=message.group_id,
                    sender_id=message.sender_id,
                    carrier_id=carrier_ctx.numeric_carrier_id,
                    first_message_id=message.id,
                    last_message_id=message.id,
                    message_count=1,
                    status=MessageDraftStatus.OPEN.value,
                    entities=draft_entities,
                    expires_at=now + timedelta(seconds=debounce_sec),
                )
            )
            message.processing_status = MessageStatus.PROCESSED.value
            db.commit()
            return "BUFFERED", []

        # Gộp tin mới vào bản nháp đang mở trong cửa sổ 60 giây
        prev_ent = dict(open_draft.entities or {})
        prev_fields = dict(prev_ent.get("fields") or {})
        prev_texts = list(prev_ent.get("texts") or [])
        prev_mids = list(prev_ent.get("message_ids") or [])
        if (message.message_text or "").strip():
            prev_texts.append((message.message_text or "").strip())
        prev_mids.append(str(message.id))

        merged_fields = {
            "truck_plate": incoming.truck_plate or prev_fields.get("truck_plate"),
            "raw_truck_plate": incoming.raw_truck_plate or prev_fields.get("raw_truck_plate"),
            "trailer_plate": incoming.trailer_plate or prev_fields.get("trailer_plate"),
            "driver_name": incoming.driver_name or prev_fields.get("driver_name"),
            "driver_phone": incoming.driver_phone or prev_fields.get("driver_phone"),
            "container_no": incoming.container_no or prev_fields.get("container_no"),
            "container_size": (incoming.canonical_cont_size or incoming.container_size) or prev_fields.get("container_size"),
            "seal_no": incoming.seal_no or prev_fields.get("seal_no"),
            "order_type": incoming.order_type or prev_fields.get("order_type"),
            "customer_hint": incoming.customer_hint or prev_fields.get("customer_hint"),
            "warehouse_hint": incoming.warehouse_hint or prev_fields.get("warehouse_hint"),
            "eta_time": incoming.eta_time or prev_fields.get("eta_time"),
            "plan_date": incoming.plan_date or prev_fields.get("plan_date"),
        }
        merged_line = ExtractedContainerLine(
            line_no=1,
            line_text="\n".join(prev_texts),
            source_format="tu_do",
            plan_date=merged_fields["plan_date"],
            truck_plate=clean_plate(merged_fields["truck_plate"]) if merged_fields["truck_plate"] else None,
            raw_truck_plate=merged_fields["raw_truck_plate"],
            trailer_plate=clean_plate(merged_fields["trailer_plate"]) if merged_fields["trailer_plate"] else None,
            driver_name=merged_fields["driver_name"],
            driver_phone=clean_phone(merged_fields["driver_phone"]) if merged_fields["driver_phone"] else None,
            container_no=clean_container(merged_fields["container_no"]) if merged_fields["container_no"] else None,
            container_size=merged_fields["container_size"],
            seal_no=merged_fields["seal_no"],
            order_type=merged_fields["order_type"],
            customer_hint=merged_fields["customer_hint"],
            warehouse_hint=merged_fields["warehouse_hint"],
            eta_time=merged_fields["eta_time"],
            carrier_id=carrier_ctx.numeric_carrier_id,
        )
        merged_line = ContainerValidator.validate_line(merged_line)
        merged_complete, _ = OutboundTemplateBuilder.check_core_fields_completeness(merged_line)

        open_draft.last_message_id = message.id
        open_draft.message_count = (open_draft.message_count or 1) + 1
        open_draft.entities = {
            **prev_ent,
            "texts": prev_texts,
            "message_ids": prev_mids,
            "fields": merged_fields,
        }
        if merged_complete and merged_line.validation_status == ValidationStatus.VALID.value:
            open_draft.status = MessageDraftStatus.FLUSHED.value
            open_draft.flushed_at = now
            db.flush()
            return "MERGED_READY", [merged_line]

        # Nếu cụm tin đã mở khóa do hết cửa sổ chờ 20s (hoặc chạm trần tối đa 60s) và không còn tin chờ phía sau -> xả bản gộp ngay
        group_delay = int(getattr(settings, "GROUP_PROCESS_DELAY_SECONDS", 0) or 0)
        max_wait_sec = int(getattr(settings, "GROUP_PROCESS_MAX_WAIT_SECONDS", 60) or 0)
        if group_delay > 0 and not raw_p.get("enable_debounce"):
            more_queued_after = db.scalar(
                select(ZaloMessage.id)
                .where(
                    ZaloMessage.group_id == message.group_id,
                    ZaloMessage.sender_id == message.sender_id,
                    ZaloMessage.id > message.id,
                    ZaloMessage.processing_status.in_(
                        [MessageStatus.RECEIVED.value, MessageStatus.QUEUED.value]
                    ),
                )
                .limit(1)
            )
            msg_ts = message.received_at or message.created_at
            msg_naive = msg_ts.astimezone().replace(tzinfo=None) if (msg_ts and msg_ts.tzinfo) else msg_ts
            first_msg_obj = db.get(ZaloMessage, open_draft.first_message_id) if open_draft.first_message_id else None
            first_ts = (first_msg_obj.received_at or first_msg_obj.created_at) if first_msg_obj else msg_ts
            first_naive = first_ts.astimezone().replace(tzinfo=None) if (first_ts and first_ts.tzinfo) else first_ts
            hit_delay = bool(msg_naive and (now - msg_naive) >= timedelta(seconds=group_delay))
            hit_max_wait = bool(max_wait_sec > 0 and first_naive and (now - first_naive) >= timedelta(seconds=max_wait_sec))
            if more_queued_after is None and (hit_delay or hit_max_wait):
                open_draft.status = MessageDraftStatus.FLUSHED.value
                open_draft.flushed_at = now
                db.flush()
                return "MERGED_READY", [merged_line]

        open_draft.expires_at = now + timedelta(seconds=debounce_sec)
        message.processing_status = MessageStatus.PROCESSED.value
        db.commit()
        return "BUFFERED", []

    @classmethod
    def flush_expired_carrier_drafts(cls, db: Session) -> int:
        """Quét các bản nháp gom tin 60s (`carrier_fragment_buffer`) đã hết hạn để gửi 1 tin nhắc bổ sung duy nhất."""
        now = datetime.now()
        expired_drafts = list(
            db.scalars(
                select(MessageDraft)
                .where(
                    MessageDraft.status == MessageDraftStatus.OPEN.value,
                    MessageDraft.entities["kind"].as_string() == "carrier_fragment_buffer",
                    MessageDraft.expires_at <= now.replace(tzinfo=None),
                )
                .order_by(MessageDraft.id.asc())
                .limit(50)
            ).all()
        )
        flushed = 0
        for draft in expired_drafts:
            ent = dict(draft.entities or {})
            fields = dict(ent.get("fields") or {})
            texts = list(ent.get("texts") or [])
            line = ExtractedContainerLine(
                line_no=1,
                line_text="\n".join(texts),
                truck_plate=clean_plate(fields.get("truck_plate")) if fields.get("truck_plate") else None,
                trailer_plate=clean_plate(fields.get("trailer_plate")) if fields.get("trailer_plate") else None,
                driver_name=fields.get("driver_name"),
                driver_phone=clean_phone(fields.get("driver_phone")) if fields.get("driver_phone") else None,
                container_no=clean_container(fields.get("container_no")) if fields.get("container_no") else None,
                seal_no=fields.get("seal_no"),
                order_type=fields.get("order_type"),
                customer_hint=fields.get("customer_hint"),
                warehouse_hint=fields.get("warehouse_hint"),
                eta_time=fields.get("eta_time"),
                plan_date=fields.get("plan_date"),
            )
            from src.handlers.plan_sync_service import resolve_trailer_from_catalog
            from src.parsing.local_nlp_extractor import enrich_local, evaluate_missing_field_signals

            line = ContainerValidator.validate_line(line)
            enriched_draft = enrich_local(
                db=db,
                lines=[line],
                carrier_id=draft.carrier_id,
                raw_text=line.line_text,
                reference=now,
                group_id=draft.group_id,
                sender_id=draft.sender_id,
                include_phobert=True,
            )
            line = enriched_draft[0] if enriched_draft else line
            resolve_trailer_from_catalog(db, line, draft.carrier_id)
            line = ContainerValidator.validate_line(line)
            evaluate_missing_field_signals(line)
            warn_text = OutboundTemplateBuilder.build_carrier_warning_reply([line])
            last_msg = db.get(ZaloMessage, draft.last_message_id or draft.first_message_id)
            src_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == draft.group_id))
            is_test = cls.is_test_message(last_msg, src_grp) if last_msg else True

            if warn_text and last_msg:
                br = BotReply(
                    id=snowflake.generate(),
                    message_id=last_msg.id,
                    sender_id=draft.sender_id,
                    reply_text=warn_text,
                    fix_deadline=now + timedelta(minutes=30),
                    status=CorrectionStatus.PENDING.value,
                )
                db.add(br)
                db.flush()
                if cls._is_dispatchable_real_group(draft.group_id, src_grp, is_test):
                    ok_s, mid_s, _ = ZaloDispatcher.send_to_group(
                        group_id=draft.group_id,
                        message=warn_text,
                        quote_msg_id=last_msg.zalo_message_id,
                    )
                    if ok_s and mid_s:
                        br.zalo_msg_id = mid_s
                        br.sent_at = now
                last_msg.processing_status = MessageStatus.NEEDS_REVIEW.value

            draft.status = MessageDraftStatus.FLUSHED.value
            draft.flushed_at = now
            flushed += 1

        if flushed:
            db.commit()
        return flushed

    @classmethod
    def create_ocr_confirmation_draft(
        cls,
        db: Session,
        message: ZaloMessage,
        line: ExtractedContainerLine,
        carrier_ctx: CarrierContext,
    ) -> ZaloMessage:
        """Tạo bản nháp xác nhận nhanh 5 trường đọc được từ ảnh OCR và hỏi nhà xe xác nhận ('ok' hoặc nhắn dòng sửa)."""
        now = datetime.now()
        summary_lines = [
            "[VSICO Bot] Hệ thống đọc được thông tin từ ảnh như sau:",
            f"- Biển số xe: {line.truck_plate or 'Chưa rõ'}",
            f"- Biển số rơ-moóc: {line.trailer_plate or 'Chưa rõ'}",
            f"- Tài xế: {line.driver_name or 'Chưa rõ'} | SĐT: {line.driver_phone or 'Chưa rõ'}",
            f"- Số container: {line.container_no or 'Chưa rõ'}",
            "Anh/chị nhắn 'ok' để xác nhận hoặc nhắn lại dòng cần sửa giúp hệ thống nhé.",
        ]
        reply_text = "\n".join(summary_lines)
        if carrier_ctx.source_group is not None:
            draft = MessageDraft(
                id=snowflake.generate(),
                zalo_info_id=carrier_ctx.source_group.id,
                group_id=message.group_id,
                sender_id=message.sender_id,
                carrier_id=carrier_ctx.numeric_carrier_id,
                first_message_id=message.id,
                last_message_id=message.id,
                message_count=1,
                status=MessageDraftStatus.WAITING_REPLY.value,
                entities={
                    "kind": "carrier_ocr_confirm",
                    "fields": line.to_dict(),
                    "raw_text": message.message_text,
                },
                expires_at=now + timedelta(minutes=30),
            )
            db.add(draft)
        br = BotReply(
            id=snowflake.generate(),
            message_id=message.id,
            sender_id=message.sender_id,
            reply_text=reply_text,
            fix_deadline=now + timedelta(minutes=30),
            status=CorrectionStatus.PENDING.value,
        )
        db.add(br)
        db.flush()
        if cls._is_dispatchable_real_group(message.group_id, carrier_ctx.source_group, carrier_ctx.is_test_msg):
            ok_s, mid_s, _ = ZaloDispatcher.send_to_group(
                group_id=message.group_id,
                message=reply_text,
                quote_msg_id=message.zalo_message_id,
            )
            if ok_s and mid_s:
                br.zalo_msg_id = mid_s
                br.sent_at = now
        message.processing_status = MessageStatus.NEEDS_REVIEW.value
        db.commit()
        db.refresh(message)
        return message
