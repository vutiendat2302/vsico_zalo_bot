"""Module Điều Phối Bóc Tách & Lưu Trữ Dữ Liệu Tin Nhắn (Extraction Handler).

Chịu trách nhiệm thực thi trọn vẹn luồng xử lý cho từng tin nhắn được lấy ra từ
hàng đợi FIFO:
1. Bộ lọc 2 tầng (`IntentClassifier`) chặn sớm tin nhắn giao tiếp xã giao ('hello', 'cảm ơn'...)
   trong < 0.05ms để tối ưu hiệu năng và không tốn phí AI.
2. Phân đoạn đa xe/đa lệnh và bóc tách chuẩn F1, F2, F3, Tự do (`TripParser`).
3. Nếu định dạng tự do quá phức tạp và bật `AI_ENABLED`, kích hoạt `AIFallbackExtractor`
   (tự động che SĐT thành `xxxx` khi gửi AI và khôi phục SĐT thật khi lưu DB).
4. Tra cứu `customer_aliases`, `warehouse_aliases` và `transport_plans` (theo `cont_no` cho F1/F2)
   để hoàn thiện **Bản ghi chuẩn (`canonical_record`)**.
5. Lưu ngay lập tức vào MySQL (`extraction_runs`, `truck_records`, `container_jobs`, `review_cases`, `bot_replies`).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import re
import time
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.enums import (
    CorrectionStatus,
    Intent,
    MessageStatus,
    OrderType,
    OutboundStatus,
    ReviewStatus,
    RoutingStatus,
    SendMode,
    TmsSyncStatus,
    ValidationStatus,
)
from contextlib import nullcontext
from src.domain.models import ExtractedContainerLine
from src.domain.rules import compact_plate
from src.handlers.carrier_flow_service import CarrierFlowService
from src.handlers.dhvt_service import DhvtNotificationService
from src.handlers.plan_sync_service import extract_plan_expected_time, resolve_trailer_from_catalog
from src.infrastructure.models import (
    BotReply,
    Carrier,
    ContainerJob,
    Customer,
    CustomerAlias,
    ExtractionRun,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    RouteMap,
    TransportPlan,
    TruckRecord,
    Warehouse,
    WarehouseAlias,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher
from src.messaging.classifier import IntentClassifier
from src.observability.logging import get_logger
from src.outbound.templates import OutboundTemplateBuilder
from src.parsing.ai_fallback import AIFallbackExtractor
from src.parsing.trip_parser import TripParser
from src.validation.taxonomy import MessageTaxonomyAnalyzer
from src.validation.validators import ContainerValidator

logger = get_logger(__name__)


class ExtractionHandler:
    """Bộ xử lý trung tâm thực hiện bóc tách dữ liệu từ tin nhắn gốc và lưu vào MySQL."""

    @classmethod
    def _enrich_from_catalog_and_plans(
        cls,
        db: Session,
        line: ExtractedContainerLine,
    ) -> tuple[Optional[int], Optional[int], bool, bool, bool]:
        """Tra cứu Khách hàng, Kho (qua tên chuẩn, alias) và Kế hoạch điều phối (`transport_plans`).

        Ưu tiên cao nhất: Khớp trực tiếp qua số Container trong bảng `transport_plans`, lấy trực tiếp
        loại lệnh (đóng/trả), khách hàng, địa chỉ kho và nhóm Zalo từ kế hoạch, tạm bỏ qua context tin nhắn.

        Args:
            db (Session): Phiên làm việc SQLAlchemy.
            line (ExtractedContainerLine): Dòng container đang xử lý.

        Returns:
            tuple: `(warehouse_id, customer_id, unmatched_warehouse, unmatched_customer, ambiguous_match)`
        """
        wh_id: Optional[int] = None
        cust_id: Optional[int] = None
        unmatched_wh = False
        unmatched_cust = False
        ambiguous = False
        match_sources: list[str] = []

        # 1. Tra cứu Kế hoạch vận chuyển (TransportPlan) theo số container (cont_no)
        if line.container_no:
            plan_query = select(TransportPlan).where(
                TransportPlan.container_no == line.container_no.strip().upper()
            )
            if line.carrier_id:
                plan_query = plan_query.where(
                    or_(
                        TransportPlan.carrier_id == line.carrier_id,
                        TransportPlan.carrier_id.is_(None),
                    )
                )
            plan_query = plan_query.order_by(
                TransportPlan.plan_date.desc(),
                TransportPlan.stt.asc(),
                TransportPlan.id.asc(),
            )
            candidate_plans = list(db.scalars(plan_query).all())
            plan: Optional[TransportPlan] = None

            if candidate_plans:
                def _norm_otype(val: Optional[str]) -> Optional[str]:
                    v = (val or "").strip().lower()
                    if v in ("load", "dong", "xuat"):
                        return OrderType.LOAD.value
                    if v in ("return", "tra", "nhap"):
                        return OrderType.RETURN.value
                    return None

                line_otype_norm = _norm_otype(line.order_type)
                if line.customer_hint:
                    clean_msg_cust = line.customer_hint.strip().lower()
                    cust_matches = [
                        p for p in candidate_plans
                        if p.customer_name and (
                            clean_msg_cust in p.customer_name.strip().lower()
                            or p.customer_name.strip().lower() in clean_msg_cust
                        )
                    ]
                    if cust_matches:
                        if line_otype_norm:
                            order_cust_matches = [
                                p for p in cust_matches
                                if _norm_otype(p.order_type) == line_otype_norm
                            ]
                            plan = order_cust_matches[0] if order_cust_matches else cust_matches[0]
                        else:
                            plan = cust_matches[0]
                    else:
                        # Khách hàng bóc tách được từ tin nhắn không khớp với bất kỳ kế hoạch nào của container này
                        plan = None
                else:
                    # Tin nhắn không ghi khách hàng, lọc theo booking (nếu có) và loại lệnh rõ ràng
                    pool = candidate_plans
                    if line.booking_no:
                        bk_norm = line.booking_no.strip().upper()
                        bk_exact = [p for p in pool if (p.booking_no or "").strip().upper() == bk_norm]
                        if bk_exact:
                            pool = bk_exact
                        else:
                            pool = [
                                p for p in pool
                                if not (p.booking_no and p.booking_no.strip().upper() != bk_norm)
                            ]
                    if line_otype_norm:
                        order_matches = [
                            p for p in pool
                            if _norm_otype(p.order_type) == line_otype_norm
                        ]
                        if line.inferred_order_type:
                            plan = order_matches[0] if order_matches else (pool[0] if pool else None)
                        else:
                            plan = order_matches[0] if order_matches else None
                    elif not line.booking_no:
                        if len(pool) > 1:
                            # Khi nhiều lệnh (vd RO + LO) dùng chung 1 số container, ưu tiên lệnh chưa từng phát hành/chờ duyệt
                            sent_or_active_statuses = (
                                OutboundStatus.SENT.value,
                                "da_gui",
                                OutboundStatus.PENDING_SEND.value,
                                OutboundStatus.SENDING.value,
                                OutboundStatus.PENDING_APPROVAL.value,
                            )
                            dispatched_jobs = list(
                                db.scalars(
                                    select(ContainerJob)
                                    .join(OutboundMessageItem, OutboundMessageItem.container_job_id == ContainerJob.id)
                                    .join(OutboundMessage, OutboundMessage.id == OutboundMessageItem.outbound_message_id)
                                    .where(
                                        ContainerJob.container_no == line.container_no.strip().upper(),
                                        OutboundMessage.status.in_(sent_or_active_statuses),
                                    )
                                ).all()
                            )
                            dispatched_plan_ids: set[int] = set()
                            for dj in dispatched_jobs:
                                dj_raw = dj.raw_fields if isinstance(dj.raw_fields, dict) else {}
                                dj_pid = dj_raw.get("transport_plan_id")
                                if dj_pid:
                                    try:
                                        dispatched_plan_ids.add(int(dj_pid))
                                    except (TypeError, ValueError):
                                        pass
                            unsent_pool = [p for p in pool if p.id not in dispatched_plan_ids]
                            if unsent_pool:
                                pool = unsent_pool
                        plan = pool[0] if pool else None

            if plan is not None:
                line.transport_plan_id = plan.id
                # Ưu tiên lấy thông tin chuẩn từ bảng kế hoạch đã ghép với khách hàng
                if plan.order_type and (not line.order_type or line.inferred_order_type):
                    mapped_otype = (plan.order_type or "").strip().lower()
                    if mapped_otype in ("load", "dong", "xuat"):
                        line.order_type = OrderType.LOAD.value
                    elif mapped_otype in ("return", "tra", "nhap"):
                        line.order_type = OrderType.RETURN.value
                    else:
                        line.order_type = plan.order_type
                if plan.customer_name:
                    if not line.customer_hint:
                        line.customer_hint = plan.customer_name
                    line.customer_code_or_id = line.customer_code_or_id or plan.customer_name
                if plan.customer_id:
                    cust_id = plan.customer_id
                if plan.delivery_address or plan.address:
                    plan_addr = (plan.delivery_address or plan.address)[:255]
                    line.warehouse_hint = plan_addr
                    line.warehouse_code_or_id = line.warehouse_code_or_id or plan_addr
                if plan.warehouse_id:
                    wh_id = plan.warehouse_id
                if plan.seal_no and not line.seal_no:
                    line.seal_no = plan.seal_no
                if plan.container_size and not line.container_size:
                    line.container_size = plan.container_size
                if plan.group_id:
                    line.target_group_id = str(plan.group_id).strip()
                if plan.plan_date:
                    line.plan_date = plan.plan_date.isoformat()
                if plan.planned_trailer_plate and not line.trailer_plate:
                    line.trailer_plate = plan.planned_trailer_plate
                plan_eta = extract_plan_expected_time(plan)
                if plan_eta and not line.eta_time:
                    line.eta_time = plan_eta
                    if not line.eta_text:
                        line.eta_text = plan_eta
                    line.field_evidences.setdefault("eta_time", "transport_plan")

                line.match_source = "transport_plan"
                return wh_id, cust_id, False, False, False

        # 2. Tra cứu Khách hàng qua bảng `customers` hoặc `customer_aliases`
        total_cust = db.scalar(select(func.count(Customer.id))) or 0
        if line.customer_hint:
            clean_cust = line.customer_hint.strip().lower()
            from src.parsing.local_nlp_extractor import normalized as _norm_vi
            norm_cust = _norm_vi(line.customer_hint)
            if total_cust > 0:
                direct_custs = list(
                    db.scalars(
                        select(Customer).where(
                            or_(
                                func.lower(Customer.name) == clean_cust,
                                Customer.normalized_name == norm_cust,
                            )
                        )
                    ).all()
                )
                if len(direct_custs) == 1:
                    cust_id = direct_custs[0].id
                    line.customer_code_or_id = direct_custs[0].id
                    match_sources.append("direct_match")
                elif len(direct_custs) > 1:
                    ambiguous = True
                else:
                    alias_cust_ids = list(
                        db.scalars(
                            select(CustomerAlias.customer_id).where(
                                func.lower(CustomerAlias.alias) == clean_cust
                            )
                        ).all()
                    )
                    distinct_alias_cust = sorted(set(alias_cust_ids))
                    if len(distinct_alias_cust) == 1:
                        cust_id = distinct_alias_cust[0]
                        cust_obj = db.get(Customer, cust_id)
                        line.customer_code_or_id = cust_id
                        match_sources.append("customer_alias")
                    elif len(distinct_alias_cust) > 1:
                        ambiguous = True
                    elif isinstance(line.customer_code_or_id, int):
                        cust_id = line.customer_code_or_id
                        match_sources.append("direct_match")
                    else:
                        unmatched_cust = True
        elif cust_id is None and isinstance(line.customer_code_or_id, int):
            cust_id = line.customer_code_or_id

        # 3. Tra cứu Kho qua bảng `warehouses` hoặc `warehouse_aliases`
        total_wh = db.scalar(select(func.count(Warehouse.id))) or 0
        if line.warehouse_hint and total_wh > 0:
            clean_wh = line.warehouse_hint.strip().lower()
            direct_whs = list(
                db.scalars(
                    select(Warehouse).where(func.lower(Warehouse.name) == clean_wh)
                ).all()
            )
            if len(direct_whs) == 1:
                wh_id = direct_whs[0].id
                line.warehouse_code_or_id = direct_whs[0].tms_warehouse_id or direct_whs[0].id
                if "direct_match" not in match_sources:
                    match_sources.append("direct_match")
            elif len(direct_whs) > 1:
                ambiguous = True
            else:
                alias_wh_ids = list(
                    db.scalars(
                        select(WarehouseAlias.warehouse_id).where(
                            func.lower(WarehouseAlias.alias) == clean_wh
                        )
                    ).all()
                )
                distinct_alias_wh = sorted(set(alias_wh_ids))
                if len(distinct_alias_wh) == 1:
                    wh_id = distinct_alias_wh[0]
                    wh_obj = db.get(Warehouse, wh_id)
                    line.warehouse_code_or_id = (wh_obj.tms_warehouse_id if wh_obj else None) or wh_id
                    match_sources.append("warehouse_alias")
                elif len(distinct_alias_wh) > 1:
                    ambiguous = True
                else:
                    unmatched_wh = True

        if "customer_alias" in match_sources:
            line.match_source = "customer_alias"
        elif "warehouse_alias" in match_sources:
            line.match_source = "warehouse_alias"
        elif "direct_match" in match_sources:
            line.match_source = "direct_match"
        else:
            line.match_source = "unmatched"

        return wh_id, cust_id, unmatched_wh, unmatched_cust, ambiguous

    @classmethod
    def _find_target_zalo_group(
        cls,
        db: Session,
        customer_id: Optional[int],
        warehouse_id: Optional[int],
        order_type: Optional[str],
        source_group_id_str: Optional[str] = None,
        plan_group_id_str: Optional[str] = None,
        customer_hint: Optional[str] = None,
    ) -> tuple[int, str]:
        """Xác định nhóm Zalo đích để gửi tin nhắn thông báo cho khách hàng."""
        src_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == source_group_id_str)) if source_group_id_str else None
        is_test_mode = bool(src_grp and src_grp.is_test) or bool(
            source_group_id_str and ("test_" in source_group_id_str or "pytest_" in source_group_id_str)
        )

        # 0. Ưu tiên số 1: Nhóm đích từ Kế hoạch vận chuyển (TransportPlan.group_id)
        if plan_group_id_str:
            clean_plan_grp = str(plan_group_id_str).strip()
            plan_zg = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == clean_plan_grp))
            if plan_zg and (is_test_mode == bool(plan_zg.is_test)):
                return plan_zg.id, plan_zg.zalo_group_id
            if not plan_zg:
                new_plan_zg = ZaloGroup(
                    zalo_group_id=clean_plan_grp,
                    name=f"Nhóm Khách Hàng {clean_plan_grp}",
                    group_role="DESTINATION",
                    send_mode=SendMode.AUTO.value,
                    is_active=True,
                    is_test=is_test_mode,
                )
                db.add(new_plan_zg)
                db.flush()
                return new_plan_zg.id, new_plan_zg.zalo_group_id

        # 1. Tra cứu RouteMap
        if customer_id:
            stmt = (
                select(RouteMap.zalo_group_id, ZaloGroup.zalo_group_id)
                .join(ZaloGroup, RouteMap.zalo_group_id == ZaloGroup.id)
                .where(RouteMap.customer_id == customer_id, RouteMap.is_active == True)
                .order_by(RouteMap.priority.desc())
            )
            if warehouse_id:
                stmt = stmt.where(or_(RouteMap.warehouse_id == warehouse_id, RouteMap.warehouse_id.is_(None)))
            if order_type:
                stmt = stmt.where(or_(RouteMap.order_type == order_type, RouteMap.order_type.is_(None)))
            row = db.execute(stmt).first()
            if row:
                return row[0], row[1]

        # 2. Khớp theo tên khách hàng trong tên nhóm Zalo (ví dụ 'Logitem' -> 'Nhóm Khách Hàng Logitem - Tân Quang')
        if customer_hint:
            clean_hint = customer_hint.strip().lower()
            matching_grp = db.scalar(
                select(ZaloGroup)
                .where(
                    ZaloGroup.group_role.in_(["destination", "customer"]),
                    ZaloGroup.is_active == True,
                    ZaloGroup.is_test == is_test_mode,
                    func.lower(ZaloGroup.name).contains(clean_hint),
                )
                .order_by(ZaloGroup.id.desc())
            )
            if matching_grp:
                return matching_grp.id, matching_grp.zalo_group_id

        # 3. Tìm nhóm Zalo đích có role 'destination' hoặc 'customer' phù hợp chế độ test/thật
        if not is_test_mode:
            main_dest = db.scalar(
                select(ZaloGroup)
                .where(
                    ZaloGroup.zalo_group_id == "6469608867469758994",
                    ZaloGroup.is_active == True,
                )
            )
            if main_dest:
                return main_dest.id, main_dest.zalo_group_id

        dest_grp = db.scalar(
            select(ZaloGroup)
            .where(
                ZaloGroup.group_role.in_(["destination", "customer"]),
                ZaloGroup.is_active == True,
                ZaloGroup.is_test == is_test_mode,
            )
            .order_by(ZaloGroup.id.desc())
        )
        if dest_grp:
            return dest_grp.id, dest_grp.zalo_group_id

        # 4. Nếu chưa có nhóm đích phù hợp, tạo nhóm đích mặc định
        default_gid = f"test_dest_{uuid4().hex[:6]}" if is_test_mode else "6469608867469758994"
        default_grp = db.scalar(select(ZaloGroup).where(ZaloGroup.zalo_group_id == default_gid))
        if not default_grp:
            default_grp = ZaloGroup(
                zalo_group_id=default_gid,
                name="Nhóm Khách Hàng Test" if is_test_mode else "Nhóm Khách Hàng VSICO",
                group_role="DESTINATION",
                send_mode=SendMode.AUTO.value,
                is_active=True,
                is_test=is_test_mode,
            )
            db.add(default_grp)
            db.flush()
        return default_grp.id, default_grp.zalo_group_id

    @classmethod
    def process_message_by_id(cls, db: Session, message_id: int) -> Optional[ZaloMessage]:
        """Xử lý bóc tách toàn diện một tin nhắn theo khóa chính `zalo_messages.id`."""
        # Đảm bảo làm mới trạng thái từ MySQL (tránh cache REPEATABLE READ giữa các phiên)
        db.expire_all()
        message: Optional[ZaloMessage] = db.get(ZaloMessage, message_id)
        if message is None:
            logger.warning("Không tìm thấy tin nhắn ID=%s trong bảng zalo_messages.", message_id)
            return None

        if message.processing_status in (
            MessageStatus.PROCESSED.value,
            MessageStatus.NEEDS_REVIEW.value,
            MessageStatus.IGNORED_CHAT.value,
            MessageStatus.IGNORED_NON_TEXT.value,
            MessageStatus.PROCESSING.value,
        ):
            return message

        # Khóa nguyên tử (Atomic CAS Update) trên MySQL: chỉ xử lý nếu bản ghi đang ở trạng thái received/queued
        claim_stmt = (
            update(ZaloMessage)
            .where(
                ZaloMessage.id == message_id,
                ZaloMessage.processing_status.in_(
                    [MessageStatus.RECEIVED.value, MessageStatus.QUEUED.value]
                ),
            )
            .values(processing_status=MessageStatus.PROCESSING.value)
        )
        claim_res = db.execute(claim_stmt)
        db.commit()
        if claim_res.rowcount == 0:
            db.refresh(message)
            return message

        from src.handlers.conversation_service import route_conversation
        if route_conversation(db, message):
            return message

        # Chống xử lý trùng lặp tuyệt đối (Idempotency): Nếu đã có lần chạy bóc tách thì bỏ qua
        existing_run = db.scalar(
            select(ExtractionRun.id).where(ExtractionRun.message_id == message.id)
        )
        if existing_run is not None:
            logger.info("Tin nhắn ID=%s đã có extraction_run, bỏ qua không tạo lại.", message.id)
            db.refresh(message)
            return message

        start_perf = time.perf_counter()
        started_dt = datetime.now(timezone.utc)
        db.refresh(message)

        # 1. Nhận diện văn bản từ ảnh qua PaddleOCR nếu là tin nhắn ảnh
        from src.infrastructure.ocr.paddle_client import PaddleOCRClient

        raw_text = (message.message_text or "").strip()
        contact_card_text = CarrierFlowService.extract_contact_card_text(message.raw_payload or {})
        if contact_card_text:
            raw_text = f"{raw_text}\n{contact_card_text}".strip() if raw_text else contact_card_text
            message.message_text = raw_text
            db.flush()
        is_image_msg = (
            message.message_type in ("image", "image_ocr")
            or PaddleOCRClient.is_image_payload(message.raw_payload or {})
        )

        ocr_metadata: Optional[dict[str, Any]] = None
        image_placeholders = {
            "[ảnh]", "[hình ảnh]", "[đính kèm]", "[photo]", "[image]",
            "[tệp đính kèm]", "[attachment]", "ảnh", "hình ảnh", "gửi ảnh"
        }
        is_placeholder = raw_text.lower().strip() in image_placeholders if raw_text else False

        has_shipping_info = False
        if raw_text and not is_placeholder:
            has_plate = bool(re.search(r"\d{2}[A-Za-z]\s*[-.]?\s*\d{3,5}", raw_text))
            has_cont = bool(re.search(r"[A-Za-z]{4}\s*\d{7}", raw_text))
            has_shipping_info = has_plate or has_cont

        if is_image_msg and (not raw_text or is_placeholder or not has_shipping_info):
            img_source = PaddleOCRClient._find_image_input(message.raw_payload or {})
            ocr_text, ocr_conf, ocr_boxes = PaddleOCRClient.extract_text_from_payload(message.raw_payload or {})
            CarrierFlowService.record_image_file_metadata(
                db=db,
                message=message,
                payload_dict=message.raw_payload or {},
                image_input=img_source,
                ocr_meta={"provider": settings.OCR_PROVIDER, "confidence": ocr_conf, "boxes_count": len(ocr_boxes)},
            )
            if ocr_text and ocr_text.strip():
                if not raw_text or is_placeholder:
                    raw_text = ocr_text.strip()
                else:
                    raw_text = f"{raw_text.strip()}\n{ocr_text.strip()}"
                message.message_text = raw_text
                message.message_type = "image_ocr"
                ocr_metadata = {
                    "provider": settings.OCR_PROVIDER,
                    "confidence": ocr_conf,
                    "boxes_count": len(ocr_boxes),
                    "extracted_length": len(raw_text),
                }
                updated_payload = dict(message.raw_payload or {})
                updated_payload["ocr_result"] = ocr_metadata
                message.raw_payload = updated_payload
                db.flush()
                logger.info(
                    "Đã bóc tách thành công %d ký tự từ ảnh qua OCR (độ tin cậy: %.2f) cho tin nhắn ID=%s",
                    len(raw_text),
                    ocr_conf,
                    message.id,
                )
            else:
                # Quy tắc nghiệp vụ: Ảnh nào không có text thì bỏ qua
                if not raw_text or is_placeholder:
                    logger.info("Tin nhắn ảnh ID=%s không tách được văn bản nào -> Bỏ qua", message.id)
                    message.processing_status = MessageStatus.IGNORED_NON_TEXT.value
                    db.commit()
                    return message

        # Bỏ qua nếu sau khi xử lý (kể cả qua OCR) vẫn không có văn bản hợp lệ
        if not raw_text:
            message.processing_status = MessageStatus.IGNORED_NON_TEXT.value
            db.commit()
            return message

        # 1b. Xác định ngữ cảnh Nhà xe / Nhóm gửi và kiểm tra nhóm có bị khóa không
        carrier_ctx = CarrierFlowService.resolve_carrier_context(db, message)
        if carrier_ctx.is_blocked_inactive:
            db.add(
                ReviewCase(
                    id=snowflake.generate(),
                    message_id=message.id,
                    case_type="INACTIVE_CARRIER_GROUP",
                    reason=f"Nhóm gửi '{message.group_id}' đang bị tạm khóa hoặc ngưng hoạt động.",
                    details={"group_id": message.group_id, "sender_id": message.sender_id},
                    status=ReviewStatus.PENDING.value,
                )
            )
            CarrierFlowService.alert_dhvt(
                db=db,
                title="NHOM NHA XE BI KHOA GUI TIN",
                body=f"Nhóm {message.group_id} (người gửi {message.sender_id}) gửi tin khi nhóm đang bị vô hiệu hóa.",
                entity_type="zalo_message",
                entity_id=str(message.id),
                is_test_msg=carrier_ctx.is_test_msg,
            )
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            db.refresh(message)
            return message

        prev_dup_id = db.scalar(
            select(ZaloMessage.id).where(
                ZaloMessage.id < message.id,
                ZaloMessage.group_id == message.group_id,
                ZaloMessage.message_text == message.message_text,
            )
        )
        is_duplicate_content = prev_dup_id is not None

        # 2. Bộ lọc 2 tầng (Fast Gatekeeper): Chặn sớm tin nhắn giao tiếp xã giao ('chào', 'hello'...)
        # Ngoại lệ: Nếu người gửi đang có BotReply chờ bổ sung (hoặc đang quote tin trước) và tin không phải xã giao thuần túy -> coi như tin bổ sung.
        intent = IntentClassifier.classify(raw_text)
        if intent == Intent.IGNORE_CHAT and not IntentClassifier._SOCIAL_CHAT_EXACT_REGEX.match(raw_text.strip().lower()):
            has_pending_reply = bool(message.quote_msg_id) or (
                db.scalar(
                    select(BotReply.id)
                    .join(ZaloMessage, BotReply.message_id == ZaloMessage.id)
                    .where(
                        ZaloMessage.group_id == message.group_id,
                        BotReply.sender_id == message.sender_id,
                        BotReply.status.in_([CorrectionStatus.PENDING.value, OutboundStatus.SENT.value]),
                        BotReply.fix_deadline >= datetime.now(timezone.utc),
                    )
                    .limit(1)
                )
                is not None
            )
            if has_pending_reply:
                intent = Intent.SUPPLEMENT
            else:
                # Tin bổ sung muộn dạng mã chì/thực thể ngắn (VD: "VS998877") sau khi đơn đã qua trong 30 phút
                quick_lines = TripParser.parse_message(raw_text)
                if quick_lines and any(
                    ln.seal_no or ln.trailer_plate or ln.driver_phone or ln.container_no or ln.truck_plate
                    for ln in quick_lines
                ):
                    recent_sender_job = db.scalar(
                        select(ContainerJob.id)
                        .join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
                        .where(
                            ZaloMessage.group_id == message.group_id,
                            ZaloMessage.sender_id == message.sender_id,
                            ContainerJob.created_at >= datetime.now(timezone.utc) - timedelta(minutes=30),
                        )
                        .limit(1)
                    )
                    if recent_sender_job is not None:
                        intent = Intent.SUPPLEMENT

        if intent == Intent.IGNORE_CHAT:
            latency_ms = int((time.perf_counter() - start_perf) * 1000)
            taxonomy = MessageTaxonomyAnalyzer.analyze(
                raw_text=raw_text,
                intent=intent,
                lines=[],
                quote_msg_id=message.quote_msg_id,
                is_duplicate_content=is_duplicate_content,
            )
            run = ExtractionRun(
                message_id=message.id,
                model_name="fast-gatekeeper-v2",
                prompt_version="v2.0",
                input_data={"raw_text": raw_text, "group_id": message.group_id},
                output_data={
                    "intent": intent.value,
                    "latency_ms": latency_ms,
                    "taxonomy": taxonomy,
                    "items": [],
                },
                status="ignored_chat",
                started_at=started_dt,
                finished_at=datetime.now(timezone.utc),
            )
            db.add(run)
            message.processing_status = MessageStatus.IGNORED_CHAT.value
            db.commit()
            return message

        # 3. Bóc tách bằng Rule-based (F1, F2, F3, Tự do)
        ref_time = message.created_at or message.zalo_sent_at or message.received_at
        extracted_lines = TripParser.parse_message(raw_text, reference_time=ref_time)
        validated_lines = ContainerValidator.validate_all(extracted_lines)
        used_model_name = "vsico-hybrid-rule-v2"
        used_prompt_version = "v2.0"
        masked_input_for_log: Optional[str] = None

        # Lấy nội dung tin nhắn được trích dẫn (nếu có) để hỗ trợ ngữ cảnh AI và gộp bổ sung
        quoted_text: Optional[str] = None
        if message.quote_msg_id:
            q_reply = db.scalar(select(BotReply).where(BotReply.zalo_msg_id == message.quote_msg_id))
            if q_reply:
                quoted_text = q_reply.reply_text
            else:
                q_msg = db.scalar(select(ZaloMessage).where(ZaloMessage.zalo_message_id == message.quote_msg_id))
                if q_msg:
                    quoted_text = q_msg.message_text

        from src.parsing.local_nlp_extractor import enrich_local, message_dates
        was_ai_candidate = AIFallbackExtractor.should_trigger_ai(validated_lines, intent=intent)
        # Tầng 2 (Local NLP + Danh mục TMS): Chạy khi Tầng 1 chưa đủ độ tin cậy hoặc thiếu ngữ cảnh danh mục
        validated_lines = enrich_local(
            db,
            validated_lines,
            carrier_ctx.numeric_carrier_id,
            raw_text,
            ref_time,
            quoted_text,
            group_id=message.group_id,
            sender_id=message.sender_id,
            include_phobert=was_ai_candidate,
        )
        # Tra cứu danh mục rơ-moóc (`trailers`) ngay trong Tầng 2 để chuẩn hóa moóc trước khi xét gọi Tầng 3 LLM
        for ln in validated_lines:
            ln.carrier_id = carrier_ctx.numeric_carrier_id
            resolve_trailer_from_catalog(db, ln, carrier_ctx.numeric_carrier_id)
        # Thẩm định lại sau khi Tầng 2 làm giàu dữ liệu từ danh mục TMS (cập nhật validation_status & confidence)
        validated_lines = ContainerValidator.validate_all(validated_lines)
        if was_ai_candidate:
            used_model_name = (
                validated_lines[0].field_evidences.get("nlp_engine")
                if validated_lines and validated_lines[0].field_evidences.get("nlp_engine")
                else "local-nlp-catalog-v2"
            )
        for line in validated_lines:
            line.candidate_dates = message_dates(raw_text, ref_time)

        # 4. Cơ chế AI / LLM Extraction qua `ai-service` (Rule-first: chỉ gọi AI khi Rule-based thiếu/mơ hồ)
        has_any_rule_entity = any(
            ln.container_no
            or ln.truck_plate
            or ln.seal_no
            or ln.driver_phone
            or ln.driver_name
            or ln.eta_time
            for ln in validated_lines
        )
        should_ai = AIFallbackExtractor.should_trigger_ai(validated_lines, intent=intent)
        deferred_only = bool(validated_lines) and all(
            (ln.container_status == "DEFERRED" or ln.seal_status == "DEFERRED")
            and ln.truck_plate and not ln.unresolved_fields for ln in validated_lines)
        need_ai_context = (should_ai or (bool(quoted_text) and not has_any_rule_entity)) and not deferred_only
        if need_ai_context:
            active_plans = CarrierFlowService.load_active_plans_for_ai(db, raw_text, carrier_ctx.numeric_carrier_id)
            ai_lines, ai_res = AIFallbackExtractor.extract_with_ai_context(
                raw_text=raw_text,
                reference_time=ref_time,
                sender_id=message.sender_id,
                group_id=message.group_id,
                carrier_id=carrier_ctx.numeric_carrier_id,
                quote_message=quoted_text,
                active_plans=active_plans,
                message_type=message.message_type or "text",
            )
            if ai_res is not None:
                used_prompt_version = ai_res.prompt_version
                masked_input_for_log = ai_res.raw_masked_text
                # Tinh chỉnh intent theo phân tích ngữ cảnh từ `ai-service` nếu phù hợp
                if intent == Intent.PARSE_TRUCK_INFO and ai_res.intent in ("UPDATE_REQUEST", "SUPPLEMENT", "CANCEL_REQUEST"):
                    intent = Intent(ai_res.intent)
            if ai_lines and (should_ai or not has_any_rule_entity):
                is_offline_heuristic = bool(
                    ai_res and ai_res.model_name in ("rule_offline_fallback", "local-heuristic-v1")
                )
                if len(validated_lines) == 1 and len(ai_lines) == 1:
                    base_ln = validated_lines[0]
                    ai_ln = ai_lines[0]
                    for attr in (
                        "truck_plate",
                        "trailer_plate",
                        "driver_name",
                        "driver_phone",
                        "container_no",
                        "container_size",
                        "seal_no",
                        "order_type",
                        "customer_hint",
                        "warehouse_hint",
                        "eta_text",
                        "eta_time",
                        "estimated_at",
                    ):
                        if not getattr(base_ln, attr, None) and getattr(ai_ln, attr, None):
                            setattr(base_ln, attr, getattr(ai_ln, attr))
                    validated_lines = ContainerValidator.validate_all([base_ln])
                    used_model_name = ai_res.model_name if ai_res else f"ai-fallback:{settings.AI_PROVIDER}:{settings.AI_MODEL_NAME}"
                elif not (
                    is_offline_heuristic
                    and len(validated_lines) == 1
                    and validated_lines[0].truck_plate
                    and validated_lines[0].container_no
                ):
                    validated_lines = ContainerValidator.validate_all(ai_lines)
                    used_model_name = ai_res.model_name if ai_res else f"ai-fallback:{settings.AI_PROVIDER}:{settings.AI_MODEL_NAME}"

        for line in validated_lines:
            line.carrier_id = carrier_ctx.numeric_carrier_id

        # Tra cứu danh mục rơ-moóc (`trailers`) để chuẩn hóa mooc & tránh nhận nhầm mooc không mang chữ R/RM thành đầu kéo
        for idx_ln, ln in enumerate(validated_lines):
            if resolve_trailer_from_catalog(db, ln, carrier_ctx.numeric_carrier_id):
                validated_lines[idx_ln] = ContainerValidator.validate_line(ln)

        # Ca đóng chưa có cont hoặc tham chiếu chưa rõ đi qua bộ đề xuất an toàn.
        from dataclasses import asdict
        from src.handlers.plan_resolution_engine import PlanResolutionEngine, order_kind
        complex_lines = [ln for ln in validated_lines if ln.unresolved_fields or
                         (order_kind(ln.order_type) == "LO" and not ln.container_no)]
        if complex_lines and carrier_ctx.numeric_carrier_id:
            dates = message_dates(raw_text, ref_time)
            from datetime import date
            scoped = list(db.scalars(select(TransportPlan).where(
                TransportPlan.plan_date.in_([date.fromisoformat(d) for d in dates]),
                or_(TransportPlan.carrier_id == carrier_ctx.numeric_carrier_id, TransportPlan.carrier_id.is_(None)),
            )).all())
            resolutions = PlanResolutionEngine.resolve_batch(
                complex_lines, scoped, carrier_ctx.numeric_carrier_id, dates
            )
            for ln, resolution in zip(complex_lines, resolutions):
                res_dict = asdict(resolution)
                db.add(ReviewCase(message_id=message.id, case_type="PLAN_RESOLUTION",
                                  reason=resolution.reason, status="PENDING",
                                  details={"resolution": res_dict,
                                           "candidate_plans": res_dict.get("candidates", []),
                                           "selected_plan_id": resolution.selected_plan_id,
                                           "secondary_plan_id": resolution.secondary_plan_id,
                                           "tier": ln.extraction_tier,
                                           "field_evidences": ln.field_evidences,
                                           "unresolved_fields": ln.unresolved_fields}))
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            return message

        # 4b. Xử lý nhanh các nhánh đặc biệt theo luồng Bot - Nhà xe (Hủy / Bổ sung / Sửa đổi xe / Debounce 60s / Xác nhận OCR)
        if intent == Intent.CANCEL_REQUEST:
            return CarrierFlowService.handle_cancel_request(db, message, validated_lines, carrier_ctx)

        # OCR xác nhận nhanh 5 trường cho ảnh từ nhà xe thật (trong pytest chỉ bật khi truyền enable_ocr_confirm=True)
        in_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
        ocr_confirm_enabled = (
            bool((message.raw_payload or {}).get("enable_ocr_confirm"))
            if (carrier_ctx.is_test_msg or in_pytest)
            else True
        )
        if message.message_type == "image_ocr" and len(validated_lines) == 1 and ocr_confirm_enabled:
            return CarrierFlowService.create_ocr_confirmation_draft(db, message, validated_lines[0], carrier_ctx)

        if intent == Intent.SUPPLEMENT or message.quote_msg_id or any(
            not (ln.truck_plate and ln.trailer_plate and ln.container_no and ln.driver_name) for ln in validated_lines
        ):
            supp_job, supp_reply = CarrierFlowService.find_pending_supplement_target(db, message, validated_lines)
            if supp_job is not None and intent != Intent.UPDATE_REQUEST:
                incoming_line = validated_lines[0] if validated_lines else ExtractedContainerLine(line_text=raw_text)
                return CarrierFlowService.process_supplement_into_job(
                    db=db,
                    message=message,
                    target_job=supp_job,
                    matched_reply=supp_reply,
                    incoming_line=incoming_line,
                    carrier_ctx=carrier_ctx,
                    enrich_fn=cls._enrich_from_catalog_and_plans,
                )

        # Bộ gom tin rời rạc 60 giây (Smart Debounce): đệm tin thiếu trường để gộp tin liên tiếp cùng người gửi
        if intent in (Intent.PARSE_TRUCK_INFO, Intent.SUPPLEMENT) and not message.quote_msg_id:
            buf_status, buf_lines = CarrierFlowService.buffer_or_merge_carrier_fragment(
                db=db,
                message=message,
                lines=validated_lines,
                carrier_ctx=carrier_ctx,
            )
            if buf_status == "BUFFERED":
                db.refresh(message)
                return message
            if buf_status == "MERGED_READY" and buf_lines:
                validated_lines = buf_lines
                for idx_ln, ln in enumerate(validated_lines):
                    resolve_trailer_from_catalog(db, ln, carrier_ctx.numeric_carrier_id)
                    validated_lines[idx_ln] = ContainerValidator.validate_line(ln)

        if intent == Intent.SUPPLEMENT:
            db.add(BotReply(message_id=message.id, sender_id=message.sender_id,
                            reply_text="Chưa xác định duy nhất chuyến cần bổ sung. Vui lòng quote đúng tin và ghi số container hoặc biển số xe.",
                            status=CorrectionStatus.PENDING.value,
                            fix_deadline=datetime.now(timezone.utc) + timedelta(minutes=30)))
            db.add(ReviewCase(message_id=message.id, case_type="AMBIGUOUS_SUPPLEMENT",
                              reason="Tin bổ sung chưa xác định được duy nhất chuyến trong nhóm.", status="PENDING"))
            message.processing_status = MessageStatus.NEEDS_REVIEW.value
            db.commit()
            return message

        if intent == Intent.UPDATE_REQUEST or (
            message.quote_msg_id
            and len(validated_lines) == 1
            and not validated_lines[0].container_no
            and CarrierFlowService.resolve_job_from_quoted_message(db, message.group_id, message.quote_msg_id) is not None
        ):
            upd_res = CarrierFlowService.handle_update_request(
                db=db,
                message=message,
                lines=validated_lines,
                carrier_ctx=carrier_ctx,
                enrich_fn=cls._enrich_from_catalog_and_plans,
            )
            if upd_res is not None:
                return upd_res

        # 5. Tra cứu danh mục (Customer / Alias / Warehouse / TransportPlan / AI Warehouse Matching)
        any_unmatched_wh = False
        any_unmatched_cust = False
        any_ambiguous = False
        line_catalog_map: dict[int, tuple[Optional[int], Optional[int]]] = {}

        for idx, line in enumerate(validated_lines):
            wh_id, cust_id, u_wh, u_cust, amb = cls._enrich_from_catalog_and_plans(db, line)
            if not wh_id and line.warehouse_hint:
                ai_wh_id = CarrierFlowService.match_warehouse_via_ai_if_needed(db, line, carrier_ctx, cust_id)
                if ai_wh_id:
                    wh_id = ai_wh_id
                    u_wh = False
            line_catalog_map[idx] = (wh_id, cust_id)
            if u_wh:
                any_unmatched_wh = True
            if u_cust:
                any_unmatched_cust = True
            if amb:
                any_ambiguous = True

        # 6. Phân tích Taxonomy Bảng 1 (1.1->1.6) và Bảng 2 (T01->T40)
        taxonomy = MessageTaxonomyAnalyzer.analyze(
            raw_text=raw_text,
            intent=intent,
            lines=validated_lines,
            quote_msg_id=message.quote_msg_id,
            is_duplicate_content=is_duplicate_content,
            unmatched_warehouse=any_unmatched_wh,
            unmatched_customer=any_unmatched_cust,
            ambiguous_route_match=any_ambiguous,
        )

        latency_ms = int((time.perf_counter() - start_perf) * 1000)
        avg_confidence = (
            round(sum(ln.confidence for ln in validated_lines) / len(validated_lines), 2)
            if validated_lines
            else 0.0
        )

        # 7. Lưu lịch sử chạy bóc tách vào bảng `extraction_runs`
        extraction_run = ExtractionRun(
            message_id=message.id,
            model_name=used_model_name,
            prompt_version=used_prompt_version,
            input_data={
                "raw_text": masked_input_for_log or raw_text,
                "group_id": message.group_id,
                "sender_id": message.sender_id,
                **({"ocr": ocr_metadata} if ocr_metadata else {}),
            },
            output_data={
                "intent": intent.value,
                "confidence": avg_confidence,
                "latency_ms": latency_ms,
                "taxonomy": taxonomy,
                "item_count": len(validated_lines),
                "canonical_records": [ln.to_canonical_record() for ln in validated_lines],
                "items": [ln.to_dict() for ln in validated_lines],
            },
            status="success",
            started_at=started_dt,
            finished_at=datetime.now(timezone.utc),
        )
        db.add(extraction_run)
        db.flush()

        # 8. Lưu từng xe (`truck_records`) và từng container (`container_jobs`)
        truck_cache: dict[tuple[Optional[str], Optional[str], Optional[str], Optional[str]], TruckRecord] = {}
        has_review_or_error = False
        source_grp = carrier_ctx.source_group
        source_mode = (
            SendMode(source_grp.send_mode).value
            if source_grp and source_grp.send_mode
            else SendMode.AUTO.value
        )
        is_auto_group = source_mode == SendMode.AUTO.value
        target_carrier_group = message.group_id
        is_test_msg = carrier_ctx.is_test_msg
        _dhvt_batch_token, _dhvt_batch_bucket = DhvtNotificationService.begin_alert_batch()

        for idx, line in enumerate(validated_lines):
            truck_key = (
                line.truck_plate,
                line.trailer_plate,
                line.driver_name,
                line.driver_phone,
            )
            truck_record = truck_cache.get(truck_key)
            if truck_record is None:
                truck_record = TruckRecord(
                    message_id=message.id,
                    extraction_run_id=extraction_run.id,
                    truck_plate=line.truck_plate,
                    trailer_plate=line.trailer_plate,
                    driver_name=line.driver_name,
                    driver_phone=line.driver_phone,
                    raw_data={
                        "plate_compact": line.plate_compact,
                        "raw_truck_plate": line.raw_truck_plate,
                        "eta_text": line.eta_text,
                        "eta": line.eta_time,
                        "estimated_at": line.estimated_at.isoformat() if line.estimated_at else None,
                        "note": line.note,
                        "status": "active",
                    },
                )
                db.add(truck_record)
                db.flush()
                truck_cache[truck_key] = truck_record

            wh_id, cust_id = line_catalog_map.get(idx, (None, None))
            cust_obj = db.get(Customer, cust_id) if cust_id else None
            wh_obj = db.get(Warehouse, wh_id) if wh_id else None

            # Thẩm định tính đầy đủ của 8 trường cốt lõi theo quy định:
            # 1. Khách hàng, 2. Lệnh, 3. Xe, 4. Tài xế, 5. SĐT, 6. Cont, 7. Size, 8. Chì
            # (Giờ dự kiến và Ghi chú là tùy chọn - có thể null)
            is_complete, missing_fields = OutboundTemplateBuilder.check_core_fields_completeness(line)
            if not is_complete:
                line.validation_status = ValidationStatus.NEEDS_REVIEW.value
                for m in missing_fields:
                    w_code = f"MISSING_{m.upper()}"
                    if w_code not in line.warnings:
                        line.warnings.append(f"Thiếu/sai: {m}")

            # 0. Đánh giá thời hạn gửi tin (Timing / Timeliness check)
            timing_status, timing_desc = OutboundTemplateBuilder.evaluate_timing_deadline(
                order_type=line.order_type,
                eta_raw=line.eta_time or line.estimated_at or line.eta_text or line.warehouse_hint or line.line_text,
                message_time=message.zalo_sent_at or message.received_at,
                plan_date_str=line.plan_date,
            )
            if (
                timing_status in ("late_warning", "overdue_warning")
                and line.field_evidences.get("eta_time") != "transport_plan"
            ):
                if timing_desc not in line.warnings:
                    line.warnings.append(timing_desc)

            container_job = ContainerJob(
                message_id=message.id,
                truck_record_id=truck_record.id,
                is_update=(intent in (Intent.UPDATE_REQUEST, Intent.SUPPLEMENT)),
                line_no=line.line_no,
                line_text=line.line_text,
                container_no=line.container_no,
                container_size=line.canonical_cont_size or line.container_size,
                seal_no=line.seal_no,
                order_type=line.order_type,
                warehouse_hint=line.warehouse_hint,
                customer_hint=line.customer_hint,
                warehouse_id=wh_id,
                customer_id=cust_id,
                match_method=line.match_source,
                ai_confidence=Decimal(str(round(line.confidence, 3))),
                estimated_at=line.estimated_at,
                note=line.note,
                container_check_digit_valid=line.check_digit_valid,
                validation_status=line.validation_status,
                routing_status=RoutingStatus.PENDING.value,
                tms_sync_status=TmsSyncStatus.NOT_STARTED.value,
                raw_fields={
                    "transport_plan_id": line.transport_plan_id,
                    "extraction_tier": line.extraction_tier,
                    "field_evidences": line.field_evidences,
                    "unresolved_fields": line.unresolved_fields,
                    "source_format": line.source_format,
                    "plan_date": line.plan_date,
                    "eta": line.eta_time,
                    "eta_text": line.eta_text,
                    "booking_no": line.booking_no,
                    "match_source": line.match_source,
                    "warnings": line.warnings,
                    "timing_check": {
                        "status": timing_status,
                        "description": timing_desc,
                    },
                    "canonical_record": line.to_canonical_record(),
                    "taxonomy": taxonomy,
                },
            )
            db.add(container_job)
            db.flush()

            # 1. Kiểm tra đối chiếu xem đúng chặng/kế hoạch của cont này đã từng gửi thành công cho khách chưa
            prev_sent_job = None
            if line.container_no:
                def _leg_kind(val: Optional[str]) -> Optional[str]:
                    v = (val or "").strip().lower()
                    if v in ("load", "dong", "lo", "xuat"):
                        return "LOAD"
                    if v in ("return", "tra", "ro", "nhap"):
                        return "RETURN"
                    return None

                curr_leg = _leg_kind(line.order_type)
                recent_sent_jobs = (
                    db.query(ContainerJob)
                    .join(OutboundMessageItem, OutboundMessageItem.container_job_id == ContainerJob.id)
                    .join(OutboundMessage, OutboundMessage.id == OutboundMessageItem.outbound_message_id)
                    .filter(
                        ContainerJob.container_no == line.container_no,
                        OutboundMessage.status.in_([OutboundStatus.SENT.value, "da_gui"]),
                        ContainerJob.id != container_job.id,
                    )
                    .order_by(ContainerJob.id.desc())
                    .limit(10)
                    .all()
                )
                for candidate_prev in recent_sent_jobs:
                    prev_raw = candidate_prev.raw_fields if isinstance(candidate_prev.raw_fields, dict) else {}
                    prev_pid = prev_raw.get("transport_plan_id")
                    if line.transport_plan_id and prev_pid:
                        try:
                            if int(prev_pid) != int(line.transport_plan_id):
                                continue
                        except (TypeError, ValueError):
                            pass
                    prev_leg = _leg_kind(candidate_prev.order_type)
                    if curr_leg and prev_leg and curr_leg != prev_leg:
                        continue
                    prev_sent_job = candidate_prev
                    break

            is_duplicate = False
            is_update = False
            changes_list: list[str] = []
            message_kind = "initial"

            if prev_sent_job and prev_sent_job.truck_record:
                prev_tr = prev_sent_job.truck_record
                prev_norm_plate = compact_plate(prev_tr.truck_plate) or ""
                curr_norm_plate = compact_plate(line.truck_plate or line.plate_compact or line.raw_truck_plate) or ""
                prev_norm_trailer = compact_plate(prev_tr.trailer_plate) or ""
                curr_norm_trailer = compact_plate(line.trailer_plate) or ""
                prev_norm_driver = " ".join((prev_tr.driver_name or "").lower().split())
                curr_norm_driver = " ".join((line.driver_name or "").lower().split())
                prev_norm_phone = re.sub(r"\D", "", prev_tr.driver_phone or "")
                curr_norm_phone = re.sub(r"\D", "", line.driver_phone or "")
                prev_norm_seal = re.sub(r"[^A-Za-z0-9]", "", prev_sent_job.seal_no or "").upper()
                curr_norm_seal = re.sub(r"[^A-Za-z0-9]", "", line.seal_no or "").upper()

                if (
                    prev_norm_plate == curr_norm_plate
                    and prev_norm_trailer == curr_norm_trailer
                    and prev_norm_driver == curr_norm_driver
                    and prev_norm_phone == curr_norm_phone
                    and prev_norm_seal == curr_norm_seal
                ):
                    # Toàn bộ thông tin không đổi -> Bỏ qua gửi trùng (tránh làm phiền khách)
                    is_duplicate = True
                    message_kind = "duplicate"
                else:
                    # Có thay đổi xe / rơ-moóc / lái xe / số chì -> Gửi thông báo CẬP NHẬT
                    is_update = True
                    message_kind = "update"
                    container_job.is_update = True
                    container_job.parent_job_id = prev_sent_job.id
                    prev_plate_disp = (prev_tr.truck_plate or "").strip()
                    curr_plate_disp = (line.truck_plate or line.plate_compact or "").strip()
                    if prev_norm_plate != curr_norm_plate:
                        changes_list.append(f"- Biển số xe: {prev_plate_disp or 'Chưa có'} -> {curr_plate_disp}")
                    if prev_norm_trailer != curr_norm_trailer and line.trailer_plate:
                        changes_list.append(f"- Biển số rơ-moóc: {(prev_tr.trailer_plate or 'Chưa có')} -> {line.trailer_plate}")
                    if prev_norm_driver != curr_norm_driver:
                        changes_list.append(f"- Lái xe: {prev_tr.driver_name or 'Chưa có'} -> {line.driver_name}")
                    if prev_norm_phone != curr_norm_phone:
                        changes_list.append(f"- SĐT: {prev_tr.driver_phone or 'Chưa có'} -> {line.driver_phone}")
                    if prev_norm_seal != curr_norm_seal:
                        changes_list.append(f"- Số chì: {prev_sent_job.seal_no or 'Chưa có'} -> {line.seal_no}")

            # 2. Tạo nội dung thông báo gửi khách hàng (Initial hoặc Update)
            cust_name = cust_obj.name if cust_obj else (line.customer_hint or "Quý khách hàng")
            wh_name = wh_obj.name if wh_obj else (line.warehouse_hint or "Kho khách hàng")
            cust_tms_code = cust_obj.tms_customer_id if cust_obj else None

            if is_update and changes_list:
                notification_text = OutboundTemplateBuilder.build_update_notification(
                    line=line,
                    changes_list=changes_list,
                    customer_name=cust_name,
                    warehouse_name=wh_name,
                    customer_id=cust_tms_code,
                )
            else:
                notification_text = OutboundTemplateBuilder.build_customer_notification(
                    line=line,
                    customer_name=cust_name,
                    warehouse_name=wh_name,
                    customer_id=cust_tms_code,
                )

            wh_id, cust_id = line_catalog_map.get(idx, (None, None))

            # Kiểm tra cặp lệnh kết hợp (RO + LO) dùng chung 1 số container (Hạng mục 3)
            comb_ro_plan, comb_lo_plan, comb_ro_has_info = CarrierFlowService.detect_combined_ro_lo_pair(
                db, line, carrier_ctx
            )
            if comb_ro_plan is not None and comb_lo_plan is not None and is_complete and line.validation_status == ValidationStatus.VALID.value:
                # Kiểm tra thêm xem lệnh trả (RO) đã từng phát hành SENT chưa (nếu đã SENT thì coi như xong Lần 1)
                ro_already_sent = (
                    db.scalar(
                        select(OutboundMessage.id)
                        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
                        .join(ContainerJob, OutboundMessageItem.container_job_id == ContainerJob.id)
                        .where(
                            ContainerJob.container_no == line.container_no,
                            OutboundMessage.status.in_([OutboundStatus.SENT.value, "da_gui"]),
                            ContainerJob.order_type.in_(["RETURN", "tra", "return", "ro"]),
                        )
                        .limit(1)
                    )
                    is not None
                )
                lo_already_sent = (
                    db.scalar(
                        select(OutboundMessage.id)
                        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
                        .join(ContainerJob, OutboundMessageItem.container_job_id == ContainerJob.id)
                        .where(
                            ContainerJob.container_no == line.container_no,
                            OutboundMessage.status.in_([OutboundStatus.SENT.value, "da_gui"]),
                            ContainerJob.order_type.in_(["LOAD", "dong", "load", "lo"]),
                        )
                        .limit(1)
                    )
                    is not None
                )
                effective_ro_done = comb_ro_has_info or ro_already_sent
                src_grp_name = (
                    (source_grp.name if source_grp and source_grp.name else None)
                    or message.group_id
                )
                carrier_obj_c = (
                    db.get(Carrier, carrier_ctx.numeric_carrier_id)
                    if carrier_ctx.numeric_carrier_id
                    else None
                )
                carrier_disp_c = (
                    carrier_obj_c.name if carrier_obj_c else (source_grp.carrier_name if source_grp else None)
                )
                comb_tgt_gid, comb_tgt_zalo_gid = CarrierFlowService.find_target_zalo_group_safe(
                    db=db,
                    customer_id=comb_ro_plan.customer_id or cust_id,
                    warehouse_id=comb_ro_plan.warehouse_id or wh_id,
                    order_type=OrderType.RETURN.value,
                    source_group_id_str=message.group_id,
                    plan_group_id_str=comb_ro_plan.group_id or line.target_group_id,
                    customer_hint=comb_ro_plan.customer_name or line.customer_hint,
                )
                comb_tgt_grp = db.get(ZaloGroup, comb_tgt_gid) if comb_tgt_gid else None
                comb_lo_tgt_gid, _ = CarrierFlowService.find_target_zalo_group_safe(
                    db=db,
                    customer_id=comb_lo_plan.customer_id or cust_id,
                    warehouse_id=comb_lo_plan.warehouse_id or wh_id,
                    order_type=OrderType.LOAD.value,
                    source_group_id_str=message.group_id,
                    plan_group_id_str=comb_lo_plan.group_id or line.target_group_id,
                    customer_hint=comb_lo_plan.customer_name or line.customer_hint,
                )
                comb_lo_tgt_grp = db.get(ZaloGroup, comb_lo_tgt_gid) if comb_lo_tgt_gid else None
                # Bất cứ nhóm nào liên quan (nhóm nhà xe SOURCE hoặc nhóm khách hàng RO/LO) ở chế độ MANUAL
                # đều BẮT BUỘC đưa cả lệnh kết hợp (RO + LO) sang ĐHVT duyệt, kể cả khi lệnh trả đã đủ 4-5 trường.
                is_comb_manual = (
                    CarrierFlowService.is_manual_approval_required(source_grp, comb_tgt_grp)
                    or CarrierFlowService.is_manual_approval_required(None, comb_lo_tgt_grp)
                )
                is_comb_auto = not is_comb_manual

                if not effective_ro_done:
                    # Lần 1: Lệnh trả (RO) chưa có thông tin xe trên TMS
                    container_job.order_type = OrderType.RETURN.value
                    container_job.validation_status = ValidationStatus.VALID.value
                    line.order_type = OrderType.RETURN.value
                    line.transport_plan_id = comb_ro_plan.id
                    cur_r = dict(container_job.raw_fields or {})
                    cur_r["transport_plan_id"] = comb_ro_plan.id
                    container_job.raw_fields = cur_r

                    if not is_comb_auto:
                        # Nhóm MANUAL -> gửi thông báo cả 2 lệnh (RO + LO) tới nhóm ĐHVT duyệt 1 lần
                        has_review_or_error = True
                        container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                        comb_outbound_id: Optional[int] = None
                        if comb_tgt_gid:
                            ro_notif = OutboundTemplateBuilder.build_customer_notification(
                                line=line,
                                customer_name=comb_ro_plan.customer_name or cust_name,
                                warehouse_name=comb_ro_plan.warehouse_name or comb_ro_plan.delivery_address or wh_name,
                                plan_date=comb_ro_plan.plan_date,
                            )
                            comb_om = OutboundMessage(
                                target_group_id=comb_tgt_gid,
                                order_type=OrderType.RETURN.value,
                                message_kind="initial",
                                content=ro_notif,
                                idempotency_key=f"outbound:{message.id}:{idx}:combined_manual",
                                status=OutboundStatus.PENDING_APPROVAL.value,
                                attempt_count=0,
                                last_error=f"Lệnh kết hợp ({comb_ro_plan.order_code} + {comb_lo_plan.order_code}) chờ ĐHVT duyệt.",
                            )
                            db.add(comb_om)
                            db.flush()
                            db.add(OutboundMessageItem(outbound_message_id=comb_om.id, container_job_id=container_job.id))
                            comb_outbound_id = comb_om.id

                        comb_details = {
                            **line.to_dict(),
                            "selected_plan_id": str(comb_lo_plan.id),
                            "secondary_plan_id": str(comb_ro_plan.id),
                            "ro_order_code": comb_ro_plan.order_code,
                            "lo_order_code": comb_lo_plan.order_code,
                            "source_group_name": src_grp_name,
                            "sender_name": message.sender_name,
                            "carrier_name": carrier_disp_c,
                            **({"outbound_message_id": str(comb_outbound_id)} if comb_outbound_id else {}),
                        }
                        DhvtNotificationService.create_or_merge_review_case(
                            db=db,
                            message_id=message.id,
                            case_type="COMBINED_RO_LO_REVIEW",
                            reason=(
                                f"Lệnh kết hợp (Lệnh trả {comb_ro_plan.order_code or comb_ro_plan.id} chưa có xe trên TMS "
                                f"+ Lệnh đóng {comb_lo_plan.order_code or comb_lo_plan.id}) từ nhóm {src_grp_name} cần ĐHVT duyệt."
                            ),
                            container_job_id=container_job.id,
                            container_no=line.container_no,
                            carrier_name=carrier_disp_c,
                            details=comb_details,
                            suggestion="Trả lời 'duyệt' trên Zalo ĐHVT hoặc bấm Duyệt trên Web để cập nhật cả 2 lệnh lên TMS.",
                            priority="HIGH",
                            is_test_msg=is_test_msg,
                            notify_zalo=True,
                        )
                        continue
                    else:
                        # Nhóm AUTO: Lệnh trả (RO) đủ 5 trường -> tự cập nhật TMS ngay; Lệnh đóng (LO) gửi tin xác nhận về Nhà xe
                        from src.handlers.plan_sync_service import sync_job_to_local_plan, sync_plan_to_tms

                        ro_out = sync_job_to_local_plan(
                            db=db,
                            job=container_job,
                            plan=comb_ro_plan,
                            allow_plan_override=False,
                            actor_id="vsico_bot",
                        )
                        if ro_out.mode in ("FILLED", "UPDATED"):
                            sync_plan_to_tms(
                                db=db,
                                plan=comb_ro_plan,
                                job=container_job,
                                changed_fields=ro_out.changed_fields,
                                before_values=ro_out.before_values,
                                allow_container_override=False,
                            )
                        if comb_tgt_gid:
                            ro_notif = OutboundTemplateBuilder.build_customer_notification(
                                line=line,
                                customer_name=comb_ro_plan.customer_name or cust_name,
                                warehouse_name=comb_ro_plan.warehouse_name or comb_ro_plan.delivery_address or wh_name,
                                plan_date=comb_ro_plan.plan_date,
                            )
                            comb_om_auto = OutboundMessage(
                                target_group_id=comb_tgt_gid,
                                order_type=OrderType.RETURN.value,
                                message_kind="initial",
                                content=ro_notif,
                                idempotency_key=f"outbound:{message.id}:{idx}:combined_ro_auto",
                                status=OutboundStatus.PENDING_SEND.value,
                                attempt_count=0,
                            )
                            db.add(comb_om_auto)
                            db.flush()
                            db.add(OutboundMessageItem(outbound_message_id=comb_om_auto.id, container_job_id=container_job.id))

                        # Kiểm tra cảnh báo cấm ghép vỏ trên lệnh trả
                        is_blocked_shell = bool(
                            comb_ro_plan.container_ownership == 2
                            or comb_ro_plan.container_warning
                            in ("empty_drop", "other_requested", "soc", "over_combined")
                        )
                        if is_blocked_shell:
                            has_review_or_error = True
                            container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                            warn_vi_map = {
                                "empty_drop": "chỉ định hạ rỗng (không tự ghép đóng hàng)",
                                "over_combined": "vượt số lượng ghép kết hợp",
                                "other_requested": "đã được đơn vị khác đăng ký",
                                "soc": "vỏ thuộc sở hữu chủ hàng",
                            }
                            warn_vi = warn_vi_map.get(
                                str(comb_ro_plan.container_warning or ("soc" if comb_ro_plan.container_ownership == 2 else "")).lower(),
                                "cảnh báo cấm ghép vỏ trả",
                            )
                            DhvtNotificationService.create_or_merge_review_case(
                                db=db,
                                message_id=message.id,
                                case_type="COMBINED_RO_LO_REVIEW",
                                reason=(
                                    f"Đã tự cập nhật lệnh trả {comb_ro_plan.order_code}. Vỏ {line.container_no} đang có "
                                    f"{warn_vi}; cần ĐHVT xác nhận trước khi ghép sang lệnh đóng {comb_lo_plan.order_code}."
                                ),
                                container_job_id=container_job.id,
                                container_no=line.container_no,
                                carrier_name=carrier_disp_c,
                                details={
                                    **line.to_dict(),
                                    "selected_plan_id": str(comb_lo_plan.id),
                                    "secondary_plan_id": str(comb_ro_plan.id),
                                    "ro_order_code": comb_ro_plan.order_code,
                                    "lo_order_code": comb_lo_plan.order_code,
                                    "source_group_name": src_grp_name,
                                },
                                priority="HIGH",
                                is_test_msg=is_test_msg,
                                notify_zalo=True,
                            )
                            continue

                        # Tạo bản nháp chờ nhà xe xác nhận lệnh đóng kết hợp LO và gửi tin hỏi xác nhận về Nhà xe
                        from src.domain.enums import MessageDraftStatus
                        from src.infrastructure.models import MessageDraft

                        confirm_lo_text = OutboundTemplateBuilder.build_combined_lo_confirm_reply(
                            container_no=line.container_no or "",
                            ro_order_code=comb_ro_plan.order_code,
                            lo_order_code=comb_lo_plan.order_code,
                            truck_plate=line.truck_plate,
                            lo_warehouse=comb_lo_plan.warehouse_name or comb_lo_plan.delivery_address,
                        )
                        if source_grp is not None:
                            db.add(
                                MessageDraft(
                                    id=snowflake.generate(),
                                    zalo_info_id=source_grp.id,
                                    group_id=message.group_id,
                                    sender_id=message.sender_id,
                                    carrier_id=carrier_ctx.numeric_carrier_id,
                                    first_message_id=message.id,
                                    last_message_id=message.id,
                                    message_count=1,
                                    status=MessageDraftStatus.WAITING_REPLY.value,
                                    entities={
                                        "kind": "combined_lo_confirm",
                                        "ro_plan_id": str(comb_ro_plan.id),
                                        "lo_plan_id": str(comb_lo_plan.id),
                                        "ro_order_code": comb_ro_plan.order_code,
                                        "lo_order_code": comb_lo_plan.order_code,
                                        "container_job_id": str(container_job.id),
                                        "container_no": line.container_no,
                                        "version": comb_lo_plan.version,
                                    },
                                    expires_at=datetime.now() + timedelta(minutes=60),
                                )
                            )
                        lo_reply = BotReply(
                            id=snowflake.generate(),
                            message_id=message.id,
                            sender_id=message.sender_id,
                            reply_text=confirm_lo_text,
                            fix_deadline=datetime.now(timezone.utc) + timedelta(minutes=60),
                            status=CorrectionStatus.PENDING.value,
                        )
                        db.add(lo_reply)
                        db.flush()
                        if CarrierFlowService._is_dispatchable_real_group(message.group_id, source_grp, is_test_msg):
                            ok_lo, mid_lo, _ = ZaloDispatcher.send_to_group(
                                group_id=message.group_id,
                                message=confirm_lo_text,
                                quote_msg_id=message.zalo_message_id,
                            )
                            if ok_lo and mid_lo:
                                lo_reply.zalo_msg_id = mid_lo
                                lo_reply.sent_at = datetime.now(timezone.utc)
                        container_job.routing_status = RoutingStatus.ROUTED.value
                        continue
                elif not lo_already_sent:
                    # Lần 2: Lệnh trả (RO) đã xử lý xong -> nhắm thẳng vào lệnh đóng (LO) và đồng bộ lại khách/kho của LO
                    line.transport_plan_id = comb_lo_plan.id
                    line.order_type = OrderType.LOAD.value
                    container_job.order_type = OrderType.LOAD.value
                    if comb_lo_plan.customer_id:
                        cust_id = comb_lo_plan.customer_id
                        container_job.customer_id = cust_id
                        cust_obj = db.get(Customer, cust_id)
                    if comb_lo_plan.customer_name:
                        line.customer_hint = comb_lo_plan.customer_name
                        container_job.customer_hint = comb_lo_plan.customer_name
                    if comb_lo_plan.warehouse_id:
                        wh_id = comb_lo_plan.warehouse_id
                        container_job.warehouse_id = wh_id
                        wh_obj = db.get(Warehouse, wh_id)
                    if comb_lo_plan.warehouse_name or comb_lo_plan.delivery_address:
                        line.warehouse_hint = comb_lo_plan.warehouse_name or comb_lo_plan.delivery_address
                        container_job.warehouse_hint = line.warehouse_hint
                    if comb_lo_plan.group_id:
                        line.target_group_id = comb_lo_plan.group_id
                    cur_r2 = dict(container_job.raw_fields or {})
                    cur_r2["transport_plan_id"] = comb_lo_plan.id
                    container_job.raw_fields = cur_r2

            plan_check = CarrierFlowService.verify_plan_and_carrier(db, line, carrier_ctx, cust_id)
            if plan_check.matched_plan is not None:
                mp = plan_check.matched_plan
                enrichment_updated = False
                if cust_id is None and mp.customer_id:
                    cust_id = mp.customer_id
                    container_job.customer_id = cust_id
                    cust_obj = db.get(Customer, cust_id)
                    enrichment_updated = True
                if not line.customer_hint and mp.customer_name:
                    line.customer_hint = mp.customer_name
                    container_job.customer_hint = mp.customer_name
                    enrichment_updated = True
                if wh_id is None and mp.warehouse_id:
                    wh_id = mp.warehouse_id
                    container_job.warehouse_id = wh_id
                    wh_obj = db.get(Warehouse, wh_id)
                    enrichment_updated = True
                if not line.warehouse_hint and mp.delivery_address:
                    line.warehouse_hint = mp.delivery_address
                    container_job.warehouse_hint = mp.delivery_address
                    enrichment_updated = True
                if not line.target_group_id and mp.group_id:
                    line.target_group_id = mp.group_id
                if mp.plan_date and line.plan_date != mp.plan_date.isoformat():
                    line.plan_date = mp.plan_date.isoformat()
                    enrichment_updated = True
                if mp.seal_no and not line.seal_no:
                    line.seal_no = mp.seal_no
                    container_job.seal_no = mp.seal_no
                    enrichment_updated = True
                if mp.container_size and not line.container_size:
                    line.container_size = mp.container_size
                    container_job.container_size = container_job.container_size or mp.container_size
                    enrichment_updated = True
                if mp.planned_trailer_plate and not line.trailer_plate:
                    line.trailer_plate = mp.planned_trailer_plate
                    enrichment_updated = True
                mp_eta = extract_plan_expected_time(mp)
                if mp_eta and not line.eta_time:
                    line.eta_time = mp_eta
                    if not line.eta_text:
                        line.eta_text = mp_eta
                    line.field_evidences.setdefault("eta_time", "transport_plan")
                    enrichment_updated = True
                if not line.transport_plan_id or enrichment_updated:
                    line.transport_plan_id = line.transport_plan_id or mp.id
                    cur_raw = dict(container_job.raw_fields or {}) if isinstance(container_job.raw_fields, dict) else {}
                    cur_raw["transport_plan_id"] = line.transport_plan_id
                    cur_raw["plan_date"] = line.plan_date
                    cur_raw["eta"] = line.eta_time
                    cur_raw["eta_text"] = line.eta_text
                    cur_raw["field_evidences"] = line.field_evidences
                    cur_raw["canonical_record"] = line.to_canonical_record()
                    container_job.raw_fields = cur_raw
                    if truck_record and isinstance(truck_record.raw_data, dict):
                        tr_raw = dict(truck_record.raw_data)
                        tr_raw["eta"] = line.eta_time
                        tr_raw["eta_text"] = line.eta_text
                        truck_record.raw_data = tr_raw
                if enrichment_updated:
                    line.warnings = [w for w in (line.warnings or []) if w != "Thiếu/sai: Khách hàng"]
                    is_complete, missing_fields = OutboundTemplateBuilder.check_core_fields_completeness(line)
                    if (
                        is_complete
                        and line.check_digit_valid is not False
                        and line.validation_status != ValidationStatus.INVALID.value
                    ):
                        line.validation_status = ValidationStatus.VALID.value
                        container_job.validation_status = ValidationStatus.VALID.value
                    cust_name = cust_obj.name if cust_obj else (line.customer_hint or "Quý khách hàng")
                    wh_name = wh_obj.name if wh_obj else (line.warehouse_hint or "Kho khách hàng")
                    cust_tms_code = cust_obj.tms_customer_id if cust_obj else None
                    if is_update and changes_list:
                        notification_text = OutboundTemplateBuilder.build_update_notification(
                            line=line,
                            changes_list=changes_list,
                            customer_name=cust_name,
                            warehouse_name=wh_name,
                            customer_id=cust_tms_code,
                        )
                    else:
                        notification_text = OutboundTemplateBuilder.build_customer_notification(
                            line=line,
                            customer_name=cust_name,
                            warehouse_name=wh_name,
                            customer_id=cust_tms_code,
                        )

            routing_blocked_reason: Optional[str] = None
            routing_blocked_type: Optional[str] = None
            if carrier_ctx.is_unregistered_group:
                routing_blocked_type = "UNREGISTERED_CARRIER_GROUP"
                routing_blocked_reason = f"Nhóm gửi '{message.group_id}' chưa được đăng ký trong danh mục nhóm nhà xe VSICO."
            elif plan_check.is_carrier_mismatch:
                routing_blocked_type = "CARRIER_MISMATCH"
                routing_blocked_reason = plan_check.reason
            elif plan_check.is_shipping_missing:
                routing_blocked_type = (
                    "PLAN_SYNC_REQUIRED"
                    if "nhiều dòng kế hoạch" in (plan_check.reason or "")
                    else "SHIPPING_NOT_FOUND"
                )
                routing_blocked_reason = plan_check.reason

            target_grp_id, target_zalo_grp_id = (None, None)
            if not routing_blocked_type:
                target_grp_id, target_zalo_grp_id = CarrierFlowService.find_target_zalo_group_safe(
                    db=db,
                    customer_id=cust_id,
                    warehouse_id=wh_id,
                    order_type=line.order_type,
                    source_group_id_str=message.group_id,
                    plan_group_id_str=line.target_group_id,
                    customer_hint=line.customer_hint,
                )

            # Ưu tiên cập nhật dữ liệu lên TransportPlan & TMS cho Lệnh trả / Lệnh đóng độc lập khi đã khớp kế hoạch
            # CHỈ thực hiện khi cả nhóm nhà xe và nhóm khách hàng đều ở chế độ AUTO.
            # Nếu nhóm đang ở chế độ Chờ duyệt (MANUAL), tuyệt đối KHÔNG ghi trước TransportPlan hay đẩy TMS
            # (kể cả khi lệnh trả đã đủ toàn bộ 4-5 trường thông tin) — bắt buộc đợi ĐHVT duyệt.
            tms_synced_directly = False
            target_grp_preview = db.get(ZaloGroup, target_grp_id) if target_grp_id else None
            is_manual_for_tms = CarrierFlowService.is_manual_approval_required(
                source_grp, target_grp_preview
            )
            if (
                not routing_blocked_type
                and plan_check.matched_plan is not None
                and is_complete
                and line.validation_status == ValidationStatus.VALID.value
                and not is_manual_for_tms
            ):
                if not CarrierFlowService.sync_job_with_local_plan_or_review(
                    db=db,
                    job=container_job,
                    source_group=carrier_ctx.source_group,
                    is_test_msg=carrier_ctx.is_test_msg,
                    allow_tms_sync=True,
                ):
                    has_review_or_error = True
                    container_job.validation_status = ValidationStatus.NEEDS_REVIEW.value
                    container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                    continue
                tms_synced_directly = True

                # Nếu chưa cấu hình nhóm khách hàng nhưng nhóm nhà xe là AUTO và đã cập nhật xong lên TMS:
                # hoàn tất luôn luồng TMS + phản hồi xác nhận cho nhà xe mà không báo lỗi ROUTING_NOT_FOUND
                if target_grp_id is None:
                    container_job.routing_status = RoutingStatus.ROUTED.value
                    mp_ok = plan_check.matched_plan
                    ok_order_lbl = mp_ok.order_code or ("Lệnh đóng" if (line.order_type or "").upper() == "LOAD" else "Lệnh trả")
                    ok_carrier_txt = (
                        "[VSICO] - ✅ Đã cập nhật thông tin xe lên hệ thống TMS\n\n"
                        f"📦 Container: {line.container_no or 'Chưa rõ'}\n"
                        f"• Lệnh: {ok_order_lbl}\n"
                        f"• Xe đầu kéo: {line.truck_plate or '—'}"
                    )
                    ok_br = BotReply(
                        message_id=message.id,
                        sender_id=message.sender_id,
                        reply_text=ok_carrier_txt,
                        status=CorrectionStatus.RESOLVED.value,
                        fix_deadline=datetime.now(timezone.utc),
                    )
                    db.add(ok_br)
                    db.flush()
                    if CarrierFlowService._is_dispatchable_real_group(message.group_id, source_grp, is_test_msg):
                        ok_sent, ok_mid, _ = ZaloDispatcher.send_to_group(
                            group_id=message.group_id,
                            message=ok_carrier_txt,
                            quote_msg_id=message.zalo_message_id,
                        )
                        if ok_sent and ok_mid:
                            ok_br.zalo_msg_id = ok_mid
                            ok_br.sent_at = datetime.now(timezone.utc)
                    continue

            if not routing_blocked_type and target_grp_id is None:
                # Nhóm MANUAL chưa có nhóm khách -> vẫn tạo ReviewCase duyệt cập nhật TMS gửi nhóm ĐHVT (ghi rõ tên nhóm nguồn)
                if plan_check.matched_plan is not None and is_manual_for_tms:
                    has_review_or_error = True
                    container_job.validation_status = ValidationStatus.NEEDS_REVIEW.value
                    container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                    mp_man = plan_check.matched_plan
                    DhvtNotificationService.create_or_merge_review_case(
                        db=db,
                        message_id=message.id,
                        case_type="group_manual_review",
                        reason=f"Nhóm '{source_grp.name if source_grp else message.group_id}' ở chế độ Chờ duyệt; cần ĐHVT duyệt cập nhật {mp_man.order_code or 'kế hoạch'} lên TMS.",
                        container_job_id=container_job.id,
                        container_no=container_job.container_no,
                        details={
                            **line.to_dict(),
                            "selected_plan_id": str(mp_man.id),
                            "transport_plan_id": str(mp_man.id),
                            "order_code": mp_man.order_code,
                            "source_group_name": source_grp.name if source_grp else message.group_id,
                            "sender_name": message.sender_name,
                        },
                        suggestion="Trả lời 'duyệt' trên Zalo ĐHVT hoặc mở Web để duyệt đẩy TMS.",
                        is_test_msg=is_test_msg,
                        notify_zalo=True,
                    )
                    continue
                routing_blocked_type = "ROUTING_NOT_FOUND"
                routing_blocked_reason = f"Không tìm thấy nhóm Zalo khách hàng cho cont {line.container_no or 'N/A'}."

            if routing_blocked_type:
                has_review_or_error = True
                is_carrier_cont_defect = (
                    routing_blocked_type == "SHIPPING_NOT_FOUND"
                    and (not line.container_no or line.check_digit_valid is False)
                )
                if is_carrier_cont_defect:
                    # Lỗi thiếu số container hoặc sai check-digit ISO 6346: Bot tự nhắc nhà xe, không bắt ĐHVT duyệt ngay
                    container_job.validation_status = (
                        ValidationStatus.INVALID.value
                        if line.check_digit_valid is False
                        else ValidationStatus.NEEDS_REVIEW.value
                    )
                    container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                    continue

                container_job.validation_status = ValidationStatus.NEEDS_REVIEW.value
                container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                carrier_obj = (
                    db.get(Carrier, carrier_ctx.source_group.carrier_id)
                    if (carrier_ctx.source_group and carrier_ctx.source_group.carrier_id)
                    else None
                )
                case_details = {
                    **line.to_dict(),
                    "source_group_name": source_grp.name if source_grp and source_grp.name else message.group_id,
                    "sender_name": message.sender_name,
                }
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
                DhvtNotificationService.create_or_merge_review_case(
                    db=db,
                    message_id=message.id,
                    case_type=routing_blocked_type,
                    reason=routing_blocked_reason or "Chặn gửi do sai lệch nhà xe hoặc thiếu kế hoạch.",
                    container_job_id=container_job.id,
                    container_no=container_job.container_no,
                    carrier_name=carrier_obj.name if carrier_obj else None,
                    details=case_details,
                    suggestion="ĐHVT kiểm tra nhà xe/kế hoạch và trả lời duyệt/từ chối trên Zalo hoặc Web.",
                    priority="HIGH" if routing_blocked_type in ("CARRIER_MISMATCH", "UNREGISTERED_CARRIER_GROUP", "SHIPPING_NOT_FOUND") else "NORMAL",
                    is_test_msg=carrier_ctx.is_test_msg,
                    notify_zalo=True,
                )
                # Hạng mục 3.3: Cont có số hợp lệ nhưng KHÔNG có trong kế hoạch -> vừa báo ĐHVT vừa cảnh báo Nhà xe
                if routing_blocked_type == "SHIPPING_NOT_FOUND" and line.container_no:
                    unknown_warn_text = OutboundTemplateBuilder.build_unknown_container_carrier_warning(
                        line.container_no
                    )
                    unk_reply = BotReply(
                        message_id=message.id,
                        sender_id=message.sender_id,
                        reply_text=unknown_warn_text,
                        fix_deadline=datetime.now(timezone.utc) + timedelta(minutes=30),
                        status=CorrectionStatus.PENDING.value,
                    )
                    db.add(unk_reply)
                    db.flush()
                    if CarrierFlowService._is_dispatchable_real_group(message.group_id, source_grp, is_test_msg):
                        ok_u, mid_u, _ = ZaloDispatcher.send_to_group(
                            group_id=message.group_id,
                            message=unknown_warn_text,
                            quote_msg_id=message.zalo_message_id,
                        )
                        if ok_u and mid_u:
                            unk_reply.zalo_msg_id = mid_u
                            unk_reply.sent_at = datetime.now(timezone.utc)
                continue

            # Xác định chế độ gửi của nhóm (send_mode): 'AUTO' hoặc 'MANUAL'
            target_grp = db.get(ZaloGroup, target_grp_id) if target_grp_id else None
            is_auto_group = not CarrierFlowService.is_manual_approval_required(source_grp, target_grp)

            # Đồng bộ dữ liệu hợp lệ lên bảng TransportPlan cục bộ CHỈ KHI ở chế độ AUTO
            # (nhóm MANUAL tuyệt đối không ghi trước TransportPlan hay đẩy TMS trước khi ĐHVT duyệt)
            if (
                not tms_synced_directly
                and is_auto_group
                and is_complete
                and line.validation_status == ValidationStatus.VALID.value
            ):
                if not CarrierFlowService.sync_job_with_local_plan_or_review(
                    db=db,
                    job=container_job,
                    source_group=carrier_ctx.source_group,
                    is_test_msg=carrier_ctx.is_test_msg,
                    allow_tms_sync=True,
                ):
                    has_review_or_error = True
                    container_job.validation_status = ValidationStatus.NEEDS_REVIEW.value
                    container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                    continue

            target_carrier_group = message.group_id

            paused_grp_name = (
                source_grp.name
                if (source_grp and SendMode(source_grp.send_mode).value == SendMode.MANUAL.value)
                else (target_grp.name if target_grp else (target_zalo_grp_id or "khách hàng"))
            )

            out_zalo_id: Optional[str] = None
            out_last_err: Optional[str] = None

            if is_duplicate:
                out_status = OutboundStatus.IGNORED_DUPLICATE.value
                out_last_err = "Đã gửi thông báo cho cont này trước đó, thông tin không đổi (bỏ qua tránh spam)"
            elif not is_auto_group:
                # Group ở trạng thái 'MANUAL':
                # Kể cả tin nhắn có thỏa mãn thì VẪN CHO VÀO DANH SÁCH ĐỂ DVDH DUYỆT HẾT!
                out_status = OutboundStatus.PENDING_APPROVAL.value
                out_zalo_id = None
                if is_complete:
                    out_last_err = f"Nhóm '{paused_grp_name}' ở chế độ Chờ duyệt (Chờ ĐHVT duyệt trước khi gửi khách)"
                else:
                    out_last_err = f"Chờ ĐHVT duyệt do thiếu/sai: {', '.join(missing_fields)}"
            elif is_complete:
                out_status = OutboundStatus.PENDING_SEND.value
                out_last_err = None
            else:
                out_status = OutboundStatus.PENDING_APPROVAL.value
                out_zalo_id = None
                out_last_err = f"Chờ ĐHVT duyệt do thiếu/sai: {', '.join(missing_fields)}"

            outbound_msg = OutboundMessage(
                target_group_id=target_grp_id,
                order_type=line.order_type or OrderType.LOAD.value,
                message_kind=message_kind,
                content=notification_text,
                idempotency_key=f"outbound:{message.id}:{idx}:{message_kind}",
                status=out_status,
                attempt_count=1 if (out_status == OutboundStatus.SENT.value and not is_duplicate) else 0,
                zalo_message_id=out_zalo_id,
                approved_by="auto_system" if (out_status == OutboundStatus.SENT.value and not is_duplicate) else None,
                approved_at=datetime.now(timezone.utc) if (out_status == OutboundStatus.SENT.value and not is_duplicate) else None,
                sent_at=datetime.now(timezone.utc) if out_status == OutboundStatus.SENT.value else None,
                last_error=out_last_err,
            )
            db.add(outbound_msg)
            db.flush()

            out_item = OutboundMessageItem(
                outbound_message_id=outbound_msg.id,
                container_job_id=container_job.id,
            )
            db.add(out_item)
            if not is_duplicate and is_complete:
                CarrierFlowService.supersede_pending_outbounds_for_container(
                    db, container_job.container_no, keep_outbound_id=outbound_msg.id
                )

            if out_status == OutboundStatus.FAILED.value:
                has_review_or_error = True
                container_job.routing_status = RoutingStatus.NEEDS_REVIEW.value
                CarrierFlowService.create_send_failed_alert(
                    db=db,
                    message=message,
                    container_job=container_job,
                    outbound_msg=outbound_msg,
                    target_group_name=target_grp.name if target_grp else str(target_zalo_grp_id),
                    error_text=out_last_err or "Gửi Zalo thất bại sau 3 lần thử",
                    is_test_msg=is_test_msg,
                )

            if not is_complete or line.validation_status in (
                ValidationStatus.INVALID.value,
                ValidationStatus.NEEDS_REVIEW.value,
            ):
                has_review_or_error = True
                case_type = (
                    "invalid_check_digit"
                    if line.check_digit_valid is False
                    else "missing_fields"
                )
                reason_text = (
                    f"Còn thiếu hoặc chưa đúng: {', '.join(missing_fields)}"
                    if missing_fields
                    else "Thông tin điều xe còn thiếu hoặc chưa hợp lệ."
                )
                DhvtNotificationService.create_or_merge_review_case(
                    db=db,
                    message_id=message.id,
                    case_type=case_type,
                    reason=reason_text,
                    container_job_id=container_job.id,
                    container_no=container_job.container_no,
                    details=line.to_dict(),
                    suggestion="Đợi nhà xe bổ sung đủ 5 thông tin (xe, rơ-moóc, cont, tài xế, SĐT).",
                    is_test_msg=is_test_msg,
                    notify_zalo=False,
                )
            elif is_duplicate:
                # Tin trùng hệt với chặng đã gửi -> phản hồi xác nhận cho nhà xe khỏi chờ/hiểu nhầm, không tạo ca duyệt thừa
                dup_cont = container_job.container_no or "N/A"
                dup_plan = db.get(TransportPlan, int(line.transport_plan_id)) if line.transport_plan_id else None
                dup_order = (dup_plan.order_code if dup_plan and dup_plan.order_code else None) or (
                    "Đóng hàng" if (line.order_type or "").upper() == "LOAD" else "Trả hàng"
                )
                dup_reply_text = (
                    f"[VSICO Bot] Thông tin điều xe cont {dup_cont} ({dup_order}) trùng khớp với thông báo đã phát hành trước đó. "
                    "Nếu anh/chị báo cho lệnh khác cùng cont, vui lòng ghi rõ mã lệnh (RO/LO)."
                )
                dup_reply = BotReply(
                    message_id=message.id,
                    sender_id=message.sender_id,
                    reply_text=dup_reply_text,
                    status=CorrectionStatus.RESOLVED.value,
                    fix_deadline=datetime.now(timezone.utc),
                )
                db.add(dup_reply)
                db.flush()
                if settings.AUTO_DISPATCH_OUTBOUND and not is_test_msg:
                    if target_carrier_group and not target_carrier_group.startswith("direct_"):
                        ok_d, mid_d, _ = ZaloDispatcher.send_to_group(
                            group_id=target_carrier_group,
                            message=dup_reply_text,
                            quote_msg_id=message.zalo_message_id,
                        )
                        if not ok_d and message.zalo_message_id:
                            ok_d, mid_d, _ = ZaloDispatcher.send_to_group(
                                group_id=target_carrier_group,
                                message=dup_reply_text,
                            )
                        if ok_d and mid_d:
                            dup_reply.zalo_msg_id = mid_d
                            dup_reply.sent_at = datetime.now(timezone.utc)
            elif not is_auto_group:
                # Tin nhắn thỏa mãn đầy đủ nhưng nhóm ở chế độ 'MANUAL' -> tạo ReviewCase để ĐHVT duyệt trước khi ghi kế hoạch / TMS / gửi khách
                has_review_or_error = True
                line.validation_status = ValidationStatus.NEEDS_REVIEW.value
                manual_plan = plan_check.matched_plan
                manual_details = {
                    **line.to_dict(),
                    "outbound_message_id": str(outbound_msg.id),
                    "source_group_name": source_grp.name if source_grp and source_grp.name else message.group_id,
                    "sender_name": message.sender_name,
                    **(
                        {
                            "selected_plan_id": str(manual_plan.id),
                            "transport_plan_id": str(manual_plan.id),
                            "order_code": manual_plan.order_code,
                        }
                        if manual_plan is not None
                        else {}
                    ),
                }
                manual_rc, _ = DhvtNotificationService.create_or_merge_review_case(
                    db=db,
                    message_id=message.id,
                    case_type="group_manual_review",
                    reason=f"Nhóm '{paused_grp_name}' ở chế độ Chờ duyệt (Cần ĐHVT duyệt trước khi cập nhật kế hoạch và gửi khách)",
                    container_job_id=container_job.id,
                    container_no=container_job.container_no,
                    details=manual_details,
                    suggestion="Mở mục Chờ duyệt để kiểm tra, đồng bộ TMS và phát hành tới khách hàng.",
                    is_test_msg=is_test_msg,
                    notify_zalo=False,
                )
                if out_status == OutboundStatus.PENDING_APPROVAL.value and is_complete:
                    DhvtNotificationService.notify_pending_outbound(
                        db=db,
                        outbound=outbound_msg,
                        target_group_name=target_grp.name if target_grp else str(target_zalo_grp_id),
                        containers=[container_job.container_no] if container_job.container_no else [],
                        reason=out_last_err or "Tin nhắn nhóm MANUAL cần ĐHVT duyệt gửi khách.",
                        is_test_msg=is_test_msg,
                        review_case_id=manual_rc.id,
                    )

        DhvtNotificationService.end_alert_batch(
            db, _dhvt_batch_token, _dhvt_batch_bucket, is_test_msg=is_test_msg
        )

        if has_review_or_error:
            # Chỉ gửi bot_reply nhắc nhà xe nếu tin nhắn thực sự THIẾU HOẶC SAI dữ liệu
            # (Không phiền nhà xe nếu tin nhắn đã chuẩn mà do nhóm đang ở chế độ duyệt nội bộ của DVDH)
            any_carrier_defect = any(
                not OutboundTemplateBuilder.check_core_fields_completeness(l)[0]
                or l.validation_status == ValidationStatus.INVALID.value
                for l in validated_lines
            )
            if any_carrier_defect:
                warning_reply_text = OutboundTemplateBuilder.build_carrier_warning_reply(validated_lines)
                if warning_reply_text:
                    bot_reply = BotReply(
                        message_id=message.id,
                        sender_id=message.sender_id,
                        reply_text=warning_reply_text,
                        fix_deadline=datetime.now(timezone.utc) + timedelta(minutes=30),
                        status=CorrectionStatus.PENDING.value,
                    )
                    db.add(bot_reply)
                    db.flush()

                    # Chỉ gửi thực tế tin nhắc lỗi về Zalo nếu:
                    # 1. Bật cờ AUTO_DISPATCH_OUTBOUND
                    # 2. Không phải là tin nhắn test / kiểm thử 20k / giả lập (is_test_msg == False)
                    if settings.AUTO_DISPATCH_OUTBOUND and not is_test_msg:
                        reply_ok = False
                        reply_msg_id = None
                        if target_carrier_group and not target_carrier_group.startswith("direct_"):
                            reply_ok, reply_msg_id, _ = ZaloDispatcher.send_to_group(
                                group_id=target_carrier_group,
                                message=warning_reply_text,
                                quote_msg_id=message.zalo_message_id,
                            )
                            if not reply_ok and message.zalo_message_id:
                                reply_ok, reply_msg_id, _ = ZaloDispatcher.send_to_group(
                                    group_id=target_carrier_group,
                                    message=warning_reply_text,
                                )
                        elif message.sender_id and not message.sender_id.startswith("test_"):
                            reply_ok, reply_msg_id, _ = ZaloDispatcher.send_to_user(
                                user_id=message.sender_id,
                                message=warning_reply_text,
                            )
                        if reply_ok and reply_msg_id:
                            bot_reply.zalo_msg_id = reply_msg_id
                            bot_reply.sent_at = datetime.now(timezone.utc)

        message.processing_status = (
            MessageStatus.NEEDS_REVIEW.value
            if has_review_or_error
            else MessageStatus.PROCESSED.value
        )
        db.commit()

        # Phát hành ngay các thông báo thật đủ điều kiện qua drain_outbox
        if settings.AUTO_DISPATCH_OUTBOUND and not CarrierFlowService.is_test_message(message):
            pending_real_ids = list(
                db.scalars(
                    select(OutboundMessage.id)
                    .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
                    .join(ContainerJob, OutboundMessageItem.container_job_id == ContainerJob.id)
                    .join(ZaloGroup, OutboundMessage.target_group_id == ZaloGroup.id)
                    .where(
                        ContainerJob.message_id == message.id,
                        OutboundMessage.status == OutboundStatus.PENDING_SEND.value,
                        ZaloGroup.is_test == False,
                    )
                    .distinct()
                ).all()
            )
            if pending_real_ids:
                from src.infrastructure.outbox_worker import drain_outbox

                drain_outbox(lambda: nullcontext(db), pending_real_ids)
                for oid in pending_real_ids:
                    om = db.get(OutboundMessage, oid)
                    if om and om.status in (OutboundStatus.FAILED.value, OutboundStatus.PENDING_APPROVAL.value):
                        message.processing_status = MessageStatus.NEEDS_REVIEW.value
                        db.commit()
                        break

        db.refresh(message)
        return message
