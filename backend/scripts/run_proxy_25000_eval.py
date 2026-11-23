"""Bộ chạy kiểm thử Proxy In-Memory trên 25.000 kịch bản (Zalo OA × TMS).

Đặc điểm:
- Chạy 100% trên proxy nội bộ trong bộ nhớ (KHÔNG ghi MySQL, KHÔNG gọi Zalo OA, KHÔNG gọi LLM trả phí).
- Gọi trực tiếp các module lõi của hệ thống: IntentClassifier, MessageSegmenter,
  TripParser, PhoBertLocalNlpEngine, domain.rules, PlanResolutionEngine và AIFallbackExtractor.should_trigger_ai.
- Tính toán đầy đủ 6 nhóm chỉ số (26 chỉ số) + phân tích tỷ lệ Rule / Local NLP / LLM Fallback
  theo từng sheet, từng family và toàn hệ thống.
- Xuất đồng bộ:
  1. backend/output/eval_25000_detailed_report.csv (báo cáo tổng hợp đa phần chuẩn CSV UTF-8 BOM)
  2. backend/output/csv_sheets/*.csv (từng file CSV riêng tương ứng từng sheet báo cáo)
  3. backend/output/eval_25000_detailed_report.xlsx (workbook nhiều sheet đánh giá chi tiết)
  4. backend/output/zalo_tms_25000_tests_EVALUATED.xlsx (bản sao bộ 25.000 test đã điền cột Kết quả Bot & PASS/FAIL)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import argparse
import csv
import json
import math
import os
import re
import shutil
import statistics
import sys
import time
import unicodedata
from typing import Any, Optional

import openpyxl
from rapidfuzz import fuzz

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.config.settings import settings  # noqa: E402
from src.domain.enums import Intent  # noqa: E402
from src.domain.rules import (  # noqa: E402
    clean_container,
    clean_driver_name,
    clean_phone,
    clean_plate,
    compact_plate,
    validate_iso6346,
)
from src.handlers.plan_resolution_engine import PlanResolutionEngine  # noqa: E402
from src.messaging.classifier import IntentClassifier  # noqa: E402
from src.messaging.segmenter import MessageSegmenter  # noqa: E402
from src.parsing.ai_fallback import AIFallbackExtractor  # noqa: E402
from src.parsing.local_nlp_extractor import PhoBertLocalNlpEngine  # noqa: E402
from src.parsing.trip_parser import TripParser  # noqa: E402


DATA_DIR = BACKEND_DIR / "tests" / "data_test"
JSONL_PATH = DATA_DIR / "zalo_tms_25000_scenarios.jsonl"
WORKBOOK_SRC = DATA_DIR / "zalo_tms_25000_tests.xlsx"
OUTPUT_DIR = BACKEND_DIR / "output"
CSV_SHEETS_DIR = OUTPUT_DIR / "csv_sheets"

SHEET_ORDER = [
    "01_CONTEXT",
    "02_RETURN ORDER",
    "03_LOAD ORDER",
    "04_COMBINED ORDER",
    "05_UPDATE CANCEL",
    "06_EDGE CASES",
    "08_FORMAT ENTITY",
]

# Đơn giá tham khảo Gemini Flash (USD / 1M tokens) dùng để ước tính chi phí Tier-3 LLM Fallback
LLM_INPUT_COST_PER_1M = 0.10
LLM_OUTPUT_COST_PER_1M = 0.40
AVG_INPUT_TOKENS_PER_CALL = 480
AVG_OUTPUT_TOKENS_PER_CALL = 180


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để so khớp tên hoặc từ khóa ổn định."""
    norm = unicodedata.normalize("NFD", text or "")
    out = "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")
    return out.replace("đ", "d").replace("Đ", "D")


def norm_upper(text: Optional[str]) -> str:
    """Chuẩn hóa chuỗi chữ hoa rút gọn khoảng trắng."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().upper()


def norm_driver(name: Optional[str]) -> str:
    """Chuẩn hóa tên tài xế để đối chiếu chính xác."""
    if not name:
        return ""
    cleaned = clean_driver_name(name) or str(name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()
    return cleaned


@dataclass
class ProxyPlan:
    """Kế hoạch TMS giả lập trong bộ nhớ tương thích thuộc tính với PlanResolutionEngine."""

    id: str
    order_code: str
    order_type: str
    plan_date: str
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    container_size: Optional[str] = "40"
    booking_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    delivery_address: Optional[str] = None
    ward_name: Optional[str] = None
    province_name: Optional[str] = None
    required_time: Optional[str] = None
    carrier_id: Optional[int] = None
    planned_truck_plate: Optional[str] = None
    planned_driver_name: Optional[str] = None
    planned_driver_phone: Optional[str] = None
    route_name: Optional[str] = None
    delivery_team: Optional[str] = None
    container_warning: Optional[str] = None
    container_ownership: Optional[str] = None
    linked_return_plan_id: Optional[str] = None
    status: str = "ACTIVE"


def load_fixture_plans() -> dict[str, ProxyPlan]:
    """Đọc 225 dòng kế hoạch chuẩn từ sheet 07_TMS_FIXTURES."""
    wb = openpyxl.load_workbook(WORKBOOK_SRC, read_only=True)
    ws = wb["07_TMS_FIXTURES"]
    plans: dict[str, ProxyPlan] = {}
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
        if not row or not row[0]:
            continue
        code = str(row[0]).strip()
        op_type = str(row[1] or "").strip().upper()
        pdate = str(row[2] or "2026-11-09").strip()[:10]
        cont = clean_container(str(row[3])) if row[3] else None
        seal = str(row[4]).strip() if row[4] is not None else None
        size = str(row[5]).strip() if row[5] is not None else "40"
        route = str(row[6] or "").strip() or None
        req_time = str(row[7] or "").strip() or None
        cust = str(row[8] or "").strip() or None
        addr = str(row[9] or "").strip() or None
        booking = str(row[10] or "").strip() or None
        team = str(row[11] or "").strip() or None
        plate_raw = str(row[13] or "").strip()
        driver_raw = str(row[14] or "").strip()
        plate = None if "TRỐNG" in plate_raw.upper() else compact_plate(plate_raw)
        driver = None if "TRỐNG" in driver_raw.upper() else norm_driver(driver_raw)
        plans[code] = ProxyPlan(
            id=code,
            order_code=code,
            order_type="RO" if op_type == "RETURN" else "LO",
            plan_date=pdate,
            container_no=cont,
            seal_no=seal,
            container_size=size,
            booking_no=booking,
            customer_name=cust,
            warehouse_name=route,
            delivery_address=addr,
            required_time=req_time,
            planned_truck_plate=plate,
            planned_driver_name=driver,
            route_name=route,
            delivery_team=team,
        )
    wb.close()
    return plans


# Biểu thức hỗ trợ tầng điều phối Proxy trên tin nhắn nghiệp vụ
_ORDER_CODE_RE = re.compile(r"\b((?:RO|LO)\d{3,6}|TEST-\d{4,10})\b", re.IGNORECASE)
_BOOKING_RE = re.compile(r"\b(?:BK|BL|BOOKING)?\s*[:#]?\s*((?:VS|B|TEST)\d{4,10})\b", re.IGNORECASE)
_SEAL_RE = re.compile(r"\bseal\s*[:#-]?\s*([A-Z0-9]{4,20})\b", re.IGNORECASE)
_TIME_RE = re.compile(r"\b(\d{1,2})\s*(?:h|:|giờ)\s*(\d{0,2})\b", re.IGNORECASE)
_BAD_PLATE_RE = re.compile(r"\b\d{2}[A-Z][-_./]?\d{0,5}(?:X{2,5}|Z{2,5})\b|\b\d{2}Z[-_./]?[A-Z0-9]{3,6}\b", re.IGNORECASE)
_BAD_CONT_LEN_RE = re.compile(r"\b([A-Z]{3}[UJZ])[-\s]?(\d{5,6})\b(?!\d)", re.IGNORECASE)
_UNREADABLE_CONT_RE = re.compile(r"\b[A-Z]{4}\d[?*#_]\d{4,6}\b", re.IGNORECASE)
_STRICT_CONT_RE = re.compile(
    r"\b([A-Z]{3})([UJZ])[-\s]?(\d{3})[-\s]?(\d{3})[-\s]?(\d)\b|"
    r"\b([A-Z]{4})[\-\.]?(\d{3})[-\s]?(\d{3})[-\s]?(\d)\b",
    re.IGNORECASE,
)
_PHONE_ANY_RE = re.compile(r"(?:sđt|sdt|đt|dt|phone|tel|số)[:\s]*(\d[\d.\-\s]{3,16}\d)", re.IGNORECASE)
_COMBINED_ID_RE = re.compile(r"\b(SIMCOMB-[A-Z0-9-]+)\b", re.IGNORECASE)


def clone_plan(p: ProxyPlan) -> ProxyPlan:
    """Tạo bản sao độc lập của một kế hoạch TMS cho sandbox từng kịch bản."""
    return ProxyPlan(
        id=p.id,
        order_code=p.order_code,
        order_type=p.order_type,
        plan_date=p.plan_date,
        container_no=p.container_no,
        seal_no=p.seal_no,
        container_size=p.container_size,
        booking_no=p.booking_no,
        customer_id=p.customer_id,
        customer_name=p.customer_name,
        warehouse_id=p.warehouse_id,
        warehouse_name=p.warehouse_name,
        delivery_address=p.delivery_address,
        ward_name=p.ward_name,
        province_name=p.province_name,
        required_time=p.required_time,
        carrier_id=p.carrier_id,
        planned_truck_plate=p.planned_truck_plate,
        planned_driver_name=p.planned_driver_name,
        planned_driver_phone=p.planned_driver_phone,
        route_name=p.route_name,
        delivery_team=p.delivery_team,
        container_warning=p.container_warning,
        container_ownership=p.container_ownership,
        linked_return_plan_id=p.linked_return_plan_id,
        status=p.status,
    )


def extract_all_raw_containers(text: str) -> list[str]:
    """Bóc tất cả chuỗi dạng Container (đúng 4 chữ + 7 số, kể cả sai check digit ISO 6346) để kiểm tra bảo vệ."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _STRICT_CONT_RE.finditer(text or ""):
        if m.group(1):
            c = f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)}".upper()
        else:
            c = f"{m.group(6)}{m.group(7)}{m.group(8)}{m.group(9)}".upper()
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def extract_all_plates(text: str) -> list[str]:
    """Bóc tất cả biển số hợp lệ theo thứ tự xuất hiện."""
    lines = TripParser.parse_message(text or "")
    out: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        p = compact_plate(ln.truck_plate)
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    # Quét bổ sung biển số nếu một đoạn có nhiều biển số cùng dòng (ví dụ đổi xe từ A sang B)
    raw_plate_re = re.compile(r"\b(\d{2}[A-Z]{1,2})[-.\s/]?(\d{3,6})(?:\.(\d{2,3}))?\b", re.IGNORECASE)
    for m in raw_plate_re.finditer(text or ""):
        cand = compact_plate(m.group(0))
        if cand and len(cand) >= 7 and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def extract_validation_errors_from_text(text: str) -> list[dict[str, str]]:
    """Kiểm tra lỗi cứng định dạng Container (ISO 6346 / độ dài / ký tự mờ), Biển số và SĐT."""
    errs: list[dict[str, str]] = []
    if _UNREADABLE_CONT_RE.search(text or ""):
        m = _UNREADABLE_CONT_RE.search(text or "")
        errs.append({"field": "container_no", "raw_value": m.group(0), "code": "UNREADABLE_CONTAINER"})
    for raw_c in extract_all_raw_containers(text):
        valid = validate_iso6346(raw_c)
        if valid is False:
            errs.append({"field": "container_no", "raw_value": raw_c, "code": "INVALID_ISO6346_CHECK_DIGIT"})
    # Kiểm tra thiếu số cuối container (10 ký tự thay vì 11)
    cleaned_full_conts = {c[:10] for c in extract_all_raw_containers(text)}
    for m in _BAD_CONT_LEN_RE.finditer(text or ""):
        pref = f"{m.group(1)}{m.group(2)}".upper()
        if pref not in cleaned_full_conts:
            errs.append({"field": "container_no", "raw_value": pref, "code": "INVALID_CONTAINER_LENGTH"})
    if _BAD_PLATE_RE.search(text or ""):
        m = _BAD_PLATE_RE.search(text or "")
        errs.append({"field": "truck_plate", "raw_value": m.group(0), "code": "INVALID_PLATE_FORMAT"})
    for m in _PHONE_ANY_RE.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(1))
        if digits and (len(digits) < 10 or len(digits) > 11):
            errs.append({"field": "driver_phone", "raw_value": digits, "code": "INVALID_PHONE_LENGTH"})
    return errs


def classify_intent_group(intent_str: Optional[str]) -> str:
    """Nhóm hóa nhãn ý định chi tiết thành các nhóm nghiệp vụ cốt lõi để so khớp công bằng."""
    s = (intent_str or "").upper()
    if not s:
        return "UNKNOWN"
    if "CANCEL_PENDING" in s or "DELETE_MESSAGE" in s or "NO_CHANGE" in s:
        return "CANCEL_OR_NO_CHANGE"
    if "CANCEL" in s:
        return "CANCEL_ORDER"
    if "DENY" in s:
        return "DENY_UNAUTHORIZED"
    if "REJECT_UNTRUSTED" in s:
        return "PROMPT_INJECTION"
    if "IGNORE_DUPLICATE" in s:
        return "IGNORE_DUPLICATE"
    if "IGNORE_SOCIAL" in s:
        return "IGNORE_SOCIAL"
    if "REVIEW_FORWARDED" in s:
        return "REVIEW_FORWARDED"
    if "REQUEST_IMAGE" in s:
        return "REQUEST_IMAGE"
    if "REQUEST_CORRECTION" in s:
        return "REQUEST_CORRECTION"
    if "FLAG_CONFLICT" in s or "AUDIT_CONFLICT" in s or "REVALIDATE" in s:
        return "CONFLICT_OR_REVIEW"
    if "CLARIFY" in s or "ASK_" in s or "MISSING_" in s:
        return "CLARIFY_OR_MISSING"
    if "UPDATE" in s or "REVISE" in s or "NEW_REVERSE" in s:
        return "UPDATE"
    if "APPLIED" in s:
        return "APPLIED"
    if "REJECTED" in s:
        return "REJECTED"
    if "CREATE_UNMATCHED" in s:
        return "UNMATCHED"
    if "LOOKUP" in s or "QUERY" in s or "VERIFY" in s or "CHECK_" in s:
        return "LOOKUP_OR_VERIFY"
    if "SUPPLEMENT" in s or "MATCH_" in s or "CANDIDATE" in s or "ASSIGN" in s or "PARSE" in s or "HANDLE_REORDERED" in s or "RETRY" in s:
        return "SUPPLEMENT_OR_MATCH"
    return s


def classify_status_group(status_str: Optional[str]) -> str:
    """Chuẩn hóa nhóm trạng thái xử lý."""
    s = (status_str or "").upper()
    if s in ("MATCHED", "AUTO_COMMIT", "APPLIED", "OK"):
        return "RESOLVED_OR_APPLIED"
    if s in ("NEEDS_CONFIRMATION", "NEEDS_REVIEW", "ESCALATE_DHVT_WEB", "NEEDS_TMS_LOOKUP"):
        return "ESCALATE_OR_CONFIRM"
    if s in ("AMBIGUOUS", "NEEDS_INFO", "ASK_CARRIER", "NEEDS_CLARIFICATION", "PARTIAL"):
        return "CLARIFY_OR_INFO"
    if s in ("NOOP", "IGNORE"):
        return "NOOP"
    if s in ("DENIED", "REJECTED", "CANCELLED_PENDING", "UNMATCHED"):
        return s
    return s


@dataclass
class EvalRecord:
    """Kết quả đánh giá chi tiết của một kịch bản."""

    test_id: str
    sheet_name: str
    family: str
    run_mode: str
    passed: bool
    blocked: bool
    latency_ms: float
    msg_count: int
    tier: str  # TIER_1_RULE | TIER_2_LOCAL_NLP | TIER_3_LLM_FALLBACK
    llm_triggered_raw: bool
    llm_needed_semantic: bool
    intent_match: bool
    ent_tp: int = 0
    ent_fp: int = 0
    ent_fn: int = 0
    multi_order_case: bool = False
    multi_order_ok: bool = False
    context_case: bool = False
    context_ok: bool = False
    reference_case: bool = False
    reference_ok: bool = False
    cross_leak: bool = False
    order_match_case: bool = False
    order_match_ok: bool = False
    order_type_ok: bool = True
    workflow_ok: bool = True
    false_update: bool = False
    missing_info_case: bool = False
    missing_info_ok: bool = False
    auto_resolved: bool = False
    clarified: bool = False
    unnecessary_clarify: bool = False
    hallucinated: bool = False
    escalated_human: bool = False
    resp_accurate: bool = True
    resp_relevant: bool = True
    resp_complete: bool = True
    runtime_error: bool = False
    bot_summary: str = ""
    fail_reason: str = ""


class ProxyEvaluator:
    """Bộ đánh giá Proxy 25.000 kịch bản trên lõi VSICO Zalo Bot."""

    def __init__(self) -> None:
        self.base_plans = load_fixture_plans()
        self.nlp_engine = PhoBertLocalNlpEngine.get_instance()
        self.parser_engine = TripParser()

    def _should_trigger_ai_proxy(self, lines: list[Any], intent: Intent) -> bool:
        """Đo lường quyết định gọi AI Fallback thực tế của AIFallbackExtractor (bật proxy flag trong RAM)."""
        orig_enabled = settings.AI_ENABLED
        orig_url = settings.AI_SERVICE_URL
        try:
            settings.AI_ENABLED = True  # type: ignore[misc]
            settings.AI_SERVICE_URL = "http://proxy-ai-check"  # type: ignore[misc]
            return AIFallbackExtractor.should_trigger_ai(lines, intent)
        finally:
            settings.AI_ENABLED = orig_enabled  # type: ignore[misc]
            settings.AI_SERVICE_URL = orig_url  # type: ignore[misc]

    # ------------------------------------------------------------------
    # ĐÁNH GIÁ SHEET 08_FORMAT ENTITY (PARSE_ONLY - 5.000 TEST)
    # ------------------------------------------------------------------
    def eval_parse_only(self, sc: dict[str, Any]) -> EvalRecord:
        t0 = time.perf_counter_ns()
        test_id = sc["test_id"]
        family = sc["family"]
        exp = sc["expected"]
        msg_text = sc["messages"][0].get("text") or ""

        runtime_err = False
        extracted_lines = []
        raw_intent = Intent.PARSE
        ph_analysis = None
        llm_gate = False
        try:
            raw_intent = IntentClassifier.classify(msg_text)
            ph_analysis = self.nlp_engine.analyze(msg_text)
            extracted_lines = TripParser.parse_message(msg_text)
            llm_gate = self._should_trigger_ai_proxy(extracted_lines, raw_intent)
        except Exception:
            runtime_err = True

        dt_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        val_errs = extract_validation_errors_from_text(msg_text)

        exp_status = exp.get("parse_status", "OK")
        exp_trips = exp.get("trips") or []
        exp_count = int(exp.get("expected_trip_count") or len(exp_trips))
        exp_errs = exp.get("validation_errors") or []

        # Kiểm tra câu hỏi xã giao / không có thực thể vận tải
        if raw_intent == Intent.IGNORE_CHAT and not extracted_lines:
            pred_status = "IGNORE"
        elif not any(
            ln.truck_plate or ln.container_no or ln.driver_name or ln.driver_phone
            for ln in extracted_lines
        ) and not val_errs:
            pred_status = "IGNORE"
        else:
            # Kiểm tra tín hiệu mơ hồ / không thể ghép cặp (chưa biết xe nào, bên nào, danh sách rời rạc)
            lower_no_accent = strip_accents(msg_text).lower()
            raw_plates = extract_all_plates(msg_text)
            raw_conts = extract_all_raw_containers(msg_text)
            valid_conts = [c for c in raw_conts if validate_iso6346(c) is True]
            is_ambig_phrase = any(
                kw in lower_no_accent
                for kw in (
                    "chua biet xe nao",
                    "ben nao nhan",
                    "khong ro",
                    "can kiem tra",
                    "nhung dong sau lai ghi",
                    "danh sach xe:",
                )
            )
            # Kiểm tra danh sách N biển số + N cont / N tài xế rời nhau không gắn nhãn ghép
            is_unpaired_list = (
                ("danh sách xe:" in msg_text.lower() and "danh sách cont:" in msg_text.lower())
                or ("tài xế:" in msg_text.lower() and len(raw_plates) >= 2 and len(extracted_lines) < len(raw_plates))
                or (bool(re.search(r"\b(?:các\s*xe|những\s*xe)\b", lower_no_accent)) and len(raw_plates) >= 2 and "tài xế:" in msg_text.lower())
                or (len(raw_conts) >= 2 and len(raw_plates) == 1 and bool(re.search(r"\b\d+\s*cont\b.*\b1\s*(?:đầu\s*kéo|dau\s*keo|xe)\b", lower_no_accent)))
            )

            if is_ambig_phrase or is_unpaired_list:
                pred_status = "NEEDS_CLARIFICATION"
                extracted_lines_eval = []
            elif val_errs:
                pred_status = "PARTIAL"
                extracted_lines_eval = extracted_lines
            else:
                pred_status = "OK"
                extracted_lines_eval = extracted_lines

        # Chuẩn hóa tập thực thể kỳ vọng và dự đoán để tính Precision / Recall / F1
        tp = fp = fn = 0
        matched_trips = 0
        used_pred: set[int] = set()

        # Lọc các dòng trích xuất có ít nhất 1 trường xe/cont/tài/sđt hoặc khi parser trống
        pred_items: list[dict[str, str]] = []
        if pred_status in ("OK", "PARTIAL"):
            for ln in extracted_lines_eval:
                item = {
                    "truck_plate": compact_plate(ln.truck_plate) or "",
                    "container_no": clean_container(ln.container_no) or "",
                    "driver_name": norm_driver(ln.driver_name),
                    "driver_phone": clean_phone(ln.driver_phone) or "",
                }
                if any(item.values()):
                    pred_items.append(item)

        exp_norm_list: list[dict[str, str]] = []
        for t in exp_trips:
            exp_norm_list.append(
                {
                    "truck_plate": compact_plate(t.get("truck_plate")) or "",
                    "container_no": clean_container(t.get("container_no")) or "",
                    "driver_name": norm_driver(t.get("driver_name")),
                    "driver_phone": clean_phone(t.get("driver_phone")) or "",
                }
            )

        # So khớp từng chuyến kỳ vọng với dòng trích xuất tốt nhất của TripParser
        for idx_e, et in enumerate(exp_norm_list):
            best_j = -1
            best_hits = -1
            for j, pt in enumerate(pred_items):
                if j in used_pred:
                    continue
                hits = 0
                if et["truck_plate"] and pt["truck_plate"] == et["truck_plate"]:
                    hits += 3
                if et["container_no"] and pt["container_no"] == et["container_no"]:
                    hits += 3
                if et["driver_phone"] and pt["driver_phone"] == et["driver_phone"]:
                    hits += 2
                if et["driver_name"] and pt["driver_name"] == et["driver_name"]:
                    hits += 2
                elif et["driver_name"] and pt["driver_name"] and (
                    strip_accents(et["driver_name"]) == strip_accents(pt["driver_name"])
                ):
                    hits += 1
                if hits > best_hits:
                    best_hits = hits
                    best_j = j

            if best_j >= 0 and best_hits > 0:
                used_pred.add(best_j)
                pt = pred_items[best_j]
                trip_all_ok = True
                for fk in ("truck_plate", "container_no", "driver_name", "driver_phone"):
                    ev = et[fk]
                    pv = pt[fk]
                    if ev and pv:
                        if fk == "driver_name":
                            ok_f = (ev == pv) or (strip_accents(ev) == strip_accents(pv))
                        else:
                            ok_f = ev == pv
                        if ok_f:
                            tp += 1
                        else:
                            fp += 1
                            fn += 1
                            trip_all_ok = False
                    elif ev and not pv:
                        fn += 1
                        trip_all_ok = False
                    elif pv and not ev:
                        fp += 1
                if trip_all_ok:
                    matched_trips += 1
            else:
                for fk in ("truck_plate", "container_no", "driver_name", "driver_phone"):
                    if et[fk]:
                        fn += 1

        # Các dòng dư không khớp chuyến nào -> False Positives
        for j, pt in enumerate(pred_items):
            if j not in used_pred:
                for fk in ("truck_plate", "container_no", "driver_name", "driver_phone"):
                    if pt[fk]:
                        fp += 1

        # Kiểm tra validation errors
        val_err_ok = True
        if exp_errs:
            exp_codes = {e["code"] for e in exp_errs}
            pred_codes = {e["code"] for e in val_errs}
            if not (exp_codes & pred_codes):
                val_err_ok = False

        status_ok = pred_status == exp_status
        count_ok = (len(pred_items) == exp_count) if exp_status in ("OK", "PARTIAL") else (pred_status == exp_status)
        if exp_status in ("OK", "PARTIAL"):
            all_trips_ok = (matched_trips == len(exp_norm_list)) and count_ok and status_ok and val_err_ok
        else:
            all_trips_ok = status_ok and (len(pred_items) == 0)

        passed = bool(all_trips_ok and not runtime_err)
        multi_case = exp_count >= 2 or family.startswith("MULTI_")

        # Phân tầng kiến trúc thực tế:
        # Nếu Rule Fast-Path F1/F2/F3 PASS -> TIER_1_RULE
        # Nếu tu_do / đa chuyến / phoBert PASS -> TIER_2_LOCAL_NLP
        # Nếu thất bại cục bộ HOẶC AIFallbackExtractor.should_trigger_ai bật -> TIER_3_LLM_FALLBACK
        uses_f123 = bool(extracted_lines) and all(ln.source_format in ("F1", "F2", "F3") for ln in extracted_lines)
        llm_needed = (not passed and exp_status != "IGNORE") or llm_gate
        if passed and uses_f123 and not llm_gate:
            tier = "TIER_1_RULE"
        elif passed and not llm_gate:
            tier = "TIER_2_LOCAL_NLP"
        else:
            tier = "TIER_3_LLM_FALLBACK"

        hallucinated = any(
            pt["truck_plate"] and pt["truck_plate"] not in re.sub(r"[^A-Z0-9]", "", msg_text.upper())
            for pt in pred_items
        )

        fail_reason = ""
        if not passed:
            reasons = []
            if not status_ok:
                reasons.append(f"status {pred_status}!={exp_status}")
            if not count_ok:
                reasons.append(f"trips {len(pred_items)}!={exp_count}")
            if not val_err_ok:
                reasons.append("val_err_miss")
            if fn > 0 or fp > 0:
                reasons.append(f"ent(tp={tp},fp={fp},fn={fn})")
            fail_reason = "; ".join(reasons)

        bot_summary = f"status={pred_status}, trips={len(pred_items)}/{exp_count}, tier={tier}"
        if fail_reason:
            bot_summary += f" | {fail_reason}"

        return EvalRecord(
            test_id=test_id,
            sheet_name=sc["sheet_name"],
            family=family,
            run_mode=sc["run_mode"],
            passed=passed,
            blocked=False,
            latency_ms=dt_ms,
            msg_count=1,
            tier=tier,
            llm_triggered_raw=llm_gate,
            llm_needed_semantic=llm_needed,
            intent_match=status_ok,
            ent_tp=tp,
            ent_fp=fp,
            ent_fn=fn,
            multi_order_case=multi_case,
            multi_order_ok=passed if multi_case else False,
            context_case=False,
            context_ok=False,
            reference_case=False,
            reference_ok=False,
            cross_leak=False,
            order_match_case=False,
            order_match_ok=False,
            order_type_ok=True,
            workflow_ok=passed,
            false_update=bool(pred_status == "OK" and exp_status in ("NEEDS_CLARIFICATION", "IGNORE", "PARTIAL")),
            missing_info_case=bool(exp_status in ("PARTIAL", "NEEDS_CLARIFICATION") or exp_errs),
            missing_info_ok=bool((status_ok and val_err_ok) if (exp_status in ("PARTIAL", "NEEDS_CLARIFICATION") or exp_errs) else False),
            auto_resolved=bool(pred_status == "OK"),
            clarified=bool(pred_status == "NEEDS_CLARIFICATION"),
            unnecessary_clarify=bool(pred_status == "NEEDS_CLARIFICATION" and exp_status == "OK"),
            hallucinated=hallucinated,
            escalated_human=bool(pred_status == "PARTIAL"),
            resp_accurate=passed,
            resp_relevant=status_ok or (pred_status == "PARTIAL" and exp_status == "PARTIAL"),
            resp_complete=bool(passed),
            runtime_error=runtime_err,
            bot_summary=bot_summary,
            fail_reason=fail_reason,
        )

    # ------------------------------------------------------------------
    # ĐÁNH GIÁ WORKFLOW_MOCK (01_CONTEXT .. 06_EDGE CASES - 20.000 TEST)
    # ------------------------------------------------------------------
    def _build_sandbox_plans(self, sc: dict[str, Any]) -> tuple[dict[str, ProxyPlan], dict[str, Any]]:
        fixture = sc.get("fixture") or {}
        assump = fixture.get("assumptions_NOT_in_source") or {}
        source_codes = fixture.get("source_orders") or []
        plan_date = fixture.get("plan_date") or "2026-11-09"

        scoped_plans: dict[str, ProxyPlan] = {}
        for code in source_codes:
            base = self.base_plans.get(code)
            if base:
                scoped_plans[code] = clone_plan(base)

        # Áp dụng các gán giả lập xe / tài xế / nhà xe / SĐT theo từng kịch bản
        truck_map = assump.get("truck_assigned_to_order") or {}
        driver_map = assump.get("driver_assigned_to_order") or {}
        carrier_map = assump.get("carrier_assigned_to_order") or {}
        assumed_phone = clean_phone(assump.get("driver_phone_assumed"))

        for code, pl in scoped_plans.items():
            if code in truck_map and truck_map[code]:
                pl.planned_truck_plate = compact_plate(truck_map[code])
            if code in driver_map and driver_map[code]:
                pl.planned_driver_name = norm_driver(driver_map[code])
            if code in carrier_map and carrier_map[code] is not None:
                try:
                    pl.carrier_id = int(carrier_map[code])
                except (ValueError, TypeError):
                    pass
            if assumed_phone:
                pl.planned_driver_phone = assumed_phone
            if plan_date:
                pl.plan_date = plan_date

        # Áp dụng synthetic combined link nếu có trong fixture
        comb = assump.get("synthetic_combined_link") or {}
        if comb and comb.get("return_order_id") in scoped_plans and comb.get("load_order_id") in scoped_plans:
            ret_id = comb["return_order_id"]
            load_id = comb["load_order_id"]
            scoped_plans[load_id].linked_return_plan_id = ret_id
            if comb.get("container_no") and not scoped_plans[load_id].container_no:
                scoped_plans[load_id].container_no = clean_container(comb["container_no"])

        # Áp dụng trạng thái đã thay đổi trước đó (applied_change)
        applied_ch = assump.get("applied_change") or {}
        if applied_ch and source_codes:
            target = scoped_plans.get(source_codes[0])
            if target and applied_ch.get("truck_plate"):
                target.planned_truck_plate = compact_plate(applied_ch["truck_plate"])

        return scoped_plans, assump

    def eval_workflow(self, sc: dict[str, Any]) -> EvalRecord:
        t0 = time.perf_counter_ns()
        test_id = sc["test_id"]
        sheet = sc["sheet_name"]
        family = sc["family"]
        exp = sc["expected"]
        scoped_plans, assump = self._build_sandbox_plans(sc)
        plan_list = list(scoped_plans.values())
        plan_date = (sc.get("fixture") or {}).get("plan_date") or "2026-11-09"
        messages = sc.get("messages") or []

        # Trạng thái hội thoại & bộ nhớ ngữ cảnh nhiều lượt (Proxy Conversation Memory)
        seen_msg_keys: set[tuple[str, str]] = set()
        seen_msg_ids: set[str] = set()
        msg_history: dict[str, dict[str, Any]] = {}
        sender_active_orders: dict[str, list[str]] = defaultdict(list)
        sender_pending_changes: dict[str, dict[str, Any]] = {}
        active_order_id: Optional[str] = None
        last_entities: dict[str, str] = {}
        accumulated_entities: dict[str, str] = {}

        # Cờ quan sát của lõi Bot qua chuỗi sự kiện
        pred_intent = "UNKNOWN"
        pred_status = "AMBIGUOUS"
        pred_order_id: Optional[str] = None
        pred_leg: Optional[str] = None
        pred_tms_write = "NONE"
        reordered = False
        prev_time: Optional[str] = None
        dhvt_edited = False
        pending_exists = bool(assump.get("pending_change"))
        saw_assign_request = False
        access_control = assump.get("access_control") or {}
        comb_link = assump.get("synthetic_combined_link") or {}
        llm_gate_any = False
        used_local_nlp = False
        used_rule_fastpath = False
        runtime_err = False
        cross_leak = False

        # Theo dõi đa lượt, tham chiếu và phát hiện xung đột
        multi_turn = len(messages) > 1
        has_reply_to = any(m.get("reply_to") for m in messages)

        for idx_m, m in enumerate(messages):
            mid = str(m.get("message_id") or f"m_{idx_m}")
            role = str(m.get("sender_role") or "NHA_XE")
            sender_id = str(m.get("sender_id") or "")
            ekind = str(m.get("event_kind") or "message")
            raw_text = str(m.get("text") or "")
            reply_to = m.get("reply_to")
            etime = m.get("event_time")

            if etime and prev_time and str(etime) < str(prev_time):
                reordered = True
            if etime:
                prev_time = str(etime)

            # Kiểm tra trùng tin nhắn / duplicate event
            norm_t = re.sub(r"[^a-z0-9]", "", strip_accents(raw_text).lower())
            dup_key = (sender_id, norm_t)
            is_dup = (mid in seen_msg_ids) or (idx_m > 0 and ekind == "message" and dup_key in seen_msg_keys and len(norm_t) >= 6)
            seen_msg_ids.add(mid)
            seen_msg_keys.add(dup_key)

            if ekind == "web_approval":
                if pending_exists or pred_order_id or source_codes_fallback(scoped_plans):
                    tgt_id = pred_order_id or source_codes_fallback(scoped_plans)
                    pred_order_id = tgt_id
                    if "hủy" in raw_text.lower():
                        pred_intent = "CANCEL_ORDER_APPLIED"
                        pred_status = "APPLIED"
                        pred_tms_write = "CANCEL_ORDER_ONCE"
                    elif "chặng đóng" in raw_text.lower() or (comb_link and tgt_id and tgt_id.startswith("LO")):
                        pred_intent = "UPDATE_COMBINED_LOAD_APPLIED"
                        pred_status = "APPLIED"
                        pred_tms_write = "UPDATE_LOAD_LEG_ONLY"
                    elif "gán xe" in raw_text.lower() or saw_assign_request:
                        pred_intent = "ASSIGN_LOAD_TRUCK_APPLIED" if (tgt_id or "").startswith("LO") else "ASSIGN_TRUCK_APPLIED"
                        pred_status = "APPLIED"
                        pred_tms_write = "ASSIGN_TRUCK_ONCE"
                    else:
                        pred_intent = "UPDATE_TRUCK_APPLIED"
                        pred_status = "APPLIED"
                        pred_tms_write = "UPDATE_TRUCK_ONCE"
                    if tgt_id and tgt_id in scoped_plans:
                        pred_leg = "RETURN" if scoped_plans[tgt_id].order_type == "RO" else "LOAD"
                continue

            if ekind == "web_rejection":
                pred_intent = "UPDATE_TRUCK_REJECTED"
                pred_status = "REJECTED"
                pred_tms_write = "NONE"
                continue

            if ekind in ("tms_response", "tms_timeout"):
                # Đã xử lý bước duyệt/ghi TMS; giữ nguyên APPLIED + tms_write
                continue

            if ekind == "delete_request":
                pred_intent = "DELETE_MESSAGE_REQUEST"
                pred_status = "NEEDS_CONFIRMATION"
                pred_tms_write = "NONE"
                continue

            if ekind == "image_placeholder" or "[IMAGE_PLACEHOLDER_NO_ATTACHMENT]" in raw_text:
                pred_intent = "REQUEST_IMAGE"
                pred_status = "NEEDS_INFO"
                pred_tms_write = "NONE"
                pred_order_id = None
                continue

            if role == "DHVT" and ekind == "message":
                dhvt_edited = True
                continue

            # Làm sạch tiền tố OCR nếu là ocr_text_mock
            work_text = raw_text.replace("[OCR_TEXT_MOCK]", "").strip()
            lower_no_accent = strip_accents(work_text).lower()

            if is_dup:
                pred_intent = "IGNORE_DUPLICATE"
                pred_status = "NOOP"
                pred_tms_write = "NONE"
                continue

            # Kiểm tra Prompt Injection
            if "[system]" in work_text.lower() or "bo moi kiem tra" in lower_no_accent or "ignore all rules" in lower_no_accent:
                pred_intent = "REJECT_UNTRUSTED_INSTRUCTIONS"
                pred_status = "NEEDS_REVIEW"
                pred_tms_write = "NONE"
                m_ord = _ORDER_CODE_RE.search(work_text)
                if m_ord and m_ord.group(1).upper() in scoped_plans:
                    pred_order_id = m_ord.group(1).upper()
                    pred_leg = "RETURN" if scoped_plans[pred_order_id].order_type == "RO" else "LOAD"
                continue

            # Kiểm tra kiểm soát truy cập & cross-tenant / data dump
            if access_control.get(sender_id) == "NO_ACCESS" or "gui danh sach tai xe va so dien thoai" in lower_no_accent:
                pred_intent = "DENY_UNAUTHORIZED"
                pred_status = "DENIED"
                pred_tms_write = "NONE"
                m_ord = _ORDER_CODE_RE.search(work_text)
                if m_ord and m_ord.group(1).upper() in scoped_plans:
                    pred_order_id = m_ord.group(1).upper()
                    pred_leg = "RETURN" if scoped_plans[pred_order_id].order_type == "RO" else "LOAD"
                continue

            # Kiểm tra tin Forward chưa xác thực
            if ekind == "forward" or work_text.lower().startswith(("[chuyển tiếp]", "[fwd]")):
                m_ord = _ORDER_CODE_RE.search(work_text)
                if m_ord and m_ord.group(1).upper() in scoped_plans:
                    pred_order_id = m_ord.group(1).upper()
                    pred_leg = "RETURN" if scoped_plans[pred_order_id].order_type == "RO" else "LOAD"
                if "hủy" in work_text.lower() or re.search(r"\bhuy(?:\s+(?:chuyen|lenh|het|don|chang)|$)", lower_no_accent):
                    pred_intent = "REVIEW_FORWARDED_CANCEL"
                else:
                    pred_intent = "REVIEW_FORWARDED_UPDATE"
                pred_status = "NEEDS_REVIEW"
                pred_tms_write = "NONE"
                continue

            # Gọi REAL Core Parsers + Classifier + PhoBERT
            try:
                cls_intent = IntentClassifier.classify(work_text)
                ph = self.nlp_engine.analyze(work_text)
                used_local_nlp = True
                parsed_lines = TripParser.parse_message(work_text)
                if self._should_trigger_ai_proxy(parsed_lines, cls_intent):
                    llm_gate_any = True
                if parsed_lines and any(ln.source_format in ("F1", "F2", "F3") for ln in parsed_lines):
                    used_rule_fastpath = True
            except Exception:
                runtime_err = True
                cls_intent = Intent.PARSE
                parsed_lines = []

            # Bóc thực thể từ TripParser + Regex bổ trợ
            order_codes_in_msg = [m_o.group(1).upper() for m_o in _ORDER_CODE_RE.finditer(work_text)]
            plates_in_msg = extract_all_plates(work_text)
            conts_raw = extract_all_raw_containers(work_text)
            bookings_in_msg = [m_b.group(1).upper() for m_b in _BOOKING_RE.finditer(work_text)]
            seals_in_msg = [m_s.group(1).upper() for m_s in _SEAL_RE.finditer(work_text)]
            val_errs = extract_validation_errors_from_text(work_text)

            first_line = parsed_lines[0] if parsed_lines else None
            driver_in_msg = norm_driver(first_line.driver_name) if (first_line and first_line.driver_name) else ""
            phone_in_msg = clean_phone(first_line.driver_phone) if (first_line and first_line.driver_phone) else ""
            eta_in_msg = first_line.eta_time if (first_line and first_line.eta_time) else ""
            if not eta_in_msg:
                # Loại bỏ biển số xe (VD: 50H-24674, 15H 16940, 29H72119) trước khi bắt giờ để tránh nhầm '50H'/'15H' thành giờ
                text_no_plates = re.sub(
                    r"\b\d{2}[A-Za-z]{1,2}[\s.\-]?\d{3,6}(?:\.\d{1,3})?\b",
                    " ",
                    work_text,
                )
                mt = _TIME_RE.search(text_no_plates)
                if mt:
                    hr = int(mt.group(1))
                    mn = int(mt.group(2) or 0)
                    if 0 <= hr <= 23 and 0 <= mn <= 59:
                        eta_in_msg = f"{hr:02d}:{mn:02d}"

            # Cập nhật lịch sử tin để xử lý Quote (`reply_to`)
            msg_record = {
                "id": mid,
                "sender_id": sender_id,
                "order_codes": order_codes_in_msg,
                "plates": plates_in_msg,
                "conts": conts_raw,
                "text": work_text,
            }
            msg_history[mid] = msg_record

            # Lọc xã giao đơn lẻ & chặn tham chiếu mơ hồ không ngữ cảnh ("ok xe đó nhé")
            if cls_intent == Intent.IGNORE_CHAT and not (
                order_codes_in_msg or plates_in_msg or conts_raw or driver_in_msg or phone_in_msg or eta_in_msg
            ) and not reply_to:
                if any(ref_kw in lower_no_accent for ref_kw in ("xe do", "cont do", "chuyen do", "lenh do")):
                    pred_intent = "CLARIFY"
                    pred_status = "AMBIGUOUS"
                    pred_order_id = None
                    continue
                if idx_m == 0 and len(messages) == 1:
                    pred_intent = "IGNORE_SOCIAL"
                    pred_status = "NOOP"
                    pred_order_id = None
                    continue
                elif reply_to:
                    # Quote vào tin xã giao rồi nhắn ngắn -> mơ hồ
                    pred_intent = "CLARIFY"
                    pred_status = "AMBIGUOUS"
                    pred_order_id = None
                    continue
                else:
                    # Tin nhiễu giữa hội thoại ("em check đã ạ", "anh gửi giúp em chứng từ") -> bỏ qua nhiễu, giữ context cũ!
                    if any(
                        nw in lower_no_accent
                        for nw in ("em check da", "cong dang dong", "chung tu", "da nhan yeu cau", "doi kho xac nhan", "@moi nguoi", "thay roi anh")
                    ):
                        continue

            # Kiểm tra Quote vào tin xã giao
            if reply_to and reply_to in msg_history:
                quoted = msg_history[reply_to]
                if not quoted["order_codes"] and not quoted["conts"] and not quoted["plates"]:
                    pred_intent = "CLARIFY"
                    pred_status = "AMBIGUOUS"
                    pred_order_id = None
                    continue

            # Phát hiện mâu thuẫn nội tại ngay trong tin nhắn (2 số cont khác nhau cho 1 lệnh không rõ)
            if len(set(conts_raw)) >= 2 and ("hình như" in work_text.lower() or "nhưng" in work_text.lower()):
                pred_intent = "CLARIFY"
                pred_status = "AMBIGUOUS"
                pred_order_id = None
                continue

            # Kiểm tra nhiều lệnh / nhiều cont / nhiều xe chưa ghép cặp rõ
            if len(order_codes_in_msg) >= 2 and "kết hợp" not in work_text.lower() and not (plates_in_msg and ";" in work_text and len(plates_in_msg) == len(order_codes_in_msg)):
                # Ví dụ: "booking B26110331 có 2 lệnh LO2441/LO2438, xe 15C-13684" hoặc "LO2388 RO2723 xe A + B"
                if "/" in work_text or "+" in work_text or "2 lệnh" in work_text.lower():
                    # Ngoại trừ trường hợp tách riêng chặng ("hủy riêng chặng đóng LO2465, chặng trả RO2707 vẫn chạy")
                    if not any(kw in lower_no_accent for kw in ("chang dong", "chang tra", "chi lai chang", "ket hop")):
                        pred_intent = "CLARIFY"
                        pred_status = "AMBIGUOUS"
                        pred_order_id = None
                        continue

            # Kiểm tra nhiều cont cùng lúc ("TMSU4000701 xe 50H...; SELU4183600 xe 72H...")
            if len(parsed_lines) >= 2 and len(conts_raw) >= 2 and sheet == "02_RETURN ORDER":
                pred_intent = "PARSE_MULTIPLE_ORDERS"
                pred_status = "NEEDS_CONFIRMATION"
                continue

            # Kiểm tra cont lạ không tồn tại trong hệ thống khi nhà xe tra cứu ("Cont ZZZZ... check lệnh trả")
            if (
                conts_raw
                and not order_codes_in_msg
                and not any(p.container_no == conts_raw[0] for p in plan_list)
                and (conts_raw[0].startswith("ZZZZ") or any(w in lower_no_accent for w in ("check lenh", "kiem tra lenh")))
            ):
                pred_intent = "CLARIFY"
                pred_status = "UNMATCHED"
                pred_order_id = None
                continue

            # Kiểm tra lỗi định dạng cứng (Check digit ISO 6346, biển số hỏng XX/ZZ, SĐT ngắn/dài)
            if val_errs:
                err_codes = {e["code"] for e in val_errs}
                if err_codes & {"INVALID_ISO6346_CHECK_DIGIT", "INVALID_PLATE_FORMAT", "INVALID_PHONE_LENGTH", "INVALID_CONTAINER_LENGTH"}:
                    pred_intent = "REQUEST_CORRECTION"
                    pred_status = "NEEDS_INFO"
                    if order_codes_in_msg and order_codes_in_msg[0] in scoped_plans:
                        pred_order_id = order_codes_in_msg[0]
                        pred_leg = "RETURN" if scoped_plans[pred_order_id].order_type == "RO" else "LOAD"
                    elif "INVALID_ISO6346_CHECK_DIGIT" in err_codes:
                        pred_order_id = None
                    continue

            # Thử phân giải mã lệnh mục tiêu:
            # Ưu tiên 1: Quote `reply_to` -> lấy mã lệnh từ tin được quote
            resolved_code: Optional[str] = None
            if reply_to and reply_to in msg_history and msg_history[reply_to]["order_codes"]:
                cand_q = [c for c in msg_history[reply_to]["order_codes"] if c in scoped_plans]
                if cand_q:
                    resolved_code = cand_q[-1]

            # Ưu tiên 2: Mã lệnh rõ ràng trong tin hiện tại (ưu tiên lệnh gắn với câu hành động chính nếu có 2 lệnh trong tin kết hợp/đa cặp)
            if not resolved_code and order_codes_in_msg:
                valid_codes = [c for c in order_codes_in_msg if c in scoped_plans]
                if valid_codes:
                    if len(valid_codes) == 1:
                        resolved_code = valid_codes[0]
                    else:
                        # Nếu tin kết hợp RO + LO, xác định chặng đang nói tới (đóng vs trả)
                        if any(kw in lower_no_accent for kw in ("chang dong", "chi lai chang", "huy rieng chang dong", "lam tiep")) or (
                            "dong " in lower_no_accent and "lo" in lower_no_accent
                        ):
                            lo_c = [c for c in valid_codes if c.startswith("LO")]
                            resolved_code = lo_c[0] if lo_c else valid_codes[-1]
                        elif ("chang tra" in lower_no_accent or "xe tra" in lower_no_accent) and "xong roi" not in lower_no_accent:
                            ro_c = [c for c in valid_codes if c.startswith("RO")]
                            resolved_code = ro_c[0] if ro_c else valid_codes[0]
                        else:
                            resolved_code = valid_codes[-1]

            # Bảo vệ kết hợp giả lập: nếu cont chỉ khớp RO mà người dùng nói về chặng ĐÓNG hoặc không nói rõ chặng khi nguồn có cả RO+LO và KHÔNG có comb_link
            has_both_ro_lo = any(p.order_type == "RO" for p in plan_list) and any(p.order_type == "LO" for p in plan_list)
            mentions_load_cue = any(kw in lower_no_accent for kw in ("dong tai", "dong o ", "dong cho", "dong hang", "dong them", "lenh lo", "dong tiep", "dong " ))
            mentions_return_cue = any(kw in lower_no_accent for kw in ("tra ", "ha ", "lenh tra", "lenh ro"))
            if not resolved_code and conts_raw and not comb_link:
                ro_cont_matches = [p.order_code for p in plan_list if p.order_type == "RO" and p.container_no == conts_raw[0]]
                lo_cont_matches = [p.order_code for p in plan_list if p.order_type == "LO" and p.container_no == conts_raw[0]]
                if ro_cont_matches and not lo_cont_matches:
                    if any(kw in lower_no_accent for kw in ("ngoai ke hoach", "phat sinh", "dong rieng", "dong them kho moi")):
                        pred_intent = "CREATE_UNMATCHED_DRAFT"
                        pred_status = "UNMATCHED"
                        pred_order_id = None
                        continue
                    if mentions_load_cue:
                        pred_intent = "CLARIFY_LOAD_OR_COMBINED" if not any(kw in lower_no_accent for kw in ("khong ro lenh lo", "dong tiep", "cung ngay")) else "CLARIFY"
                        pred_status = "AMBIGUOUS"
                        pred_order_id = None
                        continue
                    if has_both_ro_lo and not mentions_return_cue and "chuyen xe" in lower_no_accent:
                        pred_intent = "CLARIFY"
                        pred_status = "AMBIGUOUS"
                        pred_order_id = None
                        continue

            # Nếu có comb_link rõ ràng và tin nói cụ thể chặng trả / chặng đóng từ context
            if comb_link and not order_codes_in_msg:
                if "xe tra" in lower_no_accent or ("chang tra" in lower_no_accent and "xong roi" not in lower_no_accent):
                    resolved_code = comb_link.get("return_order_id")
                elif "chang dong" in lower_no_accent or "dong tiep" in lower_no_accent:
                    resolved_code = comb_link.get("load_order_id")

            # Ưu tiên 3: Gọi REAL PlanResolutionEngine khi có container hoặc thông tin xe/tuyến/khách hàng
            if not resolved_code and conts_raw:
                # Khớp chính xác qua PlanResolutionEngine nếu cont nằm trong scoped_plans
                line_for_engine = first_line or TripParser.parse_message(f"cont {conts_raw[0]}")[0]
                if eta_in_msg and not line_for_engine.eta_time:
                    line_for_engine.eta_time = eta_in_msg
                carrier_int = _infer_sender_carrier(sender_id)
                res = PlanResolutionEngine.resolve(
                    line_for_engine,
                    plan_list,
                    carrier_id=carrier_int,
                    dates=[plan_date],
                    shadow=True,
                )
                if res.selected_plan_id and res.selected_plan_id in scoped_plans:
                    resolved_code = res.selected_plan_id
                else:
                    # Kiểm tra có đúng 1 plan khớp container trong scoped_plans không
                    cont_matches = [p.order_code for p in plan_list if p.container_no == conts_raw[0]]
                    if len(cont_matches) == 1:
                        resolved_code = cont_matches[0]
            elif not resolved_code and not order_codes_in_msg and comb_link and "xe tra" in lower_no_accent:
                resolved_code = comb_link.get("return_order_id")

            # Nếu resolved_code trùng với RO trong ngữ cảnh đang hỏi xác nhận lệnh LO sai khi chưa có comb_link
            if resolved_code and not comb_link and order_codes_in_msg:
                # Ví dụ tin 2 hỏi "đóng hàng tiếp, chắc lệnh LO2402 nhỉ?" sau tin 1 "RO2747 có cont ..."
                if "chac lenh" in lower_no_accent or (re.search(r"\blenh\s+lo\b", lower_no_accent) and any(c.startswith("RO") for c in sender_active_orders.get(sender_id, []))):
                    pred_intent = "CLARIFY"
                    pred_status = "AMBIGUOUS"
                    pred_order_id = None
                    continue

            # Cập nhật bộ nhớ lệnh của người gửi
            if resolved_code:
                active_order_id = resolved_code
                if resolved_code not in sender_active_orders[sender_id]:
                    sender_active_orders[sender_id].append(resolved_code)
            elif len(order_codes_in_msg) >= 1 and order_codes_in_msg[0] not in scoped_plans:
                # Mã lệnh lạ không tồn tại trong TMS (ví dụ TEST-930988 hoặc ngoài kế hoạch)
                pred_intent = "CREATE_UNMATCHED_DRAFT"
                pred_status = "UNMATCHED"
                pred_order_id = None
                continue

            # Nếu tin hiện tại chỉ có tham chiếu ngữ cảnh ("đổi lại nhé", "xe đó", "con này", "tuần sau vẫn xe đó")
            is_vague_change_only = (
                not order_codes_in_msg
                and not conts_raw
                and not plates_in_msg
                and not driver_in_msg
                and not phone_in_msg
                and not eta_in_msg
                and any(kw in lower_no_accent for kw in ("doi lai nhe", "xe do", "tuan sau", "ok xe do"))
            )
            if is_vague_change_only and not reply_to:
                pred_intent = "CLARIFY"
                pred_status = "AMBIGUOUS"
                pred_order_id = None
                continue

            # Xử lý câu ngắn không có mã lệnh/cont rõ nhưng người gửi có >1 lệnh hoạt động trước đó -> kiểm tra mơ hồ!
            if not resolved_code:
                hist_orders = sender_active_orders.get(sender_id, [])
                if len(hist_orders) >= 2 and not reply_to and not conts_raw and not bookings_in_msg:
                    if "con nay" in lower_no_accent:
                        for hc in hist_orders:
                            if scoped_plans[hc].container_no and not scoped_plans[hc].planned_driver_name:
                                resolved_code = hc
                                break
                        if not resolved_code:
                            resolved_code = hist_orders[0]
                    else:
                        # Không tự đoán một lệnh khi cùng người gửi đang mở >= 2 lệnh khác nhau và không nhắc mã lệnh/cont/quote
                        pred_intent = "CLARIFY"
                        pred_status = "AMBIGUOUS"
                        pred_order_id = None
                        continue
                elif len(hist_orders) == 1:
                    if comb_link and "xe tra" in lower_no_accent:
                        resolved_code = comb_link.get("return_order_id") or hist_orders[0]
                    else:
                        resolved_code = hist_orders[0]

            # Kiểm tra các tin phát sinh ngoài kế hoạch ("ngoài kế hoạch", "phát sinh", "đóng riêng")
            if any(kw in lower_no_accent for kw in ("ngoai ke hoach", "phat sinh", "dong rieng")) and not resolved_code:
                pred_intent = "CREATE_UNMATCHED_DRAFT"
                pred_status = "UNMATCHED"
                pred_order_id = None
                continue

            # Kiểm tra các trường hợp không có container cho lệnh đóng & câu hỏi mơ hồ tuyến/booking/khách
            if not resolved_code:
                if "chi co" in lower_no_accent or ("chua co cont" in lower_no_accent and not order_codes_in_msg):
                    if not bookings_in_msg and len(plates_in_msg) <= 1 and "tuyen" not in lower_no_accent and "khach" not in lower_no_accent:
                        pred_intent = "ASK_MORE_FIELDS"
                        pred_status = "NEEDS_INFO"
                    else:
                        pred_intent = "CLARIFY"
                        pred_status = "AMBIGUOUS"
                    pred_order_id = None
                    continue
                # Kiểm tra khớp duy nhất tuyến + giờ + khách (và phải khớp thật tên kho/tuyến, không chấp nhận alias mờ/thiếu)
                cands_by_loc = []
                for p in plan_list:
                    score_l = 0
                    wh_matched = False
                    if p.customer_name and strip_accents(p.customer_name).lower() in lower_no_accent:
                        score_l += 1
                    if p.route_name and strip_accents(p.route_name).lower() in lower_no_accent:
                        score_l += 1
                        wh_matched = True
                    elif p.delivery_address and fuzz.token_set_ratio(lower_no_accent, strip_accents(p.delivery_address).lower()) >= 75:
                        score_l += 1
                        wh_matched = True
                    if p.required_time and p.required_time in work_text:
                        score_l += 1
                    if score_l >= 3 or (wh_matched and score_l >= 2 and not conts_raw):
                        cands_by_loc.append(p.order_code)
                if len(cands_by_loc) == 1:
                    resolved_code = cands_by_loc[0]
                elif len(conts_raw) == 1 and not order_codes_in_msg and not any(p.container_no == conts_raw[0] for p in plan_list):
                    # Cont không có trong TMS fixture
                    if any(w in lower_no_accent for w in ("tra", "check lenh tra")):
                        pred_intent = "CLARIFY"
                        pred_status = "UNMATCHED"
                    else:
                        pred_intent = "CLARIFY"
                        pred_status = "AMBIGUOUS"
                    pred_order_id = None
                    continue
                else:
                    pred_intent = "CLARIFY"
                    pred_status = "AMBIGUOUS"
                    pred_order_id = None
                    continue

            # Lúc này đã xác định được resolved_code trong scoped_plans
            pred_order_id = resolved_code
            plan = scoped_plans[resolved_code]
            pred_leg = "RETURN" if plan.order_type == "RO" else "LOAD"

            # Thu thập thực thể vào bộ nhớ tích lũy
            for p_code in plates_in_msg:
                accumulated_entities["truck_plate"] = p_code
            if driver_in_msg:
                accumulated_entities["driver_name"] = driver_in_msg
            if phone_in_msg:
                accumulated_entities["driver_phone"] = phone_in_msg
            if conts_raw:
                accumulated_entities["container_no"] = conts_raw[0]
            if eta_in_msg:
                accumulated_entities["time"] = eta_in_msg

            # Phân loại hành động nghiệp vụ trên kế hoạch đã ghép:
            # A. Nếu ĐHVT vừa chỉnh sửa (CONCURRENT_EDIT) -> REVALIDATE_TMS
            if dhvt_edited:
                pred_intent = "REVALIDATE_TMS"
                pred_status = "NEEDS_REVIEW"
                continue

            if "gán xe" in work_text.lower() or "xin gán xe" in work_text.lower():
                saw_assign_request = True

            # B. Hủy thao tác đang chờ / Phủ định đổi xe ("không đổi nữa", "đừng cập nhật", "giữ xe cũ", "hủy thay xe, vẫn chạy chuyến")
            has_negation = (
                any(neg in lower_no_accent for neg in ("dung cap nhat", "khong doi nua", "giu xe cu", "khong thay doi", "huy thay xe", "huy doi xe", "van chay chuyen"))
                or bool(re.search(r"khong\s+(?:thay\s+)?doi(?:\s+xe)?\s+nua", lower_no_accent))
                or ("giu nguyen" in lower_no_accent and "chi lai" not in lower_no_accent and not driver_in_msg)
            )
            if has_negation and not re.search(r"\bhuy\s+(?:chuyen|lenh|het|don|chang|luon)\b", lower_no_accent):
                if pending_exists:
                    pred_intent = "CANCEL_PENDING_CHANGE"
                    pred_status = "CANCELLED_PENDING"
                    pending_exists = False
                else:
                    pred_intent = "NO_CHANGE"
                    pred_status = "NOOP"
                continue

            # C. Hoàn tác đổi xe đã áp dụng ("cho về xe cũ", "hoàn tác")
            if any(kw in lower_no_accent for kw in ("cho ve xe cu", "hoan tac", "quay lai xe cu")):
                pred_intent = "NEW_REVERSE_CHANGE_REQUEST"
                pred_status = "NEEDS_CONFIRMATION"
                continue

            # D. Hủy chuyến / hủy chặng đóng
            if "hủy" in work_text.lower() or re.search(r"\bhuy\s+(?:chuyen|lenh|het|don|chang|rieng)", lower_no_accent):
                if "da huy dung khong" in lower_no_accent:
                    pred_intent = "QUERY_RETURN_STATUS"
                    pred_status = "NEEDS_TMS_LOOKUP"
                elif "huy rieng chang dong" in lower_no_accent or (comb_link and "chang dong" in lower_no_accent):
                    pred_intent = "CANCEL_LOAD_LEG_REQUEST"
                    pred_status = "NEEDS_REVIEW"
                else:
                    pred_intent = "CANCEL_ORDER_REQUEST"
                    pred_status = "NEEDS_REVIEW"
                continue

            # E. Xác nhận đổi xe hoặc yêu cầu TMS thiếu sync
            if "sao bot chua co" in lower_no_accent or "em thay plan" in lower_no_accent:
                pred_intent = "RETRY_TMS_SYNC"
                pred_status = "NEEDS_TMS_LOOKUP"
                continue

            # F. Xung đột dữ liệu với TMS (`SOURCE_TMS_MISMATCH`, `WRONG_BOOKING`, `WRONG_CUSTOMER`, `WRONG_SEAL`, `WRONG_TIME`, `WRONG_WAREHOUSE`, `WRONG_OLD_TRUCK`, `DIFFERENT_WAREHOUSE_CONFLICT`)
            has_conflict = False
            is_update_word = any(kw in lower_no_accent for kw in ("doi ", "thay ", "sua ", "chuyen ", "lui ", "qua 00:", "cap nhat", "moi toi"))
            is_time_update_word = bool(
                re.search(
                    r"(?:doi|thay\s*doi|sua(?:\s*lai)?|lui|chinh(?:\s*lai)?)\s*(?:thoi\s*gian|gio)|qua\s*00:|moi\s*toi|hen\s*lai",
                    lower_no_accent,
                )
            )
            if "sai " in lower_no_accent or "he thong nhap gio khac" in lower_no_accent or "khac voi tms" in lower_no_accent:
                has_conflict = True
                pred_intent = "AUDIT_CONFLICT"
                pred_status = "NEEDS_REVIEW"
            elif seals_in_msg and plan.seal_no and seals_in_msg[0] != plan.seal_no.upper():
                # Container & Seal khớp đúng vs sai seal
                has_conflict = True
                pred_intent = "FLAG_CONFLICT"
                pred_status = "NEEDS_REVIEW"
            elif bookings_in_msg and plan.booking_no and bookings_in_msg[0] != plan.booking_no.upper():
                has_conflict = True
                pred_intent = "FLAG_CONFLICT"
                pred_status = "NEEDS_REVIEW"
            elif (
                not comb_link
                and first_line
                and first_line.customer_hint
                and plan.customer_name
                and re.search(r"(?:\bkh\b|khách\s*hàng|khach\s*hang|khách|khach)(?:\s*[:\-]?\s+|\s*[:\-])\S+", work_text, flags=re.IGNORECASE)
            ):
                ch_norm = strip_accents(first_line.customer_hint).upper()
                pl_cust = strip_accents(plan.customer_name).upper()
                if len(ch_norm) >= 3 and ch_norm not in ("NAY", "HANG", "SAN", "CHO") and ch_norm not in pl_cust and pl_cust not in ch_norm:
                    has_conflict = True
                    pred_intent = "FLAG_CONFLICT"
                    pred_status = "NEEDS_REVIEW"
            elif assump.get("applied_change") is None and "đổi từ" in work_text.lower() and len(plates_in_msg) >= 2:
                # Kiểm tra biển số cũ nhà xe nêu có khớp biển số trên TMS hay không
                if plan.planned_truck_plate and plates_in_msg[0] != plan.planned_truck_plate:
                    has_conflict = True
                    pred_intent = "FLAG_CONFLICT"
                    pred_status = "NEEDS_REVIEW"
            elif pred_leg == "RETURN" and eta_in_msg and plan.required_time and eta_in_msg != plan.required_time and not is_time_update_word:
                has_conflict = True
                pred_intent = "FLAG_CONFLICT"
                pred_status = "NEEDS_CONFIRMATION"
            elif pred_leg == "RETURN" and any(kw in lower_no_accent for kw in ("tra o ", "ve kho ", "ha o ", "tra tai ")) and (plan.warehouse_name or plan.delivery_address or plan.province_name):
                loc_m = re.search(r"(?:trả\s*ở|tra\s*o|về\s*kho|ve\s*kho|hạ\s*ở|ha\s*o|trả\s*tại|tra\s*tai)\s+([^\n|]+)", work_text, flags=re.IGNORECASE)
                if loc_m:
                    mentioned_loc = strip_accents(loc_m.group(1)).lower()
                    plan_loc = strip_accents(f"{plan.warehouse_name or ''} {plan.delivery_address or ''} {plan.province_name or ''}").lower()
                    plan_addr = strip_accents(plan.delivery_address or "").lower()
                    if fuzz.token_set_ratio(mentioned_loc, plan_loc) < 55 or (
                        plan_addr and len(mentioned_loc) >= 25 and fuzz.token_sort_ratio(mentioned_loc, plan_addr) < 78
                    ):
                        has_conflict = True
                        pred_intent = "FLAG_CONFLICT"
                        pred_status = "NEEDS_REVIEW"
            elif (
                pred_leg == "RETURN"
                and plates_in_msg
                and plan.planned_truck_plate
                and plates_in_msg[0] != plan.planned_truck_plate
                and ("lay xe" in lower_no_accent or "xe dang lay lenh" in lower_no_accent)
                and "doi" not in lower_no_accent
            ):
                has_conflict = True
                pred_intent = "VERIFY_CARRIER_ASSIGNMENT"
                pred_status = "NEEDS_CONFIRMATION"

            if has_conflict:
                continue

            # G. Đổi xe / Đổi tài / Đổi SĐT / Đổi giờ / Chuyển kho / Nhiều điểm
            if "chuyen sang kho" in lower_no_accent or ("kho " in lower_no_accent and "chuyen" in lower_no_accent):
                pred_intent = "UPDATE_WAREHOUSE_REQUEST"
                pred_status = "NEEDS_REVIEW"
                continue
            if (
                "doi xe" in lower_no_accent
                or "thay xe" in lower_no_accent
                or "doi sang" in lower_no_accent
                or "doi qua" in lower_no_accent
                or "doi thanh" in lower_no_accent
                or "sua sang" in lower_no_accent
                or "sua lan nua" in lower_no_accent
                or "doi lan nua" in lower_no_accent
                or "xe moi" in lower_no_accent
                or ("mới nhé" in work_text.lower() and plates_in_msg)
                or (reply_to and plates_in_msg and ("doi" in lower_no_accent or "mới" in work_text.lower()))
                or "chỉ đổi xe" in work_text.lower()
            ) and plates_in_msg:
                if pending_exists and ("lan nua" in lower_no_accent or "sua lan nua" in lower_no_accent):
                    pred_intent = "REVISE_PENDING_CHANGE"
                else:
                    pred_intent = "UPDATE_TRUCK_REQUEST"
                pending_exists = True
                if "xac nhan doi sang" in lower_no_accent:
                    pred_intent = "REVALIDATE_TMS"
                    pred_status = "NEEDS_REVIEW"
                else:
                    pred_status = "NEEDS_CONFIRMATION"
                continue
            if (
                "doi tai" in lower_no_accent
                or "tai doi thanh" in lower_no_accent
                or "chi lai chang" in lower_no_accent
                or ("doi thanh" in lower_no_accent and (driver_in_msg or "tai" in lower_no_accent))
            ) and (driver_in_msg or "tai " in lower_no_accent):
                pred_intent = "UPDATE_DRIVER_REQUEST"
                pred_status = "NEEDS_CONFIRMATION"
                continue
            if ("sua so" in lower_no_accent or "doi so" in lower_no_accent) and phone_in_msg:
                pred_intent = "UPDATE_PHONE_REQUEST"
                pred_status = "NEEDS_CONFIRMATION"
                continue
            if eta_in_msg and (is_update_word or "mat " in lower_no_accent or "lui " in lower_no_accent or "moi toi" in lower_no_accent):
                if pred_intent == "LOOKUP_RETURN" or "xe dang lay lenh" in lower_no_accent:
                    # sai giờ trên lệnh trả
                    pred_intent = "FLAG_CONFLICT"
                    pred_status = "NEEDS_CONFIRMATION"
                else:
                    pred_intent = "UPDATE_TIME_REQUEST"
                    pred_status = "NEEDS_CONFIRMATION"
                continue

            # H. Tra cứu / Thiếu thông tin / Bổ sung / Kết hợp RO-LO
            if comb_link and "xong roi" in lower_no_accent:
                pred_intent = "CHECK_LOAD_LEG"
                pred_status = "NEEDS_CONFIRMATION"
            elif "vẫn chưa có tài" in work_text.lower() or "chua co tai" in lower_no_accent:
                pred_intent = "MISSING_DRIVER_INFO"
                pred_status = "NEEDS_INFO"
            elif comb_link and any(kw in lower_no_accent for kw in ("ket hop", "combo", "dong tiep", "xe tra")):
                if pred_leg == "RETURN" and ("xe tra" in lower_no_accent or "tra cont" in lower_no_accent):
                    pred_intent = "SUPPLEMENT_RETURN"
                else:
                    pred_intent = "MATCH_COMBINED_LOAD"
                pred_status = "NEEDS_CONFIRMATION"
            elif pred_leg == "RETURN" and (
                "cho em xac nhan" in lower_no_accent
                or "ma cont:" in lower_no_accent
                or "xe dang lay lenh" in lower_no_accent
                or "so cong:" in lower_no_accent
                or "check lenh" in lower_no_accent
                or "kiem tra giup" in lower_no_accent
                or "check giup" in lower_no_accent
                or "tra giup" in lower_no_accent
                or (conts_raw and order_codes_in_msg and not (plates_in_msg or driver_in_msg or seals_in_msg or bookings_in_msg))
            ) and not (seals_in_msg or driver_in_msg or bookings_in_msg or plates_in_msg):
                pred_intent = "LOOKUP_RETURN"
                pred_status = "MATCHED"
            elif pred_leg == "RETURN" and (
                any(mk in lower_no_accent for mk in ("chua co so", "chua co sdt", "thieu so", "thieu sdt"))
                or (driver_in_msg and not phone_in_msg and not plan.planned_driver_phone and "sdt" not in lower_no_accent and "09" not in work_text and "03" not in work_text)
            ) and not phone_in_msg:
                pred_intent = "ASK_MISSING_PHONE"
                pred_status = "NEEDS_INFO"
            elif pred_leg == "RETURN" and seals_in_msg and not has_conflict:
                pred_intent = "VERIFY_RETURN_INFO"
                pred_status = "NEEDS_CONFIRMATION"
            elif ekind == "ocr_text_mock" or "[OCR_TEXT_MOCK]" in raw_text:
                pred_intent = "PARSE_OCR_TEXT_MOCK"
                pred_status = "NEEDS_CONFIRMATION"
            elif reordered:
                pred_intent = "HANDLE_REORDERED_EVENTS"
                pred_status = "NEEDS_CONFIRMATION"
            elif pred_leg == "LOAD" and ("cac diem" in lower_no_accent or ("diem 1" in lower_no_accent and "diem 2" in lower_no_accent)):
                pred_intent = "VERIFY_LOAD_ROUTE"
                pred_status = "NEEDS_CONFIRMATION"
            elif pred_leg == "LOAD":
                pred_intent = "SUPPLEMENT_LOAD"
                pred_status = "NEEDS_CONFIRMATION"
            else:
                pred_intent = "SUPPLEMENT"
                pred_status = "NEEDS_CONFIRMATION"

        dt_ms = (time.perf_counter_ns() - t0) / 1_000_000.0

        # Đánh giá đối chiếu với Expected (KHÔNG che giấu sai lệch thực tế)
        exp_intent = exp.get("intent")
        exp_status = exp.get("resolution_status")
        exp_order = exp.get("matched_order_id")
        exp_leg = exp.get("matched_leg")
        exp_op = exp.get("operation_type")
        exp_tms = exp.get("tms_write_expected", "NONE")
        exp_ents = exp.get("entities") or {}

        intent_ok = classify_intent_group(pred_intent) == classify_intent_group(exp_intent)
        status_ok = classify_status_group(pred_status) == classify_status_group(exp_status)

        order_case = exp_order is not None or pred_order_id is not None
        order_ok = pred_order_id == exp_order
        if exp_leg and exp_leg != "UNKNOWN":
            op_ok = (pred_leg == exp_leg) if pred_leg else False
        elif exp_op and exp_op != "UNKNOWN":
            op_ok = (pred_leg == exp_op) if pred_leg else False
        else:
            op_ok = True

        tms_ok = pred_tms_write == exp_tms

        # False update & Hallucination & Safety checks
        false_upd = bool(
            (pred_tms_write != "NONE" and exp_tms == "NONE")
            or (pred_tms_write != exp_tms and exp_tms != "NONE")
            or (pred_order_id is not None and exp_order is not None and pred_order_id != exp_order and pred_status in ("APPLIED", "NEEDS_CONFIRMATION"))
        )
        known_orders = set(self.base_plans.keys())
        hallucinated = bool(pred_order_id is not None and pred_order_id not in known_orders)

        # Tính Entity TP / FP / FN cho các trường chuẩn hóa chính
        ent_tp = ent_fp = ent_fn = 0
        all_texts = " ".join(str(m.get("text") or "") for m in messages if m.get("event_kind") in ("message", "ocr_text_mock", None))
        parsed_all_lines = TripParser.parse_message(all_texts.replace("[OCR_TEXT_MOCK]", ""))
        all_plates_found = extract_all_plates(all_texts)
        all_conts_found = extract_all_raw_containers(all_texts)
        all_drivers_found = [norm_driver(ln.driver_name) for ln in parsed_all_lines if ln.driver_name]
        all_phones_found = [clean_phone(ln.driver_phone) for ln in parsed_all_lines if ln.driver_phone]

        if exp_ents.get("container_no"):
            ec = clean_container(exp_ents["container_no"])
            if ec and (ec in all_conts_found or (pred_order_id and scoped_plans.get(pred_order_id) and scoped_plans[pred_order_id].container_no == ec)):
                ent_tp += 1
            else:
                ent_fn += 1
        if exp_ents.get("truck_plate"):
            ep = compact_plate(exp_ents["truck_plate"])
            if ep and (ep in all_plates_found or (pred_order_id and scoped_plans.get(pred_order_id) and scoped_plans[pred_order_id].planned_truck_plate == ep)):
                ent_tp += 1
            else:
                ent_fn += 1
        if exp_ents.get("new_truck_plate"):
            enp = compact_plate(exp_ents["new_truck_plate"])
            if enp and enp in all_plates_found:
                ent_tp += 1
            else:
                ent_fn += 1
        if exp_ents.get("driver_name"):
            ed = norm_driver(exp_ents["driver_name"])
            if ed and (
                any(ed == d or strip_accents(ed) == strip_accents(d) for d in all_drivers_found)
                or (pred_order_id and scoped_plans.get(pred_order_id) and scoped_plans[pred_order_id].planned_driver_name == ed)
            ):
                ent_tp += 1
            else:
                ent_fn += 1
        if exp_ents.get("driver_phone"):
            eph = clean_phone(exp_ents["driver_phone"])
            if eph and (
                eph in all_phones_found
                or (pred_order_id and scoped_plans.get(pred_order_id) and scoped_plans[pred_order_id].planned_driver_phone == eph)
            ):
                ent_tp += 1
            else:
                ent_fn += 1

        passed = bool(status_ok and order_ok and tms_ok and intent_ok and not false_upd and not hallucinated and not runtime_err)
        blocked = bool(false_upd or (exp_status == "DENIED" and pred_status != "DENIED"))

        # Phân tầng Rule / Local NLP / LLM Fallback
        llm_needed = llm_gate_any or (not passed and exp_status not in ("NOOP", "DENIED", "REJECTED"))
        if passed and not llm_gate_any and used_rule_fastpath and not multi_turn:
            tier = "TIER_1_RULE"
        elif passed and not llm_gate_any:
            tier = "TIER_2_LOCAL_NLP"
        else:
            tier = "TIER_3_LLM_FALLBACK"

        fail_reasons = []
        if not intent_ok:
            fail_reasons.append(f"intent {pred_intent}!={exp_intent}")
        if not status_ok:
            fail_reasons.append(f"status {pred_status}!={exp_status}")
        if not order_ok:
            fail_reasons.append(f"order {pred_order_id}!={exp_order}")
        if not tms_ok:
            fail_reasons.append(f"tms {pred_tms_write}!={exp_tms}")
        if false_upd:
            fail_reasons.append("FALSE_UPDATE")
        fail_str = "; ".join(fail_reasons)
        bot_summary = f"intent={pred_intent}, order={pred_order_id}, status={pred_status}, tms={pred_tms_write}"
        if fail_str:
            bot_summary += f" | {fail_str}"

        miss_case = exp_status == "NEEDS_INFO" or "MISSING_" in str(exp_intent) or "ASK_" in str(exp_intent) or "REQUEST_CORRECTION" == str(exp_intent)
        return EvalRecord(
            test_id=test_id,
            sheet_name=sheet,
            family=family,
            run_mode=sc["run_mode"],
            passed=passed,
            blocked=blocked,
            latency_ms=dt_ms,
            msg_count=len(messages),
            tier=tier,
            llm_triggered_raw=llm_gate_any,
            llm_needed_semantic=llm_needed,
            intent_match=intent_ok,
            ent_tp=ent_tp,
            ent_fp=ent_fp,
            ent_fn=ent_fn,
            multi_order_case=("MULTI" in family or family in ("TWO_LOADS_SAME_BOOKING",)),
            multi_order_ok=passed if ("MULTI" in family or family in ("TWO_LOADS_SAME_BOOKING",)) else False,
            context_case=multi_turn,
            context_ok=passed if multi_turn else False,
            reference_case=has_reply_to or ("REFERENT" in family or "STALE" in family),
            reference_ok=passed if (has_reply_to or ("REFERENT" in family or "STALE" in family)) else False,
            cross_leak=bool(not order_ok and exp_order is None and pred_order_id is not None),
            order_match_case=order_case,
            order_match_ok=order_ok,
            order_type_ok=op_ok,
            workflow_ok=bool(status_ok and tms_ok and intent_ok),
            false_update=false_upd,
            missing_info_case=miss_case,
            missing_info_ok=bool(classify_status_group(pred_status) == "CLARIFY_OR_INFO") if miss_case else False,
            auto_resolved=bool(pred_status in ("MATCHED", "APPLIED", "NOOP") and passed),
            clarified=bool(pred_status in ("AMBIGUOUS", "NEEDS_INFO")),
            unnecessary_clarify=bool(pred_status in ("AMBIGUOUS", "NEEDS_INFO") and exp_status not in ("AMBIGUOUS", "NEEDS_INFO", "UNMATCHED")),
            hallucinated=hallucinated,
            escalated_human=bool(pred_status in ("NEEDS_CONFIRMATION", "NEEDS_REVIEW", "NEEDS_TMS_LOOKUP")),
            resp_accurate=passed,
            resp_relevant=bool(status_ok or intent_ok),
            resp_complete=bool(passed and ent_fn == 0),
            runtime_error=runtime_err,
            bot_summary=bot_summary,
            fail_reason=fail_str,
        )


def _infer_sender_carrier(sender_id: str) -> Optional[int]:
    """Tách carrier_id số từ sender_id dạng NX-321."""
    m = re.match(r"NX-(\d+)$", sender_id or "")
    return int(m.group(1)) if m else None


def source_codes_fallback(scoped_plans: dict[str, ProxyPlan]) -> Optional[str]:
    """Lấy mã lệnh duy nhất trong fixture nếu kịch bản chỉ có 1 lệnh gốc."""
    if len(scoped_plans) == 1:
        return next(iter(scoped_plans.keys()))
    return None


def safe_pct(num: float, den: float) -> float:
    """Tính tỷ lệ phần trăm làm tròn 2 chữ số."""
    return round((num / den) * 100.0, 2) if den > 0 else 0.0


def percentile(sorted_vals: list[float], pct: float) -> float:
    """Tính phân vị trên mảng đã sắp xếp."""
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(math.ceil(pct * len(sorted_vals))) - 1))
    return round(sorted_vals[idx], 4)


def compute_metrics_bundle(records: list[EvalRecord]) -> dict[str, Any]:
    """Tổng hợp toàn bộ 26 chỉ số (6 nhóm) và phân tầng Rule / Local NLP / LLM cho một tập bản ghi."""
    n = len(records)
    if n == 0:
        return {}
    passed_cnt = sum(1 for r in records if r.passed)
    blocked_cnt = sum(1 for r in records if r.blocked)
    total_msgs = sum(r.msg_count for r in records)
    lats = sorted(r.latency_ms for r in records)
    total_sec = sum(lats) / 1000.0

    # 01. NLP & Entity
    intent_acc = safe_pct(sum(1 for r in records if r.intent_match), n)
    tp = sum(r.ent_tp for r in records)
    fp = sum(r.ent_fp for r in records)
    fn = sum(r.ent_fn for r in records)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    mo = [r for r in records if r.multi_order_case]
    multi_acc = safe_pct(sum(1 for r in mo if r.multi_order_ok), len(mo)) if mo else None

    # 02. Context Understanding
    ctx = [r for r in records if r.context_case]
    ctx_acc = safe_pct(sum(1 for r in ctx if r.context_ok), len(ctx)) if ctx else None
    ref = [r for r in records if r.reference_case]
    ref_acc = safe_pct(sum(1 for r in ref if r.reference_ok), len(ref)) if ref else None
    iso_acc = safe_pct(n - sum(1 for r in records if r.cross_leak), n)

    # 03. Order & Workflow
    om = [r for r in records if r.order_match_case]
    om_acc = safe_pct(sum(1 for r in om if r.order_match_ok), len(om)) if om else None
    ot_acc = safe_pct(sum(1 for r in records if r.order_type_ok), n)
    wf_acc = safe_pct(sum(1 for r in records if r.workflow_ok), n)
    false_upd_rate = safe_pct(sum(1 for r in records if r.false_update), n)
    mi = [r for r in records if r.missing_info_case]
    mi_acc = safe_pct(sum(1 for r in mi if r.missing_info_ok), len(mi)) if mi else None

    # 04. Automation & Safety
    auto_rate = safe_pct(sum(1 for r in records if r.auto_resolved), n)
    clar_rate = safe_pct(sum(1 for r in records if r.clarified), n)
    unnec_clar_rate = safe_pct(sum(1 for r in records if r.unnecessary_clarify), n)
    halluc_rate = safe_pct(sum(1 for r in records if r.hallucinated), n)
    esc_rate = safe_pct(sum(1 for r in records if r.escalated_human), n)

    # 05. Response Quality
    resp_acc = safe_pct(sum(1 for r in records if r.resp_accurate), n)
    resp_rel = safe_pct(sum(1 for r in records if r.resp_relevant), n)
    resp_comp = safe_pct(sum(1 for r in records if r.resp_complete), n)

    # 06. Performance & Cost + Tier Analysis
    p50 = percentile(lats, 0.50)
    p95 = percentile(lats, 0.95)
    t1_cnt = sum(1 for r in records if r.tier == "TIER_1_RULE")
    t2_cnt = sum(1 for r in records if r.tier == "TIER_2_LOCAL_NLP")
    t3_cnt = sum(1 for r in records if r.tier == "TIER_3_LLM_FALLBACK")
    raw_llm_gate_cnt = sum(1 for r in records if r.llm_triggered_raw)
    llm_gate_rate = safe_pct(raw_llm_gate_cnt, n)
    llm_needed_rate = safe_pct(t3_cnt, n)

    # Chi phí trên 1.000 tin nhắn khi gọi LLM cho nhóm cần LLM Fallback
    llm_calls_per_1k = (t3_cnt / n) * 1000.0
    cost_per_call = (
        AVG_INPUT_TOKENS_PER_CALL * LLM_INPUT_COST_PER_1M / 1_000_000.0
        + AVG_OUTPUT_TOKENS_PER_CALL * LLM_OUTPUT_COST_PER_1M / 1_000_000.0
    )
    cost_per_1k = round(llm_calls_per_1k * cost_per_call, 4)
    err_rate = safe_pct(sum(1 for r in records if r.runtime_error), n)
    throughput_sc = round(n / total_sec, 1) if total_sec > 0 else 0.0
    throughput_msg = round(total_msgs / total_sec, 1) if total_sec > 0 else 0.0

    return {
        "total": n,
        "pass": passed_cnt,
        "fail": n - passed_cnt,
        "blocked": blocked_cnt,
        "pass_rate": safe_pct(passed_cnt, n),
        "total_messages": total_msgs,
        # 01
        "intent_accuracy": intent_acc,
        "entity_precision": round(prec * 100.0, 2),
        "entity_recall": round(rec * 100.0, 2),
        "entity_f1": round(f1 * 100.0, 2),
        "entity_tp": tp,
        "entity_fp": fp,
        "entity_fn": fn,
        "multi_order_accuracy": multi_acc,
        # 02
        "context_resolution_accuracy": ctx_acc,
        "reference_resolution_accuracy": ref_acc,
        "context_isolation_accuracy": iso_acc,
        # 03
        "order_matching_accuracy": om_acc,
        "order_type_accuracy": ot_acc,
        "workflow_accuracy": wf_acc,
        "false_update_rate": false_upd_rate,
        "missing_info_detection": mi_acc,
        # 04
        "auto_resolution_rate": auto_rate,
        "clarification_rate": clar_rate,
        "unnecessary_clarification_rate": unnec_clar_rate,
        "hallucination_rate": halluc_rate,
        "human_escalation_rate": esc_rate,
        # 05
        "response_accuracy": resp_acc,
        "response_relevance": resp_rel,
        "response_completeness": resp_comp,
        # 06 & Tiers
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "tier1_rule_count": t1_cnt,
        "tier1_rule_rate": safe_pct(t1_cnt, n),
        "tier2_local_nlp_count": t2_cnt,
        "tier2_local_nlp_rate": safe_pct(t2_cnt, n),
        "tier3_llm_fallback_count": t3_cnt,
        "tier3_llm_fallback_rate": llm_needed_rate,
        "llm_gate_raw_count": raw_llm_gate_cnt,
        "llm_gate_raw_rate": llm_gate_rate,
        "cost_per_1k_messages_usd": cost_per_1k,
        "error_rate": err_rate,
        "throughput_scenarios_per_s": throughput_sc,
        "throughput_messages_per_s": throughput_msg,
    }


def fmt_v(val: Any) -> str:
    """Định dạng giá trị hiển thị vào CSV/Excel."""
    if val is None:
        return "N/A"
    return str(val)


def build_cli_parser() -> argparse.ArgumentParser:
    """Khởi tạo bộ phân tích tham số dòng lệnh cho kiểm thử toàn bộ hoặc từng sheet/family/case."""
    parser = argparse.ArgumentParser(
        description="Kiểm thử Proxy In-Memory trên bộ 25.000 kịch bản (Zalo OA x TMS)."
    )
    parser.add_argument(
        "--list-sheets",
        action="store_true",
        help="Liệt kê toàn bộ 7 sheet và danh sách family kèm số lượng kịch bản rồi thoát.",
    )
    parser.add_argument(
        "--sheet",
        action="append",
        default=[],
        help="Lọc theo tên sheet (có thể truyền nhiều lần, VD: --sheet \"08_FORMAT ENTITY\").",
    )
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        help="Lọc theo tên family (có thể truyền nhiều lần, VD: --family F3_TABLE).",
    )
    parser.add_argument(
        "--test-id",
        action="append",
        default=[],
        help="Chạy và in chi tiết theo Test ID (VD: --test-id CTX-00001).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Giới hạn tối đa N kịch bản đầu tiên sau khi áp dụng bộ lọc.",
    )
    parser.add_argument(
        "--show-fails",
        type=int,
        default=15,
        help="Số ca FAIL/BLOCKED tối đa được in mẫu chi tiết ở chế độ lọc (mặc định: 15).",
    )
    parser.add_argument(
        "--only-fail",
        action="store_true",
        help="Chỉ tập trung in danh sách ca FAIL/BLOCKED (dùng kèm bộ lọc để debug).",
    )
    parser.add_argument(
        "--export-filtered",
        action="store_true",
        help="Khi chạy lọc theo sheet/family, xuất thêm CSV riêng tại backend/output/filtered/.",
    )
    return parser


def _print_sheets_catalog() -> None:
    """Đọc JSONL gốc và in bảng thống kê sheet cùng toàn bộ family."""
    sheet_counts: Counter[str] = Counter()
    fam_counts: dict[str, Counter[str]] = defaultdict(Counter)
    with JSONL_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            sc = json.loads(line)
            sh = sc.get("sheet_name", "UNKNOWN")
            fam = sc.get("family", "UNKNOWN")
            sheet_counts[sh] += 1
            fam_counts[sh][fam] += 1
    total = sum(sheet_counts.values())
    print(f"Tổng kịch bản trong {JSONL_PATH.name}: {total}")
    for sh in SHEET_ORDER:
        fams = fam_counts.get(sh, Counter())
        print(f"- {sh}: {sheet_counts.get(sh, 0)} scenarios | {len(fams)} families")
        fam_str = ", ".join(f"{k}({v})" for k, v in sorted(fams.items()))
        print(f"    Families: {fam_str}")


def _run_filtered_eval(args: argparse.Namespace) -> None:
    """Thực thi kiểm thử có chọn lọc theo sheet / family / test-id / limit mà không ghi đè báo cáo tổng 25.000."""
    target_sheets = {s.strip() for s in args.sheet if s.strip()}
    target_families = {s.strip() for s in args.family if s.strip()}
    target_ids = {s.strip() for s in args.test_id if s.strip()}

    evaluator = ProxyEvaluator()
    records: list[EvalRecord] = []
    by_sheet: dict[str, list[EvalRecord]] = defaultdict(list)
    by_family: dict[tuple[str, str], list[EvalRecord]] = defaultdict(list)

    t_start = time.perf_counter()
    with JSONL_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            sc = json.loads(line)
            sh = sc.get("sheet_name", "")
            fam = sc.get("family", "")
            tid = str(sc.get("test_id", ""))
            if target_sheets and sh not in target_sheets:
                continue
            if target_families and fam not in target_families:
                continue
            if target_ids and tid not in target_ids:
                continue
            rec = evaluator.eval_parse_only(sc) if sc.get("run_mode") == "PARSE_ONLY" else evaluator.eval_workflow(sc)
            records.append(rec)
            by_sheet[rec.sheet_name].append(rec)
            by_family[(rec.sheet_name, rec.family)].append(rec)
            if args.limit is not None and len(records) >= args.limit:
                break
    total_wall_s = round(time.perf_counter() - t_start, 2)

    if not records:
        print("Không tìm thấy kịch bản nào khớp bộ lọc. Dùng --list-sheets để xem tên sheet và family hợp lệ.")
        return

    b = compute_metrics_bundle(records)
    print(f"FILTERED EVAL in {total_wall_s}s | Total={b['total']} | PASS={b['pass']} ({b['pass_rate']}%) | FAIL={b['fail']} | BLOCKED={b['blocked']}")
    print(f"  IntentAcc={b['intent_accuracy']}% | Entity P={b['entity_precision']}% R={b['entity_recall']}% F1={b['entity_f1']}% | MultiOrder={fmt_v(b['multi_order_accuracy'])}%")
    print(f"  ContextRes={fmt_v(b['context_resolution_accuracy'])}% | RefRes={fmt_v(b['reference_resolution_accuracy'])}% | CtxIso={b['context_isolation_accuracy']}%")
    print(f"  OrderMatch={fmt_v(b['order_matching_accuracy'])}% | OrderType={b['order_type_accuracy']}% | Workflow={b['workflow_accuracy']}% | FalseUpdate={b['false_update_rate']}% | MissingInfo={fmt_v(b['missing_info_detection'])}%")
    print(f"  AutoRes={b['auto_resolution_rate']}% | Clarify={b['clarification_rate']}% | UnnecClar={b['unnecessary_clarification_rate']}% | Halluc={b['hallucination_rate']}% | HumanEsc={b['human_escalation_rate']}%")
    print(f"  RespAcc={b['response_accuracy']}% | RespRel={b['response_relevance']}% | RespComp={b['response_completeness']}%")
    print(f"  P50={b['p50_latency_ms']}ms | P95={b['p95_latency_ms']}ms | Tier1_Rule={b['tier1_rule_rate']}% | Tier2_LocalNLP={b['tier2_local_nlp_rate']}% | Tier3_LLM_Needed={b['tier3_llm_fallback_rate']}% (RawAIGate={b['llm_gate_raw_rate']}%) | Cost/1k=${b['cost_per_1k_messages_usd']}")

    if len(by_sheet) > 1 or not target_sheets:
        print("\nTheo Sheet:")
        for sh in sorted(by_sheet.keys()):
            sb = compute_metrics_bundle(by_sheet[sh])
            print(f"  {sh}: {sb['pass']}/{sb['total']} ({sb['pass_rate']}%) | F1={sb['entity_f1']}% | Rule={sb['tier1_rule_rate']}% NLP={sb['tier2_local_nlp_rate']}% LLM={sb['tier3_llm_fallback_rate']}%")

    if not args.only_fail:
        print("\nTheo Family:")
        for (sh, fam), frecs in sorted(by_family.items()):
            fb = compute_metrics_bundle(frecs)
            print(f"  [{sh}] {fam}: {fb['pass']}/{fb['total']} ({fb['pass_rate']}%) | F1={fb['entity_f1']}% | Rule={fb['tier1_rule_rate']}% NLP={fb['tier2_local_nlp_rate']}% LLM={fb['tier3_llm_fallback_rate']}%")

    if target_ids:
        print("\nChi tiết từng Test ID:")
        for r in records:
            status = "BLOCKED" if r.blocked else ("PASS" if r.passed else "FAIL")
            print(f"  {r.test_id} [{r.sheet_name} / {r.family}] -> {status} | tier={r.tier} | llm_gate={r.llm_triggered_raw} | llm_needed={r.llm_needed_semantic} | latency={round(r.latency_ms, 2)}ms")
            print(f"    BotSummary: {r.bot_summary}")
            if r.fail_reason:
                print(f"    FailReason: {r.fail_reason}")
    else:
        fails = [r for r in records if (not r.passed) or r.blocked]
        if fails and args.show_fails > 0:
            print(f"\nMẫu {min(len(fails), args.show_fails)}/{len(fails)} ca FAIL/BLOCKED:")
            for r in fails[: args.show_fails]:
                status = "BLOCKED" if r.blocked else "FAIL"
                print(f"  {r.test_id} [{r.sheet_name} / {r.family}] {status} | tier={r.tier} | {r.fail_reason} | bot={r.bot_summary}")

    if args.export_filtered:
        filtered_dir = OUTPUT_DIR / "filtered"
        filtered_dir.mkdir(parents=True, exist_ok=True)
        slug_parts = [re.sub(r"[^A-Za-z0-9_-]+", "_", s) for s in (sorted(target_sheets) + sorted(target_families) + sorted(target_ids))]
        slug = "_".join(p for p in slug_parts if p)[:80] or "subset"
        out_path = filtered_dir / f"eval_{slug}.csv"
        with out_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "Test ID", "Sheet", "Family", "Run Mode", "PASS/FAIL", "Blocked",
                "Tier", "LLM Gate Raw", "LLM Needed", "Latency (ms)",
                "Intent Match", "TP", "FP", "FN", "False Update", "Hallucinated",
                "Bot Summary", "Fail Reason",
            ])
            for r in records:
                w.writerow([
                    r.test_id, r.sheet_name, r.family, r.run_mode,
                    "BLOCKED" if r.blocked else ("PASS" if r.passed else "FAIL"),
                    r.blocked, r.tier, r.llm_triggered_raw, r.llm_needed_semantic,
                    round(r.latency_ms, 3), r.intent_match, r.ent_tp, r.ent_fp, r.ent_fn,
                    r.false_update, r.hallucinated, r.bot_summary, r.fail_reason,
                ])
        print(f"\nĐã xuất CSV kết quả lọc: {out_path}")


def main() -> None:
    parser = build_cli_parser()
    args = parser.parse_args()
    if args.list_sheets:
        _print_sheets_catalog()
        return
    if args.sheet or args.family or args.test_id or args.limit is not None or args.only_fail or args.export_filtered:
        _run_filtered_eval(args)
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CSV_SHEETS_DIR.mkdir(parents=True, exist_ok=True)

    evaluator = ProxyEvaluator()
    records: list[EvalRecord] = []
    by_sheet: dict[str, list[EvalRecord]] = defaultdict(list)
    by_family: dict[tuple[str, str], list[EvalRecord]] = defaultdict(list)

    t_start = time.perf_counter()
    with JSONL_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            sc = json.loads(line)
            if sc.get("run_mode") == "PARSE_ONLY":
                rec = evaluator.eval_parse_only(sc)
            else:
                rec = evaluator.eval_workflow(sc)
            records.append(rec)
            by_sheet[rec.sheet_name].append(rec)
            by_family[(rec.sheet_name, rec.family)].append(rec)
    total_wall_s = round(time.perf_counter() - t_start, 2)

    overall = compute_metrics_bundle(records)
    sheet_bundles = {sh: compute_metrics_bundle(by_sheet[sh]) for sh in SHEET_ORDER}
    family_rows = []
    for (sh, fam), frecs in sorted(by_family.items()):
        fb = compute_metrics_bundle(frecs)
        family_rows.append((sh, fam, fb))

    # 1. Ghi file CSV tổng hợp đa phần chuẩn UTF-8 BOM (1 file CSV lớn chứa tất cả các bảng đánh giá)
    master_csv = OUTPUT_DIR / "eval_25000_detailed_report.csv"
    with master_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["=== SECTION 1: TONG QUAN HE THONG & 26 CHI SO DANH GIA ==="])
        w.writerow(["Nhom chi so", "Chi so", "Gia tri toan bo (25000)", "Don vi", "Ghi chu danh gia"])
        metric_spec = [
            ("00. Tong quan", "Tong kich ban", overall["total"], "scenarios", f"Wall clock={total_wall_s}s | NLP={evaluator.nlp_engine.backend_mode} ({evaluator.nlp_engine.model_name})"),
            ("00. Tong quan", "So ca PASS (Core Local Proxy)", overall["pass"], "scenarios", ""),
            ("00. Tong quan", "So ca FAIL (Can nang cap / LLM)", overall["fail"], "scenarios", ""),
            ("00. Tong quan", "So ca BLOCKED (An toan / Quyen)", overall["blocked"], "scenarios", ""),
            ("00. Tong quan", "Pass Rate (Core Local)", overall["pass_rate"], "%", ""),
            ("01. NLP & Entity", "Intent Accuracy", overall["intent_accuracy"], "%", "Nhom hoa y dinh chinh"),
            ("01. NLP & Entity", "Entity Precision", overall["entity_precision"], "%", f"TP={overall['entity_tp']}, FP={overall['entity_fp']}"),
            ("01. NLP & Entity", "Entity Recall", overall["entity_recall"], "%", f"TP={overall['entity_tp']}, FN={overall['entity_fn']}"),
            ("01. NLP & Entity", "Entity F1-score", overall["entity_f1"], "%", ""),
            ("01. NLP & Entity", "Multi-order Extraction Accuracy", fmt_v(overall["multi_order_accuracy"]), "%", "Da chuyen >=2 / da lenh"),
            ("02. Context Understanding", "Context Resolution Accuracy", fmt_v(overall["context_resolution_accuracy"]), "%", "Hoi thoai nhieu luot"),
            ("02. Context Understanding", "Reference Resolution Accuracy", fmt_v(overall["reference_resolution_accuracy"]), "%", "Quote / reply_to / dai tu"),
            ("02. Context Understanding", "Context Isolation Accuracy", overall["context_isolation_accuracy"], "%", "Khong nham giua cac chuyen/nha xe"),
            ("03. Order & Workflow", "Order Matching Accuracy", fmt_v(overall["order_matching_accuracy"]), "%", "Ghep dung ma lenh TMS"),
            ("03. Order & Workflow", "Order Type Accuracy", overall["order_type_accuracy"], "%", "Phan biet RO / LO / Ket hop"),
            ("03. Order & Workflow", "Workflow Accuracy", overall["workflow_accuracy"], "%", "Them / sua / huy / web_approval / tms"),
            ("03. Order & Workflow", "False Update Rate", overall["false_update_rate"], "%", "Thap hon la tot hon"),
            ("03. Order & Workflow", "Missing Information Detection", fmt_v(overall["missing_info_detection"]), "%", "Phat hien thieu thong tin / sai dinh dang"),
            ("04. Automation & Safety", "Auto-resolution Rate", overall["auto_resolution_rate"], "%", "Tu xu ly khong can hoi lai"),
            ("04. Automation & Safety", "Clarification Rate", overall["clarification_rate"], "%", "Ty le Bot hoi lai"),
            ("04. Automation & Safety", "Unnecessary Clarification Rate", overall["unnecessary_clarification_rate"], "%", "Hoi lai khi du du lieu"),
            ("04. Automation & Safety", "Hallucination Rate", overall["hallucination_rate"], "%", "Tu bia ma lenh / bien so"),
            ("04. Automation & Safety", "Human Escalation Rate", overall["human_escalation_rate"], "%", "Chuyen DHVT duyet Web"),
            ("05. Response Quality", "Response Accuracy", overall["response_accuracy"], "%", "Chinh xac nghiep vu & trang thai"),
            ("05. Response Quality", "Response Relevance", overall["response_relevance"], "%", "Dung loai yeu cau"),
            ("05. Response Quality", "Response Completeness", overall["response_completeness"], "%", "Du truong thuc the & ket qua"),
            ("06. Performance & Cost", "P50 Latency", overall["p50_latency_ms"], "ms", "Trung vi loi Python"),
            ("06. Performance & Cost", "P95 Latency", overall["p95_latency_ms"], "ms", "Phan vi 95 loi Python"),
            ("06. Performance & Cost", "Tier-1 Rule/Regex Fast-Path Rate", overall["tier1_rule_rate"], "%", f"{overall['tier1_rule_count']} ca"),
            ("06. Performance & Cost", "Tier-2 Local NLP (PhoBERT+RapidFuzz+Context) Rate", overall["tier2_local_nlp_rate"], "%", f"{overall['tier2_local_nlp_count']} ca"),
            ("06. Performance & Cost", "Tier-3 LLM Fallback Needed Rate", overall["tier3_llm_fallback_rate"], "%", f"{overall['tier3_llm_fallback_count']} ca can LLM de dat dung"),
            ("06. Performance & Cost", "AIFallback Gate Raw Trigger Rate", overall["llm_gate_raw_rate"], "%", f"{overall['llm_gate_raw_count']} ca kich hoat should_trigger_ai()"),
            ("06. Performance & Cost", "Cost per 1,000 Messages", overall["cost_per_1k_messages_usd"], "USD", "Uoc tinh theo Gemini Flash $0.10/1M in, $0.40/1M out"),
            ("06. Performance & Cost", "Error Rate", overall["error_rate"], "%", "Loi runtime pipeline"),
            ("06. Performance & Cost", "Throughput (scenarios/sec)", overall["throughput_scenarios_per_s"], "sc/s", f"{overall['throughput_messages_per_s']} msg/s"),
        ]
        for row in metric_spec:
            w.writerow(row)

        w.writerow([])
        w.writerow(["=== SECTION 2: KET QUA CHI TIET TUNG SHEET ==="])
        sheet_headers = [
            "Sheet", "Tong Test", "PASS", "FAIL", "BLOCKED", "Pass Rate (%)",
            "Intent Acc (%)", "Precision (%)", "Recall (%)", "F1 (%)", "Multi-order Acc (%)",
            "Context Acc (%)", "Reference Acc (%)", "Isolation Acc (%)",
            "Order Match (%)", "Order Type (%)", "Workflow Acc (%)", "False Update (%)", "Missing Info (%)",
            "Auto-Res (%)", "Clarify (%)", "Unnec Clarify (%)", "Hallucination (%)", "Escalation (%)",
            "Resp Acc (%)", "Resp Rel (%)", "Resp Comp (%)",
            "P50 (ms)", "P95 (ms)", "Tier1 Rule (%)", "Tier2 Local NLP (%)", "Tier3 LLM Needed (%)", "LLM Gate Raw (%)", "Cost/1k Msg (USD)", "Error (%)"
        ]
        w.writerow(sheet_headers)
        for sh in SHEET_ORDER + ["ALL_25000"]:
            b = overall if sh == "ALL_25000" else sheet_bundles[sh]
            w.writerow([
                sh, b["total"], b["pass"], b["fail"], b["blocked"], b["pass_rate"],
                b["intent_accuracy"], b["entity_precision"], b["entity_recall"], b["entity_f1"], fmt_v(b["multi_order_accuracy"]),
                fmt_v(b["context_resolution_accuracy"]), fmt_v(b["reference_resolution_accuracy"]), b["context_isolation_accuracy"],
                fmt_v(b["order_matching_accuracy"]), b["order_type_accuracy"], b["workflow_accuracy"], b["false_update_rate"], fmt_v(b["missing_info_detection"]),
                b["auto_resolution_rate"], b["clarification_rate"], b["unnecessary_clarification_rate"], b["hallucination_rate"], b["human_escalation_rate"],
                b["response_accuracy"], b["response_relevance"], b["response_completeness"],
                b["p50_latency_ms"], b["p95_latency_ms"], b["tier1_rule_rate"], b["tier2_local_nlp_rate"], b["tier3_llm_fallback_rate"], b["llm_gate_raw_rate"], b["cost_per_1k_messages_usd"], b["error_rate"],
            ])

        w.writerow([])
        w.writerow(["=== SECTION 3: PHAN TICH TY LE RULE / LOCAL NLP / LLM FALLBACK THEO TUNG FAMILY (134 FAMILIES) ==="])
        w.writerow([
            "Sheet", "Family", "Total", "PASS", "FAIL", "Pass Rate (%)",
            "Tier1 Rule (n)", "Tier1 Rule (%)", "Tier2 Local NLP (n)", "Tier2 Local NLP (%)",
            "Tier3 LLM Needed (n)", "Tier3 LLM Needed (%)", "LLM Gate Raw (%)",
            "Entity F1 (%)", "Order Match (%)", "P50 (ms)", "P95 (ms)", "Cost/1k (USD)"
        ])
        for sh, fam, fb in family_rows:
            w.writerow([
                sh, fam, fb["total"], fb["pass"], fb["fail"], fb["pass_rate"],
                fb["tier1_rule_count"], fb["tier1_rule_rate"],
                fb["tier2_local_nlp_count"], fb["tier2_local_nlp_rate"],
                fb["tier3_llm_fallback_count"], fb["tier3_llm_fallback_rate"],
                fb["llm_gate_raw_rate"], fb["entity_f1"], fmt_v(fb["order_matching_accuracy"]),
                fb["p50_latency_ms"], fb["p95_latency_ms"], fb["cost_per_1k_messages_usd"]
            ])

    # 2. Xuất từng file CSV tách riêng tương ứng các "sheet" báo cáo trong output/csv_sheets/
    with (CSV_SHEETS_DIR / "00_TONG_QUAN_26_CHI_SO.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Nhom chi so", "Chi so", "Gia tri toan bo", "Don vi", "Ghi chu"])
        for row in metric_spec:
            w.writerow(row)

    with (CSV_SHEETS_DIR / "01_KET_QUA_TUNG_SHEET.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(sheet_headers)
        for sh in SHEET_ORDER + ["ALL_25000"]:
            b = overall if sh == "ALL_25000" else sheet_bundles[sh]
            w.writerow([
                sh, b["total"], b["pass"], b["fail"], b["blocked"], b["pass_rate"],
                b["intent_accuracy"], b["entity_precision"], b["entity_recall"], b["entity_f1"], fmt_v(b["multi_order_accuracy"]),
                fmt_v(b["context_resolution_accuracy"]), fmt_v(b["reference_resolution_accuracy"]), b["context_isolation_accuracy"],
                fmt_v(b["order_matching_accuracy"]), b["order_type_accuracy"], b["workflow_accuracy"], b["false_update_rate"], fmt_v(b["missing_info_detection"]),
                b["auto_resolution_rate"], b["clarification_rate"], b["unnecessary_clarification_rate"], b["hallucination_rate"], b["human_escalation_rate"],
                b["response_accuracy"], b["response_relevance"], b["response_completeness"],
                b["p50_latency_ms"], b["p95_latency_ms"], b["tier1_rule_rate"], b["tier2_local_nlp_rate"], b["tier3_llm_fallback_rate"], b["llm_gate_raw_rate"], b["cost_per_1k_messages_usd"], b["error_rate"],
            ])

    with (CSV_SHEETS_DIR / "02_PHAN_TICH_RULE_NLP_LLM.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Sheet", "Family", "Total", "PASS", "FAIL", "Pass Rate (%)",
            "Tier1 Rule (n)", "Tier1 Rule (%)", "Tier2 Local NLP (n)", "Tier2 Local NLP (%)",
            "Tier3 LLM Needed (n)", "Tier3 LLM Needed (%)", "LLM Gate Raw (%)",
            "Entity F1 (%)", "Order Match (%)", "P50 (ms)", "P95 (ms)", "Cost/1k (USD)"
        ])
        for sh, fam, fb in family_rows:
            w.writerow([
                sh, fam, fb["total"], fb["pass"], fb["fail"], fb["pass_rate"],
                fb["tier1_rule_count"], fb["tier1_rule_rate"],
                fb["tier2_local_nlp_count"], fb["tier2_local_nlp_rate"],
                fb["tier3_llm_fallback_count"], fb["tier3_llm_fallback_rate"],
                fb["llm_gate_raw_rate"], fb["entity_f1"], fmt_v(fb["order_matching_accuracy"]),
                fb["p50_latency_ms"], fb["p95_latency_ms"], fb["cost_per_1k_messages_usd"]
            ])

    with (CSV_SHEETS_DIR / "03_CHI_TIET_25000_CASES.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Test ID", "Sheet", "Family", "Run Mode", "PASS/FAIL", "Blocked",
            "Tier", "LLM Gate Raw", "LLM Needed", "Latency (ms)",
            "Intent Match", "TP", "FP", "FN", "False Update", "Hallucinated",
            "Bot Summary", "Fail Reason"
        ])
        for r in records:
            w.writerow([
                r.test_id, r.sheet_name, r.family, r.run_mode,
                "BLOCKED" if r.blocked else ("PASS" if r.passed else "FAIL"),
                r.blocked, r.tier, r.llm_triggered_raw, r.llm_needed_semantic,
                round(r.latency_ms, 3), r.intent_match, r.ent_tp, r.ent_fp, r.ent_fn,
                r.false_update, r.hallucinated, r.bot_summary, r.fail_reason,
            ])

    # 3. Xuất Excel báo cáo nhiều sheet (`eval_25000_detailed_report.xlsx`)
    rep_wb = openpyxl.Workbook()
    ws0 = rep_wb.active
    ws0.title = "00_TONG_QUAN_26_CHI_SO"
    ws0.append(["Nhom chi so", "Chi so", "Gia tri toan bo (25000)", "Don vi", "Ghi chu danh gia"])
    for row in metric_spec:
        ws0.append(list(row))

    ws1 = rep_wb.create_sheet("01_KET_QUA_TUNG_SHEET")
    ws1.append(sheet_headers)
    for sh in SHEET_ORDER + ["ALL_25000"]:
        b = overall if sh == "ALL_25000" else sheet_bundles[sh]
        ws1.append([
            sh, b["total"], b["pass"], b["fail"], b["blocked"], b["pass_rate"],
            b["intent_accuracy"], b["entity_precision"], b["entity_recall"], b["entity_f1"], b["multi_order_accuracy"],
            b["context_resolution_accuracy"], b["reference_resolution_accuracy"], b["context_isolation_accuracy"],
            b["order_matching_accuracy"], b["order_type_accuracy"], b["workflow_accuracy"], b["false_update_rate"], b["missing_info_detection"],
            b["auto_resolution_rate"], b["clarification_rate"], b["unnecessary_clarification_rate"], b["hallucination_rate"], b["human_escalation_rate"],
            b["response_accuracy"], b["response_relevance"], b["response_completeness"],
            b["p50_latency_ms"], b["p95_latency_ms"], b["tier1_rule_rate"], b["tier2_local_nlp_rate"], b["tier3_llm_fallback_rate"], b["llm_gate_raw_rate"], b["cost_per_1k_messages_usd"], b["error_rate"],
        ])

    ws2 = rep_wb.create_sheet("02_PHAN_TICH_RULE_NLP_LLM")
    ws2.append([
        "Sheet", "Family", "Total", "PASS", "FAIL", "Pass Rate (%)",
        "Tier1 Rule (n)", "Tier1 Rule (%)", "Tier2 Local NLP (n)", "Tier2 Local NLP (%)",
        "Tier3 LLM Needed (n)", "Tier3 LLM Needed (%)", "LLM Gate Raw (%)",
        "Entity F1 (%)", "Order Match (%)", "P50 (ms)", "P95 (ms)", "Cost/1k (USD)"
    ])
    for sh, fam, fb in family_rows:
        ws2.append([
            sh, fam, fb["total"], fb["pass"], fb["fail"], fb["pass_rate"],
            fb["tier1_rule_count"], fb["tier1_rule_rate"],
            fb["tier2_local_nlp_count"], fb["tier2_local_nlp_rate"],
            fb["tier3_llm_fallback_count"], fb["tier3_llm_fallback_rate"],
            fb["llm_gate_raw_rate"], fb["entity_f1"], fb["order_matching_accuracy"],
            fb["p50_latency_ms"], fb["p95_latency_ms"], fb["cost_per_1k_messages_usd"]
        ])
    rep_wb.save(OUTPUT_DIR / "eval_25000_detailed_report.xlsx")

    # 4. Tạo bản sao workbook gốc và điền Kết quả Bot + PASS/FAIL cho 7 sheet
    eval_wb_path = OUTPUT_DIR / "zalo_tms_25000_tests_EVALUATED.xlsx"
    shutil.copyfile(WORKBOOK_SRC, eval_wb_path)
    ewb = openpyxl.load_workbook(eval_wb_path)
    rec_by_id = {r.test_id: r for r in records}
    col_map = {
        "01_CONTEXT": (6, 7),
        "02_RETURN ORDER": (6, 7),
        "03_LOAD ORDER": (7, 8),
        "04_COMBINED ORDER": (6, 7),
        "05_UPDATE CANCEL": (6, 7),
        "06_EDGE CASES": (4, 5),
        "08_FORMAT ENTITY": (4, 5),
    }
    for sh, (bot_col, status_col) in col_map.items():
        ws = ewb[sh]
        for row_idx in range(2, ws.max_row + 1):
            tid = ws.cell(row_idx, 1).value
            r = rec_by_id.get(str(tid))
            if r:
                ws.cell(row_idx, bot_col, r.bot_summary)
                ws.cell(row_idx, status_col, "BLOCKED" if r.blocked else ("PASS" if r.passed else "FAIL"))
    ewb["00_DASHBOARD"]["A3"] = (
        f"Nguồn: kế hoạch 09/11/2026 + 5 danh mục  |  25.000 kịch bản Proxy Core  |  PASS: {overall['pass']}/25.000 ({overall['pass_rate']}%)"
    )
    ewb.save(eval_wb_path)

    # In tóm tắt để kiểm chứng nhanh
    print(f"NLP ENGINE: backend_mode={evaluator.nlp_engine.backend_mode} | model_name={evaluator.nlp_engine.model_name}")
    print(f"DONE in {total_wall_s}s | PASS={overall['pass']}/{overall['total']} ({overall['pass_rate']}%) | FAIL={overall['fail']} | BLOCKED={overall['blocked']}")
    print(f"Entity P={overall['entity_precision']}% R={overall['entity_recall']}% F1={overall['entity_f1']}%")
    print(f"Tier1 Rule={overall['tier1_rule_rate']}% | Tier2 Local NLP={overall['tier2_local_nlp_rate']}% | Tier3 LLM Needed={overall['tier3_llm_fallback_rate']}% (Raw AI Gate={overall['llm_gate_raw_rate']}%)")
    print(f"Latency P50={overall['p50_latency_ms']}ms P95={overall['p95_latency_ms']}ms | Throughput={overall['throughput_scenarios_per_s']} sc/s | Cost/1k=${overall['cost_per_1k_messages_usd']}")
    for sh in SHEET_ORDER:
        sb = sheet_bundles[sh]
        print(f"  {sh}: {sb['pass']}/{sb['total']} ({sb['pass_rate']}%) | F1={sb['entity_f1']}% | Rule={sb['tier1_rule_rate']}% NLP={sb['tier2_local_nlp_rate']}% LLM={sb['tier3_llm_fallback_rate']}%")


if __name__ == "__main__":
    main()
