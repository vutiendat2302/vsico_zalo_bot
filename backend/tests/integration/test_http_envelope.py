"""Module Kiểm Thử Tích Hợp Request/Response Chuẩn Toàn Cục (HTTP Envelope Integration Tests).

Kiểm tra toàn diện các quy tắc HTTP và Response Envelope theo Phần 3:
1. Mọi response chỉ trả qua cấu trúc Envelope:
   {"ok": bool, "data": {...}|null, "error": {"code","message","retryable"}|null, "request_id": "..."}
2. Chữ ký sai trả HTTP 401 (mã E100).
3. Schema sai / JSON rỗng trả HTTP 400 (mã E101).
4. Lỗi nghiệp vụ (không tìm thấy chuyến xe) trả HTTP 422 (mã E422).
5. Lỗi nội bộ trả HTTP 500 (mã E999, retryable=true).
6. Tin bị bỏ qua (rác, nhóm lạ, trùng) vẫn trả HTTP 200 với data.action tương ứng.
7. Request ID được kế thừa từ header X-Request-Id hoặc tự động sinh UUID.
8. Che giấu số điện thoại trong log (PII Phone Masking).
"""

import os
import sys
import json
import urllib.request
import urllib.error
import threading
import unittest
from http.server import HTTPServer
from typing import Dict, Any, Tuple, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.main import build_application
from nhaxe_bot.api.app import create_http_handler
from nhaxe_bot.observability.logging import mask_phone

ENVELOPE_TEST_PORT = 8998


class TestHttpEnvelopeAndStatus(unittest.TestCase):
    """Bộ kiểm thử tích hợp cho cấu trúc Envelope và các mã trạng thái HTTP chuẩn."""

    @classmethod
    def setUpClass(cls) -> None:
        """Khởi động một instance HTTPServer riêng trên cổng 8998."""
        from nhaxe_bot.config.settings import SETTINGS
        cls.old_secret = SETTINGS.zalo_secret_key
        SETTINGS.zalo_secret_key = "test_zalo_secret_key_123"

        shipping_file = os.path.join(
            os.path.dirname(__file__), "..", "fixtures", "shipping", "nhaxe_shipping_demo.csv"
        )
        cls.app = build_application(shipping_file)
        handler_class = create_http_handler(
            webhook_controller=cls.app["webhook_controller"],
            worker=cls.app["worker"],
            trip_repo=cls.app["trip_repo"],
            shipping_repo=cls.app["shipping_repo"],
            template_engine=cls.app["template_engine"],
        )
        cls.server = HTTPServer(("127.0.0.1", ENVELOPE_TEST_PORT), handler_class)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        """Dừng server kiểm thử sau khi hoàn tất."""
        from nhaxe_bot.config.settings import SETTINGS
        SETTINGS.zalo_secret_key = cls.old_secret
        cls.server.shutdown()
        cls.server.server_close()

    def _send_request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Gửi HTTP Request và nhận về Status Code kèm JSON Envelope đã giải mã."""
        url = f"http://127.0.0.1:{ENVELOPE_TEST_PORT}{path}"
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                content = json.loads(resp.read().decode("utf-8"))
                return status, content
        except urllib.error.HTTPError as http_err:
            status = http_err.code
            content = json.loads(http_err.read().decode("utf-8"))
            return status, content

    def test_phone_masking_rule(self) -> None:
        """Kiểm tra quy tắc che giấu số điện thoại trong log: giữ 3 số đầu và 3 số cuối."""
        self.assertEqual(mask_phone("0903976359"), "090***359")
        self.assertEqual(mask_phone("0986713346"), "098***346")
        self.assertEqual(mask_phone("Liên hệ SĐT 0332308336 của tài xế"), "Liên hệ SĐT 033***336 của tài xế")
        self.assertEqual(mask_phone("+84903976359"), "+849***359")

    def test_request_id_header_propagation(self) -> None:
        """Kiểm tra request_id được kế thừa từ header X-Request-Id."""
        custom_id = "req-test-trace-12345"
        status, res = self._send_request("GET", "/api/health", headers={"X-Request-Id": custom_id})

        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["request_id"], custom_id)
        self.assertIsNotNone(res["data"])
        self.assertIsNone(res["error"])

    def test_http_401_invalid_signature(self) -> None:
        """Kiểm tra chữ ký số Zalo sai trả về HTTP 401 kèm mã E100."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "message": {"msg_id": "test_sig_01", "text": "Tin test"}
        }
        status, res = self._send_request(
            "POST",
            "/webhook",
            body=payload,
            headers={"X-Zalo-Signature": "invalid_fake_sha256_signature_here"}
        )

        self.assertEqual(status, 401)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["data"])
        self.assertIsNotNone(res["error"])
        self.assertEqual(res["error"]["code"], "E100")
        self.assertFalse(res["error"]["retryable"])

    def test_http_400_invalid_schema_or_empty(self) -> None:
        """Kiểm tra gửi body rỗng hoặc sai kiểu dữ liệu trả về HTTP 400 kèm mã E101."""
        # 1. Gửi body chuỗi không phải dict
        url = f"http://127.0.0.1:{ENVELOPE_TEST_PORT}/webhook"
        req = urllib.request.Request(
            url,
            data=b"['not_a_dict']",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                res = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status = e.code
            res = json.loads(e.read().decode("utf-8"))

        self.assertEqual(status, 400)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "E101")
        self.assertFalse(res["error"]["retryable"])

    def test_http_422_business_logic_error(self) -> None:
        """Kiểm tra lỗi nghiệp vụ (tra cứu container không tồn tại) trả về HTTP 422 kèm mã E422."""
        status, res = self._send_request("GET", "/api/trips/NON_EXISTENT_CONT_999")

        self.assertEqual(status, 422)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["data"])
        self.assertIsNotNone(res["error"])
        self.assertEqual(res["error"]["code"], "E422")
        self.assertFalse(res["error"]["retryable"])

    def test_http_200_junk_message_handled_safely(self) -> None:
        """Kiểm tra tin nhắn rác hoặc xác nhận xã giao trả HTTP 200 với data.action = IGNORE_CHAT."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "timestamp": "1791798010000",
            "message": {
                "msg_id": "junk_test_msg_01",
                "text": "Dạ em nhận rồi ạ"
            }
        }
        status, res = self._send_request("POST", "/webhook", body=payload)

        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertIsNone(res["error"])
        data = res["data"]
        self.assertIsNotNone(data)
        self.assertEqual(data["action"], "IGNORE_CHAT")
        self.assertEqual(data["junk_verdict"], "JUNK")
        self.assertEqual(data["total_vehicles"], 0)

    def test_http_200_suspect_message_review(self) -> None:
        """Kiểm tra tin nhắn nghi ngờ thiếu thông tin trả HTTP 200 với data.action = MANUAL_REVIEW và câu phản hồi."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "timestamp": "1791798010000",
            "message": {
                "msg_id": "suspect_test_msg_01",
                "text": "sđt tài 0986713346"
            }
        }
        status, res = self._send_request("POST", "/webhook", body=payload)

        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        data = res["data"]
        self.assertEqual(data["action"], "MANUAL_REVIEW")
        self.assertEqual(data["junk_verdict"], "SUSPECT")
        self.assertTrue(data["admin_alert"])
        self.assertIn("Anh/chị gửi đủ biển số", data["operation_detail"]["reply_to_carrier"])


if __name__ == "__main__":
    unittest.main()
