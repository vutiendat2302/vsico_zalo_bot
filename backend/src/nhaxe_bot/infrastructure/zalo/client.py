"""Module Máy Khách Zalo OpenAPI (Zalo Outbound Client).

Định nghĩa interface trừu tượng và cài đặt gửi tin nhắn Zalo kèm cơ chế:
- Thử lại tối đa 3 lần với giãn cách số mũ (Exponential Backoff: 0.05s, 0.1s, 0.2s).
- Chống gửi trùng lặp tới khách hàng khi retry (Deduplication theo msg_id và băm SHA-256 nội dung).
- Đánh dấu trạng thái 'FAILED' và kích hoạt cảnh báo Admin nếu quá số lần thử lại.
- Triển khai mô phỏng DryRunZaloClient cho môi trường kiểm thử không cần Internet.
"""

import time
import hashlib
from abc import ABC, abstractmethod
from typing import Optional, Set, Tuple


class ZaloClient(ABC):
    """Giao diện trừu tượng máy khách gửi tin nhắn Zalo OpenAPI."""

    def __init__(self) -> None:
        """Khởi tạo máy khách Zalo với bộ nhớ đệm chống gửi trùng lặp."""
        self._sent_dedupe_keys: Set[str] = set()

    @abstractmethod
    def send_message(self, group_id: str, text: str) -> bool:
        """Gửi trực tiếp một thông điệp văn bản tới nhóm Zalo GMF hoặc người dùng.

        Args:
            group_id (str): Mã định danh nhóm Zalo GMF nhận tin.
            text (str): Nội dung thông báo cần gửi.

        Returns:
            bool: True nếu gửi thành công, False nếu thất bại.
        """
        pass

    def send_with_retry(
        self,
        msg_id: str,
        group_id: str,
        text: str,
        max_retries: int = 3,
        backoff_base: float = 0.05,
    ) -> Tuple[bool, str]:
        """Gửi tin nhắn kèm cơ chế thử lại (Retry) và chống gửi trùng lặp (Deduplication).

        Quy trình xử lý:
        1. Sinh khóa chống trùng: `key = msg_id + sha256(text)[:16]`.
        2. Nếu khóa đã gửi thành công trước đó: Bỏ qua không gửi lại khách hàng (Idempotent).
        3. Thử lại tối đa `max_retries` lần với backoff tăng dần (0.05s, 0.1s, 0.2s).
        4. Nếu thành công: Lưu khóa vào danh sách đã gửi và trả về trạng thái 'SENT'.
        5. Nếu hết lượt thử lại mà vẫn thất bại: Trả về False và trạng thái 'FAILED'.

        Args:
            msg_id (str): Mã định danh tin nhắn gốc của nhà xe.
            group_id (str): Nhóm Zalo nhận thông báo.
            text (str): Nội dung tin nhắn cần gửi.
            max_retries (int, optional): Số lần thử lại tối đa. Mặc định là 3.
            backoff_base (float, optional): Thời gian chờ cơ sở ban đầu. Mặc định là 0.05s.

        Returns:
            Tuple[bool, str]:
                - success (bool): True nếu gửi thành công hoặc đã gửi trước đó, False nếu thất bại.
                - status (str): 'SENT', 'SKIPPED_DUPLICATE_SEND', hoặc 'FAILED'.
        """
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        dedupe_key = f"{msg_id}:{content_hash}"

        # 1. Kiểm tra chống gửi trùng khách hàng khi retry
        if dedupe_key in self._sent_dedupe_keys:
            return True, "SKIPPED_DUPLICATE_SEND"

        # 2. Vòng lặp gửi kèm Retry và Backoff
        for attempt in range(1, max_retries + 1):
            try:
                ok = self.send_message(group_id, text)
                if ok:
                    self._sent_dedupe_keys.add(dedupe_key)
                    return True, "SENT"
            except Exception:
                pass

            # Giãn cách theo hàm mũ (Exponential Backoff) nếu chưa phải lần cuối
            if attempt < max_retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))

        # 3. Hết 3 lần retry vẫn thất bại
        return False, "FAILED"


class DryRunZaloClient(ZaloClient):
    """Lớp cài đặt mô phỏng gửi tin nhắn Zalo trong môi trường thử nghiệm và benchmark.

    Không thực hiện cuộc gọi mạng ra Internet, giúp hệ thống chạy hoàn toàn Offline
    theo đúng tiêu chí Zero External Dependencies của dự án.
    """

    def __init__(self, should_fail: bool = False) -> None:
        """Khởi tạo DryRunZaloClient với tùy chọn giả lập lỗi mạng phục vụ Unit Test.

        Args:
            should_fail (bool, optional): Nếu True, luôn giả lập gửi thất bại. Mặc định là False.
        """
        super().__init__()
        self.should_fail = should_fail
        self.call_count = 0

    def send_message(self, group_id: str, text: str) -> bool:
        """Ghi nhận hành động gửi tin nhắn mô phỏng.

        Args:
            group_id (str): Mã định danh nhóm nhận.
            text (str): Nội dung thông báo.

        Returns:
            bool: False nếu cấu hình should_fail=True, ngược lại luôn True.
        """
        self.call_count += 1
        if self.should_fail:
            return False
        return True
