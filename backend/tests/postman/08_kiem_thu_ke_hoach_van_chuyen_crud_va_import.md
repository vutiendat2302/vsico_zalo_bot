# Tài Liệu Kiểm Thử API – Module Quản Lý & Import Kế Hoạch Vận Chuyển Hằng Ngày (Transport Plans)

- **Base URL**: `http://localhost:8000`
- **Swagger UI**: `http://localhost:8000/docs`
- **Tập tin mẫu**: `tests/data_test/ketnoi.xlsx` (đã bổ sung cột `Group ID` = `6469608867469758994`)

---

## 1. Cơ Chế Nhận Diện & Phân Loại Nghiệp Vụ

### 1.1. Phân biệt Lệnh Đóng (`dong`) vs Lệnh Trả/Mở (`tra`) qua cột Hàng
Trong file kế hoạch vận chuyển điều vận của VSICO:
- **Cột Hàng có giá trị `Nhập` / `I`**: Là hàng nhập cảng kéo về kho khách $\rightarrow$ Lệnh Trả hàng / Mở cont dỡ hàng (`order_type = "tra"`, `cargo_io_type = "I"`).
- **Cột Hàng có giá trị `Xuất` / `X`**: Là kéo rỗng đến kho khách đóng hàng hạ về cảng $\rightarrow$ Lệnh Đóng hàng (`order_type = "dong"`, `cargo_io_type = "X"`).

### 1.2. Tự động ánh xạ `group_id`
- Mọi dòng dữ liệu trong file kế hoạch (hoặc khi tạo mới) nếu chưa có `group_id` sẽ được tự động map mặc định về Group ID Zalo của nhóm:
  `6469608867469758994`

---

## 2. Danh Sách Các Endpoint Quản Lý Kế Hoạch (`/api/plans`)

| Phương thức | Đường dẫn API | Chức năng |
|---|---|---|
| `GET` | `/api/plans` | Danh sách kế hoạch (lọc theo `plan_date`, `container_no`, `customer_name`, `order_type`, `group_id`, `route_name`) |
| `GET` | `/api/plans/{plan_id}` | Xem chi tiết 1 bản ghi kế hoạch theo ID |
| `POST` | `/api/plans` | Thêm mới thủ công 1 bản ghi kế hoạch |
| `PUT` | `/api/plans/{plan_id}` | Cập nhật thông tin bản ghi kế hoạch |
| `DELETE` | `/api/plans/{plan_id}` | Xóa 1 bản ghi kế hoạch |
| `DELETE` | `/api/plans/by-date/{plan_date}` | Xóa sạch toàn bộ kế hoạch của một ngày (tiện lợi khi import lại) |
| `POST` | `/api/plans/import-excel` | Import file Excel `.xlsx` (nhận diện tiêu đề sheet ngày & cột Hàng) |
| `POST` | `/api/plans/import-csv` | Import file CSV (hỗ trợ phân tách dấu phẩy, chấm phẩy, tab) |
| `POST` | `/api/plans/import` | Import đa định dạng (tự động phát hiện `.xlsx` hay `.csv` theo đuôi file) |

---

## 3. Hướng Dẫn Kiểm Thử Trên Postman / cURL

### 3.1. Import file Excel `ketnoi.xlsx`
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/plans/import-excel`
- **Params**: `replace_existing=true`
- **Body**: `form-data`
  - Key: `file` (chọn file `tests/data_test/ketnoi.xlsx`)

**cURL mẫu:**
```bash
curl -X POST "http://localhost:8000/api/plans/import-excel?replace_existing=true" \
  -F "file=@/home/datbritget/Documents/vsico_zalo_bot/backend/tests/data_test/ketnoi.xlsx"
```

**Kết quả trả về:**
```json
{
  "ok": true,
  "status": "OK",
  "message": "Đã nạp thành công 103 dòng kế hoạch ngày 2026-10-12 từ Excel.",
  "plan_date": "2026-10-12",
  "total_imported": 103,
  "total_skipped": 0,
  "default_group_id_applied": "6469608867469758994",
  "sample_imported": [
    {
      "id": 1,
      "plan_date": "2026-10-12",
      "stt": 1,
      "route_name": "HP - Tân Quang",
      "cargo_io_type": "I",
      "order_type": "tra",
      "container_no": "SELU4396800",
      "seal_no": "VSICO23675080",
      "container_size": "40",
      "cargo_weight": 9.96,
      "required_time": "7h",
      "customer_name": "Logitem",
      "cargo_type": "Mỳ",
      "vessel_voyage": "Prosper 2633N",
      "empty_depot": null,
      "full_depot": "PTSC",
      "estimated_drop_time": null,
      "fleet_partner": "Tuấn Hưng",
      "planned_truck_plate": null,
      "delivery_address": "Kho Logitem (Tân Quang). LH thủ kho Mr Sơn 096 7327975",
      "group_id": "6469608867469758994"
    }
  ]
}
```

---

### 3.2. Import file CSV Kế hoạch
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/plans/import-csv`
- **Body**: `form-data`
  - Key: `file` (chọn file `.csv`)

**cURL mẫu:**
```bash
curl -X POST "http://localhost:8000/api/plans/import-csv?replace_existing=true&plan_date=2026-10-31" \
  -F "file=@plan_sample.csv"
```

---

### 3.3. Truy vấn danh sách kế hoạch kèm bộ lọc
- **Lấy toàn bộ kế hoạch ngày 12/10/2026:**
  `GET http://localhost:8000/api/plans?plan_date=2026-10-12`
- **Lọc theo số container:**
  `GET http://localhost:8000/api/plans?container_no=SELU4396800`
- **Lọc theo tên khách hàng:**
  `GET http://localhost:8000/api/plans?customer_name=Logitem`
- **Lọc theo loại lệnh Đóng (`dong`) hoặc Trả (`tra`):**
  `GET http://localhost:8000/api/plans?order_type=dong`
- **Lọc theo Group ID Zalo:**
  `GET http://localhost:8000/api/plans?group_id=6469608867469758994`

---

### 3.4. Thêm mới thủ công 1 bản ghi
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/plans`
- **Body (JSON)**:
```json
{
  "plan_date": "2026-10-12",
  "stt": 104,
  "route_name": "HP - Long An",
  "cargo_io_type": "X",
  "container_no": "VSIU2621051",
  "seal_no": "23333878",
  "container_size": "20",
  "cargo_weight": 21.5,
  "required_time": "08:00",
  "customer_name": "Nhựa Á Đông",
  "cargo_type": "Hạt nhựa",
  "fleet_partner": "Tuấn Hưng",
  "delivery_address": "Kho Nhựa Á Đông – Long An"
}
```
*(Nếu không nhập `group_id`, hệ thống tự gán `6469608867469758994`; `order_type` tự nhận diện là `dong` vì `cargo_io_type = "X"`)*.

---

### 3.5. Ghép nối tự động (Matching) với tin nhắn Zalo F1
Khi nhà xe miền Bắc nhắn tin chỉ có số cont và số seal:
```
1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / SELU4396800 chì VSICO23675080
```
Gửi tới `POST /webhook` hoặc `POST /api/messages/test-parse`, bot sẽ tự động tra vào bảng `transport_plans` theo số cont `SELU4396800`:
- Nhận diện `order_type = "tra"` (Lệnh Trả/Mở cont dỡ hàng)
- Nhận diện `customer_raw = "Logitem"`
- Nhận diện `location_raw = "Kho Logitem (Tân Quang). LH thủ kho Mr Sơn 096 7327975"`
- Đánh dấu `match_source = "transport_plan"`
- Sẵn sàng định tuyến tin nhắn thông báo về nhóm Zalo `6469608867469758994`.
