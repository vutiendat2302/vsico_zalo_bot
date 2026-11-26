"""Nhận diện ý định local trước, không coi câu hỏi là tin báo điều xe."""

import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.domain.patterns import (
    CONT_REGEX as CONTAINER_RE,
    PHONE_PATTERN as PHONE_RE,
    PLATE_REGEX as PLATE_RE,
    TRAILER_PLATE_REGEX,
)
from .schemas import Entities, Role, ToolCall

TRAILER_PREFIX_RE = re.compile(r"^\d{2}[A-ZĐ]?R[M]?(?:[ \t\u00a0.\-/]|\d)", re.IGNORECASE)
ZALO_MENTION_RE = re.compile(r"\[@\d+\]")

_DEFERRED_OR_NON_QUESTION_PHRASES_RE = re.compile(
    r"\b(?:"
    r"(?:so\s+)?(?:cont|container|chi|seal|niêm\s*chi|niem\s*chi|mooc|ro\s*mooc|gio|xe|tai\s*xe|lai\s*xe|sdt)\s+"
    r"(?:chua|khong)\s*(?:co|cap|lay|bam|kep|biet|ro)?|"
    r"(?:chua|khong)\s+(?:co|cap|lay|bam|kep|biet|ro)\s+(?:so\s+)?(?:cont|container|chi|seal|niem\s*chi|mooc|ro\s*mooc|gio)|"
    r"(?:cont|container|chi|seal|mooc|gio)\s+(?:bao\s+sau|bo\s+sung\s+sau)|"
    r"(?:bo\s+sung|bao)\s+(?:cont|container|chi|seal|mooc|gio)\s+sau|"
    r"no\s+(?:chi|seal|cont)|"
    r"(?:bao\s+|gui\s+)?thong\s+tin\s+(?:xe|dieu\s+xe|cont|tai\s+xe)|"
    r"(?:em\s+|anh\s+|minh\s+)?xin\s+(?:bao|gui|cap\s+nhat)\s+(?:xe|cont|thong\s+tin)|"
    r"(?:tai\s*xe|lai\s*xe|lx|tx)\s*[:\-]?\s*[a-z]+(?:\s+[a-z]+){1,4}"
    r")\b",
    re.IGNORECASE,
)


def strip_zalo_mentions(text: str) -> str:
    """Loại bỏ thẻ @mention dạng `[@<id>]` của Zalo OA trước khi nhận diện ý định và mã đề xuất."""
    return ZALO_MENTION_RE.sub(" ", text or "").strip()


def normalize(text: str) -> str:
    """Bỏ dấu phục vụ luật và từ điển, giữ văn bản gốc ngoài module."""
    cleaned = strip_zalo_mentions(text)
    value = unicodedata.normalize("NFD", cleaned.lower()).replace("đ", "d")
    return " ".join("".join(c for c in value if unicodedata.category(c) != "Mn").split())


def local_date(reference: datetime) -> date:
    """Datetime MySQL không timezone được hiểu là giờ Việt Nam theo utc_now của ORM."""
    return (
        (
            reference.replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
            if reference.tzinfo is None
            else reference
        )
        .astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
        .date()
    )


def parse_entities(text: str, reference: datetime) -> Entities:
    """Bóc ngày theo lúc gửi, cont, biển, mã lệnh và booking có nhãn."""
    n = normalize(text)
    day = local_date(reference)
    offset = (
        2
        if re.search(r"\b(mot|ngay kia)\b", n)
        else 1
        if re.search(r"\bmai\b", n)
        else -1
        if "hom qua" in n
        else 0
    )
    day += timedelta(days=offset)
    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", n)
    has_explicit_date = bool(iso_match or offset != 0 or "hom nay" in n)
    if iso_match:
        day = day.replace(
            year=int(iso_match[1]), month=int(iso_match[2]), day=int(iso_match[3])
        )
    else:
        match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", n)
        if match:
            has_explicit_date = True
            day = day.replace(year=int(match[3] or day.year), month=int(match[2]), day=int(match[1]))
    e = Entities(plan_date=day)
    for attr, regex in [
        ("container_no", CONTAINER_RE),
        ("plate_no", PLATE_RE),
        ("order_code", re.compile(r"\b(?:RO|LO)\d{3,8}\b", re.IGNORECASE)),
    ]:
        found = regex.search(text)
        if found:
            setattr(e, attr, found[0].upper())
    for attr, pattern in [
        ("booking_no", r"\b(?:booking|bk|book)\s+([\w-]+)"),
        ("bill_of_lading_no", r"\b(?:bl|b/l|van don)\s+([\w-]+)"),
        ("case_id", r"(?:\bca\s*|#)\s*#?(\d{1,19})\b"),
    ]:
        found = re.search(pattern, n)
        if found:
            setattr(e, attr, found[1].upper())
    if not e.booking_no:
        compact_bk = re.search(r"\b(bk\d{4,20})\b", n)
        if compact_bk:
            e.booking_no = compact_bk[1].upper()
    if not e.plate_no:
        short = re.search(r"\bxe\s+(\d{3}[.]?\d{2}|\d{4})\b", n)
        if short:
            e.plate_no = short[1]
    if not has_explicit_date and any(
        getattr(e, k)
        for k in ("container_no", "order_code", "booking_no", "bill_of_lading_no", "plate_no", "case_id")
    ):
        e.plan_date = None
    if re.search(r"\b(mien bac|vung 1|phia bac)\b", n):
        e.region = 1
    elif re.search(r"\b(mien trung|vung 2|phia trung)\b", n):
        e.region = 2
    elif re.search(r"\b(mien nam|vung 3|phia nam)\b", n):
        e.region = 3
    if re.search(
        r"\b(theo tung vung|theo vung|theo mien|theo tinh|tung vung|tung mien|tung tinh|phan bo vung|phan bo tinh)\b",
        n,
    ):
        e.group_by_region = True
    has_both = bool(
        re.search(
            r"\b(dong\s*[,/&]\s*tra|dong\s+va\s+tra|dong\s+tra|tra\s+dong|tong\s+so\s+lenh)\b",
            n,
        )
    )
    has_dong = bool(re.search(r"\b(lenh dong|chuyen dong|cont dong|nhu cau dong)\b", n))
    has_tra = bool(re.search(r"\b(lenh tra|chuyen tra|cont tra|vo tra)\b", n))
    if not has_both:
        if has_dong and not has_tra:
            e.order_type = "LOAD"
        elif has_tra and not has_dong:
            e.order_type = "RETURN"
    return e


def route_local(
    text: str,
    role: Role,
    reference: datetime,
    *,
    has_quoted_pending_case: bool = False,
    is_bot_mentioned: bool = False,
) -> ToolCall:
    """Ưu tiên chặn ghi, nhận diện cấu trúc tường minh và dùng PhoBERT ngữ nghĩa (ĐHVT) trước khi gọi LLM."""
    n = normalize(text)
    try:
        entities = parse_entities(text, reference)
    except ValueError:
        return ToolCall(intent="CLARIFY", needs_clarification=True)

    def result(intent: str) -> ToolCall:
        """Đóng gói quyết định local cùng tham số đã chuẩn hóa."""
        return ToolCall(intent=intent, confidence=1, entities=entities)

    if n in ("?", "menu", "lenh tat") or any(k in n for k in ("huong dan", "bot lam duoc", "help", "bao lenh dong can")):
        return result("get_role_help")
    if n in ("ok", "oki", "oke", "okie", "dung", "dung roi", "xac nhan", "dong y", "duyet") or re.fullmatch(
        r"(?:xac nhan|duyet|ok|oki|dong y)\s*(?:#?\d+|(?:ro|lo)\d{3,8}|[a-z]{3}[ujz]\d{7})", n
    ):
        return result(
            "dhvt_direct_review_action" if role == "DHVT" else "CONFIRM" if role == "CARRIER" else "IGNORE"
        )
    if any(
        k in n for k in ("gps", "km nao", "vi tri thuc", "da den kho chua", "vao cong chua", "pod")
    ):
        return result("UNSUPPORTED")
    if n in ("ok em", "cam on", "vang", "da nhan", "thanks", "tks") and role != "DHVT":
        return result("IGNORE")
    mutation = bool(
        re.search(
            r"\b(doi xe|doi dau keo|thay dau keo|thay tai|doi tai|sua lai|go nham|doi gio|doi kho|huy|bo sung|chuyen gio|doi sang|doi cont|doi chi|doi seal|sua sdt|doi so dien thoai|cap nhat|thay xe)\b",
            n,
        )
    )
    n_for_question = _DEFERRED_OR_NON_QUESTION_PHRASES_RE.sub(" ", n)
    has_phone = bool(PHONE_RE.search(text))
    has_driver_label = bool(re.search(r"\b(?:tai\s*xe|lai\s*xe|lx|tx|sdt|dt)\b", n))
    has_mooc_label = bool(
        re.search(r"\b(?:mooc|ro\s*mooc|rm|\d{2}[a-z]?r[m]?[- ./]?\d{3,5})\b", n)
    )
    has_seal_label = bool(re.search(r"\b(?:so\s*chi|so\s*seal|niem\s*chi|chi|seal)\b", n))
    has_f1_slash_structure = text.count("/") >= 2 and bool(entities.plate_no or entities.container_no)
    has_explicit_question_cue = bool(
        "?" in text
        or ("neu " in n and mutation)
        or re.search(
            r"\b(?:dung\s+khong|phai\s+khong|co\s+\w+\s+khong|nhan\s+duoc\s+chua|ghi\s+nhan\s+chua|duyet\s+chua|xong\s+chua|ok\s+chua|co\s+lich\s+chua|may\s+gio|bao\s+gio|khi\s+nao|xe\s+nao|cont\s+nao|kho\s+nao|the\s+nao|tai\s+sao|vi\s+sao)\b",
            n_for_question,
        )
    )
    is_carrier_dispatch_payload = bool(
        role == "CARRIER"
        and not has_explicit_question_cue
        and (
            has_phone
            or has_f1_slash_structure
            or (
                entities.plate_no
                and entities.container_no
                and (has_driver_label or has_mooc_label or has_seal_label)
            )
        )
    )
    question = bool(
        not is_carrier_dispatch_payload
        and (
            re.search(
                r"\b(nao|may|bao nhieu|chua|khong|the nao|tai sao|vi sao|lich|tra cuu|thong ke|tong hop|xem|kiem tra|cho xin|thong tin|xin)\b",
                n_for_question,
            )
            or "?" in text
        )
    )
    if role == "DHVT":
        # Tầng 1: Chặn an toàn tuyệt đối các lệnh xóa/reset dữ liệu và chỉ giữ tín hiệu cấu trúc 100% tường minh
        if re.match(r"^(?:xoa|delete|clear|reset|drop)\b", n):
            return result("BLOCK_WRITE")
        if ("neu " in n or "anh huong" in n) and (entities.order_code or entities.container_no):
            return result("dhvt_analyze_change_impact")
        is_review_action_question = bool(
            "?" in text
            or re.search(
                r"\b(?:duyet chua|huy chua|sua chua|co duyet khong|co huy khong|tai sao|vi sao|bao nhieu|the nao|anh huong)\b",
                n,
            )
        )
        has_review_verb = bool(
            re.match(
                r"^(?:duyet|ok|oki|oke|dong y|xac nhan|sua|chinh sua|huy|tu choi|khong duyet|cho gui)\b",
                n,
            )
        )
        if has_review_verb and not is_review_action_question:
            is_explicit_review_target = bool(
                has_quoted_pending_case
                or is_bot_mentioned
                or entities.case_id
                or entities.order_code
                or entities.container_no
                or n in ("duyet", "ok", "oki", "oke", "dong y", "xac nhan", "tu choi", "khong duyet", "cho gui")
                or re.match(r"^(?:duyet|tu choi|khong duyet|sua|chinh sua)\s+", n)
            )
            if is_explicit_review_target:
                return result("dhvt_direct_review_action")
        if re.match(r"^(?:nhac|gui nhac|bao nhac)\b", n):
            return result("dhvt_remind_carrier")
        if re.match(r"^kt\s+", n) and (entities.order_code or entities.container_no or entities.plate_no):
            return result("dhvt_get_order_or_cont_detail")
        if any(p in n for p in ("da doi nhung gi", "lich su", "bot da lam", "nhat ky")):
            return result("dhvt_get_audit_timeline")
        if any(p in n for p in ("tai sao", "vi sao")) or entities.case_id:
            return result("dhvt_explain_review_case")
        if entities.order_code or entities.container_no:
            return result("dhvt_get_order_or_cont_detail")
        if entities.plate_no:
            return result("dhvt_get_vehicle_trips")
        if entities.group_by_region:
            return result("dhvt_get_daily_overview")
        if n in ("ca cho", "hang cho", "cho duyet"):
            return result("dhvt_get_priority_digest")

        # Tầng 2: PhoBERT Semantic Classifier (`vinai/phobert-base-v2`) kết hợp bối cảnh hội thoại
        from src.parsing.local_nlp_extractor import PhoBertLocalNlpEngine

        nlp_res = PhoBertLocalNlpEngine.get_instance().classify_dhvt_intent(
            text,
            has_quoted_pending_case=has_quoted_pending_case,
            is_bot_mentioned=is_bot_mentioned,
            has_question_mark="?" in text,
        )
        if nlp_res.is_confident:
            if nlp_res.intent == "INTERNAL_CHAT_IGNORE":
                return ToolCall(
                    intent="IGNORE",
                    confidence=0.95,
                    route_source="local_nlp",
                    entities=entities,
                )
            calibrated_conf = round(
                min(0.99, 0.82 + 0.14 * nlp_res.confidence + 0.15 * nlp_res.margin), 3
            )
            return ToolCall(
                intent=nlp_res.intent,
                confidence=calibrated_conf,
                route_source="local_nlp",
                entities=entities,
            )
        if (
            re.search(r"\b(?:nha xe|forwarder|khach hang)\s+\w+", n)
            or (re.search(r"\bkhach\s+\w+", n) and "gui khach" not in n and "bao khach" not in n)
        ):
            return result("dhvt_get_entity_stats")
        return ToolCall(
            intent="UNKNOWN",
            confidence=nlp_res.confidence,
            route_source="local_nlp",
            entities=entities,
        )
    if (
        role == "CARRIER"
        and question
        and "yeu cau" in n
        and any(k in n for k in ("chua xong", "chua xu ly", "nao", "cho"))
    ):
        return result("carrier_list_pending_cases")
    if role == "CUSTOMER" and "co chuyen nao doi" in n:
        return result("customer_get_trip_changes")
    if mutation and question and ("neu " in n or "khong" in n or "?" in text):
        return result("MIXED")
    if role == "CUSTOMER":
        if mutation and not ("co chuyen nao doi" in n):
            return result("customer_create_change_request")
        if entities.case_id or any(p in n for p in ("yeu cau", "luc nay xong", "duyet chua")):
            return result("customer_get_request_status")
        if "doi xe" in n or "thay doi" in n:
            return result("customer_get_trip_changes")
        if entities.plate_no:
            return result("customer_get_vehicle_driver")
        if entities.container_no or entities.order_code:
            return result("customer_get_trip_detail")
        if "co xe" in n or "cho dieu xe" in n:
            entities.assigned = (
                None
                if "da co xe" in n and "chua" in n
                else False
                if "chua" in n
                else True
                if "da co xe" in n
                else None
            )
            return result("customer_list_trips_by_status")
        if "tong" in n or "thong ke" in n:
            return result("customer_get_summary")
        if "kho " in n or "tuyen " in n or entities.booking_no or entities.bill_of_lading_no:
            return result("customer_query_schedule")
        if question and any(k in n for k in ("chuyen", "lich", "cont", "hom nay", "mai")):
            return result("customer_list_trips_by_date")
    else:
        if re.match(r"^(?:mau|lay mau|xin mau|form)\b", n) and (entities.order_code or entities.container_no):
            return result("carrier_get_order_template")
        if re.search(r"\b(huy|tra lenh|su co|hong doc duong|ket xe|tac duong|hong lop|hong xe|tre gio|cham gio|tre \d+)\b", n):
            return result("carrier_report_issue_or_cancel")
        if n in ("chuyen thieu", "lenh thieu", "cac chuyen thieu", "chuyen chua bao"):
            return result("carrier_list_incomplete_plans")
        if mutation:
            if "bo sung" in n:
                return result("carrier_supplement_trip")
            if "go nham" in n or "luc nay" in n:
                return result("carrier_fix_recent_submission")
            return result("carrier_request_vehicle_update")
        if question:
            if any(p in n for p in ("nhan duoc chua", "ghi nhan chua", "bao nhan", "bao xe xong")):
                return result("carrier_check_submission_status")
            if "yeu cau" in n or "ca cho" in n or "cho xu ly" in n:
                return result("carrier_list_pending_cases")
            if "thieu" in n or "chua bao" in n:
                return result("carrier_list_incomplete_plans")
            if entities.plate_no:
                return result("carrier_get_vehicle_schedule")
            if entities.container_no or entities.order_code or entities.booking_no:
                return result("carrier_get_order_detail")
            if "tong" in n or "thong ke" in n or "may cont 20" in n:
                return result("carrier_get_summary")
            if any(k in n for k in ("chuyen", "ke hoach", "lich", "cont", "hom nay", "mai")):
                return result("carrier_list_plans_by_date")
            return result("UNKNOWN")
        # Báo xe/cont tự do vẫn đi qua bộ bóc tách và đối chiếu đã có.
        return result("REPORT_DISPATCH")
    return result("UNKNOWN")
