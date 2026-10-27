# 📮 TEST CASE 06: TRA CỨU DANH SÁCH & CHI TIẾT CHUYẾN XE (GET APIS)

### 1. Mục tiêu kiểm thử
Xác minh 2 API đọc (Read-only) của phần mềm TMS:
1. `GET /api/trips`: Lấy danh sách toàn bộ chuyến xe đang quản lý trong bộ nhớ.
2. `GET /api/trips/{container_no}`: Tra cứu chi tiết một chuyến xe cụ thể dựa trên số container.

---

### 2. Kịch bản 1: Xem toàn bộ danh sách chuyến xe

| Thông số | Giá trị |
|---|---|
| **Method** | `GET` |
| **URL** | `http://localhost:8000/api/trips` |
| **Headers** | None |
| **Body** | None |

#### Kết quả phản hồi kỳ vọng (200 OK):
```json
{
  "total_trips": 1,
  "trips": [
    {
      "carrier_id": "NX01",
      "cont": "VSIU7399796",
      "shipping_id": "DH00000001",
      "version": 2,
      "sent_at": "2026-10-16T11:22:00+07:00",
      "xe_data": {
        "cont": "VSIU7399796",
        "seal": "73957169",
        "bien_so": "15C-878.99",
        "tai_xe": "Lê Văn Đổi",
        "sdt": "0988592302",
        "gio_den": "08:00 14/10/2026"
      }
    }
  ]
}
```
*(Lưu ý: Chuyến `VSIU7399796` hiển thị `version: 2` và tài xế mới `Lê Văn Đổi` do đã qua bước đổi tài xế ở Test Case 03).*

---

### 3. Kịch bản 2: Tra cứu chi tiết theo số container

| Thông số | Giá trị |
|---|---|
| **Method** | `GET` |
| **URL** | `http://localhost:8000/api/trips/VSIU7399796` |
| **Headers** | None |
| **Body** | None |

#### Kết quả phản hồi kỳ vọng (200 OK):
```json
{
  "success": true,
  "carrier_id": "NX01",
  "cont": "VSIU7399796",
  "shipping_id": "DH00000001",
  "version": 2,
  "sent_at": "2026-10-16T11:22:00+07:00",
  "xe_data": {
    "cont": "VSIU7399796",
    "seal": "73957169",
    "bien_so": "15C-878.99",
    "tai_xe": "Lê Văn Đổi",
    "sdt": "0988592302",
    "gio_den": "08:00 14/10/2026"
  }
}
```

#### Trường hợp tra cứu container không tồn tại (Ví dụ: `GET /api/trips/NONEXIST999`):
- **HTTP Status Code**: `404 Not Found`
- **Body**:
  ```json
  {
    "success": false,
    "error": "Không tìm thấy chuyến cont NONEXIST999"
  }
  ```

---

### 4. Tiêu chí đánh giá Pass/Fail
- [x] **Pass**: Trả về dữ liệu chuyến xe chuẩn xác, số phiên bản và thông tin tài xế đồng nhất với các thao tác trước đó.
- [ ] **Fail**: Không trả về chuyến xe hoặc hiển thị sai thông tin tài xế sau cập nhật.
