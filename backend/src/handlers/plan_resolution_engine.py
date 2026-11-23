"""Bộ đối chiếu kế hoạch 6 nhánh (TH1–TH6), hỗ trợ chuyến kết hợp RO->LO và đa chặng."""

from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_container
from src.parsing.local_nlp_extractor import normalized


@dataclass
class Candidate:
    """Ứng viên kế hoạch kèm điểm, bằng chứng khớp và lý do loại trừ."""

    plan_id: str
    score: int = 0
    evidences: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    order_code: str | None = None
    order_type: str | None = None
    customer_name: str | None = None
    warehouse_name: str | None = None
    container_no: str | None = None
    plan_date: str | None = None
    required_time: str | None = None


@dataclass
class Resolution:
    """Kết quả đối chiếu kế hoạch, luôn kèm câu hỏi hoặc lý do leo thang rõ ràng."""

    action: str
    branch: str
    selected_plan_id: str | None = None
    secondary_plan_id: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    reason: str = ""
    question: str | None = None


def order_kind(value: str | None) -> str:
    """Chuẩn hóa tên loại lệnh khác nhau trong DB và parser về RO/LO."""
    clean = normalized(value)
    if clean in ("load", "dong", "lo", "xuat"):
        return "LO"
    if clean in ("return", "tra", "ro", "nhap"):
        return "RO"
    return ""


def _levenshtein(a: str, b: str) -> int:
    """Tính khoảng cách chỉnh sửa giữa hai số container."""
    if a == b:
        return 0
    rows = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, rows[0] = rows[0], i
        for j, cb in enumerate(b, 1):
            prev, rows[j] = rows[j], min(rows[j] + 1, rows[j - 1] + 1, prev + (ca != cb))
    return rows[-1]


def _fuzzy_location_match(hint: str | None, *plan_fields: str | None) -> tuple[bool, int]:
    """Kiểm tra khớp tên kho/địa chỉ/xã/tỉnh bằng chứa chuỗi hoặc RapidFuzz >= 86."""
    h_norm = normalized(hint)
    if not h_norm or len(h_norm) < 2:
        return False, 0
    best = 0.0
    for f in plan_fields:
        f_norm = normalized(f)
        if not f_norm:
            continue
        if h_norm in f_norm or f_norm in h_norm:
            return True, 35
        rf = max(fuzz.WRatio(h_norm, f_norm), fuzz.token_set_ratio(h_norm, f_norm))
        if rf > best:
            best = float(rf)
    if best >= 86.0:
        return True, 35 if best >= 92.0 else 28
    return False, 0


def _fuzzy_customer_match(hint: str | None, customer_name: str | None) -> bool:
    """Kiểm tra khớp tên khách hàng bằng chứa chuỗi hoặc RapidFuzz >= 86."""
    h_norm = normalized(hint)
    c_norm = normalized(customer_name)
    if not h_norm or not c_norm:
        return False
    if h_norm in c_norm or c_norm in h_norm:
        return True
    return max(fuzz.WRatio(h_norm, c_norm), fuzz.token_set_ratio(h_norm, c_norm)) >= 86.0


def _warning_label_vi(warn_code: str | None) -> str:
    """Dịch mã cảnh báo vỏ trả sang nhãn tiếng Việt tự nhiên, không lộ mã nội bộ."""
    mapping = {
        "empty_drop": "chỉ định hạ rỗng (không tự ghép đóng hàng)",
        "over_combined": "vượt số lượng ghép kết hợp",
        "other_requested": "đã được đơn vị khác đăng ký",
        "soc": "vỏ thuộc sở hữu chủ hàng",
    }
    return mapping.get((warn_code or "").strip().lower(), "cảnh báo cấm ghép vỏ trả")


def _is_reuse_blocked(plan: Any) -> tuple[bool, str]:
    """Kiểm tra vỏ từ lệnh trả có bị cấm ghép sang lệnh đóng hay không."""
    warning = getattr(plan, "container_warning", None)
    ownership = getattr(plan, "container_ownership", None)
    if ownership == 2:
        return True, "soc"
    if warning in ("empty_drop", "other_requested", "soc", "over_combined"):
        return True, str(warning)
    return False, ""


class PlanResolutionEngine:
    """Không tự chọn dòng đầu tiên; chỉ AUTO_COMMIT khi đủ điểm và cách biệt rõ."""

    @classmethod
    def _score_candidate(
        cls,
        line: ExtractedContainerLine,
        plan: Any,
        carrier_id: int | None,
        dates: list[str],
        cont: str | None,
        kind: str,
        target_kind_override: str | None = None,
    ) -> Candidate:
        """Chấm điểm một dòng kế hoạch ứng viên kèm danh sách bằng chứng và loại trừ."""
        c = Candidate(
            plan_id=str(plan.id),
            order_code=getattr(plan, "order_code", None),
            order_type=getattr(plan, "order_type", None),
            customer_name=getattr(plan, "customer_name", None),
            warehouse_name=getattr(plan, "warehouse_name", None)
            or getattr(plan, "delivery_address", None),
            container_no=getattr(plan, "container_no", None),
            plan_date=(
                plan.plan_date.isoformat()
                if getattr(plan, "plan_date", None) and hasattr(plan.plan_date, "isoformat")
                else (str(getattr(plan, "plan_date", "")) or None)
            ),
            required_time=getattr(plan, "required_time", None)
            or getattr(plan, "estimated_drop_time", None)
            or getattr(plan, "eta", None),
        )
        p_cont = clean_container(getattr(plan, "container_no", None))
        p_kind = order_kind(getattr(plan, "order_type", None))
        effective_kind = target_kind_override or kind

        if carrier_id and getattr(plan, "carrier_id", None) not in (None, carrier_id):
            c.exclusions.append("CARRIER_MISMATCH")
        if dates and str(getattr(plan, "plan_date", "")) not in dates:
            c.exclusions.append("DATE_OUT_OF_WINDOW")
        if effective_kind and p_kind and effective_kind != p_kind:
            c.exclusions.append("ORDER_TYPE_MISMATCH")
        if (
            line.canonical_cont_size
            and getattr(plan, "container_size", None)
            and not str(plan.container_size).startswith(line.canonical_cont_size)
        ):
            c.exclusions.append("SIZE_MISMATCH")

        if cont and p_cont == cont:
            c.score += 100
            c.evidences.append("container_exact")
        elif cont and p_cont and p_cont != cont:
            c.exclusions.append("CONTAINER_OCCUPIED")

        if line.transport_plan_id and str(line.transport_plan_id) == str(plan.id):
            c.score += 80
            c.evidences.append("linked_plan")

        if (
            line.booking_no
            and normalized(line.booking_no) == normalized(getattr(plan, "booking_no", None))
        ):
            c.score += 65
            c.evidences.append("booking_exact")

        if (
            line.customer_code_or_id and getattr(plan, "customer_id", None) == line.customer_code_or_id
        ) or _fuzzy_customer_match(line.customer_hint, getattr(plan, "customer_name", None)):
            c.score += 30
            c.evidences.append("customer_match")

        wh_matched = bool(
            line.warehouse_code_or_id
            and getattr(plan, "warehouse_id", None) == line.warehouse_code_or_id
        )
        wh_pts = 35 if wh_matched else 0
        if not wh_matched:
            wh_matched, wh_pts = _fuzzy_location_match(
                line.warehouse_hint,
                getattr(plan, "warehouse_name", None),
                getattr(plan, "delivery_address", None),
                getattr(plan, "ward_name", None),
                getattr(plan, "province_name", None),
            )
        if wh_matched:
            c.score += wh_pts
            c.evidences.append("warehouse_match")

        if line.canonical_cont_size and str(getattr(plan, "container_size", "")).startswith(
            line.canonical_cont_size
        ):
            c.score += 15
            c.evidences.append("size_match")

        if (
            line.eta_time
            and getattr(plan, "required_time", None)
            and line.eta_time[:2] == str(plan.required_time)[:2]
        ):
            c.score += 15
            c.evidences.append("time_match")

        if effective_kind == "LO" and not getattr(plan, "planned_truck_plate", None):
            c.score += 10
            c.evidences.append("open_vehicle_slot")

        return c

    @classmethod
    def resolve(
        cls,
        line: ExtractedContainerLine,
        plans: list[Any],
        carrier_id: int | None,
        dates: list[str],
        shadow: bool = True,
    ) -> Resolution:
        """Xếp hạng ứng viên qua 6 nhánh (TH1–TH6) và quyết định tự động, hỏi lại hoặc chuyển Web."""
        if "context_reference" in line.unresolved_fields:
            return Resolution(
                "ASK_CARRIER",
                "COREFERENCE_UNRESOLVED",
                reason="Tham chiếu ngữ cảnh chưa đủ định danh một kế hoạch.",
                question="Vui lòng ghi rõ biển số xe, số container hoặc tên kho cụ thể.",
            )
        if any(f.startswith("ambiguous_") for f in line.unresolved_fields):
            return Resolution(
                "ASK_CARRIER",
                "AMBIGUOUS_ENTITY",
                reason=f"Thực thể mơ hồ ({', '.join(line.unresolved_fields)}).",
                question="Vui lòng ghi rõ tên kho/khách hàng hoặc đầy đủ biển số xe.",
            )

        cont = clean_container(line.container_no)
        kind = order_kind(line.order_type)

        # Kiểm tra sự xuất hiện của container trong tập kế hoạch thuộc nhà xe & ngày ứng viên
        carrier_plans = [
            p
            for p in plans
            if (not carrier_id or getattr(p, "carrier_id", None) in (None, carrier_id))
            and (not dates or str(getattr(p, "plan_date", "")) in dates)
        ]
        exact_ro = [
            p
            for p in carrier_plans
            if cont
            and clean_container(getattr(p, "container_no", None)) == cont
            and order_kind(getattr(p, "order_type", None)) == "RO"
        ]
        exact_lo = [
            p
            for p in carrier_plans
            if cont
            and clean_container(getattr(p, "container_no", None)) == cont
            and order_kind(getattr(p, "order_type", None)) == "LO"
        ]

        # -------------------------------------------------------------------
        # TH1: Số container xuất hiện đồng thời ở cả Lệnh trả (RO) và Lệnh đóng (LO)
        # -------------------------------------------------------------------
        if cont and exact_ro and exact_lo:
            ro_plan = exact_ro[0]
            lo_plan = exact_lo[0]
            blocked, warn_code = _is_reuse_blocked(ro_plan)
            if line.is_combined_from_return:
                if blocked:
                    cand = cls._score_candidate(line, lo_plan, carrier_id, dates, cont, "LO", "LO")
                    cand.exclusions.append("CONTAINER_REUSE_BLOCKED")
                    return Resolution(
                        "ESCALATE_DHVT_WEB",
                        "TH1_BLOCKED_CONTAINER_WARNING",
                        selected_plan_id=str(lo_plan.id),
                        secondary_plan_id=str(ro_plan.id),
                        candidates=[cand],
                        reason=f"Vỏ trả {cont} đang có {_warning_label_vi(warn_code)}; cần ĐHVT xác nhận trước khi ghép lệnh đóng.",
                    )
                cand_lo = cls._score_candidate(line, lo_plan, carrier_id, dates, cont, "LO", "LO")
                cand_ro = cls._score_candidate(line, ro_plan, carrier_id, dates, cont, "RO", "RO")
                action = "ESCALATE_DHVT_WEB" if shadow else "AUTO_COMMIT"
                return Resolution(
                    action,
                    "TH1_COMBINED_RO_LO",
                    selected_plan_id=str(lo_plan.id),
                    secondary_plan_id=str(ro_plan.id),
                    candidates=[cand_lo, cand_ro],
                    reason="Chuyến kết hợp RO -> LO cùng số container trên cả hai kế hoạch.",
                )

            # Phân biệt chặng RO hay LO theo từ khóa loại lệnh hoặc điểm khớp kho/khách
            cand_ro = cls._score_candidate(line, ro_plan, carrier_id, dates, cont, kind, "RO")
            cand_lo = cls._score_candidate(line, lo_plan, carrier_id, dates, cont, kind, "LO")
            if kind == "RO" and cand_ro.score >= cand_lo.score:
                return Resolution(
                    "AUTO_COMMIT",
                    "TH1_RO_SELECTED",
                    selected_plan_id=str(ro_plan.id),
                    secondary_plan_id=str(lo_plan.id),
                    candidates=[cand_ro, cand_lo],
                    reason="Chọn chặng lệnh trả (RO) theo từ khóa/địa điểm.",
                )
            if kind == "LO" and cand_lo.score >= cand_ro.score:
                if blocked:
                    cand_lo.exclusions.append("CONTAINER_REUSE_BLOCKED")
                    return Resolution(
                        "ESCALATE_DHVT_WEB",
                        "TH1_BLOCKED_CONTAINER_WARNING",
                        selected_plan_id=str(lo_plan.id),
                        secondary_plan_id=str(ro_plan.id),
                        candidates=[cand_lo, cand_ro],
                        reason=f"Vỏ {cont} trên lệnh trả đang có {_warning_label_vi(warn_code)}; cần ĐHVT xác nhận.",
                    )
                return Resolution(
                    "AUTO_COMMIT",
                    "TH1_LO_SELECTED",
                    selected_plan_id=str(lo_plan.id),
                    secondary_plan_id=str(ro_plan.id),
                    candidates=[cand_lo, cand_ro],
                    reason="Chọn chặng lệnh đóng (LO) theo từ khóa/địa điểm.",
                )
            if abs(cand_ro.score - cand_lo.score) >= 18:
                winner = cand_ro if cand_ro.score > cand_lo.score else cand_lo
                runner = cand_lo if winner is cand_ro else cand_ro
                return Resolution(
                    "AUTO_COMMIT",
                    "TH1_SCORE_DISAMBIGUATED",
                    selected_plan_id=winner.plan_id,
                    secondary_plan_id=runner.plan_id,
                    candidates=[winner, runner],
                    reason="Phân biệt chặng RO/LO theo kho/khách hàng.",
                )
            return Resolution(
                "ASK_CARRIER",
                "TH1_AMBIGUOUS_RO_LO",
                candidates=[cand_ro, cand_lo],
                reason=f"Container {cont} xuất hiện ở cả lệnh trả và lệnh đóng trong ngày.",
                question=f"Container {cont} có cả lệnh trả và lệnh đóng hôm nay. Anh/chị đang báo cho chặng trả hay chặng đóng kho nào?",
            )

        # -------------------------------------------------------------------
        # TH3: Container nằm ở Lệnh trả (RO), nhưng tin báo là Lệnh đóng (LO) hoặc Kết hợp RO->LO
        # -------------------------------------------------------------------
        if cont and exact_ro and not exact_lo and (kind == "LO" or line.is_combined_from_return):
            ro_plan = exact_ro[0]
            blocked, warn_code = _is_reuse_blocked(ro_plan)
            if blocked:
                ro_cand = cls._score_candidate(line, ro_plan, carrier_id, dates, cont, "RO", "RO")
                ro_cand.exclusions.append("CONTAINER_REUSE_BLOCKED")
                return Resolution(
                    "ESCALATE_DHVT_WEB",
                    "TH3_BLOCKED_CONTAINER_WARNING",
                    secondary_plan_id=str(ro_plan.id),
                    candidates=[ro_cand],
                    reason=f"Vỏ trả {cont} đang có {_warning_label_vi(warn_code)}; hệ thống không tự ghép sang lệnh đóng.",
                )

            open_lo_plans = [
                p
                for p in carrier_plans
                if order_kind(getattr(p, "order_type", None)) == "LO"
                and not clean_container(getattr(p, "container_no", None))
            ]
            lo_candidates = [
                cls._score_candidate(line, p, carrier_id, dates, None, "LO", "LO")
                for p in open_lo_plans
            ]
            valid_lo = [c for c in lo_candidates if not c.exclusions]
            valid_lo.sort(key=lambda item: item.score, reverse=True)
            if valid_lo:
                top_lo = valid_lo[0]
                gap = top_lo.score - (valid_lo[1].score if len(valid_lo) > 1 else 0)
                has_strong_loc_or_bk = any(
                    ev in top_lo.evidences for ev in ("booking_exact", "warehouse_match", "customer_match")
                )
                if has_strong_loc_or_bk and top_lo.score >= 40 and gap >= 15:
                    action = "ESCALATE_DHVT_WEB" if shadow else "AUTO_COMMIT"
                    return Resolution(
                        action,
                        "TH3_COMBINED_RO_TO_LO",
                        selected_plan_id=top_lo.plan_id,
                        secondary_plan_id=str(ro_plan.id),
                        candidates=valid_lo[:5],
                        reason=(
                            "Đề xuất ghép vỏ từ lệnh trả sang lệnh đóng (chế độ an toàn)."
                            if shadow
                            else "Ghép vỏ từ lệnh trả sang lệnh đóng khớp kho/khách."
                        ),
                    )
            return Resolution(
                "ASK_CARRIER" if valid_lo else "ESCALATE_DHVT_WEB",
                "TH3_COMBINED_NEEDS_CONFIRMATION",
                secondary_plan_id=str(ro_plan.id),
                candidates=(valid_lo or lo_candidates)[:5],
                reason=f"Vỏ {cont} thuộc lệnh trả nhưng chưa đủ căn cứ chọn duy nhất lệnh đóng để ghép.",
                question=f"Vỏ {cont} lấy từ lệnh trả sẽ đóng hàng cho khách/kho nào và mấy giờ?",
            )

        # -------------------------------------------------------------------
        # TH2: Container khớp chính xác Lệnh trả (RO)
        # -------------------------------------------------------------------
        if cont and exact_ro and not exact_lo:
            cands = [cls._score_candidate(line, p, carrier_id, dates, cont, "RO", "RO") for p in exact_ro]
            valid_ro = [c for c in cands if not c.exclusions]
            if len(valid_ro) == 1:
                return Resolution(
                    "AUTO_COMMIT",
                    "TH2_RO_EXACT",
                    selected_plan_id=valid_ro[0].plan_id,
                    candidates=valid_ro,
                    reason="Khớp chính xác container trên lệnh trả (RO).",
                )

        # -------------------------------------------------------------------
        # TH4: Container khớp chính xác Lệnh đóng (LO) đã có sẵn số cont
        # -------------------------------------------------------------------
        if cont and exact_lo and not exact_ro:
            cands = [cls._score_candidate(line, p, carrier_id, dates, cont, "LO", "LO") for p in exact_lo]
            valid_lo = [c for c in cands if not c.exclusions]
            if len(valid_lo) == 1:
                return Resolution(
                    "AUTO_COMMIT",
                    "TH4_LO_EXACT",
                    selected_plan_id=valid_lo[0].plan_id,
                    candidates=valid_lo,
                    reason="Khớp chính xác container trên lệnh đóng (LO).",
                )

        # -------------------------------------------------------------------
        # TH5 & TH6: Container mới lấy bãi (TH5) hoặc Lệnh đóng chưa có cont (TH6)
        # -------------------------------------------------------------------
        if cont and line.check_digit_valid is False:
            return Resolution(
                "ESCALATE_DHVT_WEB",
                "TH5_INVALID_ISO6346",
                reason=f"Container {cont} sai chữ số kiểm tra ISO 6346.",
            )

        # Kiểm tra sai lệch 1–2 ký tự so với container trong kế hoạch của nhà xe
        if cont and not exact_ro and not exact_lo:
            near_misses = [
                p
                for p in carrier_plans
                if getattr(p, "container_no", None)
                and 1 <= _levenshtein(cont, clean_container(p.container_no) or "") <= 2
            ]
            if near_misses:
                nm_cands = [
                    cls._score_candidate(line, p, carrier_id, dates, None, kind)
                    for p in near_misses
                ]
                for nc in nm_cands:
                    nc.evidences.append("container_near_miss")
                suggested_conts = ", ".join(
                    str(getattr(p, "container_no", "")) for p in near_misses[:3]
                )
                return Resolution(
                    "ASK_CARRIER",
                    "TH5_NEAR_MISS_CONTAINER",
                    candidates=nm_cands[:5],
                    reason=f"Container {cont} lệch 1–2 ký tự so với kế hoạch ({suggested_conts}).",
                    question=f"Số container {cont} chưa có trong kế hoạch (gần giống {suggested_conts}). Anh/chị kiểm tra lại giúp nhé.",
                )

        candidates: list[Candidate] = []
        for p in plans:
            c = cls._score_candidate(
                line,
                p,
                carrier_id,
                dates,
                cont if (exact_ro or exact_lo) else None,
                kind,
            )
            # Với TH5 (cont mới lấy từ bãi cho lệnh đóng đang trống cont), chỉ xét slot LO đang trống cont
            if (
                cont
                and not exact_ro
                and not exact_lo
                and kind == "LO"
                and clean_container(getattr(p, "container_no", None))
            ):
                if "CONTAINER_OCCUPIED" not in c.exclusions:
                    c.exclusions.append("CONTAINER_OCCUPIED")
            candidates.append(c)

        valid = [c for c in candidates if not c.exclusions]
        valid.sort(key=lambda item: item.score, reverse=True)
        branch = (
            "TH5_NEW_CONTAINER_LO"
            if (cont and kind == "LO")
            else "TH6_LO_NO_CONTAINER"
            if (kind == "LO" and not cont)
            else "CONTAINER_LOOKUP"
        )

        if not valid:
            return Resolution(
                "ESCALATE_DHVT_WEB",
                branch,
                candidates=candidates[:5],
                reason="Không có kế hoạch hợp lệ trong phạm vi nhà xe/ngày.",
            )

        top = valid[0]
        gap = top.score - (valid[1].score if len(valid) > 1 else 0)
        evidence_set = set(top.evidences) - {"open_vehicle_slot", "size_match"}
        if not evidence_set:
            return Resolution(
                "ASK_CARRIER",
                branch,
                candidates=valid[:5],
                reason="Chỉ còn slot trống chưa đủ căn cứ để tự động gán.",
                question="Vui lòng bổ sung kho đóng/trả, khách hàng, booking hoặc giờ hẹn.",
            )
        if len(valid) > 1 and gap < 18:
            return Resolution(
                "ASK_CARRIER",
                branch,
                candidates=valid[:5],
                reason="Có nhiều lệnh ứng viên gần điểm nhau.",
                question="Có nhiều lệnh phù hợp trong ngày, vui lòng cho biết kho/giờ hẹn hoặc mã lệnh.",
            )
        if top.score >= 85 and gap >= 18:
            if shadow and "container_exact" not in top.evidences and "linked_plan" not in top.evidences:
                return Resolution(
                    "ESCALATE_DHVT_WEB",
                    branch,
                    selected_plan_id=top.plan_id,
                    candidates=valid[:5],
                    reason="Đề xuất độ tin cậy cao trong chế độ shadow; chờ ĐHVT xác nhận.",
                )
            return Resolution(
                "AUTO_COMMIT",
                branch,
                selected_plan_id=top.plan_id,
                candidates=valid[:5],
                reason="Đủ điểm và khoảng cách để khớp kế hoạch.",
            )
        if top.score >= 55:
            return Resolution(
                "ESCALATE_DHVT_WEB" if shadow else "ASK_CARRIER",
                branch,
                selected_plan_id=top.plan_id if shadow else None,
                candidates=valid[:5],
                reason="Ứng viên tiềm năng nhưng cần xác nhận thêm.",
                question="Vui lòng xác nhận kho và giờ hẹn của chuyến này.",
            )
        return Resolution(
            "ESCALATE_DHVT_WEB",
            branch,
            candidates=valid[:5],
            reason="Điểm đối chiếu thấp, chuyển ĐHVT kiểm tra trên Web.",
        )

    @classmethod
    def resolve_batch(
        cls,
        lines: list[ExtractedContainerLine],
        plans: list[Any],
        carrier_id: int | None,
        dates: list[str],
        shadow: bool = True,
    ) -> list[Resolution]:
        """Đối chiếu danh sách nhiều xe/nhiều chặng trong cùng tin nhắn, tránh 2 dòng tranh cùng 1 slot LO."""
        claimed_lo_ids: set[str] = set()
        results: list[Resolution] = []
        for ln in lines:
            available_plans = [
                p
                for p in plans
                if str(getattr(p, "id", "")) not in claimed_lo_ids
                or order_kind(getattr(p, "order_type", None)) == "RO"
            ]
            res = cls.resolve(ln, available_plans, carrier_id, dates, shadow=shadow)
            if res.selected_plan_id and res.action == "AUTO_COMMIT":
                claimed_lo_ids.add(res.selected_plan_id)
            results.append(res)
        return results
