"""Module Quy Tắc Nghiệp Vụ Thuần Túy (Pure Business Rules).

Chứa các thuật toán kiểm tra tính hợp lệ và chuẩn hóa dữ liệu định dạng:
- Thuật toán thẩm định số kiểm tra container theo chuẩn quốc tế ISO 6346 Modulo 11.
- Chuẩn hóa biển số xe cơ giới theo quy chuẩn Cục Đăng kiểm Việt Nam.
- Chuẩn hóa số điện thoại di động Việt Nam về định dạng 10 chữ số (đầu số 0x).
- Chuẩn hóa chuỗi số niêm phong / seal hải quan.
"""

import re
from typing import Optional, Tuple, List

# Bảng trọng số quy đổi các chữ cái tiếng Anh (A-Z) sang giá trị số theo tiêu chuẩn ISO 6346
# Chú ý: Các bội số của 11 (11, 22, 33) bị loại bỏ theo quy định của tiêu chuẩn quốc tế.
CHAR_MAP = {
    'A': 10, 'B': 12, 'C': 13, 'D': 14, 'E': 15, 'F': 16, 'G': 17, 'H': 18, 'I': 19,
    'J': 20, 'K': 21, 'L': 23, 'M': 24, 'N': 25, 'O': 26, 'P': 27, 'Q': 28, 'R': 29,
    'S': 30, 'T': 31, 'U': 32, 'V': 34, 'W': 35, 'X': 36, 'Y': 37, 'Z': 38
}


def clean_container(raw: str) -> Optional[str]:
    """Loại bỏ ký tự phân cách và chuẩn hóa chuỗi số container về dạng chuẩn 11 ký tự viết hoa.

    Args:
        raw (str): Chuỗi số container thô từ tin nhắn (ví dụ: 'vsiu-739979-6' hoặc 'VSIU 7399796').

    Returns:
        Optional[str]: Chuỗi 11 ký tự viết hoa liền nhau nếu hợp lệ, ngược lại trả về None.
    """
    if not raw:
        return None
    s = re.sub(r'[^A-Za-z0-9]', '', str(raw)).upper()
    return s if len(s) == 11 else None


def validate_iso6346(cont: str) -> bool:
    """Kiểm tra tính hợp lệ của số container theo thuật toán kiểm tra Check Digit ISO 6346 Modulo 11.

    Cấu trúc container tiêu chuẩn 11 ký tự:
    - 4 chữ cái đầu: Mã chủ sở hữu và mã loại thiết bị (Owner Code & Category Identifier).
    - 6 chữ số tiếp theo: Số sê-ri của container (Serial Number).
    - Chữ số thứ 11: Số kiểm tra (Check Digit).

    Thuật toán:
    1. Mỗi ký tự từ vị trí 1 đến 10 được gán một giá trị tương ứng (chữ cái tra CHAR_MAP, chữ số giữ nguyên).
    2. Nhân giá trị từng ký tự với trọng số 2^(i), trong đó i chạy từ 0 đến 9.
    3. Tính tổng: Total = Sum(val * 2^i).
    4. Lấy phần dư: Remainder = Total % 11.
    5. Check Digit tính toán = Remainder % 10.
    6. So sánh Check Digit tính toán với chữ số thứ 11 của container.

    Args:
        cont (str): Chuỗi số container cần thẩm định (đã loại bỏ dấu cách).

    Returns:
        bool: True nếu container đúng cấu trúc và đúng số kiểm tra Modulo 11, ngược lại False.
    """
    if not cont or len(cont) != 11:
        return False
    owner_category = cont[:4]
    serial = cont[4:10]
    check_digit = cont[10]

    # Kiểm tra cấu trúc: 4 chữ cái + 6 chữ số + 1 chữ số kiểm tra
    if not (owner_category.isalpha() and serial.isdigit() and check_digit.isdigit()):
        return False

    total = 0
    for i, ch in enumerate(cont[:10]):
        # Ký tự là chữ cái thì tra bảng CHAR_MAP, là chữ số thì chuyển sang int trực tiếp
        val = CHAR_MAP[ch] if ch.isalpha() else int(ch)
        total += val * (2 ** i)

    rem = total % 11
    calc_digit = rem % 10
    return calc_digit == int(check_digit)


def clean_plate(raw: str) -> Optional[str]:
    """Chuẩn hóa biển số xe cơ giới Việt Nam về dạng tiêu chuẩn có dấu gạch nối (ví dụ: '15H-12303').

    Loại bỏ khoảng trắng, dấu chấm, dấu gạch thừa và chuẩn hóa định dạng
    biển số xe tải / xe đầu kéo theo quy chuẩn: [Mã tỉnh][Sê-ri]-[Số thứ tự]
    (ví dụ: '15h00814' -> '15H-00814', '15C-878.99' -> '15C-87899', '15C17066' -> '15C-17066').

    Args:
        raw (str): Chuỗi biển số thô trích xuất từ tin nhắn.

    Returns:
        Optional[str]: Chuỗi biển số xe viết hoa đã chuẩn hóa có dạng XXY-ZZZZ(Z) nếu hợp lệ, ngược lại None.
    """
    if not raw:
        return None
    s = re.sub(r'[\s\.\-]', '', str(raw)).upper()
    # Kiểm tra định dạng cơ bản: 2 chữ số tỉnh + 1-2 chữ cái sê-ri + 4-5 chữ số thứ tự
    m = re.match(r'^([0-9]{2}[A-Z]{1,2})([0-9]{4,5})$', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return s if len(s) >= 7 else None


def clean_phone(raw: str) -> Optional[str]:
    """Chuẩn hóa số điện thoại di động Việt Nam về định dạng 10 chữ số tiêu chuẩn.

    Hỗ trợ chuyển đổi mã quốc gia +84 sang số 0 đầu, loại bỏ các ký tự phân cách
    như dấu chấm, dấu cách, dấu gạch ngang (ví dụ: '+84 903.976.359' -> '0903976359').

    Args:
        raw (str): Chuỗi số điện thoại thô trích xuất từ tin nhắn.

    Returns:
        Optional[str]: Chuỗi 10 chữ số bắt đầu bằng '0' nếu hợp lệ, ngược lại None.
    """
    if not raw:
        return None
    digits = re.sub(r'\D', '', str(raw))
    # Chuyển đổi đầu số quốc tế 84 sang đầu số nội địa 0
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if len(digits) == 10 and digits.startswith("0") else None


def clean_seal(raw: str) -> Optional[str]:
    """Chuẩn hóa số niêm chì / seal hải quan của hãng tàu.

    Loại bỏ các khoảng trắng thừa ở hai đầu chuỗi.

    Args:
        raw (str): Chuỗi số seal thô từ tin nhắn.

    Returns:
        Optional[str]: Chuỗi seal đã cắt gọn nếu không rỗng, ngược lại None.
    """
    if not raw:
        return None
    s = str(raw).strip()
    return s if s else None


# Danh mục âm tiết phổ biến trong họ, tên đệm và tên người Việt Nam
COMMON_VIETNAMESE_SYLLABLES = {
    'nguyen', 'nguyễn', 'tran', 'trần', 'le', 'lê', 'pham', 'phạm', 'hoang', 'hoàng', 'huynh', 'huỳnh',
    'phan', 'vu', 'vũ', 'vo', 'võ', 'dang', 'đặng', 'bui', 'bùi', 'do', 'đỗ', 'ho', 'hồ', 'ngo', 'ngô',
    'duong', 'dương', 'ly', 'lý', 'dao', 'đào', 'doan', 'đoàn', 'vuong', 'vương', 'trinh', 'trịnh',
    'truong', 'trương', 'dinh', 'đinh', 'lam', 'lâm', 'phung', 'phùng', 'mai', 'to', 'tô', 'ha', 'hà',
    'luc', 'lục', 'ta', 'tạ', 'cao', 'trieu', 'triệu', 'chau', 'châu', 'luong', 'lương', 'khuat', 'khuất',
    'van', 'văn', 'thi', 'thị', 'huu', 'hữu', 'duc', 'đức', 'dinh', 'đình', 'xuan', 'xuân', 'quoc', 'quốc',
    'tien', 'tiến', 'hung', 'hưng', 'hung', 'hùng', 'hai', 'hải', 'nam', 'bao', 'bảo', 'khoa', 'long',
    'tuan', 'tuấn', 'dung', 'dũng', 'minh', 'thanh', 'thành', 'dat', 'đạt', 'binh', 'bình', 'phat', 'phát',
    'luc', 'lực', 'anh', 'tai', 'tài', 'thang', 'thắng', 'son', 'sơn', 'tung', 'tùng', 'quan', 'quân',
    'quang', 'phuc', 'phúc', 'trong', 'trọng', 'trung', 'kien', 'kiên', 'viet', 'việt', 'cuong', 'cường',
    'toan', 'toàn', 'ngoc', 'ngọc', 'chinh', 'chính', 'chien', 'chiến', 'cong', 'công', 'phuong', 'phương',
    'thao', 'thảo', 'trang', 'linh', 'nga', 'huong', 'hương', 'lan', 'tam', 'tâm', 'tuyen', 'tuyên',
    'thuan', 'thuận', 'tri', 'trí', 'hieu', 'hiếu', 'hien', 'hiền', 'huy', 'hien', 'hiển', 'kha', 'khả',
    'giang', 'hiep', 'hiệp', 'nhan', 'nhân', 'phong', 'quy', 'quý', 'thuc', 'thực', 'diep', 'diệp'
}


def _split_syllables_recursive(w_low: str) -> List[str]:
    """Tách đệ quy từ ghép tiếng Việt viết dính liền thành các âm tiết độc lập.

    Sử dụng giải thuật quay lui (backtracking) đối chiếu với từ điển âm tiết phổ biến tiếng Việt.
    Hỗ trợ bóc tách các trường hợp gõ dính phím/thiếu khoảng trắng như:
    - 2 âm tiết: 'tiếnhưng' -> ['tiến', 'hưng']
    - 3 âm tiết: 'phạmtiếnhưng' -> ['phạm', 'tiến', 'hưng']

    Args:
        w_low (str): Cụm từ hoặc chuỗi ký tự chữ thường cần phân rã.

    Returns:
        List[str]: Danh sách các âm tiết hợp lệ đã bóc tách, hoặc [w_low] nếu không khớp từ điển.
    """
    if not w_low:
        return []
    if len(w_low) < 4 or w_low in COMMON_VIETNAMESE_SYLLABLES:
        return [w_low]
    for i in range(2, min(len(w_low) - 1, 8)):
        p1 = w_low[:i]
        if p1 in COMMON_VIETNAMESE_SYLLABLES:
            rest = _split_syllables_recursive(w_low[i:])
            if rest and all(r in COMMON_VIETNAMESE_SYLLABLES for r in rest):
                return [p1] + rest
    return [w_low]


def clean_driver_name(raw: str) -> Optional[str]:
    """Chuẩn hóa họ tên tài xế: viết hoa chữ cái đầu mỗi từ (Title Case) và tách từ dính liền.

    Quy trình chuẩn hóa:
    1. Loại bỏ các danh xưng, đại từ hoặc chức danh đứng trước: 'anh', 'chị', 'bác', 'chú', 'em', 'tx', 'tài xế', 'lái xe'.
    2. Tách các ký tự phân cách như gạch chéo (/), gạch nối (-), dấu phẩy (,).
    3. Tự động nhận diện và phân rã các âm tiết tiếng Việt bị gõ dính liền do thiếu phím cách (ví dụ: 'tiếnhưng' -> 'tiến hưng').
    4. Viết hoa chữ cái đầu tiên của từng từ (Title Case) (ví dụ: 'phạm tiếnhưng' -> 'Phạm Tiến Hưng').

    Args:
        raw (str): Chuỗi tên thô trích xuất từ tin nhắn văn bản.

    Returns:
        Optional[str]: Tên tài xế chuẩn hóa viết hoa nếu có từ 2 ký tự trở lên, ngược lại None.
    """
    if not raw:
        return None
    name = re.sub(
        r'^(?:anh|chị|bác|chú|em|tx|tài\s+xế|lai\s+xe|lái\s+xe)\s*[:\.]?\s*',
        '',
        str(raw).strip(),
        flags=re.I,
    )
    name = re.sub(r'[^A-Za-zÀ-ỹ\s]', ' ', name)
    words = name.split()
    expanded_words: List[str] = []
    for w in words:
        expanded = _split_syllables_recursive(w.lower())
        expanded_words.extend(expanded)

    formatted = ' '.join(w.capitalize() for w in expanded_words)
    return formatted if len(formatted) >= 2 else None

