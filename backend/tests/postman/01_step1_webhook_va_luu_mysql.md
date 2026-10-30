# 📮 BƯỚC 1: KIỂM THỬ POSTMAN — CỔNG TIẾP NHẬN WEBHOOK & LƯU TIN THÔ VÀO MYSQL

### HỆ THỐNG VSICO ZALO BOT (FASTAPI + SQLALCHEMY 2.0 + MYSQL 8.4)

Tài liệu này hướng dẫn kiểm thử chi tiết **Bước 1** trên công cụ **Postman**: Tiếp nhận sự kiện tin nhắn từ `zca-js` qua cổng `POST /webhook`, kiểm tra chống trùng lặp (`zalo_message_id`) và lưu nguyên bản vào bảng `zalo_messages` trong cơ sở dữ liệu **MySQL**.

---

## 1. Cấu Hình Môi Trường Postman

- **Base URL**: `http://localhost:8000`
- **Header bắt buộc cho các request `POST`**:
  - `Content-Type`: `application/json; charset=utf-8`

---

## 2. Kịch Bản 1.1: Kiểm Tra Kết Nối MySQL (`GET /api/health`)

### Thông tin Request

- **Method**: `GET`
- **URL**: `http://localhost:8000/api/health`

### Kết quả kỳ vọng (`200 OK`)

```json
{
  "ok": true,
  "status": "UP",
  "database": "mysql_connected",
  "stats": {
    "total_groups": 1,
    "total_messages": 1
  }
}
```

---

## 3. Kịch Bản 1.2: Gửi Tin Nhắn Mới Từ ZCA-JS Vào MySQL (`POST /webhook`)

### Thông tin Request

- **Method**: `POST`
- **URL**: `http://localhost:8000/webhook`
- **Body (`raw` -> `JSON`)**:

```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "2001000000000000001",
  "sender": {
    "id": "1001000000000000001",
    "name": "Điều hành Hải Long"
  },
  "timestamp": "1791798010000",
  "quote_msg_id": null,
  "message": {
    "msg_id": "zalo_raw_msg_001",
    "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903******\nGiờ đến: 08:00"
  }
}
```

### Kết quả kỳ vọng (`200 OK` — Lần gửi đầu tiên)

Hệ thống tự động thêm nhóm `2001000000000000001` vào bảng `zalo_groups` (nếu chưa có) và lưu tin nhắn vào bảng `zalo_messages` với trạng thái `received`:

```json
{
  "ok": true,
  "status": "success",
  "data": {
    "id": 1,
    "msg_id": "zalo_raw_msg_001",
    "group_id": "2001000000000000001",
    "sender_id": "1001000000000000001",
    "sender_name": "Điều hành Hải Long",
    "quote_msg_id": null,
    "action": "STORED_RAW",
    "processing_status": "received",
    "reason": "Đã lưu tin nhắn thô vào bảng zalo_messages trong MySQL thành công",
    "reply_to_carrier": null,
    "customer_notifications": [],
    "admin_alert": false
  }
}
```

---

## 4. Kịch Bản 1.3: Kiểm Tra Chống Trùng Lặp Idempotency (`POST /webhook`)

### Thực hiện

Bấm nút **Send** lần thứ 2 trên Postman với **cùng Request Body ở Kịch bản 1.2** (giữ nguyên `"msg_id": "zalo_raw_msg_001"`).

### Kết quả kỳ vọng (`200 OK` — Phát hiện trùng lặp)

Hệ thống phát hiện `zalo_message_id` đã tồn tại trong bảng `zalo_messages`, không tạo bản ghi mới và trả về `action: "DUPLICATE_MESSAGE"`:

```json
{
  "ok": true,
  "status": "success",
  "data": {
    "id": 1,
    "msg_id": "zalo_raw_msg_001",
    "action": "DUPLICATE_MESSAGE",
    "processing_status": "received",
    "reason": "Tin nhắn đã tồn tại trong MySQL, bỏ qua xử lý trùng lặp",
    "reply_to_carrier": null,
    "customer_notifications": [],
    "admin_alert": false
  }
}
```

---

## 5. Kịch Bản 1.4: Tra Cứu Danh Sách Tin Thô Đã Lưu Trong MySQL (`GET /api/messages`)

### Thông tin Request

- **Method**: `GET`
- **URL**: `http://localhost:8000/api/messages?limit=10`

### Kết quả kỳ vọng (`200 OK`)

```json
{
  "ok": true,
  "total_returned": 1,
  "items": [
    {
      "id": 1,
      "zalo_message_id": "zalo_raw_msg_001",
      "group_id": "2001000000000000001",
      "sender_id": "1001000000000000001",
      "sender_name": "Điều hành Hải Long",
      "quote_msg_id": null,
      "message_type": "text",
      "message_text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903******\nGiờ đến: 08:00",
      "processing_status": "received",
      "received_at": "2026-10-27T04:26:50+00:00"
    }
  ]
}
```
