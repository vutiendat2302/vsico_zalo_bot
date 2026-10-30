# 📮 BỘ KIỂM THỬ POSTMAN: TRUY VẤN TIN NHẮN & TEST KHẢ NĂNG XỬ LÝ (FIFO EXTRACTOR)
### DỰ ÁN VSICO ZALO BOT (BACKEND REST API - FASTAPI + MYSQL)

Tài liệu này đặc tả chi tiết toàn bộ các bài kiểm thử theo đúng yêu cầu:
1. **Lấy tất cả tin nhắn** (`GET /api/messages`)
2. **Lấy tất cả tin nhắn bởi `groupId`** (`GET /api/messages/group/{group_id}`)
3. **Lấy tất cả tin nhắn bởi `userId`** (`GET /api/messages/user/{user_id}`)
4. **Lấy tất cả tin nhắn bởi `userId` trong `groupId`** (`GET /api/messages/group/{group_id}/user/{user_id}`)
5. **Lấy tất cả các kết quả đã xử lý xong** (`GET /api/messages?status=processed`)
6. **Lấy tất cả các tin nhắn đã xử lý bởi `userId`** (`GET /api/messages/user/{user_id}?status=processed`)
7. **Lấy tất cả các tin nhắn đã xử lý trong `groupId`** (`GET /api/messages/group/{group_id}?status=processed`)
8. **Lấy tất cả các tin nhắn đã xử lý bởi `userId` trong `groupId`** (`GET /api/messages/group/{group_id}/user/{user_id}?status=processed`)
9. **Test khả năng xử lý tin nhắn** (Nhập tin nhắn thô -> Tự động bóc tách Xe, Tài xế, SĐT, Cont, Seal, Giờ đến và thẩm định ISO 6346 Mod 11)

---

## 1. Thiết Lập Môi Trường (Postman Environment)

- **`baseUrl`**: `http://localhost:8000`
- **`groupId`**: `2001000000000000001` (hoặc `6469608867469758994`)
- **`userId`**: `1001000000000000001` (hoặc `6691387223255581446`)
- **Header chung cho `POST`**: `Content-Type: application/json; charset=utf-8`

---

## 2. PHẦN A: TEST KHẢ NĂNG XỬ LÝ TIN NHẮN (NHẬP TIN NHẮN -> TRẢ RA KẾT QUẢ ĐÃ BÓC TÁCH)

### Kịch Bản 01: Test khả năng xử lý 1 xe chuẩn (Happy Path)
* **Method**: `POST`
* **URL**: `{{baseUrl}}/webhook`
* **Mô tả**: Nhập vào tin nhắn thô, hệ thống tự động đưa vào hàng đợi FIFO, bóc tách đầy đủ biển số, tài xế, SĐT, số cont, seal, giờ đến và kiểm tra Check Digit ISO 6346 Mod 11.
* **Request Body (`raw` -> `JSON`)**:
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
* **Kết quả sau xử lý (`200 OK`)**:
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

### Kịch Bản 02: Test khả năng xử lý nhiều xe trong 1 tin (Dấu gạch chéo `/`)
* **Method**: `POST`
* **URL**: `{{baseUrl}}/webhook`
* **Request Body**:
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
* **Kết quả sau xử lý (`200 OK`)**:
Hệ thống tự động phân đoạn thành `trucks_count: 2`, `containers_count: 2` độc lập.

---

### Kịch Bản 03: Test khả năng xử lý tin nhắn thiếu seal (Yêu cầu bổ sung)
* **Method**: `POST`
* **URL**: `{{baseUrl}}/webhook`
* **Request Body**:
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
* **Kết quả sau xử lý**:
Trường `processing_status` là `"needs_review"` và `reply_to_carrier` trả về: *"Chuyến cont VSIU7399796 còn thiếu: số seal/chì. Vui lòng bổ sung!"*.

---

## 3. PHẦN B: TRUY VẤN TIN NHẮN RAW (TẤT CẢ TRẠNG THÁI)

### Kịch Bản 04: Lấy tất cả tin nhắn
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages`
* **Query Params (tùy chọn)**:
  - `limit`: `20`
  - `offset`: `0`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages"
```
* **Ý nghĩa**: Trả về toàn bộ tin nhắn đã lưu trong hệ thống, bao gồm cả tin thô (`raw_text`) và kết quả bóc tách (`trucks`, `containers`).

---

### Kịch Bản 05: Lấy tất cả tin nhắn bởi `groupId`
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages/group/2001000000000000001"
```
* **Ý nghĩa**: Lọc tất cả các tin nhắn phát sinh trong nhóm nhà xe hoặc nhóm khách hàng tương ứng.

---

### Kịch Bản 06: Lấy tất cả tin nhắn bởi `userId`
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages/user/{{userId}}`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages/user/1001000000000000001"
```
* **Ý nghĩa**: Lấy tất cả tin nhắn do một người dùng gửi (cả nhắn riêng 1-1 và nhắn trong bất kỳ nhóm nào).

---

### Kịch Bản 07: Lấy tất cả tin nhắn bởi `userId` trong `groupId`
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}/user/{{userId}}`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages/group/2001000000000000001/user/1001000000000000001"
```
* **Ý nghĩa**: Lọc chính xác các tin nhắn mà tài khoản `userId` đó đã gửi bên trong nhóm `groupId`.

---

### Kịch Bản 08: Lấy chi tiết tin nhắn và kết quả đã xử lý bóc tách bởi `messageId`
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages/detail/{{messageId}}` *(hoặc `{{baseUrl}}/api/messages/id/{{messageId}}`)*
* **Path Variable**:
  - `messageId`: Có thể truyền `zalo_message_id` (ví dụ: `test_process_001`) hoặc ID số nguyên trong MySQL (ví dụ: `1`).
* **cURL**:
```bash
# Tra cứu theo mã tin nhắn Zalo
curl -X GET "http://localhost:8000/api/messages/detail/test_process_001"

# Hoặc tra cứu theo ID MySQL
curl -X GET "http://localhost:8000/api/messages/detail/1"
```
* **Kết quả kỳ vọng (`200 OK`)**:
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

## 4. PHẦN C: TRUY VẤN CÁC KẾT QUẢ ĐÃ XỬ LÝ XONG (`status=processed`)

Khi thêm tham số `status=processed`, API chỉ trả về các tin nhắn **đã được bóc tách dữ liệu thành công** (đã tách xong xe và container hợp lệ).

### Kịch Bản 08: Lấy tất cả các kết quả đã xử lý xong
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages?status=processed`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages?status=processed"
```
* **Kết quả kỳ vọng (`200 OK`)**:
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

### Kịch Bản 09: Lấy tất cả các tin nhắn đã xử lý bởi `userId`
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages/user/{{userId}}?status=processed`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages/user/1001000000000000001?status=processed"
```
* **Ý nghĩa**: Xem lịch sử các chuyến xe mà tài khoản `userId` (tài xế hoặc điều hành nhà xe) đã gửi và hệ thống bóc tách thành công.

---

### Kịch Bản 10: Lấy tất cả các tin nhắn đã xử lý trong `groupId`
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}?status=processed`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages/group/2001000000000000001?status=processed"
```
* **Ý nghĩa**: Xem toàn bộ kết quả bóc tách xe & cont của nhà xe thuộc nhóm `groupId`.

---

### Kịch Bản 11: Lấy tất cả các tin nhắn đã xử lý bởi `userId` trong `groupId`
* **Method**: `GET`
* **URL**: `{{baseUrl}}/api/messages/group/{{groupId}}/user/{{userId}}?status=processed`
* **cURL**:
```bash
curl -X GET "http://localhost:8000/api/messages/group/2001000000000000001/user/1001000000000000001?status=processed"
```
* **Ý nghĩa**: Báo cáo chính xác từng lượt điều xe thành công của riêng một nhân sự trong nhóm cụ thể.

---

## 5. TÙY CHỌN NÂNG CAO: LỌC THEO KHOẢNG THỜI GIAN (TIME RANGE FILTER)
Tất cả các API ở Phần B và Phần C đều hỗ trợ lọc thời gian linh hoạt:
- **Theo ngày**: `?from_time=2026-10-27&to_time=2026-10-27`
- **Theo giờ phút giây**: `?from_time=2026-10-27 08:00:00&to_time=2026-10-27 18:00:00`
- **Định dạng Việt Nam**: `?from_time=27/10/2026&to_time=27/10/2026`
