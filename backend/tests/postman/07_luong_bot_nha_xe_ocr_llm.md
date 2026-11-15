# Bộ Kiểm Thử Postman: Luồng Bot - Nhà Xe, OCR Ảnh & LLM Extraction

### Dự Án VSICO Zalo Bot (Backend FastAPI + AI & OCR Microservice)

Tài liệu này hướng dẫn chi tiết các bước thiết lập trên Postman (Method, URL, Headers, Params, Body) để kiểm thử luồng nghiệp vụ Bot - Nhà xe, OCR nhận diện hình ảnh và bóc tách thông tin bằng LLM:

1. Tiếp nhận và phân loại ý định tin nhắn qua Webhook (Xã giao, Tạo mới, Bổ sung, Cập nhật/Đổi xe, Hủy chuyến).
2. Kiểm tra đầy đủ trường bắt buộc, thẩm định số container ISO 6346 Mod 11, đối chiếu kế hoạch (`transport_plans`) và quyền sở hữu nhà xe (`carriers`).
3. Phản hồi nhắc nhà xe khi thiếu/sai thông tin (`BotReply` hạn 30 phút) và ghép nối tự động khi nhà xe trích dẫn (quote) bổ sung.
4. Phát hành thông báo sang nhóm Khách hàng, chống gửi trùng lặp, xử lý lỗi gửi Zalo sau 3 lần thử và xác nhận gửi thủ công (`mark-manual-sent`).
5. Kiểm thử trực tiếp **OCR Microservice** (`/api/v1/ocr`), **LLM NLP Extraction + Che SĐT** (`/api/v1/extract`) và **Map Địa chỉ Kho nhiều tầng** (`/api/v1/match-warehouse`).

---

## 1. Thiết Lập Môi Trường Postman (Environment Variables)

Khởi tạo một Postman Environment với các biến sau:

| Tên biến | Giá trị mẫu | Mô tả |
| :--- | :--- | :--- |
| `baseUrl` | `http://localhost:8000` | Địa chỉ dịch vụ Backend FastAPI |
| `aiUrl` | `http://localhost:8001` | Địa chỉ dịch vụ AI & OCR Microservice (`ai-service`) |
| `internalToken` | *(giá trị `INTERNAL_SECRET` trong `.env`)* | Token xác thực nội bộ qua header `X-Internal-Token` |
| `authToken` | *(lấy sau khi đăng nhập ĐHVT/Admin)* | JWT Bearer Token xác thực người dùng |
| `carrierGroupId` | `test_carrier_grp_01` | Mã nhóm Zalo nhà xe (môi trường test) |
| `senderId` | `test_driver_01` | Mã người gửi tin nhắn phía nhà xe |
| `outboundMsgId` | `1234567890` | ID bản ghi `OutboundMessage` lỗi cần xử lý |

---

## 2. Kịch Bản 01: Lọc Sớm Tin Nhắn Xã Giao (`IGNORED_CHAT`)

Tin nhắn chào hỏi thông thường không chứa thông tin xe/container bị chặn ngay tại Fast Gatekeeper, không tạo `ContainerJob` và không gửi ra nhóm khách hàng.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_chat_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{senderId}}",
  "text": "Chào cả nhà buổi sáng nha",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "IGNORED_CHAT",
  "containers_count": 0,
  "reply_to_carrier": null
}
```

---

## 3. Kịch Bản 02: Nhà Xe Báo Đủ Thông Tin -> Phát Hành Sang Khách Hàng

Tiếp nhận tin báo đủ trường (Loại lệnh, Khách hàng/Kho, Biển số, Tài xế, SĐT, Số container chuẩn ISO 6346, Size, Seal, Giờ hẹn) -> Kiểm tra hoàn chỉnh -> Phát hành `OutboundMessage` trạng thái `SENT` tới nhóm đích.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_happy_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{senderId}}",
  "text": "Đóng hàng - Công ty Nhựa Long An - Kho Đức Hòa Long An\nXe 15C-878.99 tài xế Nguyễn Văn An 0903123456\nCont MSCU1234566 40DC seal VS889900 hẹn 08:30",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "PROCESSED",
  "containers_count": 1,
  "data": {
    "customer_notifications": [
      {
        "send_status": "SENT",
        "truck_plate": "15C-878.99",
        "container_no": "MSCU1234566",
        "seal_no": "VS889900"
      }
    ]
  }
}
```

---

## 4. Kịch Bản 03: Thiếu Số Chì -> Bot Nhắc Nhà Xe -> Quote Bổ Sung -> Tự Ghép & Gửi Khách

### Bước 3A: Nhà xe gửi thiếu số chì (`seal_no`)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_missing_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_02",
  "text": "Xe 50H-049.15 lái xe Trần Bình 0912345678 trả hàng cont TEMU4455662 40HC hẹn 09:30",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "NEEDS_REVIEW",
  "reply_to_carrier": "Yêu cầu bổ sung số chì/seal cho container TEMU4455662"
}
```

### Bước 3B: Nhà xe trích dẫn (quote) bổ sung số chì cho cùng container

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_supp_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_02",
  "quote_msg_id": "pm_missing_001",
  "text": "Bổ sung cont TEMU4455662 số chì HL778899",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "PROCESSED"
}
```

---

## 5. Kịch Bản 04: Đổi Xe, Đổi Tài Xế, Chống Trùng Lặp & Hủy Chuyến

### Bước 4A: Gửi báo xe ban đầu đầy đủ

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_upd_init_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_03",
  "text": "Xe 15C-111.22 lái xe Nguyễn A 0901112233 đóng cont CSNU7788996 40DC chì SL1122 hẹn 08:00",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "PROCESSED"
}
```

### Bước 4B: Nhắn đổi xe nhưng quên ghi số container -> Bot hỏi lại

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_upd_nocont_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_03",
  "text": "Đổi sang xe 15C-999.88 tài xế Lê Hùng",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "NEEDS_REVIEW",
  "reply_to_carrier": "Vui lòng cung cấp số container cần đổi thông tin xe."
}
```

### Bước 4C: Nhắn đổi xe kèm đủ số Container -> Phát hành Thông Báo Cập Nhật

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_upd_ok_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_03",
  "text": "Đổi xe cont CSNU7788996 sang xe 15C-999.88 tài xế Lê Hùng 0988777666",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "PROCESSED"
}
```

### Bước 4D: Nhà xe nhắn lặp lại thông tin vừa cập nhật -> Chống trùng lặp

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_upd_dup_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_03",
  "text": "Cập nhật lại cont CSNU7788996 vẫn xe 15C-999.88 tài xế Lê Hùng 0988777666",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "IGNORED_DUPLICATE"
}
```

### Bước 4E: Nhà xe báo hủy chuyến (`CANCEL_REQUEST`)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_cancel_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_03",
  "text": "Hủy chuyến xe cont CSNU7788996 do khách dời lịch",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "NEEDS_REVIEW"
}
```

---

## 6. Kịch Bản 05: Kiểm Tra Lỗi Gửi Zalo & Xác Nhận Gửi Thủ Công

### Bước 5A: Liệt kê thông báo lỗi gửi và danh sách ca rà soát

**1. Liệt kê các thông báo Outbound đang ở trạng thái `FAILED`:**
- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/outbound/messages?status=FAILED`
- **Headers / Bảo mật**: *(Không bắt buộc)*
- **Params / Body**: Query param `status=FAILED`
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "items": [
    {
      "id": "1234567890",
      "status": "FAILED",
      "attempt_count": 3
    }
  ]
}
```

**2. Liệt kê danh sách `ReviewCase` cần xử lý:**
- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/reviews?status=PENDING`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
- **Params / Body**: Query param `status=PENDING`
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "items": [
    {
      "id": "2345678901",
      "case_type": "OUTBOUND_SEND_FAILED",
      "status": "PENDING"
    }
  ]
}
```

### Bước 5B: ĐHVT xác nhận đã gửi Zalo thủ công (`mark-manual-sent`)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/outbound/messages/{{outboundMsgId}}/mark-manual-sent?note=DHVT+da+gui+tay`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
- **Params / Body**: Query param `note=DHVT da gui tay`
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "message": "Đã chuyển trạng thái OutboundMessage sang SENT"
}
```

---

## 7. Kịch Bản 06: Kiểm Thử OCR Ảnh Qua Backend & Trực Tiếp AI Service

### 7.1. Kiểm thử qua Backend (`POST /webhook` với tin nhắn ảnh)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "msg_id": "pm_ocr_img_001",
  "event_name": "user_send_image",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "test_driver_ocr",
  "message_type": "image",
  "text": "[ảnh]",
  "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "is_test": true
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "processing_status": "IGNORED_NON_TEXT"
}
```

### 7.2. Kiểm thử trực tiếp Endpoint OCR trên AI Service (`POST /api/v1/ocr`)

**1. Gửi ảnh hợp lệ kèm token nội bộ:**
- **Method**: `POST`
- **URL**: `{{aiUrl}}/api/v1/ocr`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
  - `X-Internal-Token: {{internalToken}}`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "lang": "vi"
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "text": "",
  "confidence": 0.0,
  "layout_type": "unknown",
  "provider": "paddleocr"
}
```

**2. Gửi sai Token bảo mật (kỳ vọng bị từ chối):**
- **Method**: `POST`
- **URL**: `{{aiUrl}}/api/v1/ocr`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
  - `X-Internal-Token: wrong-token`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "image_base64": "aGVsbG8=",
  "lang": "vi"
}
```
- **Kết quả mong đợi**: HTTP `401 Unauthorized` hoặc `403 Forbidden`
```json
{
  "detail": "Invalid or missing internal token"
}
```

---

## 8. Kịch Bản 07: Kiểm Thử Trực Tiếp AI NLP Extraction & Map Kho

### 8.1. Bóc tách đa xe & Kiểm chứng cơ chế che SĐT (PII Masking)

- **Method**: `POST`
- **URL**: `{{aiUrl}}/api/v1/extract`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
  - `X-Internal-Token: {{internalToken}}`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "message_text": "Đóng hàng kho Đức Hòa\n1) 15C-878.99 An 0903976359 cont VSIU7399796 40DC seal S1122 hẹn 08:30\n2) 50H-049.15 Bình 0912345678 cont TEMU4455662 40HC seal S3344 hẹn 10:00",
  "sender_id": "driver_multi",
  "group_id": "{{carrierGroupId}}",
  "carrier_id": 1001,
  "message_type": "text",
  "active_plans": [
    {
      "container_no": "VSIU7399796",
      "customer_name": "Nhựa Long An",
      "warehouse_name": "Kho Đức Hòa",
      "order_type": "LOAD"
    }
  ]
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "intent": "PARSE_TRUCK_INFO",
  "is_multi_vehicle": true,
  "raw_masked_text": "Đóng hàng kho Đức Hòa\n1) 15C-878.99 An 0903xxxx59 cont VSIU7399796 40DC seal S1122 hẹn 08:30\n2) 50H-049.15 Bình 0912xxxx78 cont TEMU4455662 40HC seal S3344 hẹn 10:00",
  "items": [
    {
      "truck_plate": "15C-878.99",
      "driver_name": "An",
      "driver_phone": "0903976359",
      "container_no": "VSIU7399796",
      "seal_no": "S1122",
      "appointment_time": "08:30"
    },
    {
      "truck_plate": "50H-049.15",
      "driver_name": "Bình",
      "driver_phone": "0912345678",
      "container_no": "TEMU4455662",
      "seal_no": "S3344",
      "appointment_time": "10:00"
    }
  ]
}
```

### 8.2. Map Địa chỉ Kho Nhiều Tầng (`POST /api/v1/match-warehouse`)

- **Method**: `POST`
- **URL**: `{{aiUrl}}/api/v1/match-warehouse`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
  - `X-Internal-Token: {{internalToken}}`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "raw_address": "Kho Nhựa Long An - Đức Hòa",
  "carrier_id": 1001,
  "customer_id": 2001,
  "candidate_warehouses": [
    {
      "id": 3001,
      "name": "Kho Đức Hòa Long An",
      "address": "KCN Đức Hòa, Long An",
      "aliases": ["Kho LA", "Duc Hoa"]
    },
    {
      "id": 3002,
      "name": "Kho Cát Lái",
      "address": "Quận 2, TP.HCM",
      "aliases": ["Cat Lai"]
    }
  ]
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "matched": true,
  "warehouse_id": 3001,
  "warehouse_name": "Kho Đức Hòa Long An",
  "source": "habit"
}
```
