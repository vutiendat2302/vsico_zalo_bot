"""Module Giao Diện Phân Loại Ý Định (Intent Classifier Base Interface).

Định nghĩa interface trừu tượng cho tất cả các bộ phân loại ý định (Rule-based, LLM).
"""

from abc import ABC, abstractmethod
from typing import List
from ...domain.enums import Intent


class IntentClassifier(ABC):
    """Giao diện trừu tượng cho bộ phân loại ý định (Intent Classifier)."""

    @abstractmethod
    def classify(self, text: str, conts: List[str]) -> Intent:
        """Phân tích nội dung tin nhắn và xác định loại ý định nghiệp vụ (Intent).

        Args:
            text (str): Chuỗi văn bản tin nhắn của nhà xe cần phân loại.
            conts (List[str]): Danh sách các số container đã bóc tách sơ bộ từ văn bản.

        Returns:
            Intent: Loại ý định nghiệp vụ tương ứng (PARSE, UPDATE_REQUEST, CANCEL_REQUEST, ...).
        """
        pass
