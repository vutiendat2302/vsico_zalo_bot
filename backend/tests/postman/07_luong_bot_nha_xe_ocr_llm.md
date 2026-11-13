# BỘ KIỂM THỬ POSTMAN & CURL: LUỒNG BOT - NHÀ XE, OCR ẢNH & LLM EXTRACTION

### DỰ ÁN VSICO ZALO BOT (BACKEND FASTAPI + AI & OCR MICROSERVICE)

Tài liệu này hướng dẫn chi tiết cách kiểm thử luồng nghiệp vụ đầu tiên (**Bot <-> Nhà xe**) theo đặc tả vận hành đa kênh, bao gồm:

1. Tiếp nhận và phân loại ý định tin nhắn (Xã giao, Tạo mới, Bổ sung, Cập nhật/Đổi xe, Hủy chuyến).
2. Kiểm tra đầy đủ trường bắt buộc, thẩm định số container ISO 6346 Mod 11, đối chiếu kế hoạch (`transport_plans`) và quyền sở hữu nhà xe (`carriers`).
3. Phản hồi nhắc nhà xe khi thiếu/sai thông tin (`BotReply` hạn 30 phút) và ghép nối tự động khi nhà xe trích dẫn (quote) bổ sung.
4. Phát hành thông báo sang nhóm Khách hàng, chống gửi trùng lặp, xử lý lỗi gửi Zalo sau 3 lần thử và xác nhận gửi thủ công (`mark-manual-sent`).
5. Kiểm thử trực tiếp **OCR Microservice** (`/api/v1/ocr`), **LLM NLP Extraction + Che SĐT** (`/api/v1/extract`) và **Map Địa chỉ Kho nhiều tầng** (`/api/v1/match-warehouse`).

---

## 1. Thiết Lập Môi Trường & Khởi Động Dịch Vụ

### 1.1. Biến môi trường Postman (`Postman Environment`)

| Tên biến         | Giá trị đề xuất                                                      | Mô tả                                                             |
| :----------------- | :------------------------------------------------------------------------ | :------------------------------------------------------------------ |
| `baseUrl`        | `http://localhost:8000`                                                 | Địa chỉ dịch vụ Backend FastAPI                                |
| `aiUrl`          | `http://localhost:8001`                                                 | Địa chỉ dịch vụ AI & OCR Microservice (`ai-service`)         |
| `internalToken`  | *(Giá trị `INTERNAL_SECRET` trong tệp `.env` ở thư mục gốc)* | Token xác thực nội bộ qua header `X-Internal-Token`           |
| `carrierGroupId` | `test_carrier_grp_01`                                                   | Mã nhóm Zalo nhà xe (môi trường test)                         |
| `senderId`       | `test_driver_01`                                                        | Mã người gửi tin nhắn phía nhà xe                            |
| `outboundMsgId`  | *(Lấy từ kết quả `GET /api/outbound/messages`)*                   | ID bản ghi `OutboundMessage` lỗi cần đánh dấu đã gửi tay |

Headers chung:

* Backend REST API: `Content-Type: application/json; charset=utf-8`
* AI & OCR Microservice: `Content-Type: application/json; charset=utf-8` và `X-Internal-Token: {{internalToken}}`

### 1.2. Khởi chạy đồng thời Backend và AI Service

Mở 2 cửa sổ terminal riêng từ thư mục gốc dự án:

```bash
# Terminal 1: Khởi chạy AI & OCR Microservice (Cổng 8001)
cd ai-service
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2: Khởi chạy Backend API (Cổng 8000)
cd backend
.venv/bin/uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

Kiểm tra sức khỏe 2 dịch vụ trước khi test:

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8001/health
```

---

## 2. Kịch Bản 01: Lọc Sớm Tin Nhắn Xã Giao (`IGNORED_CHAT`)

* **Mục tiêu**: Tin nhắn chào hỏi thông thường không chứa thông tin xe/container phải bị chặn ngay ở Fast Gatekeeper, không tạo `ContainerJob` và không gửi ra nhóm khách hàng.
* **Endpoint**: `POST {{baseUrl}}/webhook`

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_chat_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_01",
    "text": "Chào cả nhà buổi sáng nha",
    "is_test": true
  }'
```

* **Kết quả mong đợi (`200 OK`)**:
  * `processing_status`: `"IGNORED_CHAT"`
  * `containers_count`: `0`
  * `reply_to_carrier`: `null`

---

## 3. Kịch Bản 02: Luồng Chuẩn Nhà Xe Báo Đủ Thông Tin -> Phát Hành Sang Khách Hàng

* **Mục tiêu**: Tiếp nhận tin báo đủ trường (Loại lệnh, Khách hàng/Kho, Biển số, Tài xế, SĐT, Số container chuẩn ISO 6346, Size, Seal, Giờ hẹn) -> Kiểm tra hoàn chỉnh -> Phát hành `OutboundMessage` trạng thái `SENT` tới nhóm đích.
* **Endpoint**: `POST {{baseUrl}}/webhook`

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_happy_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_01",
    "text": "Đóng hàng - Công ty Nhựa Long An - Kho Đức Hòa Long An\nXe 15C-878.99 tài xế Nguyễn Văn An 0903123456\nCont MSCU1234566 40DC seal VS889900 hẹn 08:30",
    "is_test": true
  }'
```

* **Kiểm tra phản hồi (`200 OK`)**:
  * `processing_status`: `"PROCESSED"` (nếu đã khớp kế hoạch/tạo ở chế độ `is_test=true`)
  * `containers_count`: `1`
  * `data.customer_notifications`: Có 1 bản ghi với `send_status = "SENT"` và nội dung chứa biển số `15C-878.99`, container `MSCU1234566`, seal `VS889900`.

*Lưu ý*: Với dữ liệu thật (`is_test=false`), cần có `transport_plans` tương ứng của nhà xe đó trong ngày; nếu chưa có hoặc lệch nhà xe sở hữu, hệ thống sẽ chuyển sang `NEEDS_REVIEW` và tạo `ReviewCase` cảnh báo ĐHVT.

---

## 4. Kịch Bản 03: Thiếu Số Chì -> Bot Nhắc Nhà Xe -> Quote Bổ Sung -> Tự Ghép & Gửi Khách

### Bước 3A: Nhà xe gửi thiếu `seal_no`

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_missing_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_02",
    "text": "Xe 50H-049.15 lái xe Trần Bình 0912345678 trả hàng cont TEMU4455662 40HC hẹn 09:30",
    "is_test": true
  }'
```

* **Kết quả mong đợi (`200 OK`)**:
  * `processing_status`: `"NEEDS_REVIEW"`
  * `reply_to_carrier`: Chuỗi nhắc bổ sung chứa từ khóa `chì` / `seal`.
  * Trong DB tạo bản ghi `bot_replies` với `status = "PENDING"` và `fix_deadline = now + 30 phút`.

### Bước 3B: Nhà xe reply (hoặc quote) bổ sung số chì cho cùng container

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_supp_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_02",
    "quote_msg_id": "pm_missing_001",
    "text": "Bổ sung cont TEMU4455662 số chì HL778899",
    "is_test": true
  }'
```

* **Kết quả mong đợi (`200 OK`)**:
  * `processing_status`: `"PROCESSED"`
  * Hệ thống tự hợp nhất `seal_no = "HL778899"` vào `ContainerJob` trước đó, chuyển `BotReply.status = "RESOLVED"`, và gửi thông báo tới nhóm khách hàng.

---

## 5. Kịch Bản 04: Nhà Xe Đổi Xe / Đổi Tài Xế / Chống Trùng Lặp / Hủy Chuyến

### Bước 4A: Gửi báo xe ban đầu đầy đủ

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_upd_init_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_03",
    "text": "Xe 15C-111.22 lái xe Nguyễn A 0901112233 đóng cont CSNU7788996 40DC chì SL1122 hẹn 08:00",
    "is_test": true
  }'
```

### Bước 4B: Nhắn đổi xe nhưng quên ghi số container -> Bot hỏi lại

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_upd_nocont_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_03",
    "text": "Đổi sang xe 15C-999.88 tài xế Lê Hùng",
    "is_test": true
  }'
```

* **Kết quả mong đợi (`200 OK`)**:
  * `processing_status`: `"NEEDS_REVIEW"`
  * `reply_to_carrier`: Yêu cầu cung cấp `Số Container` cần cập nhật.
  * Tạo `ReviewCase` với `case_type = "MISSING_CONTAINER_FOR_UPDATE"`.

### Bước 4C: Nhắn đổi xe kèm đủ số Container -> Phát hành `THÔNG BÁO CẬP NHẬT`

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_upd_ok_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_03",
    "text": "Đổi xe cont CSNU7788996 sang xe 15C-999.88 tài xế Lê Hùng 0988777666",
    "is_test": true
  }'
```

* **Kết quả mong đợi (`200 OK`)**:
  * `processing_status`: `"PROCESSED"`
  * Trong `outbound_messages` sinh bản ghi `message_kind = "update"` có tiêu đề `THÔNG BÁO CẬP NHẬT THÔNG TIN XE`.

### Bước 4D: Nhà xe nhắn lặp lại y nguyên thông tin vừa cập nhật -> Chống spam

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_upd_dup_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_03",
    "text": "Cập nhật lại cont CSNU7788996 vẫn xe 15C-999.88 tài xế Lê Hùng 0988777666",
    "is_test": true
  }'
```

* **Kết quả mong đợi**:
  * Bản ghi `OutboundMessage` mới mang trạng thái `"IGNORED_DUPLICATE"`, không gửi trùng lặp ra nhóm khách hàng.

### Bước 4E: Nhà xe báo hủy chuyến (`CANCEL_REQUEST`)

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_cancel_001",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_03",
    "text": "Hủy chuyến xe cont CSNU7788996 do khách dời lịch",
    "is_test": true
  }'
```

* **Kết quả mong đợi**:
  * Chuyến tương ứng không còn nằm ở luồng gửi bình thường; hệ thống tạo cảnh báo ĐHVT và `ReviewCase` theo dõi hủy chuyến.

---

## 6. Kịch Bản 05: Kiểm Tra Cảnh Báo Lỗi Gửi Zalo & Xác Nhận Gửi Thủ Công

Khi hệ thống gửi tin nhắn thật sang Zalo khách hàng thất bại sau 3 lần thử (`attempt_count = 3`), bản ghi chuyển sang `status = "FAILED"` và tạo `ReviewCase` với `case_type = "OUTBOUND_SEND_FAILED"`.

### Bước 5A: Liệt kê các thông báo Outbound đang lỗi gửi

```bash
curl -s "http://localhost:8000/api/outbound/messages?status=FAILED"
```

Liệt kê danh sách `ReviewCase` cần xử lý:

```bash
curl -s "http://localhost:8000/api/reviews?status=PENDING"
```

### Bước 5B: ĐHVT tự copy gửi Zalo tay rồi đánh dấu hoàn tất

* **Endpoint**: `POST {{baseUrl}}/api/outbound/messages/{{outboundMsgId}}/mark-manual-sent?note=DHVT+da+gui+Zalo+thu+cong`

```bash
curl -s -X POST "http://localhost:8000/api/outbound/messages/1234567890/mark-manual-sent?note=DHVT%20da%20gui%20tay"
```

* **Kết quả mong đợi (`200 OK`)**:
  * `"ok": true`
  * Bản ghi `OutboundMessage` chuyển từ `"FAILED"` sang `"SENT"`.
  * `ReviewCase` liên quan được đánh dấu `"RESOLVED"` và `ZaloMessage.processing_status` được cập nhật `"PROCESSED"`.

---

## 7. Kịch Bản 06: Kiểm Thử OCR Ảnh Qua Backend & Trực Tiếp AI Service

### 7.1. Kiểm thử qua Backend (`POST /webhook` với tin nhắn ảnh)

Thay chuỗi `iVBOR...` bằng chuỗi Base64 của ảnh PNG/JPG phiếu điều xe:

```bash
curl -s -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "msg_id": "pm_ocr_img_001",
    "event_name": "user_send_image",
    "group_id": "test_carrier_grp_01",
    "sender_id": "test_driver_ocr",
    "message_type": "image",
    "text": "[ảnh]",
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "is_test": true
  }'
```

* **Hành vi cần kiểm chứng**:
  1. Backend gọi sang `ai-service` (`POST /api/v1/ocr`) với header `X-Internal-Token` (và tự fallback PaddleOCR / Gemini Vision nếu cần).
  2. Ghi nhận metadata tệp vào bảng `files` với `source_type = "ZALO_IMAGE"`.
  3. Nếu ảnh chỉ là icon/hình không có chữ (`has_text = false`), Backend đánh dấu `processing_status = "IGNORED_NON_TEXT"` và bỏ qua an toàn.

### 7.2. Kiểm thử trực tiếp Endpoint OCR trên AI Service (`POST /api/v1/ocr`)

```bash
curl -s -X POST "http://localhost:8001/api/v1/ocr" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Internal-Token: YOUR_INTERNAL_SECRET" \
  -d '{
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "lang": "vi"
  }'
```

Kiểm tra trường hợp thiếu/sai Token bảo mật (phải bị từ chối `401` hoặc `403`):

```bash
curl -i -X POST "http://localhost:8001/api/v1/ocr" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: wrong-token" \
  -d '{"image_base64": "aGVsbG8=", "lang": "vi"}'
```

---

## 8. Kịch Bản 07: Kiểm Thử Trực Tiếp AI NLP Extraction & Map Kho (AI Service Port 8001)

### 8.1. Bóc tách đa xe & Kiểm chứng cơ chế Che SĐT (PII Privacy Masking)

```bash
curl -s -X POST "http://localhost:8001/api/v1/extract" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Internal-Token: YOUR_INTERNAL_SECRET" \
  -d '{
    "message_text": "Đóng hàng kho Đức Hòa\n1) 15C-878.99 An 0903976359 cont VSIU7399796 40DC seal S1122 hẹn 08:30\n2) 50H-049.15 Bình 0912345678 cont TEMU4455662 40HC seal S3344 hẹn 10:00",
    "sender_id": "driver_multi",
    "group_id": "test_carrier_grp_01",
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
  }'
```

* **Kết quả mong đợi (`200 OK`)**:
  * `intent`: `"PARSE_TRUCK_INFO"`
  * `is_multi_vehicle`: `true`, `items` có 2 phần tử riêng biệt tương ứng 2 đầu xe.
  * `raw_masked_text`: SĐT đã bị che thành dạng `0903xxxx59` và `0912xxxx78` trước khi chuyển vào prompt Cloud LLM.
  * `items[].driver_phone`: Đã được khôi phục lại số gốc `0903976359` / `0912345678` khi trả về Backend.

### 8.2. Map Địa chỉ Kho Nhiều Tầng (`POST /api/v1/match-warehouse`)

```bash
curl -s -X POST "http://localhost:8001/api/v1/match-warehouse" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Internal-Token: YOUR_INTERNAL_SECRET" \
  -d '{
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
  }'
```

* **Kết quả mong đợi (`200 OK`)**:
  * `matched`: `true`
  * `warehouse_id`: `3001`
  * `warehouse_name`: `"Kho Đức Hòa Long An"`
  * `source`: Một trong các tầng theo thứ tự ưu tiên `"habit"` | `"fuzzy"` | `"vector"` | `"llm"` (nếu không đủ ngưỡng tin cậy trả `"unresolved"`).

---

## 9. Chạy Bộ Kiểm Thử Tự Động (Pytest)

### 9.1. Kiểm thử Backend (Domain, Templates & E2E Bot-Nhà xe cô lập Savepoint MySQL)

```bash
cd backend
.venv/bin/pytest tests -v
```

Kiểm tra dữ liệu DB sau khi test xong (đảm bảo không để lại bản ghi rác):

```bash
cd backend
.venv/bin/python scripts/manage_db.py status
```

### 9.2. Kiểm thử AI & OCR Microservice (Privacy Masker, OCR, Extract, Match Warehouse)

```bash
cd ai-service
.venv/bin/pytest -v
```
