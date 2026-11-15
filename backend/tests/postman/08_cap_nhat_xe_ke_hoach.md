# Bộ Kiểm Thử Postman: Cập Nhật Xe Vào Kế Hoạch Vận Chuyển Nội Bộ

### Dự Án VSICO Zalo Bot (Backend FastAPI + MySQL)

Tài liệu này hướng dẫn chi tiết các bước thiết lập trên Postman (Method, URL, Headers, Params, Body) để kiểm thử API Cập nhật thông tin xe/tài xế/container/seal vào Kế hoạch vận chuyển nội bộ (`/api/plans/{id}/vehicle`) với cơ chế kiểm soát phiên bản chống ghi đè lạc quan (`expected_version`).

---

## 1. Thiết Lập Môi Trường Postman (Environment Variables)

Khởi tạo một Postman Environment với các biến sau:

| Tên biến | Giá trị mẫu | Mô tả |
| :--- | :--- | :--- |
| `baseUrl` | `http://localhost:8000` | Địa chỉ máy chủ Backend FastAPI |
| `authToken` | *(lấy sau khi đăng nhập ĐHVT/Admin)* | JWT Bearer Token xác thực người dùng |
| `planId` | `379330403493875712` | Snowflake ID của kế hoạch vận chuyển cần kiểm thử |

---

## 2. Danh Sách Endpoint API

| Phương thức | Đường dẫn API | Xác thực | Mục đích |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/plans/{id}` | Bearer Token | Lấy thông tin kế hoạch và phiên bản `version` hiện tại |
| `PATCH` | `/api/plans/{id}/vehicle` | Bearer Token (ĐHVT/Admin) | Cập nhật thông tin xe vào kế hoạch với kiểm soát phiên bản |

---

## 3. Kịch Bản Kiểm Thử Chi Tiết (Test Cases)

### TC-01: Lấy thông tin kế hoạch và phiên bản hiện tại

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/plans/{{planId}}`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
- **Params / Body**: Không có
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "id": "379330403493875712",
  "version": 1,
  "planned_truck_plate": null,
  "driver_name": null,
  "driver_phone": null,
  "container_no": null,
  "seal_no": null,
  "container_size": null,
  "carrier_id": null,
  "tms_sync_status": "PENDING"
}
```

---

### TC-02: Cập nhật thông tin xe vào kế hoạch thành công (Happy Path)

Cập nhật thông tin xe, tài xế, container và giờ hẹn. Hệ thống thẩm định số container theo ISO 6346 Modulo 11 và SĐT 10 số.

- **Method**: `PATCH`
- **URL**: `{{baseUrl}}/api/plans/{{planId}}/vehicle`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "expected_version": 1,
  "planned_truck_plate": "15C-123.45",
  "driver_name": "Tên tài xế",
  "driver_phone": "0901234567",
  "container_no": "VSIU7399796",
  "seal_no": "SEAL123",
  "container_size": "40DC",
  "required_time": "09:30"
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "id": "379330403493875712",
  "version": 2,
  "planned_truck_plate": "15C-123.45",
  "driver_name": "Tên tài xế",
  "driver_phone": "0901234567",
  "container_no": "VSIU7399796",
  "seal_no": "SEAL123",
  "container_size": "40DC",
  "eta": "09:30",
  "tms_sync_status": "PENDING"
}
```

---

### TC-03: Cập nhật từng trường riêng biệt (Partial Update)

Có thể gửi từng trường; trường không gửi được giữ nguyên giá trị cũ, gửi `null` để xóa trường tùy chọn.

- **Method**: `PATCH`
- **URL**: `{{baseUrl}}/api/plans/{{planId}}/vehicle`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "expected_version": 2,
  "seal_no": "SEAL456_MOI"
}
```
- **Kết quả mong đợi**: HTTP `200 OK` (Tăng `version` lên 3, các trường khác giữ nguyên).

---

### TC-04: Xung đột phiên bản khi có thao tác đồng thời (Optimistic Locking)

Khi `expected_version` gửi lên không khớp với `version` hiện hành trong DB (do đã có người cập nhật trước), hệ thống từ chối cập nhật để tránh ghi đè dữ liệu.

- **Method**: `PATCH`
- **URL**: `{{baseUrl}}/api/plans/{{planId}}/vehicle`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "expected_version": 1,
  "planned_truck_plate": "15C-888.88"
}
```
- **Kết quả mong đợi**: HTTP `409 Conflict`
```json
{
  "detail": "Kế hoạch đã thay đổi; tải lại trước khi cập nhật."
}
```

---

### TC-05: Lỗi dữ liệu không hợp lệ (Validation Error)

Số container sai chuẩn ISO 6346 hoặc số điện thoại không đủ 10 chữ số bắt đầu bằng `0`.

- **Method**: `PATCH`
- **URL**: `{{baseUrl}}/api/plans/{{planId}}/vehicle`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "expected_version": 3,
  "container_no": "INVALID_CONT",
  "driver_phone": "12345"
}
```
- **Kết quả mong đợi**: HTTP `422 Unprocessable Entity`
```json
{
  "detail": "Số container không hợp lệ theo ISO 6346."
}
```

---

### TC-06: Kế hoạch không tồn tại trong hệ thống

- **Method**: `PATCH`
- **URL**: `{{baseUrl}}/api/plans/999999999999999999/vehicle`
- **Headers / Bảo mật**:
  - `Authorization: Bearer {{authToken}}`
  - `Content-Type: application/json`
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "expected_version": 1,
  "planned_truck_plate": "15C-123.45"
}
```
- **Kết quả mong đợi**: HTTP `404 Not Found`
```json
{
  "detail": "Không tìm thấy kế hoạch."
}
```

---

### TC-07: Từ chối khi chưa xác thực hoặc sai quyền

Người dùng chưa đăng nhập hoặc không có vai trò `admin` / `dhvt`.

- **Method**: `PATCH`
- **URL**: `{{baseUrl}}/api/plans/{{planId}}/vehicle`
- **Headers / Bảo mật**: *(Không gửi Bearer Token)*
- **Params / Body**: Body (`raw` - JSON)
```json
{
  "expected_version": 1,
  "planned_truck_plate": "15C-123.45"
}
```
- **Kết quả mong đợi**: HTTP `401 Unauthorized` hoặc `403 Forbidden`
```json
{
  "detail": "Chỉ ĐHVT hoặc Admin được cập nhật kế hoạch."
}
```

---

## 4. Quy Tắc Nghiệp Vụ & Đối Soát

1. **Vòng đời phiên bản & Đồng bộ TMS**:
   - Cập nhật thành công sẽ tự động tăng `version` thêm 1, đặt `tms_sync_status = "PENDING"`, và ghi nhật ký kiểm toán vào bảng `activity_logs` với action `PLAN_VEHICLE_UPDATED`.
   - Trạng thái `PENDING` nghĩa là đã cập nhật nội bộ, chưa đồng bộ lên phần mềm TMS.
   - Khi chưa kết nối `be-tms`, không có thao tác ghi TMS thật và không tự ý chuyển `SYNCED`.
2. **Quy định trường dữ liệu**:
   - Hỗ trợ các trường: `planned_truck_plate`, `driver_name`, `driver_phone`, `container_no`, `seal_no`, `container_size`, `required_time`, `carrier_id`.
   - Không hỗ trợ trường rơ-moóc.
   - Số container phải kiểm tra đạt chuẩn ISO 6346 Check Digit Modulo 11; SĐT phải đủ 10 số bắt đầu bằng 0.
3. **Mối quan hệ với Webhook & Phát hành thông báo**:
   - API này chỉ cập nhật kế hoạch trong cơ sở dữ liệu nội bộ, không tự gửi thông báo Zalo.
   - Tin nhắn nhà xe hợp lệ được worker ghi vào kế hoạch trước khi phát hành thông báo ra nhóm khách hàng.
   - Cần gắn `carrier_id` cho cả nhóm Zalo và kế hoạch vận chuyển; không tự suy luận quyền sở hữu bằng tên.
   - Webhook tiếp nhận tin nhắn trả `QUEUED`, xử lý bất đồng bộ qua hàng đợi FIFO, không đợi OCR/AI.
