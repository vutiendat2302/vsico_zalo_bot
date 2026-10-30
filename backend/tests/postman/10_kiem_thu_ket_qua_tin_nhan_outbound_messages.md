# 📑 TÀI LIỆU KIỂM THỬ POSTMAN & CURL: QUẢN LÝ KẾT QUẢ TIN NHẮN (OUTBOUND MESSAGES)

Tài liệu này hướng dẫn chi tiết cách kiểm thử các API quản lý và theo dõi **Kết quả tin nhắn (Tin đã gửi, Chờ duyệt, Bị hủy, Thất bại)** trong hệ thống `nhaxe-bot` (VSICO Zalo Bot).

---

## 1. Tổng quan các trạng thái kết quả tin nhắn

Mỗi thông báo điều xe gửi tới nhóm Zalo khách hàng hoặc nhà xe được quản lý qua bảng `outbound_messages` với 4 trạng thái cốt lõi:
- **`da_gui`**: Tin nhắn đã được gửi thành công ra Zalo OA.
- **`cho_duyet`**: Tin nhắn đã soạn thảo xong, đang chờ điều độ viên bấm nút phê duyệt gửi.
- **`huy`**: Tin nhắn bị hủy do thay đổi chuyến xe, đổi lịch hoặc điều độ từ chối.
- **`that_bai`**: Gửi không thành công (lỗi mạng hoặc gặp lỗi HTTP 429 Too Many Requests từ máy chủ Zalo OA).

---

## 2. Danh sách các API Endpoint

| Phương thức | Đường dẫn API | Mục đích |
|---|---|---|
| `GET` | `/api/outbound/summary` | Thống kê số lượng theo 4 trạng thái (`da_gui`, `cho_duyet`, `huy`, `that_bai`) |
| `GET` | `/api/outbound/messages` | Lấy danh sách kết quả tin nhắn (hỗ trợ lọc status, search, ngày, phân trang) |
| `GET` | `/api/outbound/messages/{id}` | Lấy chi tiết một tin nhắn kết quả |
| `POST` | `/api/outbound/messages/{id}/approve` | Phê duyệt và kích hoạt gửi tin qua Token Bucket Throttler ra Zalo OA |
| `POST` | `/api/outbound/messages/{id}/cancel` | Hủy tin nhắn thông báo điều xe (chuyển sang `huy`) |
| `POST` | `/api/outbound/messages/{id}/resend` | Thử gửi lại tin nhắn bị lỗi |
| `POST` | `/api/outbound/seed-samples` | Tạo dữ liệu mẫu đủ 4 trạng thái để kiểm thử giao diện |

---

## 3. Hướng dẫn kiểm thử chi tiết qua cURL

### 3.1. Thống kê tổng hợp số lượng (Summary)
```bash
curl -X GET "http://localhost:8000/api/outbound/summary" \
  -H "Accept: application/json"
```

**Phản hồi mẫu (200 OK):**
```json
{
  "ok": true,
  "total": 4,
  "da_gui": 1,
  "cho_duyet": 1,
  "huy": 1,
  "that_bai": 1
}
```

---

### 3.2. Lọc danh sách tin nhắn đang "Chờ duyệt" (`cho_duyet`)
```bash
curl -X GET "http://localhost:8000/api/outbound/messages?status=cho_duyet&limit=10" \
  -H "Accept: application/json"
```

---

### 3.3. Phê duyệt gửi tin nhắn (`POST .../approve`)
```bash
curl -X POST "http://localhost:8000/api/outbound/messages/14/approve?operator_name=NguyenVanHung" \
  -H "Accept: application/json"
```

**Phản hồi mẫu (200 OK):**
```json
{
  "ok": true,
  "message": "Đã phê duyệt và gửi tin nhắn #14 ra Zalo OA thành công.",
  "status": "da_gui",
  "sent_at": "2026-10-30T06:25:34",
  "zalo_message_id": "zalo_oa_a1b2c3d4e5f6"
}
```

---

### 3.4. Hủy tin nhắn thông báo điều xe (`POST .../cancel`)
```bash
curl -X POST "http://localhost:8000/api/outbound/messages/13/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Khách hàng thông báo hoãn nhận hàng sang chiều"
  }'
```

---

### 3.5. Gửi lại tin nhắn thất bại (`POST .../resend`)
```bash
curl -X POST "http://localhost:8000/api/outbound/messages/16/resend" \
  -H "Accept: application/json"
```
