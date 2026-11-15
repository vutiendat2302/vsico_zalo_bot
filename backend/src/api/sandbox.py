"""API Sandbox kiểm thử thuật toán & hiểu bối cảnh hội thoại (Dry-Run 100%, không lưu CSDL).

Cho phép nhập tin nhắn, ảnh OCR, tin nhắn trích dẫn (quote), lịch sử tin trước đó
và trạng thái các ca container ảo trong phiên để quan sát toàn bộ kết quả xử lý của
từng tầng (OCR -> Gatekeeper -> Rule Parser -> Ngữ cảnh/AI -> ISO 6346 -> Kế hoạch -> Template)
mà tuyệt đối không ghi bất kỳ dữ liệu nào vào MySQL hay phát hành tin nhắn Zalo thật.
"""

import time
import unicodedata
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.api.messages import parse_flexible_datetime
from src.domain.enums import Intent, MessageStatus, ValidationStatus
from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_container, clean_phone, clean_plate
from src.handlers.extraction_handler import ExtractionHandler
from src.infrastructure.ai_service_client import AIServiceClient
from src.infrastructure.database import get_db
from src.infrastructure.models import Carrier, TransportPlan, Warehouse, WarehouseAlias, ZaloGroup
from src.infrastructure.ocr.paddle_client import PaddleOCRClient
from src.messaging.classifier import IntentClassifier
from src.outbound.templates import OutboundTemplateBuilder
from src.parsing.ai_fallback import AIFallbackExtractor
from src.parsing.trip_parser import TripParser
from src.validation.taxonomy import MessageTaxonomyAnalyzer
from src.validation.validators import ContainerValidator

router = APIRouter(prefix="/api/sandbox", tags=["9. Kiểm Thử Thuật Toán (Sandbox Dry-Run)"])


class SandboxSimulateRequest(BaseModel):
    """Dữ liệu đầu vào mô phỏng xử lý tin nhắn & bối cảnh trong chế độ không lưu CSDL."""

    text: str = Field(default="", description="Nội dung tin nhắn cần kiểm thử")
    image_base64: str | None = Field(default=None, description="Ảnh Base64/Data URI đính kèm để kiểm thử OCR")
    quote_message: str | None = Field(default=None, description="Nội dung tin nhắn cũ hoặc tin nhắc Bot được Quote")
    context_messages: list[str] = Field(
        default_factory=list,
        description="Danh sách các tin nhắn trước đó trong cùng cuộc hội thoại",
    )
    virtual_jobs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Danh sách ca container ảo trong phiên test hiện tại trên trình duyệt",
    )
    carrier_hint: str | None = Field(default=None, description="Tên nhà xe giả lập gửi tin")
    timestamp: str | None = Field(default=None, description="Thời điểm gửi giả lập (ISO-8601)")
    allow_ai_fallback: bool = Field(
        default=False,
        description="Bật để cho phép gọi ai-service khi Rule-based không đủ; mặc định False (0 token)",
    )


def _norm_ascii(text: str | None) -> str:
    """Chuẩn hóa chuỗi tiếng Việt không dấu viết thường phục vụ đối chiếu tên."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text.strip())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.replace("đ", "d").replace("Đ", "D").lower().split())


def _line_to_virtual_job(line: ExtractedContainerLine, status_val: str) -> dict[str, Any]:
    """Chuyển dòng container chuẩn thành đối tượng virtual_job lưu tạm trong phiên UI."""
    return {
        "container_no": line.container_no,
        "truck_plate": line.truck_plate,
        "trailer_plate": line.trailer_plate,
        "driver_name": line.driver_name,
        "driver_phone": line.driver_phone,
        "container_size": line.canonical_cont_size or line.container_size,
        "seal_no": line.seal_no,
        "order_type": line.order_type,
        "customer_hint": line.customer_hint,
        "warehouse_hint": line.warehouse_hint,
        "eta_time": line.eta_time,
        "plan_date": line.plan_date,
        "line_text": line.line_text,
        "status": status_val,
    }


def _virtual_job_to_line(job: dict[str, Any]) -> ExtractedContainerLine:
    """Khôi phục `ExtractedContainerLine` từ dictionary `virtual_job` trong phiên Sandbox."""
    return ExtractedContainerLine(
        line_no=1,
        line_text=str(job.get("line_text") or ""),
        source_format="tu_do",
        plan_date=job.get("plan_date"),
        truck_plate=clean_plate(job.get("truck_plate")) if job.get("truck_plate") else None,
        raw_truck_plate=job.get("truck_plate"),
        trailer_plate=clean_plate(job.get("trailer_plate")) if job.get("trailer_plate") else None,
        driver_name=job.get("driver_name"),
        driver_phone=clean_phone(job.get("driver_phone")) if job.get("driver_phone") else None,
        container_no=clean_container(job.get("container_no")) if job.get("container_no") else None,
        container_size=job.get("container_size"),
        seal_no=job.get("seal_no"),
        order_type=job.get("order_type"),
        customer_hint=job.get("customer_hint"),
        warehouse_hint=job.get("warehouse_hint"),
        eta_time=job.get("eta_time"),
    )


def _merge_lines_in_memory(
    base_line: ExtractedContainerLine,
    incoming: ExtractedContainerLine,
    tag: str = "BO SUNG",
) -> ExtractedContainerLine:
    """Gộp trường mới vào bản ghi nền theo đúng quy tắc `CarrierFlowService.merge_line_into_job`."""
    merged = ExtractedContainerLine(
        line_no=1,
        line_text=f"{base_line.line_text}\n[{tag}] {incoming.line_text}".strip(),
        source_format=base_line.source_format or incoming.source_format,
        plan_date=incoming.plan_date or base_line.plan_date,
        truck_plate=incoming.truck_plate or base_line.truck_plate,
        raw_truck_plate=incoming.raw_truck_plate or base_line.raw_truck_plate,
        trailer_plate=incoming.trailer_plate or base_line.trailer_plate,
        driver_name=incoming.driver_name or base_line.driver_name,
        driver_phone=incoming.driver_phone or base_line.driver_phone,
        container_no=incoming.container_no or base_line.container_no,
        container_size=incoming.canonical_cont_size or incoming.container_size or base_line.container_size,
        seal_no=incoming.seal_no or base_line.seal_no,
        order_type=incoming.order_type or base_line.order_type,
        customer_hint=incoming.customer_hint or base_line.customer_hint,
        warehouse_hint=incoming.warehouse_hint or base_line.warehouse_hint,
        customer_code_or_id=base_line.customer_code_or_id or incoming.customer_code_or_id,
        warehouse_code_or_id=base_line.warehouse_code_or_id or incoming.warehouse_code_or_id,
        eta_time=incoming.eta_time or base_line.eta_time,
        estimated_at=incoming.estimated_at or base_line.estimated_at,
        note=incoming.note or base_line.note,
        confidence=max(float(base_line.confidence), float(incoming.confidence)),
    )
    return ContainerValidator.validate_all([merged])[0]


def _compute_diff_in_memory(
    old_line: ExtractedContainerLine,
    new_line: ExtractedContainerLine,
) -> list[str]:
    """Tính danh sách các trường thay đổi giữa bản ghi cũ và bản cập nhật đổi xe/tài xế."""
    changes: list[str] = []
    checks = [
        ("Biển số xe", old_line.truck_plate, new_line.truck_plate),
        ("Tài xế", old_line.driver_name, new_line.driver_name),
        ("SĐT tài xế", old_line.driver_phone, new_line.driver_phone),
        ("Giờ hẹn", old_line.eta_time, new_line.eta_time),
        ("Số chì", old_line.seal_no, new_line.seal_no),
    ]
    for label, before_val, after_val in checks:
        if after_val and (before_val or "").strip() != after_val.strip():
            changes.append(f"{label}: {before_val or 'Trống'} -> {after_val}")
    return changes


def _find_target_base_job(
    incoming_lines: list[ExtractedContainerLine],
    quote_message: str | None,
    context_messages: list[str],
    virtual_jobs: list[dict[str, Any]],
    ref_time: datetime,
    prefer_pending: bool = False,
) -> tuple[ExtractedContainerLine | None, int | None, str]:
    """Tìm ca container nền từ `virtual_jobs`, `quote_message` hoặc `context_messages` để kiểm tra ngữ cảnh."""
    cont_candidates = [ln.container_no for ln in incoming_lines if ln.container_no]

    # 1. Tìm trực tiếp trong virtual_jobs theo container_no
    if cont_candidates and virtual_jobs:
        for idx, vj in reversed(list(enumerate(virtual_jobs))):
            v_cont = clean_container(vj.get("container_no"))
            if v_cont and v_cont in cont_candidates:
                return _virtual_job_to_line(vj), idx, "virtual_job_by_container"

    # 2. Nếu có quote_message: đối chiếu virtual_jobs theo cont hoặc biển số trước khi tự parse quote
    if quote_message and quote_message.strip():
        is_bot_warning = "[vsico bot]" in quote_message.lower()
        q_parsed = TripParser.parse_message(quote_message.strip(), reference_time=ref_time)
        q_valid = ContainerValidator.validate_all(q_parsed)
        q_conts = {ln.container_no for ln in q_valid if ln.container_no}
        q_plates = {ln.truck_plate for ln in q_valid if ln.truck_plate}
        if virtual_jobs:
            for idx, vj in reversed(list(enumerate(virtual_jobs))):
                v_cont = clean_container(vj.get("container_no"))
                v_plate = clean_plate(vj.get("truck_plate")) if vj.get("truck_plate") else None
                if (v_cont and v_cont in q_conts) or (v_plate and v_plate in q_plates):
                    return _virtual_job_to_line(vj), idx, "virtual_job_by_quote"
        if not is_bot_warning and q_valid and any(ln.container_no or ln.truck_plate or ln.driver_name for ln in q_valid):
            return q_valid[0], None, "parsed_from_quote_message"

    # 3. Tìm ca đang chờ bổ sung gần nhất trong phiên nếu đang ở chế độ bổ sung
    if prefer_pending and virtual_jobs:
        for idx, vj in reversed(list(enumerate(virtual_jobs))):
            if vj.get("status") in ("NEEDS_REVIEW", "PENDING_SUPPLEMENT"):
                return _virtual_job_to_line(vj), idx, "pending_virtual_job_session"

    # 4. Tìm trong tin nhắn bối cảnh gần nhất nếu chỉ có 1 cont đang trao đổi
    for prev_text in reversed(context_messages):
        if not prev_text.strip():
            continue
        p_valid = ContainerValidator.validate_all(TripParser.parse_message(prev_text, reference_time=ref_time))
        if len(p_valid) == 1 and (p_valid[0].container_no or p_valid[0].truck_plate):
            p_cont = p_valid[0].container_no
            if p_cont and virtual_jobs:
                for idx, vj in reversed(list(enumerate(virtual_jobs))):
                    if clean_container(vj.get("container_no")) == p_cont:
                        return _virtual_job_to_line(vj), idx, "virtual_job_by_context_history"
            return p_valid[0], None, "parsed_from_context_messages"

    return None, None, "none"


@router.get("/context-options")
def get_sandbox_context_options(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Trả về danh mục nhà xe và thống kê kế hoạch thật từ CSDL để hỗ trợ chọn ngữ cảnh test."""
    carriers = list(
        db.scalars(select(Carrier).where(Carrier.is_active.is_(True)).order_by(Carrier.name.asc()).limit(50)).all()
    )
    source_groups = list(
        db.scalars(
            select(ZaloGroup)
            .where(ZaloGroup.is_active.is_(True), ZaloGroup.group_role.in_(["SOURCE", "CARRIER", "source", "car"]))
            .order_by(ZaloGroup.name.asc())
            .limit(50)
        ).all()
    )
    plan_count = db.scalar(select(func.count(TransportPlan.id))) or 0
    recent_plans = list(
        db.scalars(
            select(TransportPlan)
            .order_by(desc(TransportPlan.plan_date), desc(TransportPlan.id))
            .limit(10)
        ).all()
    )
    sample_plan_rows = list(
        db.scalars(
            select(TransportPlan)
            .where(TransportPlan.container_no.is_not(None), TransportPlan.container_no != "")
            .order_by(desc(TransportPlan.plan_date), desc(TransportPlan.id))
            .limit(5)
        ).all()
    )

    carrier_names: list[str] = []
    seen_names: set[str] = set()
    for c in carriers:
        if c.name and c.name not in seen_names:
            seen_names.add(c.name)
            carrier_names.append(c.name)
    for zg in source_groups:
        c_label = zg.carrier_name or zg.name
        if c_label and c_label not in seen_names:
            seen_names.add(c_label)
            carrier_names.append(c_label)
    for rp in recent_plans:
        c_label = rp.fleet_partner or rp.carrier_name
        if c_label and c_label not in seen_names:
            seen_names.add(c_label)
            carrier_names.append(c_label)

    return {
        "ok": True,
        "persisted": False,
        "total_plans_in_db": int(plan_count),
        "carriers": carrier_names,
        "sample_plans": [
            {
                "container_no": p.container_no,
                "order_type": p.order_type,
                "customer_name": p.customer_name,
                "fleet_partner": p.fleet_partner or p.carrier_name,
                "delivery_address": p.delivery_address or p.address,
                "plan_date": p.plan_date.isoformat() if p.plan_date else None,
            }
            for p in sample_plan_rows
        ],
    }


@router.post("/simulate")
def simulate_message_pipeline(
    payload: SandboxSimulateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Mô phỏng toàn bộ thuật toán xử lý tin nhắn, OCR, AI Fallback và hiểu bối cảnh mà KHÔNG lưu DB."""
    if not (payload.text or "").strip() and not (payload.image_base64 or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vui lòng nhập nội dung tin nhắn hoặc tải ảnh lên để kiểm thử.",
        )

    t0 = time.perf_counter()
    try:
        ref_time = parse_flexible_datetime(payload.timestamp) or datetime.now()
        raw_text = (payload.text or "").strip()
        image_placeholders = {
            "[ảnh]", "[hình ảnh]", "[đính kèm]", "[photo]", "[image]",
            "[tệp đính kèm]", "[attachment]", "ảnh", "hình ảnh", "gửi ảnh",
        }
        is_placeholder = raw_text.lower() in image_placeholders if raw_text else False

        # Tầng 0: OCR ảnh (nếu có)
        ocr_stage: dict[str, Any] = {
            "triggered": False,
            "has_text": False,
            "confidence": 0.0,
            "extracted_text": "",
            "lines_count": 0,
        }
        if payload.image_base64 and payload.image_base64.strip():
            ocr_stage["triggered"] = True
            ocr_text, ocr_conf, ocr_boxes = PaddleOCRClient.extract_text(payload.image_base64.strip())
            ocr_stage.update(
                {
                    "has_text": bool(ocr_text and ocr_text.strip()),
                    "confidence": round(float(ocr_conf), 4),
                    "extracted_text": ocr_text or "",
                    "lines_count": len(ocr_boxes),
                }
            )
            if ocr_text and ocr_text.strip():
                raw_text = ocr_text.strip() if (not raw_text or is_placeholder) else f"{raw_text}\n{ocr_text.strip()}"
            elif not raw_text or is_placeholder:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                return {
                    "ok": True,
                    "persisted": False,
                    "effective_text": raw_text,
                    "masked_text": "",
                    "processing_status": MessageStatus.IGNORED_NON_TEXT.value,
                    "initial_intent": Intent.IGNORE_CHAT.value,
                    "resolved_intent": Intent.IGNORE_CHAT.value,
                    "source_format": "image_non_text",
                    "ai_would_trigger": False,
                    "ai_executed": False,
                    "ai_service_status": "SKIPPED",
                    "model_name": "ocr-gatekeeper",
                    "prompt_version": "sandbox-v1",
                    "latency_ms": latency_ms,
                    "ocr": ocr_stage,
                    "context_resolution": {
                        "understood": True,
                        "resolution_type": "IGNORED_NON_TEXT",
                        "summary": "Ảnh không chứa văn bản điều vận nên hệ thống bỏ qua an toàn (0 token LLM).",
                        "changes_list": [],
                        "target_container": None,
                        "clarify_missing_container": False,
                        "is_duplicate_update": False,
                    },
                    "records": [],
                    "plan_matches": [],
                    "preview_outputs": {
                        "bot_reply": None,
                        "customer_notification": None,
                        "dhvt_alert": None,
                    },
                    "warnings": [],
                    "taxonomy": {},
                    "virtual_jobs_next": list(payload.virtual_jobs),
                }

        masked_text, _phone_map = AIFallbackExtractor.mask_phones_for_ai(raw_text)

        # Tầng 1: Fast Gatekeeper & Phân loại ý định ban đầu
        initial_intent = IntentClassifier.classify(raw_text)
        quote_clean = (payload.quote_message or "").strip() or None

        # Hỗ trợ nhận diện bối cảnh bổ sung nếu quote tin nhắc Bot hoặc chỉ gửi phần bổ sung ngắn
        if initial_intent == Intent.IGNORE_CHAT:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            taxonomy = MessageTaxonomyAnalyzer.analyze(
                raw_text=raw_text,
                intent=initial_intent,
                lines=[],
                quote_msg_id="sandbox_quote" if quote_clean else None,
            )
            return {
                "ok": True,
                "persisted": False,
                "effective_text": raw_text,
                "masked_text": masked_text,
                "processing_status": MessageStatus.IGNORED_CHAT.value,
                "initial_intent": initial_intent.value,
                "resolved_intent": initial_intent.value,
                "source_format": None,
                "ai_would_trigger": False,
                "ai_executed": False,
                "ai_service_status": "SKIPPED",
                "model_name": "fast-gatekeeper-v2",
                "prompt_version": "v2.0",
                "latency_ms": latency_ms,
                "ocr": ocr_stage,
                "context_resolution": {
                    "understood": True,
                    "resolution_type": "FAST_GATEKEEPER_IGNORED_CHAT",
                    "summary": "Fast Gatekeeper chặn tin nhắn xã giao ngay tầng 1 trong < 1ms, không tốn token AI.",
                    "changes_list": [],
                    "target_container": None,
                    "clarify_missing_container": False,
                    "is_duplicate_update": False,
                },
                "records": [],
                "plan_matches": [],
                "preview_outputs": {
                    "bot_reply": None,
                    "customer_notification": None,
                    "dhvt_alert": None,
                },
                "warnings": [],
                "taxonomy": taxonomy,
                "virtual_jobs_next": list(payload.virtual_jobs),
            }

        # Tầng 2: Bóc tách Rule-based & Kiểm tra ISO 6346
        rule_lines = ContainerValidator.validate_all(TripParser.parse_message(raw_text, reference_time=ref_time))
        validated_lines = list(rule_lines)
        resolved_intent = initial_intent

        # Tinh chỉnh bổ sung dựa trên ngữ cảnh Quote nhắc lỗi
        if resolved_intent == Intent.PARSE_TRUCK_INFO and (
            (quote_clean and any(kw in quote_clean.lower() for kw in ("thiếu", "bổ sung", "kiểm tra", "chì", "seal", "container")))
            or any(kw in raw_text.lower() for kw in ("bổ sung", "gửi thêm", "gửi nốt"))
        ):
            resolved_intent = Intent.SUPPLEMENT

        used_model = "vsico-hybrid-rule-v2"
        prompt_ver = "v2.0"

        # Tầng 3: Kiểm tra ngưỡng gọi AI & Gọi `ai-service` (chỉ khi allow_ai_fallback=True)
        has_any_rule_entity = any(
            ln.container_no or ln.truck_plate or ln.seal_no or ln.driver_phone or ln.driver_name or ln.eta_time
            for ln in validated_lines
        )
        algo_should_ai = AIFallbackExtractor.should_trigger_ai(validated_lines, intent=resolved_intent) or (
            bool(quote_clean) and not has_any_rule_entity
        )
        ai_executed = False
        ai_service_status = "DISABLED_BY_DEFAULT" if not payload.allow_ai_fallback else "NOT_NEEDED"

        if payload.allow_ai_fallback and (algo_should_ai or bool(payload.context_messages) or bool(quote_clean)):
            ai_res = AIServiceClient.extract(
                message_text=raw_text,
                quote_message=quote_clean,
                context_messages=payload.context_messages[-5:],
                active_plans=[],
                message_type="image_ocr" if ocr_stage["has_text"] else "text",
            )
            if ai_res is None:
                ai_service_status = "UNAVAILABLE_OFFLINE"
            else:
                ai_executed = True
                ai_service_status = f"OK ({ai_res.model_name})"
                prompt_ver = ai_res.prompt_version
                if ai_res.raw_masked_text:
                    masked_text = ai_res.raw_masked_text
                if resolved_intent == Intent.PARSE_TRUCK_INFO and ai_res.intent in (
                    "UPDATE_REQUEST",
                    "SUPPLEMENT",
                    "CANCEL_REQUEST",
                ):
                    resolved_intent = Intent(ai_res.intent)
                if ai_res.items and algo_should_ai:
                    converted = AIFallbackExtractor._convert_service_items(raw_text, ai_res, reference_time=ref_time)
                    if converted:
                        validated_lines = ContainerValidator.validate_all(converted)
                        used_model = ai_res.model_name

        # Tầng 4: Giải quyết Bối Cảnh Hội Thoại (Supplement / Update / Cancel / New) trên bộ nhớ tạm
        next_virtual_jobs: list[dict[str, Any]] = [dict(j) for j in payload.virtual_jobs]
        context_resolution: dict[str, Any] = {
            "understood": True,
            "resolution_type": "NEW_DISPATCH",
            "summary": "Tin nhắn báo điều xe mới độc lập.",
            "changes_list": [],
            "target_container": None,
            "clarify_missing_container": False,
            "is_duplicate_update": False,
        }
        bot_reply_preview: str | None = None
        customer_notif_preview: str | None = None
        dhvt_alert_preview: str | None = None
        processing_status = MessageStatus.PROCESSED.value

        # Thử đối chiếu ngữ cảnh Supplement nếu là SUPPLEMENT hoặc tin quote thiếu thông tin cốt lõi
        incoming_incomplete = any(
            not (ln.truck_plate and ln.container_no and ln.driver_name and ln.seal_no)
            for ln in validated_lines
        )
        base_line, base_idx, base_source = _find_target_base_job(
            incoming_lines=validated_lines,
            quote_message=quote_clean,
            context_messages=payload.context_messages,
            virtual_jobs=next_virtual_jobs,
            ref_time=ref_time,
            prefer_pending=(resolved_intent == Intent.SUPPLEMENT or bool(quote_clean)),
        )

        working_lines = list(validated_lines)
        if resolved_intent == Intent.CANCEL_REQUEST:
            target_conts = [ln.container_no for ln in validated_lines if ln.container_no]
            if not target_conts and base_line and base_line.container_no:
                target_conts = [base_line.container_no]
            for j in next_virtual_jobs:
                if clean_container(j.get("container_no")) in target_conts:
                    j["status"] = "CANCELLED"
            processing_status = MessageStatus.NEEDS_REVIEW.value
            dhvt_alert_preview = (
                f"[CANH BAO DHVT - YEU CAU HUY CHUYEN]\n"
                f"Container: {', '.join(target_conts) if target_conts else 'Chưa xác định'}\n"
                f"Nội dung: {raw_text}"
            )
            context_resolution = {
                "understood": True,
                "resolution_type": "CANCEL_REQUEST",
                "summary": (
                    f"Nhận diện yêu cầu Hủy chuyến cho container {', '.join(target_conts)} (nguồn: {base_source})."
                    if target_conts
                    else "Nhận diện yêu cầu Hủy chuyến nhưng chưa ghi rõ số Container -> Đẩy ĐHVT kiểm tra."
                ),
                "changes_list": [],
                "target_container": target_conts[0] if target_conts else None,
                "clarify_missing_container": False,
                "is_duplicate_update": False,
            }

        elif resolved_intent == Intent.UPDATE_REQUEST:
            incoming = validated_lines[0] if validated_lines else ExtractedContainerLine(line_text=raw_text)
            if not incoming.container_no and base_line is None:
                bot_reply_preview = OutboundTemplateBuilder.build_clarify_container_reply()
                dhvt_alert_preview = (
                    f"[CANH BAO DHVT - DOI XE THIEU SO CONT]\nNội dung: {raw_text}\n"
                    "Bot sẽ tự động hỏi lại nhà xe Số Container."
                )
                processing_status = MessageStatus.NEEDS_REVIEW.value
                context_resolution = {
                    "understood": True,
                    "resolution_type": "UPDATE_MISSING_CONTAINER",
                    "summary": "Hệ thống hiểu đây là lệnh Đổi xe / Cập nhật nhưng thiếu Số Container -> Bot tự hỏi lại nhà xe.",
                    "changes_list": [],
                    "target_container": None,
                    "clarify_missing_container": True,
                    "is_duplicate_update": False,
                }
            elif base_line is not None:
                changes_list = _compute_diff_in_memory(base_line, incoming)
                merged = _merge_lines_in_memory(base_line, incoming, tag="CAP NHAT")
                working_lines = [merged]
                if not changes_list:
                    processing_status = MessageStatus.PROCESSED.value
                    context_resolution = {
                        "understood": True,
                        "resolution_type": "UPDATE_DUPLICATE_SUPPRESSED",
                        "summary": "Thông tin cập nhật trùng khớp với bản trước đó -> Chống spam không gửi lại khách.",
                        "changes_list": [],
                        "target_container": merged.container_no,
                        "clarify_missing_container": False,
                        "is_duplicate_update": True,
                    }
                else:
                    if base_idx is not None:
                        next_virtual_jobs[base_idx] = _line_to_virtual_job(merged, "PROCESSED")
                    context_resolution = {
                        "understood": True,
                        "resolution_type": "UPDATE_DIFF",
                        "summary": f"Đã liên kết container {merged.container_no} từ {base_source} và tính diff {len(changes_list)} thay đổi.",
                        "changes_list": changes_list,
                        "target_container": merged.container_no,
                        "clarify_missing_container": False,
                        "is_duplicate_update": False,
                    }
            else:
                context_resolution = {
                    "understood": True,
                    "resolution_type": "UPDATE_WITHOUT_PRIOR_JOB",
                    "summary": f"Đã trích xuất container {incoming.container_no} cho lệnh cập nhật (chưa có ca gốc trong phiên để so sánh diff).",
                    "changes_list": [],
                    "target_container": incoming.container_no,
                    "clarify_missing_container": False,
                    "is_duplicate_update": False,
                }

        elif (resolved_intent == Intent.SUPPLEMENT or (quote_clean and incoming_incomplete)) and base_line is not None:
            incoming = validated_lines[0] if validated_lines else ExtractedContainerLine(line_text=raw_text)
            merged = _merge_lines_in_memory(base_line, incoming, tag="BO SUNG")
            working_lines = [merged]
            is_ok, missing = OutboundTemplateBuilder.check_core_fields_completeness(merged)
            job_status = MessageStatus.PROCESSED.value if is_ok else MessageStatus.NEEDS_REVIEW.value
            if base_idx is not None:
                next_virtual_jobs[base_idx] = _line_to_virtual_job(merged, job_status)
            else:
                next_virtual_jobs.append(_line_to_virtual_job(merged, job_status))
            context_resolution = {
                "understood": True,
                "resolution_type": "SUPPLEMENT_MERGE",
                "summary": f"Đã hiểu ngữ cảnh từ {base_source} và gộp bổ sung vào container {merged.container_no or 'N/A'}.",
                "changes_list": [f"Trạng thái sau gộp: {'Đủ trường' if is_ok else 'Còn thiếu: ' + ', '.join(missing)}"],
                "target_container": merged.container_no,
                "clarify_missing_container": False,
                "is_duplicate_update": False,
            }

        else:
            if len(working_lines) > 1 and any(ln.warehouse_hint or ln.customer_hint or ln.order_type for ln in working_lines):
                context_resolution["summary"] = (
                    f"Phân đoạn đa xe thành công ({len(working_lines)} container), giữ nguyên ngữ cảnh Kho/Khách/Lệnh chung."
                )

        # Tầng 5: Đối chiếu Kế hoạch & Danh mục Thật (Read-Only MySQL) + Map Kho
        plan_matches: list[dict[str, Any]] = []
        carrier_mismatch_detected = False
        any_unmatched_wh = False
        any_unmatched_cust = False
        any_ambiguous = False
        norm_sender_carrier = _norm_ascii(payload.carrier_hint)

        for ln in working_lines:
            wh_id, cust_id, u_wh, u_cust, amb = ExtractionHandler._enrich_from_catalog_and_plans(db, ln)

            # Kiểm tra AI Match Kho nếu bật AI và chưa khớp kho trong DB
            if not wh_id and ln.warehouse_hint and payload.allow_ai_fallback:
                warehouses = list(db.scalars(select(Warehouse).where(Warehouse.is_active.is_(True)).limit(60)).all())
                if warehouses:
                    aliases = list(db.scalars(select(WarehouseAlias)).all())
                    alias_by_wh: dict[int, list[str]] = {}
                    for al in aliases:
                        alias_by_wh.setdefault(al.warehouse_id, []).append(al.alias)
                    cands = [
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
                    wh_res = AIServiceClient.match_warehouse(
                        raw_address=ln.warehouse_hint,
                        carrier_id=None,
                        customer_id=cust_id,
                        candidate_warehouses=cands,
                    )
                    if wh_res and wh_res.matched and wh_res.warehouse_id:
                        wh_id = wh_res.warehouse_id
                        u_wh = False
                        ln.match_source = f"ai_{wh_res.source}"

            any_unmatched_wh = any_unmatched_wh or u_wh
            any_unmatched_cust = any_unmatched_cust or u_cust
            any_ambiguous = any_ambiguous or amb

            matched_plan = None
            if ln.container_no:
                matched_plan = db.scalar(
                    select(TransportPlan)
                    .where(TransportPlan.container_no == ln.container_no.strip().upper())
                    .order_by(TransportPlan.plan_date.desc(), TransportPlan.id.desc())
                )

            mismatch = False
            plan_carrier_name = None
            if matched_plan is not None:
                plan_carrier_name = matched_plan.fleet_partner or matched_plan.carrier_name
                if norm_sender_carrier and plan_carrier_name:
                    norm_plan_carrier = _norm_ascii(plan_carrier_name)
                    if norm_sender_carrier not in norm_plan_carrier and norm_plan_carrier not in norm_sender_carrier:
                        mismatch = True
                        carrier_mismatch_detected = True

            plan_matches.append(
                {
                    "container_no": ln.container_no,
                    "match_source": ln.match_source,
                    "plan_found": matched_plan is not None,
                    "plan_order_type": matched_plan.order_type if matched_plan else None,
                    "plan_customer": matched_plan.customer_name if matched_plan else None,
                    "plan_carrier": plan_carrier_name,
                    "carrier_mismatch": mismatch,
                }
            )

        # Lưu cập nhật danh sách ca ảo nếu đây là báo mới hoàn chỉnh/thiếu trường
        if (
            resolved_intent == Intent.PARSE_TRUCK_INFO
            and context_resolution["resolution_type"] == "NEW_DISPATCH"
            and working_lines
        ):
            for ln in working_lines:
                is_ok, _ = OutboundTemplateBuilder.check_core_fields_completeness(ln)
                st = MessageStatus.PROCESSED.value if (is_ok and not carrier_mismatch_detected) else MessageStatus.NEEDS_REVIEW.value
                existing_idx = next(
                    (
                        i
                        for i, vj in enumerate(next_virtual_jobs)
                        if ln.container_no and clean_container(vj.get("container_no")) == ln.container_no
                    ),
                    None,
                )
                vj_obj = _line_to_virtual_job(ln, st)
                if existing_idx is not None:
                    next_virtual_jobs[existing_idx] = vj_obj
                else:
                    next_virtual_jobs.append(vj_obj)

        # Tầng 6: Kiểm tra hoàn chỉnh & Tạo Preview Outputs
        all_warnings: list[str] = []
        incomplete_lines: list[ExtractedContainerLine] = []
        for ln in working_lines:
            is_ok, missing = OutboundTemplateBuilder.check_core_fields_completeness(ln)
            if not is_ok or ln.validation_status == ValidationStatus.INVALID.value:
                incomplete_lines.append(ln)
                for m_field in missing:
                    tag = f"MISSING:{m_field}"
                    if tag not in ln.warnings:
                        ln.warnings.append(tag)
            all_warnings.extend(ln.warnings)

        if resolved_intent == Intent.CANCEL_REQUEST or context_resolution["clarify_missing_container"]:
            pass
        elif carrier_mismatch_detected:
            processing_status = MessageStatus.NEEDS_REVIEW.value
            dhvt_alert_preview = (
                "[CANH BAO DHVT - CARRIER_MISMATCH]\n"
                f"Nhà xe gửi tin ('{payload.carrier_hint}') không khớp với kế hoạch trên TMS -> "
                "Hệ thống CHẶN gửi sang nhóm khách hàng."
            )
        elif incomplete_lines:
            processing_status = MessageStatus.NEEDS_REVIEW.value
            bot_reply_preview = OutboundTemplateBuilder.build_carrier_warning_reply(incomplete_lines)
        elif context_resolution["is_duplicate_update"]:
            processing_status = MessageStatus.PROCESSED.value
        elif context_resolution["resolution_type"] == "UPDATE_DIFF" and working_lines:
            ln0 = working_lines[0]
            customer_notif_preview = OutboundTemplateBuilder.build_update_notification(
                line=ln0,
                changes_list=context_resolution["changes_list"],
                customer_name=ln0.customer_hint or "Quý khách hàng",
                warehouse_name=ln0.warehouse_hint or "Kho khách hàng",
            )
            processing_status = MessageStatus.PROCESSED.value
        elif working_lines:
            rendered_msgs = [
                OutboundTemplateBuilder.build_customer_notification(
                    line=ln,
                    customer_name=ln.customer_hint or "Quý khách hàng",
                    warehouse_name=ln.warehouse_hint or "Kho khách hàng",
                )
                for ln in working_lines
            ]
            customer_notif_preview = "\n\n---\n\n".join(rendered_msgs)
            processing_status = MessageStatus.PROCESSED.value

        taxonomy = MessageTaxonomyAnalyzer.analyze(
            raw_text=raw_text,
            intent=resolved_intent,
            lines=working_lines,
            quote_msg_id="sandbox_quote" if quote_clean else None,
            unmatched_warehouse=any_unmatched_wh,
            unmatched_customer=any_unmatched_cust,
            ambiguous_route_match=any_ambiguous,
        )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        records_out = [
            {
                **ln.to_canonical_record(),
                "line_no": ln.line_no,
                "source_format": ln.source_format,
                "check_digit_valid": ln.check_digit_valid,
                "validation_status": ln.validation_status,
                "match_source": ln.match_source,
                "confidence": round(float(ln.confidence), 3),
                "warnings": ln.warnings,
            }
            for ln in working_lines
        ]

        return {
            "ok": True,
            "persisted": False,
            "effective_text": raw_text,
            "masked_text": masked_text,
            "processing_status": processing_status,
            "initial_intent": initial_intent.value,
            "resolved_intent": resolved_intent.value,
            "source_format": working_lines[0].source_format if working_lines else "tu_do",
            "ai_would_trigger": algo_should_ai,
            "ai_executed": ai_executed,
            "ai_service_status": ai_service_status,
            "model_name": used_model,
            "prompt_version": prompt_ver,
            "latency_ms": latency_ms,
            "ocr": ocr_stage,
            "context_resolution": context_resolution,
            "records": records_out,
            "plan_matches": plan_matches,
            "preview_outputs": {
                "bot_reply": bot_reply_preview,
                "customer_notification": customer_notif_preview,
                "dhvt_alert": dhvt_alert_preview,
            },
            "warnings": sorted(set(all_warnings)),
            "taxonomy": taxonomy,
            "virtual_jobs_next": next_virtual_jobs,
        }
    finally:
        # Đảm bảo tuyệt đối không có bất kỳ thay đổi nào được commit xuống MySQL
        db.rollback()
