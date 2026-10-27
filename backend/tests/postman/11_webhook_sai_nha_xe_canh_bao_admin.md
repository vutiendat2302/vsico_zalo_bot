# 📮 TEST CASE 11: ZALO WEBHOOK - SAI NHÀ XE NHẬN CUỐC & CẢNH BÁO ADMIN

### 1. Mục tiêu kiểm thử

Xác minh tính năng đối chiếu chéo (Cross-check Validation) giữa **nhà xe gửi tin** và **kế hoạch phân bổ vận chuyển trong bảng Shipping**.

**Tình huống thực tế:**
Trong kế hoạch điều độ của VSICO, container `SEGU3874035` được giao cho đơn vị vận tải Hải Long (`NX01`). Tuy nhiên, nhóm Zalo của đơn vị vận tải Thành Đạt (`NX03`) lại gửi tin nhắn báo xe nhận container này.

Đây là rủi ro nghiêm trọng: có thể do điều độ phân nhầm đơn vị, hoặc hai nhà xe tự ý bán thầu lại cho nhau mà chưa qua phê duyệt.

Hệ thống phải:

1. Phát hiện sự không khớp: `MatchStatus.WRONG_CARRIER`.
2. Chuyển chuyến xe sang trạng thái: `send_status: "HOLD_ADMIN"`.
3. Kích hoạt cờ cảnh báo tức thời: `admin_alert: true`.
4. Soạn tin nhắn báo động cho ĐHVT (`admin_message`).
5. **Tuyệt đối không gửi tin nhắn cho khách hàng** khi sự cố chưa được ĐHVT giải quyết.

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
  "group_id": "2003000000000000001",
  "sender": {
    "id": "1003000000000000001"
  },
  "timestamp": "1791851000000",
  "message": {
    "msg_id": "webhook_wrong_carrier_01",
    "text": "XE NHẬP HÀNG\nCont: SEGU3874035\nSeal: 99887766\nBiển số: 29C-888.99\nTài xế: Nguyễn Văn Nhầm\nSĐT: 0912345678\nGiờ đến: 14:00 14/10/2026"
  }
}
```

*(Ghi chú: Nhóm `2003000000000000001` thuộc nhà xe `NX03`, nhưng cont `SEGU3874035` trong `shipping.csv` lại thuộc `NX01`).*

---

### 3. Các bước thực hiện trên Postman

1. Chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/webhook`.
3. Trong tab **Body**, chọn **raw** $\rightarrow$ **JSON**.
4. Dán payload sai nhà xe ở trên.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**

```json
{
  "success": true,
  "seq": 6,
  "msg_id": "webhook_wrong_carrier_01",
  "carrier_id": "NX03",
  "action": "PARSE",
  "reason": null,
  "admin_alert": true,
  "admin_message": "CẢNH BÁO ĐHVT: Cont SEGU3874035 trong kế hoạch thuộc NX01, nhưng tin nhắn do NX03 gửi!",
  "total_vehicles": 1,
  "vehicles": [
    {
      "cont": "SEGU3874035",
      "carrier_id": "NX03",
      "warnings": [
        "sai_nha_xe"
      ],
      "status": "need_admin",
      "send_status": "HOLD_ADMIN",
      "notification_text": null
    }
  ],
  "operation_detail": null
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - `admin_alert` là `true`.
  - Mảng `warnings` có mã `"sai_nha_xe"`.
  - `send_status` là `"HOLD_ADMIN"`.
  - Tin nhắn không bị gửi ra ngoài nhóm khách hàng.
- [ ] **Fail**: `admin_alert` là `false` hoặc hệ thống vẫn tiến hành gửi thông báo khách.
