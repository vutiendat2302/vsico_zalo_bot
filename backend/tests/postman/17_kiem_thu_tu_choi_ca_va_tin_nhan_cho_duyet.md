# 🚫 TÀI LIỆU KIỂM THỬ POSTMAN & CURL: TỪ CHỐI CA RÀ SOÁT & TIN NHẮN CHỜ DUYỆT (DHVT REJECTION)

Tài liệu này hướng dẫn chi tiết quy trình kiểm thử tính năng **Từ chối (Reject/Cancel)** dành cho Điều độ viên (ĐHVT) khi kiểm tra dữ liệu ở danh sách chờ duyệt:
1. Từ chối từng ca rà soát lỗi: `POST /api/reviews/{review_id}/reject`
2. Từ chối toàn bộ tin nhắn điều xe: `POST /api/messages/{message_id}/reject`

---

## 📌 QUY TRÌNH NGHIỆP VỤ KHI TỪ CHỐI

Khi ĐHVT bấm **Từ chối**:
1. **Ca rà soát (`ReviewCase`)**: Chuyển trạng thái sang `rejected`, lưu thời gian và lý do từ chối.
2. **Nhiệm vụ Container (`ContainerJob`)**: Chuyển `validation_status = 'rejected'`, `routing_status = 'cancelled'`, `tms_sync_status = 'failed'`.
3. **Thông báo gửi khách (`OutboundMessage`)**: Toàn bộ tin nhắn đang ở trạng thái `cho_duyet` sẽ chuyển sang `huy` (Bị hủy), ghi nhận lý do từ chối vào `last_error` để đảm bảo **không bao giờ gửi nhầm ra nhóm Zalo khách hàng**.
4. **Tin nhắn Zalo gốc (`ZaloMessage`)**: Chuyển `processing_status = 'cancelled'` (Bị hủy), lập tức biến mất khỏi danh sách chờ duyệt (`needs_review`) và xuất hiện trong bộ lọc `cancelled`.

---

## 🚀 CÁC CA KIỂM THỬ POSTMAN & CURL

---

### Ca 1: Từ chối ca rà soát từ trang Rà Soát & Phê Duyệt (`/reviews`)

- **Method**: `POST`
- **URL**: `http://localhost:8000/api/reviews/{review_id}/reject`
- **Headers**: `Content-Type: application/json`

#### cURL Lệnh mẫu:
```bash
curl -X POST "http://localhost:8000/api/reviews/285/reject" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Dữ liệu biển số xe không trùng khớp với lệnh vận chuyển thực tế."
  }'
```

#### Phản hồi kỳ vọng (200 OK):
```json
{
  "ok": true,
  "status": "REJECTED",
  "review_id": 285,
  "message": "Đã từ chối ca rà soát ID=285 và hủy thông báo gửi khách thành công."
}
```

---

### Ca 2: ĐHVT từ chối toàn bộ tin nhắn từ trang Quản Lý Tin Nhắn (`/messages`)

- **Method**: `POST`
- **URL**: `http://localhost:8000/api/messages/{message_id}/reject?operator_name=Điều%20độ%20viên%20ĐHVT`
- **Headers**: `Content-Type: application/json`

#### cURL Lệnh mẫu:
```bash
curl -X POST "http://localhost:8000/api/messages/289/reject" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Chuyến xe bị hủy theo yêu cầu đột xuất từ khách hàng."
  }'
```

#### Phản hồi kỳ vọng (200 OK):
```json
{
  "ok": true,
  "message": "ĐHVT đã từ chối tin nhắn #289 thành công! Đã hủy 1 thông báo gửi Zalo.",
  "message_id": 289,
  "processing_status": "cancelled",
  "cancelled_outbounds": [394]
}
```

---

### Ca 3: Kiểm tra trạng thái dữ liệu sau khi từ chối

#### 1. Kiểm tra tin nhắn đã chuyển sang `cancelled`:
```bash
curl -X GET "http://localhost:8000/api/messages?status=cancelled&limit=5" \
  -H "Accept: application/json"
```

#### 2. Kiểm tra thông báo gửi khách đã chuyển sang `huy`:
```bash
curl -X GET "http://localhost:8000/api/outbound/messages?status=huy&limit=5" \
  -H "Accept: application/json"
```
