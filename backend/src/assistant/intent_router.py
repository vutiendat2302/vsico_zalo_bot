"""Nhận diện ý định local trước, không coi câu hỏi là tin báo điều xe."""

import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .schemas import Entities, Role, ToolCall

PLATE_RE = re.compile(r"\b\d{2}[A-Z]{1,2}(?:[- ./]?\d{3}[- .]?\d{2}|[- ./]?\d{4,5})\b", re.IGNORECASE)
CONTAINER_RE = re.compile(r"\b[A-Z]{4}\d{7}\b", re.IGNORECASE)
ZALO_MENTION_RE = re.compile(r"\[@\d+\]")


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


def route_local(text: str, role: Role, reference: datetime) -> ToolCall:
    """Ưu tiên chặn ghi, nhận diện câu hỏi rồi mới chuyển báo xe về pipeline."""
    n = normalize(text)
    try:
        entities = parse_entities(text, reference)
    except ValueError:
        return ToolCall(intent="CLARIFY", needs_clarification=True)

    def result(intent: str) -> ToolCall:
        """Đóng gói quyết định local cùng tham số đã chuẩn hóa."""
        return ToolCall(intent=intent, confidence=1, entities=entities)

    if n in ("ok", "dung", "dung roi", "xac nhan", "dong y") or re.fullmatch(r"xac nhan #?\d+", n):
        return result(
            "BLOCK_WRITE" if role == "DHVT" else "CONFIRM" if role == "CARRIER" else "IGNORE"
        )
    if any(
        k in n for k in ("gps", "km nao", "vi tri thuc", "da den kho chua", "vao cong chua", "pod")
    ):
        return result("UNSUPPORTED")
    if any(k in n for k in ("huong dan", "bot lam duoc", "help", "bao lenh dong can")):
        return result("get_role_help")
    if n in ("ok em", "cam on", "vang", "da nhan", "thanks", "tks") and role != "DHVT":
        return result("IGNORE")
    n_for_question = re.sub(
        r"\b(chua co cont|chua co so cont|chua co chi|chua co seal|chua cap cont|cont bao sau|chi bao sau)\b",
        "",
        n,
    )
    question = bool(
        re.search(
            r"\b(nao|may|bao nhieu|chua|khong|the nao|tai sao|vi sao|lich|tra cuu|thong ke|tong hop|xem|kiem tra|cho xin|thong tin|xin)\b",
            n_for_question,
        )
        or "?" in text
    )
    mutation = bool(
        re.search(
            r"\b(doi xe|doi dau keo|thay dau keo|thay tai|doi tai|sua lai|go nham|doi gio|doi kho|huy|bo sung|chuyen gio|doi sang|doi cont|doi chi|doi seal|sua sdt|doi so dien thoai|cap nhat|thay xe)\b",
            n,
        )
    )
    if role == "DHVT":
        if ("neu " in n or "anh huong" in n) and (entities.order_code or entities.container_no):
            return result("dhvt_analyze_change_impact")
        if (
            re.search(r"\b(duyet|xoa|cho gui|sua truc tiep|huy lenh|huy chuyen)\b", n)
            and not question
        ):
            return result("BLOCK_WRITE")
        rules = [
            (("bot tu xu ly", "ty le", "hieu qua bot", "llm"), "dhvt_get_bot_performance"),
            (("da doi nhung gi", "lich su", "bot da lam", "nhat ky"), "dhvt_get_audit_timeline"),
            (("tai sao", "vi sao"), "dhvt_explain_review_case"),
            (("trung chuyen", "trung xe", "trung lich"), "dhvt_detect_duplicate_vehicles"),
            (
                ("canh bao vo", "ha rong", "qua sl", "ben khac da xin", "soc"),
                "dhvt_get_container_warnings",
            ),
            (("dong bo", "gui khach", "gui tin", "that bai"), "dhvt_get_delivery_and_sync_errors"),
            (
                ("chua khop", "bao sai", "lech chi", "lech seal", "loi du lieu"),
                "dhvt_get_validation_failures",
            ),
            (("cho duyet", "ca cho", "xu ly gap", "can xu ly"), "dhvt_get_priority_digest"),
            (("chua co xe", "thieu cont", "thieu xe"), "dhvt_get_unassigned_plans"),
        ]
        for phrases, tool in rules:
            if any(p in n for p in phrases):
                return result(tool)
        if entities.case_id:
            return result("dhvt_explain_review_case")
        if entities.order_code or entities.container_no:
            return result("dhvt_get_order_or_cont_detail")
        if entities.plate_no:
            return result("dhvt_get_vehicle_trips")
        if "khach " in n or "nha xe " in n or "forwarder " in n:
            return result("dhvt_get_entity_stats")
        if (
            entities.group_by_region
            or entities.region is not None
            or entities.order_type is not None
            or any(
                k in n
                for k in (
                    "chuyen",
                    "ke hoach",
                    "can doi",
                    "cont",
                    "hom nay",
                    "mai",
                    "lenh",
                    "tong",
                    "thong ke",
                    "vung",
                    "mien",
                    "tinh",
                )
            )
        ):
            return result("dhvt_get_daily_overview")
        return result("UNKNOWN")
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
        if re.search(r"\b(huy|tra lenh|su co|hong doc duong)\b", n):
            return result("carrier_report_issue_or_cancel")
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
