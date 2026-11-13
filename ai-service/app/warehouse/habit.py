"""Tầng 1 (Habit): Đối chiếu địa chỉ dựa trên thói quen và bí danh lịch sử của nhà xe."""

from typing import Any

from app.warehouse.normalizer import normalize_address


def match_by_habit(
    raw_address: str,
    carrier_id: int | None,
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any], float] | None:
    """Khớp địa chỉ nhà xe gõ với bí danh hoặc thói quen đã lưu trong danh sách ứng viên."""
    target_norm = normalize_address(raw_address)
    if not target_norm:
        return None

    for wh in candidates:
        habit_carriers = wh.get("carrier_ids") or []
        aliases = wh.get("aliases") or []
        habit_addrs = wh.get("habit_addresses") or []
        combined_patterns = list(aliases) + list(habit_addrs)
        if carrier_id and carrier_id in habit_carriers:
            wh_norm = normalize_address(str(wh.get("normalized_name") or wh.get("name") or ""))
            if wh_norm:
                combined_patterns.append(wh_norm)

        for pat in combined_patterns:
            pat_norm = normalize_address(str(pat))
            if pat_norm and pat_norm == target_norm:
                is_carrier_match = bool(carrier_id and carrier_id in habit_carriers)
                return wh, (0.96 if is_carrier_match else 0.92)
    return None
