"""Bộ Kiểm Thử Tự Động Bước 2: Bóc Tách FIFO Thời Gian Thực & 4 API Truy Vấn Theo Thời Gian.

Kiểm tra toàn diện:
1. Bóc tách tuần tự Vào Trước - Ra Trước (FIFO) cho cả tin nhắn trực tiếp (Direct 1-1)
   lẫn tin nhắn trong Group Zalo.
2. Bóc tách đa xe/đa container, kiểm tra Check Digit ISO 6346 Modulo 11, tự động lưu
   `extraction_runs`, `truck_records`, `container_jobs`, `review_cases`, `bot_replies`.
3. Kiểm tra 4 API truy vấn:
   - `GET /api/messages` (Tất cả tin nhắn)
   - `GET /api/messages/user/{user_id}` (Tin nhắn theo User ID)
   - `GET /api/messages/group/{group_id}` (Tin nhắn theo Group ID)
   - `GET /api/messages/group/{group_id}/user/{user_id}` (Tin nhắn của User trong Group)
   Tất cả đều kiểm thử cả 2 chế độ: Không nhập thời gian (lấy hết) và Có nhập khoảng thời gian.
"""

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from src.infrastructure.database import SessionLocal
from src.infrastructure.models import (
    BotReply,
    ContainerJob,
    ExtractionRun,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    TruckRecord,
    ZaloGroup,
    ZaloMessage,
)
from src.main import app

client = TestClient(app)

TEST_PREFIX = "pytest_step2_"
GROUP_A = f"{TEST_PREFIX}group_carrier_hp"
GROUP_B = f"{TEST_PREFIX}group_carrier_bn"
USER_1 = f"{TEST_PREFIX}user_tai_xe_1"
USER_2 = f"{TEST_PREFIX}user_dieu_van_2"


def cleanup_test_records() -> None:
    """Dọn dẹp chỉ các bản ghi kiểm thử có tiền tố `pytest_step2_`, bảo toàn dữ liệu thật."""
    with SessionLocal() as db:
        msg_ids = list(
            db.scalars(
                select(ZaloMessage.id).where(
                    ZaloMessage.zalo_message_id.like(f"{TEST_PREFIX}%")
                )
            ).all()
        )
        if msg_ids:
            job_ids = list(
                db.scalars(
                    select(ContainerJob.id).where(ContainerJob.message_id.in_(msg_ids))
                ).all()
            )
            if job_ids:
                out_ids = list(
                    db.scalars(
                        select(OutboundMessageItem.outbound_message_id).where(
                            OutboundMessageItem.container_job_id.in_(job_ids)
                        )
                    ).all()
                )
                db.execute(delete(OutboundMessageItem).where(OutboundMessageItem.container_job_id.in_(job_ids)))
                if out_ids:
                    db.execute(delete(OutboundMessage).where(OutboundMessage.id.in_(out_ids)))

            db.execute(delete(BotReply).where(BotReply.message_id.in_(msg_ids)))
            db.execute(delete(ReviewCase).where(ReviewCase.message_id.in_(msg_ids)))
            db.execute(update(ContainerJob).where(ContainerJob.message_id.in_(msg_ids)).values(parent_job_id=None))
            db.execute(delete(ContainerJob).where(ContainerJob.message_id.in_(msg_ids)))
            db.execute(delete(TruckRecord).where(TruckRecord.message_id.in_(msg_ids)))
            db.execute(delete(ExtractionRun).where(ExtractionRun.message_id.in_(msg_ids)))
            db.execute(delete(ZaloMessage).where(ZaloMessage.id.in_(msg_ids)))
        db.execute(
            delete(ZaloGroup).where(
                ZaloGroup.zalo_group_id.like(f"%{TEST_PREFIX}%")
            )
        )
        db.commit()


def test_fifo_extraction_and_four_query_apis() -> None:
    """Kiểm thử toàn trình luồng FIFO Extraction và 4 API truy vấn kèm bộ lọc thời gian."""
    cleanup_test_records()
    try:
        # 1. Gửi tin nhắn 1 (User 1 trong Group A lúc 2026-10-25 08:30:00) - 2 xe hợp lệ chuẩn ISO 6346
        res1 = client.post(
            "/webhook",
            json={
                "msg_id": f"{TEST_PREFIX}msg_001",
                "group_id": GROUP_A,
                "group_name": "Nhóm Nhà Xe Hải Phòng Test",
                "sender_id": USER_1,
                "sender_name": "Anh Bảo Điều Vận",
                "text": (
                    "Đóng hàng khách Sun Paper tại Kho 3B\n"
                    "15C-878.99 / Trần Quốc Bảo / 0903976359 / VSIU7399796 / 40HC / chì 73957169\n"
                    "15H-008.14 / Nguyễn Văn Minh / 0912345678 / MSCU5285725 / 20DC / chì 52851122"
                ),
                "timestamp": "2026-10-25T08:30:00",
            },
        )
        assert res1.status_code == 200
        body1 = res1.json()
        assert body1["status"] == "ENQUEUED_AND_PROCESSED_FIFO"
        assert body1["processing_status"] == "processed"
        assert body1["trucks_count"] == 2
        assert body1["containers_count"] == 2
        assert body1["containers"][0]["container_no"] == "VSIU7399796"
        assert body1["containers"][0]["check_digit_valid"] is True
        assert body1["containers"][0]["order_type"] == "dong"

        # 2. Gửi tin nhắn 2 (User 2 trong Group A lúc 2026-10-26 14:15:00) - Sai Check Digit ISO 6346
        res2 = client.post(
            "/webhook",
            json={
                "msg_id": f"{TEST_PREFIX}msg_002",
                "group_id": GROUP_A,
                "group_name": "Nhóm Nhà Xe Hải Phòng Test",
                "sender_id": USER_2,
                "sender_name": "Chị Lan Nhà Xe",
                "text": (
                    "Trả hàng tại Kho Đình Vũ\n"
                    "Biển số: 29C-556.88\n"
                    "Tài xế: Lê Hoàng Nam\n"
                    "SĐT: 0988112233\n"
                    "Số cont: VSIU7399790"
                ),
                "timestamp": "2026-10-26T14:15:00",
            },
        )
        assert res2.status_code == 200
        body2 = res2.json()
        assert body2["processing_status"] == "needs_review"
        assert body2["containers_count"] == 1
        assert body2["containers"][0]["check_digit_valid"] is False
        assert body2["containers"][0]["validation_status"] in ("invalid", "needs_review")

        # 3. Gửi tin nhắn 3 (User 1 nhắn trực tiếp 1-1 không có group_id lúc 2026-10-27 09:00:00)
        res3 = client.post(
            "/webhook",
            json={
                "msg_id": f"{TEST_PREFIX}msg_003",
                "group_id": "",
                "sender_id": USER_1,
                "sender_name": "Anh Bảo Điều Vận",
                "text": "Đóng hàng khách Sun Paper tại Kho Tiên Sơn: 15C-999.11 / Phạm Văn Hùng / 0977665544 / VSIU7399796 / 40HC / chì 73991122",
                "timestamp": "2026-10-27T09:00:00",
            },
        )
        assert res3.status_code == 200
        body3 = res3.json()
        assert body3["group_id"] == f"direct_{USER_1}"
        assert body3["processing_status"] == "processed"

        # 4. Kiểm tra API 1: Lấy tất cả các tin nhắn (không truyền thời gian vs có truyền thời gian)
        all_no_time = client.get("/api/messages")
        assert all_no_time.status_code == 200
        assert all_no_time.json()["total"] >= 3

        all_filtered = client.get(
            "/api/messages",
            params={"from_time": "2026-10-26 00:00:00", "to_time": "2026-10-26 23:59:59"},
        )
        assert all_filtered.status_code == 200
        filtered_ids = [m["zalo_message_id"] for m in all_filtered.json()["messages"]]
        assert f"{TEST_PREFIX}msg_002" in filtered_ids
        assert f"{TEST_PREFIX}msg_001" not in filtered_ids

        # 5. Kiểm tra API 2: Lấy tin nhắn theo User ID (không truyền thời gian vs có truyền thời gian)
        user_all = client.get(f"/api/messages/user/{USER_1}")
        assert user_all.status_code == 200
        assert user_all.json()["total"] == 2

        user_time = client.get(
            f"/api/messages/user/{USER_1}",
            params={"from_time": "2026-10-27", "to_time": "2026-10-27"},
        )
        assert user_time.status_code == 200
        assert user_time.json()["total"] == 1
        assert user_time.json()["messages"][0]["zalo_message_id"] == f"{TEST_PREFIX}msg_003"

        # 6. Kiểm tra API 3: Lấy tin nhắn theo Group ID (không truyền thời gian vs có truyền thời gian)
        group_all = client.get(f"/api/messages/group/{GROUP_A}")
        assert group_all.status_code == 200
        assert group_all.json()["total"] == 2

        group_time = client.get(
            f"/api/messages/group/{GROUP_A}",
            params={"from_time": "2026-10-25", "to_time": "2026-10-25"},
        )
        assert group_time.status_code == 200
        assert group_time.json()["total"] == 1
        assert group_time.json()["messages"][0]["zalo_message_id"] == f"{TEST_PREFIX}msg_001"

        # 7. Kiểm tra API 4: Lấy tin nhắn của một User trong một Group (cả 2 đường dẫn + lọc thời gian)
        ug_all = client.get(f"/api/messages/group/{GROUP_A}/user/{USER_1}")
        assert ug_all.status_code == 200
        assert ug_all.json()["total"] == 1
        assert ug_all.json()["messages"][0]["zalo_message_id"] == f"{TEST_PREFIX}msg_001"

        ug_alias = client.get(
            f"/api/messages/user/{USER_1}/group/{GROUP_A}",
            params={"from_time": "2026-10-26", "to_time": "2026-10-27"},
        )
        assert ug_alias.status_code == 200
        assert ug_alias.json()["total"] == 0
    finally:
        cleanup_test_records()
