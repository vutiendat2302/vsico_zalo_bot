# BỘ KIỂM THỬ POSTMAN: QUẢN LÝ, KIỂM TRA SỨC KHỎE VÀ DỌN DẸP CƠ SỞ DỮ LIỆU

Tài liệu hướng dẫn kiểm thử các endpoint kiểm tra trạng thái kết nối MySQL và xóa/dọn dẹp dữ liệu kế hoạch vận chuyển bằng Postman.

---

## 1. Thiết Lập Biến Môi Trường (Postman Environment)

| Biến | Giá trị mẫu | Ghi chú |
| :--- | :--- | :--- |
| `backend_url` | `http://localhost:8000` | Địa chỉ Backend FastAPI |
| `plan_id` | `1` | ID kế hoạch vận chuyển cần thao tác |
| `plan_date` | `2026-10-12` | Ngày kế hoạch (định dạng YYYY-MM-DD) |

---

## 2. Danh Mục Endpoint Kiểm Thử

| STT | Method | Endpoint | Mô tả |
| :---: | :---: | :--- | :--- |
| 01 | `GET` | `{{backend_url}}/api/health` | Kiểm tra kết nối MySQL 8.4 và thống kê số lượng bản ghi |
| 02 | `DELETE` | `{{backend_url}}/api/plans/by-date/2026-10-12` | Xóa toàn bộ kế hoạch vận chuyển của một ngày cụ thể |
| 03 | `DELETE` | `{{backend_url}}/api/plans/{{plan_id}}` | Xóa một bản ghi kế hoạch vận chuyển đơn lẻ |
| 04 | `POST` | `{{backend_url}}/api/plans/import-excel?replace_existing=true` | Nạp file Excel và ghi đè kế hoạch cũ |

---

## 3. Chi Tiết Các Kịch Bản Kiểm Thử

### Kịch Bản 01: Kiểm tra sức khỏe kết nối cơ sở dữ liệu

Xác nhận máy chủ FastAPI kết nối thành công tới MySQL 8.4, Connection Pool hoạt động bình thường và lấy được bộ đếm bản ghi thời gian thực.

- **Method**: `GET`
- **URL**: `{{backend_url}}/api/health`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**: Không có
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "OK",
  "database": "mysql_connected",
  "total_messages": 100,
  "total_trucks_extracted": 99,
  "total_containers_extracted": 103,
  "fifo_queue": {
    "queue_size": 0,
    "total_enqueued": 100,
    "total_processed": 100,
    "total_failed": 0,
    "worker_alive": true
  }
}
```

---

### Kịch Bản 02: Dọn dẹp kế hoạch vận chuyển theo ngày

Dọn dẹp sạch toàn bộ dữ liệu kế hoạch vận chuyển của một ngày (ví dụ `2026-10-12`) để chuẩn bị nạp lại dữ liệu mới từ TMS hoặc file Excel.

- **Method**: `DELETE`
- **URL**: `{{backend_url}}/api/plans/by-date/2026-10-12`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**: Không có (Path param: `plan_date = 2026-10-12`)
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "DELETED",
  "plan_date": "2026-10-12",
  "deleted_count": 95
}
```

---

### Kịch Bản 03: Xóa một bản ghi kế hoạch đơn lẻ

Xóa một bản ghi kế hoạch vận chuyển đơn lẻ khi chuyến xe bị hủy hoặc nhập nhầm.

- **Method**: `DELETE`
- **URL**: `{{backend_url}}/api/plans/{{plan_id}}`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**: Không có (Path param: `plan_id = 1`)
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "DELETED",
  "deleted_plan_id": 1
}
```

---

### Kịch Bản 04: Nạp và ghi đè kế hoạch vận chuyển từ file Excel

Khi nạp file Excel điều vận với tham số `replace_existing=true`, hệ thống tự động dọn sạch các bản ghi cũ của cùng ngày trước khi chèn các dòng mới.

- **Method**: `POST`
- **URL**: `{{backend_url}}/api/plans/import-excel?replace_existing=true`
- **Headers / Bảo mật**:
  - `Accept: application/json`
- **Params / Body**:
  - **Query Params**: `replace_existing=true`
  - **Body (`form-data`)**:
    - Key: `file` (loại File) -> Chọn file Excel kế hoạch (ví dụ: `ketnoi.xlsx`)
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "status": "IMPORTED",
  "plan_date": "2026-10-12",
  "total_imported": 95,
  "default_group_id_applied": "6469608867469758994",
  "replaced_existing": true
}
```
