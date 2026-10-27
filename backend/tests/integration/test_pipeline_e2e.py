import unittest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.main import build_application

class TestPipelineE2E(unittest.TestCase):
    """Bộ kiểm thử đầu-cuối toàn diện toàn bộ pipeline (End-to-End Pipeline Tests).

    Kiểm tra sự phối hợp nhịp nhàng giữa tất cả các tầng:
    Webhook Gateway -> Queue Publisher -> Queue Worker -> Classifier ->
    Router -> Use Case Handler -> Repository & Outbound Responder.
    """

    def setUp(self) -> None:
        """Khởi tạo một instance ứng dụng sạch trước mỗi ca kiểm thử."""
        shipping_file = os.path.join(PROJECT_ROOT, "tests", "fixtures", "shipping", "nhaxe_shipping_demo.csv")
        self.app = build_application(shipping_file)
        self.webhook = self.app["webhook_controller"]
        self.worker = self.app["worker"]
        self.trip_repo = self.app["trip_repo"]

    def test_e2e_happy_path_and_update_by_plate(self) -> None:
        """Kiểm thử luồng hoàn chỉnh từ tạo chuyến mới đến đổi tài xế chỉ qua biển số xe.

        Quy trình:
        1. Gửi tin báo xe chuẩn cho cont VSIU7399796 -> Kết quả tạo chuyến version 1 (SENT_DRY_RUN).
        2. Gửi tin đổi tài xế chỉ nêu biển số 15C-878.99 -> Hệ thống tự động tra cứu
           chuyến xe theo biển số và nâng cấp lên version 2 với tài xế mới.
        """
        # 1. Gửi tin báo 1 xe mới (Happy Path)
        payload_1 = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "timestamp": "1791798010000",
            "message": {
                "msg_id": "e2e_msg_001",
                "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026"
            }
        }
        status, ack = self.webhook.handle_webhook_event(1, payload_1)
        self.assertEqual(status, 200)

        # Worker xử lý từ Queue
        results_1 = self.worker.process_all_queued()
        self.assertEqual(len(results_1), 1)
        res1 = results_1[0]
        self.assertEqual(res1["action"], "PARSE")
        self.assertEqual(res1["cont"], "VSIU7399796")
        self.assertEqual(res1["send_status"], "SENT_DRY_RUN")

        # Kiểm tra chuyến đã lưu trong TripRepository
        trip = self.trip_repo.get_trip("NX01", "VSIU7399796")
        self.assertIsNotNone(trip)
        self.assertEqual(trip.version, 1)

        # 2. Gửi tin đổi tài xế CHỈ DÙNG BIỂN SỐ XE
        payload_2 = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "timestamp": "1791855257000",
            "message": {
                "msg_id": "e2e_msg_002",
                "text": "Đổi tài xế xe 15C-878.99 sang Lê Văn Đổi 0988592302 nhé anh"
            }
        }
        status2, ack2 = self.webhook.handle_webhook_event(2, payload_2)
        self.assertEqual(status2, 200)

        results_2 = self.worker.process_all_queued()
        self.assertEqual(len(results_2), 1)
        res2 = results_2[0]
        self.assertEqual(res2["action"], "UPDATE_REQUEST")
        self.assertEqual(res2["cont"], "VSIU7399796")

        # Kiểm tra phiên bản chuyến xe đã nâng lên Version 2
        trip_v2 = self.trip_repo.get_trip("NX01", "VSIU7399796")
        self.assertEqual(trip_v2.version, 2)
        self.assertEqual(trip_v2.xe_data["tai_xe"], "Lê Văn Đổi")
        self.assertEqual(trip_v2.xe_data["sdt"], "0988592302")

    def test_e2e_wrong_carrier_alert(self) -> None:
        """Kiểm thử phát hiện lỗi phân công sai nhà xe (Wrong Carrier Security Alert).

        Cont SEGU3874035 trong kế hoạch được giao cho NX01 nhưng tin do NX03 gửi
        -> Hệ thống phải giữ lại (HOLD_ADMIN), kích hoạt cảnh báo điều phối (admin_alert)
        và ghi nhận mã cảnh báo 'sai_nha_xe'.
        """
        payload = {
            "event_name": "user_send_text",
            "group_id": "2003000000000000001",
            "sender": {"id": "1003000000000000001"},
            "timestamp": "1791848880000",
            "message": {
                "msg_id": "e2e_wrong_03",
                "text": "xe 30E45104 tx Dương Văn Khoa 0973867761 cont SEGU3874035 seal 8429599 tra hang 14/10 8h"
            }
        }
        self.webhook.handle_webhook_event(3, payload)
        results = self.worker.process_all_queued()
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["send_status"], "HOLD_ADMIN")
        self.assertTrue(res["admin_alert"])
        self.assertIn("sai_nha_xe", res["warnings"])

if __name__ == "__main__":
    unittest.main()
