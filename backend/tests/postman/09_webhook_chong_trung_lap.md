# 📮 TEST CASE 09: ZALO WEBHOOK - CHỐNG TRÙNG LẶP TIN NHẮN (IDEMPOTENCY)

### 1. Mục tiêu kiểm thử

Xác minh cơ chế **chống trùng lặp (Idempotency)** của module `Deduplicator` tại tầng `Ingestion`.

**Tình huống thực tế:**
Hệ thống Zalo Webhook có cơ chế tự động gửi lại (Retry) khi đường truyền mạng chập chờn, hoặc người dùng gửi lại cùng một tin nhắn nhiều lần. Nếu không lọc trùng, hệ thống sẽ gửi liên tiếp nhiều tin nhắn trùng lặp cho khách hàng (spam) và làm sai lệch thống kê chuyến xe.

Hệ thống phải:

1. Ghi nhận mã định danh tin nhắn (`msg_id`).
2. Khi nhận lại cùng `msg_id`, lập tức gán hành động `DUPLICATE_MESSAGE`.
3. Bỏ qua không xử lý tiếp, không gọi parser, không gửi lại tin nhắn cho khách.

---

### 2. Thông tin Request trên Postman

| Thông số        | Giá trị                          |
| ----------------- | ---------------------------------- |
| **Method**  | `POST`                           |
| **URL**     | `http://localhost:8000/webhook`  |
| **Headers** | `Content-Type: application/json` |

#### Bước thực hiện:

Gửi **2 lần liên tiếp** cùng một Request Body dưới đây (cùng `msg_id: "test_duplicate_msg_99"`):

```json
{
  "app_id": "1234567890123456789",
  "event_name": "user_send_text",
  "group_id": "2001000000000000001",
  "sender": {
    "id": "1001000000000000001"
  },
  "timestamp": "1791798010000",
  "message": {
    "msg_id": "test_duplicate_msg_99",
    "text": "TRẢ HÀNG\nCont: TCLU2819034\nSeal: 10293847\nBiển số: 29H-102.39\nTài xế: Vũ Hải Nam\nSĐT: 0912093847\nGiờ đến: 10:00 14/10/2026"
  }
}
```

---

### 3. Kết quả phản hồi kỳ vọng

#### Lần bấm Send thứ 1:

- **HTTP Status**: `200 OK`
- `action`: `"PARSE"` (Xử lý bình thường).

#### Lần bấm Send thứ 2 (Trùng `msg_id`):

- **HTTP Status**: `200 OK`
- **Body phản hồi:**

```json
{
  "success": true,
  "seq": 4,
  "msg_id": "test_duplicate_msg_99",
  "carrier_id": null,
  "action": "DUPLICATE_MESSAGE",
  "reason": "Bỏ qua do trùng lặp msg_id (test_duplicate_msg_99)",
  "admin_alert": false,
  "admin_message": "",
  "total_vehicles": 0,
  "vehicles": [],
  "operation_detail": {
    "target_cont": null,
    "reply_to_carrier": null,
    "reason": "Bỏ qua do trùng lặp msg_id (test_duplicate_msg_99)"
  }
}
```

---

### 4. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**: Lần gửi thứ 2 nhận về `action: "DUPLICATE_MESSAGE"`, `total_vehicles: 0` và lý do nêu rõ việc trùng lặp `msg_id`.
- [ ] **Fail**: Lần gửi thứ 2 vẫn bóc tách và gửi lại thông báo mới.
