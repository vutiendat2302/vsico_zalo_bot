"""Module Chống Trùng Lặp Tin Nhắn (Message Deduplication & Idempotency).

Đảm bảo tính bất biến (Idempotent) của toàn bộ hệ thống xử lý tin nhắn:
Một tin nhắn có cùng msg_id chỉ được phép tiếp nhận và xử lý đúng một lần duy nhất,
ngăn chặn spam thông báo gửi cho khách hàng và sai lệch số liệu chuyến xe.
"""

from typing import Set


class Deduplicator:
    """Bộ lọc phát hiện và ngăn chặn tin nhắn gửi trùng lặp theo msg_id.

    Sử dụng cấu trúc tập hợp (Set) trong bộ nhớ để lưu vết các msg_id đã duyệt qua.
    """

    def __init__(self):
        """Khởi tạo bộ lọc chống trùng với tập hợp rỗng."""
        self._seen_msg_ids: Set[str] = set()

    def is_duplicate(self, msg_id: str) -> bool:
        """Kiểm tra xem mã định danh tin nhắn (msg_id) đã từng xuất hiện hay chưa.

        Args:
            msg_id (str): Mã định danh tin nhắn cần kiểm tra.

        Returns:
            bool: True nếu msg_id đã tồn tại trong danh sách đã duyệt (bị trùng), ngược lại False.
        """
        if not msg_id:
            return False
        return msg_id in self._seen_msg_ids

    def mark_seen(self, msg_id: str) -> None:
        """Ghi nhận msg_id vào danh sách đã duyệt để chặn các lần gửi lặp sau đó.

        Args:
            msg_id (str): Mã định danh tin nhắn vừa tiếp nhận thành công.
        """
        if msg_id:
            self._seen_msg_ids.add(msg_id)

    def reset(self) -> None:
        """Xóa sạch bộ nhớ đệm lưu vết msg_id (thường dùng trong Unit Test hoặc khởi động lại ca)."""
        self._seen_msg_ids.clear()
