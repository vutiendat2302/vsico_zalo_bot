"""Module Kết Nối Mô Hình Ngôn Ngữ Lớn (LLM Client).

Định nghĩa interface trừu tượng và cài đặt giả lập (FakeLLMClient)
phục vụ kiểm thử tự động mà không cần máy chủ GPU hay kết nối mạng bên ngoài.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class LLMClient(ABC):
    """Giao diện trừu tượng cho máy khách gọi mô hình ngôn ngữ lớn (LLM)."""

    @abstractmethod
    def generate(self, prompt: str) -> Optional[str]:
        """Gửi prompt tới LLM và nhận chuỗi phản hồi.

        Args:
            prompt (str): Câu lệnh chỉ dẫn văn bản cho mô hình.

        Returns:
            Optional[str]: Kết quả phản hồi từ mô hình hoặc None nếu lỗi.
        """
        pass


class FakeLLMClient(LLMClient):
    """Lớp giả lập máy khách LLM dùng cho kiểm thử tự động (Unit Test).

    Trả về phản hồi cố định (Canned Response) đã được cấu hình trước.
    """

    def __init__(self, canned_response: Optional[str] = None):
        """Khởi tạo FakeLLMClient.

        Args:
            canned_response (Optional[str]): Nội dung phản hồi được định sẵn.
        """
        self.canned_response = canned_response

    def generate(self, prompt: str) -> Optional[str]:
        """Trả về phản hồi cố định mà không cần gọi mạng.

        Args:
            prompt (str): Prompt đầu vào (bị bỏ qua trong FakeClient).

        Returns:
            Optional[str]: Chuỗi canned_response đã đăng ký.
        """
        return self.canned_response
