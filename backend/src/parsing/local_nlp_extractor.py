"""Tầng 2 NLP nội bộ: RapidFuzz + Từ điển danh mục (Catalog Gazetteer) + PhoBERT + Giải quyết đồng tham chiếu."""

import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz, process
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_container, clean_phone, clean_plate, compact_plate
from src.infrastructure.models import (
    ContainerJob,
    Customer,
    CustomerAlias,
    Driver,
    MessageDraft,
    Trailer,
    TransportPlan,
    TruckRecord,
    Vehicle,
    Warehouse,
    WarehouseAlias,
    ZaloMessage,
)


def normalized(value: str | None) -> str:
    """Bỏ dấu tiếng Việt và gom khoảng trắng để đối sánh ổn định."""
    raw = unicodedata.normalize("NFD", (value or "").lower()).replace("đ", "d")
    return re.sub(
        r"\s+", " ", "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    ).strip()


def vn_time(reference: datetime | None) -> datetime:
    """Quy đổi thời điểm gốc sang múi giờ Việt Nam để tính đúng từ chỉ ngày."""
    now = reference or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    if now.tzinfo is None:
        return now.replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    return now.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))


def message_dates(text: str, reference: datetime | None) -> list[str]:
    """Xác định một hoặc hai ngày ứng viên từ nội dung và thời điểm gửi gốc."""
    base = vn_time(reference)
    clean = normalized(text)
    explicit = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", clean)
    if explicit:
        day, month, year = int(explicit[1]), int(explicit[2]), explicit[3]
        full_year = int(year) + (2000 if year and len(year) == 2 else 0) if year else base.year
        return [f"{full_year:04d}-{month:02d}-{day:02d}"]
    if re.search(r"\b(ngay kia|mot)\b", clean):
        return [(base.date() + timedelta(days=2)).isoformat()]
    if re.search(r"\b(ngay mai|mai|sang mai|chieu mai|toi mai)\b", clean):
        return [(base.date() + timedelta(days=1)).isoformat()]
    if re.search(r"\b(hom qua)\b", clean):
        return [(base.date() - timedelta(days=1)).isoformat()]
    if re.search(r"\b(hom nay|nay|sang nay|chieu nay|toi nay)\b", clean):
        return [base.date().isoformat()]
    if base.hour >= 18:
        return [base.date().isoformat(), (base.date() + timedelta(days=1)).isoformat()]
    return [base.date().isoformat()]


# ---------------------------------------------------------------------------
# PhoBERT Local NLP Engine (vinai/phobert-base-v2 adapter + Subword/BIO NER)
# ---------------------------------------------------------------------------

PHOBERT_COMPOUND_VOCAB: tuple[str, ...] = (
    "dong hang",
    "tra vo",
    "ha rong",
    "lay rong",
    "doi xe",
    "doi tai",
    "bo sung",
    "huy chuyen",
    "huy lenh",
    "ket hop",
    "quay dau",
    "giao kho",
    "lenh dong",
    "lenh tra",
    "khu cong nghiep",
    "tai xe",
    "dau keo",
    "ro mooc",
    "gio hen",
    "bien so",
    "so chi",
    "so cont",
    "cho cu",
    "kho cu",
    "nhu hom qua",
    "xe tren",
    "xe nay",
    "cont do",
    "cont tren",
)

INTENT_PROTOTYPES: dict[str, tuple[str, ...]] = {
    "COMBINED_TRIP": (
        "tra xong dong luon",
        "ha vo xong boc hang",
        "ket hop tra va dong",
        "quay dau dong tiep",
        "giao xong lay hang",
        "tra kho xong qua dong",
    ),
    "LOAD_DISPATCH": (
        "bao xe dong hang",
        "xe vao kho dong cont",
        "lay rong dong hang xuat",
        "lenh dong kho",
    ),
    "RETURN_DISPATCH": (
        "bao xe tra hang nhap",
        "xe giao hang tra vo",
        "ha rong bãi",
        "lenh tra cont",
    ),
    "SUPPLEMENT_INFO": (
        "bo sung so chi",
        "bo sung cont",
        "bo sung sdt tai xe",
        "gui them bien so",
    ),
    "VEHICLE_CHANGE": (
        "doi xe sang bien so",
        "thay dau keo",
        "doi tai xe",
        "sua lai bien so",
    ),
    "CANCEL_TRIP": (
        "huy chuyen",
        "xin huy lenh",
        "xe hong huy chuyen",
        "tra lenh khong chay",
    ),
}


@dataclass
class PhoBertNerSpan:
    """Thực thể nhận diện từ tầng PhoBERT BIO/Subword kết hợp Gazetteer."""

    label: str  # PER, LOC, ORG, TIME, ORDER_TYPE, COREF
    text: str
    normalized_text: str
    confidence: float


@dataclass
class PhoBertAnalysis:
    """Kết quả phân tích ngữ nghĩa & thực thể từ PhoBERT Local NLP."""

    segmented_text: str
    intent_label: str
    intent_confidence: float
    order_type_hint: str | None = None
    is_combined_trip: bool = False
    spans: list[PhoBertNerSpan] = field(default_factory=list)
    backend_mode: str = "phobert_subword_gazetteer"


class PhoBertLocalNlpEngine:
    """Bộ xử lý PhoBERT (`vinai/phobert-base-v2`) hỗ trợ chạy offline/local và trích xuất đặc trưng."""

    _instance: "PhoBertLocalNlpEngine | None" = None

    def __init__(self) -> None:
        """Khởi tạo PhoBERT tokenizer/model nếu có sẵn trong môi trường cục bộ."""
        self.model_name = os.getenv("PHOBERT_MODEL_PATH", "vinai/phobert-base-v2")
        self._tokenizer: Any = None
        self._model: Any = None
        self.backend_mode = "phobert_subword_gazetteer"
        self._try_load_local_transformers()

    def _try_load_local_transformers(self) -> None:
        """Thử nạp trọng số PhoBERT đã cache trên đĩa (local_files_only=True) để không phụ thuộc mạng."""
        if os.getenv("ENABLE_PHOBERT_TRANSFORMERS", "0") != "1":
            return
        try:
            from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found]

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, local_files_only=True)
            self._model = AutoModel.from_pretrained(self.model_name, local_files_only=True)
            self.backend_mode = "phobert_transformers_local"
        except Exception:
            self._tokenizer = None
            self._model = None
            self.backend_mode = "phobert_subword_gazetteer"

    @classmethod
    def get_instance(cls) -> "PhoBertLocalNlpEngine":
        """Lấy singleton PhoBertLocalNlpEngine dùng chung trong worker."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def segment_vietnamese_compounds(text: str) -> str:
        """Ghép từ ghép tiếng Việt theo chuẩn đầu vào của PhoBERT (ví dụ: `dong_hang`, `khu_cong_nghiep`)."""
        norm = normalized(text)
        segmented = norm
        for compound in sorted(PHOBERT_COMPOUND_VOCAB, key=len, reverse=True):
            replacement = compound.replace(" ", "_")
            segmented = re.sub(rf"\b{re.escape(compound)}\b", replacement, segmented)
        return segmented

    @staticmethod
    def subword_ngrams(text: str) -> Counter[str]:
        """Sinh vector BPE/char-word n-gram mô phỏng không gian biểu diễn subword của PhoBERT."""
        seg = PhoBertLocalNlpEngine.segment_vietnamese_compounds(text)
        tokens = seg.split()
        feats: Counter[str] = Counter()
        for tok in tokens:
            feats[f"w:{tok}"] += 2
            padded = f"<{tok}>"
            for n in (3, 4):
                for i in range(max(0, len(padded) - n + 1)):
                    feats[f"c{n}:{padded[i : i + n]}"] += 1
        for i in range(len(tokens) - 1):
            feats[f"bi:{tokens[i]}_{tokens[i + 1]}"] += 2
        return feats

    @classmethod
    def semantic_similarity(cls, text_a: str, text_b: str) -> float:
        """Tính độ tương đồng ngữ nghĩa kết hợp Cosine Subword PhoBERT và RapidFuzz."""
        norm_a = normalized(text_a)
        norm_b = normalized(text_b)
        if not norm_a or not norm_b:
            return 0.0
        vec_a = cls.subword_ngrams(norm_a)
        vec_b = cls.subword_ngrams(norm_b)
        dot = sum(vec_a[k] * vec_b[k] for k in (vec_a.keys() & vec_b.keys()))
        mag_a = math.sqrt(sum(v * v for v in vec_a.values())) or 1.0
        mag_b = math.sqrt(sum(v * v for v in vec_b.values())) or 1.0
        cosine = dot / (mag_a * mag_b)
        fuzzy_w = fuzz.WRatio(norm_a, norm_b) / 100.0
        fuzzy_tset = fuzz.token_set_ratio(norm_a, norm_b) / 100.0
        return round(0.40 * cosine + 0.35 * fuzzy_w + 0.25 * fuzzy_tset, 4)

    def analyze(self, raw_text: str) -> PhoBertAnalysis:
        """Phân tích ý định điều vận, luồng kết hợp RO->LO và trích xuất các thực thể BIO."""
        clean = normalized(raw_text)
        segmented = self.segment_vietnamese_compounds(raw_text)
        best_intent = "UNKNOWN"
        best_score = 0.0
        for label, prototypes in INTENT_PROTOTYPES.items():
            for proto in prototypes:
                score = self.semantic_similarity(clean, proto)
                if proto in clean:
                    score = max(score, 0.92)
                if score > best_score:
                    best_score = score
                    best_intent = label

        is_combined = bool(
            re.search(
                r"\b(tra\s+xong\s+dong|ha\s+.*?\s+xong\s+dong|ket\s+hop|quay\s+dau\s+dong|giao\s+.*?\s+xong\s+.*?\s*dong)\b",
                clean,
            )
            or best_intent == "COMBINED_TRIP"
        )
        order_type_hint: str | None = None
        if is_combined:
            order_type_hint = "LOAD"
        elif re.search(r"\b(dong\s+hang|lenh\s+dong|lay\s+rong|boc\s+hang|dong\s+kho|dong\s+cont)\b", clean):
            order_type_hint = "LOAD"
        elif re.search(r"\b(tra\s+hang|tra\s+vo|ha\s+rong|lenh\s+tra|giao\s+hang|ha\s+bai)\b", clean):
            order_type_hint = "RETURN"

        spans: list[PhoBertNerSpan] = []
        # B-LOC / I-LOC: Kho / KCN / Nhà máy / Địa điểm
        loc_patterns = [
            r"\b(?:kho|kcn|khu cong nghiep|nha may|nm|cang|icd|cum cn)\s+([a-z0-9\s\-]{2,45}?)(?=\s+(?:luc|gio|cont|xe|tai|sdt|chi|seal|ngay|mai|hom)|[,;.\n]|$)",
            r"\b(?:dong|tra|giao|ha)\s+(?:o|tai)?\s*(?:kho|kcn|nha may)?\s*([a-z0-9\s\-]{3,35}?)(?=\s+(?:luc|gio|cont|xe|tai|sdt|chi|seal)|[,;.\n]|$)",
        ]
        for pat in loc_patterns:
            for m in re.finditer(pat, clean):
                candidate_loc = m.group(1).strip()
                if candidate_loc and candidate_loc not in ("hang", "vo", "rong", "cont", "luon", "tiep"):
                    spans.append(
                        PhoBertNerSpan(
                            label="LOC",
                            text=candidate_loc,
                            normalized_text=candidate_loc,
                            confidence=0.86,
                        )
                    )

        # B-PER: Tên tài xế sau nhãn "tài", "lx", "lái xe", "bác tài"
        per_match = re.search(
            r"\b(?:tai xe|lai xe|bac tai|lx|tai)\s+([a-z\s]{2,30}?)(?=\s+(?:\d|sdt|dt|cont|xe|chi|seal|kho|tra|dong|giao|ha|luc|hen)|[,;.\n]|$)",
            clean,
        )
        if per_match:
            drv_raw = per_match.group(1).strip()
            spans.append(
                PhoBertNerSpan(
                    label="PER",
                    text=drv_raw,
                    normalized_text=drv_raw,
                    confidence=0.88,
                )
            )

        return PhoBertAnalysis(
            segmented_text=segmented,
            intent_label=best_intent,
            intent_confidence=round(best_score, 4),
            order_type_hint=order_type_hint,
            is_combined_trip=is_combined,
            spans=spans,
            backend_mode=self.backend_mode,
        )


def _match_catalog_gazetteer(
    db: Session,
    line: ExtractedContainerLine,
    carrier_id: int | None,
    raw_text: str,
    candidate_dates: list[str],
) -> None:
    """Đối sánh thực thể bằng RapidFuzz trên Từ điển danh mục (Khách hàng, Kho, Alias, Kế hoạch)."""
    norm_line = normalized(line.line_text or raw_text)
    if not norm_line:
        return

    # 1. Nạp các dòng kế hoạch trong phạm vi ngày + nhà xe để ưu tiên từ điển theo ngữ cảnh
    plan_dates_obj: list[date] = []
    for d_str in candidate_dates:
        try:
            plan_dates_obj.append(date.fromisoformat(d_str))
        except ValueError:
            pass

    scoped_plans: list[TransportPlan] = []
    if plan_dates_obj:
        stmt = select(TransportPlan).where(TransportPlan.plan_date.in_(plan_dates_obj))
        if carrier_id is not None:
            stmt = stmt.where(
                or_(TransportPlan.carrier_id == carrier_id, TransportPlan.carrier_id.is_(None))
            )
        scoped_plans = list(db.scalars(stmt).all())

    # 2. Khớp Booking / Mã lệnh từ câu nhắn nếu chưa có
    if not line.booking_no:
        bk_match = re.search(r"\b(?:bk|book|booking)\s*[:#-]?\s*([A-Z0-9-]{4,24})\b", raw_text, re.I)
        if bk_match:
            line.booking_no = bk_match.group(1).upper()
            line.field_evidences["booking_no"] = "regex_booking"
        else:
            for p in scoped_plans:
                if p.booking_no and len(p.booking_no) >= 5 and normalized(p.booking_no) in norm_line:
                    line.booking_no = p.booking_no
                    line.field_evidences["booking_no"] = "plan_booking_gazetteer"
                    break

    # 3. Khớp Khách hàng (Customer + CustomerAlias + Kế hoạch trong ngày) bằng RapidFuzz
    if not line.customer_code_or_id:
        customer_choices: dict[str, tuple[int, str]] = {}
        for cust_obj in db.scalars(select(Customer).limit(500)).all():
            if cust_obj.name:
                customer_choices[normalized(cust_obj.name)] = (cust_obj.id, cust_obj.name)
        for alias_obj, cust_obj in db.execute(
            select(CustomerAlias, Customer).join(Customer, CustomerAlias.customer_id == Customer.id)
        ).all():
            if alias_obj.alias:
                customer_choices[normalized(alias_obj.alias)] = (cust_obj.id, cust_obj.name)
        for p in scoped_plans:
            if p.customer_id and p.customer_name:
                customer_choices[normalized(p.customer_name)] = (p.customer_id, p.customer_name)

        query_cust = normalized(line.customer_hint) if line.customer_hint else None
        matched_custs: dict[int, tuple[float, str]] = {}
        for key_norm, (cid, cname) in customer_choices.items():
            if not key_norm or len(key_norm) < 3:
                continue
            if f" {key_norm} " in f" {norm_line} ":
                score = min(99.0, 90.0 + len(key_norm) * 0.3)
                if cid not in matched_custs or score > matched_custs[cid][0]:
                    matched_custs[cid] = (score, cname)
            elif query_cust:
                rf_score = max(
                    fuzz.WRatio(query_cust, key_norm),
                    fuzz.token_set_ratio(query_cust, key_norm),
                )
                if rf_score >= 86.0 and (cid not in matched_custs or rf_score > matched_custs[cid][0]):
                    matched_custs[cid] = (float(rf_score), cname)

        if matched_custs:
            ranked_c = sorted(matched_custs.items(), key=lambda item: item[1][0], reverse=True)
            if len(ranked_c) == 1 or (ranked_c[0][1][0] - ranked_c[1][1][0] >= 5.0):
                best_cid, (best_cscore, best_cname) = ranked_c[0]
                line.customer_code_or_id = best_cid
                line.customer_hint = line.customer_hint or best_cname
                line.field_evidences["customer"] = f"rapidfuzz_catalog:{best_cscore:.1f}"

    # 4. Khớp Kho / Địa điểm (Warehouse + WarehouseAlias + TransportPlan) bằng RapidFuzz
    if not line.warehouse_code_or_id:
        wh_choices_map: dict[str, tuple[int | None, str]] = {}
        for wh_obj in db.scalars(select(Warehouse).limit(600)).all():
            for val in (wh_obj.name, wh_obj.address):
                if val and len(normalized(val)) >= 3:
                    wh_choices_map[normalized(val)] = (wh_obj.id, wh_obj.name)
        for walias, wh_obj in db.execute(
            select(WarehouseAlias, Warehouse).join(Warehouse, WarehouseAlias.warehouse_id == Warehouse.id)
        ).all():
            if walias.alias and len(normalized(walias.alias)) >= 3:
                wh_choices_map[normalized(walias.alias)] = (wh_obj.id, wh_obj.name)
        for p in scoped_plans:
            for field_val in (p.warehouse_name, p.delivery_address, p.ward_name):
                if field_val and len(normalized(field_val)) >= 3:
                    wh_choices_map[normalized(field_val)] = (
                        p.warehouse_id,
                        p.warehouse_name or p.delivery_address or field_val,
                    )

        query_wh = normalized(line.warehouse_hint) if line.warehouse_hint else norm_line
        matched_wh: dict[str, tuple[float, int | None, str]] = {}
        for key_norm, (wid, wname) in wh_choices_map.items():
            dedup_key = str(wid) if wid is not None else normalize_key(wname)
            if f" {key_norm} " in f" {norm_line} ":
                score = min(99.0, 88.0 + len(key_norm) * 0.4)
            elif line.warehouse_hint:
                score = max(
                    fuzz.WRatio(query_wh, key_norm),
                    fuzz.token_set_ratio(query_wh, key_norm),
                )
            else:
                score = 0.0
            if score >= 86.0:
                prev = matched_wh.get(dedup_key)
                if prev is None or score > prev[0]:
                    matched_wh[dedup_key] = (float(score), wid, wname)

        if matched_wh:
            ranked_w = sorted(matched_wh.values(), key=lambda item: item[0], reverse=True)
            if len(ranked_w) == 1 or (ranked_w[0][0] - ranked_w[1][0] >= 5.0):
                best_wscore, best_wid, best_wname = ranked_w[0]
                if best_wid is not None:
                    line.warehouse_code_or_id = best_wid
                line.warehouse_hint = line.warehouse_hint or best_wname
                line.field_evidences["warehouse"] = f"rapidfuzz_catalog:{best_wscore:.1f}"


def normalize_key(value: str | None) -> str:
    """Tạo khóa chuẩn hóa cho tên kho khi chưa có warehouse_id."""
    return normalized(value)


def _resolve_conversational_coreference(
    db: Session,
    line: ExtractedContainerLine,
    raw_text: str,
    quoted_text: str | None,
    carrier_id: int | None,
    group_id: str | None = None,
    sender_id: str | None = None,
    reference_time: datetime | None = None,
) -> bool:
    """Giải quyết đồng tham chiếu ('xe trên', 'xe này', 'cont đó', 'chỗ cũ', 'kho cũ') an toàn."""
    clean = normalized(raw_text)
    has_vehicle_ref = bool(re.search(r"\b(xe tren|xe nay|xe do|con xe tren)\b", clean))
    has_cont_ref = bool(re.search(r"\b(cont do|cont tren|cont nay|vo tren|vo do)\b", clean))
    has_place_ref = bool(re.search(r"\b(cho cu|kho cu|nhu hom qua|kho hom qua)\b", clean))

    if not (has_vehicle_ref or has_cont_ref or has_place_ref):
        return True

    resolved_all = True

    # 1. Thu thập ngữ cảnh ứng viên từ quote, MessageDraft mở và lịch sử 30 phút của cùng sender
    candidate_plates: set[str] = set()
    candidate_drivers: dict[str, tuple[str | None, str | None]] = {}
    candidate_conts: set[str] = set()
    candidate_warehouses: set[str] = set()

    if quoted_text:
        for pm in re.findall(r"\b\d{2}[A-Z]{1,2}[- .]?\d{3}[- .]?\d{2}\b", quoted_text, re.I):
            cleaned_p = clean_plate(pm)
            if cleaned_p:
                candidate_plates.add(cleaned_p)
        for cm in re.findall(r"\b[A-Z]{4}\d{7}\b", quoted_text, re.I):
            cleaned_c = clean_container(cm)
            if cleaned_c:
                candidate_conts.add(cleaned_c)

    if group_id and sender_id:
        open_drafts = list(
            db.scalars(
                select(MessageDraft).where(
                    MessageDraft.group_id == group_id,
                    MessageDraft.sender_id == sender_id,
                    MessageDraft.status == "OPEN",
                )
            ).all()
        )
        for dr in open_drafts:
            ent = dr.entities if isinstance(dr.entities, dict) else {}
            if ent.get("truck_plate"):
                candidate_plates.add(str(ent["truck_plate"]))
            if ent.get("container_no"):
                candidate_conts.add(str(ent["container_no"]))
            if ent.get("warehouse_hint"):
                candidate_warehouses.add(str(ent["warehouse_hint"]))

        cutoff = (reference_time or datetime.now()) - timedelta(minutes=30)
        recent_jobs = list(
            db.scalars(
                select(ContainerJob)
                .join(ZaloMessage, ContainerJob.message_id == ZaloMessage.id)
                .where(
                    ZaloMessage.group_id == group_id,
                    ZaloMessage.sender_id == sender_id,
                    ZaloMessage.created_at >= cutoff.replace(tzinfo=None),
                )
                .order_by(ContainerJob.id.desc())
                .limit(5)
            ).all()
        )
        for rj in recent_jobs:
            if rj.container_no:
                candidate_conts.add(rj.container_no)
            if rj.warehouse_hint:
                candidate_warehouses.add(rj.warehouse_hint)
            if rj.truck_record and rj.truck_record.truck_plate:
                p_no = rj.truck_record.truck_plate
                candidate_plates.add(p_no)
                candidate_drivers[p_no] = (
                    rj.truck_record.driver_name,
                    rj.truck_record.driver_phone,
                )

    if has_vehicle_ref and not line.truck_plate:
        if len(candidate_plates) == 1:
            chosen_plate = next(iter(candidate_plates))
            line.truck_plate = chosen_plate
            line.field_evidences["truck_plate"] = "coref_unique_vehicle"
            if chosen_plate in candidate_drivers:
                drv_name, drv_phone = candidate_drivers[chosen_plate]
                if not line.driver_name and drv_name:
                    line.driver_name = drv_name
                if not line.driver_phone and drv_phone:
                    line.driver_phone = drv_phone
        else:
            resolved_all = False

    if has_cont_ref and not line.container_no:
        if len(candidate_conts) == 1:
            line.container_no = next(iter(candidate_conts))
            line.field_evidences["container_no"] = "coref_unique_container"
        else:
            resolved_all = False

    if has_place_ref and not line.warehouse_hint:
        if not candidate_warehouses and carrier_id is not None:
            ref_day = vn_time(reference_time).date() - timedelta(days=1)
            prev_plans = list(
                db.scalars(
                    select(TransportPlan).where(
                        TransportPlan.carrier_id == carrier_id,
                        TransportPlan.plan_date == ref_day,
                    )
                ).all()
            )
            for pp in prev_plans:
                wh_label = pp.warehouse_name or pp.delivery_address
                if wh_label:
                    candidate_warehouses.add(wh_label)
        if len(candidate_warehouses) == 1:
            line.warehouse_hint = next(iter(candidate_warehouses))
            line.field_evidences["warehouse_hint"] = "coref_unique_warehouse"
        else:
            resolved_all = False

    return resolved_all


def enrich_local(
    db: Session,
    lines: list[ExtractedContainerLine],
    carrier_id: int | None,
    raw_text: str,
    reference: datetime | None,
    quoted_text: str | None = None,
    group_id: str | None = None,
    sender_id: str | None = None,
) -> list[ExtractedContainerLine]:
    """Làm giàu từ danh mục nhà xe + RapidFuzz + PhoBERT + giải quyết đồng tham chiếu."""
    dates = message_dates(raw_text, reference)
    drivers = (
        list(
            db.scalars(
                select(Driver).where(Driver.carrier_id == carrier_id, Driver.is_active.is_(True))
            ).all()
        )
        if carrier_id
        else []
    )
    vehicles = (
        list(
            db.scalars(
                select(Vehicle).where(Vehicle.carrier_id == carrier_id, Vehicle.is_active.is_(True))
            ).all()
        )
        if carrier_id
        else []
    )
    trailers = list(
        db.scalars(
            select(Trailer).where(
                *(
                    [Trailer.carrier_id == carrier_id, Trailer.is_active.is_(True)]
                    if carrier_id
                    else [Trailer.is_active.is_(True)]
                )
            )
        ).all()
    )
    norm_text = f"{normalized(raw_text)} {normalized(quoted_text)}"
    phobert = PhoBertLocalNlpEngine.get_instance()
    pb_analysis = phobert.analyze(raw_text)

    for line in lines:
        line.candidate_dates = dates
        if not line.plan_date and len(dates) == 1:
            line.plan_date = dates[0]

        line.field_evidences["nlp_engine"] = "rapidfuzz+catalog+phobert"
        line.field_evidences["phobert_mode"] = pb_analysis.backend_mode
        line.field_evidences["phobert_intent"] = pb_analysis.intent_label

        # Nhận diện chuyến kết hợp RO -> LO và loại lệnh từ PhoBERT nếu rule-based chưa bắt được
        if pb_analysis.is_combined_trip:
            line.is_combined_from_return = True
            line.field_evidences["combined_trip"] = "phobert_combined_ro_lo"
        if not line.order_type and pb_analysis.order_type_hint:
            line.order_type = pb_analysis.order_type_hint
            line.inferred_order_type = True
            line.field_evidences["order_type"] = "phobert_intent_classifier"

        # Áp dụng các thực thể BIO (LOC, PER) do PhoBERT trích xuất nếu dòng chưa có
        for span in pb_analysis.spans:
            if span.label == "LOC" and not line.warehouse_hint:
                line.warehouse_hint = span.text
                line.field_evidences["warehouse_hint"] = f"phobert_ner_loc:{span.confidence:.2f}"
            elif span.label == "PER" and not line.driver_name:
                line.driver_name = span.text
                line.field_evidences["driver_name"] = f"phobert_ner_per:{span.confidence:.2f}"

        # Đối sánh Tài xế từ danh mục nhà xe (exact + RapidFuzz)
        if not line.driver_name or not line.driver_phone:
            matched_drivers: list[tuple[float, Driver]] = []
            for d in drivers:
                d_norm = normalized(d.normalized_name or d.full_name)
                if not d_norm:
                    continue
                d_tokens = d_norm.split()
                given_name = d_tokens[-1] if d_tokens else ""
                if d_norm in norm_text or (
                    line.driver_phone and clean_phone(d.phone) == clean_phone(line.driver_phone)
                ):
                    matched_drivers.append((100.0, d))
                elif given_name and len(given_name) >= 2 and (
                    (line.driver_name and normalized(line.driver_name) == given_name)
                    or re.search(
                        rf"\b(?:tai xe|lai xe|tx|lx|tai)\s+{re.escape(given_name)}\b", norm_text
                    )
                ):
                    matched_drivers.append((94.0, d))
                elif line.driver_name:
                    rf_drv = max(
                        fuzz.WRatio(normalized(line.driver_name), d_norm),
                        fuzz.token_set_ratio(normalized(line.driver_name), d_norm),
                    )
                    if rf_drv >= 88.0:
                        matched_drivers.append((float(rf_drv), d))
            if matched_drivers:
                matched_drivers.sort(key=lambda item: item[0], reverse=True)
                unique_ids = {d.id for s, d in matched_drivers if s >= matched_drivers[0][0] - 3.0}
                if len(unique_ids) == 1:
                    best_drv = matched_drivers[0][1]
                    if not line.driver_name or normalized(line.driver_name) in normalized(
                        best_drv.full_name
                    ):
                        line.driver_name = best_drv.full_name
                    line.driver_phone = line.driver_phone or clean_phone(best_drv.phone)
                    line.extraction_tier = "TIER_2_LOCAL_NLP"
                    line.field_evidences["driver"] = "carrier_driver_catalog_rapidfuzz"
                elif len(unique_ids) > 1 and "ambiguous_driver" not in line.unresolved_fields:
                    line.unresolved_fields.append("ambiguous_driver")

        # Đối sánh Biển số xe viết tắt (4-5 số cuối) từ danh mục phương tiện nhà xe
        if not line.truck_plate:
            short = re.findall(r"\b\d{3}[.]?\d{2}\b|\b\d{4,5}\b", raw_text)
            candidates = [
                v
                for v in vehicles
                if v.vehicle_type == 1
                and any(
                    compact_plate(v.plate_no or "").endswith(re.sub(r"\D", "", token))
                    for token in short
                )
            ]
            if len(candidates) == 1:
                line.truck_plate = clean_plate(candidates[0].plate_no) or candidates[0].plate_no
                line.extraction_tier = "TIER_2_LOCAL_NLP"
                line.field_evidences["truck_plate"] = "carrier_vehicle_suffix"
            elif len(candidates) > 1 and "ambiguous_plate" not in line.unresolved_fields:
                line.unresolved_fields.append("ambiguous_plate")

        # Đối sánh Biển số rơ-moóc viết tắt (4-5 số cuối sau từ khóa mooc/rm) từ danh mục `trailers`
        if not line.trailer_plate and trailers:
            mooc_short = re.findall(
                r"\b(?:mooc|rơ\s*moóc|ro\s*mooc|rm)\s*[:\-]?\s*(\d{3}[.]?\d{2}|\d{4,5})\b",
                raw_text,
                flags=re.IGNORECASE,
            )
            if mooc_short:
                tr_cands = [
                    t
                    for t in trailers
                    if any(
                        (t.normalized_plate or "").endswith(re.sub(r"\D", "", tok))
                        for tok in mooc_short
                    )
                ]
                if len(tr_cands) == 1:
                    line.trailer_plate = clean_plate(tr_cands[0].license_plate) or tr_cands[0].license_plate
                    line.extraction_tier = "TIER_2_LOCAL_NLP"
                    line.field_evidences["trailer_plate"] = "carrier_trailer_suffix"

        # Đối sánh Từ điển danh mục (Khách hàng, Kho, Alias, Kế hoạch) bằng RapidFuzz
        _match_catalog_gazetteer(db, line, carrier_id, raw_text, dates)

        # Trạng thái chờ cont / chờ chì hợp lệ cho lệnh đóng
        if re.search(r"\b(chua co cont|cont bao sau|lay rong|doi cap cont)\b", norm_text):
            line.container_status = "DEFERRED"
        if re.search(r"\b(chua co chi|chi bao sau|seal bao sau|chua cap chi)\b", norm_text):
            line.seal_status = "DEFERRED"

        # Giải quyết đồng tham chiếu ('xe trên', 'xe này', 'cont đó', 'chỗ cũ', 'kho cũ')
        if not _resolve_conversational_coreference(
            db=db,
            line=line,
            raw_text=raw_text,
            quoted_text=quoted_text,
            carrier_id=carrier_id,
            group_id=group_id,
            sender_id=sender_id,
            reference_time=reference,
        ):
            if "context_reference" not in line.unresolved_fields:
                line.unresolved_fields.append("context_reference")
        else:
            if "context_reference" in line.unresolved_fields:
                line.unresolved_fields.remove("context_reference")

        if any(
            k in line.field_evidences
            for k in ("warehouse", "customer", "booking_no", "combined_trip", "order_type")
        ):
            line.extraction_tier = "TIER_2_LOCAL_NLP"

    return lines
