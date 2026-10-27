"""Module Đẩy Tin Vào Hàng Đợi (Queue Publisher).

Đóng vai trò Producer đẩy các thông điệp InboundMessage đã chuẩn hóa
vào hàng đợi FIFO (First-In, First-Out) bất đồng bộ.
"""

from queue import Queue
from typing import Any
from ...ingestion.models import InboundMessage


class QueuePublisher:
    """Bộ xuất bản thông điệp vào hàng đợi tin nhắn (Queue Publisher)."""

    def __init__(self, message_queue: Queue):
        """Khởi tạo Publisher với đối tượng hàng đợi tương ứng.

        Args:
            message_queue (Queue): Hàng đợi FIFO dùng để chứa các InboundMessage.
        """
        self.queue = message_queue

    def publish(self, message: InboundMessage) -> None:
        """Đẩy một thông điệp InboundMessage vào hàng đợi để Worker xử lý ngầm.

        Args:
            message (InboundMessage): Thông điệp đã chuẩn hóa cần xử lý.
        """
        self.queue.put(message)
