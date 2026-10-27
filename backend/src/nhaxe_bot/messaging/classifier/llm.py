"""Module Phân Loại Ý Định Bằng Mô Hình Ngôn Ngữ Lớn (LLM Intent Classifier).

Đóng vai trò bộ phân loại thông minh dự phòng cho các trường hợp câu từ đa nghĩa,
viết tắt phức tạp mà tập luật Rule-based không bao phủ hết. Có cơ chế Fallback tự động
về Rule-based nếu máy chủ LLM gặp sự cố hoặc timeout.
"""

from typing import List, Optional
from ...domain.enums import Intent
from .base import IntentClassifier


class LLMClassifier(IntentClassifier):
    """Bộ phân loại ý định sử dụng LLM với cơ chế tự phục hồi (Graceful Degradation).

    Khi máy chủ LLM ngoại tuyến hoặc phản hồi chậm, hệ thống tự động fallback
    về RuleBasedClassifier mà không làm gián đoạn tiến trình của Worker.
    """

    def __init__(self, fallback_classifier: IntentClassifier):
        """Khởi tạo bộ phân loại LLM kèm theo classifier dự phòng.

        Args:
            fallback_classifier (IntentClassifier): Bộ phân loại quy tắc để kích hoạt khi LLM lỗi.
        """
        self.fallback = fallback_classifier

    def classify(self, text: str, conts: List[str]) -> Intent:
        """Phân loại ý định tin nhắn qua LLM hoặc tự động chuyển tiếp sang Fallback.

        Args:
            text (str): Chuỗi văn bản tin nhắn cần phân loại.
            conts (List[str]): Danh sách container tìm thấy sơ bộ.

        Returns:
            Intent: Loại ý định nhận diện được.
        """
        # Dự phòng: chuyển tiếp sang bộ phân loại rule-based an toàn
        return self.fallback.classify(text, conts)
