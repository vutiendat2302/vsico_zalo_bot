"""Module Tiền Xử Lý Văn Bản Tin Nhắn (Message Text Preprocessing).

Thực hiện các thao tác làm sạch chuỗi ký tự ban đầu:
- Chuẩn hóa mã hóa Unicode theo định dạng dựng sẵn NFC.
- Đồng nhất ký tự ngắt dòng (\r\n -> \n).
- Trích xuất thông tin chung ở phần tiêu đề tin nhắn (loại hàng, ngày giờ thực hiện).
"""

import unicodedata
import re
from typing import Dict, Optional


def normalize_text(text: str) -> str:
    """Chuẩn hóa văn bản tiếng Việt sang dạng Unicode dựng sẵn (NFC) và thống nhất ngắt dòng.

    Args:
        text (str): Chuỗi văn bản thô từ tin nhắn Zalo.

    Returns:
        str: Chuỗi văn bản đã chuẩn hóa và cắt bỏ khoảng trắng thừa ở 2 đầu.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    # Chuyển đổi ký tự thoát literal \r\n, \n (nhập từ terminal CLI) thành ký tự xuống dòng thực tế
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Tự động tách các tiền tố 'xe', 'bks', 'bs', 'biển' viết dính liền với số tỉnh biển số (ví dụ: Xe15h00814 -> Xe 15h00814)
    text = re.sub(r'(?i)\b(xe|bks|bsx|bs|bien|biển|so|số)\s*([0-9]{2}[A-Za-z])', r'\1 \2', text)
    return text.strip()


def detect_header_info(full_text: str) -> Dict[str, Optional[str]]:
    """Phát hiện và bóc tách thông tin ngữ cảnh chung ở 2 dòng đầu tin nhắn.

    Thường các nhà xe sẽ gõ dòng tiêu đề chung như:
    'NHẬP HÀNG 14/10 9h' hoặc 'TRẢ HÀNG NGÀY MAI'
    sau đó mới liệt kê chi tiết từng xe ở bên dưới.

    Args:
        full_text (str): Toàn bộ nội dung tin nhắn nhà xe.

    Returns:
        Dict[str, Optional[str]]: Từ điển chứa các trường:
            - 'loai': Hướng vận chuyển trích xuất ('nhap', 'tra', 'dong').
            - 'date_str': Chuỗi ngày tháng tìm thấy (ví dụ: '14/10').
            - 'time_str': Chuỗi giờ giấc tìm thấy (ví dụ: '9h', '08:30').
    """
    first_lines = full_text.split('\n')[:2]
    header = ' '.join(first_lines).lower()
    res = {'loai': None, 'time_str': None, 'date_str': None}

    # Nhận diện hướng hàng từ từ khóa tiêu đề
    if ('nhập' in header or 'nhap' in header) and ('đóng' in header or 'dong' in header):
        res['loai'] = 'tra'
    elif 'nhập' in header or 'nhap' in header:
        res['loai'] = 'nhap'
    elif 'trả' in header or 'tra' in header:
        res['loai'] = 'tra'
    elif 'đóng' in header or 'dong' in header:
        res['loai'] = 'dong'

    # Nhận diện ngày tháng dạng DD/MM hoặc DD/MM/YYYY
    dm = re.search(r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)', header)
    if dm:
        res['date_str'] = dm.group(1)

    # Nhận diện giờ giấc dạng HH:MM hoặc HHh (ví dụ: 08:30, 9h)
    tm = re.search(r'\b([01]?\d|2[0-3])[:h][0-5]\d\b(?!\d)|\b([01]?\d|2[0-3])h\b(?!\d)', header)
    if tm:
        matched_t = tm.group(0)
        # Tránh nhầm lẫn với ngày tháng nếu regex trùng khớp
        if matched_t != res['date_str']:
            res['time_str'] = matched_t
    return res
