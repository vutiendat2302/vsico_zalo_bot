# 📮 TEST CASE 01: KIỂM TRA SỨC KHỎE MÁY CHỦ (HEALTH CHECK)

### 1. Mục tiêu kiểm thử
Xác nhận máy chủ backend `nhaxe-bot` đang hoạt động ổn định, kiểm tra tổng số tin nhắn đã xử lý trong phiên làm việc, tổng số chuyến xe đã lưu trữ trong bộ nhớ và danh sách các endpoint sẵn có.

---

### 2. Thông tin Request trên Postman

| Thông số | Giá trị |
|---|---|
| **Method** | `GET` |
| **URL** | `http://localhost:8000/api/health` |
| **Headers** | Không yêu cầu header đặc biệt |
| **Body** | Để trống (None) |

---

### 3. Các bước thực hiện trên Postman
1. Mở Postman, bấm nút **New Request**.
2. Chọn phương thức **GET** từ danh sách thả xuống.
3. Nhập đường dẫn: `http://localhost:8000/api/health`.
4. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**
```json
{
  "status": "UP",
  "service": "nhaxe-bot-service",
  "version": "2.0.0",
  "timestamp": "2026-10-16T11:20:00+07:00",
  "stats": {
    "total_messages_processed": 0,
    "total_trips_stored": 0
  },
  "endpoints": {
    "webhook": "POST /webhook",
    "create_trip": "POST /api/trips/new",
    "update_driver": "POST /api/trips/update-driver",
    "supplement_trip": "POST /api/trips/supplement",
    "cancel_trip": "POST /api/trips/cancel",
    "list_trips": "GET /api/trips",
    "trip_detail": "GET /api/trips/{container_no}",
    "health": "GET /api/health"
  }
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail
- [x] **Pass**: HTTP Status là `200 OK`, trường `status` có giá trị `"UP"`, danh sách `endpoints` liệt kê đầy đủ cả Webhook Gateway và các TMS REST API.
- [ ] **Fail**: Không kết nối được tới server (`Connection refused`), hoặc mã lỗi `404 Not Found` / `500 Internal Server Error`.
