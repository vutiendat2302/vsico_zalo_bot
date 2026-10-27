# 📮 TEST CASE 08: ZALO WEBHOOK - BÁO NHIỀU XE TRONG 1 TIN NHẮN (PHÂN ĐOẠN KHỐI XE)

### 1. Mục tiêu kiểm thử

Xác minh khả năng phân đoạn văn bản thông minh của module `VehicleSegmenter`.

**Tình huống thực tế:**
Nhà xe thường gõ gộp 2 hoặc 3 chuyến xe vào chung một tin nhắn duy nhất, phân cách bằng số thứ tự (`1)`, `2)`) hoặc dấu gạch chéo (`/`).

Hệ thống phải tự động:

1. Phát hiện tin nhắn chứa nhiều xe.
2. Tách thành 2 bản ghi xe hoàn toàn độc lập (`xe_index: 1` và `xe_index: 2`).
3. Kế thừa tiêu đề chung (ngày giờ, loại lệnh: `NHAP HANG 14/10 9h`) cho cả 2 xe nếu trong từng dòng không ghi lại.
4. Bóc tách độc lập và khớp đơn hàng cho từng xe.

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
  "group_id": "2004000000000000001",
  "sender": {
    "id": "1004000000000000001"
  },
  "timestamp": "1791849309000",
  "message": {
    "msg_id": "webhook_multi_xe_02",
    "text": "NHAP HANG 14/10 9h\n1) 50H-46744 / Lý Hoàng Phúc / sdt 0766544549 / SEGU7191464 / chì 53330158\n2) 72C-64021 / Trịnh Văn Cường / sdt 0860247525 / HLXU6721270 / seal 72355925"
  }
}
```

---

### 3. Các bước thực hiện trên Postman

1. Chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/webhook`.
3. Trong tab **Body**, chọn **raw** $\rightarrow$ **JSON**.
4. Dán payload tin nhắn 2 xe ở trên.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**

```json
{
  "success": true,
  "seq": 2,
  "msg_id": "webhook_multi_xe_02",
  "carrier_id": "NX04",
  "action": "PARSE",
  "reason": null,
  "admin_alert": false,
  "admin_message": "",
  "total_vehicles": 2,
  "vehicles": [
    {
      "xe_index": 1,
      "cont": "SEGU7191464",
      "seal": "53330158",
      "bien_so": "50H-467.44",
      "tai_xe": "Lý Hoàng Phúc",
      "sdt": "0766544549",
      "gio_den": "09:00 14/10/2026",
      "status": "ready",
      "send_status": "SENT_DRY_RUN"
    },
    {
      "xe_index": 2,
      "cont": "HLXU6721270",
      "seal": "72355925",
      "bien_so": "72C-640.21",
      "tai_xe": "Trịnh Văn Cường",
      "sdt": "0860247525",
      "gio_den": "09:00 14/10/2026",
      "status": "ready",
      "send_status": "SENT_DRY_RUN"
    }
  ],
  "operation_detail": null
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - `total_vehicles` bằng đúng `2`.
  - Mảng `vehicles` chứa đúng 2 phần tử với số cont `SEGU7191464` và `HLXU6721270`.
  - Giờ đến `09:00 14/10/2026` được phân bổ chính xác cho cả 2 xe từ dòng tiêu đề.
- [ ] **Fail**: Chỉ nhận diện được 1 xe hoặc gộp nhầm thông tin giữa 2 tài xế.
