"""Module Trích Xuất Số Điện Thoại Tài Xế (Driver Phone Parser).

Nhận diện và bóc tách số điện thoại liên lạc của tài xế xe tải/đầu kéo.
"""

import re
from typing import Optional
from ...domain.rules import clean_phone

# Regex nhận diện số điện thoại di động Việt Nam (10 số, đầu số 03, 05, 07, 08, 09 hoặc +84)
PHONE_PATTERN = re.compile(r'(?:\+?84|0)(?:3|5|7|8|9)[0-9]{8}\b')


def extract_phone(text: str) -> Optional[str]:
    """Tìm kiếm và chuẩn hóa số điện thoại di động Việt Nam từ văn bản.

    Args:
        text (str): Chuỗi văn bản tin nhắn.

    Returns:
        Optional[str]: Chuỗi 10 chữ số chuẩn hóa (đầu số 0x) nếu tìm thấy, ngược lại None.
    """
    match = PHONE_PATTERN.search(text)
    if match:
        return clean_phone(match.group(0))
    return None
