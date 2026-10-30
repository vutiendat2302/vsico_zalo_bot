# 📮 PHẦN 2: BỘ KIỂM THỬ POSTMAN — CỔNG WEBHOOK GATEWAY & QUY TRÌNH ĐIỀU PHỐI (BACKEND PYTHON)

### HỆ THỐNG VSICO ZALO BOT (FASTAPI + MYSQL 8.4 - PORT 8000)

Tài liệu này đặc tả chi tiết các bài kiểm thử trên cổng Webhook tiếp nhận sự kiện (`POST /webhook`) và các luồng bóc tách dữ liệu từ Bot ZCA gửi sang Backend Python.

---

## 1. Khởi Động Server Backend Python

Mở terminal và chạy máy chủ Backend (Cổng `8000`):

```bash
cd /home/datbritget/Documents/vsico_zalo_bot/backend
.venv/bin/python run.py
```

---

## 2. Thiết Lập Môi Trường Postman (Environment)

* **Variable Name**: `backend_url` -> **Initial / Current Value**: `http://localhost:8000`
* **Header bắt buộc cho request `POST`**:
  * `Content-Type`: `application/json; charset=utf-8`

---

## 3. Danh Mục Chi Tiết Các Kịch Bản Kiểm Thử

### Kịch Bản 1: Kiểm Tra Trạng Thái Backend & MySQL

* **Tên Request**: `01. Kiểm tra sức khỏe Server & MySQL`
* **Method**: `GET`
* **URL**: `{{backend_url}}/api/health`
* **cURL**:
  ```bash
  curl -X GET http://localhost:8000/api/health
  ```
* **Kết quả kỳ vọng (`200 OK`)**:
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

### Kịch Bản 2: Báo Xe Chuẩn 1 Xe (Happy Path)

* **Tên Request**: `02. Webhook - Báo xe chuẩn 1 xe`
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Body (`raw` -> `JSON`)**:
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
      "msg_id": "test_zalo_happy_path_001",
      "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026"
    }
  }
  ```
* **Kết quả kỳ vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "status": "success",
    "data": {
      "id": 1,
      "msg_id": "test_zalo_happy_path_001",
      "group_id": "2001000000000000001",
      "action": "STORED_RAW",
      "processing_status": "received",
      "reason": "Đã lưu tin nhắn thô vào bảng zalo_messages trong MySQL thành công"
    }
  }
  ```

---

### Kịch Bản 3: Chống Trùng Lặp Tin Nhắn (Idempotency)

* **Tên Request**: `03. Webhook - Kiểm tra chống lặp tin`
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Mô tả**: Bấm gửi lại chính xác Body ở **Kịch Bản 2** (giữ nguyên `"msg_id": "test_zalo_happy_path_001"`).
* **Kết quả kỳ vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "status": "success",
    "data": {
      "id": 1,
      "msg_id": "test_zalo_happy_path_001",
      "action": "DUPLICATE_MESSAGE",
      "processing_status": "received",
      "reason": "Tin nhắn đã tồn tại trong MySQL, bỏ qua xử lý trùng lặp"
    }
  }
  ```

---

### Kịch Bản 4: Báo Xe Thiếu Seal / Giờ Đến (Yêu Cầu Bổ Sung)

* **Tên Request**: `04. Webhook - Xe thiếu seal yêu cầu bổ sung`
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Body (`raw` -> `JSON`)**:
  ```json
  {
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "2001000000000000001",
    "sender": {
      "id": "1001000000000000001",
      "name": "Lái xe Hải Long"
    },
    "timestamp": "1791798020000",
    "quote_msg_id": null,
    "message": {
      "msg_id": "test_zalo_missing_seal_002",
      "text": "TRẢ HÀNG\nCont: GAOU6422920\nBiển số: 15C-345.67\nTài xế: Nguyễn Văn A\nSĐT: 0901234567"
    }
  }
  ```
* **Kết quả kỳ vọng**: Hệ thống tiếp nhận, lưu thô và chuẩn bị phản hồi nhà xe bổ sung số chì.

---

### Kịch Bản 5: Điều Hành Vận Tải (ĐHVT) Quote Duyệt Tin Nháp ('ok')

* **Tên Request**: `05. Webhook - ĐHVT duyệt quote ok`
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Body (`raw` -> `JSON`)**:
  ```json
  {
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "2000000000000000001",
    "sender": {
      "id": "9001000000000000001",
      "name": "Điều Hành VSICO"
    },
    "timestamp": "1791798030000",
    "quote_msg_id": "test_zalo_happy_path_001",
    "message": {
      "msg_id": "dhvt_quote_ok_003",
      "text": "ok",
      "quote_msg_id": "test_zalo_happy_path_001"
    }
  }
  ```
* **Ý nghĩa**: ĐHVT trích dẫn lại tin nhắn nháp và trả lời `ok` -> Kích hoạt lệnh phát hành tin thông báo tới nhóm khách hàng.

---

### Kịch Bản 6: ĐHVT Quote Sửa Thông Tin Nháp Trên Điện Thoại

* **Tên Request**: `06. Webhook - ĐHVT sửa biển số hoặc số chì`
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Body (`raw` -> `JSON`)**:
  ```json
  {
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "2000000000000000001",
    "sender": {
      "id": "9001000000000000001",
      "name": "Điều Hành VSICO"
    },
    "timestamp": "1791798040000",
    "quote_msg_id": "test_zalo_happy_path_001",
    "message": {
      "msg_id": "dhvt_quote_edit_004",
      "text": "sửa xe 15C-999.88, sửa chì 23333330",
      "quote_msg_id": "test_zalo_happy_path_001"
    }
  }
  ```
* **Ý nghĩa**: Cập nhật thông tin bản ghi nháp và tạo thông báo mới gửi lại nhóm ĐHVT duyệt lại.

---

### Kịch Bản 7: Báo Nhiều Xe Trong 1 Tin Nhắn (Phân Tách Bằng Dấu `/`)

* **Tên Request**: `07. Webhook - Báo 2 xe trong 1 tin`
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Body (`raw` -> `JSON`)**:
  ```json
  {
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "2001000000000000001",
    "sender": {
      "id": "1001000000000000001",
      "name": "Điều hành Hải Long"
    },
    "timestamp": "1791798050000",
    "quote_msg_id": null,
    "message": {
      "msg_id": "test_multi_vehicle_005",
      "text": "15C-123.45 / Nguyễn Văn Nam / 0912345678 / VSIU1234567 / Seal 112233 / 09:00\n15C-678.90 / Lê Văn Hùng / 0987654321 / VSIU7654321 / Seal 445566 / 10:00"
    }
  }
  ```

---

### Kịch Bản 8: Tra Cứu Danh Sách Tin Thô Đã Lưu Trong MySQL

* **Tên Request**: `08. Tra cứu tin nhắn thô MySQL`
* **Method**: `GET`
* **URL**: `{{backend_url}}/api/messages?limit=20`
* **cURL**:
  ```bash
  curl -X GET "http://localhost:8000/api/messages?limit=20"
  ```
* **Kết quả kỳ vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "total_returned": 5,
    "items": [
      {
        "id": 1,
        "zalo_message_id": "test_zalo_happy_path_001",
        "group_id": "2001000000000000001",
        "sender_id": "1001000000000000001",
        "sender_name": "Điều hành Hải Long",
        "message_text": "TRẢ HÀNG\nCont: VSIU7399796...",
        "processing_status": "received",
        "received_at": "2026-10-27T04:26:50+00:00"
      }
    ]
  }
  ```
