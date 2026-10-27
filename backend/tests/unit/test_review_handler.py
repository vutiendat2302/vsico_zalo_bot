"""Bộ Kiểm Thử Nghiệp Vụ ĐHVT Duyệt Tin Qua Zalo Quote (Test Review Handler).

Kiểm tra 3 kịch bản cốt lõi theo Mục 8.2 tab Đặc tả:
1. ĐHVT quote 'ok' -> Phê duyệt phát hành tin cho khách (APPROVE_OUTBOUND).
2. ĐHVT quote 'sửa xe ..., sửa chì ...' -> Cập nhật bản nháp (EDIT_PENDING).
3. ĐHVT quote 'huỷ' -> Huỷ bỏ bản nháp (CANCEL_REQUEST).
"""

import unittest
from datetime import datetime
from nhaxe_bot.domain.enums import Intent
from nhaxe_bot.ingestion.models import InboundMessage
from nhaxe_bot.outbound.templates import TemplateEngine
from nhaxe_bot.handlers.review_handler import ReviewHandler
from nhaxe_bot.config.settings import SETTINGS


class TestReviewHandler(unittest.TestCase):
    """Bộ unit test kiểm tra xử lý lệnh duyệt / sửa của ĐHVT qua Zalo trích dẫn."""

    def setUp(self) -> None:
        templates = TemplateEngine(SETTINGS.templates_dir)
        self.handler = ReviewHandler(templates)

    def test_dhvt_approve_with_ok(self) -> None:
        """Kiểm tra ĐHVT trả lời 'ok' trích dẫn tin nháp: hệ thống duyệt và phát hành tin khách."""
        inbound = InboundMessage(
            seq=1,
            msg_id="reply_msg_001",
            raw_text="ok",
            group_id="2000000000000000001",
            sender_id="9001000000000000001",
            event_name="user_send_text",
            received_at=datetime.now(),
            carrier_id="ADMIN_DHVT",
            quote_msg_id="draft_msg_12345",
        )

        results = self.handler.handle(inbound, {})
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["action"], "APPROVE_OUTBOUND")
        self.assertFalse(res["needs_review"])
        self.assertTrue(len(res["customer_notifications"]) > 0)
        self.assertIn("ĐHVT đã duyệt", res["reason"])

    def test_dhvt_edit_pending_draft(self) -> None:
        """Kiểm tra ĐHVT trả lời 'sửa xe 15H-06722, sửa chì 23333330': hệ thống sửa và giữ ở trạng thái nháp."""
        inbound = InboundMessage(
            seq=2,
            msg_id="reply_msg_002",
            raw_text="sửa xe 15H-06722, sửa chì 23333330",
            group_id="2000000000000000001",
            sender_id="9001000000000000001",
            event_name="user_send_text",
            received_at=datetime.now(),
            carrier_id="ADMIN_DHVT",
            quote_msg_id="draft_msg_12345",
        )

        results = self.handler.handle(inbound, {})
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["action"], "EDIT_PENDING")
        self.assertTrue(res["needs_review"])
        self.assertEqual(len(res["customer_notifications"]), 0)
        self.assertIsNotNone(res["reply_to_carrier"])
        self.assertIn("15H-06722", res["reply_to_carrier"])

    def test_dhvt_cancel_pending_draft(self) -> None:
        """Kiểm tra ĐHVT trả lời 'huỷ': hệ thống hủy bản nháp và không gửi ra ngoài."""
        inbound = InboundMessage(
            seq=3,
            msg_id="reply_msg_003",
            raw_text="huỷ",
            group_id="2000000000000000001",
            sender_id="9001000000000000001",
            event_name="user_send_text",
            received_at=datetime.now(),
            carrier_id="ADMIN_DHVT",
            quote_msg_id="draft_msg_12345",
        )

        results = self.handler.handle(inbound, {})
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["action"], "CANCEL_REQUEST")
        self.assertFalse(res["needs_review"])
        self.assertEqual(len(res["customer_notifications"]), 0)


if __name__ == "__main__":
    unittest.main()
