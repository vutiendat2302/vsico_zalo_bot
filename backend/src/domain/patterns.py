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
