import os
import sys
import json
import time
import threading
import urllib.request
import unittest
from http.server import HTTPServer
from typing import Dict, Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.main import build_application
from nhaxe_bot.api.app import create_http_handler

TEST_PORT = 8998

class TestWebhookApiIntegration(unittest.TestCase):
    """Bộ kiểm thử tích hợp toàn diện HTTP REST API và Zalo Webhook Gateway.

    Khởi chạy một máy chủ HTTP thực tế trên cổng `TEST_PORT` chạy nền bằng luồng riêng (daemon thread),
    thực hiện các cuộc gọi mạng HTTP GET và POST thực để kiểm thử toàn diện 8 điểm cuối API:
    - `GET  /api/health`
    - `POST /webhook`
    - `GET  /api/trips`
    - `GET  /api/trips/{cont}`
    - `POST /api/trips/new`
    - `POST /api/trips/update-driver`
    - `POST /api/trips/cancel`
    - `POST /api/trips/supplement`
    """

    @classmethod
    def setUpClass(cls) -> None:
        """Khởi động máy chủ kiểm thử tích hợp trên luồng nền trước khi chạy toàn bộ test cases."""
        shipping_file = os.path.join(PROJECT_ROOT, "tests", "fixtures", "shipping", "nhaxe_shipping_demo.csv")
        cls.app = build_application(shipping_file)
        handler_class = create_http_handler(
            cls.app["webhook_controller"],
            cls.app["worker"],
            cls.app["trip_repo"],
            cls.app.get("shipping_repo"),
            cls.app.get("template_engine")
        )
        cls.httpd = HTTPServer(("localhost", TEST_PORT), handler_class)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        """Đóng kết nối và dọn dẹp máy chủ kiểm thử sau khi hoàn thành toàn bộ test cases."""
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _send_post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Phương thức trợ giúp gửi HTTP POST JSON request tới server kiểm thử.

        Args:
            endpoint (str): Đường dẫn API tương đối (ví dụ: '/webhook', '/api/trips/new').
            payload (Dict[str, Any]): Dữ liệu payload JSON gửi kèm trong body request.

        Returns:
            Dict[str, Any]: Dữ liệu phản hồi JSON từ server sau khi giải mã UTF-8.
        """
        url = f"http://localhost:{TEST_PORT}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            envelope = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(envelope.get("ok"))
            self.assertIsNotNone(envelope.get("request_id"))
            return envelope.get("data", {})

    def _send_get(self, endpoint: str) -> Dict[str, Any]:
        """Phương thức trợ giúp gửi HTTP GET request tới server kiểm thử.

        Args:
            endpoint (str): Đường dẫn API tương đối (ví dụ: '/api/health', '/api/trips').

        Returns:
            Dict[str, Any]: Dữ liệu payload 'data' từ envelope sau khi giải mã UTF-8.
        """
        url = f"http://localhost:{TEST_PORT}{endpoint}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            envelope = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(envelope.get("ok"))
            self.assertIsNotNone(envelope.get("request_id"))
            return envelope.get("data", {})

    def test_01_get_health(self) -> None:
        """Kiểm tra điểm cuối `GET /api/health` phản hồi trạng thái UP và metrics chính xác."""
        data = self._send_get("/api/health")
        self.assertEqual(data["status"], "UP")
        self.assertIn("nhaxe-bot", data["service"])

    def test_02_post_webhook_happy_path(self) -> None:
        """Kiểm tra luồng chuẩn tiếp nhận tin nhắn báo xe qua điểm cuối `POST /webhook`."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "timestamp": "1791798010000",
            "message": {
                "msg_id": "api_msg_001",
                "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026"
            }
        }
        res = self._send_post("/webhook", payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "PARSE")
        self.assertEqual(res["total_vehicles"], 1)
        self.assertEqual(res["vehicles"][0]["send_status"], "SENT_DRY_RUN")

    def test_03_get_trips(self) -> None:
        """Kiểm tra điểm cuối `GET /api/trips` trả về danh sách các chuyến xe đã được lưu trữ."""
        data = self._send_get("/api/trips")
        self.assertGreaterEqual(data["total_trips"], 1)

    def test_04_get_trip_by_cont(self) -> None:
        """Kiểm tra điểm cuối `GET /api/trips/{cont}` tra cứu chi tiết chuyến xe theo số container."""
        data = self._send_get("/api/trips/VSIU7399796")
        self.assertTrue(data["success"])
        self.assertEqual(data["cont"], "VSIU7399796")

    def test_05_post_rest_api_create_trip(self) -> None:
        """Kiểm tra REST API `POST /api/trips/new` tạo chuyến xe mới trực tiếp từ TMS."""
        payload = {
            "carrier_id": "NX01",
            "cont": "SEGU3874035",
            "seal": "88991122",
            "bien_so": "29C-123.45",
            "tai_xe": "Nguyễn Văn Test",
            "sdt": "0912345678",
            "gio_den": "09:30 14/10/2026"
        }
        res = self._send_post("/api/trips/new", payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "CREATE_TRIP")
        self.assertEqual(res["cont"], "SEGU3874035")
        self.assertEqual(res["version"], 1)

    def test_06_post_rest_api_update_driver(self) -> None:
        """Kiểm tra REST API `POST /api/trips/update-driver` cập nhật tài xế và tăng số version."""
        payload = {
            "carrier_id": "NX01",
            "cont": "SEGU3874035",
            "tai_xe_moi": "Trần Văn Mới",
            "sdt_moi": "0987654321"
        }
        res = self._send_post("/api/trips/update-driver", payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "UPDATE_DRIVER")
        self.assertEqual(res["version"], 2)
        self.assertEqual(res["new_driver"], "Trần Văn Mới")

    def test_07_post_rest_api_cancel(self) -> None:
        """Kiểm tra REST API `POST /api/trips/cancel` ghi nhận yêu cầu hủy và kích hoạt admin alert."""
        payload = {
            "carrier_id": "NX01",
            "cont": "SEGU3874035",
            "ly_do": "Xe gặp sự cố kỹ thuật"
        }
        res = self._send_post("/api/trips/cancel", payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "CANCEL_REQUEST")
        self.assertTrue(res["admin_alert"])

    def test_08_post_rest_api_supplement(self) -> None:
        """Kiểm tra REST API `POST /api/trips/supplement` cập nhật trường seal và giờ đến."""
        payload = {
            "carrier_id": "NX01",
            "cont": "SEGU3874035",
            "seal": "99988877",
            "gio_den": "11:00 14/10/2026"
        }
        res = self._send_post("/api/trips/supplement", payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "SUPPLEMENT")

    def test_09_get_shipping(self) -> None:
        """Kiểm tra điểm cuối `GET /api/shipping` trả về danh mục lệnh kế hoạch."""
        data = self._send_get("/api/shipping")
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["total_orders"], 1)

    def test_10_post_shipping_mock_mode(self) -> None:
        """Kiểm tra REST API `POST /api/shipping/mock-mode` bật tắt chế độ auto-mock."""
        res = self._send_post("/api/shipping/mock-mode", {"enabled": True})
        self.assertTrue(res["success"])
        self.assertTrue(res["auto_mock_enabled"])

    def test_11_post_shipping_new(self) -> None:
        """Kiểm tra REST API `POST /api/shipping/new` nạp lệnh shipping mới theo ý muốn."""
        payload = {
            "carrier_id": "NX01",
            "cont": "CSQU3054383",
            "khach_hang_id": "KH_SAMSUNG",
            "ten_khach_hang": "Công ty TNHH Samsung Electronics VN",
            "kho_tra": "Kho Samsung Yên Phong",
            "dia_chi_kho_tra": "KCN Yên Phong, Bắc Ninh"
        }
        res = self._send_post("/api/shipping/new", payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["cont"], "CSQU3054383")
        self.assertEqual(res["action"], "CREATE_SHIPPING_ORDER")

    def test_12_post_webhook_with_dynamic_container(self) -> None:
        """Kiểm tra gửi tin nhắn Zalo với container vừa được nạp động vào shipping."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "timestamp": "1791798010000",
            "message": {
                "msg_id": "api_msg_dynamic_01",
                "text": "TRẢ HÀNG\nCont: CSQU3054383\nSeal: 11223344\nBiển số: 29C-999.99\nTài xế: Lê Hoàng Hải\nSĐT: 0918889999\nGiờ đến: 14:00 15/10/2026"
            }
        }
        res = self._send_post("/webhook", payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "PARSE")
        self.assertEqual(res["vehicles"][0]["send_status"], "SENT_DRY_RUN")
        self.assertEqual(res["vehicles"][0]["kho_tra"], "Kho Samsung Yên Phong")

if __name__ == "__main__":
    unittest.main()
