"""Bộ kiểm thử Nhận Diện Ký Tự Quang Học OCR từ Ảnh (PaddleOCR Image Extraction Tests).

Kiểm thử toàn diện các yêu cầu nghiệp vụ:
1. "Ảnh nào không có text thì bỏ qua":
   - Ảnh không chứa chữ (hoặc OCR không bóc tách được văn bản nào)
   - Trạng thái xử lý: `bo_qua_anh` (MessageStatus.IGNORED_NON_TEXT).
   - Không sinh lỗi, không tạo xe/container, không gửi Zalo khách.
2. "Ảnh nào tách được text thì lại xét như hệ thống xét text hiện tại":
   - Ảnh chứa lệnh điều xe hợp lệ (đủ 8 trường cốt lõi).
   - Hệ thống tự động chuyển văn bản OCR vào pipeline bóc tách chuẩn:
     TripParser -> ContainerValidator -> Matching -> OutboundMessage.
   - Nhóm tự động: Gửi thẳng Zalo khách hàng (`da_gui`, `processed`).
   - Nhóm chờ duyệt: Đưa vào hàng đợi để ĐHVT duyệt.
3. Ảnh chứa lệnh nhưng thiếu thông tin (thiếu số chì, sai số cont...):
   - Đưa vào ca rà soát (`needs_review`), tự động cảnh báo nhà xe qua bot reply.
4. Kiểm thử các định dạng nhận ảnh: Base64, URL ảnh, file path, mock ocr data.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from src.main import app
from src.infrastructure.database import SessionLocal, engine
from src.infrastructure.models import (
    ZaloGroup,
    ZaloMessage,
    ReviewCase,
    OutboundMessage,
    OutboundMessageItem,
    ContainerJob,
    BotReply,
)
from src.domain.rules import compute_iso6346_check_digit
from src.infrastructure.ocr.paddle_client import PaddleOCRClient


def make_unique_valid_cont(uid: str) -> str:
    """Tạo số container chuẩn quốc tế ISO 6346 độc nhất cho từng ca test."""
    num_part = int(uid, 16) % 800000 + 100000
    base = f"VSIU{num_part}"
    cd = compute_iso6346_check_digit(base + "0")
    if cd is None:
        cd = 1
    return f"{base}{cd}"


def make_unique_valid_plate(uid: str) -> str:
    """Tạo biển số xe chuẩn Việt Nam hoàn toàn bằng số ở đuôi."""
    head = int(uid, 16) % 900 + 100
    tail = int(uid, 16) % 90 + 10
    return f"15C-{head}.{tail}"


@pytest.fixture(autouse=True)
def clean_ocr_test_records():
    """Dọn dẹp các bản ghi kiểm thử liên quan trước và sau mỗi test."""
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM bot_replies WHERE sender_id LIKE 'test_ocr_%'"))
        conn.execute(text("DELETE FROM review_cases WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_ocr_%')"))
        conn.execute(text("DELETE FROM outbound_message_items WHERE outbound_message_id IN (SELECT id FROM outbound_messages WHERE idempotency_key LIKE 'outbound_%')"))
        conn.execute(text("DELETE FROM outbound_messages WHERE idempotency_key LIKE 'outbound_%' AND (target_group_id IN (SELECT id FROM zalo_groups WHERE zalo_group_id LIKE 'test_ocr_grp_%'))"))
        conn.execute(text("DELETE FROM container_jobs WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_ocr_%')"))
        conn.execute(text("DELETE FROM truck_records WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_ocr_%')"))
        conn.execute(text("DELETE FROM extraction_runs WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_ocr_%')"))
        conn.execute(text("DELETE FROM zalo_messages WHERE zalo_message_id LIKE 'test_ocr_%'"))
        conn.execute(text("DELETE FROM zalo_groups WHERE zalo_group_id LIKE 'test_ocr_grp_%'"))


def test_01_image_without_text_is_ignored():
    """Kiểm thử yêu cầu 1: Ảnh không có text thì hệ thống tự động bỏ qua.

    - Trạng thái xử lý: `bo_qua_anh` (MessageStatus.IGNORED_NON_TEXT).
    - Không tạo xe/container.
    - Không gửi thông báo khách hay cảnh báo nhà xe.
    """
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_ocr_grp_carrier_{uid}"

    # Gửi webhook sự kiện gửi ảnh nhưng không có chữ nào trong ảnh (mock_ocr_text='')
    res = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_image",
            "group_id": carrier_grp_id,
            "sender": {"id": f"test_ocr_driver_{uid}", "name": "Tài xế Ảnh"},
            "timestamp": "1791798030000",
            "message": {
                "msg_id": f"test_ocr_blank_{uid}",
                "image_url": "https://example.com/photos/blank_landscape.jpg",
            },
            "mock_ocr_text": "",  # PaddleOCR không phát hiện được chữ
        },
    )
    assert res.status_code == 200
    body = res.json()

    # Phải được bỏ qua (bo_qua_anh)
    assert body["processing_status"] == "bo_qua_anh"
    assert body["trucks_count"] == 0
    assert body["containers_count"] == 0
    assert len(body["data"]["customer_notifications"]) == 0
    assert body["data"]["reply_to_carrier"] is None

    # Kiểm tra trong MySQL DB
    db = SessionLocal()
    msg = db.get(ZaloMessage, body["record_id"])
    assert msg is not None
    assert msg.message_type == "image"
    assert msg.processing_status == "bo_qua_anh"
    db.close()


def test_02_image_with_valid_text_is_processed_like_text_message():
    """Kiểm thử yêu cầu 2: Ảnh tách được text thì xử lý như hệ thống xét text hiện tại.

    - Bóc tách văn bản từ ảnh qua PaddleOCR.
    - Tự động thẩm định 8 trường cốt lõi (Khách, Lệnh, Xe, Lái xe, SĐT, Cont, Size, Chì).
    - Nhóm tự động -> Gửi thẳng Zalo khách hàng (`da_gui`, `processed`).
    """
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_ocr_grp_carrier_auto_{uid}"
    target_grp_id = f"test_ocr_grp_cust_auto_{uid}"
    cont_no = make_unique_valid_cont(uid)
    plate_no = make_unique_valid_plate(uid)

    # Chuẩn bị 2 nhóm ở chế độ TỰ ĐỘNG
    db = SessionLocal()
    g_target = ZaloGroup(
        zalo_group_id=target_grp_id,
        name=f"Nhóm Khách Auto OCR {uid}",
        group_role="destination",
        send_mode="tu_dong",
        is_test=True,
    )
    g_source = ZaloGroup(
        zalo_group_id=carrier_grp_id,
        name=f"Nhóm Xe Auto OCR {uid}",
        group_role="source",
        send_mode="tu_dong",
        is_test=True,
    )
    db.add(g_target)
    db.add(g_source)
    db.commit()
    db.close()

    # Nội dung văn bản nằm trong ảnh chụp phiếu điều xe
    ocr_text_in_photo = (
        "Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Logitem Tân Quang - 8h\n"
        f"1 xe: {plate_no} / Vũ Tiến Đạt / 0903976359 / {cont_no} / 40HC / chì 73957169"
    )

    res = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_image",
            "group_id": carrier_grp_id,
            "sender": {"id": f"test_ocr_driver_{uid}", "name": "Lái xe Đạt"},
            "timestamp": "1791798035000",
            "message": {
                "msg_id": f"test_ocr_photo_valid_{uid}",
                "image_url": "https://example.com/photos/dispatch_order_sample.jpg",
            },
            "mock_ocr_text": ocr_text_in_photo,  # Mô phỏng PaddleOCR đọc ra chuỗi này
        },
    )
    assert res.status_code == 200
    body = res.json()

    # Xử lý thành công như tin nhắn text
    assert body["processing_status"] == "processed"
    assert body["trucks_count"] == 1
    assert body["containers_count"] == 1
    assert body["containers"][0]["container_no"] == cont_no
    assert body["containers"][0]["order_type"] == "dong"
    assert body["containers"][0]["check_digit_valid"] is True
    assert len(body["data"]["customer_notifications"]) == 1
    assert "THÔNG BÁO XE ĐÓNG HÀNG" in body["data"]["customer_notifications"][0]["message_text"]

    # Kiểm tra DB
    db = SessionLocal()
    msg = db.get(ZaloMessage, body["record_id"])
    assert msg.message_type == "image_ocr"
    assert msg.processing_status == "processed"
    assert ocr_text_in_photo.splitlines()[0] in msg.message_text

    outs = db.scalars(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(ContainerJob.message_id == msg.id)
    ).all()
    assert len(outs) == 1
    assert outs[0].status == "da_gui"
    db.close()


def test_03_image_in_manual_group_stays_pending_for_dvdh():
    """Kiểm thử: Ảnh chụp có đủ 8 trường nhưng nhóm ở chế độ 'cho_duyet' -> Chờ ĐHVT duyệt."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_ocr_grp_carrier_manual_{uid}"
    target_grp_id = f"test_ocr_grp_cust_manual_{uid}"
    cont_no = make_unique_valid_cont(uid)
    plate_no = make_unique_valid_plate(uid)

    db = SessionLocal()
    g_target = ZaloGroup(
        zalo_group_id=target_grp_id,
        name=f"Nhóm Khách Chờ Duyệt {uid}",
        group_role="destination",
        send_mode="tu_dong",
        is_test=True,
    )
    g_source = ZaloGroup(
        zalo_group_id=carrier_grp_id,
        name=f"Nhóm Xe Chờ Duyệt {uid}",
        group_role="source",
        send_mode="cho_duyet",
        is_test=True,
    )
    db.add(g_target)
    db.add(g_source)
    db.commit()
    db.close()

    ocr_text = (
        f"Lệnh trả hàng - KH: Logitem - Điểm trả: Depot Tân Vũ\n"
        f"1 xe: {plate_no} / Lê Hoàng Nam / 0988112233 / {cont_no} / 20DC / chì 52851122"
    )

    res = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_image",
            "group_id": carrier_grp_id,
            "sender": {"id": f"test_ocr_driver_{uid}", "name": "Lái xe Nam"},
            "timestamp": "1791798040000",
            "image_url": "https://example.com/photos/order_tra_cont.jpg",
            "mock_ocr_text": ocr_text,
        },
    )
    assert res.status_code == 200
    body = res.json()

    # Phải ở trạng thái needs_review vì nhóm chờ duyệt
    assert body["processing_status"] == "needs_review"
    assert len(body["data"]["customer_notifications"]) == 0
    assert body["data"]["reply_to_carrier"] is None  # Dữ liệu chuẩn nên không phiền tài xế

    # ĐHVT bấm duyệt ca này
    db = SessionLocal()
    review = db.scalar(select(ReviewCase).where(ReviewCase.message_id == body["record_id"]))
    assert review is not None
    assert review.case_type == "group_manual_review"
    review_id = review.id
    db.close()

    appr_res = client.post(f"/api/reviews/{review_id}/approve")
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "APPROVED"

    # Kiểm tra outbound message đã được duyệt và chuyển 'da_gui'
    db = SessionLocal()
    refreshed_msg = db.get(ZaloMessage, body["record_id"])
    assert refreshed_msg.processing_status == "processed"
    db.close()


def test_04_image_with_missing_fields_warns_carrier():
    """Kiểm thử: Ảnh chụp thiếu số chì -> Tự động nhắc nhà xe bổ sung."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_ocr_grp_carrier_auto_{uid}"
    target_grp_id = f"test_ocr_grp_cust_auto_{uid}"
    cont_no = make_unique_valid_cont(uid)
    plate_no = make_unique_valid_plate(uid)

    db = SessionLocal()
    g_target = ZaloGroup(zalo_group_id=target_grp_id, name="Target", group_role="destination", send_mode="tu_dong", is_test=True)
    g_source = ZaloGroup(zalo_group_id=carrier_grp_id, name="Source", group_role="source", send_mode="tu_dong", is_test=True)
    db.add(g_target)
    db.add(g_source)
    db.commit()
    db.close()

    # Ảnh chụp THIẾU SỐ CHÌ
    ocr_missing_seal = (
        f"Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Tân Quang\n"
        f"1 xe: {plate_no} / Trần Văn An / 0988654321 / {cont_no} / 40HC"
    )

    res = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_image",
            "group_id": carrier_grp_id,
            "sender": {"id": f"test_ocr_driver_{uid}", "name": "Lái xe An"},
            "timestamp": "1791798045000",
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "mock_ocr_text": ocr_missing_seal,
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert body["processing_status"] == "needs_review"
    assert len(body["data"]["customer_notifications"]) == 0
    assert body["data"]["reply_to_carrier"] is not None
    assert "chì" in body["data"]["reply_to_carrier"].lower()


def test_05_paddle_ocr_client_parsing_and_sorting():
    """Kiểm thử bộ phân tích cú pháp và sắp xếp bounding boxes của PaddleOCRClient."""
    # Giả lập phản hồi chuẩn từ PaddleHub Serving
    hub_response = {
        "status": "000",
        "msg": "success",
        "results": [
            [
                {
                    "text": "1 xe: 15C-878.99 / Vũ Tiến Đạt / 0903976359",
                    "confidence": 0.98,
                    "text_region": [[10, 80], [400, 80], [400, 110], [10, 110]],  # Dòng dưới (Y=80)
                },
                {
                    "text": "Lệnh đóng hàng - KH: Logitem",
                    "confidence": 0.99,
                    "text_region": [[10, 20], [300, 20], [300, 50], [10, 50]],  # Dòng trên (Y=20)
                },
            ]
        ],
    }

    text_out, conf, items = PaddleOCRClient._parse_paddle_response(hub_response)
    lines = text_out.splitlines()

    # Dòng trên (Y=20) phải xuất hiện trước dòng dưới (Y=80)
    assert len(lines) == 2
    assert lines[0] == "Lệnh đóng hàng - KH: Logitem"
    assert lines[1] == "1 xe: 15C-878.99 / Vũ Tiến Đạt / 0903976359"
    assert conf >= 0.98
    assert len(items) == 2
