"""Module Lớp Cơ Sở Handler (Use Case Base Handler).

Định nghĩa interface trừu tượng cho mọi nghiệp vụ Use Case xử lý Intent.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from ..ingestion.models import InboundMessage


class BaseHandler(ABC):
    """Lớp cơ sở trừu tượng cho mọi Use Case / Intent Handler trong hệ thống."""

    @abstractmethod
    def handle(self, inbound: InboundMessage, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi logic nghiệp vụ cụ thể cho thông điệp tiếp nhận.

        Args:
            inbound (InboundMessage): Thông điệp nội bộ đã qua bước Ingestion.
            context (Dict[str, Any]): Dữ liệu ngữ cảnh bổ sung (cấu hình, metadata).

        Returns:
            List[Dict[str, Any]]: Danh sách các kết quả xử lý của các xe trong tin nhắn.
        """
        pass
