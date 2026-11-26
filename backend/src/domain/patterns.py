"""Tập hợp biểu thức chính quy chuẩn hóa chính xác cao cho thực thể vận tải container Việt Nam.

Dùng chung thống nhất trên toàn hệ thống (`TripParser`, `IntentClassifier`, `MessageSegmenter`,
`intent_router`) để loại bỏ sai lệch biên khi nhận diện biển số đầu kéo, biển rơ-moóc, số container
ISO 6346 và số điện thoại tài xế (kể cả ký tự NBSP `\\u00a0` copy từ Zalo).
"""

import re

# Mã tỉnh/thành hợp lệ Việt Nam (11-12, 14-99; loại 00-10 và 13)
_PROVINCE = r"(?:1[124-9]|[2-7]\d|8\d|9\d)"

# Ký tự phân cách nội dòng: bỏ \s để không ăn xuyên qua xuống dòng \n, thêm NBSP \u00a0 của Zalo
_SEP = r"[ \t\u00a0.\-/]"

# Phần số của biển số: 5 số (3+2) hoặc 4 số đời cũ
_DIGITS = r"(?:\d{3}[ \t\u00a0.\-]?\d{2}|\d{4})"

# Ràng buộc hậu tố biển số:
# - Không dính chữ/số liền kề (?!\w)
# - Loại số thập phân hoặc gạch nối số phía sau (?![.\-]\d) như 12345.6, 12345-6
# - Loại chuỗi số rời 1-3 chữ số phía sau ("12 345 678"), nhưng vẫn cho qua " 0912...", " 30E-...", " 20 tấn"
_TAIL = (
    r"(?!\w)"
    r"(?![.\-]\d)"
    r"(?![ \t\u00a0]\d{1,3}(?!\d)(?![ \t\u00a0]*[A-Za-zÀ-ỹ]))"
)

# 1. Biển số xe đầu kéo (loại trực tiếp seri rơ-moóc R, RM)
PLATE_REGEX = re.compile(
    rf"(?<!\w){_PROVINCE}{_SEP}{{0,3}}"
    r"(?!RM?(?![A-ZĐ]))"
    r"[A-ZĐ]{1,2}"
    rf"{_SEP}{{0,3}}{_DIGITS}{_TAIL}",
    re.IGNORECASE,
)

# 2. Biển số rơ-moóc (seri R, RM hoặc R kèm 1 chữ số phụ như 15R1)
TRAILER_PLATE_REGEX = re.compile(
    rf"(?<!\w){_PROVINCE}{_SEP}{{0,3}}"
    r"RM?\d?"
    rf"{_SEP}{{0,3}}{_DIGITS}{_TAIL}",
    re.IGNORECASE,
)

# 3. Biển số tổng hợp (gồm cả đầu kéo lẫn rơ-moóc) dùng cho kiểm tra tín hiệu phương tiện
ANY_PLATE_REGEX = re.compile(
    rf"(?<!\w){_PROVINCE}{_SEP}{{0,3}}"
    r"(?:RM?\d?|[A-ZĐ]{1,2})"
    rf"{_SEP}{{0,3}}{_DIGITS}{_TAIL}",
    re.IGNORECASE,
)

# 4. Số hiệu container chuẩn ISO 6346 (3 chữ chủ sở hữu + U/J/Z + đúng 7 chữ số)
CONT_REGEX = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Z]{3}[UJZ]"
    r"[ \t\u00a0.\-]{0,2}"
    r"\d(?:[ \t\u00a0.\-]{0,2}\d){6}"
    r"(?![A-Za-z0-9])"
    r"(?![ \t\u00a0.\-]{0,2}\d)",
    re.IGNORECASE,
)

# 5. Số điện thoại Việt Nam chuẩn 10 ký tự (+84/84/0 + đúng 9 ký tự số hoặc ký tự che x/X/*)
PHONE_PATTERN = re.compile(
    r"(?<![\w+])"
    r"(?:\+?84|0)"
    r"(?:[ \t\u00a0.\-]?[\dxX*]){9}"
    r"(?![\dxX*])(?![.\-]\d)"
)

# 6. Số điện thoại di động bị thiếu/thừa 1 chữ số (đầu 03/05/07/08/09, 8-9 hoặc 11 số) để bắt lỗi nhắc nhà xe
PHONE_MALFORMED_REGEX = re.compile(
    r"(?<![\w+])"
    r"(?:\+?84[ \t\u00a0.\-]?|0)[35789]"
    r"(?:[ \t\u00a0.\-]?\d){6,9}"
    r"(?![\dxX*])(?![.\-]\d)"
)

# Bảng chữ cái hoa/thường tiếng Việt chuẩn Unicode NFC (tránh dải `[A-ZÀ-Ỹ]` bị lẫn chữ thường như `â`, `ă`, `đ`, `ê`, `ô`, `ơ`, `ư`)
VN_UPPER_CLASS = "A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ"
VN_LOWER_CLASS = "a-zàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
VN_LETTER_CLASS = VN_UPPER_CLASS + VN_LOWER_CLASS
_CAMEL_BOUNDARY_RE = re.compile(rf"(?<=[{VN_LOWER_CLASS}])(?=[{VN_UPPER_CLASS}])")


def split_camel_case_vn(text: str) -> str:
    """Tách ranh giới chữ thường -> chữ hoa tiếng Việt chuẩn Unicode (VD: 'TịnhVănDuân' -> 'Tịnh Văn Duân')."""
    if not text:
        return ""
    return _CAMEL_BOUNDARY_RE.sub(" ", text)


_URL_PROTECT_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DEGLUE_ORDER_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])((?i:RO|LO)\d{3,6})"
    rf"(?=(?i:xe|bks|bsx|mooc|rm|cont|cntr|container|tài|tai|lái|lai|txe|tx|lx|s+d+đ*t+|s+đ+t+|d+t+|đ+t+|seal|chì|chi)|[{VN_UPPER_CLASS}][{VN_LOWER_CLASS}])"
)
_DEGLUE_VEHICLE_PREFIX_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?i:(rơ\s*moóc|ro\s*mooc|biển\s*số|bien\s*so|mooc|rm|xe|bks|bsx|bs|biển|bien|số|so))(?={_PROVINCE}[A-Za-zĐđ])"
)
_DEGLUE_LETTER_BEFORE_PLATE_RE = re.compile(
    rf"([{VN_LETTER_CLASS}]+)"
    rf"({_PROVINCE}(?i:RM?\d?|[A-ZĐ]{{1,2}})(?:[.\-]?\d{{3}}[.\-]?\d{{2}}|[.\-]?\d{{4}})(?!\d))"
)
_DEGLUE_PLATE_BEFORE_CONT_RE = re.compile(
    rf"((?<![A-Za-z0-9]){_PROVINCE}(?i:RM?\d?|[A-ZĐ]{{1,2}})(?:[.\-]?\d{{3}}[.\-]?\d{{2}}|[.\-]?\d{{4}}))"
    r"(?=(?i:[A-Z]{3}[UJZ])\d{3,9}(?!\d))"
)
_DEGLUE_PLATE_BEFORE_TAIL_RE = re.compile(
    rf"((?<![A-Za-z0-9]){_PROVINCE}(?i:RM?\d?|[A-ZĐ]{{1,2}})(?:[.\-]?\d{{3}}[.\-]?\d{{2}}|[.\-]?\d{{4}}))"
    r"(?=(?i:tài\s*xế|tai\s*xe|taixe|tàixế|lái\s*xe|lai\s*xe|laixe|láixe|bác\s*tài|bac\s*tai|bactai|"
    r"txe|tx|lx|tài|tai|s+d+đ*t+|s+đ+t+|d+t+|đ+t+|tel|lh|hl|mooc|rm|cont|cntr|container|công|cong|seal|chì|chi)"
    rf"|(?:\+?84|0)[35789]\d{{6,10}}(?!\d)|[{VN_UPPER_CLASS}][{VN_LOWER_CLASS}])"
)
_DEGLUE_CONT_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(?i:(container|cntr|cont|công|cong))(?=(?i:[A-Z]{3}[UJZ])\d{3,9}(?!\d))"
)
_DEGLUE_CONT_BEFORE_TAIL_RE = re.compile(
    r"((?<![A-Za-z0-9])(?i:[A-Z]{3}[UJZ])\d{3,9})"
    r"(?=(?i:s+d+đ*t+|s+đ+t+|d+t+|đ+t+|tel|lh|hl|xe|bks|mooc|rm|tài|tai|lái|lai|txe|tx|lx|seal|chì|chi)"
    rf"|(?:\+?84|0)[35789]\d{{6,10}}(?!\d)|[{VN_UPPER_CLASS}][{VN_LOWER_CLASS}])"
)
_DEGLUE_PHONE_LABEL_ANY_LEN_RE = re.compile(
    rf"(?<![{VN_LETTER_CLASS}0-9])(?i:(s+d+đ*t+|s+đ+t+|d+t+|đ+t+|tel|lh|hl|zalo|phone|call))"
    r"((?:\+?84|0)[35789](?:[.\-]?\d){6,10})(?![\dxX*])"
)
_DEGLUE_ALPHA_BEFORE_PHONE_RE = re.compile(
    rf"([{VN_LETTER_CLASS}]+)((?:\+?84|0)[35789](?:[.\-]?\d){{8}})(?![\dxX*])"
)
_DEGLUE_PHONE_BEFORE_ALPHA_RE = re.compile(
    rf"((?<![\dA-Za-z])(?:\+?84|0)[35789]\d{{8}})(?=[{VN_LETTER_CLASS}])"
)
_DEGLUE_MALFORMED_PHONE_BEFORE_TAIL_RE = re.compile(
    rf"((?<![\dA-Za-z])(?:\+?84|0)[35789]\d{{6,10}})"
    rf"(?=[{VN_UPPER_CLASS}][{VN_LOWER_CLASS}]|(?i:xe|bks|mooc|rm|cont|cntr|container|tài|tai|lái|lai|txe|tx|lx|seal|chì|chi))"
)
_DEGLUE_LONG_DRIVER_LABEL_RE = re.compile(
    rf"(?<![{VN_LETTER_CLASS}0-9])(?i:(tên\s*tài\s*xế|ten\s*tai\s*xe|tên\s*lái\s*xe|ten\s*lai\s*xe|"
    r"tài\s*xế|tai\s*xe|taixe|tàixế|lái\s*xe|lai\s*xe|laixe|láixe|bác\s*tài|bac\s*tai|bactai|txe))"
    rf"(?=[{VN_UPPER_CLASS}][{VN_LOWER_CLASS}])"
)
_DEGLUE_SHORT_DRIVER_LABEL_RE = re.compile(
    rf"(?<![{VN_LETTER_CLASS}0-9])(?i:(tài|tai|tx|lx))"
    rf"(?=[{VN_UPPER_CLASS}][{VN_LOWER_CLASS}]{{1,7}}(?:[{VN_UPPER_CLASS}][{VN_LOWER_CLASS}]{{1,7}}){{1,3}}(?![{VN_LOWER_CLASS}]))"
)
_NON_PHONE_PREFIXES: frozenset[str] = frozenset(
    {"cccd", "cmnd", "seal", "chi", "chì", "bk", "booking", "bl", "bill"}
)
_NON_PLATE_DOC_PREFIXES: frozenset[str] = frozenset(
    {"cccd", "cmnd", "seal", "chi", "chì", "bk", "booking", "bl", "bill", "vs", "hl", "ro", "lo", "dr"}
)


def _split_alpha_before_phone(match: re.Match[str]) -> str:
    """Chèn dấu cách trước SĐT 10 số khi dính sau chữ cái, bỏ qua tiền tố CCCD/CMND/Seal/Booking."""
    prefix = match.group(1)
    low = prefix.lower()
    if low in _NON_PHONE_PREFIXES or low.endswith(("cccd", "cmnd", "seal")):
        return match.group(0)
    return f"{prefix} {match.group(2)}"


def _split_letter_before_plate(match: re.Match[str]) -> str:
    """Chèn dấu cách giữa chữ cái và biển số xe/moóc viết dính (VD: 'VũTùngAnh29C44719' -> 'VũTùngAnh 29C44719')."""
    prefix = match.group(1)
    low = prefix.lower()
    if low in _NON_PLATE_DOC_PREFIXES or low.endswith(("cccd", "cmnd", "seal", "booking", "bill")):
        return match.group(0)
    return f"{prefix} {match.group(2)}"


def deglue_transport_entities(text: str) -> str:
    """Tách ranh giới an toàn cho các thực thể vận tải viết dính liền (biển số, moóc, cont, SĐT, mã lệnh, nhãn tài xế).

    Bảo toàn URL, chuỗi CCCD/Seal, mã container thiếu/thừa số (giữ nguyên toàn bộ chữ số để Validator báo sai)
    và các từ tiếng Việt thông thường.
    """
    if not text:
        return ""

    urls: list[str] = []

    def _hide_url(m: re.Match[str]) -> str:
        idx = len(urls)
        urls.append(m.group(0))
        return f" __VSICO_URL_{idx}__ "

    s = _URL_PROTECT_RE.sub(_hide_url, text)

    for _ in range(4):
        prev = s
        s = _DEGLUE_ORDER_CODE_RE.sub(r"\1 ", s)
        s = _DEGLUE_VEHICLE_PREFIX_RE.sub(r"\1 ", s)
        s = _DEGLUE_LETTER_BEFORE_PLATE_RE.sub(_split_letter_before_plate, s)
        s = _DEGLUE_PLATE_BEFORE_CONT_RE.sub(r"\1 ", s)
        s = _DEGLUE_PLATE_BEFORE_TAIL_RE.sub(r"\1 ", s)
        s = _DEGLUE_CONT_PREFIX_RE.sub(r"\1 ", s)
        s = _DEGLUE_CONT_BEFORE_TAIL_RE.sub(r"\1 ", s)
        s = _DEGLUE_PHONE_LABEL_ANY_LEN_RE.sub(r"\1 \2", s)
        s = _DEGLUE_ALPHA_BEFORE_PHONE_RE.sub(_split_alpha_before_phone, s)
        s = _DEGLUE_PHONE_BEFORE_ALPHA_RE.sub(r"\1 ", s)
        s = _DEGLUE_MALFORMED_PHONE_BEFORE_TAIL_RE.sub(r"\1 ", s)
        s = _DEGLUE_LONG_DRIVER_LABEL_RE.sub(r"\1 ", s)
        s = _DEGLUE_SHORT_DRIVER_LABEL_RE.sub(r"\1 ", s)
        if s == prev:
            break

    for idx, u in enumerate(urls):
        s = s.replace(f" __VSICO_URL_{idx}__ ", u).replace(f"__VSICO_URL_{idx}__", u)
    return s
