# Kiểm Thử Kéo Kế Hoạch Vận Chuyển Theo Ngày Từ TMS (`be-tms`) Bằng Postman

## 1. Mục đích
Hướng dẫn kiểm thử API kéo kế hoạch vận chuyển theo ngày và miền từ hệ thống `be-tms` bằng Postman hoặc cURL, phục vụ đối chiếu dữ liệu trước khi tích hợp đồng bộ vào bảng `transport_plans` cục bộ.

---

## 2. Thiết lập biến môi trường Postman
Sử dụng cùng Environment với tài liệu `12_dong_bo_master_data_tms.md`:

| Biến | Giá trị mẫu | Ghi chú |
| :--- | :--- | :--- |
| `TMS_BASE_URL` | `https://dev-tms.vsico.com.vn/api` | URL gốc API của TMS |
| `TMS_TOKEN` | *(tự động điền sau bước Login)* | Bearer Token xác thực |
| `PLAN_DATE` | `2026-11-11` | Ngày kế hoạch theo định dạng `YYYY-MM-DD` |
| `REGION` | `1` | Mã miền (`1`: Miền Bắc) |

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

### Bước 2: Kéo kế hoạch vận chuyển theo ngày và miền
- **Method**: `GET`
- **URL**: `{{TMS_BASE_URL}}/transport-plan?plan_date={{PLAN_DATE}}&region={{REGION}}`
- **Query Params**:
  - `plan_date`: Ngày kế hoạch (`YYYY-MM-DD`), ví dụ `2026-11-11`.
  - `region`: Mã miền (`1`: Miền Bắc, có thể thử `2` / `3` tùy cấu hình miền trên TMS).
- **Headers**:
  - `Authorization: Bearer {{TMS_TOKEN}}`
  - `Accept: application/json`
- **Script tab `Tests`**:
```javascript
const res = pm.response.json();
pm.test("Status is 200", function () {
    pm.response.to.have.status(200);
});
pm.test("Response has status success and data array", function () {
    pm.expect(res.status).to.eql("success");
    pm.expect(res.data).to.be.an("array");
});
pm.test("Summary contains container_balance", function () {
    pm.expect(res.summary).to.have.property("container_balance");
});
```

---

## 4. Cấu trúc dữ liệu trả về từ TMS

Response của `GET /transport-plan` gom nhóm theo từng tỉnh/thành phố trong mảng `data`:

```json
{
  "status": "success",
  "summary": {
    "container_balance": {
      "size_20ft": { "return_count": 9, "loading_count": 10, "balance": -1 },
      "size_40ft": { "return_count": 24, "loading_count": 30, "balance": -6 },
      "total": { "return_count": 33, "loading_count": 40, "balance": -7 }
    },
    "container_warning_counts": {
      "normal": 23,
      "over_combined": 10,
      "empty_drop": 0,
      "other_requested": 0,
      "soc": 0
    }
  },
  "data": [
    {
      "province_id": 15,
      "province_name": "Tỉnh Ninh Bình",
      "total_orders": 16,
      "return_orders_count": 6,
      "loading_orders_count": 10,
      "return_orders": [
        {
          "id": 3732,
          "order_code": "RO2846",
          "plan_date": "11/11/2026",
          "fwd_name": "VSICO Log",
          "customer_name": "NUPLEX",
          "carrier_id": null,
          "warehouse_id": 9118,
          "warehouse_name": "KHO SƠN LUXSEN BÌNH AN NINH BÌNH",
          "warehouse_address": "...",
          "terminal_name": "PTSC",
          "vessel_voyage_name": "PROSPER 2637N",
          "commodity_name": "PHUY",
          "gross_weight": 22.21,
          "required_time": "07:00",
          "bill_of_lading_no_code": "VS26110346",
          "container_type": "DC",
          "container_size": "20",
          "container_no": "GAOU2701649",
          "container_seal": "23993825",
          "container_status_message": "Bình thường"
        }
      ],
      "loading_orders": [
        {
          "id": 4374,
          "order_code": "LO2497",
          "plan_date": "11/11/2026",
          "fwd_name": "VSICO Log",
          "customer_name": "HONDA",
          "carrier_id": null,
          "warehouse_id": 8694,
          "warehouse_name": "KHO HONDA KCN ĐỒNG VĂN II NINH BÌNH",
          "warehouse_address": "KCN Đồng Văn II, Duy Hà, Ninh Bình",
          "terminal_name": "PTSC",
          "vessel_voyage_name": "NEW VISION 2633S",
          "commodity_name": "XE MAY",
          "required_time": "15:00",
          "booking_no_code": "B26110492",
          "container_size": "40",
          "etd": "2026-11-19 00:00:00"
        }
      ]
    }
  ]
}
```

### Lưu ý khi kiểm tra theo ngày
- Với ngày không có kế hoạch (ví dụ `2026-11-15`), `data` trả về mảng rỗng `[]` và các bộ đếm trong `summary` đều bằng `0`.
- Mỗi phần tử tỉnh trong `data` tách rõ hai mảng:
  - `return_orders`: Lệnh trả (`RO...`), đã có sẵn `container_no`, `container_seal`, `bill_of_lading_no_code`, `eta`, `gross_weight`, `container_grade_id`.
  - `loading_orders`: Lệnh đóng (`LO...`), chưa có số container, có `booking_no_code`, `etd`, `container_size`, `required_time`, `points`.

---

## 5. Kiểm thử nhanh bằng cURL

```bash
# 1. Lấy token
TMS_TOKEN=$(curl -s -X POST "https://dev-tms.vsico.com.vn/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"<TMS_USERNAME>","password":"<TMS_PASSWORD>"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['authorisation']['token'])")

# 2. Kéo kế hoạch ngày 2026-11-11 (Miền Bắc: region=1)
curl -s -X GET "https://dev-tms.vsico.com.vn/api/transport-plan?plan_date=2026-11-11&region=1" \
  -H "Authorization: Bearer ${TMS_TOKEN}" \
  -H "Accept: application/json" | python3 -m json.tool | head -n 60
```

---

## 6. Kiểm thử Backend VSICO Zalo Bot: Đồng bộ, Tra cứu & Xuất Excel Kế hoạch TMS

Sau khi Backend đã cấu hình tài khoản kết nối TMS (`TMS_API_URL`, `TMS_USERNAME`, `TMS_PASSWORD` trong `.env` tại thư mục gốc), dùng các API dưới đây để kéo kế hoạch từ TMS về bảng `transport_plans` trên MySQL, kiểm tra dữ liệu tổng hợp theo tỉnh và xuất Excel mẫu `ketnoi.xlsx`.

Biến môi trường bổ sung trong Postman Environment:

| Variable | Initial Value | Ghi chú |
| :--- | :--- | :--- |
| `BOT_BASE_URL` | `http://127.0.0.1:8000` | Địa chỉ Backend FastAPI |
| `DEFAULT_GROUP_ID` | `b0301d81c0ee29b070ff` | Group ID Zalo mặc định gán cho lệnh đồng bộ |
| `PLAN_DATE` | `2026-11-09` | Ngày kế hoạch cần đồng bộ và đối soát |
| `BOT_ACCESS_TOKEN` | *(để trống)* | Tự động điền sau bước đăng nhập Web Admin/ĐHVT |

### Bước 6.1. Đồng bộ kế hoạch TMS về MySQL và cập nhật các trường mới

* **Method & URL:** `POST {{BOT_BASE_URL}}/api/plans/sync-tms`
* **Query Params:**
  * `plan_date`: `{{PLAN_DATE}}` (hỗ trợ `YYYY-MM-DD` hoặc `DD/MM/YYYY`, mặc định `2026-11-09`)
  * `region`: `1` (`1`: Miền Bắc, `2`: Miền Trung, `3`: Miền Nam)
  * `group_id`: `{{DEFAULT_GROUP_ID}}` (mặc định `b0301d81c0ee29b070ff`)
  * `replace_existing`: `false` (`true`: xóa các dòng cũ của đúng ngày/miền trước khi nạp lại; `false`: upsert theo `tms_order_id`)
  * `clear_all_before_sync`: `false` (`true`: xóa toàn bộ bảng `transport_plans` trước khi đồng bộ)
* **Headers:** `Accept: application/json`

**Script Tab `Tests` (Postman):**

```javascript
pm.test("Status code is 200 OK", function () {
    pm.response.to.have.status(200);
});

const jsonData = pm.response.json();

pm.test("Sync succeeded with valid counters", function () {
    pm.expect(jsonData.ok).to.eql(true);
    pm.expect(jsonData.default_group_id_applied).to.eql("b0301d81c0ee29b070ff");
    pm.expect(jsonData.total_synced).to.eql(jsonData.return_orders_count + jsonData.loading_orders_count);
});
```

**Mẫu Response (`200 OK`):**

```json
{
  "ok": true,
  "status": "OK",
  "message": "Đã đồng bộ 225 lệnh ngày 2026-11-09 (Miền 1): 137 lệnh trả, 88 lệnh đóng.",
  "plan_date": "2026-11-09",
  "region": 1,
  "provinces_count": 9,
  "return_orders_count": 137,
  "loading_orders_count": 88,
  "total_synced": 225,
  "inserted": 225,
  "updated": 0,
  "deleted_old": 0,
  "default_group_id_applied": "b0301d81c0ee29b070ff"
}
```

### Bước 6.2. Kiểm tra danh sách kế hoạch chính sau khi đồng bộ

* **Method & URL:** `GET {{BOT_BASE_URL}}/api/plans?plan_date={{PLAN_DATE}}&limit=50`
* **Query Params tùy chọn:** `container_no`, `customer_name`, `driver_name`, `truck_plate`, `order_type` (`tra` | `dong`), `q` (tìm mã lệnh, booking, vận đơn, kho, forwarder, địa chỉ), `skip`, `limit`.

**Script Tab `Tests` (Postman):**

```javascript
pm.test("Status code is 200 OK", function () {
    pm.response.to.have.status(200);
});

const jsonData = pm.response.json();

pm.test("Plans contain TMS fields and default group_id", function () {
    pm.expect(jsonData.ok).to.eql(true);
    pm.expect(jsonData.total).to.be.above(0);
    const first = jsonData.plans[0];
    pm.expect(first.group_id).to.eql("b0301d81c0ee29b070ff");
    pm.expect(first).to.have.property("tms_order_id");
    pm.expect(first).to.have.property("order_code");
    pm.expect(first).to.have.property("warehouse_name");
    pm.expect(first).to.have.property("province_name");
});
```

### Bước 6.3. Xuất file Excel chuẩn mẫu `ketnoi.xlsx` (23 cột)

* **Method & URL:** `GET {{BOT_BASE_URL}}/api/plans/export-excel?plan_date={{PLAN_DATE}}`
* **Query Params tùy chọn:** `plan_date`, `region`, `order_type` (`tra` | `dong`), `q`.
* **Thao tác Postman:** Nhấn mũi tên cạnh nút **Send** và chọn **Send and Download** để tải về file `ke_hoach_van_chuyen_2026-11-09.xlsx`.

**Script Tab `Tests` (Postman):**

```javascript
pm.test("Status code is 200 and returns XLSX file", function () {
    pm.response.to.have.status(200);
    const contentType = pm.response.headers.get("Content-Type") || "";
    pm.expect(contentType).to.include("spreadsheetml.sheet");
    const disposition = pm.response.headers.get("Content-Disposition") || "";
    pm.expect(disposition).to.include(".xlsx");
});
```

### Bước 6.4. Đăng nhập Bot Backend để lấy JWT Token (cho API Tùy chọn / Master)

* **Method & URL:** `POST {{BOT_BASE_URL}}/api/auth/login`
* **Headers:** `Content-Type: application/json`
* **Body (`raw` -> `JSON`):**

```json
{
  "username": "admin",
  "password": "<BOT_USER_PASSWORD>"
}
```

**Script Tab `Tests` (Postman):**

```javascript
pm.test("Login succeeded", function () {
    pm.response.to.have.status(200);
    const jsonData = pm.response.json();
    const token = jsonData.access_token || (jsonData.data && jsonData.data.access_token);
    pm.expect(token).to.be.a("string").and.not.empty;
    pm.environment.set("BOT_ACCESS_TOKEN", token);
});
```

### Bước 6.5. Lấy dữ liệu Kế hoạch TMS tổng hợp theo Tỉnh (Trang Tùy chọn -> Kế hoạch TMS)

* **Method & URL:** `GET {{BOT_BASE_URL}}/api/master/transport-plans?plan_date={{PLAN_DATE}}&region=1`
* **Headers:**
  * `Authorization: Bearer {{BOT_ACCESS_TOKEN}}`
  * `Accept: application/json`
* **Query Params tùy chọn:** `search`, `forwarder_name`, `order_type` (`tra` | `dong`), `container_size` (`20` | `40`), `delivery_term` (`1`: Nguyên cont | `2`: Kiểm đếm), `dispatch_state`, `container_warning` (`normal` | `over_combined` | `empty_drop` | `other_requested` | `soc`).

**Script Tab `Tests` (Postman):**

```javascript
pm.test("Status code is 200 OK", function () {
    pm.response.to.have.status(200);
});

const jsonData = pm.response.json();

pm.test("Summary container balance matches total orders", function () {
    pm.expect(jsonData.ok).to.eql(true);
    const bal = jsonData.summary.container_balance.total;
    pm.expect(bal.return_count + bal.loading_count).to.be.at.least(jsonData.total_orders);
    pm.expect(jsonData.provinces).to.be.an("array");
});
```

### Kiểm thử nhanh toàn bộ API Backend bằng cURL

```bash
# 1. Đồng bộ kế hoạch ngày 2026-11-09 từ TMS về MySQL (mặc định group_id=b0301d81c0ee29b070ff)
curl -s -X POST "http://127.0.0.1:8000/api/plans/sync-tms?plan_date=2026-11-09&region=1" \
  -H "Accept: application/json" | python3 -m json.tool

# 2. Kiểm tra danh sách kế hoạch chính từ MySQL
curl -s "http://127.0.0.1:8000/api/plans?plan_date=2026-11-09&limit=5" \
  | python3 -m json.tool | head -n 45

# 3. Tải file Excel xuất chuẩn ketnoi.xlsx (23 cột)
curl -s -L -o "ke_hoach_van_chuyen_2026-11-09.xlsx" \
  "http://127.0.0.1:8000/api/plans/export-excel?plan_date=2026-11-09"

# 4. Đăng nhập Bot Backend và gọi API giao diện Kế hoạch TMS
BOT_TOKEN=$(curl -s -X POST "http://127.0.0.1:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<BOT_USER_PASSWORD>"}' \
  | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('access_token') or d['data']['access_token'])")

curl -s "http://127.0.0.1:8000/api/master/transport-plans?plan_date=2026-11-09&region=1" \
  -H "Authorization: Bearer ${BOT_TOKEN}" \
  -H "Accept: application/json" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['total_orders'], len(d['provinces']), d['summary'])"
```
