# 📮 TEST CASE 10: ZALO WEBHOOK - XỬ LÝ XE THIẾU SEAL & PHẢN HỒI NHÀ XE

### 1. Mục tiêu kiểm thử

Xác minh quy trình thẩm định dữ liệu (`VehicleValidator`) khi tin nhắn nhà xe thiếu các trường bắt buộc (thiếu số seal hải quan).

Hệ thống phải:

1. Phát hiện trường `seal` bị thiếu.
2. Đưa chuyến xe vào trạng thái chờ bổ sung: `send_status: "HOLD_WAIT_SUPPLEMENT"`.
3. **Không gửi thông báo cho khách hàng** để tránh gửi dữ liệu sai thiếu.
4. Tự động soạn tin nhắn phản hồi gửi ngược lại vào nhóm Zalo nhà xe (`reply_to_carrier`), nêu rõ số container và trường còn thiếu cần bổ sung.

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
  "timestamp": "1791850000000",
  "message": {
    "msg_id": "webhook_missing_seal_01",
    "text": "BÁO XE TRẢ HÀNG\nCont: GAOU9386298\nBiển số: 15C-129.83\nTài xế: Ngô Doãn Nam\nSĐT: 0918239485\n(chưa có chì)"
  }
}
```

---

### 3. Các bước thực hiện trên Postman

1. Chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/webhook`.
3. Trong tab **Body**, chọn **raw** $\rightarrow$ **JSON**.
4. Dán payload thiếu seal ở trên.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**

```json
{
  "success": true,
  "seq": 5,
  "msg_id": "webhook_missing_seal_01",
  "carrier_id": "NX01",
  "action": "PARSE",
  "reason": null,
  "admin_alert": false,
  "admin_message": "",
  "total_vehicles": 1,
  "vehicles": [
    {
      "cont": "GAOU9386298",
      "seal": null,
      "bien_so": "15C-129.83",
      "tai_xe": "Ngô Doãn Nam",
      "sdt": "0918239485",
      "warnings": [
        "thieu_seal",
        "thieu_gio_den"
      ],
      "status": "wait_supplement",
      "send_status": "HOLD_WAIT_SUPPLEMENT",
      "reply_to_carrier": "VSICO xin thông báo: Chuyến xe cont GAOU9386298 hiện còn thiếu: số seal, giờ đến. Vui lòng nhắn tin bổ sung sớm để chuyển thông tin cho khách hàng."
    }
  ],
  "operation_detail": null
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - `send_status` chuyển thành `"HOLD_WAIT_SUPPLEMENT"`.
  - Mảng `warnings` chứa mã lỗi `"thieu_seal"`.
  - Trường `reply_to_carrier` chứa nội dung nhắn nhà xe bổ sung số seal.
  - Trường `notification_text` không được kích hoạt gửi đi khách hàng.
- [ ] **Fail**: Hệ thống vẫn gửi thông báo thiếu seal cho khách hàng.
