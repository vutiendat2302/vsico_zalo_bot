"""Module Quy Tắc Nghiệp Vụ Lõi (Pure Domain Business Rules).

Bao gồm các thuật toán chuẩn hóa và kiểm tra dữ liệu vận tải container:
1. Kiểm tra chữ số cuối (Check Digit) của số container theo chuẩn quốc tế ISO 6346 (Modulo 11).
2. Chuẩn hóa biển số xe đầu kéo và rơ-moóc (cả dạng viết liền '50H04915' cho bản ghi chuẩn
   và dạng hiển thị '50H-049.15').
3. Chuẩn hóa số điện thoại di động Việt Nam (10 chữ số, chuyển +84/84 về 0, giữ nguyên số thật khi lưu DB).
4. Làm sạch họ tên tài xế, giữ nguyên dấu tiếng Việt gốc của người gửi (không tự ý sửa 'Nguyên' thành 'Nguyễn').
"""

import re
from typing import Optional

# Bảng quy đổi giá trị chữ cái sang số theo tiêu chuẩn ISO 6346 (bỏ qua bội số của 11: 11, 22, 33)
ISO6346_CHAR_MAP: dict[str, int] = {
    "A": 10, "B": 12, "C": 13, "D": 14, "E": 15, "F": 16, "G": 17,
    "H": 18, "I": 19, "J": 20, "K": 21, "L": 23, "M": 24, "N": 25,
    "O": 26, "P": 27, "Q": 28, "R": 29, "S": 30, "T": 31, "U": 32,
    "V": 34, "W": 35, "X": 36, "Y": 37, "Z": 38,
}


def clean_container(raw: Optional[str]) -> Optional[str]:
    """Làm sạch chuỗi số container, chỉ giữ chữ cái in hoa và chữ số.

    Args:
        raw (Optional[str]): Chuỗi số container thô từ tin nhắn.

    Returns:
        Optional[str]: Số container đã làm sạch (ví dụ: 'VSIU2620327'), hoặc None nếu rỗng.
    """
    if not raw:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    return cleaned if cleaned else None


def compute_iso6346_check_digit(container_no: str) -> Optional[int]:
    """Tính toán chữ số kiểm tra (Check Digit - ký tự thứ 11) theo chuẩn ISO 6346 Modulo 11.

    Args:
        container_no (str): Chuỗi số container cần tính toán.

    Returns:
        Optional[int]: Chữ số kiểm tra hợp lệ (0 -> 9), hoặc None nếu sai cấu trúc 4 chữ + 7 số.
    """
    cleaned = clean_container(container_no)
    if not cleaned or not re.match(r"^[A-Z]{4}\d{7}$", cleaned):
        return None

    total = 0
    for idx in range(10):
        ch = cleaned[idx]
        val = ISO6346_CHAR_MAP.get(ch) if ch.isalpha() else int(ch)
        if val is None:
            return None
        total += val * (2**idx)

    return (total % 11) % 10


def validate_iso6346(container_no: Optional[str]) -> bool:
    """Kiểm tra một số container có hợp lệ hoàn toàn theo chuẩn ISO 6346 hay không.

    Args:
        container_no (Optional[str]): Số container cần thẩm định.

    Returns:
        bool: True nếu đúng định dạng 4 chữ + 7 số và khớp chữ số kiểm tra cuối cùng.
    """
    if not container_no:
        return False
    cleaned = clean_container(container_no)
    if not cleaned or len(cleaned) != 11:
        return False
    expected = compute_iso6346_check_digit(cleaned)
    return expected is not None and int(cleaned[-1]) == expected


def compact_plate(raw_plate: Optional[str]) -> Optional[str]:
    """Chuẩn hóa biển số xe về dạng viết liền in hoa cho Bản ghi chuẩn (ví dụ: '50H-04915' -> '50H04915').

    Args:
        raw_plate (Optional[str]): Biển số xe thô hoặc đã chuẩn hóa.

    Returns:
        Optional[str]: Biển số viết liền in hoa (ví dụ: '15C17066', '50H04915').
    """
    if not raw_plate:
        return None
    alnum = re.sub(r"[^A-Za-z0-9]", "", raw_plate).upper()
    return alnum if alnum else None


def clean_plate(raw_plate: Optional[str]) -> Optional[str]:
    """Chuẩn hóa biển số xe cơ giới Việt Nam về dạng hiển thị chuẩn (ví dụ: '15C-878.99').

    Args:
        raw_plate (Optional[str]): Chuỗi biển số thô (ví dụ: '15c 87899', '50H-04915').

    Returns:
        Optional[str]: Biển số đã chuẩn hóa hoặc None nếu không hợp lệ.
    """
    if not raw_plate:
        return None
    alnum = re.sub(r"[^A-Za-z0-9]", "", raw_plate).upper()
    match = re.match(r"^(\d{2}[A-Z]{1,2})(\d{4,5})$", alnum)
    if not match:
        return raw_plate.strip().upper()
    prefix, digits = match.group(1), match.group(2)
    if len(digits) == 5:
        return f"{prefix}-{digits[:3]}.{digits[3:]}"
    return f"{prefix}-{digits}"


def clean_phone(raw_phone: Optional[str]) -> Optional[str]:
    """Chuẩn hóa số điện thoại di động Việt Nam về đúng 10 chữ số bắt đầu bằng số 0.

    Lưu ý: Giữ nguyên số thật khi lưu vào cơ sở dữ liệu (không che bằng xxxx).
    Nếu dữ liệu đầu vào vốn đã bị che bằng '*' thì giữ nguyên để không làm mất dữ liệu.

    Args:
        raw_phone (Optional[str]): Chuỗi SĐT thô (ví dụ: '0931142873', '+84 903.976.359').

    Returns:
        Optional[str]: Chuỗi SĐT 10 chữ số (ví dụ: '0931142873').
    """
    if not raw_phone:
        return None
    stripped = raw_phone.strip()
    if "*" in stripped:
        masked = re.sub(r"[^0-9*]", "", stripped)
        if masked.startswith("84") and len(masked) == 11:
            masked = "0" + masked[2:]
        return masked if masked else None

    digits = re.sub(r"\D", "", stripped)
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if digits else None


EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50]|[\ufe0f]"
)


def clean_driver_name(raw_name: Optional[str]) -> Optional[str]:
    """Làm sạch họ tên tài xế, loại bỏ nhãn tiền tố và biểu tượng emoji nhưng giữ nguyên dấu tiếng Việt gốc của người gửi.

    Ví dụ: '\\n👤 Trần Hữu Dũng\\n📞' -> 'Trần Hữu Dũng'.

    Args:
        raw_name (Optional[str]): Chuỗi tên tài xế thô từ tin nhắn.

    Returns:
        Optional[str]: Họ tên tài xế đã làm sạch.
    """
    if not raw_name:
        return None
    # Chuẩn hóa ký tự xuống dòng và loại bỏ biểu tượng emoji
    text = (
        raw_name.replace("\\r", " ")
        .replace("\\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    text = EMOJI_PATTERN.sub(" ", text).strip()
    text = re.sub(r"^[\-\*•\d\.)\s]+", "", text)
    text = re.sub(
        r"^(?:tên\s*lái\s*xe|ten\s*lai\s*xe|tên\s*tài\s*xế|ten\s*tai\s*xe|bác\s*tài|bac\s*tai|"
        r"tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|tx|lx|tài|anh|chú|mr\.?)\s*[:\-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Loại bỏ số điện thoại dính kèm hoặc nhãn SĐT ở cuối tên
    text = re.sub(
        r"(?:sđt|sdt|đt|dt|lh|tel)?\s*[:\-]?\s*(?:\+?84|0)\d[\d\s.\-*xX]{7,11}[\d*xX]",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+(?:sđt|sdt|đt|dt|lh|tel)\s*[:\-]?$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -:/,.*|\t")
    if not text:
        return None
    return " ".join(word[0].upper() + word[1:].lower() if word else "" for word in text.split())
