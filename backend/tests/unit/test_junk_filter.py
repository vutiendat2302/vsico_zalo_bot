"""Module Kiểm Thử Đơn Vị Bộ Lọc Tin Rác & Nghi Ngờ (Junk Filter Unit Tests).

Kiểm tra toàn diện các kịch bản theo đúng yêu cầu Phần 1:
- JUNK: "ok", "Dạ em nhận rồi ạ", "👍", "cảm ơn anh", "xin chào cả nhà", "https://...", chuỗi rỗng.
- SUSPECT: "sđt tài 0986713346", "xe 15C17066 đang chạy".
- CANDIDATE:
  + "1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2621051 chì 23333878"
  + "Xe15h00814/phạm tiến hưng/0332308336/GAOU6422920/ kho win yên mỹ"
- Ghép tin nghi ngờ trong vòng 30 phút qua SuspectMessageBuffer.
"""

import os
import sys
import unittest
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.messaging.classifier.junk_filter import classify_junk, SuspectMessageBuffer


class TestJunkFilter(unittest.TestCase):
    """Bộ kiểm thử phân loại tin rác, tin nghi ngờ và ứng viên xử lý."""

    def test_junk_messages(self) -> None:
        """Kiểm tra các tin nhắn rác, xác nhận xã giao, chỉ có emoji hoặc liên kết URL."""
        junk_samples = [
            ("ok", "Xác nhận ngắn"),
            ("Dạ em nhận rồi ạ", "Xác nhận xã giao"),
            ("👍", "Chỉ chứa biểu tượng emoji"),
            ("cảm ơn anh", "Chào hỏi/cảm ơn xã giao"),
            ("xin chào cả nhà", "Chào hỏi tập thể"),
            ("https://zalo.me/g/demo123", "Liên kết URL quảng cáo"),
            ("https://shopee.vn/flash-sale", "Liên kết mua sắm"),
            ("", "Chuỗi rỗng"),
            ("   \n\t  ", "Chuỗi chỉ chứa khoảng trắng"),
            ("🎉👏🚚", "Nhiều emoji không có chữ số"),
        ]

        for text, desc in junk_samples:
            verdict, reason, signals = classify_junk(text)
            self.assertEqual(
                verdict,
                "JUNK",
                f"Kỳ vọng JUNK cho mẫu [{desc}]: '{text}', nhưng nhận được {verdict} ({reason})"
            )

    def test_suspect_messages(self) -> None:
        """Kiểm tra các tin nghi ngờ chỉ chứa 1 tín hiệu xe yếu (thiếu thông tin container)."""
        suspect_samples = [
            ("sđt tài 0986713346", "Chỉ có số điện thoại"),
            ("xe 15C17066 đang chạy", "Chỉ có biển số xe và từ khóa xe"),
            ("bác tài 0903976359", "Chỉ có số điện thoại tài xế"),
            ("xe 50H-467.44 tới rồi", "Chỉ có biển số xe cơ giới"),
        ]

        for text, desc in suspect_samples:
            verdict, reason, signals = classify_junk(text)
            self.assertEqual(
                verdict,
                "SUSPECT",
                f"Kỳ vọng SUSPECT cho mẫu [{desc}]: '{text}', nhưng nhận được {verdict} ({reason})"
            )
            # Tín hiệu không được có số cont
            self.assertFalse(signals["has_cont"])

    def test_candidate_messages(self) -> None:
        """Kiểm tra các tin ứng viên có cont hợp lệ hoặc từ 2 tín hiệu xe trở lên."""
        candidate_samples = [
            (
                "1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2621051 chì 23333878",
                "Đầy đủ biển số, tài xế, SĐT, số cont và seal"
            ),
            (
                "Xe15h00814/phạm tiến hưng/0332308336/GAOU6422920/ kho win yên mỹ",
                "Đầy đủ biển số dính liền, tài xế, SĐT và số cont"
            ),
            (
                "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026",
                "Tin báo xe định dạng xuống dòng đầy đủ"
            ),
            (
                "hủy cont VSIU7399796",
                "Lệnh hủy chuyến kèm số cont"
            ),
        ]

        for text, desc in candidate_samples:
            verdict, reason, signals = classify_junk(text)
            self.assertEqual(
                verdict,
                "CANDIDATE",
                f"Kỳ vọng CANDIDATE cho mẫu [{desc}]: '{text}', nhưng nhận được {verdict} ({reason})"
            )

    def test_suspect_buffer_merge_within_30_minutes(self) -> None:
        """Kiểm tra bộ đệm ghép tin nghi ngờ: 2 tin lẻ gửi cách nhau dưới 30 phút được ghép thành CANDIDATE."""
        buffer = SuspectMessageBuffer(ttl_seconds=1800.0)
        carrier_id = "NX01"
        start_time = 1000000.0

        # Tin 1: Chỉ có số điện thoại -> SUSPECT
        msg1 = "sđt tài 0986713346"
        v1, _, _ = classify_junk(msg1)
        self.assertEqual(v1, "SUSPECT")
        buffer.record_suspect(carrier_id, msg1, timestamp=start_time)

        # Tin 2: Gửi sau 10 phút (600 giây < 1800 giây) bổ sung số cont và biển số
        current_time = start_time + 600.0
        msg2 = "xe 15C17066 cont VSIU2621051 chì 23333878"
        merged = buffer.get_merged_if_recent(carrier_id, msg2, current_time=current_time)

        self.assertIsNotNone(merged)
        self.assertIn("0986713346", merged)
        self.assertIn("VSIU2621051", merged)

        # Tái thẩm định chuỗi ghép nối -> Phải trở thành CANDIDATE
        v_merged, _, _ = classify_junk(merged)
        self.assertEqual(v_merged, "CANDIDATE")

    def test_suspect_buffer_expired_after_30_minutes(self) -> None:
        """Kiểm tra tin nhắn nghi ngờ quá 30 phút sẽ hết hạn và không được ghép nối."""
        buffer = SuspectMessageBuffer(ttl_seconds=1800.0)
        carrier_id = "NX02"
        start_time = 1000000.0

        msg1 = "xe 15C17066 đang chạy"
        buffer.record_suspect(carrier_id, msg1, timestamp=start_time)

        # Tin 2: Gửi sau 35 phút (2100 giây > 1800 giây)
        current_time = start_time + 2100.0
        msg2 = "sđt 0986713346"
        merged = buffer.get_merged_if_recent(carrier_id, msg2, current_time=current_time)

        self.assertIsNone(merged, "Kỳ vọng không ghép nối khi đã quá thời hạn 30 phút")


if __name__ == "__main__":
    unittest.main()
