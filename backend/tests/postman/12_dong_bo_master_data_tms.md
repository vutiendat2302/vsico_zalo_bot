# Kiểm Thử Đồng Bộ Master Data Từ TMS (`be-tms`) Bằng Postman

## 1. Mục đích
Hướng dẫn kiểm thử các endpoint Master Data của hệ thống `be-tms` bằng Postman (hoặc cURL) và đối chiếu kết quả đồng bộ vào cơ sở dữ liệu MySQL cục bộ (`carriers`, `customers`, `warehouses`, `vehicles`, `drivers`).

---

## 2. Thiết lập biến môi trường Postman
Tạo hoặc cập nhật Environment trong Postman với các biến sau:

| Biến | Giá trị mẫu | Ghi chú |
| :--- | :--- | :--- |
| `TMS_BASE_URL` | `https://dev-tms.vsico.com.vn/api` | URL gốc API của TMS |
| `TMS_TOKEN` | *(tự động điền sau bước Login)* | Bearer Token xác thực |

---

## 3. Bộ Request kiểm thử Postman

### Bước 1: Đăng nhập lấy Bearer Token
- **Method**: `POST`
- **URL**: `{{TMS_BASE_URL}}/login`
- **Headers**: `Content-Type: application/json`
- **Body (`raw` - JSON)**:
```json
{
  "username": "<TMS_USERNAME>",
  "password": "<TMS_PASSWORD>"
}
```
- **Script tab `Tests` (tự động lưu token vào biến `TMS_TOKEN`)**:
```javascript
const res = pm.response.json();
pm.test("Login status 200", function () {
    pm.response.to.have.status(200);
});
if (res.authorisation && res.authorisation.token) {
    pm.environment.set("TMS_TOKEN", res.authorisation.token);
}
```
- **Kết quả mong đợi**: HTTP `200 OK`, trả về `status: "success"` và `authorisation.token`.

---

### Bước 2: Kéo danh mục Nhà xe (`carriers`)
- **Method**: `GET`
- **URL**: `{{TMS_BASE_URL}}/carriers?per_page=100&page=1`
- **Headers**:
  - `Authorization: Bearer {{TMS_TOKEN}}`
  - `Accept: application/json`
- **Kết quả mong đợi**: HTTP `200 OK`, có `pagination.total` và mảng `data` chứa `id`, `code`, `name`, `short_name`, `tax_code`, `status`.

---

### Bước 3: Kéo danh mục Khách hàng (`customers`)
- **Method**: `GET`
- **URL**: `{{TMS_BASE_URL}}/customers?per_page=100&page=1`
- **Headers**:
  - `Authorization: Bearer {{TMS_TOKEN}}`
  - `Accept: application/json`
- **Kết quả mong đợi**: HTTP `200 OK`, mảng `data` chứa `id`, `name`, `short_name`, `tax_code`, `address`, `status`.

---

### Bước 4: Kéo danh mục Kho khách hàng (`warehouses`)
- **Method**: `GET`
- **URL**: `{{TMS_BASE_URL}}/warehouses?per_page=100&page=1`
- **Headers**:
  - `Authorization: Bearer {{TMS_TOKEN}}`
  - `Accept: application/json`
- **Kết quả mong đợi**: HTTP `200 OK`, mảng `data` chứa `id`, `name`, `address`, `latitude`, `longitude`, `status`.

---

### Bước 5: Kéo danh mục Cảng (`ports`) và Depot (`depots`)
1. **Cảng**:
   - **Method**: `GET`
   - **URL**: `{{TMS_BASE_URL}}/ports?per_page=100&page=1`
   - **Headers**: `Authorization: Bearer {{TMS_TOKEN}}`, `Accept: application/json`
2. **Depot**:
   - **Method**: `GET`
   - **URL**: `{{TMS_BASE_URL}}/depots?per_page=100&page=1`
   - **Headers**: `Authorization: Bearer {{TMS_TOKEN}}`, `Accept: application/json`
- **Kết quả mong đợi**: HTTP `200 OK`, khi đồng bộ vào bảng `warehouses` cục bộ sẽ phân biệt bằng cột `location_type` (`port` / `depot`) và tiền tố `tms_warehouse_id` (`PORT:` / `DEPOT:`).

---

### Bước 6: Kéo danh mục Xe đầu kéo & Rơ-mooc (`vehicles`)
- **Method**: `GET`
- **URL**: `{{TMS_BASE_URL}}/vehicles?per_page=100&page=1`
- **Headers**:
  - `Authorization: Bearer {{TMS_TOKEN}}`
  - `Accept: application/json`
- **Kết quả mong đợi**: HTTP `200 OK`, mảng `data` chứa `id`, `carrier_id`, `truck_no`, `vehicles_type` (`1`: đầu kéo, `2`: rơ-mooc), `payload_capacity`, `vehicle_identification_number` (gợi ý tên tài xế nếu có), `status`.

---

### Bước 7: Kéo danh mục Tài xế (`drivers`)
- **Method**: `GET`
- **URL**: `{{TMS_BASE_URL}}/drivers?per_page=100&page=1`
- **Headers**:
  - `Authorization: Bearer {{TMS_TOKEN}}`
  - `Accept: application/json`
- **Kết quả mong đợi**: HTTP `200 OK`, mảng `data` chứa `id`, `carrier_id`, `full_name`, `phone`, `identity_no`, `license_no`, `status`.

---

## 4. Đồng bộ tự động về MySQL cục bộ & Kiểm tra dữ liệu

1. Cấu hình `TMS_BASE_URL`, `TMS_USERNAME`, `TMS_PASSWORD` trong tệp `.env` ở thư mục gốc.
2. Chạy lệnh đồng bộ toàn bộ 7 danh mục từ thư mục gốc:
   ```bash
   make tms-sync
   ```
3. Kiểm tra lại số lượng bản ghi đã vào các bảng MySQL:
   ```bash
   make db-status
   ```
   Hoặc truy vấn trực tiếp trong MySQL:
   ```sql
   SELECT 'carriers' AS tbl, COUNT(*) AS total FROM carriers
   UNION ALL
   SELECT 'customers', COUNT(*) FROM customers
   UNION ALL
   SELECT 'warehouses', COUNT(*) FROM warehouses
   UNION ALL
   SELECT 'vehicles', COUNT(*) FROM vehicles
   UNION ALL
   SELECT 'drivers', COUNT(*) FROM drivers;
   ```
