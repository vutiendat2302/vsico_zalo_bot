# KIỂM THỬ POSTMAN — CẬP NHẬT ĐIỀU PHỐI SANG TMS (`DISPATCH ASSIGNMENT`)

Tài liệu hướng dẫn kiểm thử tích hợp API đẩy cập nhật từng phần (Partial Update) từ **VSICO Zalo Bot** sang **be-tms** qua endpoint chính thức:

```http
POST {{tmsBaseUrl}}/integrations/zalo/dispatch-assignment
Authorization: Bearer {{tmsZaloIntegrationToken}}
Content-Type: application/json
```

---

## 1. Thiết Lập Biến Môi Trường Postman

| Tên biến | Giá trị mẫu (Dev / Local) | Ghi chú |
| :--- | :--- | :--- |
| `baseUrl` | `http://localhost:8000` | FastAPI Backend của VSICO Zalo Bot |
| `tmsBaseUrl` | `https://dev-tms.vsico.com.vn/api` | URL gốc API TMS (`be-tms`) |
| `tmsZaloIntegrationToken` | *(giá trị `TMS_ZALO_INTEGRATION_TOKEN` trong `.env`)* | Bearer token tích hợp riêng, không dùng chung JWT Admin |
| `webhookSecret` | *(giá trị `ZALO_SECRET_KEY` trong `.env`)* | Header `X-Webhook-Secret` cho `/webhook` |
| `authToken` | *(JWT ĐHVT/Admin sau khi `POST /api/auth/login`)* | Dùng gọi `/api/plans`, `/api/reviews`, `/api/messages` |
| `carrierGroupId` | `3632c4cbeaa503fb5ab4` | Nhóm Zalo nhà xe (`group_role = SOURCE`) |
| `carrierSenderId` | `test_carrier_user_01` | Người gửi tin trong nhóm nhà xe |
| `sampleLoadOrder` | `LO2507` | Mã lệnh đóng (`LO...`) có sẵn trong DB |
| `sampleReturnOrder` | `RO2816` | Mã lệnh trả (`RO...`) có sẵn trong DB |
| `sampleVehicleId` | `2215` | `tms_vehicle_id` trong bảng `vehicles` (`15C-066.95`) |
| `sampleDriverId` | `645` | `tms_driver_id` trong bảng `drivers` (`Vũ Văn Hưởng`) |

Lưu ý:
- Toàn bộ kịch bản Phần 2 gọi trực tiếp sang `{{tmsBaseUrl}}`. Nếu không muốn ghi vào dữ liệu dev của TMS, sử dụng môi trường mock hoặc chọn đúng dòng kế hoạch test.
- Biển số dạng text gửi sang TMS được chuẩn hóa về **dạng có dấu chấm** (ví dụ: `15H-008.14`, `15H-998.81`).
- Nếu một tin liên quan cả lệnh `LO` và `RO`, Bot gửi **2 request độc lập** (1 cho `LO...`, 1 cho `RO...`), không ghép thành một payload chung.

---

## 2. Phần I: Kiểm Thử Trực Tiếp API TMS (`POST {{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`)

Headers chung cho tất cả request trong Phần I:
- `Authorization`: `Bearer {{tmsZaloIntegrationToken}}`
- `Content-Type`: `application/json`
- `Accept`: `application/json`

### Case 01: Chỉ cập nhật `vehicle_id` theo `order_code` (Xe có trên TMS)

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleLoadOrder}}",
  "vehicle_id": 2215
}
```
- **Script `Tests`**:
```javascript
pm.test("HTTP 2xx cập nhật vehicle_id thành công", function () {
    pm.expect(pm.response.code).to.be.oneOf([200, 201]);
});
```

### Case 02: Xe chưa tồn tại trên TMS (`vehicle_id: null` + biển số có dấu chấm)

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleLoadOrder}}",
  "vehicle_id": null,
  "planned_truck_plate": "15H-008.14"
}
```

### Case 03: Cập nhật chỉ tài xế có `driver_id` hợp lệ

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleLoadOrder}}",
  "driver_id": 645
}
```

### Case 04: Tài xế không có trên TMS (`driver_id: null` + SĐT chuẩn `0...` + tên)

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleLoadOrder}}",
  "driver_id": null,
  "driver_phone": "0986123456",
  "driver_name": "Nguyễn Văn A"
}
```

### Case 05: Tài xế chỉ có tên (khi chưa xác định duy nhất `driver_id`)

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleLoadOrder}}",
  "driver_name": "Nguyễn Văn A"
}
```

### Case 06: Lệnh LO chưa có container — Bổ sung `container_no` hợp lệ ISO 6346

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleLoadOrder}}",
  "container_no": "VSIU2360549"
}
```

### Case 07: Lệnh RO — Chỉ gửi xe/tài xế, không gửi `container_no`

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleReturnOrder}}",
  "vehicle_id": null,
  "planned_truck_plate": "15H-008.14",
  "driver_id": null,
  "driver_phone": "0986123456",
  "driver_name": "Nguyễn Văn A"
}
```

### Case 08: Sai Bearer Token (Kỳ vọng `401 Unauthorized`)

- **Method**: `POST`
- **URL**: `{{tmsBaseUrl}}/integrations/zalo/dispatch-assignment`
- **Headers**: thay `Authorization` thành `Bearer invalid_token_test`
- **Body (`raw` - JSON)**:
```json
{
  "order_code": "{{sampleLoadOrder}}",
  "vehicle_id": 2215
}
```
- **Script `Tests`**:
```javascript
pm.test("Từ chối khi token sai", function () {
    pm.expect(pm.response.code).to.be.oneOf([401, 403]);
});
```

---

## 3. Phần II: Kiểm Thử Luồng Đầy Đủ Qua Bot Webhook (`POST {{baseUrl}}/webhook`)

Trước khi chạy Phần II, kiểm tra trong DB:
- Nhóm `{{carrierGroupId}}` đã gán đúng `carrier_id` của dòng kế hoạch `{{sampleLoadOrder}}` / `{{sampleReturnOrder}}`.
- Trong `.env` đã bật `TMS_SYNC_ENABLED=true`, `TMS_WRITE_ENABLED=true` và có `TMS_ZALO_INTEGRATION_TOKEN`.

Headers chung cho các request Webhook:
- `Content-Type`: `application/json`
- `X-Webhook-Secret`: `{{webhookSecret}}`

### Kịch Bản A: Cập nhật từng phần một trường (`order_code` + biển số xe)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "tms-part-plate-{{$timestamp}}",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "{{sampleLoadOrder}} xe 15H/00814",
  "is_test": false
}
```
- **Kiểm tra sau khi chạy**:
  - Nếu `15H-008.14` có trong bảng `vehicles` của nhà xe: Bot gửi `{"order_code": "{{sampleLoadOrder}}", "vehicle_id": <tms_vehicle_id>}`.
  - Nếu `15H-008.14` không có trong bảng `vehicles`: Bot chuẩn hóa thành `"15H-008.14"` và gửi `{"order_code": "{{sampleLoadOrder}}", "vehicle_id": null, "planned_truck_plate": "15H-008.14"}`.

### Kịch Bản B: Hội thoại nhiều lượt bổ sung dần rồi xác nhận (`Cont + Xe` -> `Tài` -> `SĐT` -> `xác nhận`)

Thực hiện tuần tự 4 request cùng `group_id` và `sender_id`:

**Lượt 1 (Xe + Cont):**
```json
{
  "msg_id": "tms-multi-1-{{$timestamp}}",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "{{sampleLoadOrder}} đổi sang xe 15H-00814",
  "is_test": false
}
```

**Lượt 2 (Bổ sung tên tài xế vào bản nháp đang chờ):**
```json
{
  "msg_id": "tms-multi-2-{{$timestamp}}",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "Tài Nguyễn Văn A",
  "is_test": false
}
```

**Lượt 3 (Bổ sung SĐT định dạng `+84`):**
```json
{
  "msg_id": "tms-multi-3-{{$timestamp}}",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "SĐT +84986123456",
  "is_test": false
}
```

**Lượt 4 (Xác nhận — lúc này Bot mới gọi API TMS 1 lần duy nhất):**
```json
{
  "msg_id": "tms-multi-4-{{$timestamp}}",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "xác nhận",
  "is_test": false
}
```

### Kịch Bản C: Một tin có cả lệnh LO và lệnh RO (Gửi riêng 2 lần sang TMS)

```json
{
  "msg_id": "tms-two-orders-{{$timestamp}}",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "{{sampleLoadOrder}} xe 15C-066.95\n{{sampleReturnOrder}} tài Vũ Văn Hưởng 0964271792",
  "is_test": false
}
```
- **Kỳ vọng**: Hệ thống tách riêng từng dòng, gọi 2 lần độc lập tới `/api/integrations/zalo/dispatch-assignment` (1 cho `{{sampleLoadOrder}}`, 1 cho `{{sampleReturnOrder}}` không gửi `container_no`).

---

## 4. Kiểm Tra Trạng Thái & Audit Sau Khi Chạy

1. **Kiểm tra trạng thái đồng bộ trên kế hoạch**:
```http
GET {{baseUrl}}/api/plans?q={{sampleLoadOrder}}
Authorization: Bearer {{authToken}}
```
Kiểm tra `plans[0].tms_sync_status` (`"SYNCED"` nếu TMS trả 2xx, `"FAILED"` nếu TMS lỗi, `"PENDING"` nếu đang chờ duyệt), `planned_truck_plate`, `version`.

2. **Duyệt ca nếu nhóm ở chế độ `MANUAL` (`POST {{baseUrl}}/api/reviews/{{reviewId}}/approve`)**:
```http
POST {{baseUrl}}/api/reviews/{{reviewId}}/approve
Authorization: Bearer {{authToken}}
Content-Type: application/json
```
```json
{
  "selected_plan_id": "{{planId}}",
  "expected_version": 1
}
```
Kiểm tra trường `tms_sync_statuses` trong response trả về.

3. **Kiểm tra Audit Log trong MySQL (đảm bảo SĐT đã được che và không lộ token)**:
```sql
SELECT id, entity_id, action, details, created_at
FROM activity_logs
WHERE action = 'TMS_DISPATCH_ASSIGNMENT_SYNC'
ORDER BY id DESC
LIMIT 10;

SELECT id, container_job_id, operation, http_status, status, request_data, response_data, error_message, created_at
FROM tms_sync_logs
ORDER BY id DESC
LIMIT 10;
```
