# 🚛 TÀI LIỆU KIỂM THỬ POSTMAN & CURL: BÓC TÁCH TIN NHẮN ĐA XE EMOJI & KHỚP LỆNH ĐÓNG HÀNG CHÍNH XÁC

Tài liệu này hướng dẫn chi tiết quy trình kiểm thử bóc tách tin nhắn thực tế có chứa các biểu tượng cảm xúc (Emoji: 🚛, 👤, 📞, 📦), phân tách chính xác thành từng xe độc lập và khớp lệnh Đóng hàng (`dong`) thay vì bị gán nhầm sang lệnh Trả hàng (`tra`).

---

## 1. Mẫu Tin Nhắn Kiểm Thử Thực Tế (Real World Payload)

```text
Lệnh đóng hàng - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h
🚛 36B89953
👤 Trần Hữu Dũng
📞 0972174845
📦 GAOU7806508 chì 23338253
🚛 14H49614
👤 Hoàng Đức Huynh
📞 0917558933
📦 GAOU7801569 chì 23334434
```

### Các yêu cầu nghiệp vụ bắt buộc:
1. **Phân đoạn xe độc lập**: Nhận diện ranh giới `🚛` để tách thành 2 xe riêng biệt:
   - **Xe 1**: Biển số `36B-899.53`, Lái xe `Trần Hữu Dũng`, SĐT `0972174845`, Cont `GAOU7806508`, Chì `23338253`.
   - **Xe 2**: Biển số `14H-496.14`, Lái xe `Hoàng Đức Huynh`, SĐT `0917558933`, Cont `GAOU7801569`, Chì `23334434`.
2. **Loại bỏ triệt để rác ký tự Emoji**: Tên lái xe tuyệt đối không bị dính `\n👤` hoặc `\n📞`.
3. **Bảo toàn ngữ cảnh Lệnh và Khách hàng**:
   - Lệnh: `dong` (Đóng hàng, sinh tiêu đề `VSICO - THÔNG BÁO XE ĐÓNG HÀNG`).
   - Khách hàng: `Logitem` (không bị ghi đè thành khách hàng khác trong kế hoạch cũ).
   - Điểm đóng: `kho Logitem Tân Quang` (đã cắt bỏ phần giờ dính đuôi `- 8h`).
   - Giờ đến dự kiến: `08:00`.
4. **Định tuyến nhóm Zalo đích**: Tự động khớp vào nhóm `Nhóm Khách Hàng Logitem - Tân Quang` (Zalo Group ID: `7196206900754562564`).

---

## 2. Lệnh cURL Kiểm Thử Qua Webhook

### Request: Gửi Tin Nhắn Đa Xe Có Emoji Qua Cổng Webhook

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "7196206900754562564",
    "sender": {
      "id": "7196206900754562564_driver",
      "name": "Vũ Tiến Đạt"
    },
    "timestamp": "1791798050000",
    "message": {
      "msg_id": "msg_emoji_multi_test_01",
      "text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n🚛 36B89953\n👤 Trần Hữu Dũng\n📞 0972174845\n📦 GAOU7806508 chì 23338253\n🚛 14H49614\n👤 Hoàng Đức Huynh\n📞 0917558933\n📦 GAOU7801569 chì 23334434"
    }
  }'
```

### Phản Hồi Kỳ Vọng (Response: HTTP 200 OK)

```json
{
  "status": "success",
  "record_id": 1,
  "processing_status": "needs_review",
  "data": {
    "total_vehicles": 2,
    "trucks": [
      {
        "truck_plate": "36B-899.53",
        "trailer_plate": null,
        "driver_name": "Trần Hữu Dũng",
        "driver_phone": "0972174845"
      },
      {
        "truck_plate": "14H-496.14",
        "trailer_plate": null,
        "driver_name": "Hoàng Đức Huynh",
        "driver_phone": "0917558933"
      }
    ],
    "containers": [
      {
        "line_no": 1,
        "container_no": "GAOU7806508",
        "order_type": "dong",
        "customer_hint": "Logitem",
        "warehouse_hint": "kho Logitem Tân Quang",
        "seal_no": "23338253",
        "eta": "08:00"
      },
      {
        "line_no": 2,
        "container_no": "GAOU7801569",
        "order_type": "dong",
        "customer_hint": "Logitem",
        "warehouse_hint": "kho Logitem Tân Quang",
        "seal_no": "23334434",
        "eta": "08:00"
      }
    ]
  }
}
```

---

## 3. Lệnh cURL Kiểm Tra Chi Tiết Outbound Messages Sinh Ra

```bash
curl -X GET http://localhost:8000/api/messages/detail/1 \
  -H "Accept: application/json"
```

### Nội Dung Mẫu Tin Nhắn Gửi Khách Hàng (Outbound Content)

#### Tin Nhắn 1 (Xe 1):
```text
VSICO - THÔNG BÁO XE ĐÓNG HÀNG
Khách hàng: Logitem

- Số cont: GAOU7806508 (40DC)
- Số chì: 23338253
- Biển số xe: 36B-899.53
- Lái xe: Trần Hữu Dũng - SĐT: 0972174845
- Điểm đóng: kho Logitem Tân Quang
- Giờ đến dự kiến: 08:00
```

#### Tin Nhắn 2 (Xe 2):
```text
VSICO - THÔNG BÁO XE ĐÓNG HÀNG
Khách hàng: Logitem

- Số cont: GAOU7801569 (40DC)
- Số chì: 23334434
- Biển số xe: 14H-496.14
- Lái xe: Hoàng Đức Huynh - SĐT: 0917558933
- Điểm đóng: kho Logitem Tân Quang
- Giờ đến dự kiến: 08:00
```

---

## 4. Kiểm Thử Phê Duyệt Gửi Đi Của ĐHVT (DVDH Approval)

Nếu nhóm đang ở chế độ Chờ duyệt (`cho_duyet`), điều hành vận tải có thể kiểm tra và duyệt nhanh từng ca rà soát:

```bash
# Xem danh sách ca rà soát chờ duyệt
curl -X GET "http://localhost:8000/api/reviews?status=pending"

# Phê duyệt ca rà soát (ID ví dụ: 1)
curl -X POST "http://localhost:8000/api/reviews/1/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer": "admin_dvdh",
    "note": "Duyệt gửi thông báo xe đóng hàng cho Logitem"
  }'
```

Tin nhắn lập tức được chuyển trạng thái sang `da_gui` và đẩy ra nhóm Zalo khách hàng.
