# 📮 TEST CASE 12: ZALO WEBHOOK - LỌC TIN NHẮN RÁC & CẢNH BÁO NGƯỜI LẠ

### 1. Mục tiêu kiểm thử

Xác minh 2 tầng bảo vệ an ninh và tối ưu hóa tài nguyên của hệ thống:

1. **Lọc tin nhắn chào hỏi thông thường (`IGNORE_CHAT`)**: Tránh tiêu tốn tài nguyên bóc tách hay gọi LLM cho các câu chat ngắn như `ok`, `alo`, `dạ vâng`.
2. **Cảnh báo người lạ gửi tin trong nhóm nhà xe (`IGNORE_UNKNOWN_SENDER`)**: Nếu tài khoản Zalo không nằm trong danh sách nhân sự ủy quyền của nhà xe, lập tức từ chối và cảnh báo Admin để kiểm tra an ninh thông tin.

---

### 2. Kịch bản 1: Tin nhắn chat thông thường (`IGNORE_CHAT`)

#### Request Payload:

```json
{
  "app_id": "1234567890123456789",
  "event_name": "user_send_text",
  "group_id": "2001000000000000001",
  "sender": {
    "id": "1001000000000000001"
  },
  "timestamp": "1791852000000",
  "message": {
    "msg_id": "webhook_chat_01",
    "text": "Dạ em cảm ơn ad, bên em đã nhận thông tin rồi nhé ạ!"
  }
}
```

#### Kết quả kỳ vọng (200 OK):

```json
{
  "success": true,
  "seq": 7,
  "msg_id": "webhook_chat_01",
  "carrier_id": "NX01",
  "action": "IGNORE_CHAT",
  "reason": "Tin nhắn chào hỏi / trao đổi thông thường",
  "admin_alert": false,
  "admin_message": "",
  "total_vehicles": 0,
  "vehicles": [],
  "operation_detail": {
    "target_cont": null,
    "reply_to_carrier": null,
    "reason": "Tin nhắn chào hỏi / trao đổi thông thường"
  }
}
```

*(Hệ thống tự động bỏ qua, không gọi bóc tách dữ liệu xe).*

---

### 3. Kịch bản 2: Người lạ gửi tin trong nhóm nhà xe (`IGNORE_UNKNOWN_SENDER`)

Nhà xe Hải Long (`NX01`) chỉ ủy quyền cho 2 tài khoản: `1001000000000000001` và `1001000000000000002`.
Nếu tài khoản `1999000000000000001` (chưa đăng ký) gửi tin:

#### Request Payload:

```json
{
  "app_id": "1234567890123456789",
  "event_name": "user_send_text",
  "group_id": "2001000000000000001",
  "sender": {
    "id": "1999000000000000001"
  },
  "timestamp": "1791853000000",
  "message": {
    "msg_id": "webhook_unknown_sender_01",
    "text": "Báo xe trả cont VSIU7399796"
  }
}
```

#### Kết quả kỳ vọng (200 OK):

```json
{
  "success": true,
  "seq": 8,
  "msg_id": "webhook_unknown_sender_01",
  "carrier_id": "NX01",
  "action": "IGNORE_UNKNOWN_SENDER",
  "reason": "Người gửi 1999000000000000001 không thuộc danh sách ủy quyền của NX01",
  "admin_alert": true,
  "admin_message": "Cảnh báo người lạ gửi tin trong nhóm 2001000000000000001: Báo xe trả cont VSIU7399796",
  "total_vehicles": 0,
  "vehicles": [],
  "operation_detail": {
    "target_cont": null,
    "reply_to_carrier": null,
    "reason": "Người gửi 1999000000000000001 không thuộc danh sách ủy quyền của NX01"
  }
}
```

---

### 4. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - Tin chào hỏi được xếp đúng vào `IGNORE_CHAT`, `admin_alert: false`.
  - Tin từ tài khoản lạ được xếp đúng vào `IGNORE_UNKNOWN_SENDER`, kích hoạt `admin_alert: true` và trích xuất nội dung tin lạ gửi Admin.
- [ ] **Fail**: Xử lý nhầm tin chào hỏi thành chuyến xe hoặc bỏ qua cảnh báo người lạ.
