"""Bộ Kiểm Thử Tự Động Bước 1: Tiếp Nhận Webhook & Lưu Tin Thô Vào MySQL.

Kiểm tra các yêu cầu cốt lõi của Bước 1:
1. Kết nối MySQL hoạt động ổn định (`GET /api/health`).
2. Tiếp nhận payload từ `zca-js` qua `POST /webhook`, tự động đăng ký nhóm vào `zalo_groups`
   và lưu tin nhắn nguyên bản vào `zalo_messages` với trạng thái `received`.
3. Chống trùng lặp (Idempotency): Gửi lại cùng `msg_id` trả về `DUPLICATE_MESSAGE`, không tạo bản ghi thứ 2.
4. Truy vấn danh sách tin nhắn đã lưu qua `GET /api/messages`.
"""

import uuid
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_01_health_check_mysql_connected() -> None:
    """Kiểm tra endpoint `/api/health` xác nhận kết nối MySQL thành công."""
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["database"] == "mysql_connected"


def test_02_receive_webhook_and_deduplicate_in_mysql() -> None:
    """Kiểm tra lưu tin thô mới vào MySQL và chống trùng lặp khi gửi lại cùng `msg_id`."""
    unique_msg_id = f"test_zca_msg_{uuid.uuid4().hex[:10]}"
    payload = {
        "app_id": "zca_personal_bot",
        "event_name": "user_send_text",
        "group_id": "2001000000000000001",
        "sender": {
            "id": "1001000000000000001",
            "name": "Điều hành Hải Long",
        },
        "timestamp": "1791798010000",
        "quote_msg_id": None,
        "message": {
            "msg_id": unique_msg_id,
            "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903******",
        },
    }

    # Lần gửi 1: Phải lưu thành công vào bảng zalo_messages và bóc tách FIFO tức thời
    res1 = client.post("/webhook", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()["data"]
    assert data1["action"] in ("STORED_RAW", "PROCESSED_FIFO")
    assert data1["msg_id"] == unique_msg_id
    assert data1["processing_status"] in ("received", "processed", "needs_review")
    inserted_id = data1["id"]

    # Lần gửi 2 (cùng msg_id): Phải phát hiện trùng lặp, trả lại đúng ID bản ghi cũ
    res2 = client.post("/webhook", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()["data"]
    assert data2["action"] == "DUPLICATE_MESSAGE"
    assert data2["id"] == inserted_id


def test_03_list_stored_messages_from_mysql() -> None:
    """Kiểm tra truy vấn danh sách tin nhắn thô vừa lưu trong MySQL."""
    response = client.get("/api/messages?limit=5")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["total_returned"] >= 1
