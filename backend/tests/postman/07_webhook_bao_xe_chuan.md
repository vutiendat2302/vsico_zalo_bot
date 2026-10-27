# 📮 TEST CASE 07: ZALO WEBHOOK - BÁO XE CHUẨN 1 XE (HAPPY PATH)

### 1. Mục tiêu kiểm thử

Mô phỏng sự kiện webhook thực tế từ máy chủ Zalo OA khi nhà xe gửi tin nhắn báo 1 xe chuẩn vào nhóm Zalo GMF điều xe.

Hệ thống sẽ thực hiện toàn bộ luồng tự động hóa:

1. Tiếp nhận tại `POST /webhook`, xác thực người gửi và nhóm Zalo (`group_id: 2001000000000000001` -> Nhà xe Hải Long `NX01`).
2. Kiểm tra chống trùng `msg_id`.
3. Phân loại ý định: `Intent.PARSE`.
4. Bóc tách các trường: số container, số seal, biển số, tên tài xế, SĐT, giờ đến.
5. Thẩm định Check Digit ISO 6346 Mod 11.
6. Khớp lệnh vận chuyển trong `shipping.csv` (tìm thấy đơn hàng `DH00000001` của khách hàng `KH001` - Dược Phẩm Á Châu).
7. Nạp template `default_tra.txt` và render thông báo hoàn chỉnh gửi vào nhóm Zalo của khách hàng.

---

### 2. Thông tin Request trên Postman

| Thông số        | Giá trị                          |
| ----------------- | ---------------------------------- |
| **Method**  | `POST`                           |
| **URL**     | `http://localhost:8000/webhook`  |
| **Headers** | `Content-Type: application/json` |

#### Request Body (JSON Raw):

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
    "msg_id": "webhook_happy_01",
    "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026"
  }
}
```

---

### 3. Các bước thực hiện trên Postman

1. Chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/webhook`.
3. Trong tab **Body**, chọn **raw** $\rightarrow$ **JSON**.
4. Dán payload webhook ở trên vào khung soạn thảo.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**

```json
{
  "success": true,
  "seq": 1,
  "msg_id": "webhook_happy_01",
  "carrier_id": "NX01",
  "action": "PARSE",
  "reason": null,
  "admin_alert": false,
  "admin_message": "",
  "total_vehicles": 1,
  "vehicles": [
    {
      "seq": 1,
      "msg_id": "webhook_happy_01",
      "carrier_id": "NX01",
      "action": "PARSE",
      "xe_index": 1,
      "cont": "VSIU7399796",
      "seal": "73957169",
      "bien_so": "15C-878.99",
      "tai_xe": "Trần Quốc Bảo",
      "sdt": "0903976359",
      "gio_den": "08:00 14/10/2026",
      "warnings": [],
      "status": "ready",
      "in_shipping": true,
      "shipping_id": "DH00000001",
      "khach_hang_id": "KH001",
      "ten_khach_hang": "Dược Phẩm Á Châu",
      "send_status": "SENT_DRY_RUN",
      "notification_text": "Kính gửi Quý khách Dược Phẩm Á Châu,\nVSICO xin thông báo thông tin xe trả hàng:\n- Số cont: VSIU7399796\n- Số seal: 73957169\n- Biển số: 15C-878.99\n- Tài xế: Trần Quốc Bảo (0903976359)\n- Giờ dự kiến đến kho: 08:00 14/10/2026\nTrân trọng cảm ơn!"
    }
  ],
  "operation_detail": null
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - `action` là `"PARSE"`.
  - Khớp thành công đơn hàng: `in_shipping: true`, `shipping_id: "DH00000001"`.
  - `send_status` chuyển thành `"SENT_DRY_RUN"`.
  - Đoạn text `notification_text` được tạo tự động chuẩn mẫu không bị rỗng.
- [ ] **Fail**: Không bóc tách được số container hoặc không khớp được bảng shipping.
