import unittest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.domain.models import Carrier
from nhaxe_bot.ingestion.deduplicator import Deduplicator
from nhaxe_bot.ingestion.normalizer import IngestionNormalizer

class TestIngestionNormalizer(unittest.TestCase):
    """Bộ kiểm thử đơn vị cho tầng tiếp nhận và chuẩn hóa IngestionNormalizer.

    Kiểm tra:
    - Tiếp nhận payload hợp lệ từ Zalo và ánh xạ đúng nhà xe.
    - Khử trùng lặp tin nhắn dựa trên msg_id (Idempotency).
    - Từ chối tin nhắn từ nhóm chat Zalo không xác định.
    - Phát hiện và kích hoạt cảnh báo an ninh khi người gửi không thuộc danh sách ủy quyền.
    """

    def setUp(self) -> None:
        """Thiết lập môi trường kiểm thử với danh bạ nhà xe và deduplicator bộ nhớ."""
        self.carriers = {
            "NX01": Carrier("NX01", "Hải Long", "2001000000000000001", ["1001000000000000001"])
        }
        self.dedup = Deduplicator()
        self.normalizer = IngestionNormalizer(self.carriers, self.dedup)

    def test_valid_inbound_message(self) -> None:
        """Kiểm tra trường hợp payload Zalo hợp lệ được chuẩn hóa thành công sang InboundMessage."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "message": {"msg_id": "msg_001", "text": "TRẢ HÀNG Cont: VSIU7399796"}
        }
        msg = self.normalizer.normalize(1, payload)
        self.assertTrue(msg.is_valid)
        self.assertEqual(msg.carrier_id, "NX01")
        self.assertEqual(msg.msg_id, "msg_001")

    def test_deduplication(self) -> None:
        """Kiểm tra cơ chế lọc trùng: gửi 2 lần cùng msg_id thì lần thứ hai phải bị từ chối."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "1001000000000000001"},
            "message": {"msg_id": "msg_001", "text": "TRẢ HÀNG Cont: VSIU7399796"}
        }
        # Lần 1: Thành công
        msg1 = self.normalizer.normalize(1, payload)
        self.assertTrue(msg1.is_valid)

        # Lần 2: Trùng msg_id -> Bị chặn
        msg2 = self.normalizer.normalize(2, payload)
        self.assertFalse(msg2.is_valid)
        self.assertEqual(msg2.action, "DUPLICATE_MESSAGE")

    def test_unknown_group(self) -> None:
        """Kiểm tra tin nhắn phát sinh từ group_id lạ không có trong danh bạ bị bỏ qua an toàn."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "9999999999999999999",
            "sender": {"id": "1001000000000000001"},
            "message": {"msg_id": "msg_002", "text": "test"}
        }
        msg = self.normalizer.normalize(3, payload)
        self.assertFalse(msg.is_valid)
        self.assertEqual(msg.action, "IGNORE_UNKNOWN_GROUP")

    def test_unknown_sender(self) -> None:
        """Kiểm tra tài khoản gửi tin nhắn lạ vào nhóm được ủy quyền sẽ kích hoạt admin alert."""
        payload = {
            "event_name": "user_send_text",
            "group_id": "2001000000000000001",
            "sender": {"id": "9999999999999999999"},
            "message": {"msg_id": "msg_003", "text": "test"}
        }
        msg = self.normalizer.normalize(4, payload)
        self.assertFalse(msg.is_valid)
        self.assertEqual(msg.action, "IGNORE_UNKNOWN_SENDER")
        self.assertTrue(msg.admin_alert)

if __name__ == "__main__":
    unittest.main()
