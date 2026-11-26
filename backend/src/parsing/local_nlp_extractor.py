"""Tầng 2 NLP nội bộ: RapidFuzz + Từ điển danh mục (Catalog Gazetteer) + PhoBERT + Giải quyết đồng tham chiếu."""

import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz, process
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.domain.models import ExtractedContainerLine
from src.domain.patterns import (
    CONT_REGEX,
    PHONE_PATTERN,
    PLATE_REGEX,
    TRAILER_PLATE_REGEX,
    split_camel_case_vn,
)
from src.domain.rules import (
    clean_container,
    clean_driver_name,
    clean_phone,
    clean_plate,
    compact_plate,
    split_phones,
)
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

# Bộ mẫu ngữ nghĩa cho Trợ lý ĐHVT (Tầng 2 PhoBERT phân loại ý định & nhận diện chat nội bộ)
DHVT_ASSISTANT_INTENT_PROTOTYPES: dict[str, tuple[str, ...]] = {
    "dhvt_direct_review_action": (
        "duyệt ca này giúp em",
        "đồng ý xác nhận cho gửi khách",
        "từ chối vì không đúng thông tin xe",
        "từ chối cont chưa có lịch",
        "hủy yêu cầu này cont có thông tin rồi",
        "không duyệt lệnh này",
        "sửa biển số xe và duyệt gửi khách",
    ),
    "dhvt_get_daily_overview": (
        "hôm nay có bao nhiêu chuyến vận chuyển",
        "hôm nay bao nhiêu chuyến",
        "hôm nay tổng số lệnh đóng trả theo từng vùng thế nào",
        "thống kê tổng quan kế hoạch hôm nay theo từng vùng",
        "thống kê kế hoạch ngày",
        "xem kế hoạch vận chuyển ngày",
        "kế hoạch hôm nay",
        "hôm nay cân đối vỏ thế nào",
        "miền bắc hôm nay có bao nhiêu lệnh đóng",
        "hôm nay có bao nhiêu lệnh đóng lệnh trả",
        "số lệnh trả hôm nay là bao nhiêu",
        "thống kê lệnh đóng trả theo tỉnh hôm nay",
    ),
    "dhvt_get_province_plans": (
        "chi tiết kế hoạch tỉnh hải phòng",
        "chi tiết hải phòng",
        "danh sách các lệnh ở ninh bình ngày",
        "xem các chuyến tại phú thọ",
        "chi tiết tỉnh hưng yên",
    ),
    "dhvt_get_unassigned_plans": (
        "chuyến nào chưa có xe",
        "những lệnh nào thiếu container hoặc thiếu xe",
        "xem lệnh chưa bố trí xe cận giờ",
        "danh sách lệnh chưa báo đủ xe",
    ),
    "dhvt_get_priority_digest": (
        "hôm nay có gì cần xử lý gấp",
        "có gì cần xử lý gấp hôm nay không",
        "xem danh sách ca chờ duyệt",
        "hàng chờ duyệt có bao nhiêu ca",
    ),
    "dhvt_detect_duplicate_vehicles": (
        "có xe nào trùng chuyến hoặc trùng giờ không",
        "xe nào trùng chuyến",
        "kiểm tra xe trùng lịch hôm nay",
    ),
    "dhvt_get_container_warnings": (
        "có vỏ nào cảnh báo hạ rỗng hoặc soc không",
        "có vỏ nào hạ rỗng",
        "kiểm tra cảnh báo vỏ kết hợp quá sl bên khác đã xin",
    ),
    "dhvt_get_validation_failures": (
        "có cont nào chưa khớp hoặc báo sai dữ liệu không",
        "có cont nào chưa khớp",
        "kiểm tra lệch chì lệch seal lỗi dữ liệu",
    ),
    "dhvt_get_delivery_and_sync_errors": (
        "có tin gửi khách thất bại hoặc lỗi đồng bộ tms không",
        "có tin gửi khách thất bại",
        "kiểm tra lỗi gửi khách và đồng bộ hệ thống",
    ),
    "dhvt_get_bot_performance": (
        "hôm nay tỷ lệ bot tự xử lý và dùng llm thế nào",
        "hôm nay tỷ lệ dùng llm",
    ),
    "dhvt_get_audit_timeline": (
        "chuyến này đã đổi những gì xem lịch sử nhật ký",
        "bot đã làm gì cho lệnh này",
    ),
    "BLOCK_WRITE": (
        "xóa toàn bộ bảng dữ liệu",
        "xóa toàn bộ bảng kế hoạch",
        "xóa hết đi",
        "reset dọn sạch bảng kế hoạch",
        "xóa bỏ toàn bộ dữ liệu trong bảng",
    ),
    "INTERNAL_CHAT_IGNORE": (
        "cont này có thông tin rồi",
        "có thông tin rồi nhé",
        "thông tin",
        "xe này chạy rồi em ơi",
        "để em gọi lại nhà xe kiểm tra nhé",
        "anh em nhớ để ý chuyến này",
        "vâng để em nhắn khách hàng luôn",
        "hôm nay trời mưa quá tắc đường",
    ),
}


@dataclass
class PhoBertAssistantIntentResult:
    """Kết quả phân loại ý định Trợ lý ĐHVT từ tầng NLP PhoBERT kèm điểm tin cậy và ứng viên."""

    intent: str
    confidence: float
    margin: float
    is_confident: bool
    backend_mode: str
    top_candidates: list[dict[str, Any]] = field(default_factory=list)


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
    backend_mode: str = "rule_char_ngram_fuzzy_nlp"


class PhoBertLocalNlpEngine:
    """Bộ xử lý Local NLP mặc định chạy trọng số thật `vinai/phobert-base-v2` (`phobert_transformers_local`)
    kết hợp bộ đệm LRU embedding + vector hóa cosine similarity và ngưỡng `INTENT_MIN_CONFIDENCE`.
    """

    _instance: "PhoBertLocalNlpEngine | None" = None
    INTENT_MIN_CONFIDENCE: float = 0.65

    _SKELETON_PLATE_RE = re.compile(r"\b\d{2}[a-z]{1,2}[\s.\-/]*\d{3,5}(?:\.\d{2})?\b", re.IGNORECASE)
    _SKELETON_CONT_RE = re.compile(r"\b[a-z]{3}[ujz][\s.\-]*\d{7}\b", re.IGNORECASE)
    _SKELETON_PHONE_RE = re.compile(r"(?:\+?84|0)[\d\s.\-*xX]{8,12}")
    _SKELETON_CODE_RE = re.compile(r"\b(?:ro|lo|bk|bl|vs)\d{3,10}\b", re.IGNORECASE)

    def __init__(self) -> None:
        """Khởi tạo PhoBERT tokenizer/model (`vinai/phobert-base-v2`) cục bộ mặc định."""
        self.model_name = os.getenv("PHOBERT_MODEL_PATH", "vinai/phobert-base-v2")
        self._tokenizer: Any = None
        self._model: Any = None
        self._torch: Any = None
        self._proto_embeddings: dict[str, list[Any]] = {}
        self._proto_matrix: Any = None
        self._proto_labels: list[str] = []
        self._ner_loc_anchor: Any = None
        self._ner_per_anchor: Any = None
        self._embed_cache: dict[str, Any] = {}
        self._dhvt_mean_emb: Any = None
        self._dhvt_proto_mats: dict[str, Any] = {}
        self._dhvt_proto_centroids: dict[str, Any] = {}
        self.backend_mode = "rule_char_ngram_fuzzy_nlp"
        self._try_load_local_transformers()

    def _try_load_local_transformers(self) -> None:
        """Nạp trọng số `vinai/phobert-base-v2` cục bộ hoàn toàn offline và hiệu chuẩn vector trung bình (mean-centering)."""
        enabled_flag = os.getenv("ENABLE_PHOBERT_TRANSFORMERS", "1").strip().lower()
        if enabled_flag in ("0", "false", "no", "off"):
            return
        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            import torch  # type: ignore[import-not-found]
            from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found]

            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, local_files_only=True)
            self._model = AutoModel.from_pretrained(self.model_name, local_files_only=True)
            self._model.eval()
            self.backend_mode = "phobert_transformers_local"

            # Tính vector trung bình nền (mean-centering) để khử anisotropy vốn có của RoBERTa/PhoBERT
            background_texts = [
                "xin chao moi nguoi hom nay troi dep qua an com chua",
                "cam on anh chi chuc ngay moi vui ve hen gap lai",
                "thong bao giao nhan van tai container kho bai cang bien",
                *[p for protos in INTENT_PROTOTYPES.values() for p in protos],
            ]
            raw_bg = [self._encode_raw_phobert_embedding(t) for t in background_texts]
            self._mean_emb = torch.stack(raw_bg, dim=0).mean(dim=0)

            proto_tensors: list[Any] = []
            proto_labels: list[str] = []
            self._proto_embeddings = {}
            for label, protos in INTENT_PROTOTYPES.items():
                embs = [self._encode_phobert_embedding(proto) for proto in protos]
                self._proto_embeddings[label] = embs
                for emb in embs:
                    proto_tensors.append(emb)
                    proto_labels.append(label)
            if proto_tensors:
                self._proto_matrix = torch.stack(proto_tensors, dim=0)
                self._proto_labels = proto_labels
            self._ner_loc_anchor = self._encode_phobert_embedding("kho hàng khu công nghiệp cảng nhà máy giao nhận")
            self._ner_per_anchor = self._encode_phobert_embedding("tài xế lái xe anh nguyễn văn minh")
        except Exception:
            self._torch = None
            self._tokenizer = None
            self._model = None
            self._mean_emb = None
            self._proto_embeddings = {}
            self._proto_matrix = None
            self._proto_labels = []
            self._ner_loc_anchor = None
            self._ner_per_anchor = None
            self.backend_mode = "rule_char_ngram_fuzzy_nlp"

    @classmethod
    def _intent_skeleton(cls, text: str) -> str:
        """Chuẩn hóa bộ khung câu tiếng Việt (thay biển số/cont/SĐT bằng từ loại chung) để tăng độ chính xác PhoBERT và cache."""
        clean = normalized(text)
        clean = cls._SKELETON_CONT_RE.sub(" so_cont ", clean)
        clean = cls._SKELETON_PLATE_RE.sub(" bien_so ", clean)
        clean = cls._SKELETON_PHONE_RE.sub(" sdt ", clean)
        clean = cls._SKELETON_CODE_RE.sub(" ma_lenh ", clean)
        clean = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ngay ", clean)
        clean = re.sub(r"\b\d{1,2}[:h]\d{0,2}\b", " gio ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean[:220]

    def _encode_raw_phobert_embedding(self, text: str) -> Any:
        """Tính vector mean-pooling thô từ lớp ẩn cuối của PhoBERT (chưa trừ vector nền)."""
        torch = self._torch
        seg = self.segment_vietnamese_compounds(text)
        encoded = self._tokenizer(
            seg,
            return_tensors="pt",
            truncation=True,
            max_length=96,
            padding=True,
        )
        with torch.no_grad():
            out = self._model(**encoded)
            mask = encoded["attention_mask"].unsqueeze(-1).float()
            summed = (out.last_hidden_state * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            return (summed / counts).squeeze(0)

    def _encode_phobert_embedding(self, text: str) -> Any:
        """Tính vector ngữ nghĩa PhoBERT đã khử anisotropy (trừ vector trung bình nền + chuẩn hóa L2, có cache)."""
        seg = self.segment_vietnamese_compounds(text)
        cached = self._embed_cache.get(seg)
        if cached is not None:
            return cached
        torch = self._torch
        raw = self._encode_raw_phobert_embedding(text)
        mean_emb = getattr(self, "_mean_emb", None)
        if mean_emb is not None:
            raw = raw - mean_emb
        vec = torch.nn.functional.normalize(raw.unsqueeze(0), p=2, dim=1).squeeze(0)
        if len(self._embed_cache) < 32768:
            self._embed_cache[seg] = vec
        return vec

    def _phobert_intent_scores(self, text: str) -> tuple[str, float]:
        """Phân loại ý định trực tiếp bằng phép nhân ma trận cosine similarity trên embedding PhoBERT."""
        skeleton = self._intent_skeleton(text)
        if not skeleton:
            return "UNKNOWN", 0.0
        q_emb = self._encode_phobert_embedding(skeleton)
        if self._proto_matrix is not None and self._proto_labels:
            sims = self._torch.mv(self._proto_matrix, q_emb)
            best_idx = int(self._torch.argmax(sims).item())
            best_score = float(sims[best_idx].item())
            best_label = self._proto_labels[best_idx]
        else:
            best_label = "UNKNOWN"
            best_score = 0.0
            for label, proto_embs in self._proto_embeddings.items():
                for p_emb in proto_embs:
                    sim = float(self._torch.dot(q_emb, p_emb).item())
                    if sim > best_score:
                        best_score = sim
                        best_label = label
        if best_score < self.INTENT_MIN_CONFIDENCE:
            return "UNKNOWN", round(max(0.0, best_score), 4)
        return best_label, round(best_score, 4)

    def _ensure_dhvt_assistant_prototypes(self) -> None:
        """Khởi tạo lười (lazy-init) ma trận vector PhoBERT mean-centered cho bộ ý định Trợ lý ĐHVT."""
        if self._model is None or self._torch is None or self._dhvt_proto_mats:
            return
        torch = self._torch
        raw_map: dict[str, Any] = {}
        for protos in DHVT_ASSISTANT_INTENT_PROTOTYPES.values():
            for proto in protos:
                if proto not in raw_map:
                    raw_map[proto] = self._encode_raw_phobert_embedding(proto)
        self._dhvt_mean_emb = torch.stack(list(raw_map.values()), dim=0).mean(dim=0)
        mats: dict[str, Any] = {}
        centroids: dict[str, Any] = {}
        for label, protos in DHVT_ASSISTANT_INTENT_PROTOTYPES.items():
            vecs = [
                torch.nn.functional.normalize((raw_map[p] - self._dhvt_mean_emb).unsqueeze(0), p=2, dim=1).squeeze(0)
                for p in protos
            ]
            mat = torch.stack(vecs, dim=0)
            mats[label] = mat
            centroids[label] = torch.nn.functional.normalize(mat.mean(dim=0, keepdim=True), p=2, dim=1).squeeze(0)
        self._dhvt_proto_mats = mats
        self._dhvt_proto_centroids = centroids

    @staticmethod
    def _normalize_dhvt_query_for_phobert(text: str) -> str:
        """Chuẩn hóa chữ thường, bỏ dấu câu thừa và quy đổi ngày cụ thể về từ loại 'ngày' cho PhoBERT (case-sensitive)."""
        cleaned = re.sub(r"\[@\d+\]", " ", text or "").strip().lower()
        cleaned = re.sub(r"\b(?:ngày\s+)?\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", "ngày", cleaned)
        cleaned = re.sub(r"[?!.,;:]+", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def classify_dhvt_intent(
        self,
        text: str,
        *,
        has_quoted_pending_case: bool = False,
        is_bot_mentioned: bool = False,
        has_question_mark: bool = False,
    ) -> PhoBertAssistantIntentResult:
        """Phân loại ý định tin nhắn nhóm ĐHVT bằng PhoBERT mean-centered embedding kết hợp bối cảnh hội thoại."""
        cleaned = self._normalize_dhvt_query_for_phobert(text)
        if not cleaned:
            return PhoBertAssistantIntentResult(
                intent="INTERNAL_CHAT_IGNORE",
                confidence=1.0,
                margin=1.0,
                is_confident=True,
                backend_mode=self.backend_mode,
            )

        raw_scores: dict[str, float] = {}
        if self._model is not None and self._torch is not None:
            self._ensure_dhvt_assistant_prototypes()
            torch = self._torch
            q_raw = self._encode_raw_phobert_embedding(cleaned) - self._dhvt_mean_emb
            q_vec = torch.nn.functional.normalize(q_raw.unsqueeze(0), p=2, dim=1).squeeze(0)
            for label, mat in self._dhvt_proto_mats.items():
                sims = torch.mv(mat, q_vec)
                top1 = float(sims.max().item())
                cent = float(torch.dot(self._dhvt_proto_centroids[label], q_vec).item())
                raw_scores[label] = 0.65 * top1 + 0.35 * cent
        else:
            # Fallback RapidFuzz trên cùng tập prototype khi tắt PyTorch (`ENABLE_PHOBERT_TRANSFORMERS=0`)
            q_norm = normalized(cleaned)
            for label, protos in DHVT_ASSISTANT_INTENT_PROTOTYPES.items():
                ratios = [
                    0.5 * (fuzz.token_set_ratio(q_norm, normalized(p)) / 100.0)
                    + 0.5 * (fuzz.WRatio(q_norm, normalized(p)) / 100.0)
                    for p in protos
                ]
                raw_scores[label] = 0.65 * max(ratios) + 0.35 * (sum(ratios) / max(len(ratios), 1))

        # Áp dụng trọng số bối cảnh hội thoại thật (quote ca duyệt PENDING / @mention / dấu hỏi)
        if has_quoted_pending_case:
            raw_scores["dhvt_direct_review_action"] = raw_scores.get("dhvt_direct_review_action", 0.0) + 0.18
            raw_scores["INTERNAL_CHAT_IGNORE"] = raw_scores.get("INTERNAL_CHAT_IGNORE", 0.0) - 0.15
        elif not is_bot_mentioned and not has_question_mark:
            raw_scores["INTERNAL_CHAT_IGNORE"] = raw_scores.get("INTERNAL_CHAT_IGNORE", 0.0) + 0.04

        ranked = sorted(raw_scores.items(), key=lambda kv: kv[1], reverse=True)
        top1_label, top1_score = ranked[0]
        top2_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = max(0.0, top1_score - top2_score)

        if self._model is not None:
            is_confident = (top1_score >= 0.50 and margin >= 0.10) or (top1_score >= 0.42 and margin >= 0.18)
        else:
            is_confident = (top1_score >= 0.68 and margin >= 0.08) or (top1_score >= 0.58 and margin >= 0.14)

        top_candidates = [
            {"intent": lbl, "score": round(float(sc), 4)}
            for lbl, sc in ranked[:3]
        ]
        return PhoBertAssistantIntentResult(
            intent=top1_label,
            confidence=round(max(0.0, min(1.0, float(top1_score))), 4),
            margin=round(float(margin), 4),
            is_confident=is_confident,
            backend_mode=self.backend_mode,
            top_candidates=top_candidates,
        )

    def _phobert_span_confidence(self, span_text: str, label: str, base_conf: float) -> float:
        """Tính độ tin cậy động cho thực thể `LOC`/`PER` dựa trên cosine similarity với vector neo PhoBERT."""
        anchor = self._ner_loc_anchor if label == "LOC" else self._ner_per_anchor
        if self._model is None or anchor is None:
            return round(min(0.95, base_conf), 2)
        emb = self._encode_phobert_embedding(span_text)
        sim = float(self._torch.dot(emb, anchor).item())
        blended = 0.55 * base_conf + 0.45 * max(0.0, min(1.0, sim))
        return round(max(0.50, min(0.97, blended)), 2)

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
        """Sinh vector char-word n-gram phục vụ đối sánh cục bộ khi chạy chế độ nhẹ không có PyTorch."""
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
        """Tính độ tương đồng kết hợp Cosine N-gram và RapidFuzz."""
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
        """Phân tích ý định điều vận (có ngưỡng `INTENT_MIN_CONFIDENCE`), luồng RO->LO và trích xuất thực thể với điểm tin cậy động."""
        clean = normalized(raw_text)
        segmented = self.segment_vietnamese_compounds(raw_text)
        best_intent = "UNKNOWN"
        best_score = 0.0

        if self._model is not None and self._tokenizer is not None and self._proto_embeddings:
            best_intent, best_score = self._phobert_intent_scores(raw_text)
            # Kết hợp thêm tín hiệu khớp cụm từ khóa chính xác nếu có
            for label, prototypes in INTENT_PROTOTYPES.items():
                for proto in prototypes:
                    if proto in clean and best_score < 0.92:
                        best_score = 0.92
                        best_intent = label
        else:
            for label, prototypes in INTENT_PROTOTYPES.items():
                for proto in prototypes:
                    score = self.semantic_similarity(clean, proto)
                    if proto in clean:
                        score = max(score, 0.92)
                    if score > best_score:
                        best_score = score
                        best_intent = label
            # Ngưỡng tin cậy tối thiểu: không gán bừa intent khi điểm tương đồng quá thấp
            if best_score < self.INTENT_MIN_CONFIDENCE:
                best_intent = "UNKNOWN"

        is_combined = bool(
            re.search(
                r"\b(tra\s+xong\s+dong|ha\s+.*?\s+xong\s+dong|ket\s+hop|quay\s+dau\s+dong|giao\s+.*?\s+xong\s+.*?\s*dong)\b",
                clean,
            )
            or (best_intent == "COMBINED_TRIP" and best_score >= self.INTENT_MIN_CONFIDENCE)
        )
        order_type_hint: str | None = None
        if is_combined:
            order_type_hint = "LOAD"
        elif re.search(r"\b(dong\s+hang|lenh\s+dong|lay\s+rong|boc\s+hang|dong\s+kho|dong\s+cont)\b", clean):
            order_type_hint = "LOAD"
        elif re.search(r"\b(tra\s+hang|tra\s+vo|ha\s+rong|lenh\s+tra|giao\s+hang|ha\s+bai)\b", clean):
            order_type_hint = "RETURN"

        spans: list[PhoBertNerSpan] = []
        # B-LOC / I-LOC: Kho / KCN / Nhà máy / Địa điểm (điểm tin cậy động theo cấu trúc nhãn & độ dài ứng viên)
        loc_patterns = [
            (
                r"\b(?:kho|kcn|khu cong nghiep|nha may|nm|cang|icd|cum cn)\s+([a-z0-9\s\-]{2,45}?)(?=\s+(?:luc|gio|cont|xe|tai|sdt|chi|seal|ngay|mai|hom)|[,;.\n]|$)",
                0.78,
            ),
            (
                r"\b(?:dong|tra|giao|ha)\s+(?:o|tai)?\s*(?:kho|kcn|nha may)?\s*([a-z0-9\s\-]{3,35}?)(?=\s+(?:luc|gio|cont|xe|tai|sdt|chi|seal)|[,;.\n]|$)",
                0.68,
            ),
        ]
        for pat, base_conf in loc_patterns:
            for m in re.finditer(pat, clean):
                candidate_loc = m.group(1).strip()
                if candidate_loc and candidate_loc not in ("hang", "vo", "rong", "cont", "luon", "tiep"):
                    token_bonus = min(0.14, 0.04 * len(candidate_loc.split()))
                    dyn_conf = self._phobert_span_confidence(
                        candidate_loc, "LOC", min(0.95, base_conf + token_bonus)
                    )
                    spans.append(
                        PhoBertNerSpan(
                            label="LOC",
                            text=candidate_loc,
                            normalized_text=candidate_loc,
                            confidence=dyn_conf,
                        )
                    )

        # B-PER: Tên tài xế sau nhãn "tài", "lx", "lái xe", "bác tài" (điểm tin cậy động kết hợp PhoBERT)
        per_match = re.search(
            r"\b(?:tai xe|lai xe|bac tai|lx|tai)\s+([a-z\s]{2,30}?)(?=\s+(?:\d|sdt|dt|cont|xe|chi|seal|kho|tra|dong|giao|ha|luc|hen)|[,;.\n]|$)",
            clean,
        )
        if per_match:
            drv_raw = per_match.group(1).strip()
            word_cnt = len(drv_raw.split())
            if 1 <= word_cnt <= 5:
                per_conf = self._phobert_span_confidence(
                    drv_raw, "PER", 0.66 + min(0.24, 0.08 * word_cnt)
                )
                spans.append(
                    PhoBertNerSpan(
                        label="PER",
                        text=drv_raw,
                        normalized_text=drv_raw,
                        confidence=per_conf,
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
        compact_bk = re.search(r"\b(BK\d{4,20})\b", raw_text, re.I)
        if compact_bk:
            line.booking_no = compact_bk.group(1).upper()
            line.field_evidences["booking_no"] = "regex_booking"
        else:
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


_RESIDUAL_STOP_WORDS_RE = re.compile(
    r"\b(?:đóng\s*hàng|dong\s*hang|trả\s*hàng|tra\s*hang|trả\s*vỏ|tra\s*vo|hạ\s*rỗng|ha\s*rong|"
    r"lấy\s*rỗng|lay\s*rong|giao\s*hàng|giao\s*hang|đóng\s*cont|dong\s*cont|trả\s*cont|tra\s*cont|"
    r"kho|nhà\s*máy|nha\s*may|khách\s*hàng|khach\s*hang|cont|container|cntr|"
    r"seal|chì|chi|booking|lệnh|lenh|cảng|cang|kcn|khu\s*công\s*nghiệp|khu\s*cong\s*nghiep|bãi|bai|"
    r"biển\s*số|bien\s*so|bks|mooc|rơ\s*moóc|ro\s*mooc|dự\s*kiến|du\s*kien|eta|thông\s*báo|thong\s*bao|"
    r"danh\s*sách|danh\s*sach|kế\s*hoạch|ke\s*hoach|điều\s*xe|dieu\s*xe|chưa\s*có|chua\s*co|chờ\s*cấp|cho\s*cap|"
    r"kính\s*gửi|kinh\s*gui|stt|điện\s*thoại|dien\s*thoai|chuyến|chuyen|hôm\s*nay|hom\s*nay|ngày\s*mai|ngay\s*mai|"
    r"cảm\s*ơn|cam\s*on|xác\s*nhận|xac\s*nhan|bổ\s*sung|bo\s*sung|cập\s*nhật|cap\s*nhat|"
    r"đính\s*chính|dinh\s*chinh|thay\s*đổi|thay\s*doi|nhé|nhe|nha|ơi|oi|giúp|giup|xong|rồi|roi|"
    r"công\s*ty|cong\s*ty|tnhh|cổ\s*phần|co\s*phan|miền\s*bắc|mien\s*bac|miền\s*nam|mien\s*nam|miền\s*trung|mien\s*trung|"
    r"tỉnh|tinh|thành\s*phố|thanh\s*pho|hà\s*nội|ha\s*noi|hải\s*phòng|hai\s*phong|hưng\s*yên|hung\s*yen|"
    r"bắc\s*ninh|bac\s*ninh|hải\s*dương|hai\s*duong|ninh\s*bình|ninh\s*binh|phú\s*thọ|phu\s*tho|"
    r"bình\s*dương|binh\s*duong|đồng\s*nai|dong\s*nai|hồ\s*chí\s*minh|ho\s*chi\s*minh|hcm|"
    r"đầu\s*kéo|dau\s*keo|sdt|sđt|sddt|cccd|cmnd|chủ\s*hàng|chu\s*hang|nhà\s*xe|nha\s*xe|thầu\s*phụ|thau\s*phu|"
    r"điều\s*hành|dieu\s*hanh|không\s*có|khong\s*co|báo\s*sau|bao\s*sau|alo|ok|oki|vâng|vang|dạ)\b",
    re.IGNORECASE,
)

_VI_COMMON_SURNAMES: frozenset[str] = frozenset(
    {
        "nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo",
        "dang", "bui", "do", "ho", "ngo", "duong", "ly", "dao", "dinh", "doan",
        "trinh", "mai", "ta", "cao", "chu", "to", "luu", "phung", "vuong", "truong",
        "luong", "tang", "quach", "thai", "kieu", "la", "tong", "nghiem", "tinh",
        "ha", "trung", "chau", "dam", "giang", "khong", "khuat", "la", "lam",
        "mac", "nguy", "nong", "phi", "quang", "thach", "trieu", "van", "vi",
    }
)

_ATTACHED_PHONE_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:s+d+đ*t+|s+đ+t+|d+t+|đ+t+|tel|lh|hl|zalo|phone|call|alo|tx|lx)\s*[:.\-]?\s*"
    r"((?:\+?84|0)[35789](?:[ \t\u00a0.\-]?\d){8})(?![\dxX*])",
    re.IGNORECASE,
)
_ATTACHED_PLATE_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(xe|bks|đầu\s*kéo|dau\s*keo|mooc|rơ\s*moóc|ro\s*mooc|rm)\s*[:.\-]?(?=\d{2}[A-Za-zđĐ])",
    re.IGNORECASE,
)
_ATTACHED_CONT_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(cont|cntr|container|công|cong)\s*[:.\-]?(?=[A-Za-z]{3}[UJZujz][\s.\-]?\d{7})",
    re.IGNORECASE,
)


def _flex_alnum_pattern(compact_val: str) -> str:
    """Tạo regex khớp chuỗi chữ-số bất kể ký tự phân cách (`.`, `-`, `/`, khoảng trắng) ở giữa."""
    chars = [re.escape(ch) for ch in re.sub(r"[^A-Za-z0-9]", "", compact_val or "")]
    if not chars:
        return ""
    return r"[\s.\-_/]*".join(chars)


def _strip_extracted_entities_for_residual(line: ExtractedContainerLine) -> str:
    """Loại bỏ toàn bộ các thực thể đã bóc tách thành công và các nhãn kỹ thuật để lấy phần văn bản dư."""
    residual = line.line_text or ""
    if not residual.strip():
        return ""

    # 1. Loại bỏ CCCD / CMND / Seal / Chì / Booking có nhãn
    residual = re.sub(
        r"\b(?:cccd|cmnd|căn\s*cước|can\s*cuoc|chứng\s*minh|chung\s*minh|số\s*chì|so\s*chi|"
        r"số\s*seal|so\s*seal|seal|chì|chi|booking|\bbk\b)\s*[:\-]?\s*[A-Za-z0-9\-_/]+",
        " | ",
        residual,
        flags=re.IGNORECASE,
    )
    residual = re.sub(r"\b(?:RO|LO|BK|DR)\d{3,8}\b", " | ", residual, flags=re.IGNORECASE)

    # 2. Loại bỏ container, biển số đầu kéo, rơ-moóc, SĐT đã bắt được (kèm nhãn đứng liền trước nếu có)
    if line.container_no:
        pat_c = _flex_alnum_pattern(line.container_no)
        if pat_c:
            residual = re.sub(
                rf"(?:(?:số\s*)?(?:cont|cntr|container|công|cong)\s*[:.\-]?\s*)?{pat_c}",
                " | ",
                residual,
                flags=re.IGNORECASE,
            )

    for val in (line.truck_plate, line.raw_truck_plate, line.trailer_plate):
        if val:
            pat = _flex_alnum_pattern(val)
            if pat:
                residual = re.sub(
                    rf"(?:(?:rơ\s*[\-\s]*moóc|ro\s*[\-\s]*mooc|biển\s*(?:số\s*)?(?:xe|mooc)?|bien\s*(?:so\s*)?(?:xe|mooc)?|đầu\s*kéo|dau\s*keo|bks|mooc|rm|xe)\s*[:.\-]?\s*)?{pat}",
                    " | ",
                    residual,
                    flags=re.IGNORECASE,
                )

    phone_lbl = r"(?:(?:s+d+đ*t+|s+đ+t+|d+t+|đ+t+|điện\s*thoại|dien\s*thoai|tel|lh|hl|zalo|phone|call)\s*[:.\-]?\s*)?"
    for ph in split_phones(line.driver_phone):
        pat_ph = _flex_alnum_pattern(ph)
        if pat_ph:
            residual = re.sub(rf"{phone_lbl}{pat_ph}", " | ", residual, flags=re.IGNORECASE)
        if ph.startswith("0") and len(ph) >= 9:
            pat_84 = r"\+?84[\s.\-]*" + _flex_alnum_pattern(ph[1:])
            residual = re.sub(rf"{phone_lbl}{pat_84}", " | ", residual, flags=re.IGNORECASE)

    for exact_val in (line.driver_name, line.seal_no, line.booking_no, line.customer_hint, line.warehouse_hint):
        if exact_val and len(str(exact_val).strip()) >= 2:
            residual = re.sub(re.escape(str(exact_val).strip()), " | ", residual, flags=re.IGNORECASE)

    # 3. Loại bỏ ngày tháng, giờ hẹn, cỡ cont
    residual = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " | ", residual)
    residual = re.sub(r"\b\d{1,2}\s*[:h]\s*\d{0,2}\b", " | ", residual, flags=re.IGNORECASE)
    residual = re.sub(
        r"\b(?:\d+\s*[xX]\s*)?(?:20|40|45)\s*(?:DC|HC|HQ|GP|RF|OT|FR|FT|'|feet)?\b",
        " | ",
        residual,
        flags=re.IGNORECASE,
    )
    return residual


def _recover_missing_fields_local(
    line: ExtractedContainerLine,
    raw_text: str,
    phobert: PhoBertLocalNlpEngine,
    tms_driver_syllables: frozenset[str],
    include_phobert: bool = True,
) -> bool:
    """Tầng 2 Local NLP cứu hộ có mục tiêu cho từng trường còn thiếu trước khi xét gọi Tầng 3 LLM."""
    recovered = False
    source_text = line.line_text or raw_text or ""
    if not source_text.strip():
        return False

    # 1. Cứu SĐT bị gõ dính nhãn (VD: SDDT0345032001, DT0912345678, ALO0389257627)
    if not line.driver_phone:
        residual = _strip_extracted_entities_for_residual(line)
        found_phones: list[str] = []
        for m_att in _ATTACHED_PHONE_LABEL_RE.finditer(residual):
            cleaned_p = clean_phone(m_att.group(1))
            if cleaned_p and len(cleaned_p) == 10 and cleaned_p.startswith("0") and cleaned_p not in found_phones:
                found_phones.append(cleaned_p)
        if not found_phones:
            # Tách biên chung cho chuỗi chữ cái ngắn (1-5 chữ) dính liền đầu số di động VN 10 số
            for m_gen in re.finditer(
                r"(?<![A-Za-z0-9])[A-Za-zĐđ]{1,5}((?:0|\+?84)[35789](?:[ \t\u00a0.\-]?\d){8})(?![\dxX*])",
                residual,
            ):
                prefix_alpha = m_gen.group(0)[: m_gen.start(1) - m_gen.start(0)].lower()
                if prefix_alpha in ("cccd", "cmnd", "seal", "cont", "cntr"):
                    continue
                cleaned_p = clean_phone(m_gen.group(1))
                if cleaned_p and len(cleaned_p) == 10 and cleaned_p.startswith("0") and cleaned_p not in found_phones:
                    found_phones.append(cleaned_p)
        if found_phones:
            line.driver_phone = " | ".join(found_phones)
            line.extraction_tier = "TIER_2_LOCAL_NLP"
            line.field_evidences["driver_phone"] = "local_nlp_attached_label_phone"
            recovered = True

    # 2. Cứu biển số đầu kéo / rơ-moóc bị dính nhãn (VD: XE29C44719, BKS29C-447.19, MOOC28RM45678)
    if not line.truck_plate or not line.trailer_plate:
        split_plate_text = _ATTACHED_PLATE_LABEL_RE.sub(r"\1 ", source_text)
        if split_plate_text != source_text:
            if not line.trailer_plate:
                tr_m = TRAILER_PLATE_REGEX.search(split_plate_text)
                if tr_m:
                    norm_tr = clean_plate(tr_m.group(0))
                    if norm_tr:
                        line.trailer_plate = norm_tr
                        line.extraction_tier = "TIER_2_LOCAL_NLP"
                        line.field_evidences["trailer_plate"] = "local_nlp_attached_label_plate"
                        recovered = True
            if not line.truck_plate:
                pl_m = PLATE_REGEX.search(split_plate_text)
                if pl_m:
                    norm_pl = clean_plate(pl_m.group(0))
                    if norm_pl and norm_pl != line.trailer_plate:
                        line.truck_plate = norm_pl
                        line.raw_truck_plate = line.raw_truck_plate or pl_m.group(0).strip()
                        line.extraction_tier = "TIER_2_LOCAL_NLP"
                        line.field_evidences["truck_plate"] = "local_nlp_attached_label_plate"
                        recovered = True

    # 3. Cứu số container bị dính nhãn (VD: CONTGAOU2701401)
    if not line.container_no and not line.is_container_pending and line.container_status != "DEFERRED":
        split_cont_text = _ATTACHED_CONT_LABEL_RE.sub(r"\1 ", source_text)
        if split_cont_text != source_text:
            cm = CONT_REGEX.search(split_cont_text)
            if cm:
                cleaned_c = clean_container(cm.group(0))
                if cleaned_c:
                    line.container_no = cleaned_c
                    line.extraction_tier = "TIER_2_LOCAL_NLP"
                    line.field_evidences["container_no"] = "local_nlp_attached_label_cont"
                    recovered = True

    # 4. Cứu tên tài xế tự do không nhãn bằng PhoBERT PER vs LOC scoring trên văn bản dư
    if not line.driver_name and include_phobert and phobert._model is not None and phobert._ner_per_anchor is not None:
        residual = _strip_extracted_entities_for_residual(line)
        segments = [
            seg.strip(" -:/,.;*|\t[]()\"'{}—–·•→#")
            for seg in re.split(
                r"[,;/\\|｜\t\n•·—–]+|\s+-\s+|\b(?:alo|s+d+đ*t+|s+đ+t+|d+t+|đ+t+|tel|lh|hl|zalo|phone|call)\b",
                residual,
                flags=re.IGNORECASE,
            )
            if seg.strip()
        ]
        best_cand: tuple[float, str] | None = None
        for seg in segments:
            if not seg or any(ch.isdigit() for ch in seg):
                continue
            # Tách CamelCase chuẩn Unicode cho cụm họ tên viết dính không dấu cách (VD: 'VũTùngAnh' -> 'Vũ Tùng Anh')
            cand_seg = split_camel_case_vn(seg) if (" " not in seg and seg.isalpha()) else seg
            words = cand_seg.split()
            if not (2 <= len(words) <= 4):
                continue
            if not all(w.isalpha() and 1 <= len(w) <= 8 for w in words):
                continue
            if _RESIDUAL_STOP_WORDS_RE.search(cand_seg):
                continue
            if not any(w[0].isupper() for w in words):
                continue
            has_title_case = all(w[0].isupper() for w in words)
            has_vn_surname = normalized(words[0]) in _VI_COMMON_SURNAMES
            if not (has_title_case or has_vn_surname):
                continue
            emb = phobert._encode_phobert_embedding(cand_seg)
            per_sim = float(phobert._torch.dot(emb, phobert._ner_per_anchor).item())
            loc_sim = (
                float(phobert._torch.dot(emb, phobert._ner_loc_anchor).item())
                if phobert._ner_loc_anchor is not None
                else 0.0
            )
            min_per_sim = 0.05 if has_vn_surname else 0.12
            if per_sim >= min_per_sim and per_sim > loc_sim + 0.05:
                if best_cand is None or per_sim > best_cand[0]:
                    best_cand = (per_sim, cand_seg)
        if best_cand is not None:
            cand_name = clean_driver_name(best_cand[1], extra_syllables=tms_driver_syllables) or best_cand[1]
            line.driver_name = cand_name
            line.extraction_tier = "TIER_2_LOCAL_NLP"
            line.field_evidences["driver_name"] = f"local_nlp_phobert_per:{best_cand[0]:.2f}"
            recovered = True

    return recovered


def evaluate_missing_field_signals(line: ExtractedContainerLine) -> tuple[str, list[str]]:
    """Tầng 2 NLP đánh giá trạng thái đủ/thiếu và kiểm tra văn bản dư có tín hiệu cho trường thiếu hay không.

    Returns:
        tuple[str, list[str]]: `(decision, signals)` với `decision` thuộc:
            - `'COMPLETE'`: Đã đủ các trường cốt lõi.
            - `'ESCALATE_TIER3_LLM'`: Còn thiếu trường VÀ văn bản dư có tín hiệu khả nghi -> đẩy sang Tầng 3 LLM.
            - `'STOP_NO_SIGNAL'`: Còn thiếu trường nhưng văn bản dư KHÔNG có tín hiệu -> dừng tại Tầng 2, trả báo thiếu.
    """
    cont_ok = bool(line.container_no) or line.is_container_pending or line.container_status == "DEFERRED"
    has_invalid_phone = "INVALID_DRIVER_PHONE" in (line.warnings or [])
    phone_ok = bool(line.driver_phone) or has_invalid_phone
    missing_fields: list[str] = []
    if not cont_ok:
        missing_fields.append("container_no")
    if not line.truck_plate:
        missing_fields.append("truck_plate")
    if not line.trailer_plate:
        missing_fields.append("trailer_plate")
    if not line.driver_name:
        missing_fields.append("driver_name")
    if not phone_ok:
        missing_fields.append("driver_phone")

    if not missing_fields:
        line.field_evidences["tier2_nlp_decision"] = "COMPLETE"
        line.field_evidences.pop("tier2_missing_signals", None)
        return "COMPLETE", []

    residual = _strip_extracted_entities_for_residual(line)
    norm_res = normalized(residual)
    norm_full = normalized(line.line_text or "")
    signals: list[str] = []

    # 1. Tín hiệu SĐT bị viết dị biệt (VD: O345.032.001, 0345*032*001, sdt đi kèm dãy >= 7 chữ số)
    if "driver_phone" in missing_fields:
        has_explicit_no_phone = bool(
            re.search(r"\b(chua co so|chua co sdt|khong co sdt|sdt bao sau|bo sung sdt sau)\b", norm_full)
        )
        if not has_explicit_no_phone:
            has_fuzzy_phone = bool(
                re.search(r"(?:[0oO]|\+?84)[ \t\u00a0.\-_*]*[35789](?:[ \t\u00a0.\-_*]*\d){7,9}", residual)
                or re.search(
                    r"\b(?:sdt|sddt|dt|tel|lh|hl|alo|phone|zalo|so)\s*[:.\-]?\s*[0oO\d][ \t\u00a0.\-_*0-9oO]{6,13}",
                    norm_res,
                )
            )
            if has_fuzzy_phone:
                signals.append("missing_phone_signal")

    # 2. Tín hiệu tên tài xế chưa bóc được (nhãn gõ lỗi txe/taixe/laixe hoặc cụm 2-4 từ chữ cái tiếng Việt)
    if "driver_name" in missing_fields:
        has_explicit_no_driver = bool(
            re.search(r"\b(chua co tai|chua co lai xe|chua xep tai|chua biet tai|tai bao sau)\b", norm_full)
        )
        if not has_explicit_no_driver:
            has_driver_cue = bool(
                re.search(r"\b(?:txe|taixe|laixe|bactai|nguoi\s+lai|a\.|anh\s+[a-z])\b", norm_res)
            )
            has_name_like_chunk = False
            if not has_driver_cue:
                for seg in re.split(r"[,;/\\|｜\t\n•·—–]+|\s+-\s+", residual):
                    clean_seg = seg.strip(" -:/,.;*|\t[]()\"'{}—–·•→#")
                    if not clean_seg or any(ch.isdigit() for ch in clean_seg):
                        continue
                    words = clean_seg.split()
                    if (
                        2 <= len(words) <= 4
                        and all(w.isalpha() and 1 <= len(w) <= 8 for w in words)
                        and any(w[0].isupper() for w in words)
                        and not _RESIDUAL_STOP_WORDS_RE.search(clean_seg)
                    ):
                        has_name_like_chunk = True
                        break
            if has_driver_cue or has_name_like_chunk:
                signals.append("missing_driver_name_signal")

    # 3. Tín hiệu biển số đầu kéo / rơ-moóc viết dị biệt (VD: 29C_447*19, mooc kèm 4-5 số)
    if "truck_plate" in missing_fields or "trailer_plate" in missing_fields:
        has_fuzzy_plate = bool(
            re.search(r"\d{2}[ \t.\-_*]*[A-Za-zđĐ]{1,2}[ \t.\-_*]*\d{3,5}", residual)
            or re.search(r"\b(?:mooc|rm|bks|dau\s*keo)\s*[:.\-_]?\s*[a-z0-9.\-_*]{4,10}", norm_res)
        )
        if has_fuzzy_plate:
            signals.append("missing_plate_signal")

    # 4. Tín hiệu số container viết dị biệt (VD: GAO U 27014O1)
    if "container_no" in missing_fields:
        has_fuzzy_cont = bool(
            re.search(r"[A-Za-z]{3}[ \t.\-_]?[UJZujz][ \t.\-_]*(?:[0-9oOlI][ \t.\-_]?){6,7}", residual)
            and len(re.findall(r"\d", residual)) >= 5
        )
        if has_fuzzy_cont:
            signals.append("missing_container_signal")

    decision = "ESCALATE_TIER3_LLM" if signals else "STOP_NO_SIGNAL"
    line.field_evidences["tier2_nlp_decision"] = decision
    if signals:
        line.field_evidences["tier2_missing_signals"] = ",".join(signals)
    else:
        line.field_evidences.pop("tier2_missing_signals", None)
    return decision, signals


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
    include_phobert: bool = True,
) -> list[ExtractedContainerLine]:
    """Làm giàu từ toàn bộ danh mục TMS (Driver, Vehicle, Trailer, TransportPlan, Warehouse, Customer) + Local NLP."""
    dates = message_dates(raw_text, reference)
    # Ưu tiên danh mục thuộc đúng nhà xe; nếu chưa gắn carrier_id thì vẫn tận dụng danh mục TMS toàn cục (chỉ nhận khi khớp duy nhất)
    drivers = list(
        db.scalars(
            select(Driver).where(
                *(
                    [Driver.carrier_id == carrier_id, Driver.is_active.is_(True)]
                    if carrier_id
                    else [Driver.is_active.is_(True)]
                )
            )
        ).all()
    )
    vehicles = list(
        db.scalars(
            select(Vehicle).where(
                *(
                    [Vehicle.carrier_id == carrier_id, Vehicle.is_active.is_(True)]
                    if carrier_id
                    else [Vehicle.is_active.is_(True)]
                )
            )
        ).all()
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
    tms_driver_syllables = frozenset(
        tok
        for d in drivers
        for tok in (normalized(d.full_name).split() + (d.full_name or "").lower().split())
        if len(tok) >= 2 and tok.isalpha()
    )
    norm_text = f"{normalized(raw_text)} {normalized(quoted_text)}"
    phobert = PhoBertLocalNlpEngine.get_instance()
    pb_analysis = phobert.analyze(raw_text)

    for line in lines:
        line.candidate_dates = dates
        if not line.plan_date and len(dates) == 1:
            line.plan_date = dates[0]

        line.field_evidences["nlp_engine"] = pb_analysis.backend_mode
        line.field_evidences["phobert_mode"] = pb_analysis.backend_mode
        line.field_evidences["phobert_intent"] = pb_analysis.intent_label
        line.field_evidences["phobert_intent_confidence"] = str(pb_analysis.intent_confidence)

        # Tách lại họ tên tài xế bị gõ dính bằng từ điển âm tiết thực tế từ danh mục Driver TMS
        if line.driver_name and len(line.driver_name.split()) == 1 and tms_driver_syllables:
            re_split = clean_driver_name(line.driver_name, extra_syllables=tms_driver_syllables)
            if re_split and len(re_split.split()) >= 2:
                line.driver_name = re_split
                line.extraction_tier = "TIER_2_LOCAL_NLP"
                line.field_evidences["driver_name"] = "tms_syllable_splitter"

        # Nhận diện chuyến kết hợp RO -> LO và loại lệnh từ Local NLP nếu rule-based chưa bắt được
        if pb_analysis.is_combined_trip:
            line.is_combined_from_return = True
            line.field_evidences["combined_trip"] = "local_nlp_combined_ro_lo"
        if not line.order_type and pb_analysis.order_type_hint:
            line.order_type = pb_analysis.order_type_hint
            line.inferred_order_type = True
            line.field_evidences["order_type"] = "local_nlp_intent_classifier"

        # Cứu hộ có mục tiêu tại Tầng 2 (tách nhãn dính chữ SĐT/biển/cont & PhoBERT PER tự do)
        _recover_missing_fields_local(
            line=line,
            raw_text=raw_text,
            phobert=phobert,
            tms_driver_syllables=tms_driver_syllables,
            include_phobert=include_phobert,
        )

        # Áp dụng các thực thể (LOC, PER) từ Local NLP nếu dòng chưa có và không phải chuỗi cont/booking
        if include_phobert:
            for span in pb_analysis.spans:
                if span.label == "LOC" and not line.warehouse_hint:
                    norm_loc = normalized(span.text)
                    if re.search(
                        r"^(?:cont|container|bk)\b|\b[a-z]{4}\d{7}\b|\bbk\d{4,}\b|\b(?:20|40|45)\s*(?:hc|hq|dc|gp|rf)\b",
                        norm_loc,
                    ):
                        continue
                    line.warehouse_hint = span.text
                    line.field_evidences["warehouse_hint"] = f"local_nlp_loc:{span.confidence:.2f}"
                elif span.label == "PER" and not line.driver_name:
                    line.driver_name = clean_driver_name(span.text, extra_syllables=tms_driver_syllables) or span.text
                    line.field_evidences["driver_name"] = f"local_nlp_per:{span.confidence:.2f}"

        # Đối sánh Tài xế từ danh mục TMS (exact + đa SĐT + RapidFuzz)
        line_phones = set(split_phones(line.driver_phone))
        if drivers and (not line.driver_name or not line.driver_phone or len(line.driver_name.split()) < 2):
            matched_drivers: list[tuple[float, Driver]] = []
            for d in drivers:
                d_norm = normalized(d.normalized_name or d.full_name)
                if not d_norm:
                    continue
                d_phones = set(split_phones(d.phone))
                d_tokens = d_norm.split()
                given_name = d_tokens[-1] if d_tokens else ""
                if (line_phones and d_phones and (line_phones & d_phones)) or d_norm in norm_text:
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
                    best_phones = set(split_phones(best_drv.phone))
                    best_name_norm = normalized(best_drv.normalized_name or best_drv.full_name)
                    line_name_norm = normalized(line.driver_name) if line.driver_name else ""
                    name_conflict = bool(
                        line_name_norm and best_name_norm and line_name_norm not in best_name_norm
                    )
                    phone_conflict = bool(line_phones and best_phones and not (line_phones & best_phones))
                    if not name_conflict and not phone_conflict:
                        if not line.driver_name or line_name_norm in best_name_norm:
                            line.driver_name = best_drv.full_name
                        if not line.driver_phone and best_drv.phone:
                            line.driver_phone = clean_phone(best_drv.phone)
                        line.extraction_tier = "TIER_2_LOCAL_NLP"
                        line.field_evidences["driver"] = f"tms_driver_catalog:{matched_drivers[0][0] / 100.0:.2f}"
                elif len(unique_ids) > 1 and "ambiguous_driver" not in line.unresolved_fields:
                    line.unresolved_fields.append("ambiguous_driver")

        # Đối sánh Biển số xe viết tắt (4-5 số cuối) từ danh mục phương tiện TMS
        if not line.truck_plate and vehicles:
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

        # Đối sánh chéo theo Mã lệnh (RO/LO), Số Booking hoặc Số Container với bảng `transport_plans` đã đồng bộ từ TMS
        matched_plans: list[TransportPlan] = []
        ord_code_m = re.search(r"\b((?:RO|LO)\d{3,6})\b", line.line_text or raw_text or "", re.I)
        if ord_code_m:
            ord_up = ord_code_m.group(1).upper()
            ord_stmt = select(TransportPlan).where(TransportPlan.order_code == ord_up)
            if carrier_id is not None:
                ord_stmt = ord_stmt.where(
                    or_(TransportPlan.carrier_id == carrier_id, TransportPlan.carrier_id.is_(None))
                )
            matched_plans = list(db.scalars(ord_stmt).all())
        if not matched_plans and line.booking_no:
            bk_up = line.booking_no.strip().upper()
            bk_stmt = select(TransportPlan).where(TransportPlan.booking_no == bk_up)
            if carrier_id is not None:
                bk_stmt = bk_stmt.where(
                    or_(TransportPlan.carrier_id == carrier_id, TransportPlan.carrier_id.is_(None))
                )
            matched_plans = list(db.scalars(bk_stmt).all())
        if not matched_plans and line.container_no:
            plan_stmt = select(TransportPlan).where(TransportPlan.container_no == line.container_no.strip().upper())
            if carrier_id is not None:
                plan_stmt = plan_stmt.where(
                    or_(TransportPlan.carrier_id == carrier_id, TransportPlan.carrier_id.is_(None))
                )
            matched_plans = list(db.scalars(plan_stmt).all())
            if line.booking_no:
                bk_up = line.booking_no.strip().upper()
                matched_plans = [
                    p
                    for p in matched_plans
                    if p.booking_no and p.booking_no.strip().upper() == bk_up
                ]
        if matched_plans and line.order_type:
            want_load = line.order_type.upper() in ("LOAD", "DONG", "XUAT")
            matched_plans = [
                p
                for p in matched_plans
                if not p.order_type
                or ((p.order_type.lower() in ("dong", "load", "xuat")) == want_load)
            ]
        if len(matched_plans) == 1:
            mp = matched_plans[0]
            if not line.order_type and mp.order_type:
                line.order_type = "LOAD" if mp.order_type.lower() in ("dong", "load", "xuat") else "RETURN"
            if not line.customer_code_or_id and mp.customer_id:
                line.customer_code_or_id = mp.customer_id
            if not line.customer_hint and mp.customer_name:
                line.customer_hint = mp.customer_name
            if not line.warehouse_code_or_id and mp.warehouse_id:
                line.warehouse_code_or_id = mp.warehouse_id
            if not line.warehouse_hint and (mp.warehouse_name or mp.delivery_address):
                line.warehouse_hint = mp.warehouse_name or mp.delivery_address
            if not line.trailer_plate and mp.planned_trailer_plate:
                line.trailer_plate = clean_plate(mp.planned_trailer_plate) or mp.planned_trailer_plate
            line.field_evidences["transport_plan_tms"] = f"matched_plan:{mp.order_code or mp.id}"
        elif len(matched_plans) > 1:
            # Nhiều slot LO dùng chung mã booking: nếu đều thuộc 1 khách hàng duy nhất thì vẫn làm giàu khách hàng
            unique_cust_ids = {p.customer_id for p in matched_plans if p.customer_id is not None}
            if len(unique_cust_ids) == 1 and not line.customer_code_or_id:
                cid_only = next(iter(unique_cust_ids))
                line.customer_code_or_id = cid_only
                cname_only = next((p.customer_name for p in matched_plans if p.customer_name), None)
                if cname_only and not line.customer_hint:
                    line.customer_hint = cname_only
                line.field_evidences["transport_plan_tms"] = f"matched_booking_customer:{cid_only}"

        # Đối sánh Từ điển danh mục (Khách hàng, Kho, Alias, Kế hoạch) bằng RapidFuzz
        _match_catalog_gazetteer(db, line, carrier_id, raw_text, dates)

        # Trạng thái chờ cont / chờ chì hợp lệ cho lệnh đóng
        if re.search(
            r"\b(chua co cont|chua co so cont|cont chua co|so cont chua co|cont bao sau|lay rong|doi cap cont|chua cap cont|chua lay cont)\b",
            norm_text,
        ):
            line.container_status = "DEFERRED"
        if re.search(
            r"\b(chua co chi|chua co seal|chi chua co|seal chua co|so chi chua co|so seal chua co|chi bao sau|seal bao sau|chua cap chi|chua cap seal|chua bam chi|chua kep chi|no chi|no seal|chi bo sung sau|bo sung chi sau)\b",
            norm_text,
        ):
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

        # Tầng 2 NLP đánh giá tín hiệu dư cho các trường còn thiếu -> quyết định COMPLETE / STOP_NO_SIGNAL / ESCALATE_TIER3_LLM
        t2_decision, _t2_signals = evaluate_missing_field_signals(line)

        if any(
            k in line.field_evidences
            for k in (
                "warehouse",
                "customer",
                "booking_no",
                "combined_trip",
                "order_type",
                "driver",
                "driver_name",
                "driver_phone",
                "truck_plate",
                "trailer_plate",
                "container_no",
                "transport_plan_tms",
            )
        ):
            line.extraction_tier = "TIER_2_LOCAL_NLP"

        # Tính lại độ tin cậy sau Tier 2:
        # - Chỉ coi là đủ lõi (0.88) khi đủ cả tên lẫn SĐT (COMPLETE)
        # - Khi STOP_NO_SIGNAL (thiếu trường nhưng Tầng 2 xác nhận KHÔNG còn tín hiệu dư để LLM đọc)
        #   và đã có thực thể chính + không còn unresolved_fields -> nâng >= 0.80 để dừng tại Tầng 2
        # - Khi ESCALATE_TIER3_LLM -> giữ nguyên để kích hoạt Tầng 3 LLM cứu trường thiếu
        has_core_after_t2 = bool(
            t2_decision == "COMPLETE"
            and line.truck_plate
            and (line.container_no or line.container_status == "DEFERRED" or line.is_container_pending)
            and line.driver_name
            and line.driver_phone
        )
        if has_core_after_t2 and not line.unresolved_fields:
            line.confidence = max(line.confidence, 0.88)
        elif (
            t2_decision == "STOP_NO_SIGNAL"
            and (
                line.truck_plate
                or line.trailer_plate
                or line.container_no
                or line.driver_phone
                or line.seal_no
                or line.booking_no
            )
            and not line.unresolved_fields
        ):
            line.confidence = max(line.confidence, 0.80)
        elif (
            t2_decision != "ESCALATE_TIER3_LLM"
            and (line.truck_plate or line.container_no)
            and any(k in line.field_evidences for k in ("driver", "truck_plate", "warehouse", "customer", "transport_plan_tms"))
            and not line.unresolved_fields
        ):
            line.confidence = max(line.confidence, 0.80)

    return lines
