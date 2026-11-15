"""Công cụ vận hành ĐHVT chỉ đọc; các con số xuất phát từ bản ghi thật."""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.rules import compact_plate
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    ContainerJob,
    ExtractionRun,
    OutboundMessage,
    ReviewCase,
    TmsSyncLog,
    TransportPlan,
    ZaloMessage,
)

from .intent_router import local_date
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


def run_dhvt(
    db: Session, scope: ScopeContext, call: ToolCall, message: ZaloMessage
) -> AssistantReply:
    """Thực thi O01–O14, tuyệt đối không sửa kế hoạch hay trạng thái duyệt."""
    name = call.intent
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    start, end = day_bounds(call.entities.plan_date or local_date(scope.reference_time))
    stmt = plans_statement(scope, call.entities)
    if name in ("dhvt_get_daily_overview", "dhvt_get_entity_stats"):
        reply = summary(db, scope, call)
        if name == "dhvt_get_daily_overview":
            all_plans = list(db.scalars(stmt).all())
            returns = [p for p in all_plans if (p.order_type or "").lower() in ("tra", "return", "ro")]
            loads = [p for p in all_plans if (p.order_type or "").lower() in ("dong", "load", "lo")]
            eligible = [
                p
                for p in returns
                if p.container_ownership != 2
                and p.container_warning
                not in ("empty_drop", "other_requested", "soc", "over_combined")
            ]
            reply.text += (
                f"\nTổng số lệnh: {len(all_plans)} | Số lệnh đóng (LO): {len(loads)} | Số lệnh trả (RO): {len(returns)}."
            )
            reply.text += f"\nVỏ trả: {len(returns)}; chưa có cảnh báo cấm ghép: {len(eligible)}; nhu cầu đóng: {len(loads)}."
            region_labels = {1: "Miền Bắc", 2: "Miền Trung", 3: "Miền Nam"}
            region_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
            province_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
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
            if region_stats:
                reg_lines = [
                    f"- {r_name}: tổng {counts[0]} lệnh (đóng: {counts[1]}, trả: {counts[2]})"
                    for r_name, counts in sorted(region_stats.items(), key=lambda x: x[1][0], reverse=True)
                ]
                reply.text += "\nThống kê theo vùng/miền:\n" + "\n".join(reg_lines)
            if province_stats:
                prov_lines = [
                    f"- {p_name}: tổng {counts[0]} lệnh (đóng: {counts[1]}, trả: {counts[2]})"
                    for p_name, counts in sorted(province_stats.items(), key=lambda x: x[1][0], reverse=True)
                ]
                reply.text += "\nThống kê theo tỉnh/thành:\n" + "\n".join(prov_lines)
            reply.text += (
                "\nĐây là cân đối số lượng, chưa xác nhận ghép tuyến/thời gian cho từng vỏ."
            )
        return reply
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
        return AssistantReply(
            text=f"Tổng hợp hàng chờ ĐHVT (hiện tại): {pending} ca; ưu tiên HIGH: {high}; "
            f"gửi lỗi: {failed}; nhắc quá hạn: {overdue}.\n"
            + "\n".join(f"#{c.id}: {c.case_type} — {base}/reviews/{c.id}" for c in cases[:10])
            + f"\n{base}/reviews"
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
