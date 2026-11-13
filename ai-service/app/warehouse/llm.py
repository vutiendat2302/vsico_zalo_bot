"""Tầng 4 (LLM Selector): Nhờ LLM chọn đúng kho trong danh sách ứng viên từ backend."""

import json
from typing import Any

from app.providers.factory import get_ai_provider

_WH_SYSTEM_PROMPT = """Bạn là trợ lý logistics chọn đúng mã kho từ danh sách ứng viên.
Chỉ được chọn `warehouse_id` CÓ MẶT trong danh sách ứng viên, không tự bịa mã kho mới.
Nếu không có kho nào khớp hợp lý, trả về `{"matched": false, "warehouse_id": null, "confidence": 0.0}`.
CHỈ TRẢ VỀ JSON: {"matched": true|false, "warehouse_id": <int|null>, "confidence": <0.0-1.0>}."""


async def match_by_llm(
    raw_address: str,
    candidates: list[dict[str, Any]],
    threshold: float = 0.72,
) -> tuple[dict[str, Any], float] | None:
    """Yêu cầu AI Provider chọn kho ứng viên phù hợp nhất với tên/địa chỉ nhà xe nhập."""
    if not raw_address.strip() or not candidates:
        return None

    compact_cands = [
        {
            "warehouse_id": w.get("id"),
            "name": w.get("name"),
            "address": w.get("address"),
            "aliases": w.get("aliases") or [],
        }
        for w in candidates[:25]
    ]
    user_prompt = (
        f"Địa chỉ/tên kho nhà xe nhập: {raw_address}\n\n"
        f"Danh sách kho ứng viên:\n{json.dumps(compact_cands, ensure_ascii=False)}"
    )
    provider = get_ai_provider()
    res = await provider.generate_structured_json(system_prompt=_WH_SYSTEM_PROMPT, user_prompt=user_prompt)
    if not res.success or not res.parsed.get("matched"):
        return None

    selected_id = res.parsed.get("warehouse_id")
    conf = float(res.parsed.get("confidence") or 0.0)
    if selected_id is None or conf < threshold:
        return None

    matched_wh = next((w for w in candidates if str(w.get("id")) == str(selected_id)), None)
    if not matched_wh:
        return None
    return matched_wh, round(min(1.0, conf), 4)
