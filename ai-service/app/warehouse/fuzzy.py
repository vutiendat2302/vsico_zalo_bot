"""Tầng 2 (Fuzzy): So khớp chuỗi mờ bằng RapidFuzz kết hợp từ khóa danh mục kho ứng viên."""

from difflib import SequenceMatcher
from typing import Any

from rapidfuzz import fuzz

from app.warehouse.normalizer import normalize_address


def _similarity_score(target: str, candidate: str) -> float:
    """Tính điểm tương đồng kết hợp giữa RapidFuzz (WRatio, token_set_ratio) và giao từ."""
    if not target or not candidate:
        return 0.0
    if target in candidate or candidate in target:
        shorter = min(len(target), len(candidate))
        longer = max(len(target), len(candidate))
        return round(min(0.95, 0.78 + 0.17 * (shorter / max(1, longer))), 4)

    t_tokens = set(target.split())
    c_tokens = set(candidate.split())
    token_overlap = len(t_tokens & c_tokens) / max(1, len(t_tokens | c_tokens))
    wratio = fuzz.WRatio(target, candidate) / 100.0
    tset = fuzz.token_set_ratio(target, candidate) / 100.0
    seq_score = SequenceMatcher(None, target, candidate).ratio()
    combined = 0.35 * wratio + 0.30 * tset + 0.20 * token_overlap + 0.15 * seq_score
    return round(combined, 4)


def match_by_fuzzy(
    raw_address: str,
    candidates: list[dict[str, Any]],
    threshold: float = 0.76,
) -> tuple[dict[str, Any], float] | None:
    """Tìm kho ứng viên có điểm tương đồng cao nhất vượt ngưỡng fuzzy."""
    target_norm = normalize_address(raw_address)
    if not target_norm:
        return None

    best_wh: dict[str, Any] | None = None
    best_score = 0.0

    for wh in candidates:
        fields = [
            wh.get("name") or "",
            wh.get("normalized_name") or "",
            wh.get("address") or "",
            *(wh.get("aliases") or []),
        ]
        for f in fields:
            cand_norm = normalize_address(str(f))
            if not cand_norm:
                continue
            score = _similarity_score(target_norm, cand_norm)
            if score > best_score:
                best_score = score
                best_wh = wh

    if best_wh and best_score >= threshold:
        return best_wh, best_score
    return None
