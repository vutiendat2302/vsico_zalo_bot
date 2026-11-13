"""Bộ sinh mã định danh duy nhất Snowflake ID 64-bit cho toàn hệ thống VSICO.

Tuân thủ quy chuẩn khóa chính 64-bit dạng số nguyên lớn (BigInteger) sinh ở tầng ứng dụng,
không sử dụng AUTO_INCREMENT của MySQL (theo Mục 1.4 và Mục 3 AGENTS.md).

Cấu trúc 64 bit:
- 1 bit dấu (luôn = 0)
- 41 bit: Dấu thời gian tính bằng mili-giây (khoảng 69 năm tính từ EPOCH)
- 5 bit: Datacenter ID (0 - 31)
- 5 bit: Worker ID (0 - 31)
- 12 bit: Sequence number (0 - 4095 trong cùng 1 mili-giây)
"""

import threading
import time

from src.config.settings import settings


class SnowflakeGenerator:
    """Bộ sinh mã Snowflake 64-bit an toàn trong môi trường đa luồng."""

    def __init__(
        self,
        datacenter_id: int | None = None,
        worker_id: int | None = None,
        epoch_ms: int | None = None,
    ) -> None:
        """Khởi tạo cấu hình bộ sinh Snowflake.

        Args:
            datacenter_id: Mã trung tâm dữ liệu (0-31).
            worker_id: Mã máy chủ xử lý (0-31).
            epoch_ms: Mốc thời gian gốc tính bằng mili-giây.
        """
        self.datacenter_id = (
            datacenter_id
            if datacenter_id is not None
            else getattr(settings, "SNOWFLAKE_DATACENTER_ID", 1)
        )
        self.worker_id = (
            worker_id
            if worker_id is not None
            else getattr(settings, "SNOWFLAKE_WORKER_ID", 1)
        )
        self.epoch_ms = (
            epoch_ms
            if epoch_ms is not None
            else getattr(settings, "SNOWFLAKE_EPOCH_MS", 1704067200000)
        )

        self._sequence = 0
        self._last_timestamp = -1
        self._lock = threading.Lock()

    def _current_timestamp(self) -> int:
        """Lấy dấu thời gian hiện tại tính bằng mili-giây."""
        return int(time.time() * 1000)

    def _wait_next_millis(self, last_timestamp: int) -> int:
        """Chờ cho đến khi chuyển sang mili-giây tiếp theo nếu tràn dãy số."""
        timestamp = self._current_timestamp()
        while timestamp <= last_timestamp:
            timestamp = self._current_timestamp()
        return timestamp

    def generate(self) -> int:
        """Sinh một mã định danh duy nhất Snowflake ID 64-bit.

        Returns:
            int: Số nguyên 64-bit không trùng lặp.
        """
        with self._lock:
            timestamp = self._current_timestamp()

            if timestamp < self._last_timestamp:
                # Hệ thống bị chỉnh lùi đồng hồ, chờ đồng hồ đuổi kịp
                timestamp = self._wait_next_millis(self._last_timestamp)

            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & 0xFFF  # 12 bit (4095)
                if self._sequence == 0:
                    timestamp = self._wait_next_millis(self._last_timestamp)
            else:
                self._sequence = 0

            self._last_timestamp = timestamp

            # Dịch bit và kết hợp
            snowflake_id = (
                ((timestamp - self.epoch_ms) << 22)
                | ((self.datacenter_id & 0x1F) << 17)
                | ((self.worker_id & 0x1F) << 12)
                | (self._sequence & 0xFFF)
            )
            return snowflake_id


# Thực thể Singleton dùng chung cho toàn bộ ứng dụng
snowflake = SnowflakeGenerator()
