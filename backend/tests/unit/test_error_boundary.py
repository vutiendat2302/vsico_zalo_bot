"""Module Kiểm Thử Đơn Vị Ranh Giới Bắt Lỗi Toàn Cục (Error Boundary & Throttler Unit Tests).

Kiểm tra toàn diện các kịch bản theo yêu cầu Phần 2:
- Hàm `run_safely` bọc việc xử lý một tin: Khi handler ném RuntimeError, lỗi được chuyển thành Action.ERROR
  kèm mã E999, vẫn ghi một dòng vào results.csv, và worker không bị sập.
- Kiểm tra hệ thống lớp ngoại lệ CarrierBotError: E100, E101, E200, E300, E999.
- Kiểm tra cơ chế tiết lưu cảnh báo Admin (Throttle 5 phút): Cùng mã lỗi chỉ bắn cảnh báo một lần mỗi 5 phút,
  kèm theo số lần lặp.
- Kiểm tra cơ chế gửi Zalo thử lại (Retry 3 lần) với backoff, chống gửi trùng lặp (Deduplication).
"""

import os
import sys
import unittest
import tempfile
from datetime import datetime
from queue import Queue

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.domain.errors import (
    CarrierBotError,
    InvalidSignatureError,
    InvalidSchemaError,
    ShippingDataError,
    OutboundSendError,
    InternalServerError,
)
from nhaxe_bot.ingestion.models import InboundMessage
from nhaxe_bot.infrastructure.error_boundary import run_safely, ErrorAlertThrottler
from nhaxe_bot.infrastructure.results_writer import ResultsWriter
from nhaxe_bot.infrastructure.zalo.client import DryRunZaloClient


class TestErrorBoundary(unittest.TestCase):
    """Bộ kiểm thử ranh giới bắt lỗi toàn cục và điều tiết cảnh báo."""

    def setUp(self) -> None:
        """Tạo tệp kết quả tạm thời phục vụ kiểm thử ghi file."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.csv_path = os.path.join(self.temp_dir.name, "test_results.csv")
        self.writer = ResultsWriter(self.csv_path)
        self.throttler = ErrorAlertThrottler(window_seconds=300.0)

    def tearDown(self) -> None:
        """Dọn dẹp thư mục tạm."""
        self.temp_dir.cleanup()

    def test_run_safely_catches_runtime_error(self) -> None:
        """Kiểm tra khi handler ném RuntimeError bất ngờ: run_safely bắt lỗi an toàn và ghi Action.ERROR."""
        inbound = InboundMessage(
            seq=1,
            msg_id="err_msg_001",
            raw_text="Cont: VSIU7399796",
            group_id="2001000000000000001",
            sender_id="1001000000000000001",
            event_name="user_send_text",
            received_at=datetime.now(),
            carrier_id="NX01",
            is_valid=True,
        )

        def faulty_handler(msg: InboundMessage):
            raise RuntimeError("Lỗi ngoại lệ giả lập làm sập hệ thống!")

        alerts = []
        def mock_alert(code: str, message: str, count: int):
            alerts.append((code, message, count))

        # Thực thi qua run_safely
        results = run_safely(
            handler_fn=faulty_handler,
            inbound=inbound,
            alert_fn=mock_alert,
            results_writer=self.writer,
            throttler=self.throttler,
        )

        # 1. Kết quả trả về phải là một bản ghi ERROR với mã E999
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["action"], "ERROR")
        self.assertEqual(res["error_code"], "E999")
        self.assertTrue(res["admin_alert"])
        self.assertIn("Lỗi ngoại lệ", res["admin_message"])

        # 2. Cảnh báo Admin được kích hoạt đúng 1 lần
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][0], "E999")

        # 3. Kết quả được ghi một dòng vào results.csv
        with open(self.csv_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        self.assertEqual(len(lines), 2)  # 1 header + 1 error row
        self.assertIn("ERROR", lines[1])
        self.assertIn("E999", lines[1])

    def test_carrier_bot_error_hierarchy_and_codes(self) -> None:
        """Kiểm tra hệ thống phân cấp ngoại lệ CarrierBotError và mã lỗi tương ứng."""
        err1 = InvalidSignatureError()
        self.assertEqual(err1.code, "E100")
        self.assertEqual(err1.http_status, 401)
        self.assertFalse(err1.retryable)

        err2 = InvalidSchemaError()
        self.assertEqual(err2.code, "E101")
        self.assertEqual(err2.http_status, 400)
        self.assertFalse(err2.retryable)

        err3 = ShippingDataError()
        self.assertEqual(err3.code, "E200")
        self.assertEqual(err3.http_status, 422)
        self.assertFalse(err3.retryable)

        err4 = OutboundSendError()
        self.assertEqual(err4.code, "E300")
        self.assertEqual(err4.http_status, 500)
        self.assertTrue(err4.retryable)

        err5 = InternalServerError()
        self.assertEqual(err5.code, "E999")
        self.assertEqual(err5.http_status, 500)
        self.assertTrue(err5.retryable)

    def test_alert_throttling_within_5_minutes(self) -> None:
        """Kiểm tra cùng mã lỗi chỉ báo Admin một lần mỗi 5 phút kèm số lần lặp."""
        throttler = ErrorAlertThrottler(window_seconds=300.0)
        code = "E300"
        t0 = 1000000.0

        # Lần 1: Bắn cảnh báo
        should1, cnt1 = throttler.record_and_should_alert(code, current_time=t0)
        self.assertTrue(should1)
        self.assertEqual(cnt1, 1)

        # Lần 2 (sau 1 phút = 60s): Tiết lưu, không báo
        should2, cnt2 = throttler.record_and_should_alert(code, current_time=t0 + 60.0)
        self.assertFalse(should2)
        self.assertEqual(cnt2, 2)

        # Lần 3 (sau 3 phút = 180s): Tiếp tục tiết lưu
        should3, cnt3 = throttler.record_and_should_alert(code, current_time=t0 + 180.0)
        self.assertFalse(should3)
        self.assertEqual(cnt3, 3)

        # Lần 4 (sau 6 phút = 360s > 300s): Cho phép cảnh báo lại và báo cáo số lần lặp
        should4, cnt4 = throttler.record_and_should_alert(code, current_time=t0 + 360.0)
        self.assertTrue(should4)
        self.assertEqual(cnt4, 4)

    def test_zalo_send_retry_and_deduplication(self) -> None:
        """Kiểm tra ZaloClient: retry 3 lần khi thất bại, và không gửi trùng lặp khi retry thành công."""
        # 1. Trường hợp mạng lỗi liên tục -> Thử lại 3 lần và trả về FAILED
        failing_client = DryRunZaloClient(should_fail=True)
        ok, status = failing_client.send_with_retry("msg_fail_01", "group_01", "Nội dung", max_retries=3, backoff_base=0.01)
        self.assertFalse(ok)
        self.assertEqual(status, "FAILED")
        self.assertEqual(failing_client.call_count, 3)

        # 2. Trường hợp thành công -> Gửi lần đầu SENT, lần 2 SKIPPED_DUPLICATE_SEND
        success_client = DryRunZaloClient(should_fail=False)
        ok1, status1 = success_client.send_with_retry("msg_ok_01", "group_01", "Nội dung chuẩn", max_retries=3, backoff_base=0.01)
        self.assertTrue(ok1)
        self.assertEqual(status1, "SENT")
        self.assertEqual(success_client.call_count, 1)

        # Gửi lại cùng msg_id và cùng nội dung -> Phải chống trùng lặp (Deduplicate)
        ok2, status2 = success_client.send_with_retry("msg_ok_01", "group_01", "Nội dung chuẩn", max_retries=3, backoff_base=0.01)
        self.assertTrue(ok2)
        self.assertEqual(status2, "SKIPPED_DUPLICATE_SEND")
        # Không được gọi thêm hàm gửi thực tế
        self.assertEqual(success_client.call_count, 1)


if __name__ == "__main__":
    unittest.main()
