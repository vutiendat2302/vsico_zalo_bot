"""Tiện ích parse JSON an toàn từ phản hồi văn bản của LLM."""

import json
import re
from typing import Any


def parse_json_object(raw_text: str) -> dict[str, Any]:
    """Trích xuất đối tượng JSON hợp lệ từ văn bản thô do LLM sinh ra."""
    text = (raw_text or "").strip()
    if not text:
        return {}

    # Loại bỏ hàng rào markdown ```json ... ``` nếu model trả kèm định dạng
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
        if isinstance(loaded, list):
            return {"items": loaded}
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            loaded = json.loads(text[start : end + 1])
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            return {}
    return {}
