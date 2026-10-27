import unittest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.domain.enums import Intent
from nhaxe_bot.messaging.classifier.rule_based import RuleBasedClassifier

class TestIntentClassifier(unittest.TestCase):
    """Bộ kiểm thử đơn vị cho bộ phân loại ý định tin nhắn (RuleBasedClassifier Tests).

    Kiểm tra độ ưu tiên phân loại khi gặp các cặp xung đột từ khóa nghiệp vụ:
    - Xung đột hủy chuyến vs báo xe có container.
    - Xung đột đổi tài xế chỉ nêu biển số xe.
    - Xung đột đổi tài xế nhưng thiếu cả biển số và container.
    - Tin nhắn bổ sung số seal cho chuyến xe đang chờ.
    - Tin báo xe chuẩn thông thường.
    - Tin nhắn giao tiếp thông thường cần bỏ qua (IGNORE_CHAT).
    """

    def setUp(self) -> None:
        """Khởi tạo một phiên bản RuleBasedClassifier mới trước mỗi ca kiểm thử."""
        self.classifier = RuleBasedClassifier()

    def test_conflict_cancel_vs_cont(self) -> None:
        """Cặp xung đột 1: Vừa có từ khóa xin hủy chuyến vừa có số container hợp lệ.

        Hệ thống bắt buộc phải ưu tiên Intent.CANCEL_REQUEST thay vì Intent.PARSE.
        """
        text = "anh ơi xe hỏng em xin hủy chuyến cont AHLXU1029021 nhé ạ"
        intent = self.classifier.classify(text, ["AHLXU1029021"])
        self.assertEqual(intent, Intent.CANCEL_REQUEST)

    def test_conflict_update_driver_plate_only(self) -> None:
        """Cặp xung đột 2: Đổi tài xế chỉ nêu biển số xe, không có số container.

        Hệ thống phải nhận diện chính xác Intent.UPDATE_REQUEST để tìm kiếm chuyến theo biển số.
        """
        text = "Đổi tài xế xe 15C-878.99 sang Lê Văn Đổi 0988592302 nhé anh"
        intent = self.classifier.classify(text, [])
        self.assertEqual(intent, Intent.UPDATE_REQUEST)

    def test_conflict_update_without_cont_or_plate(self) -> None:
        """Cặp xung đột 3: Đổi thông tin chung chung không rõ số cont hoặc biển số xe.

        Hệ thống phải phân loại là Intent.ASK_WHICH_CONT để phản hồi hỏi lại nhà xe.
        """
        text = "bên em đổi tài xế nhé anh, tài xế mới Nguyễn Văn Lực 0944443210"
        intent = self.classifier.classify(text, [])
        self.assertEqual(intent, Intent.ASK_WHICH_CONT)

    def test_supplement_seal(self) -> None:
        """Bổ sung số seal hoặc giờ đến cho chuyến xe đang chờ thông tin -> Intent.SUPPLEMENT."""
        text = "seal cont GAOU9386298 73957169 giờ đến 08:00"
        intent = self.classifier.classify(text, ["GAOU9386298"])
        self.assertEqual(intent, Intent.SUPPLEMENT)

    def test_normal_parse(self) -> None:
        """Tin báo xe chuẩn với đầy đủ trường thông tin -> Intent.PARSE."""
        text = "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo"
        intent = self.classifier.classify(text, ["VSIU7399796"])
        self.assertEqual(intent, Intent.PARSE)

    def test_ignore_chat(self) -> None:
        """Tin nhắn hội thoại thông thường (chào hỏi, cảm ơn, xác nhận) -> Intent.IGNORE_CHAT."""
        self.assertEqual(self.classifier.classify("ok", []), Intent.IGNORE_CHAT)
        self.assertEqual(self.classifier.classify("dạ em nhận rồi ạ", []), Intent.IGNORE_CHAT)

if __name__ == "__main__":
    unittest.main()
