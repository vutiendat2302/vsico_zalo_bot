"""Module Điều Phối & Xuất Bản Tin Nhắn Gửi Ra Zalo (Zalo Outbound Dispatcher).

Thực hiện nhiệm vụ gửi thông báo điều vận và cảnh báo nghiệp vụ tới các nhóm chat Zalo
và tài xế thông qua cầu nối HTTP `zca-js` (cổng 3000):
1. Tích hợp bộ điều tiết tốc độ Token Bucket (`outbound_throttler`) để tránh quá tải/429.
2. Gửi thông báo đến nhóm khách hàng: `POST /api/bot/send/group`.
3. Gửi tin nhắc lỗi đến tài xế: `POST /api/bot/send/user` hoặc trích dẫn `quoteMsgId`.
4. Bền bỉ và Chống sập (Resilience): Lỗi mạng hoặc Zalo offline tuyệt đối không làm gián đoạn Worker.
"""

from datetime import datetime
import json
import time
from typing import Any, Optional, Tuple
import urllib.error
import urllib.request
from uuid import uuid4

from src.config.settings import settings
from src.infrastructure.throttler import outbound_throttler
from src.observability.logging import get_logger

logger = get_logger(__name__)


class ZaloDispatcher:
    """Bộ điều phối gửi tin nhắn thời gian thực ra máy chủ Zalo."""

    @classmethod
    def send_to_group(
        cls,
        group_id: str,
        message: str,
        quote_msg_id: Optional[str] = None,
        timeout: float = 8.0,
        max_retries: int = 3,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Gửi một tin nhắn thông báo vào Nhóm Zalo đích (có thử lại tối đa 3 lần).

        Args:
            group_id (str): ID nhóm Zalo đích (VD: '6469608867469758994').
            message (str): Nội dung văn bản thông báo đã render theo mẫu template.
            quote_msg_id (Optional[str]): Mã tin nhắn cần trích dẫn (reply).
            timeout (float): Giới hạn thời gian chờ phản hồi (giây).
            max_retries (int): Số lần thử lại tối đa khi gặp lỗi ngoại vi (mặc định 3).

        Returns:
            Tuple[bool, Optional[str], Optional[str]]: `(is_success, zalo_msg_id, error_message)`.
        """
        if not group_id or not message:
            return False, None, "Thiếu group_id hoặc nội dung tin nhắn"

        # Bỏ qua gọi mạng ngoài nếu là dữ liệu kiểm thử tự động
        if str(group_id).startswith("pytest_") or str(group_id).startswith("test_dummy_"):
            return True, f"test_mock_zalo_{uuid4().hex[:12]}", None

        url = f"{settings.ZALO_BRIDGE_URL.rstrip('/')}/api/bot/send/group"
        payload = {
            "groupId": str(group_id).strip(),
            "message": message,
        }
        # Chỉ truyền quoteMsgId khi là số nguyên (mã tin nhắn Zalo chuẩn)
        if quote_msg_id and str(quote_msg_id).strip().isdigit():
            payload["quoteMsgId"] = str(quote_msg_id).strip()

        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "VSICO-Zalo-Dispatcher/1.0",
            },
            method="POST",
        )

        last_error: Optional[str] = None
        for attempt in range(1, max_retries + 1):
            # 1. Điều tiết lưu lượng qua Token Bucket (chặn nếu vượt quá 10 req/s)
            has_token = outbound_throttler.acquire(timeout=5.0)
            if not has_token:
                last_error = f"Rate limit exceeded (Token Bucket Throttled - lần {attempt})"
                logger.warning("Hết hạn mức gửi Zalo OA tạm thời cho nhóm %s (lần %d/%d)", group_id, attempt, max_retries)
                if attempt < max_retries:
                    time.sleep(1.0 * attempt)
                continue

            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp_body = json.loads(resp.read().decode("utf-8"))
                    if resp_body.get("ok"):
                        res_obj = resp_body.get("result") or {}
                        msg_obj = res_obj.get("message") or {}
                        zalo_msg_id = str(msg_obj.get("msgId") or "") or None
                        logger.info("[ZALO_OK] Đã gửi tin nhắn tới nhóm Zalo %s (msgId: %s, lần %d)", group_id, zalo_msg_id, attempt)
                        return True, zalo_msg_id, None
                    else:
                        err = resp_body.get("error") or "Lỗi từ ZCA bridge"
                        last_error = err
                        logger.warning("Máy chủ ZCA từ chối gửi tới nhóm %s (lần %d/%d): %s", group_id, attempt, max_retries, err)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    outbound_throttler.report_rate_limit(retry_after=3.0)
                try:
                    err_body = e.read().decode("utf-8")
                    err_json = json.loads(err_body)
                    last_error = err_json.get("error") or f"HTTP {e.code}: {e.reason}"
                except Exception:
                    last_error = f"HTTP {e.code}: {e.reason}"
                logger.warning("Lỗi HTTP khi gửi tin nhóm %s (lần %d/%d): %s", group_id, attempt, max_retries, last_error)
            except Exception as e:
                last_error = str(e)
                logger.warning("Không thể kết nối tới Zalo bridge (%s, lần %d/%d): %s", url, attempt, max_retries, last_error)

            if attempt < max_retries:
                time.sleep(1.0 * attempt)

        logger.error("[ZALO_ERR] Thất bại sau %d lần thử gửi tin nhóm %s: %s", max_retries, group_id, last_error)
        return False, None, last_error

    @classmethod
    def send_to_user(
        cls,
        user_id: str,
        message: str,
        timeout: float = 8.0,
        max_retries: int = 3,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Gửi tin nhắn riêng (1-1) cho một người dùng hoặc tài xế Zalo (có thử lại tối đa 3 lần).

        Args:
            user_id (str): ID tài khoản Zalo nhận tin.
            message (str): Nội dung tin nhắn gửi đi.
            timeout (float): Giới hạn thời gian chờ.
            max_retries (int): Số lần thử lại tối đa (mặc định 3).

        Returns:
            Tuple[bool, Optional[str], Optional[str]]: `(is_success, zalo_msg_id, error_message)`.
        """
        if not user_id or not message:
            return False, None, "Thiếu user_id hoặc nội dung tin nhắn"

        # Bỏ qua gọi mạng ngoài nếu là dữ liệu kiểm thử tự động
        if str(user_id).startswith("pytest_") or str(user_id).startswith("test_dummy_"):
            return True, f"test_mock_zalo_{uuid4().hex[:12]}", None

        url = f"{settings.ZALO_BRIDGE_URL.rstrip('/')}/api/bot/send/user"
        payload = {
            "userId": str(user_id).strip(),
            "message": message,
        }
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "VSICO-Zalo-Dispatcher/1.0",
            },
            method="POST",
        )

        last_error: Optional[str] = None
        for attempt in range(1, max_retries + 1):
            has_token = outbound_throttler.acquire(timeout=5.0)
            if not has_token:
                last_error = f"Rate limit exceeded (Token Bucket Throttled - user lần {attempt})"
                if attempt < max_retries:
                    time.sleep(1.0 * attempt)
                continue

            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp_body = json.loads(resp.read().decode("utf-8"))
                    if resp_body.get("ok"):
                        res_obj = resp_body.get("result") or {}
                        msg_obj = res_obj.get("message") or {}
                        zalo_msg_id = str(msg_obj.get("msgId") or "") or None
                        logger.info("[ZALO_OK] Đã gửi tin nhắn tới User Zalo %s (msgId: %s, lần %d)", user_id, zalo_msg_id, attempt)
                        return True, zalo_msg_id, None
                    else:
                        err = resp_body.get("error") or "Lỗi từ ZCA bridge"
                        last_error = err
                        if resp_body.get("code") == 123 or "123" in str(err):
                            logger.warning("[ZALO_WARN] Người nhận %s chưa kết bạn hoặc chặn tin nhắn người lạ (Zalo error 123). Dừng thử lại.", user_id)
                            break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    outbound_throttler.report_rate_limit(retry_after=3.0)
                try:
                    err_body = e.read().decode("utf-8")
                    err_json = json.loads(err_body)
                    last_error = err_json.get("error") or f"HTTP {e.code}: {e.reason}"
                    if err_json.get("code") == 123 or "123" in str(last_error):
                        logger.warning("[ZALO_WARN] Người nhận %s chưa kết bạn hoặc chặn tin nhắn người lạ (Zalo error 123). Dừng thử lại.", user_id)
                        break
                except Exception:
                    last_error = f"HTTP {e.code}: {e.reason}"
                logger.warning("Lỗi HTTP khi gửi tin tới user %s (lần %d/%d): %s", user_id, attempt, max_retries, last_error)
            except Exception as e:
                last_error = str(e)
                logger.warning("Không thể gửi tin tới user %s (lần %d/%d): %s", user_id, attempt, max_retries, last_error)

            if attempt < max_retries:
                time.sleep(1.0 * attempt)

        logger.error("[ZALO_ERR] Thất bại sau %d lần thử gửi tin tới user %s: %s", max_retries, user_id, last_error)
        return False, None, last_error
