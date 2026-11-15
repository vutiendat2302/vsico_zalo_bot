"""Tiện ích chuẩn hóa địa chỉ tiếng Việt phục vụ đối chiếu kho nhiều tầng."""

import re
import unicodedata


def strip_accents(text: str) -> str:
    """Loại bỏ dấu tiếng Việt và ký tự đặc biệt để so khớp không phân biệt hoa thường."""
    normalized = unicodedata.normalize("NFD", text or "")
    no_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    no_marks = no_marks.replace("đ", "d").replace("Đ", "D")
    return no_marks


def normalize_address(text: str) -> str:
    """Chuẩn hóa chuỗi tên/địa chỉ kho về dạng gọn thống nhất."""
    clean = strip_accents(text).lower()
    clean = re.sub(r"[\.,;\-/\\()]+", " ", clean)
    clean = re.sub(r"\b(kho|bai|nha\s*may|kcn|cong\s*ty|tnhh|cp|dia\s*chi)\b", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean
