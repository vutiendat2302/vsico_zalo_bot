"""Bộ kiểm thử Chế độ gửi của Nhóm (send_mode: tu_dong / cho_duyet) và Thẩm định 8 trường cốt lõi (Core Fields).

Quy tắc nghiệp vụ:
1. Đủ 8 trường cốt lõi: Khách hàng, Lệnh, Xe, Tài xế, SĐT, Cont, Size, Chì.
   - Giờ dự kiến (ETA) và Ghi chú (Note) có thể null.
2. Group ở chế độ Tự động (`send_mode = 'tu_dong'`):
   - Đủ 8 trường và hợp lệ -> Tự động gửi (`da_gui`, `processed`), xuất hiện trong `customer_notifications`.
   - Thiếu hoặc sai trường -> Chuyển sang chờ duyệt (`cho_duyet`, `needs_review`), cảnh báo nhà xe qua `bot_replies`.
3. Group ở chế độ Chờ duyệt (`send_mode = 'cho_duyet'`):
   - Kể cả tin nhắn có thỏa mãn 100% -> Vẫn đưa vào danh sách chờ duyệt (`cho_duyet`, `needs_review`).
   - Không cảnh báo nhà xe vì bản thân dữ liệu nhà xe gửi không sai sót gì.
4. Khi Điều độ viên (DVDH) phê duyệt qua API `POST /api/reviews/{id}/approve`:
   - `ReviewCase.status = 'approved'`
   - `OutboundMessage.status = 'da_gui'`
   - `ZaloMessage.processing_status = 'processed'`
5. API Quản lý nhóm Zalo:
   - `GET /api/groups`
   - `PUT /api/groups/{id}/send-mode` (chuyển đổi qua lại giữa 'tu_dong' và 'cho_duyet')
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
def clean_test_data():
    """Dọn dẹp các bản ghi kiểm thử liên quan trước và sau mỗi test."""
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM bot_replies WHERE sender_id LIKE 'test_driver_%'"))
        conn.execute(text("DELETE FROM review_cases WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_mode_%')"))
        conn.execute(text("DELETE FROM outbound_message_items WHERE outbound_message_id IN (SELECT id FROM outbound_messages WHERE idempotency_key LIKE 'outbound_%')"))
        conn.execute(text("DELETE FROM outbound_messages WHERE idempotency_key LIKE 'outbound_%' AND (target_group_id IN (SELECT id FROM zalo_groups WHERE zalo_group_id LIKE 'test_grp_%'))"))
        conn.execute(text("DELETE FROM container_jobs WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_mode_%')"))
        conn.execute(text("DELETE FROM truck_records WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_mode_%')"))
        conn.execute(text("DELETE FROM extraction_runs WHERE message_id IN (SELECT id FROM zalo_messages WHERE zalo_message_id LIKE 'test_mode_%')"))
        conn.execute(text("DELETE FROM zalo_messages WHERE zalo_message_id LIKE 'test_mode_%'"))
        conn.execute(text("DELETE FROM zalo_groups WHERE zalo_group_id LIKE 'test_grp_%'"))


def test_01_auto_group_with_valid_complete_message():
    """Trường hợp 1: Nhóm Tự động (tu_dong) + Tin nhắn đủ 8 trường cốt lõi.

    Kết quả mong đợi:
    - Tin nhắn được gửi tự động: OutboundMessage.status == 'da_gui'.
    - Message.processing_status == 'processed'.
    - Webhook response chứa customer_notifications với 1 phần tử.
    - Không có cảnh báo lỗi nhà xe trong bot_replies.
    """
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_grp_carrier_auto_{uid}"
    target_grp_id = f"test_grp_cust_auto_{uid}"
    cont_no = make_unique_valid_cont(uid)

    # Chuẩn bị 2 nhóm ở chế độ TỰ ĐỘNG
    db = SessionLocal()
    g_target = ZaloGroup(
        zalo_group_id=target_grp_id,
        name=f"Nhóm Khách Hàng Auto {uid}",
        group_role="destination",
        send_mode="tu_dong",
        is_test=True,
    )
    g_source = ZaloGroup(
        zalo_group_id=carrier_grp_id,
        name=f"Nhóm Nhà Xe Auto {uid}",
        group_role="source",
        send_mode="tu_dong",
        is_test=True,
    )
    db.add(g_target)
    db.add(g_source)
    db.commit()
    db.close()

    plate_no = make_unique_valid_plate(uid)

    # Gửi tin nhắn đầy đủ 8 trường cốt lõi (Khách hàng, Lệnh, Xe, Tài xế, SĐT, Cont, Size, Chì)
    # Giờ dự kiến và Ghi chú là null
    valid_text = (
        "Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Logitem Tân Quang\n"
        f"1 xe: {plate_no} / Phạm Quốc Hùng / 0988123456 / {cont_no} / 40HC / chì 88991122"
    )

    res = client.post(
        "/webhook",
        json={
            "msg_id": f"test_mode_valid_{uid}",
            "group_id": carrier_grp_id,
            "sender_id": f"test_driver_{uid}",
            "sender_name": "Tài xế Hùng",
            "text": valid_text,
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert body["processing_status"] == "processed"
    assert len(body["data"]["customer_notifications"]) == 1
    assert "THÔNG BÁO XE ĐÓNG HÀNG" in body["data"]["customer_notifications"][0]["message_text"]
    assert body["data"]["reply_to_carrier"] is None

    # Kiểm tra bản ghi trong DB
    db = SessionLocal()
    msg = db.get(ZaloMessage, body["record_id"])
    assert msg.processing_status == "processed"

    # OutboundMessage tương ứng phải là 'da_gui'
    outs = db.scalars(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(ContainerJob.message_id == msg.id)
    ).all()
    assert len(outs) == 1
    assert outs[0].status == "da_gui"

    # Không có ReviewCase nào
    reviews = db.scalars(select(ReviewCase).where(ReviewCase.message_id == msg.id)).all()
    assert len(reviews) == 0

    # Không có BotReply cảnh báo nhà xe
    replies = db.scalars(select(BotReply).where(BotReply.message_id == msg.id)).all()
    assert len(replies) == 0
    db.close()


def test_02_auto_group_with_missing_fields_needs_review_and_warns_carrier():
    """Trường hợp 2: Nhóm Tự động (tu_dong) nhưng tin nhắn thiếu trường cốt lõi (thiếu số chì).

    Kết quả mong đợi:
    - Tin nhắn thiếu số chì -> OutboundMessage.status == 'cho_duyet'.
    - Message.processing_status == 'needs_review'.
    - Không gửi thông báo khách: customer_notifications là rỗng.
    - Cảnh báo nhà xe qua bot_replies với lý do thiếu thông tin (chì).
    - Tạo ReviewCase ở trạng thái 'pending' để DVDH rà soát.
    """
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_grp_carrier_auto_{uid}"
    target_grp_id = f"test_grp_cust_auto_{uid}"
    cont_no = make_unique_valid_cont(uid)

    db = SessionLocal()
    g_target = ZaloGroup(
        zalo_group_id=target_grp_id,
        name=f"Nhóm Khách Auto {uid}",
        group_role="destination",
        send_mode="tu_dong",
        is_test=True,
    )
    g_source = ZaloGroup(
        zalo_group_id=carrier_grp_id,
        name=f"Nhóm Xe Auto {uid}",
        group_role="source",
        send_mode="tu_dong",
        is_test=True,
    )
    db.add(g_target)
    db.add(g_source)
    db.commit()
    db.close()

    plate_no = make_unique_valid_plate(uid)
    # Tin nhắn THIẾU SỐ CHÌ
    missing_seal_text = (
        "Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Logitem Tân Quang\n"
        f"1 xe: {plate_no} / Trần Văn An / 0988654321 / {cont_no} / 20DC"
    )

    res = client.post(
        "/webhook",
        json={
            "msg_id": f"test_mode_missing_{uid}",
            "group_id": carrier_grp_id,
            "sender_id": f"test_driver_{uid}",
            "sender_name": "Tài xế An",
            "text": missing_seal_text,
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert body["processing_status"] == "needs_review"
    assert len(body["data"]["customer_notifications"]) == 0
    assert body["data"]["reply_to_carrier"] is not None
    assert "chì" in body["data"]["reply_to_carrier"].lower()

    # Kiểm tra DB
    db = SessionLocal()
    msg = db.get(ZaloMessage, body["record_id"])
    assert msg.processing_status == "needs_review"

    outs = db.scalars(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(ContainerJob.message_id == msg.id)
    ).all()
    assert len(outs) == 1
    assert outs[0].status == "cho_duyet"

    # Có ReviewCase chờ duyệt
    reviews = db.scalars(select(ReviewCase).where(ReviewCase.message_id == msg.id)).all()
    assert len(reviews) == 1
    assert reviews[0].status == "pending"
    assert reviews[0].case_type == "missing_fields"

    # Có BotReply cảnh báo nhà xe
    replies = db.scalars(select(BotReply).where(BotReply.message_id == msg.id)).all()
    assert len(replies) == 1
    assert "chì" in replies[0].reply_text.lower()
    db.close()


def test_03_manual_group_with_valid_message_stays_pending_no_carrier_warning():
    """Trường hợp 3: Nhóm ở chế độ Chờ duyệt (cho_duyet) + Tin nhắn 100% hợp lệ.

    Kết quả mong đợi:
    - KỂ CẢ TIN NHẮN THỎA MÃN ĐỦ 8 TRƯỜNG THÌ VẪN CHO VÀO DANH SÁCH ĐỂ DVDH DUYỆT!
    - OutboundMessage.status == 'cho_duyet'.
    - Message.processing_status == 'needs_review'.
    - Không gửi thông báo khách tự động: customer_notifications là rỗng.
    - KHÔNG cảnh báo nhà xe (reply_to_carrier is None) vì bản thân dữ liệu nhà xe gửi chuẩn 100%.
    - ReviewCase được tạo với case_type == 'group_manual_review'.
    """
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_grp_carrier_manual_{uid}"
    target_grp_id = f"test_grp_cust_manual_{uid}"
    cont_no = make_unique_valid_cont(uid)

    # Cấu hình nhóm nhà xe nguồn ở chế độ 'cho_duyet'
    db = SessionLocal()
    g_target = ZaloGroup(
        zalo_group_id=target_grp_id,
        name=f"Nhóm Khách Hàng Chờ Duyệt {uid}",
        group_role="destination",
        send_mode="tu_dong",
        is_test=True,
    )
    g_source = ZaloGroup(
        zalo_group_id=carrier_grp_id,
        name=f"Nhóm Xe Carrier Chờ Duyệt {uid}",
        group_role="source",
        send_mode="cho_duyet",
        is_test=True,
    )
    db.add(g_target)
    db.add(g_source)
    db.commit()
    db.close()

    plate_no = make_unique_valid_plate(uid)
    # Tin nhắn 100% ĐẦY ĐỦ VÀ CHUẨN XÁC
    valid_text = (
        f"Lệnh trả hàng - KH: Logitem - Điểm trả: Depot Tân Vũ\n"
        f"1 xe: {plate_no} / Nguyễn Hoàng Nam / 0977112233 / {cont_no} / 40HC / chì 99887766"
    )

    res = client.post(
        "/webhook",
        json={
            "msg_id": f"test_mode_manual_{uid}",
            "group_id": carrier_grp_id,
            "sender_id": f"test_driver_{uid}",
            "sender_name": "Tài xế Nam",
            "text": valid_text,
        },
    )
    assert res.status_code == 200
    body = res.json()

    # Kể cả thỏa mãn thì vẫn là needs_review
    assert body["processing_status"] == "needs_review"
    assert len(body["data"]["customer_notifications"]) == 0
    # KHÔNG cảnh báo lỗi nhà xe
    assert body["data"]["reply_to_carrier"] is None

    # Kiểm tra DB
    db = SessionLocal()
    msg = db.get(ZaloMessage, body["record_id"])
    assert msg.processing_status == "needs_review"

    outs = db.scalars(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(ContainerJob.message_id == msg.id)
    ).all()
    assert len(outs) == 1
    assert outs[0].status == "cho_duyet"
    assert "chế độ Chờ duyệt" in (outs[0].last_error or "")

    # ReviewCase được tạo lý do nhóm chờ duyệt
    reviews = db.scalars(select(ReviewCase).where(ReviewCase.message_id == msg.id)).all()
    assert len(reviews) == 1
    assert reviews[0].case_type == "group_manual_review"
    assert reviews[0].status == "pending"

    # Không có tin nhắc lỗi nhà xe
    replies = db.scalars(select(BotReply).where(BotReply.message_id == msg.id)).all()
    assert len(replies) == 0
    db.close()


def test_04_dvdh_approval_releases_outbound_and_completes_message():
    """Trường hợp 4: DVDH phê duyệt ca chờ duyệt qua API POST /api/reviews/{id}/approve.

    Kết quả mong đợi:
    - ReviewCase.status chuyển thành 'approved'.
    - OutboundMessage.status chuyển thành 'da_gui'.
    - ZaloMessage.processing_status chuyển thành 'processed'.
    """
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    carrier_grp_id = f"test_grp_carrier_appr_{uid}"
    target_grp_id = f"test_grp_cust_appr_{uid}"
    cont_no = make_unique_valid_cont(uid)

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
        name=f"Nhóm Xe Carrier Chờ Duyệt {uid}",
        group_role="source",
        send_mode="cho_duyet",
        is_test=True,
    )
    db.add(g_target)
    db.add(g_source)
    db.commit()
    db.close()

    plate_no = make_unique_valid_plate(uid)
    valid_text = (
        f"Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Logitem Tân Quang\n"
        f"1 xe: {plate_no} / Vũ Văn Đạt / 0912999888 / {cont_no} / 20DC / chì 66554433"
    )

    res = client.post(
        "/webhook",
        json={
            "msg_id": f"test_mode_to_approve_{uid}",
            "group_id": carrier_grp_id,
            "sender_id": f"test_driver_{uid}",
            "sender_name": "Tài xế Đạt",
            "text": valid_text,
        },
    )
    assert res.status_code == 200
    msg_id = res.json()["record_id"]

    # Tìm ReviewCase vừa sinh ra
    db = SessionLocal()
    review = db.scalar(select(ReviewCase).where(ReviewCase.message_id == msg_id))
    assert review is not None
    review_id = review.id
    db.close()

    # Điều độ viên (DVDH) bấm duyệt ca này
    approve_res = client.post(f"/api/reviews/{review_id}/approve")
    assert approve_res.status_code == 200
    appr_data = approve_res.json()
    assert appr_data["ok"] is True
    assert appr_data["status"] == "APPROVED"

    # Kiểm tra trong DB: Toàn bộ liên kết đã được cập nhật thành công
    db = SessionLocal()
    refreshed_rc = db.get(ReviewCase, review_id)
    assert refreshed_rc.status == "approved"

    refreshed_msg = db.get(ZaloMessage, msg_id)
    assert refreshed_msg.processing_status == "processed"

    out = db.scalars(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(ContainerJob.message_id == msg_id)
    ).first()
    assert out is not None
    assert out.status == "da_gui"
    assert out.approved_by == "admin_reviewer"
    assert out.sent_at is not None
    db.close()


def test_05_group_management_api_crud_and_send_mode_toggle():
    """Trường hợp 5: API Quản lý nhóm Zalo và chuyển đổi chế độ gửi send_mode."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    test_group_id = f"test_grp_api_{uid}"

    # 1. Tạo mới nhóm qua API POST /api/groups
    create_res = client.post(
        "/api/groups",
        json={
            "zalo_group_id": test_group_id,
            "name": f"Nhóm Quản Lý Test {uid}",
            "group_role": "destination",
            "send_mode": "tu_dong",
            "is_active": True,
            "is_test": True,
        },
    )
    assert create_res.status_code == 201
    grp_data = create_res.json()
    assert grp_data["ok"] is True
    group_pk = grp_data["group"]["id"]
    assert grp_data["group"]["send_mode"] == "tu_dong"
    assert grp_data["group"]["send_mode_label"] == "Tự động"

    # 2. Truy vấn danh sách qua API GET /api/groups
    list_res = client.get(f"/api/groups?search={test_group_id}")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    found = [g for g in list_data["groups"] if g["zalo_group_id"] == test_group_id]
    assert len(found) == 1
    assert found[0]["send_mode"] == "tu_dong"

    # 3. Chuyển đổi trạng thái sang 'cho_duyet' qua PUT /api/groups/{id}/send-mode
    toggle_res1 = client.put(
        f"/api/groups/{group_pk}/send-mode",
        json={"send_mode": "cho_duyet"},
    )
    assert toggle_res1.status_code == 200
    t1_data = toggle_res1.json()
    assert t1_data["send_mode"] == "cho_duyet"
    assert t1_data["send_mode_label"] == "Chờ duyệt"

    # 4. Chuyển ngược lại sang 'tu_dong'
    toggle_res2 = client.put(
        f"/api/groups/{group_pk}/send-mode",
        json={"send_mode": "tu_dong"},
    )
    assert toggle_res2.status_code == 200
    t2_data = toggle_res2.json()
    assert t2_data["send_mode"] == "tu_dong"
    assert t2_data["send_mode_label"] == "Tự động"
