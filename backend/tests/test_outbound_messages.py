"""Unit & Integration Tests cho Module Kết Quả Tin Nhắn & Outbound Messages (Task 2 - PM TMS VSICO).

Kiểm thử toàn diện:
1. Thống kê tổng hợp số lượng tin nhắn kết quả (Summary).
2. Tạo mẫu kiểm thử 4 trạng thái (Đã gửi, Chờ duyệt, Bị hủy, Thất bại).
3. Lọc danh sách theo trạng thái (`status=cho_duyet`, `status=da_gui`, `status=huy`, `status=that_bai`).
4. Thao tác Phê duyệt gửi tin (Approve) $\rightarrow$ chuyển trạng thái thành `da_gui`.
5. Thao tác Hủy tin nhắn (Cancel) $\rightarrow$ chuyển trạng thái thành `huy`.
6. Thao tác Gửi lại tin nhắn (Resend).
7. Xem chi tiết một bản ghi kết quả tin nhắn.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.main import app
from src.infrastructure.database import engine


@pytest.fixture(autouse=True)
def clean_outbound_tables():
    """Dọn dẹp bảng outbound_message_items và outbound_messages trước và sau khi test."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM outbound_message_items"))
        conn.execute(text("DELETE FROM outbound_messages"))
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM outbound_message_items"))
        conn.execute(text("DELETE FROM outbound_messages"))


def test_01_outbound_summary_empty():
    """Kiểm tra API summary trả về 0 khi chưa có bản ghi nào."""
    client = TestClient(app)
    res = client.get("/api/outbound/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["total"] == 0
    assert data["da_gui"] == 0
    assert data["cho_duyet"] == 0
    assert data["huy"] == 0
    assert data["that_bai"] == 0


def test_02_seed_samples_and_query_by_status():
    """Kiểm tra tạo mẫu và lọc kết quả tin nhắn theo 4 trạng thái."""
    client = TestClient(app)
    # 1. Tạo dữ liệu mẫu
    seed_res = client.post("/api/outbound/seed-samples")
    assert seed_res.status_code == 200
    seed_data = seed_res.json()
    assert seed_data["ok"] is True
    assert len(seed_data["created_ids"]) == 4

    # 2. Kiểm tra summary
    sum_res = client.get("/api/outbound/summary")
    assert sum_res.status_code == 200
    sum_data = sum_res.json()
    assert sum_data["total"] == 4
    assert sum_data["da_gui"] == 1
    assert sum_data["cho_duyet"] == 1
    assert sum_data["huy"] == 1
    assert sum_data["that_bai"] == 1

    # 3. Lọc danh sách theo status: cho_duyet
    pending_res = client.get("/api/outbound/messages?status=cho_duyet")
    assert pending_res.status_code == 200
    p_data = pending_res.json()
    assert p_data["total"] == 1
    assert p_data["messages"][0]["status"] == "cho_duyet"
    pending_id = p_data["messages"][0]["id"]

    # 4. Phê duyệt tin chờ duyệt
    approve_res = client.post(f"/api/outbound/messages/{pending_id}/approve?operator_name=TestOperator")
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "da_gui"

    # 5. Kiểm tra summary sau khi duyệt
    sum2 = client.get("/api/outbound/summary").json()
    assert sum2["cho_duyet"] == 0
    assert sum2["da_gui"] == 2


def test_03_cancel_and_resend_outbound_message():
    """Kiểm tra hủy tin và gửi lại tin nhắn kết quả."""
    client = TestClient(app)
    client.post("/api/outbound/seed-samples")

    # Lấy tin da_gui
    sent_res = client.get("/api/outbound/messages?status=da_gui")
    sent_id = sent_res.json()["messages"][0]["id"]

    # Hủy tin
    cancel_res = client.post(f"/api/outbound/messages/{sent_id}/cancel", json={"reason": "Khách dời lịch"})
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "huy"

    # Thử gửi lại tin
    resend_res = client.post(f"/api/outbound/messages/{sent_id}/resend")
    assert resend_res.status_code == 200
    assert resend_res.json()["status"] == "da_gui"

    # Xem chi tiết tin
    detail_res = client.get(f"/api/outbound/messages/{sent_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()["message"]
    assert detail["id"] == sent_id
    assert detail["status"] == "da_gui"


def test_04_deduplication_and_update_rules():
    """Kiểm thử quy tắc gửi tin nhắn: Chống gửi trùng lặp & Tự động tạo tin cập nhật khi đổi xe/lái xe."""
    client = TestClient(app)
    from uuid import uuid4
    uid = uuid4().hex[:6]

    # 1. Gửi tin lần đầu (Initial dispatch)
    res1 = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_text",
            "group_id": "pytest_grp_carrier_01",
            "sender": {"id": "pytest_user_01", "name": "Lái xe test"},
            "timestamp": "1791798030000",
            "message": {
                "msg_id": f"test_rule_{uid}_01",
                "text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n1 xe: 36H74446/ Hoàng Thanh Bình đt: 0981695322 / SELU4396800 chì 23331731",
            },
        },
    )
    assert res1.status_code == 200
    b1 = res1.json()
    assert b1["processing_status"] == "processed"

    # Kiểm tra outbound message 1 là initial
    msg1_detail = client.get(f"/api/messages/detail/{b1['record_id']}").json()
    assert len(msg1_detail["outbound_messages"]) == 1
    assert msg1_detail["outbound_messages"][0]["message_kind"] == "initial"
    assert msg1_detail["outbound_messages"][0]["status"] == "da_gui"

    # 2. Gửi tin trùng lặp nguyên văn (Deduplication)
    res2 = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_text",
            "group_id": "pytest_grp_carrier_01",
            "sender": {"id": "pytest_user_01", "name": "Lái xe test"},
            "timestamp": "1791798035000",
            "message": {
                "msg_id": f"test_rule_{uid}_02_dup",
                "text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n1 xe: 36H74446/ Hoàng Thanh Bình đt: 0981695322 / SELU4396800 chì 23331731",
            },
        },
    )
    assert res2.status_code == 200
    b2 = res2.json()
    msg2_detail = client.get(f"/api/messages/detail/{b2['record_id']}").json()
    assert len(msg2_detail["outbound_messages"]) == 1
    assert msg2_detail["outbound_messages"][0]["message_kind"] == "duplicate"
    assert msg2_detail["outbound_messages"][0]["status"] == "bo_qua_trung_lap"

    # 3. Gửi tin cập nhật đổi lái xe và SĐT (Update dispatch)
    res3 = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_text",
            "group_id": "pytest_grp_carrier_01",
            "sender": {"id": "pytest_user_01", "name": "Lái xe test"},
            "timestamp": "1791798040000",
            "message": {
                "msg_id": f"test_rule_{uid}_03_update",
                "text": "Đổi tài xế: 1 xe: 36H74446 / Lê Văn Bảo đt: 0977889900 / SELU4396800 chì 23331731",
            },
        },
    )
    assert res3.status_code == 200
    b3 = res3.json()
    msg3_detail = client.get(f"/api/messages/detail/{b3['record_id']}").json()
    assert len(msg3_detail["outbound_messages"]) == 1
    assert msg3_detail["outbound_messages"][0]["message_kind"] == "update"
    assert msg3_detail["outbound_messages"][0]["status"] == "da_gui"
    assert "CẬP NHẬT THÔNG TIN XE" in msg3_detail["outbound_messages"][0]["content"]
    assert "Hoàng Thanh Bình -> Lê Văn Bảo" in msg3_detail["outbound_messages"][0]["content"]
    assert msg3_detail["outbound_messages"][0]["attempt_count"] >= 1


def test_05_emoji_multi_vehicle_icon_segmentation_and_template_accuracy() -> None:
    """Kiểm thử bóc tách tin nhắn đa xe chứa biểu tượng Emoji (🚛, 👤, 📞, 📦) và kết xuất mẫu thông báo chuẩn xác."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:6]
    test_msg = (
        "Lệnh đóng hàng - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n"
        "🚛 36B89953\n"
        "👤 Trần Hữu Dũng\n"
        "📞 0972174845\n"
        f"📦 GAOU7806508 chì 23338253\n"
        "🚛 14H49614\n"
        "👤 Hoàng Đức Huynh\n"
        "📞 0917558933\n"
        f"📦 GAOU7801569 chì 23334434"
    )

    res = client.post(
        "/webhook",
        json={
            "app_id": "zca_personal_bot",
            "event_name": "user_send_text",
            "group_id": f"pytest_grp_carrier_{uid}",
            "sender": {"id": f"pytest_user_{uid}", "name": "Vũ Tiến Đạt"},
            "timestamp": "1791798050000",
            "message": {
                "msg_id": f"test_emoji_multi_{uid}",
                "text": test_msg,
            },
        },
    )
    assert res.status_code == 200
    body = res.json()
    data = body["data"]

    # Đảm bảo phân đoạn thành công 2 xe độc lập
    assert data["total_vehicles"] == 2
    assert len(data["trucks"]) == 2
    assert len(data["containers"]) == 2

    # Xe 1
    t1 = data["trucks"][0]
    assert t1["truck_plate"] == "36B-899.53"
    assert t1["driver_name"] == "Trần Hữu Dũng"
    assert t1["driver_phone"] == "0972174845"

    # Xe 2
    t2 = data["trucks"][1]
    assert t2["truck_plate"] == "14H-496.14"
    assert t2["driver_name"] == "Hoàng Đức Huynh"
    assert t2["driver_phone"] == "0917558933"

    # Container 1 & 2
    c1 = data["containers"][0]
    c2 = data["containers"][1]
    assert c1["container_no"] == "GAOU7806508"
    assert c1["order_type"] == "dong"
    assert c1["customer_hint"] == "Logitem"
    assert c1["warehouse_hint"] == "kho Logitem Tân Quang"
    assert c1["seal_no"] == "23338253"

    assert c2["container_no"] == "GAOU7801569"
    assert c2["order_type"] == "dong"
    assert c2["customer_hint"] == "Logitem"
    assert c2["warehouse_hint"] == "kho Logitem Tân Quang"
    assert c2["seal_no"] == "23334434"

    # Kiểm tra chi tiết Outbound Messages sinh ra
    rec_id = body["record_id"]
    detail = client.get(f"/api/messages/detail/{rec_id}").json()
    assert len(detail["outbound_messages"]) == 2

    content1 = detail["outbound_messages"][0]["content"]
    content2 = detail["outbound_messages"][1]["content"]

    assert "VSICO - THÔNG BÁO XE ĐÓNG HÀNG" in content1
    assert "Khách hàng: Logitem" in content1
    assert "36B-899.53" in content1
    assert "Trần Hữu Dũng" in content1
    assert "0972174845" in content1
    assert "kho Logitem Tân Quang" in content1
    assert "👤" not in content1
    assert "📞" not in content1

    assert "VSICO - THÔNG BÁO XE ĐÓNG HÀNG" in content2
    assert "Khách hàng: Logitem" in content2
    assert "14H-496.14" in content2
    assert "Hoàng Đức Huynh" in content2
    assert "0917558933" in content2
    assert "kho Logitem Tân Quang" in content2
    assert "👤" not in content2
    assert "📞" not in content2
