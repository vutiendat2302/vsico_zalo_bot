"""Module Phân Tích Ngày Giờ Đến Kho (Vietnamese Datetime Parser).

Chịu trách nhiệm diễn giải các định dạng thời gian tự nhiên của người Việt:
- Giờ cụ thể: '08:00', '8h', '14h30', '14:00'.
- Ngày cụ thể: '14/10', '14/10/2026', '2026-10-14'.
- Nhận diện các cụm từ mập mờ, thiếu căn cứ chính xác: 'sáng mai', 'chiều nay' -> cảnh báo 'gio_mo_ho'.
- Tự động điền ngày/tháng/năm hiện tại từ thời điểm nhận tin nếu nhà xe chỉ gõ giờ.
"""

import re
from datetime import datetime
from typing import Optional, List, Tuple
from ...config.settings import TZ_VN


def parse_vietnamese_datetime(
    raw_time_str: Optional[str],
    msg_dt: datetime,
) -> Tuple[Optional[str], List[str]]:
    """Phân tích chuỗi ngày giờ đến kho dựa theo thời điểm gửi tin nhắn msg_dt (+07:00).

    Args:
        raw_time_str (Optional[str]): Chuỗi văn bản chứa thông tin giờ/ngày trích xuất từ tin nhắn.
        msg_dt (datetime): Thời điểm nhận tin nhắn (chuẩn timezone GMT+7) dùng làm mốc quy chiếu.

    Returns:
        Tuple[Optional[str], List[str]]:
            - formatted_datetime: Chuỗi ngày giờ chuẩn hóa theo định dạng 'HH:MM DD/MM/YYYY'
              hoặc None nếu thiếu hoặc không diễn giải được.
            - warnings: Danh sách cảnh báo (['thieu_gio_den'], ['gio_mo_ho']).
    """
    if not raw_time_str or not raw_time_str.strip():
        return None, ["thieu_gio_den"]

    s = raw_time_str.strip().lower()

    # Nhận diện các cụm từ mập mờ không xác định được giờ cụ thể
    if any(
        k in s
        for k in [
            'sáng mai',
            'sang mai',
            'chiều mai',
            'chieu mai',
            'trưa mai',
            'sáng nay',
            'chiều nay',
        ]
    ):
        return None, ["gio_mo_ho"]

    warnings: List[str] = []
    hour = 8
    minute = 0
    day = msg_dt.day
    month = msg_dt.month
    year = msg_dt.year
    date_specified = False
    time_specified = False

    # 1. Bóc tách giờ giấc dạng HH:MM hoặc HHhMM (ví dụ: 08:30, 8h30)
    time_m = re.search(r'\b([01]?\d|2[0-3])[:h]([0-5]\d)\b(?!\d)', s)
    if time_m:
        hour = int(time_m.group(1))
        minute = int(time_m.group(2))
        time_specified = True
    else:
        # Bóc tách giờ giấc dạng HHh (ví dụ: 9h, 14h)
        time_m2 = re.search(r'\b([01]?\d|2[0-3])h\b(?!\d)', s)
        if time_m2:
            hour = int(time_m2.group(1))
            minute = 0
            time_specified = True

    # Nếu không tìm thấy thông tin giờ cụ thể nào
    if not time_specified:
        return None, ["thieu_gio_den"]

    # 2. Bóc tách ngày tháng dạng ISO (YYYY-MM-DD)
    iso_date_m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if iso_date_m:
        year = int(iso_date_m.group(1))
        month = int(iso_date_m.group(2))
        day = int(iso_date_m.group(3))
        date_specified = True
    else:
        # Bóc tách ngày tháng dạng Việt Nam (DD/MM hoặc DD/MM/YYYY)
        dmy_m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', s)
        if dmy_m:
            day = int(dmy_m.group(1))
            month = int(dmy_m.group(2))
            if dmy_m.group(3):
                y_str = dmy_m.group(3)
                year = int(y_str) if len(y_str) == 4 else 2000 + int(y_str)
            else:
                year = msg_dt.year
            date_specified = True

    # 3. Tạo đối tượng datetime và format thành chuỗi chuẩn
    try:
        dt_res = datetime(year, month, day, hour, minute, tzinfo=TZ_VN)
        formatted_str = dt_res.strftime("%H:%M %d/%m/%Y")
        return formatted_str, warnings
    except ValueError:
        # Ngày tháng không hợp lệ (ví dụ: ngày 31 tháng 2)
        return None, ["gio_mo_ho"]
