# BỘ KIỂM THỬ POSTMAN: TRUY VẤN TIN NHẮN VÀ BÓC TÁCH DỮ LIỆU (FIFO EXTRACTOR)

Tài liệu đặc tả các kịch bản kiểm thử API tiếp nhận bóc tách tin nhắn (Webhook FIFO) và các endpoint truy vấn tin nhắn, kết quả xử lý trong hệ thống VSICO Zalo Bot.

---

## 1. Thiết Lập Biến Môi Trường (Postman Environment)

| Biến | Giá trị mẫu | Ghi chú |
| :--- | :--- | :--- |
| `baseUrl` | `http://localhost:8000` | Địa chỉ Backend FastAPI |
| `groupId` | `2001000000000000001` | ID nhóm Zalo (ví dụ: `6469608867469758994`) |
| `userId` | `1001000000000000001` | ID tài khoản người gửi (ví dụ: `6691387223255581446`) |
| `messageId` | `test_process_001` | Mã tin nhắn Zalo hoặc ID bản ghi MySQL |

---

## 2. Danh Mục Kịch Bản Kiểm Thử

| STT | Nhóm chức năng | Method | Endpoint |
| :---: | :--- | :---: | :--- |
| 01 | Bóc tách tin nhắn | `POST` | `{{baseUrl}}/webhook` (1 xe chuẩn) |
| 02 | Bóc tách tin nhắn | `POST` | `{{baseUrl}}/webhook` (Đa xe qua dấu `/`) |
| 03 | Bóc tách tin nhắn | `POST` | `{{baseUrl}}/webhook` (Thiếu seal) |
| 04 | Truy vấn tin nhắn thô | `GET` | `{{baseUrl}}/api/messages` |
| 05 | Truy vấn tin nhắn thô | `GET` | `{{baseUrl}}/api/messages/group/{{groupId}}` |
| 06 | Truy vấn tin nhắn thô | `GET` | `{{baseUrl}}/api/messages/user/{{userId}}` |
| 07 | Truy vấn tin nhắn thô | `GET` | `{{baseUrl}}/api/messages/group/{{groupId}}/user/{{userId}}` |
| 08 | Chi tiết tin nhắn | `GET` | `{{baseUrl}}/api/messages/detail/{{messageId}}` |
| 09 | Tin nhắn đã xử lý | `GET` | `{{baseUrl}}/api/messages?status=processed` |
| 10 | Tin nhắn đã xử lý | `GET` | `{{baseUrl}}/api/messages/user/{{userId}}?status=processed` |
| 11 | Tin nhắn đã xử lý | `GET` | `{{baseUrl}}/api/messages/group/{{groupId}}?status=processed` |
| 12 | Tin nhắn đã xử lý | `GET` | `{{baseUrl}}/api/messages/group/{{groupId}}/user/{{userId}}?status=processed` |

---

## 3. PHẦN A: Bóc Tách Tin Nhắn Qua Webhook FIFO

### Kịch Bản 01: Xử lý 1 xe chuẩn (Happy Path)

Nhập tin nhắn thô, hệ thống tự động đưa vào hàng đợi FIFO, bóc tách đầy đủ biển số, tài xế, SĐT, số cont, seal, giờ đến và kiểm tra Check Digit ISO 6346 Modulo 11.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body (`raw` - JSON)**:
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "{{groupId}}",
  "sender": {
    "id": "{{userId}}",
    "name": "Điều hành Hải Long"
  },
  "timestamp": "1791798010000",
  "quote_msg_id": null,
  "message": {
    "msg_id": "test_process_001",
    "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026\nĐiểm trả: Kho Nhựa Long An"
  }
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "ENQUEUED_AND_PROCESSED_FIFO",
  "record_id": 1,
  "zalo_message_id": "test_process_001",
  "group_id": "2001000000000000001",
  "sender_id": "1001000000000000001",
  "processing_status": "processed",
  "trucks_count": 1,
  "containers_count": 1,
  "trucks": [
    {
      "truck_plate": "15C-878.99",
      "driver_name": "Trần Quốc Bảo",
      "driver_phone": "0903976359"
    }
  ],
  "containers": [
    {
      "line_no": 1,
      "container_no": "VSIU7399796",
      "seal_no": "73957169",
      "order_type": "tra",
      "warehouse_hint": "Kho Nhựa Long An",
      "check_digit_valid": true,
      "validation_status": "valid",
      "warnings": []
    }
  ]
}
```

---

### Kịch Bản 02: Xử lý nhiều xe trong 1 tin (Phân cách bằng dấu gạch chéo `/`)

Hệ thống tự động phân tách từng dòng và bóc tách nhiều xe/container độc lập.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body (`raw` - JSON)**:
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "{{groupId}}",
  "sender": {
    "id": "{{userId}}",
    "name": "Điều hành Hải Long"
  },
  "timestamp": "1791798020000",
  "quote_msg_id": null,
  "message": {
    "msg_id": "test_process_multi_002",
    "text": "15C-123.45 / Nguyễn Văn Nam / 0912345678 / VSIU7399796 / Seal 112233 / 09:00\n15C-678.90 / Lê Văn Hùng / 0987654321 / GAOU6422920 / Seal 445566 / 10:00"
  }
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "ENQUEUED_AND_PROCESSED_FIFO",
  "processing_status": "processed",
  "trucks_count": 2,
  "containers_count": 2
}
```

---

### Kịch Bản 03: Xử lý tin nhắn thiếu seal (Yêu cầu bổ sung)

Tin nhắn thiếu thông tin bắt buộc (số seal), hệ thống chuyển trạng thái `needs_review` và sinh thông báo nhắc nhở nhà xe.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body (`raw` - JSON)**:
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "{{groupId}}",
  "sender": {
    "id": "{{userId}}",
    "name": "Lái xe Hải Long"
  },
  "timestamp": "1791798030000",
  "quote_msg_id": null,
  "message": {
    "msg_id": "test_process_missing_seal_003",
    "text": "TRẢ HÀNG cont VSIU7399796 xe 15C-878.99 tx Bảo 0903976359"
  }
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "needs_review",
  "reply_to_carrier": "[VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại các thông tin còn thiếu/sai sau:\n- Xe 15C-878.99: thiếu/sai số chì / seal."
}
```

---

## 4. PHẦN B: Truy Vấn Tin Nhắn Thô (Tất Cả Trạng Thái)

### Kịch Bản 04: Lấy tất cả tin nhắn

Trả về toàn bộ tin nhắn đã lưu trong hệ thống kèm kết quả bóc tách.

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "total": 100,
  "items": [
    {
      "id": 1,
      "zalo_message_id": "test_process_001",
      "group_id": "2001000000000000001",
      "sender_id": "1001000000000000001",
      "sender_name": "Điều hành Hải Long",
      "message_type": "text",
      "raw_text": "TRẢ HÀNG\nCont: VSIU7399796...",
      "processing_status": "processed"
    }
  ]
}
```

---

### Kịch Bản 05: Lấy tất cả tin nhắn theo `groupId`

Lọc toàn bộ tin nhắn phát sinh trong nhóm nhà xe hoặc nhóm khách hàng tương ứng.

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`, mảng danh sách tin nhắn thuộc nhóm `groupId`.

---

### Kịch Bản 06: Lấy tất cả tin nhắn theo `userId`

Lấy tất cả tin nhắn do một tài khoản người dùng gửi (nhắn riêng 1-1 và trong các nhóm).

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages/user/{{userId}}`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`, mảng danh sách tin nhắn do `userId` gửi.

---

### Kịch Bản 07: Lấy tất cả tin nhắn theo `userId` trong `groupId`

Lọc chính xác các tin nhắn mà tài khoản `userId` đã gửi bên trong nhóm `groupId`.

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}/user/{{userId}}`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`, danh sách tin nhắn của `userId` gửi trong nhóm `groupId`.

---

### Kịch Bản 08: Lấy chi tiết tin nhắn và kết quả bóc tách theo `messageId`

Tra cứu chi tiết một tin nhắn kèm thông tin xe (`trucks`) và container (`containers`) đã bóc tách.

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages/detail/{{messageId}}`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Path Variable**: `messageId` (mã tin nhắn Zalo ví dụ `test_process_001` hoặc ID số nguyên MySQL ví dụ `1`)
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "OK",
  "message": {
    "id": 1,
    "zalo_message_id": "test_process_001",
    "group_id": "2001000000000000001",
    "sender_id": "1001000000000000001",
    "sender_name": "Điều hành Hải Long",
    "message_type": "text",
    "raw_text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026\nĐiểm trả: Kho Nhựa Long An",
    "sent_at": "2026-10-27T08:00:00",
    "received_at": "2026-10-27T08:00:05",
    "processing_status": "processed",
    "trucks": [
      {
        "id": 1,
        "truck_plate": "15C-878.99",
        "trailer_plate": null,
        "driver_name": "Trần Quốc Bảo",
        "driver_phone": "0903976359",
        "status": "active"
      }
    ],
    "containers": [
      {
        "id": 1,
        "truck_record_id": 1,
        "line_no": 1,
        "container_no": "VSIU7399796",
        "seal_no": "73957169",
        "order_type": "tra",
        "warehouse_hint": "Kho Nhựa Long An",
        "check_digit_valid": true,
        "validation_status": "valid",
        "routing_status": "pending",
        "warnings": []
      }
    ]
  }
}
```

---

## 5. PHẦN C: Truy Vấn Tin Nhắn Đã Xử Lý Xong (`status=processed`)

Chỉ lọc các tin nhắn đã bóc tách dữ liệu thành công (đủ xe và container hợp lệ).

### Kịch Bản 09: Lấy tất cả tin nhắn đã xử lý xong

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages?status=processed`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `status`: `processed`
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "total": 2,
  "items": [
    {
      "id": 1,
      "zalo_message_id": "test_process_001",
      "group_id": "2001000000000000001",
      "sender_id": "1001000000000000001",
      "sender_name": "Điều hành Hải Long",
      "raw_text": "TRẢ HÀNG\nCont: VSIU7399796...",
      "processing_status": "processed",
      "trucks": [
        {
          "truck_plate": "15C-878.99",
          "driver_name": "Trần Quốc Bảo",
          "driver_phone": "0903976359"
        }
      ],
      "containers": [
        {
          "container_no": "VSIU7399796",
          "seal_no": "73957169",
          "check_digit_valid": true,
          "validation_status": "valid"
        }
      ]
    }
  ]
}
```

---

### Kịch Bản 10: Lấy tất cả tin nhắn đã xử lý theo `userId`

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages/user/{{userId}}?status=processed`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `status`: `processed`
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`, danh sách tin nhắn đã bóc tách thành công của `userId`.

---

### Kịch Bản 11: Lấy tất cả tin nhắn đã xử lý trong `groupId`

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}?status=processed`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `status`: `processed`
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`, danh sách tin nhắn đã bóc tách thành công trong nhóm `groupId`.

---

### Kịch Bản 12: Lấy tất cả tin nhắn đã xử lý theo `userId` trong `groupId`

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}/user/{{userId}}?status=processed`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**:
    - `status`: `processed`
    - `limit`: `20` (tùy chọn)
    - `offset`: `0` (tùy chọn)
- **Kết quả mong đợi**: HTTP `200 OK`, danh sách tin nhắn đã bóc tách thành công của `userId` trong nhóm `groupId`.

---

## 6. Tham Số Lọc Khoảng Thời Gian (Time Range Filter)

Tất cả các API ở Phần B và Phần C đều hỗ trợ lọc thời gian linh hoạt qua query params:

| Kiểu lọc | Tham số Query | Ví dụ |
| :--- | :--- | :--- |
| **Theo ngày** | `from_time`, `to_time` | `?from_time=2026-10-27&to_time=2026-10-27` |
| **Theo ngày giờ** | `from_time`, `to_time` | `?from_time=2026-10-27 08:00:00&to_time=2026-10-27 18:00:00` |
| **Định dạng Việt Nam** | `from_time`, `to_time` | `?from_time=27/10/2026&to_time=27/10/2026` |
