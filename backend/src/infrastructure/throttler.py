"""Module Điều Tiết Tốc Độ & Quản Lý Hạn Mức Tải Zalo OA (Rate Limiter & Outbound Throttler).

Bảo vệ hệ thống và tuân thủ nghiêm ngặt giới hạn tần suất gọi API của Zalo OA khi có hàng trăm,
hàng nghìn nhóm gửi tin cùng lúc:
1. Thuật toán Token Bucket kiểm soát lưu lượng gửi tin phản hồi (Outbound Rate Limiting).
2. Tự động điều chỉnh tốc độ (Backpressure & Dynamic Throttling) khi gặp lỗi 429 Too Many Requests.
3. Cung cấp số liệu thống kê thời gian thực cho Dashboard Frontend.
"""

from datetime import datetime, timezone
import threading
import time
from typing import Any

from src.observability.logging import get_logger

logger = get_logger(__name__)


class ZaloOutboundThrottler:
    """Bộ điều tiết tốc độ gửi tin nhắn ra Zalo OA theo thuật toán Token Bucket."""

    def __init__(self, max_requests_per_second: float = 10.0, burst_capacity: float = 20.0):
        """Khởi tạo bộ điều tiết tốc độ.

        Args:
            max_requests_per_second (float): Tốc độ tối đa cho phép gửi ra (mặc định 10 request/giây).
            burst_capacity (float): Dung lượng bộ đệm xung đột tối đa.
        """
        self.rate = max_requests_per_second
        self.capacity = burst_capacity
        self.tokens = burst_capacity
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

        # Thống kê giám sát
        self.total_requests = 0
        self.total_throttled = 0
        self.total_429_retries = 0
        self.backoff_until = 0.0

    def _refill(self) -> None:
        """Hồi phục số lượng token theo thời gian trôi qua."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

    def acquire(self, timeout: float = 10.0) -> bool:
        """Xin cấp quyền gửi một tin nhắn ra Zalo OA, tự động đợi nếu đang hết hạn mức.

        Args:
            timeout (float): Thời gian chờ tối đa (giây).

        Returns:
            bool: True nếu được cấp quyền, False nếu quá thời gian chờ.
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            with self._lock:
                now = time.monotonic()
                # Nếu đang trong thời gian phạt do Zalo trả về 429
                if now < self.backoff_until:
                    sleep_time = self.backoff_until - now
                else:
                    self._refill()
                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        self.total_requests += 1
                        return True
                    # Tính toán thời gian cần đợi cho đến khi có ít nhất 1 token
                    needed = 1.0 - self.tokens
                    sleep_time = needed / self.rate

            self.total_throttled += 1
            time.sleep(min(sleep_time, 0.1))

        logger.warning("Quá hạn thời gian chờ cấp quyền gửi Zalo OA (%s giây).", timeout)
        return False

    def report_rate_limit(self, retry_after: float = 2.0) -> None:
        """Ghi nhận khi máy chủ Zalo OA phản hồi mã 429 Too Many Requests để kích hoạt phạt giãn cách.

        Args:
            retry_after (float): Số giây cần giãn cách theo khuyến cáo của Zalo hoặc mặc định 2s.
        """
        with self._lock:
            self.total_429_retries += 1
            self.tokens = 0.0
            self.backoff_until = time.monotonic() + retry_after
        logger.warning("Đã chạm giới hạn Zalo OA (429)! Tự động giãn cách trong %s giây.", retry_after)

    def get_metrics(self) -> dict[str, Any]:
        """Lấy thông số giám sát hiện tại của bộ điều tiết.

        Returns:
            dict[str, Any]: Thông số trạng thái hạn mức, token còn lại, số lần điều tiết.
        """
        with self._lock:
            self._refill()
            now = time.monotonic()
            is_backed_off = now < self.backoff_until
            remaining_backoff = max(0.0, round(self.backoff_until - now, 2))

            return {
                "max_requests_per_second": self.rate,
                "burst_capacity": self.capacity,
                "available_tokens": round(self.tokens, 2),
                "is_throttled": is_backed_off or (self.tokens < 1.0),
                "is_backing_off_429": is_backed_off,
                "remaining_backoff_seconds": remaining_backoff,
                "total_requests_approved": self.total_requests,
                "total_throttled_waits": self.total_throttled,
                "total_429_hits": self.total_429_retries,
            }


# Thực thể singleton dùng chung cho toàn bộ ứng dụng
outbound_throttler = ZaloOutboundThrottler(max_requests_per_second=10.0, burst_capacity=20.0)
