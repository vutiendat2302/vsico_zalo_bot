# 🖼️ TÀI LIỆU KIỂM THỬ POSTMAN & CURL: BÓC TÁCH VĂN BẢN TỪ ẢNH QUA PADDLEOCR TỰ HOST

Tài liệu này hướng dẫn chi tiết cách kiểm thử tính năng **Nhận diện ký tự quang học (OCR) từ hình ảnh** do tài xế/nhà xe gửi qua Zalo (ảnh chụp phiếu điều xe, lệnh đóng/trả cont, chụp màn hình tin nhắn...) sử dụng mô hình **PaddleOCR tự host (Self-Hosted Local PaddleOCR)**.

---

## 📌 QUY TẮC NGHIỆP VỤ BẮT BUỘC

1. **Ảnh không có text $\rightarrow$ Bỏ qua**:
   - Nếu ảnh gửi vào là ảnh phong cảnh, ảnh mờ không đọc được chữ, hoặc OCR không nhận diện được đoạn văn bản nào:
   - Hệ thống tự động gán trạng thái `processing_status = "bo_qua_anh"` (`MessageStatus.IGNORED_NON_TEXT`).
   - Không sinh lỗi, không tạo xe/container giả lập, không làm phiền khách hàng hay nhà xe.
2. **Ảnh tách được text $\rightarrow$ Xử lý giống 100% như tin nhắn văn bản hiện tại**:
   - Văn bản bóc tách từ ảnh được đưa vào pipeline chuẩn hóa: `TripParser` $\rightarrow$ `ContainerValidator` $\rightarrow$ Thẩm định 8 trường cốt lõi (*Khách hàng, Lệnh, Xe, Tài xế, SĐT, Cont, Size, Chì*).
   - Nếu nhóm ở chế độ **Tự động (`tu_dong`)** và đủ 8 trường $\rightarrow$ Gửi thẳng ra Zalo khách hàng (`da_gui`, `processed`).
   - Nếu nhóm ở chế độ **Chờ duyệt (`cho_duyet`)** $\rightarrow$ Đưa vào hàng đợi để Điều độ viên (ĐHVT) duyệt qua API `POST /api/reviews/{id}/approve`.
   - Nếu ảnh có chữ nhưng **thiếu hoặc sai thông tin cốt lõi** $\rightarrow$ Hệ thống tự động phản hồi form cảnh báo nhắc nhà xe bổ sung trong 30 phút.

---

## 🚀 HƯỚNG DẪN KHỞI CHẠY MÁY CHỦ PADDLEOCR CỤC BỘ

Mô hình PaddleOCR chạy tự host hoàn toàn trên máy chủ nội bộ thông qua 1 trong 2 cách sau:

### Cách 1: Chạy Microservice Python độc lập (Khuyên dùng)
```bash
cd backend
.venv/bin/python scripts/paddle_ocr_server.py --host 127.0.0.1 --port 8866
```
*(Nếu chưa cài đặt thư viện PaddleOCR: `pip install paddlepaddle paddleocr`)*

### Cách 2: Chạy bằng Docker Container
```bash
docker run -d --name vsico-paddleocr \
  -p 8866:8866 \
  --restart always \
  paddlepaddle/paddleocr:latest \
  hub serving start -m ocr_system
```

### Kiểm tra sức khỏe dịch vụ OCR:
```bash
curl -X GET "http://127.0.0.1:8866/health"
```
**Phản hồi kỳ vọng:**
```json
{
  "status": "UP",
  "engine": "paddleocr",
  "model_loaded": true,
  "default_lang": "vi"
}
```

---

## ⚙️ CẤU HÌNH BIẾN MÔI TRƯỜNG (`backend/.env`)

```ini
# Bật/tắt tính năng OCR
OCR_ENABLED=true
OCR_PROVIDER=paddleocr
# Địa chỉ máy chủ PaddleOCR tự host
PADDLE_OCR_URL=http://127.0.0.1:8866/predict/ocr_system
OCR_TIMEOUT_SECONDS=15
OCR_LANG=vi
```

---

## 📝 CÁC CA KIỂM THỬ CHI TIẾT (CURL & POSTMAN)

---

### Ca 1: Gửi ảnh KHÔNG CÓ TEXT $\rightarrow$ Hệ thống tự động BỎ QUA (`bo_qua_anh`)

- **Mục tiêu**: Kiểm tra hệ thống nhận diện ảnh không có chữ và bỏ qua một cách êm đẹp.
- **Method**: `POST`
- **URL**: `http://localhost:8000/webhook`

#### cURL Lệnh mẫu:
```bash
curl -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_image",
    "group_id": "6469608867469758994",
    "sender": {"id": "driver_test_01", "name": "Lái xe gửi ảnh rỗng"},
    "timestamp": "1791798030000",
    "message": {
      "msg_id": "ocr_test_blank_001",
      "image_url": "https://example.com/photos/blank_landscape.jpg"
    },
    "mock_ocr_text": ""
  }'
```

#### Phản hồi mẫu (200 OK — Bỏ qua ảnh không text):
```json
{
  "ok": true,
  "status": "ENQUEUED_AND_PROCESSED_FIFO",
  "record_id": 120,
  "zalo_message_id": "ocr_test_blank_001",
  "processing_status": "bo_qua_anh",
  "trucks_count": 0,
  "containers_count": 0,
  "trucks": [],
  "containers": [],
  "data": {
    "id": 120,
    "action": "PROCESSED_FIFO",
    "processing_status": "bo_qua_anh",
    "total_vehicles": 0,
    "reply_to_carrier": null,
    "customer_notifications": []
  }
}
```

---

### Ca 2: Gửi ảnh CÓ TEXT CHUẨN 8 TRƯỜNG vào Nhóm Tự Động $\rightarrow$ Tự động gửi Zalo

- **Mục tiêu**: Bóc tách ảnh phiếu điều xe, nhận diện đủ 8 trường cốt lõi và gửi thẳng Zalo khách hàng.
- **Method**: `POST`
- **URL**: `http://localhost:8000/webhook`

#### cURL Lệnh mẫu:
```bash
curl -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_image",
    "group_id": "6469608867469758994",
    "sender": {"id": "driver_dat_01", "name": "Lái xe Vũ Tiến Đạt"},
    "timestamp": "1791798040000",
    "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "message": {
      "msg_id": "ocr_test_valid_dong_002"
    },
    "mock_ocr_text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Logitem Tân Quang - 8h\n1 xe: 15C-878.99 / Vũ Tiến Đạt / 0903976359 / VSIU7399796 / 40HC / chì 73957169"
  }'
```

#### Phản hồi mẫu (200 OK — Đã bóc tách và gửi Zalo thành công):
```json
{
  "ok": true,
  "status": "ENQUEUED_AND_PROCESSED_FIFO",
  "record_id": 121,
  "zalo_message_id": "ocr_test_valid_dong_002",
  "processing_status": "processed",
  "trucks_count": 1,
  "containers_count": 1,
  "containers": [
    {
      "container_no": "VSIU7399796",
      "order_type": "dong",
      "check_digit_valid": true,
      "validation_status": "valid"
    }
  ],
  "data": {
    "processing_status": "processed",
    "customer_notifications": [
      {
        "target_group_id": "6469608867469758994",
        "message_text": "VSICO - THÔNG BÁO XE ĐÓNG HÀNG\nKhách hàng: Logitem\n\n- Số cont: VSIU7399796 (40)\n- Số chì: 73957169\n- Biển số xe: 15C-878.99\n- Lái xe: Vũ Tiến Đạt - SĐT: 0903976359\n- Điểm đóng: Kho Logitem Tân Quang\n- Giờ đến dự kiến: 8h\n",
        "cont": "VSIU7399796",
        "shipping_id": "SHP-121"
      }
    ]
  }
}
```

---

### Ca 3: Gửi ảnh CÓ TEXT vào Nhóm Chờ Duyệt $\rightarrow$ ĐHVT duyệt qua API

- **Mục tiêu**: Nhóm đích ở chế độ `cho_duyet`, ảnh gửi lên bóc tách chuẩn vẫn đưa vào hàng đợi `needs_review` để ĐHVT duyệt trước khi gửi khách.

#### Bước 3.1: Gửi ảnh vào webhook
```bash
curl -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_image",
    "group_id": "grp_test_manual_002",
    "sender": {"id": "driver_nam_02", "name": "Lái xe Lê Hoàng Nam"},
    "timestamp": "1791798050000",
    "message": {
      "msg_id": "ocr_test_manual_003"
    },
    "mock_ocr_text": "Lệnh trả hàng - KH: Logitem - Điểm trả: Depot Tân Vũ\n1 xe: 29C-556.88 / Lê Hoàng Nam / 0988112233 / MSCU5285725 / 20DC / chì 52851122"
  }'
```
*Kết quả:* `processing_status = "needs_review"`, tạo `ReviewCase`.

#### Bước 3.2: ĐHVT gọi API phê duyệt ca
```bash
curl -X POST "http://localhost:8000/api/reviews/50/approve" \
  -H "Accept: application/json"
```

#### Bước 3.3: Lấy kết quả form gửi Zalo sau khi duyệt
```bash
curl -X GET "http://localhost:8000/api/outbound/messages?status=da_gui&limit=1" \
  -H "Accept: application/json"
```

---

### Ca 4: Gửi ảnh THIẾU SỐ CHÌ $\rightarrow$ Cảnh báo lỗi nhà xe

- **Mục tiêu**: Ảnh chụp không có số chì $\rightarrow$ hệ thống đưa vào `needs_review` và tự động gửi tin nhắc lỗi cho nhà xe qua bot reply.
```bash
curl -X POST "http://localhost:8000/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_image",
    "group_id": "6469608867469758994",
    "sender": {"id": "driver_an_03", "name": "Lái xe Trần Văn An"},
    "timestamp": "1791798060000",
    "message": {
      "msg_id": "ocr_test_missing_seal_004"
    },
    "mock_ocr_text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Logitem Tân Quang\n1 xe: 15C-444.55 / Trần Văn An / 0988654321 / VSIU2621051 / 40HC"
  }'
```

*Phản hồi chứa Form nhắc lỗi nhà xe:*
```text
[VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại các thông tin còn thiếu/sai sau:
- Xe dòng #1: thiếu/sai số chì.
(Hạn bổ sung thông tin trong vòng 30 phút để bot kịp thời thông báo tới khách hàng)
```
