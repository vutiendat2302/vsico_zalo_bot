"""Module Bộ Lọc Tin Rác & Thẩm Định Tín Hiệu Xe (Junk Filter & Suspect Message Buffer).

Thực hiện nhiệm vụ cốt lõi trong Phần 1:
- Phân loại độ tin cậy của tin nhắn với hàm thuần `classify_junk(text)`:
  + JUNK: Tin rỗng, chỉ emoji, xác nhận xã giao, link quảng cáo, không có tín hiệu xe.
  + SUSPECT: Chỉ có đúng 1 tín hiệu yếu (chỉ SĐT, chỉ biển số, hoặc xe thiếu cont).
  + CANDIDATE: Có số cont hợp lệ hoặc có từ 2 tín hiệu xe trở lên.
- Quản lý bộ đệm tin nhắn nghi ngờ `SuspectMessageBuffer` trong cửa sổ 30 phút (1800s):
  Tự động ghép tin sau của cùng nhà xe với tin nghi ngờ trước đó để tái thẩm định và bóc tách.
"""

import re
import time
from typing import Tuple, Dict, Any, Optional

# Danh sách cụm từ xã giao thông dụng không liên quan đến điều xe
COMMON_CHAT_PHRASES = {
    "ok", "oke", "okay", "dạ", "da", "vâng", "vang", "dạ em nhận rồi ạ",
    "da em nhan roi a", "nhận rồi", "nhan roi", "đã nhận", "da nhan",
    "cảm ơn", "cam on", "cảm ơn anh", "cam on anh", "cảm ơn em", "cam on em",
    "xin chào", "xin chao", "xin chào cả nhà", "chào cả nhà", "chao ca nha",
    "chào anh", "chao anh", "xe bên em tới chưa anh ơi?", "xe ben em toi chua anh oi?",
    "ok a", "ok anh", "da vang", "dạ vâng", "dạ a", "da a", "done", "da gui", "dạ gửi"
}


def extract_vehicle_signals(text: str) -> Dict[str, Any]:
    """Trích xuất danh mục các tín hiệu liên quan đến điều vận xe từ chuỗi tin nhắn.

    Tín hiệu được tìm kiếm bao gồm:
    - has_cont: Tồn tại chuỗi mã container dạng 4 chữ cái + 7 chữ số.
    - has_plate: Tồn tại định dạng biển kiểm soát xe cơ giới Việt Nam.
    - has_phone: Tồn tại số điện thoại di động Việt Nam (10 số).
    - has_seal: Tồn tại từ khóa niêm phong / số seal / chì.
    - has_truck_kw: Tồn tại từ khóa chỉ phương tiện vận tải (xe, đầu kéo, rơ-moóc).

    Args:
        text (str): Chuỗi văn bản tin nhắn thô.

    Returns:
        Dict[str, Any]: Từ điển chứa cờ boolean và danh sách chi tiết các tín hiệu tìm thấy.
    """
    t_clean = text.strip()
    t_low = t_clean.lower()

    # 1. Tín hiệu số Container: 4 chữ cái + 7 số (ISO 6346)
    m_cont = re.findall(r'\b[A-Za-z]{4}\d{7}\b', t_clean)

    # 2. Tín hiệu biển số xe
    m_plate = re.findall(
        r'(?:(?<=\b)|(?<=[A-Za-z]))(?<!\d)(\d{2}[A-Za-z][\dA-Za-z]?[\s\.\-]?(?:\d{4,5}|\d{3}\.\d{2}))\b',
        t_clean,
    )
    if not m_plate:
        # Nhận diện biển số đi liền sau tiền tố xe/bks
        m_plate_prefixed = re.findall(r'(?:xe|bks|bsx)\s*[:\s]*([0-9]{2}[A-Za-z][A-Za-z0-9\.\-]{3,10})', t_clean, re.I)
        if m_plate_prefixed:
            m_plate = m_plate_prefixed

    # 3. Tín hiệu số điện thoại di động Việt Nam
    m_phone = re.findall(r'(?:\+?84|0)(?:3|5|7|8|9)\d{8}\b', t_clean)
    if not m_phone:
        m_phone_labeled = re.findall(r'(?:sđt|sdt|đt|dt)\s*[:\s]*(\+?[0-9][0-9\.\s]{7,12}\d)\b', t_clean, re.I)
        if m_phone_labeled:
            m_phone = m_phone_labeled

    # 4. Tín hiệu số niêm seal / chì
    has_seal = bool(re.search(r'\b(?:seal|chì|niêm chì|chi)\b', t_low))

    # 5. Tín hiệu từ khóa phương tiện xe tải / đầu kéo
    has_truck_kw = bool(re.search(r'\b(?:xe|đầu kéo|dau keo|mooc|rơ mooc|ro mooc)\b', t_low))

    return {
        "has_cont": len(m_cont) > 0,
        "conts": m_cont,
        "has_plate": len(m_plate) > 0,
        "plates": m_plate,
        "has_phone": len(m_phone) > 0,
        "phones": m_phone,
        "has_seal": has_seal,
        "has_truck_kw": has_truck_kw,
    }


def classify_junk(text: str) -> Tuple[str, str, Dict[str, Any]]:
    """Hàm thuần phân loại tin nhắn rác, tin nghi ngờ và ứng viên xử lý (Pure Function).

    Phân chia thành 3 phân nhóm (Verdicts) chính:
    1. JUNK:
       - Tin nhắn rỗng hoặc chỉ khoảng trắng.
       - Chỉ chứa biểu tượng cảm xúc (emoji) hoặc dấu câu/ký hiệu lạ.
       - Chứa link quảng cáo, URL mạng xã hội mà không có thông tin xe.
       - Câu chào hỏi, cảm ơn, xác nhận xã giao thông thường ('ok', 'dạ', 'cảm ơn').
       - Không chứa bất kỳ tín hiệu xe nào.
       Hành động: IGNORE_CHAT, chỉ ghi log, không phản hồi nhà xe.

    2. SUSPECT:
       - Chỉ có đúng một tín hiệu điều xe yếu (chỉ có biển số, hoặc chỉ có SĐT, hoặc 'xe ...' mà thiếu cont).
       - Tuyệt đối không được bỏ sót xe.
       Hành động: MANUAL_REVIEW, gửi tin yêu cầu nhà xe bổ sung đủ thông tin và báo Admin.

    3. CANDIDATE:
       - Có số container hợp lệ về định dạng (ISO 6346), HOẶC
       - Có từ 2 tín hiệu điều xe trở lên (trong các trường: cont, biển số, SĐT, chì/seal).
       Hành động: Cho phép đi tiếp vào bộ bóc tách chuyên sâu (Parser).

    Args:
        text (str): Chuỗi nội dung tin nhắn thô từ nhà xe.

    Returns:
        Tuple[str, str, Dict[str, Any]]:
            - verdict (str): Phân loại kết quả ('JUNK', 'SUSPECT', 'CANDIDATE').
            - reason (str): Diễn giải lý do chi tiết.
            - signals (Dict[str, Any]): Các cờ tín hiệu xe trích xuất được.
    """
    signals = extract_vehicle_signals(text)
    t_clean = text.strip()
    t_low = t_clean.lower()

    # 1. Trường hợp chuỗi rỗng hoặc chỉ khoảng trắng
    if not t_clean:
        return "JUNK", "Tin nhắn rỗng", signals

    # 2. Trường hợp chỉ chứa biểu tượng cảm xúc (Emoji) hoặc ký hiệu đặc biệt
    if not re.search(r'[a-zA-Z0-9\u00C0-\u1EF9]', t_clean):
        return "JUNK", "Chỉ chứa biểu tượng hoặc ký tự đặc biệt", signals

    # 3. Trường hợp chứa liên kết URL hoặc tin quảng cáo không có thông tin xe
    if re.search(r'https?://|www\.', t_low):
        if not signals["has_cont"] and not signals["has_plate"]:
            return "JUNK", "Liên kết trang web hoặc tin nhắn quảng cáo", signals

    # 4. Trường hợp câu chào hỏi, cảm ơn, xác nhận xã giao thông thường
    # Loại bỏ dấu câu để so khớp từ khóa xã giao
    t_words = re.sub(r'[\.,\!\?\:\;\-~]', '', t_low).strip()
    if t_words in COMMON_CHAT_PHRASES:
        return "JUNK", "Xác nhận xã giao hoặc chào hỏi thông thường", signals

    # 5. Trường hợp chứa từ khóa thao tác nghiệp vụ điều hành (hủy / đổi / sửa)
    if re.search(r'\b(?:hủy|huy|xin hủy|đổi tài xế|doi tai xe|đổi xe|doi xe|sửa seal|sua seal|bổ sung seal)\b', t_low):
        return "CANDIDATE", "Chứa từ khóa nghiệp vụ điều phối chuyến xe", signals

    # 6. Phân nhóm CANDIDATE: Có số cont hợp lệ HOẶC từ 2 tín hiệu xe trở lên
    if signals["has_cont"]:
        return "CANDIDATE", "Có số container hợp lệ", signals

    # Đếm số lượng tín hiệu xe độc lập
    distinct_signals = sum([
        1 if signals["has_plate"] else 0,
        1 if signals["has_phone"] else 0,
        1 if signals["has_seal"] else 0,
        1 if (signals["has_truck_kw"] and not signals["has_plate"]) else 0,
    ])

    if distinct_signals >= 2:
        return "CANDIDATE", "Có từ 2 tín hiệu xe trở lên", signals

    # 6. Phân nhóm SUSPECT: Chỉ có đúng một tín hiệu yếu (chỉ biển số, chỉ SĐT, chỉ từ khóa xe)
    if distinct_signals == 1:
        return "SUSPECT", "Chỉ có một tín hiệu điều xe yếu, thiếu thông tin container", signals

    # 7. Mặc định: Hoàn toàn không có tín hiệu điều xe nào
    return "JUNK", "Không chứa bất kỳ tín hiệu điều xe nào", signals


class SuspectMessageBuffer:
    """Bộ đệm lưu trữ tin nhắn nghi ngờ (Suspect) theo từng nhà xe trong cửa sổ 30 phút.

    Hỗ trợ ghép nối nội dung tin nhắn nghi ngờ trước đó với tin nhắn kế tiếp từ cùng một nhà xe:
    `merged_text = f"{prev_text}\n{current_text}"`
    Giúp xử lý trọn vẹn tình huống nhà xe chia nhỏ thông tin báo xe thành 2 tin nhắn liên tiếp.
    """

    def __init__(self, ttl_seconds: float = 1800.0) -> None:
        """Khởi tạo bộ đệm với thời gian sống TTL (mặc định 30 phút = 1800s).

        Args:
            ttl_seconds (float, optional): Thời gian tồn tại của tin nhắn nghi ngờ. Mặc định là 1800.0s.
        """
        self.ttl_seconds = ttl_seconds
        self._buffer: Dict[str, Tuple[str, float]] = {}

    def record_suspect(
        self, carrier_id: str, text: str, timestamp: Optional[float] = None
    ) -> None:
        """Lưu lại tin nhắn nghi ngờ của nhà xe vào bộ đệm.

        Args:
            carrier_id (str): Mã định danh nhà xe.
            text (str): Nội dung tin nhắn nghi ngờ.
            timestamp (Optional[float], optional): Mốc thời gian tiếp nhận (Unix epoch).
        """
        ts = timestamp if timestamp is not None else time.time()
        self._buffer[carrier_id] = (text, ts)

    def get_merged_if_recent(
        self, carrier_id: str, new_text: str, current_time: Optional[float] = None
    ) -> Optional[str]:
        """Kiểm tra và ghép nối tin nhắn mới với tin nghi ngờ trước đó nếu còn trong thời hạn 30 phút.

        Args:
            carrier_id (str): Mã định danh nhà xe.
            new_text (str): Nội dung tin nhắn mới gửi đến.
            current_time (Optional[float], optional): Mốc thời gian hiện tại.

        Returns:
            Optional[str]: Nội dung ghép nối nếu còn trong hạn 30 phút, ngược lại trả về None.
        """
        if carrier_id not in self._buffer:
            return None

        prev_text, prev_time = self._buffer[carrier_id]
        now = current_time if current_time is not None else time.time()

        if now - prev_time <= self.ttl_seconds:
            return f"{prev_text}\n{new_text}"

        # Đã quá thời hạn 30 phút -> Xóa bỏ tin cũ
        del self._buffer[carrier_id]
        return None

    def clear(self, carrier_id: str) -> None:
        """Xóa bỏ bản ghi nghi ngờ của nhà xe khi đã xử lý thành công hoặc hết hạn.

        Args:
            carrier_id (str): Mã định danh nhà xe cần xóa.
        """
        self._buffer.pop(carrier_id, None)

    def reset(self) -> None:
        """Xóa sạch toàn bộ bộ đệm (phục vụ môi trường kiểm thử)."""
        self._buffer.clear()
