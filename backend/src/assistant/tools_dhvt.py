"""Công cụ vận hành ĐHVT chỉ đọc; các con số xuất phát từ bản ghi thật."""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.patterns import CONT_REGEX, PHONE_PATTERN, PLATE_REGEX, TRAILER_PLATE_REGEX
from src.domain.rules import clean_container, clean_phone, clean_plate, compact_plate
from src.handlers.dhvt_service import (
    DhvtNotificationService,
    _resolve_reviewer_display_name,
    humanize_reason_text,
)
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    Carrier,
    ContainerJob,
    ExtractionRun,
    OutboundMessage,
    ReviewCase,
    TmsSyncLog,
    TransportPlan,
    User,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.zalo_dispatcher import ZaloDispatcher
from src.outbound.report_image_generator import HtmlReportImageGenerator

from .intent_router import local_date, normalize, strip_zalo_mentions
from .queries import plan_jobs, plan_outbounds, plans_statement, scoped_cases, scoped_jobs_statement
from .response_formatter import NOT_FOUND, format_plans, job_line, plan_line
from .schemas import AssistantReply, ScopeContext, ToolCall
from .tools_customer import summary


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Tạo khoảng ngày giờ Việt Nam theo quy ước datetime hiện tại của ORM."""
    start = datetime.combine(day, time.min, ZoneInfo("Asia/Ho_Chi_Minh")).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def appointment_minutes(value: str | None) -> int | None:
    """Chỉ so sánh giờ có định dạng chắc chắn, không bịa thời lượng làm hàng."""
    match = re.fullmatch(r"\s*(\d{1,2})(?:[:h](\d{2})?)?\s*", value or "")
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2] or 0)
    return hour * 60 + minute if hour < 24 and minute < 60 else None


def duplicate_rows(plans: list[TransportPlan]) -> list[str]:
    """Cảnh báo nghi trùng giờ; nhiều chuyến khác giờ không tự coi là lỗi."""
    groups = defaultdict(list)
    for p in plans:
        if p.planned_truck_plate:
            groups[compact_plate(p.planned_truck_plate)].append(p)
    rows = []
    for plate, group in groups.items():
        if len(group) < 2:
            continue
        times = [appointment_minutes(p.required_time or p.eta) for p in group]
        known = [t for t in times if t is not None]
        if len(set(known)) < len(known):
            rows.append(
                f"{plate}: nghi trùng giờ hẹn: "
                + ", ".join(p.order_code or str(p.id) for p in group)
            )
        elif None in times:
            rows.append(
                f"{plate}: nhiều lệnh thiếu giờ, cần kiểm tra: "
                + ", ".join(p.order_code or str(p.id) for p in group)
            )
    return rows


def _find_target_review_case_for_dhvt(
    db: Session,
    call: ToolCall,
    message: ZaloMessage,
) -> ReviewCase | None:
    """Xác định ca duyệt `PENDING` mục tiêu khi ĐHVT nhắn duyệt/sửa/hủy trực tiếp trên nhóm Zalo ĐHVT."""
    # 1. Theo quote_msg_id của tin báo duyệt từ Bot trong nhóm ĐHVT
    if message.quote_msg_id:
        q_mid = str(message.quote_msg_id).strip()
        open_cases = list(
            db.scalars(
                select(ReviewCase)
                .where(ReviewCase.status.in_(["PENDING", "pending"]))
                .order_by(ReviewCase.id.desc())
                .limit(50)
            ).all()
        )
        for rc in open_cases:
            d = rc.details if isinstance(rc.details, dict) else {}
            if str(d.get("dhvt_zalo_msg_id") or "") == q_mid:
                return rc
        om = db.scalar(select(OutboundMessage).where(OutboundMessage.review_zalo_msg_id == q_mid))
        if om:
            for rc in open_cases:
                d = rc.details if isinstance(rc.details, dict) else {}
                if str(d.get("outbound_message_id") or "") == str(om.id):
                    return rc

    # 2. Theo mã ca `#ID` nêu trực tiếp (nếu ghi rõ ID mà không tồn tại/không PENDING -> không tự đoán ca khác)
    if call.entities.case_id and str(call.entities.case_id).isdigit():
        rc = db.get(ReviewCase, int(call.entities.case_id))
        if rc and rc.status in ("PENDING", "pending"):
            return rc
        return None

    # 3. Theo số container hoặc mã lệnh RO/LO
    open_cases = list(
        db.scalars(
            select(ReviewCase)
            .where(ReviewCase.status.in_(["PENDING", "pending"]))
            .order_by(ReviewCase.id.desc())
            .limit(40)
        ).all()
    )
    if call.entities.container_no:
        target_cont = clean_container(call.entities.container_no) or call.entities.container_no.upper()
        for rc in open_cases:
            d = rc.details if isinstance(rc.details, dict) else {}
            if clean_container(str(d.get("container_no") or "")) == target_cont:
                return rc
            if rc.container_job_id:
                cj = db.get(ContainerJob, rc.container_job_id)
                if cj and clean_container(cj.container_no) == target_cont:
                    return rc
    if call.entities.order_code:
        target_ord = call.entities.order_code.strip().upper()
        for rc in open_cases:
            d = rc.details if isinstance(rc.details, dict) else {}
            if any(
                str(d.get(k) or "").strip().upper() == target_ord
                for k in ("order_code", "ro_order_code", "lo_order_code")
            ):
                return rc
            pid = d.get("selected_plan_id") or d.get("transport_plan_id")
            if pid and str(pid).isdigit():
                pl = db.get(TransportPlan, int(pid))
                if pl and (pl.order_code or "").strip().upper() == target_ord:
                    return rc

    # 4. Nếu chỉ có duy nhất 1 ca PENDING mới tạo trong 10 phút gần nhất -> chọn tự động
    cutoff = datetime.now() - timedelta(minutes=10)
    recent_open = [
        rc for rc in open_cases if rc.created_at and rc.created_at.replace(tzinfo=None) >= cutoff
    ]
    if len(recent_open) == 1:
        return recent_open[0]
    return None


def _execute_dhvt_direct_review_action(
    db: Session,
    scope: ScopeContext,
    call: ToolCall,
    message: ZaloMessage,
) -> AssistantReply:
    """Thực thi lệnh Duyệt / Sửa / Hủy / Từ chối trực tiếp từ nhân viên ĐHVT trên nhóm Zalo ĐHVT."""
    from fastapi import HTTPException
    from src.api.reviews import (
        RejectPayload,
        ReviewApprovePayload,
        approve_review_case,
        reject_review_case,
    )

    dhvt_user = db.scalar(
        select(User).where(User.zalo_user_id == message.sender_id, User.is_active.is_(True))
    )
    if dhvt_user is None or (dhvt_user.role or "").lower() not in ("dhvt", "admin"):
        return AssistantReply(
            text="Tài khoản Zalo của bạn chưa được gắn quyền ĐHVT/Admin nên không thể duyệt trực tiếp trên Zalo."
        )

    case_obj = _find_target_review_case_for_dhvt(db, call, message)
    if case_obj is None:
        return AssistantReply(
            text="Chưa xác định được ca cần xử lý. Vui lòng quote trực tiếp tin báo duyệt của Bot hoặc ghi kèm mã lệnh/số container (VD: 'duyệt LO2564' hoặc 'duyệt #ID')."
        )

    raw_text = strip_zalo_mentions(message.message_text or "").strip()
    norm_text = normalize(raw_text)
    zalo_sender_name = (
        getattr(message, "sender_name", None)
        or (message.raw_payload.get("sender_name") if isinstance(message.raw_payload, dict) else None)
    )
    actor_name = _resolve_reviewer_display_name(
        dhvt_user.full_name or dhvt_user.username,
        zalo_sender_name,
    )

    # Nhánh Từ chối / Hủy (trừ khi ca gốc là CANCEL_REQUEST và ĐHVT gõ "duyệt hủy" / "đồng ý hủy")
    is_cancel_case = case_obj.case_type in ("CANCEL_REQUEST", "CARRIER_CANCEL_OR_ISSUE")
    is_reject_cmd = bool(
        re.match(r"^(?:tu choi|khong duyet)\b", norm_text)
        or (re.match(r"^huy\b", norm_text) and not is_cancel_case)
    )
    if is_reject_cmd:
        reason_clean = re.sub(
            r"^(?:từ\s*chối|tu\s*choi|không\s*duyệt|khong\s*duyet|hủy|huy)\s*[:\-]?\s*",
            "",
            raw_text,
            flags=re.IGNORECASE,
        ).strip()
        try:
            final_reason = reason_clean or f"{actor_name} từ chối/hủy trực tiếp qua Zalo."
            reject_review_case(
                review_id=case_obj.id,
                payload=RejectPayload(
                    reason=final_reason,
                    operator_name=actor_name,
                    skip_dhvt_zalo_broadcast=True,
                ),
                current_user=dhvt_user,
                db=db,
            )
            return AssistantReply(
                text=DhvtNotificationService.render_dhvt_review_decision(
                    db=db,
                    case_obj=case_obj,
                    action_verb="từ chối / hủy yêu cầu",
                    actor_display=actor_name,
                    reason=reason_clean or None,
                )
            )
        except HTTPException as exc:
            return AssistantReply(
                text=f"[VSICO] - ⚙️ Không thể từ chối ca #{case_obj.id}: {exc.detail}"
            )

    # Nhánh Sửa kèm Duyệt hoặc Duyệt ngay ("ok", "oki", "duyệt", "đồng ý", "sửa xe ...")
    approve_kwargs: dict[str, str | bool | None] = {
        "operator_name": actor_name,
        "skip_dhvt_zalo_broadcast": True,
    }
    has_manual_edits = False
    if re.match(r"^(?:sua|chinh sua)\b", norm_text):
        tr_match = TRAILER_PLATE_REGEX.search(raw_text)
        if tr_match:
            approve_kwargs["trailer_plate"] = clean_plate(tr_match.group(0))
            has_manual_edits = True
        pl_match = PLATE_REGEX.search(raw_text)
        if pl_match:
            approve_kwargs["truck_plate"] = clean_plate(pl_match.group(0))
            has_manual_edits = True
        cont_match = CONT_REGEX.search(raw_text)
        if cont_match:
            approve_kwargs["container_no"] = clean_container(cont_match.group(0))
            has_manual_edits = True
        phones = [clean_phone(m.group(0)) for m in PHONE_PATTERN.finditer(raw_text)]
        phones = [p for p in phones if p]
        if phones:
            approve_kwargs["driver_phone"] = " | ".join(dict.fromkeys(phones))
            has_manual_edits = True
        drv_m = re.search(r"(?:tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|tx|tài|tai)\s*[:\-]?\s*([^\d,;/|\n]+)", raw_text, re.IGNORECASE)
        if drv_m:
            approve_kwargs["driver_name"] = drv_m.group(1).strip(" .,-:")
            has_manual_edits = True
        seal_m = re.search(r"\b(?:chì|chi|seal)\s*[:\-]?\s*([A-Za-z0-9\-]{4,20})\b", raw_text, re.IGNORECASE)
        if seal_m:
            approve_kwargs["seal_no"] = seal_m.group(1).upper()
            has_manual_edits = True

    try:
        approve_review_case(
            review_id=case_obj.id,
            payload=ReviewApprovePayload(**approve_kwargs),
            current_user=dhvt_user,
            db=db,
        )
        return AssistantReply(
            text=DhvtNotificationService.render_dhvt_review_decision(
                db=db,
                case_obj=case_obj,
                action_verb="sửa và duyệt" if has_manual_edits else "duyệt",
                actor_display=actor_name,
            )
        )
    except HTTPException as exc:
        short_url = DhvtNotificationService._short_entity_url("r", case_obj.id)
        return AssistantReply(
            text=(
                "[VSICO] - ⚙️ Chưa thể duyệt tự động yêu cầu này\n\n"
                f"{exc.detail}\n\n"
                f"🔗 Vui lòng xử lý trực tiếp trên Web: {short_url}"
            )
        )


def _execute_dhvt_remind_carrier(
    db: Session,
    scope: ScopeContext,
    call: ToolCall,
    message: ZaloMessage,
) -> AssistantReply:
    """Thực thi lệnh ĐHVT nhắc nhà xe bổ sung thông tin xe/container cho các lệnh thiếu trong ngày."""
    raw_text = strip_zalo_mentions(message.message_text or "").strip()
    norm_text = normalize(raw_text)
    target_date = call.entities.plan_date or local_date(scope.reference_time)

    plans_to_remind: list[TransportPlan] = []
    target_carrier: Carrier | None = None
    if call.entities.order_code:
        p = db.scalar(
            select(TransportPlan)
            .where(TransportPlan.order_code == call.entities.order_code.upper())
            .order_by(TransportPlan.id.desc())
        )
        if p:
            plans_to_remind = [p]
            if p.carrier_id:
                target_carrier = db.get(Carrier, p.carrier_id)
    else:
        carriers = list(db.scalars(select(Carrier).where(Carrier.is_active.is_(True))).all())
        for c in carriers:
            c_norm = normalize(c.short_name or c.name or "")
            if c_norm and len(c_norm) >= 3 and c_norm in norm_text:
                target_carrier = c
                break
        if target_carrier:
            plans_to_remind = list(
                db.scalars(
                    select(TransportPlan).where(
                        TransportPlan.carrier_id == target_carrier.id,
                        TransportPlan.plan_date == target_date,
                        or_(
                            TransportPlan.planned_truck_plate.is_(None),
                            TransportPlan.planned_truck_plate == "",
                            TransportPlan.driver_name.is_(None),
                            TransportPlan.driver_name == "",
                        ),
                    )
                ).all()
            )

    if not target_carrier and not plans_to_remind:
        return AssistantReply(
            text="Chưa xác định được nhà xe hoặc mã lệnh cần nhắc. Ví dụ: 'nhắc nhà xe Tuấn Hưng lệnh thiếu hôm nay' hoặc 'nhắc LO2564'."
        )

    carrier_grp: ZaloGroup | None = None
    if target_carrier:
        carrier_grp = db.scalar(
            select(ZaloGroup).where(
                ZaloGroup.is_active.is_(True),
                ZaloGroup.is_test.is_(False),
                ZaloGroup.group_role.in_(["SOURCE", "CARRIER", "source", "carrier"]),
                or_(
                    ZaloGroup.carrier_id == str(target_carrier.id),
                    ZaloGroup.carrier_id == str(target_carrier.tms_carrier_id or ""),
                ),
            )
        )
    if not plans_to_remind:
        return AssistantReply(
            text=f"Nhà xe {target_carrier.name if target_carrier else ''} hiện không có lệnh nào thiếu thông tin xe ngày {target_date}."
        )

    lines_txt = [
        f"• {p.order_code or p.id} · Cont: {p.container_no or 'Chưa có'} · Kho: {p.warehouse_name or p.delivery_address or '—'}"
        for p in plans_to_remind[:10]
    ]
    remind_msg = (
        f"[VSICO] - 📝 Nhắc bổ sung thông tin xe ({len(plans_to_remind)} lệnh ngày {target_date.strftime('%d/%m')})\n\n"
        + "\n".join(lines_txt)
        + "\n\n💬 Anh/chị nhắn 'mẫu <Mã lệnh>' để lấy mẫu báo xe nhanh nhé."
    )
    from src.handlers.carrier_flow_service import CarrierFlowService

    current_grp = db.get(ZaloGroup, scope.group_id)
    is_test_msg = CarrierFlowService.is_test_message(message, current_grp)
    sent_ok = False
    if carrier_grp and settings.AUTO_DISPATCH_OUTBOUND and not is_test_msg:
        sent_ok, _, _ = ZaloDispatcher.send_to_group(carrier_grp.zalo_group_id, remind_msg)

    cname = target_carrier.name if target_carrier else "nhà xe"
    if carrier_grp and sent_ok:
        return AssistantReply(
            text=(
                f"[VSICO] - ✅ Đã gửi tin nhắc tới nhóm '{carrier_grp.name}' ({cname}) "
                f"cho {len(plans_to_remind)} lệnh chưa đủ thông tin xe."
            )
        )
    return AssistantReply(
        text=(
            f"[VSICO] - 📝 Đã soạn nội dung nhắc {cname} ({len(plans_to_remind)} lệnh thiếu).\n\n"
            f"{remind_msg}"
        )
    )


def _pct_vi(part: int, total: int) -> str:
    """Tính tỷ lệ phần trăm tiếng Việt dạng 33,1%."""
    if not total or total <= 0:
        return "0,0%"
    return f"{(part / total) * 100:.1f}%".replace(".", ",")


def _plan_is_closed(plan: TransportPlan) -> bool:
    """Xác định lệnh đã đóng (đã bố trí đủ biển số xe và số container) hay vẫn đang mở."""
    has_plate = bool((plan.planned_truck_plate or "").strip())
    has_cont = bool((plan.container_no or "").strip())
    return has_plate and has_cont


def _short_province_label(name: str) -> str:
    """Rút gọn tiền tố Tỉnh / Thành phố để hiển thị gọn đẹp trên tin nhắn Zalo."""
    clean = (name or "").strip()
    for prefix in ("Thành phố ", "Tỉnh ", "TP. ", "TP "):
        if clean.startswith(prefix):
            return clean[len(prefix) :].strip()
    return clean


def _fmt_size_summary(plans: list[TransportPlan]) -> str:
    """Định dạng cỡ container dạng `9 cont 20' · 62 cont 40'`."""
    counts: dict[str, int] = {}
    for p in plans:
        sz = (p.container_size or "").strip()
        if sz:
            counts[sz] = counts.get(sz, 0) + 1
    if not counts:
        return ""
    parts = [f"{cnt} cont {sz}'" for sz, cnt in sorted(counts.items())]
    return " (" + " · ".join(parts) + ")"


def _plan_to_trip_row(p: TransportPlan) -> dict[str, str]:
    """Chuyển bản ghi TransportPlan sang dòng dữ liệu bảng ảnh PNG."""
    is_load = (p.order_type or "").lower() in ("dong", "load", "lo")
    sz = f" {p.container_size}'" if p.container_size else ""
    order_kind_vi = f"Đóng{sz}" if is_load else f"Trả{sz}"
    veh_parts = [x for x in (p.planned_truck_plate, p.driver_name) if x]
    veh_str = " · ".join(veh_parts) if veh_parts else "Chưa bố trí"
    if _plan_is_closed(p):
        st_vi = "Đã đóng"
    elif (p.planned_truck_plate or "").strip():
        st_vi = "Đang mở (đã có xe)"
    else:
        st_vi = "Đang mở (chờ xe)"
    return {
        "order_code": p.order_code or str(p.id),
        "order_type": order_kind_vi,
        "province": _short_province_label(p.province_name or "") or "—",
        "container_no": p.container_no or "Chưa có",
        "customer": p.customer_name or "—",
        "warehouse": p.warehouse_name or p.delivery_address or "—",
        "carrier_name": p.carrier_name or p.fleet_partner or "—",
        "vehicle": veh_str,
        "status": st_vi,
    }


def _count_sent_plans(db: Session, plan_ids: list[int]) -> int:
    """Đếm số lệnh đã phát hành thông báo SENT trong danh sách kế hoạch."""
    if not plan_ids:
        return 0
    from src.infrastructure.models import OutboundMessageItem

    id_strs = [str(pid) for pid in plan_ids]
    return (
        db.scalar(
            select(func.count(func.distinct(ContainerJob.raw_fields["transport_plan_id"].as_string())))
            .select_from(ContainerJob)
            .join(OutboundMessageItem)
            .join(OutboundMessage)
            .where(
                ContainerJob.raw_fields["transport_plan_id"].as_string().in_(id_strs),
                OutboundMessage.status == "SENT",
                OutboundMessage.message_kind != "answer",
            )
        )
        or 0
    )


def _run_dhvt_province_plans(
    db: Session,
    scope: ScopeContext,
    call: ToolCall,
    message: ZaloMessage,
) -> AssistantReply:
    """Trả về danh sách chi tiết các lệnh thuộc riêng 1 tỉnh/thành trong ngày kèm tỷ lệ % và ảnh PNG bảng lệnh."""
    from src.handlers.carrier_flow_service import CarrierFlowService

    target_date = call.entities.plan_date or local_date(scope.reference_time)
    date_short = target_date.strftime("%d/%m")
    prov = (call.entities.province_name or "").strip()

    if not prov:
        # Liệt kê nhanh các tỉnh đang có kế hoạch trong ngày để ĐHVT chọn
        day_plans = list(db.scalars(plans_statement(scope, call.entities)).all())
        prov_counts = Counter(_short_province_label(p.province_name) for p in day_plans if p.province_name)
        if not prov_counts:
            return AssistantReply(text=NOT_FOUND)
        top_list = ", ".join(f"{name} ({cnt})" for name, cnt in prov_counts.most_common(6))
        return AssistantReply(
            text=(
                f"[VSICO] - 🔍 Chưa xác định rõ tỉnh/thành cần xem chi tiết ngày {date_short}\n\n"
                f"Các địa phương đang có kế hoạch: {top_list}.\n\n"
                "💬 Anh/chị nhắn ví dụ: \"Chi tiết Hải Phòng\" hoặc \"Chi tiết lệnh Hưng Yên\" nhé."
            )
        )

    plans = list(db.scalars(plans_statement(scope, call.entities).order_by(TransportPlan.id)).all())
    prov_short = _short_province_label(prov)
    if not plans:
        return AssistantReply(
            text=(
                f"[VSICO] - 🔍 Không có lệnh vận chuyển nào tại {prov_short} ngày {date_short}\n\n"
                "💬 Anh/chị có thể hỏi \"Thống kê kế hoạch hôm nay\" để xem danh sách các tỉnh đang có lệnh."
            )
        )

    total = len(plans)
    returns = [p for p in plans if (p.order_type or "").lower() in ("tra", "return", "ro")]
    loads = [p for p in plans if (p.order_type or "").lower() in ("dong", "load", "lo")]
    assigned = sum(1 for p in plans if (p.planned_truck_plate or "").strip())
    unassigned = total - assigned
    closed = sum(1 for p in plans if _plan_is_closed(p))
    opened = total - closed
    sent = _count_sent_plans(db, [p.id for p in plans])

    header_lines = [
        f"[VSICO] - 📍 CHI TIẾT KẾ HOẠCH {prov_short.upper()} | {date_short}",
        "",
        f"🚛 {total} lệnh tại {prov_short}",
        f"✅ Đã bố trí xe: {assigned} ({_pct_vi(assigned, total)}) · ⏳ Chưa có xe: {unassigned} ({_pct_vi(unassigned, total)})",
        f"🔒 Lệnh đã đóng: {closed} ({_pct_vi(closed, total)}) · 🔓 Lệnh đang mở: {opened} ({_pct_vi(opened, total)})",
        f"📢 Đã phát hành thông báo: {sent}",
        "",
        f"Phân loại tại {prov_short}:",
        f"• Lệnh trả: {len(returns)} ({_pct_vi(len(returns), total)}){_fmt_size_summary(returns)}",
        f"• Lệnh đóng: {len(loads)} ({_pct_vi(len(loads), total)}){_fmt_size_summary(loads)}",
        "",
        "Danh sách lệnh trong ngày:",
    ]

    trip_rows = [_plan_to_trip_row(p) for p in plans]
    list_lines: list[str] = []
    prefix_text = "\n".join(header_lines) + "\n"
    footer_lines = [
        "",
        f"💬 Anh/chị có thể hỏi: \"Xem lệnh chưa có xe {prov_short}\" hoặc gửi mã lệnh để xem chi tiết.",
    ]
    footer_text = "\n".join(footer_lines)
    budget = 1850 - len(prefix_text) - len(footer_text)

    shown = 0
    for idx, (p, tr) in enumerate(zip(plans, trip_rows), start=1):
        cont_seg = f"Cont {p.container_no}" if p.container_no else "Chưa có cont"
        cust_seg = (p.customer_name or "").strip()
        line_str = f"{idx}. {tr['order_code']} ({tr['order_type']}) · {cont_seg}"
        if cust_seg:
            line_str += f" · {cust_seg[:26]}"
        line_str += f" · {tr['vehicle']} · {tr['status']}"
        if sum(len(x) + 1 for x in list_lines) + len(line_str) + 45 > budget:
            break
        list_lines.append(line_str)
        shown += 1

    if shown < total:
        list_lines.append(f"... Hiển thị {shown}/{total} lệnh (xem đủ bảng trong ảnh đính kèm).")

    # Tự động kết xuất PNG chi tiết tỉnh (chỉ gửi thật khi không phải test; Pytest tự định tuyến qua Proxy)
    current_grp = db.get(ZaloGroup, scope.group_id)
    is_test_msg = CarrierFlowService.is_test_message(message, current_grp)
    if settings.AUTO_DISPATCH_OUTBOUND and not is_test_msg:
        img_res = HtmlReportImageGenerator.render_province_detail_report(
            province_name=prov,
            report_date=str(target_date),
            total_plans=total,
            assigned_count=assigned,
            closed_count=closed,
            open_count=opened,
            load_count=len(loads),
            return_count=len(returns),
            trips=trip_rows,
        )
        if img_res.get("ok") and img_res.get("public_url"):
            ZaloDispatcher.send_image_to_group(
                group_id=scope.zalo_group_id,
                image_url=str(img_res["public_url"]),
                caption=f"[VSICO] - 📍 Bảng chi tiết {total} lệnh tại {prov_short} ngày {date_short}",
            )

    full_text = prefix_text + "\n".join(list_lines) + footer_text
    return AssistantReply(text=full_text, plan_ids=[str(p.id) for p in plans[:20]])


def run_dhvt(
    db: Session, scope: ScopeContext, call: ToolCall, message: ZaloMessage
) -> AssistantReply:
    """Thực thi O01–O17, bao gồm duyệt/sửa/hủy trực tiếp cho ĐHVT, thống kê ngày và chi tiết theo tỉnh."""
    name = call.intent
    if name == "dhvt_direct_review_action":
        return _execute_dhvt_direct_review_action(db, scope, call, message)
    if name == "dhvt_remind_carrier":
        return _execute_dhvt_remind_carrier(db, scope, call, message)
    if name == "dhvt_get_province_plans":
        return _run_dhvt_province_plans(db, scope, call, message)
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    start, end = day_bounds(call.entities.plan_date or local_date(scope.reference_time))
    stmt = plans_statement(scope, call.entities)
    if name in ("dhvt_get_daily_overview", "dhvt_get_entity_stats"):
        if name == "dhvt_get_entity_stats":
            return summary(db, scope, call)

        all_plans = list(db.scalars(stmt.order_by(TransportPlan.id)).all())
        if not all_plans:
            return AssistantReply(text=NOT_FOUND)

        target_date = call.entities.plan_date or local_date(scope.reference_time)
        date_short = target_date.strftime("%d/%m")
        total = len(all_plans)
        returns = [p for p in all_plans if (p.order_type or "").lower() in ("tra", "return", "ro")]
        loads = [p for p in all_plans if (p.order_type or "").lower() in ("dong", "load", "lo")]
        eligible = [
            p
            for p in returns
            if p.container_ownership != 2
            and p.container_warning
            not in ("empty_drop", "other_requested", "soc", "over_combined")
        ]
        assigned = sum(1 for p in all_plans if (p.planned_truck_plate or "").strip())
        unassigned = total - assigned
        closed = sum(1 for p in all_plans if _plan_is_closed(p))
        opened = total - closed
        sent = _count_sent_plans(db, [p.id for p in all_plans])

        region_labels = {1: "Miền Bắc", 2: "Miền Trung", 3: "Miền Nam"}
        region_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        province_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        carrier_missing: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        missing_veh_total = 0
        for p in all_plans:
            is_load = (p.order_type or "").lower() in ("dong", "load", "lo")
            is_ret = (p.order_type or "").lower() in ("tra", "return", "ro")
            reg_name = region_labels.get(p.region, "Chưa phân vùng") if p.region else "Chưa phân vùng"
            region_stats[reg_name][0] += 1
            if is_load:
                region_stats[reg_name][1] += 1
            elif is_ret:
                region_stats[reg_name][2] += 1
            if p.province_name:
                province_stats[p.province_name][0] += 1
                if is_load:
                    province_stats[p.province_name][1] += 1
                elif is_ret:
                    province_stats[p.province_name][2] += 1
            is_missing = not (p.planned_truck_plate and p.container_no)
            if is_missing:
                missing_veh_total += 1
            cname = p.carrier_name or p.fleet_partner or "Chưa gán nhà xe"
            carrier_missing[cname][0] += 1
            if is_missing:
                carrier_missing[cname][1] += 1

        sorted_regions = sorted(region_stats.items(), key=lambda x: x[1][0], reverse=True)
        sorted_provinces = sorted(province_stats.items(), key=lambda x: x[1][0], reverse=True)

        lines: list[str] = [
            f"[VSICO] - 📊 KẾ HOẠCH VẬN CHUYỂN | {date_short}",
            "",
            f"🚛 {total} lệnh vận chuyển",
            f"✅ Đã bố trí xe: {assigned} ({_pct_vi(assigned, total)})",
            f"⏳ Chưa có xe: {unassigned} ({_pct_vi(unassigned, total)})",
            f"🔒 Lệnh đã đóng: {closed} ({_pct_vi(closed, total)}) · 🔓 Lệnh đang mở: {opened} ({_pct_vi(opened, total)})",
            f"📢 Đã phát hành thông báo: {sent}",
            "",
            "Phân loại:",
            f"• Lệnh trả: {len(returns)} ({_pct_vi(len(returns), total)}){_fmt_size_summary(returns)}",
            f"• Lệnh đóng: {len(loads)} ({_pct_vi(len(loads), total)}){_fmt_size_summary(loads)}",
        ]

        if sorted_regions and (call.entities.group_by_region or len(sorted_regions) > 1):
            lines.append("")
            lines.append("Theo vùng/miền:")
            for r_name, counts in sorted_regions:
                lines.append(f"• {r_name}: {counts[0]} (đóng: {counts[1]} · trả: {counts[2]})")

        if sorted_provinces:
            lines.append("")
            if len(sorted_provinces) > 5:
                lines.append("Các địa phương có nhiều lệnh nhất:")
                for p_name, counts in sorted_provinces[:4]:
                    lines.append(f"📍 {_short_province_label(p_name)}: {counts[0]}")
                others_total = sum(counts[0] for _, counts in sorted_provinces[4:])
                lines.append(f"📍 Các tỉnh/thành còn lại: {others_total}")
            else:
                lines.append("Theo địa phương:")
                for p_name, counts in sorted_provinces:
                    lines.append(
                        f"📍 {_short_province_label(p_name)}: {counts[0]} (đóng: {counts[1]} · trả: {counts[2]})"
                    )

        lines.extend(
            [
                "",
                f"Cân đối vỏ: {len(eligible)} vỏ trả chưa có cảnh báo cấm ghép / {len(loads)} lệnh đóng cần vỏ.",
                "",
                "ℹ️ Số liệu chỉ phản ánh cân đối số lượng, chưa xác nhận ghép tuyến hoặc thời gian.",
                "",
                "💬 Anh/chị có thể hỏi:",
                "\"Xem lệnh chưa có xe\", \"Chi tiết Hải Phòng\" hoặc \"Đề xuất ghép vỏ\".",
            ]
        )

        # Kết xuất PNG tổng hợp gồm CẢ bảng thống kê tỷ lệ % lẫn bảng chi tiết các lệnh
        from src.handlers.carrier_flow_service import CarrierFlowService

        current_grp = db.get(ZaloGroup, scope.group_id)
        is_test_msg = CarrierFlowService.is_test_message(message, current_grp)
        if settings.AUTO_DISPATCH_OUTBOUND and not is_test_msg:
            trip_rows = [_plan_to_trip_row(p) for p in all_plans]
            img_res = HtmlReportImageGenerator.render_daily_stats_report(
                report_date=str(target_date),
                total_plans=total,
                load_count=len(loads),
                return_count=len(returns),
                missing_vehicle_count=missing_veh_total,
                assigned_count=assigned,
                closed_count=closed,
                open_count=opened,
                region_rows=[(r, c[0], c[1], c[2]) for r, c in sorted_regions],
                province_rows=[(p, c[0], c[1], c[2]) for p, c in sorted_provinces],
                incomplete_carriers=[
                    (c_name, vals[0], vals[1])
                    for c_name, vals in sorted(carrier_missing.items(), key=lambda x: x[1][1], reverse=True)
                    if vals[1] > 0
                ],
                trips=trip_rows,
            )
            if img_res.get("ok") and img_res.get("public_url"):
                ZaloDispatcher.send_image_to_group(
                    group_id=scope.zalo_group_id,
                    image_url=str(img_res["public_url"]),
                    caption=f"[VSICO] - 📊 Bảng thống kê & danh sách lệnh ngày {date_short}",
                )

        return AssistantReply(text="\n".join(lines), plan_ids=[str(p.id) for p in all_plans[:20]])
    if name == "dhvt_get_priority_digest":
        cases = scoped_cases(db, scope, call.entities, pending=True)
        pending = (
            db.scalar(
                select(func.count()).select_from(ReviewCase).where(ReviewCase.status == "PENDING")
            )
            or 0
        )
        high = (
            db.scalar(
                select(func.count())
                .select_from(ReviewCase)
                .where(
                    ReviewCase.status == "PENDING",
                    ReviewCase.details["priority"].as_string() == "HIGH",
                )
            )
            or 0
        )
        failed = (
            db.scalar(
                select(func.count())
                .select_from(OutboundMessage)
                .where(OutboundMessage.status == "FAILED")
            )
            or 0
        )
        overdue = (
            db.scalar(
                select(func.count())
                .select_from(BotReply)
                .where(BotReply.status == "PENDING", BotReply.fix_deadline < datetime.now())
            )
            or 0
        )
        case_lines: list[str] = []
        for idx_c, c in enumerate(cases[:10], 1):
            ctx = DhvtNotificationService._resolve_review_case_context(db=db, case_obj=c)
            short_link = DhvtNotificationService._short_entity_url("r", c.id)
            lbl = ctx.get("order_label") or f"#{c.id}"
            cont = ctx.get("container_no") or "Chưa có cont"
            src = ctx.get("source_group_name") or ctx.get("carrier_name") or "Chưa rõ nhóm"
            case_lines.append(
                f"{idx_c}. {lbl} | {cont} | Nhóm: {src} | {humanize_reason_text(c.reason)[:70]} -> {short_link}"
            )
        return AssistantReply(
            text=f"Tổng hợp hàng chờ ĐHVT: {pending} ca chờ (ưu tiên cao: {high} | gửi lỗi: {failed} | quá hạn: {overdue}).\n"
            + ("\n".join(case_lines) if case_lines else "Hiện không có ca nào đang chờ duyệt.")
        )
    if name == "dhvt_explain_review_case":
        if not call.entities.case_id:
            return AssistantReply(text="Vui lòng ghi mã ca, ví dụ: tại sao ca #123 cần duyệt?")
        cases = scoped_cases(db, scope, call.entities)
        if not cases:
            return AssistantReply(text=NOT_FOUND)
        c = cases[0]
        details = c.details or {}
        candidates = (
            details.get("candidate_plans")
            or details.get("candidate_plan_ids")
            or (details.get("resolution") or {}).get("candidates")
            or []
        )
        return AssistantReply(
            text=f"Ca #{c.id}: {c.status}\n{c.reason}\nỨng viên: {str(candidates)[:1500]}\n{base}/reviews/{c.id}"
        )
    if name == "dhvt_get_delivery_and_sync_errors":
        outs = list(
            db.scalars(
                select(OutboundMessage)
                .where(
                    OutboundMessage.created_at >= start,
                    OutboundMessage.created_at < end,
                    OutboundMessage.status == "FAILED",
                )
                .order_by(OutboundMessage.id.desc())
                .limit(20)
            ).all()
        )
        pending = list(
            db.scalars(
                stmt.where(TransportPlan.tms_sync_status.in_(["PENDING", "FAILED"])).limit(21)
            ).all()
        )
        rows = [f"Tin #{o.id}: FAILED — {base}/outbound" for o in outs]
        rows += [f"{p.order_code or p.id}: TMS {p.tms_sync_status}" for p in pending[:20]]
        logs = list(
            db.scalars(
                select(TmsSyncLog)
                .where(
                    TmsSyncLog.created_at >= start,
                    TmsSyncLog.created_at < end,
                    TmsSyncLog.status == "FAILED",
                )
                .order_by(TmsSyncLog.id.desc())
                .limit(10)
            ).all()
        )
        rows += [
            f"TMS log #{log.id}: job #{log.container_job_id}, HTTP {log.http_status or 'không có phản hồi'}"
            for log in logs
        ]
        if len(pending) > 20:
            rows.append("Còn kế hoạch khác chờ đồng bộ; xem đầy đủ trên Web /plans.")
        return AssistantReply(
            text="\n".join(rows)
            or "Không có lỗi gửi hoặc kế hoạch chờ/lỗi đồng bộ trong ngày tra cứu."
        )
    if name == "dhvt_get_validation_failures":
        jobs = list(
            db.scalars(
                select(ContainerJob)
                .where(
                    ContainerJob.created_at >= start,
                    ContainerJob.created_at < end,
                    ContainerJob.validation_status != "VALID",
                )
                .limit(21)
            ).all()
        )
        return AssistantReply(
            text="\n".join(
                f"Job #{j.id}: {j.container_no or 'Chưa có cont'} — {j.validation_status}"
                for j in jobs[:20]
            )
            or "Không có bản ghi kiểm tra lỗi trong ngày tra cứu."
        )
    if name == "dhvt_get_bot_performance":
        runs = list(
            db.scalars(
                select(ExtractionRun).where(
                    ExtractionRun.started_at >= start, ExtractionRun.started_at < end
                )
            ).all()
        )
        counts = Counter()
        latencies = []
        for r in runs:
            model = (r.model_name or "").lower()
            tier = (r.output_data or {}).get("extractor_type")
            if not tier:
                tier = (
                    "local_nlp"
                    if "local-nlp" in model
                    else "rule"
                    if ("rule" in model or "heuristic" in model or "gatekeeper" in model)
                    else "llm"
                    if any(x in model for x in ("gemini", "gpt", "llm"))
                    else "unknown"
                )
            counts[tier] += 1
            if isinstance((r.output_data or {}).get("latency_ms"), (int, float)):
                latencies.append(r.output_data["latency_ms"])
            elif r.finished_at and r.started_at:
                latencies.append((r.finished_at - r.started_at).total_seconds() * 1000)
        messages = (
            db.scalar(
                select(func.count())
                .select_from(ZaloMessage)
                .where(ZaloMessage.created_at >= start, ZaloMessage.created_at < end)
            )
            or 0
        )
        errors = sum(bool(r.error_message) for r in runs)
        rate = f"{100 * counts['llm'] / len(runs):.1f}%" if runs else "Chưa có dữ liệu"
        return AssistantReply(
            text=f"Ngày {call.entities.plan_date}: {messages} tin; {len(runs)} lượt bóc tách.\n"
            f"Rule: {counts['rule']}; NLP local: {counts['local_nlp']}; LLM: {counts['llm']}; chưa phân loại: {counts['unknown']}.\n"
            f"Tỷ lệ LLM theo lượt: {rate}; lượt lỗi: {errors}.\n"
            + (
                f"Thời gian trung bình: {sum(latencies) / len(latencies):.0f} ms."
                if latencies
                else "Chưa có số đo thời gian."
            )
            + "\nKhông suy tỷ lệ ghép đúng từ số lượt chạy; cần bộ dữ liệu đã gán nhãn."
        )
    if name == "dhvt_get_unassigned_plans":
        stmt = stmt.where(
            or_(
                TransportPlan.planned_truck_plate.is_(None),
                TransportPlan.planned_truck_plate == "",
                TransportPlan.container_no.is_(None),
                TransportPlan.container_no == "",
            )
        )
    if name == "dhvt_get_container_warnings":
        stmt = stmt.where(
            or_(
                TransportPlan.container_warning.in_(
                    ["empty_drop", "over_combined", "other_requested", "soc"]
                ),
                TransportPlan.container_ownership == 2,
            )
        )
    plans = list(db.scalars(stmt.order_by(TransportPlan.id)).all())
    if name == "dhvt_detect_duplicate_vehicles":
        rows = duplicate_rows(plans)
        return AssistantReply(
            text="\n".join(rows[:20])
            or "Chưa phát hiện trùng giờ hẹn. Không có dữ liệu thời lượng/GPS để khẳng định lịch không chồng lấn."
        )
    if name == "dhvt_get_audit_timeline":
        if not (call.entities.order_code or call.entities.container_no or call.entities.plate_no):
            return AssistantReply(text="Vui lòng ghi mã lệnh, cont hoặc biển số để xem lịch sử.")
        ids = [str(p.id) for p in plans]
        logs = (
            list(
                db.scalars(
                    select(ActivityLog)
                    .where(
                        ActivityLog.entity_type == "transport_plan", ActivityLog.entity_id.in_(ids)
                    )
                    .order_by(ActivityLog.created_at.desc())
                    .limit(20)
                ).all()
            )
            if ids
            else []
        )
        events = [
            (a.created_at, f"{a.actor_id} — {a.action}: {str(a.details)[:500]}") for a in logs
        ]
        mids = {j.message_id for p in plans for j in plan_jobs(db, p)}
        if mids:
            for r in db.scalars(
                select(BotReply)
                .where(BotReply.message_id.in_(mids))
                .order_by(BotReply.id.desc())
                .limit(20)
            ).all():
                events.append((r.created_at, f"Bot nhắc ({r.status}): {r.reply_text[:250]}"))
            for r in db.scalars(
                select(ExtractionRun)
                .where(ExtractionRun.message_id.in_(mids))
                .order_by(ExtractionRun.id.desc())
                .limit(20)
            ).all():
                events.append((r.started_at, f"Bóc tách {r.model_name}: {r.status}"))
        events.sort(key=lambda entry: entry[0].replace(tzinfo=None), reverse=True)
        return AssistantReply(
            text="\n".join(f"{at}: {text}" for at, text in events[:20]) or NOT_FOUND
        )
    if name == "dhvt_analyze_change_impact":
        if len(plans) != 1:
            return AssistantReply(
                text="Vui lòng chỉ rõ một mã lệnh và ngày để phân tích ảnh hưởng; chưa thay đổi dữ liệu."
            )
        p = plans[0]
        paired = (
            list(
                db.scalars(
                    select(TransportPlan).where(
                        TransportPlan.container_no == p.container_no,
                        TransportPlan.plan_date == p.plan_date,
                        TransportPlan.id != p.id,
                    )
                ).all()
            )
            if p.container_no
            else []
        )
        sent = sum(o.status == "SENT" for o in plan_outbounds(db, p))
        return AssistantReply(
            text=f"{plan_line(p)}\nTMS: {p.tms_sync_status}; đã phát hành: {sent} tin.\n"
            f"Lệnh khác cùng cont trong ngày (chưa khẳng định kết hợp): {', '.join(q.order_code or str(q.id) for q in paired) or 'Không có'}.\n"
            f"Đây là phân tích chỉ đọc. Thao tác tại {base}/plans"
        )
    reply = format_plans(plans, f"Kế hoạch {call.entities.plan_date}:", detail=True)
    if name == "dhvt_get_container_warnings":
        labels = {
            "empty_drop": "Chỉ định hạ rỗng",
            "other_requested": "Bên khác đã xin",
            "soc": "Vỏ SOC",
            "over_combined": "Quá số lượng kết hợp",
        }
        reply.text += "\n" + "\n".join(
            f"{p.order_code or p.container_no or p.id}: "
            + (
                "Vỏ SOC"
                if p.container_ownership == 2
                else labels.get(p.container_warning, p.container_warning or "")
            )
            for p in plans[:20]
        )
    if name in ("dhvt_get_order_or_cont_detail", "dhvt_get_vehicle_trips"):
        jobs = list(
            db.scalars(
                scoped_jobs_statement(scope, call.entities)
                .order_by(ContainerJob.id.desc())
                .limit(3)
            ).all()
        )
        if jobs:
            if not plans:
                reply.text = "Thông tin nhà xe đã báo:"
            reply.text += "\n" + "\n".join(job_line(j) for j in jobs)
    return reply
