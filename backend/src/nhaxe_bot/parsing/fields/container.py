"""Module Trích Xuất Số Container (Container Field Parser).

Chịu trách nhiệm nhận diện và bóc tách số container từ văn bản tự do,
kèm theo việc thẩm định số kiểm tra chuẩn quốc tế ISO 6346 Modulo 11.
"""

import re
from typing import List, Optional, Tuple
from ...domain.rules import clean_container, validate_iso6346

# Mẫu regex nhận diện container: 4 chữ cái + ký tự phân cách tùy chọn + 7 chữ số
CONT_PATTERN = re.compile(r'\b([A-Za-z]{4}[\s\.\-]?[0-9]{7})\b')


def extract_containers(text: str) -> List[str]:
    """Tìm kiếm tất cả các số container hợp lệ xuất hiện trong văn bản.

    Args:
        text (str): Chuỗi văn bản tin nhắn.

    Returns:
        List[str]: Danh sách các chuỗi số container đã chuẩn hóa 11 ký tự (không trùng lặp).
    """
    matches = CONT_PATTERN.findall(text)
    conts = []
    for m in matches:
        cleaned = clean_container(m)
        if cleaned and cleaned not in conts:
            conts.append(cleaned)
    return conts


def extract_primary_container(text: str) -> Tuple[Optional[str], List[str]]:
    """Trích xuất container chính của xe và kiểm tra tính hợp lệ của số kiểm tra ISO 6346.

    Args:
        text (str): Chuỗi văn bản tin nhắn của 1 khối xe.

    Returns:
        Tuple[Optional[str], List[str]]:
            - cont: Số container chính (nếu tìm thấy), ngược lại None.
            - warnings: Danh sách mã cảnh báo (['thieu_cont'] nếu không thấy,
              ['cont_sai_dinh_dang'] nếu sai check digit ISO 6346).
    """
    conts = extract_containers(text)
    if not conts:
        return None, ["thieu_cont"]

    cont = conts[0]
    warnings = []
    # Thẩm định số kiểm tra theo thuật toán Modulo 11
    if not validate_iso6346(cont):
        warnings.append("cont_sai_dinh_dang")
    return cont, warnings
