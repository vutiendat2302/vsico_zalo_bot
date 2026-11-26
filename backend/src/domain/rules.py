"""Module Quy Tắc Nghiệp Vụ Lõi (Pure Domain Business Rules).

Bao gồm các thuật toán chuẩn hóa và kiểm tra dữ liệu vận tải container:
1. Kiểm tra chữ số cuối (Check Digit) của số container theo chuẩn quốc tế ISO 6346 (Modulo 11).
2. Chuẩn hóa biển số xe đầu kéo (cả dạng viết liền '50H04915' cho bản ghi chuẩn
   và dạng hiển thị '50H-049.15').
3. Chuẩn hóa số điện thoại di động Việt Nam (10 chữ số, chuyển +84/84 về 0, giữ nguyên số thật khi lưu DB).
4. Làm sạch họ tên tài xế, giữ nguyên dấu tiếng Việt gốc của người gửi (không tự ý sửa 'Nguyên' thành 'Nguyễn').
"""

import re
from typing import Optional
import unicodedata

from src.domain.patterns import split_camel_case_vn

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
    match = re.match(r"^(\d{2}[A-Z]{1,2})(\d{4,6})$", alnum)
    if not match:
        return raw_plate.strip().upper()
    prefix, digits = match.group(1), match.group(2)
    if len(digits) == 6:
        return f"{prefix}-{digits[:3]}.{digits[3:]}"
    if len(digits) == 5:
        return f"{prefix}-{digits[:3]}.{digits[3:]}"
    return f"{prefix}-{digits}"


def _clean_single_phone(raw_token: str) -> Optional[str]:
    """Chuẩn hóa một số điện thoại di động đơn lẻ về dạng nội địa bắt đầu bằng 0."""
    stripped = (raw_token or "").strip()
    if not stripped:
        return None
    if "*" in stripped:
        masked = re.sub(r"[^0-9*]", "", stripped)
        if masked.startswith("84") and len(masked) == 11:
            masked = "0" + masked[2:]
        return masked if masked else None

    digits = re.sub(r"\D", "", stripped)
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if digits else None


def split_phones(phone_str: Optional[str]) -> list[str]:
    """Tách chuỗi một hoặc nhiều SĐT (ngăn cách bởi `|`, `/`, `,`, `;`) thành danh sách chuẩn hóa không trùng lặp."""
    if not phone_str:
        return []
    raw = str(phone_str).strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"\s*[|/,;]\s*", raw) if p.strip()]
    results: list[str] = []
    for part in parts:
        cleaned = _clean_single_phone(part)
        if cleaned and cleaned not in results:
            results.append(cleaned)
    if not results:
        single = _clean_single_phone(raw)
        if single:
            results.append(single)
    return results


def is_valid_phone_list(phone_str: Optional[str]) -> bool:
    """Kiểm tra chuỗi 1 hoặc nhiều SĐT (`09..1 | 09..2`) có hợp lệ toàn bộ (mỗi số đúng 10 chữ số đầu 0)."""
    phones = split_phones(phone_str)
    if not phones:
        return False
    for ph in phones:
        if "*" in ph:
            if len(ph) != 10 or not ph.startswith("0"):
                return False
        elif not re.match(r"^0\d{9}$", ph):
            return False
    return True


def clean_phone(raw_phone: Optional[str]) -> Optional[str]:
    """Chuẩn hóa một hoặc nhiều SĐT di động Việt Nam (nhiều số lưu theo dạng `'09..1 | 09..2'`).

    Lưu ý: Giữ nguyên số thật khi lưu vào cơ sở dữ liệu.

    Args:
        raw_phone (Optional[str]): Chuỗi SĐT thô (ví dụ: '0931142873', '+84 903.976.359', '0394251493/0984131254').

    Returns:
        Optional[str]: Chuỗi 1 SĐT hoặc nhiều SĐT ngăn cách bởi `' | '`.
    """
    if not raw_phone:
        return None
    stripped = str(raw_phone).strip()
    if not stripped:
        return None
    if re.search(r"[|/,;]", stripped):
        phones = split_phones(stripped)
        return " | ".join(phones) if phones else None
    return _clean_single_phone(stripped)


# Danh mục âm tiết họ tên tiếng Việt phổ biến để tách các từ gõ dính liền phím (VD: 'tiếnhưng' -> 'tiến hưng')
COMMON_VIETNAMESE_SYLLABLES: frozenset[str] = frozenset({
    "nguyen", "nguyễn", "tran", "trần", "le", "lê", "pham", "phạm", "hoang", "hoàng", "huynh", "huỳnh",
    "phan", "vu", "vũ", "vo", "võ", "dang", "đặng", "bui", "bùi", "do", "đỗ", "ho", "hồ", "ngo", "ngô",
    "duong", "dương", "ly", "lý", "dao", "đào", "doan", "đoàn", "vuong", "vương", "trinh", "trịnh",
    "truong", "trương", "dinh", "đinh", "lam", "lâm", "phung", "phùng", "mai", "to", "tô", "ha", "hà",
    "luc", "lục", "ta", "tạ", "cao", "trieu", "triệu", "chau", "châu", "luong", "lương", "khuat", "khuất",
    "van", "văn", "thi", "thị", "huu", "hữu", "duc", "đức", "xuan", "xuân", "quoc", "quốc", "dinh", "đình",
    "tien", "tiến", "hung", "hưng", "hùng", "hai", "hải", "nam", "bao", "bảo", "khoa", "long",
    "tuan", "tuấn", "dung", "dũng", "minh", "thanh", "thành", "dat", "đạt", "binh", "bình", "phat", "phát",
    "luc", "lực", "anh", "tai", "tài", "thang", "thắng", "son", "sơn", "tung", "tùng", "quan", "quân",
    "quang", "phuc", "phúc", "trong", "trọng", "trung", "kien", "kiên", "viet", "việt", "cuong", "cường",
    "toan", "toàn", "ngoc", "ngọc", "chinh", "chính", "chien", "chiến", "cong", "công", "phuong", "phương",
    "thao", "thảo", "trang", "linh", "nga", "huong", "hương", "lan", "tam", "tâm", "tuyen", "tuyên", "tuyển",
    "thuan", "thuận", "tri", "trí", "hieu", "hiếu", "hien", "hiền", "hiển", "huy", "kha", "khả",
    "giang", "hiep", "hiệp", "nhan", "nhân", "phong", "quy", "quý", "thuc", "thực", "diep", "diệp",
    "vi", "vĩ", "hoa", "hòa", "huynh", "bien", "biên", "thoai", "thoại", "duan", "duẩn", "duân",
    "tu", "tú", "tư", "loc", "lộc", "khanh", "khánh", "cuong", "sang", "sáng", "thinh", "thịnh",
})


def _split_syllables_recursive(w_low: str, extra_syllables: Optional[frozenset[str]] = None) -> list[str]:
    """Tách đệ quy âm tiết tiếng Việt bị viết dính liền thành từng từ độc lập."""
    vocab = COMMON_VIETNAMESE_SYLLABLES | extra_syllables if extra_syllables else COMMON_VIETNAMESE_SYLLABLES
    if not w_low:
        return []
    if len(w_low) < 4 or w_low in vocab:
        return [w_low]
    for i in range(2, min(len(w_low) - 1, 8)):
        p1 = w_low[:i]
        if p1 in vocab:
            rest = _split_syllables_recursive(w_low[i:], extra_syllables)
            if rest and all(r in vocab for r in rest):
                return [p1] + rest
    return [w_low]


_DRIVER_PREFIX_PATTERN = re.compile(
    r"^(?:"
    r"(?:tên\s*lái\s*xe|ten\s*lai\s*xe|tên\s*tài\s*xế|ten\s*tai\s*xe|bác\s*tài|bac\s*tai|bactai|"
    r"tài\s*xế|tai\s*xe|taixe|tàixế|lái\s*xe|lai\s*xe|laixe|láixe|txe)\s*[:\-]?\s*"
    r"|(?:tx|lx)\s*[:\-]\s*"
    r")",
    flags=re.IGNORECASE,
)

_TRAILING_PHONE_PATTERN = re.compile(
    r"(?:sđt|sdt|đt|dt|lh|tel|điện\s*thoại|dien\s*thoai)?\s*[:\-]?\s*(?:\+?84|0)\d[\d\s.\-*xX]{7,11}[\d*xX]",
    flags=re.IGNORECASE,
)


def _strip_symbols_and_controls(text: str) -> str:
    """Loại bỏ ký tự emoji, biểu tượng đồ họa và ký tự điều khiển Unicode (giữ chữ, số và dấu câu cơ bản)."""
    cleaned_chars: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("So", "Cf", "Co", "Cs") or ch in ("\ufe0e", "\ufe0f", "\u200d"):
            cleaned_chars.append(" ")
        else:
            cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def clean_driver_name(
    raw_name: Optional[str],
    extra_syllables: Optional[frozenset[str]] = None,
) -> Optional[str]:
    """Chuẩn hóa họ tên tài xế, loại bỏ emoji/nhãn, tách âm tiết dính liền nhưng giữ nguyên dấu gốc.

    Chỉ cắt nhãn nghề nghiệp rõ ràng (`Tài xế:`, `Lái xe:`, `TX:`, `LX:`), không cắt các từ đơn
    như `anh`, `chú`, `tài` để tránh mất tên đệm/họ (VD: 'Anh Tuấn', 'Tài Linh').
    """
    if not raw_name:
        return None

    # 1. Chuẩn hóa Unicode NFC và chuyển xuống dòng/tab thành khoảng trắng
    text = unicodedata.normalize("NFC", raw_name)
    text = (
        text.replace("\\r", " ")
        .replace("\\n", " ")
        .replace("\\t", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
    )

    # 2. Loại bỏ toàn bộ emoji/biểu tượng và dấu đầu dòng đánh số
    text = _strip_symbols_and_controls(text).strip()
    text = re.sub(r"^[\-\*•\d\.)\s]+", "", text)

    # 3. Cắt nhãn nghề nghiệp rõ ràng ở đầu chuỗi (giữ an toàn tên riêng như 'Anh Tuấn', 'Tài Linh')
    text = _DRIVER_PREFIX_PATTERN.sub("", text).strip()

    # 4. Cắt SĐT hoặc nhãn SĐT bị dính kèm ở cuối chuỗi
    text = _TRAILING_PHONE_PATTERN.sub("", text)
    text = re.sub(r"\s+(?:sđt|sdt|đt|dt|lh|tel)\s*[:\-]?$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -:/,.*|\t")

    if not text or not any(ch.isalpha() for ch in text):
        return None

    expanded_words: list[str] = []
    for word in text.split():
        if not word:
            continue
        # Ưu tiên tách tên viết dính dạng CamelCase chuẩn Unicode (VD: 'VũTùngAnh' -> 'Vũ Tùng Anh', 'TịnhVănDuân' -> 'Tịnh Văn Duân')
        if word.isalpha():
            camel_split = split_camel_case_vn(word)
            if " " in camel_split:
                camel_parts = [p for p in camel_split.split() if p]
                if len(camel_parts) > 1 and all(1 <= len(p) <= 8 for p in camel_parts):
                    for cp in camel_parts:
                        if len(cp) >= 6:
                            sub_parts = _split_syllables_recursive(cp.lower(), extra_syllables)
                            if len(sub_parts) > 1:
                                expanded_words.extend(sub_parts)
                                continue
                        expanded_words.append(cp)
                    continue
        if word.isalpha() and len(word) >= 5:
            parts = _split_syllables_recursive(word.lower(), extra_syllables)
            if len(parts) > 1:
                expanded_words.extend(parts)
                continue
        expanded_words.append(word)

    return " ".join(w[0].upper() + w[1:].lower() for w in expanded_words if w)


def split_truck_plate_and_driver(
    raw_val: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Phân tách chuỗi số xe hỗn hợp thành (tên tài xế, biển số xe chuẩn).

    Hỗ trợ các định dạng thường gặp trong file điều vận hoặc tin nhắn như:
    - 'Hải 29C44541' -> ('Hải', '29C-445.41')
    - '29C-445.41 - Nguyễn Văn A' -> ('Nguyễn Văn A', '29C-445.41')
    - '15C-066.95' -> (None, '15C-066.95')
    - 'Bác tài Hải' -> ('Hải', None)

    Args:
        raw_val (Optional[str]): Chuỗi số xe đầu vào.

    Returns:
        tuple[Optional[str], Optional[str]]: (driver_name, truck_plate)
    """
    if not raw_val or not str(raw_val).strip():
        return None, None

    s = str(raw_val).strip()
    # Tìm mẫu biển số xe Việt Nam: 2 chữ số + 1-2 chữ cái + dấu gạch/chấm/cách tùy chọn + 4-5 số
    match = re.search(r"(\d{2}[A-Za-z]{1,2}\s*[-.]?\s*\d{3,5}(?:\.\d{2})?)", s)
    if match:
        plate = clean_plate(match.group(1))
        # Phần còn lại là tên tài xế (nếu có)
        driver_part = (s[:match.start()] + " " + s[match.end():]).strip(" -:/,.*|\t")
        driver = clean_driver_name(driver_part) if driver_part else None
        return driver, plate

    # Nếu không tìm thấy biển số, kiểm tra xem có phải tên tài xế thuần không
    driver = clean_driver_name(s)
    return driver, s


def mask_phone(text: Optional[str]) -> str:
    """Che 4 chữ số giữa của SĐT di động Việt Nam (ví dụ: `0903123459` -> `0903xxxx59`)."""
    if not text:
        return ""
    return re.sub(
        r"\b((?:\+?84|0)\d{2,3})\d{4}(\d{2})\b",
        lambda m: f"{'0' + m.group(1).lstrip('+84') if m.group(1).startswith(('+84', '84')) else m.group(1)}xxxx{m.group(2)}",
        str(text),
    )
