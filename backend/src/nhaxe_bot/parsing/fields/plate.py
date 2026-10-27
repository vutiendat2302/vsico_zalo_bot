"""Module Trích Xuất Biển Số Xe (Vehicle License Plate Parser).

Nhận diện và bóc tách biển số xe cơ giới (đầu kéo, tải, rơ-moóc) theo quy chuẩn Việt Nam.
"""

import re
from typing import Optional
from ...domain.rules import clean_plate

# Regex nhận diện biển số xe: 2 số tỉnh + 1-2 chữ cái + 4-5 số (hỗ trợ dấu gạch, chấm, khoảng cách và đứng sau tiền tố chữ)
PLATE_PATTERN = re.compile(
    r'(?:(?<=\b)|(?<=[A-Za-z]))(?<!\d)([0-9]{2}[A-Za-z][\dA-Za-z]?[\s\.\-]?(?:[0-9]{4,5}|[0-9]{3}\.[0-9]{2}))\b'
)


def extract_plate(text: str) -> Optional[str]:
    """Tìm kiếm, trích xuất và chuẩn hóa biển số xe cơ giới từ văn bản.

    Args:
        text (str): Chuỗi văn bản tin nhắn.

    Returns:
        Optional[str]: Biển số xe đã chuẩn hóa (ví dụ: '15C87899') nếu tìm thấy, ngược lại None.
    """
    match = PLATE_PATTERN.search(text)
    if match:
        return clean_plate(match.group(1))
    return None
