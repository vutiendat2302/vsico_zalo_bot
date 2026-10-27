# 📮 TEST CASE 05: YÊU CẦU HỦY CHUYẾN XE QUA REST API

### 1. Mục tiêu kiểm thử

Xác minh quy trình tiếp nhận yêu cầu hủy chuyến và cơ chế kích hoạt cờ cảnh báo ưu tiên cao (`admin_alert: true`) tới Điều hành Vận tải (ĐHVT).

**Tình huống thực tế:**
Xe gặp tai nạn, hỏng máy hoặc nhà xe không thể tiếp tục vận chuyển container đã nhận. Yêu cầu hủy phải được chuyển gấp cho Admin để phân bổ chuyến xe cho đơn vị vận tải dự phòng, tránh trễ giờ giao hàng cho khách.

---

### 2. Thông tin Request trên Postman

| Thông số        | Giá trị                                  |
| ----------------- | ------------------------------------------ |
| **Method**  | `POST`                                   |
| **URL**     | `http://localhost:8000/api/trips/cancel` |
| **Headers** | `Content-Type: application/json`         |

#### Request Body (JSON Raw):

```json
{
  "carrier_id": "NX03",
  "cont": "AHLXU1029021",
  "ly_do": "Xe hỏng cầu chì và lốc máy dọc đường quốc lộ"
}
```

---

### 3. Các bước thực hiện trên Postman

1. Chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/api/trips/cancel`.
3. Trong tab **Body**, chọn **raw** $\rightarrow$ **JSON**.
4. Dán payload báo hủy chuyến ở trên.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**

```json
{
  "success": true,
  "action": "CANCEL_REQUEST",
  "carrier_id": "NX03",
  "cont": "AHLXU1029021",
  "reason": "Xe hỏng cầu chì và lốc máy dọc đường quốc lộ",
  "admin_alert": true,
  "admin_message": "Chuyến cont AHLXU1029021 (NX03) yêu cầu hủy: Xe hỏng cầu chì và lốc máy dọc đường quốc lộ"
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - `action` nhận diện đúng là `"CANCEL_REQUEST"`.
  - Cờ `admin_alert` được bật thành `true`.
  - Chuỗi `admin_message` tổng hợp rõ ràng mã container, nhà xe và lý do hủy để hiển thị tức thời trên Dashboard ĐHVT.
- [ ] **Fail**: Cờ `admin_alert` là `false` hoặc bị bỏ qua thông tin lý do hủy.
