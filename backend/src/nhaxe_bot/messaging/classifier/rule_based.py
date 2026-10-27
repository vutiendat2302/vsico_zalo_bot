"""Module Phân Loại Ý Định Bằng Tập Luật (Rule-based Intent Classifier).

Thực hiện phân loại ý định dựa trên các biểu thức chính quy (Regex), từ khóa đặc trưng
và hệ thống phân cấp mức độ ưu tiên để giải quyết triệt để các trường hợp xung đột ý định.
"""

import re
from typing import List
from ...domain.enums import Intent
from .base import IntentClassifier


class RuleBasedClassifier(IntentClassifier):
    """Bộ phân loại ý định dựa trên quy tắc ưu tiên và phân tích từ khóa văn bản.

    Bảng phân cấp mức độ ưu tiên giải quyết xung đột (Conflict Resolution Hierarchy):
    1. CANCEL_REQUEST (Ưu tiên cao nhất: Báo hủy chuyến luôn thắng các intent khác).
    2. UPDATE_REQUEST (Báo đổi tài xế, đổi xe, sửa số seal).
    3. ASK_WHICH_CONT (Có từ khóa sửa/đổi nhưng thiếu cả số cont và biển số xe).
    4. SUPPLEMENT (Bổ sung seal/giờ cho chuyến đang chờ).
    5. MANUAL_REVIEW (Báo tiến độ giao hàng: đã hạ, đã giao xong).
    6. IGNORE_CHAT (Tin nhắn chào hỏi thông thường: ok, dạ vâng).
    7. PARSE (Mặc định: Tin nhắn báo xe hợp lệ cần trích xuất thông tin).
    """

    def classify(self, text: str, conts: List[str]) -> Intent:
        """Phân loại ý định từ nội dung tin nhắn theo thứ tự ưu tiên nghiệp vụ.

        Args:
            text (str): Chuỗi văn bản tin nhắn thô.
            conts (List[str]): Danh sách các số container tìm thấy sơ bộ trong tin nhắn.

        Returns:
            Intent: Loại ý định nghiệp vụ được xác định.
        """
        t_clean = text.strip()
        t_low = t_clean.lower()

        # 1. Chat thông thường (câu chào hỏi ngắn, tán ngẫu)
        if t_low in ["dạ em nhận rồi ạ", "ok", "xe bên em tới chưa anh ơi?"]:
            return Intent.IGNORE_CHAT

        # 2. Cập nhật tiến độ giao nhận (cần nhân viên xem xét thủ công)
        if any(k in t_low for k in ["trả xong rồi", "đã trả xong", "giao xong", "đã hạ"]):
            return Intent.MANUAL_REVIEW

        # 3. Yêu cầu hủy chuyến (Ưu tiên cao nhất - Thắng mọi trường hợp khác kể cả có cont)
        if (
            t_low.startswith("hủy cont")
            or "hủy cont" in t_low
            or "hủy chuyến" in t_low
            or "xin hủy" in t_low
        ):
            return Intent.CANCEL_REQUEST

        # 4. Bổ sung seal cho chuyến xe đang ở trạng thái chờ
        if t_low.startswith("seal cont") or t_low.startswith("chì cont"):
            return Intent.SUPPLEMENT

        # 5. Sửa số seal của chuyến đã gửi
        if "sửa seal cont" in t_low or "sua seal cont" in t_low:
            return Intent.UPDATE_REQUEST

        # 6. Đổi tài xế hoặc đổi xe
        if any(k in t_low for k in ["đổi tài xế", "doi tai xe", "đổi xe", "doi xe"]):
            m_cont = re.search(r'\b([A-Za-z]{4}\d{7})\b', t_clean)
            m_plate = re.search(
                r'\b(\d{2}[A-Za-z][\dA-Za-z]?[\s\.\-]?(?:\d{4,5}|\d{3}\.\d{2}))\b', t_clean
            )
            # Nếu báo đổi nhưng không chỉ rõ số cont và không có biển số để tra ngược
            if not m_cont and not m_plate:
                return Intent.ASK_WHICH_CONT
            return Intent.UPDATE_REQUEST

        # 7. Sửa/đổi thông tin chung chung nhưng không rõ đổi cho xe nào
        if any(k in t_low for k in ["sửa", "sua", "đổi", "doi", "thay", "cập nhật"]):
            if not conts and not re.search(r'\b\d{2}[A-Za-z]\d{4,5}\b', t_clean):
                return Intent.ASK_WHICH_CONT

        # 8. Mặc định: Phân tích bóc tách tin nhắn báo xe mới
        return Intent.PARSE
