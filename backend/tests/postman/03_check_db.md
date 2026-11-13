# ĐẶC TẢ KIỂM THỬ POSTMAN: QUẢN LÝ, KIỂM TRA SỨC KHỎE & DỌN DẸP CƠ SỞ DỮ LIỆU

### TÀI LIỆU HƯỚNG DẪN KIỂM THỬ TẦNG CƠ SỞ DỮ LIỆU MYSQL (TASK 2 - PM TMS VSICO)

Tài liệu này hướng dẫn chi tiết cách kiểm thử các endpoint và quy trình vận hành liên quan đến **Kiểm tra trạng thái kết nối MySQL**, **Xóa và dọn dẹp kế hoạch vận chuyển**, cùng **Quy trình dọn dẹp Database (Clean DB)** an toàn.

---

## 1. Danh Mục Các Endpoint & Thao Tác Kiểm Thử

|     STT     | Phương thức | Đường dẫn Endpoint / Câu lệnh                                          | Chức năng kiểm thử                                                              |
| :----------: | :------------: | :--------------------------------------------------------------------------- | :---------------------------------------------------------------------------------- |
| **01** |    `GET`    | `http://localhost:8000/api/health`                                         | Kiểm tra kết nối MySQL 8.4 và thống kê số lượng bản ghi tin nhắn/xe/cont |
| **02** |   `DELETE`   | `http://localhost:8000/api/plans/by-date/2026-10-12`                       | Xóa sạch toàn bộ kế hoạch vận chuyển của một ngày cụ thể               |
| **03** |   `DELETE`   | `http://localhost:8000/api/plans/{{plan_id}}`                              | Xóa một bản ghi kế hoạch vận chuyển đơn lẻ                                |
| **04** |    `POST`    | `http://localhost:8000/api/plans/import-excel?replace_existing=true`       | Tự động dọn dẹp và ghi đè kế hoạch cũ khi nạp file Excel mới           |
| **05** |    `CLI`    | `make db-status` (hoặc `python scripts/manage_db.py status`)            | Kiểm tra số lượng bản ghi của 17 bảng trước và sau dọn dẹp              |
| **06** |    `CLI`    | `make db-clean` (hoặc `python scripts/manage_db.py clean --runtime -y`) | Dọn dẹp dữ liệu nghiệp vụ runtime (giữ master data & plans)                  |

---

## 2. Kịch Bản Kiểm Thử Chi Tiết

### Kịch Bản 1: Kiểm Tra Sức Khỏe Kết Nối Cơ Sở Dữ Liệu (`GET /api/health`)

#### Mục đích:

Xác nhận máy chủ FastAPI kết nối thành công tới MySQL 8.4, Connection Pool hoạt động bình thường và lấy được bộ đếm bản ghi thời gian thực.

#### Cấu hình Postman:

- **Method**: `GET`
- **URL**: `{{backend_url}}/api/health` (mặc định: `http://localhost:8000/api/health`)
- **Headers**:
  ```http
  Accept: application/json
  ```

#### cURL mẫu:

```bash
curl -X GET "http://localhost:8000/api/health" \
  -H "Accept: application/json"
```

#### Phản hồi kỳ vọng (`200 OK`):

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

#### Tiêu chí đánh giá (Postman Tests script):

```javascript
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});

pm.test("Database is connected", function () {
    const json = pm.response.json();
    pm.expect(json.ok).to.eql(true);
    pm.expect(json.database).to.eql("mysql_connected");
});

pm.test("FIFO worker is alive", function () {
    const json = pm.response.json();
    pm.expect(json.fifo_queue.worker_alive).to.eql(true);
});
```

---

### Kịch Bản 2: Dọn Dẹp Kế Hoạch Vận Chuyển Theo Ngày (`DELETE /api/plans/by-date/{plan_date}`)

#### Mục đích:

Khi Điều hành Vận tải cần dọn dẹp sạch sẽ dữ liệu kế hoạch vận chuyển của một ngày (ví dụ `2026-10-12`) để chuẩn bị nạp lại dữ liệu mới từ TMS hoặc file Excel.

#### Cấu hình Postman:

- **Method**: `DELETE`
- **URL**: `{{backend_url}}/api/plans/by-date/2026-10-12`
- **Headers**:
  ```http
  Accept: application/json
  ```

#### cURL mẫu:

```bash
curl -X DELETE "http://localhost:8000/api/plans/by-date/2026-10-12" \
  -H "Accept: application/json"
```

#### Phản hồi kỳ vọng (`200 OK`):

```json
{
  "ok": true,
  "status": "DELETED",
  "plan_date": "2026-10-12",
  "deleted_count": 95
}
```

#### Tiêu chí đánh giá (Postman Tests script):

```javascript
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});

pm.test("Plans for date deleted successfully", function () {
    const json = pm.response.json();
    pm.expect(json.ok).to.eql(true);
    pm.expect(json.status).to.eql("DELETED");
    pm.expect(json.plan_date).to.eql("2026-10-12");
});
```

---

### Kịch Bản 3: Xóa Một Bản Ghi Kế Hoạch Đơn Lẻ (`DELETE /api/plans/{plan_id}`)

#### Mục đích:

Xóa một cuốc xe bị hủy hoặc nhập nhầm trong kế hoạch vận chuyển hằng ngày.

#### Cấu hình Postman:

- **Method**: `DELETE`
- **URL**: `{{backend_url}}/api/plans/1`
- **Headers**:
  ```http
  Accept: application/json
  ```

#### cURL mẫu:

```bash
curl -X DELETE "http://localhost:8000/api/plans/1" \
  -H "Accept: application/json"
```

#### Phản hồi kỳ vọng (`200 OK`):

```json
{
  "ok": true,
  "status": "DELETED",
  "deleted_plan_id": 1
}
```

---

### Kịch Bản 4: Tự Động Dọn Dẹp Và Ghi Đè Kế Hoạch Cũ Khi Import Excel

#### Mục đích:

Khi nạp file Excel điều vận mới với tham số `replace_existing=true`, hệ thống sẽ tự động dọn sạch các bản ghi cũ của cùng ngày trước khi chèn các dòng mới.

#### Cấu hình Postman:

- **Method**: `POST`
- **URL**: `{{backend_url}}/api/plans/import-excel?replace_existing=true`
- **Body**: `form-data`
  - Key: `file` (loại File) -> Chọn `tests/data_test/ketnoi.xlsx`

#### cURL mẫu:

```bash
curl -X POST "http://localhost:8000/api/plans/import-excel?replace_existing=true" \
  -F "file=@tests/data_test/ketnoi.xlsx"
```

#### Phản hồi kỳ vọng (`200 OK`):

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

---

## 3. Quy Trình Dọn Dẹp Cơ Sở Dữ Liệu Qua CLI (Command-Line Verification)

Khi chạy kiểm thử hoặc chuyển giao hệ thống, việc dọn dẹp cơ sở dữ liệu có thể thực hiện nhanh chóng qua CLI mà không cần thao tác thủ công trong phpMyAdmin/Navicat:

```bash
# 1. Xem thống kê dữ liệu hiện có trong 17 bảng
make db-status

# 2. Dọn sạch tin nhắn và nghiệp vụ runtime sau khi test xong
make db-clean

# 3. Kiểm tra lại trạng thái database đảm bảo sạch sẽ
make db-status
```

Tất cả các lệnh trên đều bảo toàn cấu trúc bảng và quản lý migration an toàn thông qua Alembic!
