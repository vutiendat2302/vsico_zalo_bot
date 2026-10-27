"""Module Phân Đoạn Khối Xe (Vehicle Message Segmenter).

Chịu trách nhiệm phát hiện và bóc tách các tin nhắn phức tạp chứa nhiều xe
thành các khối văn bản độc lập cho từng xe (1 tin nhắn -> n xe).
Hỗ trợ cơ chế phân đoạn 2 tầng (Two-phase Multi-vehicle Segmentation):
1. Phân đoạn vĩ mô: Phân tách theo cấu trúc xuống dòng, đánh số thứ tự (1., 2., 1), 2)).
2. Phân đoạn vi mô nội dòng (Intra-line splitting): Bóc tách các xe được viết nối tiếp nhau
   trên cùng một dòng bởi các ký tự phân cách (/, ;, ,, hoặc khoảng trắng rộng).
"""

import re
from typing import List


def _has_vehicle_signal(text: str) -> bool:
    """Kiểm tra một chuỗi văn bản có chứa tín hiệu phương tiện hay không.

    Tín hiệu hợp lệ bao gồm:
    - Định dạng số container ISO 6346 (4 chữ cái + 7 chữ số) hoặc nhãn cont.
    - Biển số xe cơ giới (đầu kéo/tải) có hoặc không có tiền tố xe/bks/bsx.

    Args:
        text (str): Đoạn văn bản cần thẩm định tín hiệu xe.

    Returns:
        bool: True nếu tìm thấy ít nhất một tín hiệu xe, ngược lại False.
    """
    return bool(
        re.search(r'\b[A-Za-z]{4}\d{7}\b', text) or
        re.search(r'(?:xe|bks|bsx|bs|số\s*xe)?\s*\b\d{2}[A-Za-z][\dA-Za-z]?[\s\.\-]?(?:\d{4,5}|\d{3}\.\d{2})\b', text, re.I) or
        re.search(r'(?:cont|số\s*cont)\s*[:\s]*[A-Za-z0-9]', text, re.I)
    )


def _split_inline_vehicles(block: str) -> List[str]:
    """Phân tách nội dòng nếu một khối văn bản chứa nhiều xe nối nhau bởi ký tự phân cách.

    Nhận diện ranh giới xe mới khi sau ký tự phân cách (/, ;, hoặc xuống dòng)
    xuất hiện dấu hiệu bắt đầu của xe tiếp theo:
    - Tiền tố xe/bks/biển kèm biển số (ví dụ: '/Xe15h00814', '/xe 15C17066').
    - Biển số xe cơ giới độc lập (ví dụ: '/ 15C-878.99', '/ 72C-64021').
    - Đánh số thứ tự mới với mọi định dạng (ví dụ: '2) 72C...', '2)72C...', '2. ...').

    Args:
        block (str): Đoạn văn bản cần kiểm tra phân tách nội dòng.

    Returns:
        List[str]: Danh sách các khối xe con sau khi tách.
    """
    pattern = (
        r'[/;]\s*(?=(?:xe|bks|bsx|bs|số\s*xe)\s*[0-9]{2}[A-Za-z]'
        r'|\b[0-9]{2}[A-Za-z][\dA-Za-z]?[\s\.\-]?(?:\d{4,5}|\d{3}\.\d{2})'
        r'|\d{1,2}[\.\)]\s*)'
        r'|(?:\n|\s+)(?=\d{1,2}[\.\)]\s*(?:(?:xe|bks|bsx|bs)?\s*\d{2}[A-Za-z]|\b\d{2}[A-Za-z]))'
    )
    parts = [p.strip() for p in re.split(pattern, block, flags=re.I) if p.strip()]
    return parts if parts else [block]


def split_vehicle_blocks(text: str) -> List[str]:
    """Tách một tin nhắn tổng hợp thành danh sách các khối văn bản riêng cho từng xe.

    Quy trình phân đoạn 2 giai đoạn (Two-phase Multi-vehicle Segmentation):
    - Giai đoạn 1 (Macro Segmentation): Phân tách theo cấu trúc dòng hoặc danh sách:
        1. Phân tách theo danh sách đánh số thứ tự (1., 2., hoặc 1), 2)), chấp nhận cả trường
           hợp viết dính liền không dấu cách (ví dụ: '2)72C...').
        2. Phân tách bằng 2 dấu xuống dòng liên tiếp (\\n\\s*\\n).
        3. Phân tách theo từng dòng độc lập nếu mỗi dòng bắt đầu bằng biển số hoặc container.
    - Giai đoạn 2 (Micro Segmentation): Quét từng khối từ Giai đoạn 1; nếu một khối vẫn chứa
      nhiều xe dính liền nhau qua dấu gạch chéo (/), chấm phẩy (;), xuống dòng (\\n) thì tiếp
      tục tách thành các khối xe con độc lập.

    Args:
        text (str): Nội dung văn bản tin nhắn thô từ nhà xe.

    Returns:
        List[str]: Danh sách các chuỗi văn bản đại diện cho từng xe riêng biệt.
    """
    # Thống nhất cả ngắt dòng thực tế lẫn ký tự thoát literal \n do nhập từ bàn phím terminal
    text_clean = text.replace("\\r\\n", "\n").replace("\\n", "\n").strip()
    if not text_clean:
        return []

    initial_blocks: List[str] = []

    # Trường hợp 1: Phân tách theo danh sách đánh số thứ tự (1), 2) hoặc 1., 2.)
    numbered_splits = [
        p.strip() for p in re.split(r'(?:^|[\n;/]|\s+)(?=\d{1,2}[\.\)]\s*)', text_clean) if p.strip()
    ]
    vehicle_numbered = [p for p in numbered_splits if _has_vehicle_signal(p)]
    if len(vehicle_numbered) >= 2:
        initial_blocks = vehicle_numbered

    # Trường hợp 2: Phân tách bằng 2 dấu xuống dòng liên tiếp
    if not initial_blocks:
        double_nl_blocks = [b.strip() for b in re.split(r'\n\s*\n', text_clean) if b.strip()]
        vehicle_double_nl = [b for b in double_nl_blocks if _has_vehicle_signal(b)]
        if len(vehicle_double_nl) >= 2:
            initial_blocks = vehicle_double_nl

    # Trường hợp 3: Từng dòng bắt đầu bằng biển số xe hoặc số container
    if not initial_blocks:
        lines = [l.strip() for l in text_clean.split('\n') if l.strip()]
        plate_or_cont_lines = []
        for l in lines:
            if re.match(r'^(?:xe\s+)?\d{2}[A-Za-z]', l, re.I) or re.match(r'^[A-Za-z]{4}\d{7}', l, re.I):
                plate_or_cont_lines.append(l)
        if len(plate_or_cont_lines) >= 2:
            initial_blocks = plate_or_cont_lines

    # Nếu không rơi vào các trường hợp trên, khối ban đầu là toàn bộ tin nhắn
    if not initial_blocks:
        initial_blocks = [text_clean]

    # Giai đoạn 2: Quét nội dòng (Intra-line splitting) cho từng khối
    final_blocks: List[str] = []
    for b in initial_blocks:
        sub_blocks = _split_inline_vehicles(b)
        final_blocks.extend(sub_blocks)

    # Lọc bỏ các khối không có thông tin xe (như dòng tiêu đề đơn lẻ)
    valid_blocks = [b for b in final_blocks if _has_vehicle_signal(b)]
    return valid_blocks if valid_blocks else [text_clean]

