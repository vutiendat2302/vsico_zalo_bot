# 📮 TEST CASE 04: BỔ SUNG SỐ SEAL VÀ GIỜ ĐẾN QUA REST API

### 1. Mục tiêu kiểm thử
Xác minh chức năng bổ sung dữ liệu cho chuyến xe đang ở trạng thái tạm giữ chờ bổ sung thông tin (`HOLD_WAIT_SUPPLEMENT`).

**Tình huống thực tế:**
Khi xe nhận cont tại cảng nhưng chưa kẹp chì, nhà xe chỉ báo số xe và tài xế trước. Sau khi bốc cont xong và bấm chì, nhà xe gửi bổ sung số seal và giờ dự kiến xe cập kho khách hàng.

---

### 2. Thông tin Request trên Postman

| Thông số | Giá trị |
|---|---|
| **Method** | `POST` |
| **URL** | `http://localhost:8000/api/trips/supplement` |
| **Headers** | `Content-Type: application/json` |

#### Request Body (JSON Raw):
```json
{
  "carrier_id": "NX01",
  "cont": "GAOU9386298",
  "seal": "84920192",
  "gio_den": "10:00 14/10/2026"
}
```

---

### 3. Các bước thực hiện trên Postman
1. Chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/api/trips/supplement`.
3. Trong tab **Body**, chọn **raw** $\rightarrow$ **JSON**.
4. Dán nội dung payload bổ sung ở trên.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**
```json
{
  "success": true,
  "action": "SUPPLEMENT",
  "carrier_id": "NX01",
  "cont": "GAOU9386298",
  "supplemented_fields": {
    "seal": "84920192",
    "gio_den": "10:00 14/10/2026"
  },
  "status": "READY"
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail
- [x] **Pass**: HTTP Status là `200 OK`, `action` là `"SUPPLEMENT"`, trạng thái chuyển sang `"READY"` (sẵn sàng điều phối).
- [ ] **Fail**: Báo lỗi 400 hoặc không ghi nhận được các trường bổ sung.
