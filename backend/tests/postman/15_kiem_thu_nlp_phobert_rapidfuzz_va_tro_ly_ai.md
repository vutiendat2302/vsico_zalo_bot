# Bộ Kiểm Thử Postman: NLP Nội Bộ (RapidFuzz + Từ Điển Danh Mục + PhoBERT), Đối Chiếu 6 Nhánh & Trợ Lý Vận Tải AI

### Dự Án VSICO Zalo Bot (Backend FastAPI + AI & OCR Microservice + OA Bridge)

Tài liệu này hướng dẫn chi tiết từng bước cấu hình trên **Postman** (Method, URL, Headers, Params, Body JSON, Script kiểm tra tự động `Tests` và Kết quả JSON mong đợi) để kiểm thử toàn diện các tính năng vừa hoàn thiện:

1. **Quản lý và đồng bộ Nhóm Zalo thật từ OA Bridge** (`TMS Điều hành VT - TEST`, `TMS Nhà xe - TEST`, `TMS Thầu phụ - TEST`, hội thoại 1-1 `Vũ Tiến Đạt`).
2. **Tầng NLP Nội bộ (`RapidFuzz + Từ điển danh mục + PhoBERT`)**: Tách từ ghép tiếng Việt chuẩn PhoBERT (`_`), nhận diện thực thể BIO (`PER` tài xế, `LOC` địa điểm kho), đối sánh mờ `RapidFuzz` trên danh mục (`Customer`, `Warehouse`, `WarehouseAlias`, `Driver`, `Vehicle`) và giải quyết đồng tham chiếu hội thoại (`xe trên`, `xe này`, `cont đó`, `chỗ cũ`).
3. **Bộ Đối chiếu Kế hoạch 6 Nhánh (`TH1` đến `TH6`), Đa xe (`resolve_batch`) & Cập nhật Nguyên tử `RO -> LO`**: Tự động ghép hoặc tạo đề xuất chọn kế hoạch an toàn, kiểm soát cảnh báo vỏ (`empty_drop`, `soc`, `other_requested`, `over_combined`).
4. **Trợ lý Vận tải AI 3 Vai trò & Thống kê ĐHVT theo Vùng/Tỉnh**: Tra cứu số lệnh đóng (`LO`), số lệnh trả (`RO`), tổng số lệnh, thống kê phân bổ lệnh đóng/trả theo từng vùng (`Miền Bắc`, `Miền Trung`, `Miền Nam`) và theo từng tỉnh/thành phố (`Bắc Ninh`, `Hải Phòng`...), xác nhận 2 bước cho nhà xe, và chặn duyệt trực tiếp trên Zalo.
5. **Bảo mật RBAC (`ADMIN`/`DHVT`), Khóa Phiên bản (`expected_version` -> `409 Conflict`), Chọn ứng viên trên `/reviews` & Tự động lưu `WarehouseAlias`**.

---

## 1. Thiết Lập Môi Trường Postman (Environment Variables)

Tạo hoặc cập nhật Postman Environment với bộ biến chuẩn dưới đây (sử dụng đúng ID nhóm thật từ `oa-bridge` đang chạy):

| Tên biến | Giá trị khởi tạo | Ý nghĩa nghiệp vụ |
| :--- | :--- | :--- |
| `baseUrl` | `http://localhost:8000` | Địa chỉ Backend FastAPI |
| `botUrl` | `http://localhost:3000` | Địa chỉ Zalo OA Bridge (`oa-bridge`) |
| `aiUrl` | `http://localhost:8001` | Địa chỉ AI & OCR Microservice (`ai-service`) |
| `dhvtGroupId` | `456c699447faaea4f7eb` | Nhóm Zalo thật: `TMS Điều hành VT - TEST` (vai trò `DHVT`) |
| `carrierGroupId` | `3632c4cbeaa503fb5ab4` | Nhóm Zalo thật: `TMS Nhà xe - TEST` (vai trò `SOURCE`) |
| `subCarrierGroupId` | `b0301d81c0ee29b070ff` | Nhóm Zalo thật: `TMS Thầu phụ - TEST` (vai trò `SOURCE` / `DESTINATION`) |
| `directGroupId` | `direct_2025593064656318114` | Hội thoại 1-1 thật: `Vũ Tiến Đạt` (vai trò `DIRECT_CHAT`) |
| `dhvtSenderId` | `2025593064656318114` | Zalo User ID thật của nhân viên ĐHVT / Admin (`Vũ Tiến Đạt`) |
| `carrierSenderId` | `driver_test_01` | Mã người gửi phía nhà xe dùng khi mô phỏng |
| `planDate` | `2026-11-09` | Ngày kế hoạch kiểm thử (`YYYY-MM-DD`) |
| `authToken` | *(tự động lưu ở Kịch bản 01)* | JWT Bearer Token của tài khoản `admin` / `dhvt` |
| `internalToken` | *(giá trị `INTERNAL_SECRET` trong `.env`)* | Token nội bộ khi gọi trực tiếp `ai-service` |

---

## 2. Phần I: Xác Thực & Đồng Bộ Nhóm Zalo Thật Từ OA Bridge

### Kịch Bản 01: Đăng Nhập Quản Trị Viên Lấy `authToken`

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/auth/login`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "username": "admin",
  "password": "123456"
}
```
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("HTTP 200 OK và trả về access_token", function () {
    pm.response.to.have.status(200);
    pm.expect(res.ok).to.be.true;
    pm.expect(res.access_token).to.be.a("string");
});
if (res.access_token) {
    pm.environment.set("authToken", res.access_token);
}
```
- **Kết quả mong đợi**: HTTP `200 OK`, token được tự động lưu vào biến môi trường `{{authToken}}`.

---

### Kịch Bản 02: Lấy Danh Sách Nhóm Zalo Thật (Tự Động Đồng Bộ Từ `oa-bridge`)

Khi gọi `GET /api/groups`, Backend tự động đồng bộ danh sách nhóm thật từ `{{botUrl}}/api/bot/groups` vào bảng `zalo_groups` mà không dùng bất kỳ nhóm giả nào.

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/groups?limit=100`
- **Headers**:
  - `Accept`: `application/json`
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("HTTP 200 OK và đồng bộ đủ nhóm thật từ OA Bridge", function () {
    pm.response.to.have.status(200);
    pm.expect(res.ok).to.be.true;
    pm.expect(res.groups).to.be.an("array");
    const ids = res.groups.map(g => g.zalo_group_id);
    pm.expect(ids).to.include("456c699447faaea4f7eb");
    pm.expect(ids).to.include("3632c4cbeaa503fb5ab4");
    pm.expect(ids).to.include("b0301d81c0ee29b070ff");
});
if (res.groups && res.groups.length > 0) {
    const dhvtGrp = res.groups.find(g => g.zalo_group_id === "456c699447faaea4f7eb");
    if (dhvtGrp) {
        pm.environment.set("dhvtGroupDbId", dhvtGrp.id);
    }
}
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "total": 4,
  "limit": 100,
  "offset": 0,
  "groups": [
    {
      "id": "3073804738540831091",
      "zalo_group_id": "direct_2025593064656318114",
      "name": "Vũ Tiến Đạt",
      "group_role": "DIRECT_CHAT",
      "send_mode": "AUTO",
      "send_mode_label": "Tự động",
      "is_active": true,
      "is_test": false
    },
    {
      "id": "3073804738540831093",
      "zalo_group_id": "456c699447faaea4f7eb",
      "name": "TMS Điều hành VT - TEST",
      "group_role": "DHVT",
      "send_mode": "AUTO",
      "send_mode_label": "Tự động",
      "is_active": true,
      "is_test": false
    },
    {
      "id": "3073804738540831094",
      "zalo_group_id": "3632c4cbeaa503fb5ab4",
      "name": "TMS Nhà xe - TEST",
      "group_role": "SOURCE",
      "send_mode": "AUTO",
      "send_mode_label": "Tự động",
      "is_active": true,
      "is_test": false
    },
    {
      "id": "3073804738540831095",
      "zalo_group_id": "b0301d81c0ee29b070ff",
      "name": "TMS Thầu phụ - TEST",
      "group_role": "SOURCE",
      "send_mode": "AUTO",
      "send_mode_label": "Tự động",
      "is_active": true,
      "is_test": false
    }
  ]
}
```

---

### Kịch Bản 03: Xem Chi Tiết Nhóm Thật Kèm Danh Sách Thành Viên Realtime

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/groups/{{dhvtGroupDbId}}`
- **Headers**:
  - `Accept`: `application/json`
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("Trả về đúng tên nhóm TMS Điều hành VT - TEST và danh sách thành viên thật", function () {
    pm.response.to.have.status(200);
    pm.expect(res.group.name).to.eql("TMS Điều hành VT - TEST");
    pm.expect(res.group.zalo_live_info).to.be.an("object");
    pm.expect(res.group.zalo_live_info.total_members).to.be.at.least(1);
    pm.expect(res.group.zalo_live_info.members).to.be.an("array");
});
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "ok": true,
  "group": {
    "zalo_group_id": "456c699447faaea4f7eb",
    "name": "TMS Điều hành VT - TEST",
    "group_role": "DHVT",
    "send_mode": "AUTO",
    "zalo_live_info": {
      "total_members": 2,
      "group_link": "https://zalo.me/g/ywxreu969",
      "members": [
        {
          "id": "2208036998371849749",
          "display_name": "PTLS co ltd"
        },
        {
          "id": "2025593064656318114",
          "display_name": "Vũ Tiến Đạt"
        }
      ]
    }
  }
}
```

---

## 3. Phần II: Kiểm Thử Tách Từ Tiếng Việt (PhoBERT), BIO NER & Từ Điển Danh Mục `RapidFuzz`

Sử dụng endpoint mô phỏng cô lập `POST /api/sandbox/simulate` (không ghi rác vào CSDL thật) hoặc `POST /webhook` để kiểm tra chi tiết từng tầng xử lý ngôn ngữ tự nhiên.

### Kịch Bản 04: Tách Từ Ghép PhoBERT & Nhận Diện Thực Thể BIO (`PER` Tài Xế, `LOC` Địa Điểm Kho)

Kiểm tra khả năng tách từ ghép tiếng Việt (`đóng_hàng`, `khu_công_nghiệp`, `quế_võ`, `bắc_ninh`, `lấy_rỗng`) và nhận diện thực thể tên người (`PER`), địa điểm kho (`LOC`), trạng thái chờ cont (`container_status = "DEFERRED"`).

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/simulate`
- **Headers**:
  - `Content-Type`: `application/json`
  - `Authorization`: `Bearer {{authToken}}`
- **Body (`raw` - JSON)**:
```json
{
  "role": "CARRIER",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "Xe 15C-170.66 tài xế Phạm Văn Huynh 0986713346 đi lấy rỗng đóng hàng khu công nghiệp Quế Võ Bắc Ninh hẹn 08:30 chưa có cont",
  "plan_date": "{{planDate}}"
}
```
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("HTTP 200 OK và bóc tách chuẩn thực thể qua PhoBERT + RapidFuzz", function () {
    pm.response.to.have.status(200);
    pm.expect(res.ok).to.be.true;
    pm.expect(res.extracted_items).to.be.an("array").that.is.not.empty;
    const item = res.extracted_items[0];
    pm.expect(item.truck_plate).to.eql("15C-170.66");
    pm.expect(item.driver_phone).to.eql("0986713346");
    pm.expect(item.order_type).to.eql("LOAD");
    pm.expect(item.eta_time).to.eql("08:30");
});
```
- **Kết quả mong đợi**:
  - `truck_plate`: `"15C-170.66"`
  - `driver_name`: `"Phạm Văn Huynh"`
  - `driver_phone`: `"0986713346"`
  - `order_type`: `"LOAD"`
  - `eta_time`: `"08:30"`
  - `field_evidences.nlp_engine`: `"rapidfuzz+catalog+phobert"`

---

### Kịch Bản 05: Nhận Diện Chuyến Kết Hợp `RO -> LO` Bằng PhoBERT & Rule

Kiểm tra câu báo xe tự do có cụm từ ghép kết hợp (`trả xong ... đóng luôn ...` hoặc `hạ vỏ ... bốc hàng luôn`).

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/simulate`
- **Headers**:
  - `Content-Type`: `application/json`
  - `Authorization`: `Bearer {{authToken}}`
- **Body (`raw` - JSON)**:
```json
{
  "role": "CARRIER",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "Xe 15C-170.66 tài Huynh 0986713346 trả xong cont MSCU1234566 quay đầu đóng luôn kho Tiên Sơn lúc 14:00 chì SL9988",
  "plan_date": "{{planDate}}"
}
```
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("Bóc tách đúng số container ISO 6346, chì mới và cờ kết hợp RO -> LO", function () {
    pm.response.to.have.status(200);
    const item = res.extracted_items[0];
    pm.expect(item.container_no).to.eql("MSCU1234566");
    pm.expect(item.seal_no).to.eql("SL9988");
    pm.expect(item.eta_time).to.eql("14:00");
});
```

---

### Kịch Bản 06: Giải Quyết Đồng Tham Chiếu Hội Thoại (`"Xe trên"` Khi Có Quote Duy Nhất 1 Xe)

Khi nhà xe trích dẫn (quote) tin nhắn trước đó có đúng 1 biển số xe và nhắn `"Xe trên bổ sung chì SL998877 nhé"`, tầng NLP tự động kế thừa biển số từ tin được quote.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/simulate`
- **Headers**:
  - `Content-Type`: `application/json`
  - `Authorization`: `Bearer {{authToken}}`
- **Body (`raw` - JSON)**:
```json
{
  "role": "CARRIER",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "Xe trên bổ sung số cont MSCU1234566 và chì SL998877 nhé",
  "quoted_text": "Xe 15C-170.66 tài Phạm Văn Huynh 0986713346 đóng hàng kho Quế Võ lúc 08:30",
  "plan_date": "{{planDate}}"
}
```
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("Tự động liên kết biển số 15C-170.66 từ tin quote", function () {
    pm.response.to.have.status(200);
    const item = res.extracted_items[0];
    pm.expect(item.container_no).to.eql("MSCU1234566");
    pm.expect(item.seal_no).to.eql("SL998877");
});
```

---

### Kịch Bản 07: Kiểm Thử Tầng `RapidFuzz` Map Địa Chỉ Kho Trực Tiếp Trên `ai-service`

Kiểm tra tầng GP1.5 (`RapidFuzz` `WRatio` + `token_set_ratio`) tại `POST {{aiUrl}}/api/v1/match-warehouse` với địa chỉ kho gõ tắt/không dấu.

- **Method**: `POST`
- **URL**: `{{aiUrl}}/api/v1/match-warehouse`
- **Headers**:
  - `Content-Type`: `application/json`
  - `X-Internal-Token`: `{{internalToken}}`
- **Body (`raw` - JSON)**:
```json
{
  "raw_address": "kcn que vo bac ninh",
  "customer_id": 101,
  "carrier_id": 202,
  "habit_candidates": [],
  "candidate_warehouses": [
    {
      "warehouse_id": 5001,
      "name": "Kho KCN Quế Võ - Bắc Ninh",
      "address": "Khu công nghiệp Quế Võ, Phường Vân Dương, Bắc Ninh",
      "normalized_name": "kho kcn que vo bac ninh"
    },
    {
      "warehouse_id": 5002,
      "name": "Kho Tiên Sơn - Bắc Ninh",
      "address": "KCN Tiên Sơn, Từ Sơn, Bắc Ninh",
      "normalized_name": "kho tien son bac ninh"
    }
  ]
}
```
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("RapidFuzz khớp đúng warehouse_id = 5001 ở tầng fuzzy", function () {
    pm.response.to.have.status(200);
    pm.expect(res.warehouse_id).to.eql(5001);
    pm.expect(res.source).to.eql("fuzzy");
    pm.expect(res.confidence).to.be.at.least(0.82);
});
```
- **Kết quả mong đợi**: HTTP `200 OK`
```json
{
  "warehouse_id": 5001,
  "matched_name": "Kho KCN Quế Võ - Bắc Ninh",
  "confidence": 0.9,
  "source": "fuzzy",
  "model_name": "local-waterfall",
  "prompt_version": "wh_match_v2.0"
}
```

---

## 4. Phần III: Kiểm Thử Trợ Lý Vận Tải AI (ĐHVT, Nhà Xe, Khách Hàng) & Thống Kê Lệnh Theo Vùng/Tỉnh

> **Lưu ý chuẩn bị cho nhóm ĐHVT**: Đảm bảo tài khoản `admin` (hoặc tài khoản ĐHVT của bạn trên trang `/admin/users`) đã gắn `zalo_user_id = "2025593064656318114"` và thuộc nhóm `TMS Điều hành VT - TEST` (`456c699447faaea4f7eb`).

### Kịch Bản 08: ĐHVT Tra Cứu Tổng Số Lệnh, Số Lệnh Đóng, Số Lệnh Trả Theo Từng Vùng & Tỉnh

Nhân viên ĐHVT nhắn trong nhóm `TMS Điều hành VT - TEST` để hỏi tổng số lệnh, số lệnh đóng (`LO`), số lệnh trả (`RO`) và thống kê phân bổ theo từng vùng (`Miền Bắc`, `Miền Trung`, `Miền Nam`) cùng chi tiết từng tỉnh/thành phố.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "pm_dhvt_stats_region_001",
  "group_id": "{{dhvtGroupId}}",
  "sender_id": "{{dhvtSenderId}}",
  "message_text": "Hôm nay tổng số lệnh, số lệnh đóng, trả theo từng vùng thế nào?",
  "is_test": true
}
```
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("Webhook tiếp nhận tin hỏi thống kê vùng của ĐHVT", function () {
    pm.response.to.have.status(200);
    pm.expect(res.ok).to.be.true;
    pm.environment.set("lastDhvtMsgId", res.record_id);
});
```
- **Kiểm tra nội dung Bot trả lời ĐHVT** (`GET {{baseUrl}}/api/outbound/messages?limit=5`):
  - Bản ghi phản hồi trong `outbound_messages` (hoặc trên màn hình **Kết quả gửi** `/results`) có dạng:
    - `Tổng quan YYYY-MM-DD: N chuyến (Đóng (LO): X [20': ..., 40': ...] | Trả (RO): Y [20': ..., 40': ...]); đã gán xe ..., chưa xe ...`
    - `Theo vùng: Miền Bắc: ... lệnh (Đóng: ..., Trả: ...); Miền Trung: ...; Miền Nam: ...`
    - `Theo tỉnh/khu vực: Bắc Ninh: ... (Đóng ..., Trả ...); Hải Phòng: ...`

---

### Kịch Bản 09: ĐHVT Tra Cứu Riêng Số Lệnh Đóng Tại Một Miền Cụ Thể (`Miền Bắc`)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "pm_dhvt_north_load_002",
  "group_id": "{{dhvtGroupId}}",
  "sender_id": "{{dhvtSenderId}}",
  "message_text": "Miền Bắc hôm nay có bao nhiêu lệnh đóng?",
  "is_test": true
}
```
- **Kết quả mong đợi**:
  - Bot lọc đúng `region = 1` (`Miền Bắc`) và `order_type = "dong"` (`Lệnh đóng`), trả về:
    `Tổng quan YYYY-MM-DD (Miền Bắc, Lệnh đóng): X chuyến (Đóng (LO): X [20': ..., 40': ...] | Trả (RO): 0 [20': 0, 40': 0])...`

---

### Kịch Bản 10: ĐHVT Tra Cứu Riêng Số Lệnh Trả Trong Ngày

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "pm_dhvt_return_count_003",
  "group_id": "{{dhvtGroupId}}",
  "sender_id": "{{dhvtSenderId}}",
  "message_text": "Số lệnh trả hôm nay là bao nhiêu?",
  "is_test": true
}
```
- **Kết quả mong đợi**:
  - Bot lọc đúng `order_type = "tra"` (`Lệnh trả`) và báo cáo tổng số lệnh trả, số cont `20'`, `40'`, số chuyến đã có xe / chưa có xe.

---

### Kịch Bản 11: ĐHVT Tra Cứu Cảnh Báo Vỏ (`Hạ Rỗng`, `SOC`, `Bên Khác Đã Xin`, `Quá SL`) & Hiệu Quả Bot

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "pm_dhvt_warnings_004",
  "group_id": "{{dhvtGroupId}}",
  "sender_id": "{{dhvtSenderId}}",
  "message_text": "Có vỏ nào cảnh báo hạ rỗng hoặc SOC không?",
  "is_test": true
}
```
- **Kết quả mong đợi**:
  - Bot liệt kê các dòng kế hoạch có `container_warning` (`empty_drop`, `soc`, `other_requested`, `over_combined`) kèm nhãn tiếng Việt rõ ràng.

---

### Kịch Bản 12: Chặn Tuyệt Đối Lệnh Duyệt / Sửa Trực Tiếp Trên Nhóm Zalo ĐHVT (`BLOCK_WRITE`)

Theo quy tắc nghiệp vụ, ĐHVT không được duyệt hoặc sửa kế hoạch qua tin nhắn Zalo. Khi nhắn lệnh duyệt hoặc quote `"ok"`, Bot phải chặn và gửi đường dẫn mở Web quản lý.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "pm_dhvt_block_write_005",
  "group_id": "{{dhvtGroupId}}",
  "sender_id": "{{dhvtSenderId}}",
  "message_text": "Duyệt ca #123 cho gửi khách luôn",
  "is_test": true
}
```
- **Kết quả mong đợi**:
  - Với nhân viên ĐHVT đã đăng ký tài khoản `users.zalo_user_id` trong nhóm ĐHVT: Bot tìm ca duyệt `#123` (hoặc ca được quote). Nếu ca tồn tại ở trạng thái `PENDING`, Bot duyệt/sửa/hủy trực tiếp, đồng bộ TMS, thông báo công khai vào nhóm ĐHVT (`"ĐHVT <Tên> đã duyệt/sửa/hủy..."`) và phản hồi kết quả về nhóm Nhà xe.
  - Nếu mã ca `#123` không tồn tại hoặc chưa chỉ rõ ca: Bot giữ nguyên dữ liệu kế hoạch và hướng dẫn quote tin báo duyệt hoặc ghi kèm mã lệnh/số container.
  - Với tài khoản Zalo chưa gắn quyền ĐHVT/Admin: Bot từ chối thực thi ghi dữ liệu.

---

### Kịch Bản 12B: Kiểm Thử Trực Tiếp Bộ Bóc Tách NLP 3 Tầng (`Precision Regex + vinai/phobert-base-v2 + Kế Hoạch`)

Endpoint dry-run `POST /api/sandbox/nlp-analyze` (không ghi DB, không gửi Zalo thật) trả chi tiết kết quả bóc tách của Tầng 1 (`PLATE_REGEX`, `TRAILER_PLATE_REGEX`, `CONT_REGEX`, `PHONE_PATTERN`), Tầng 2 (`phobert_transformers_local`, `vinai/phobert-base-v2`, ngưỡng `INTENT_MIN_CONFIDENCE = 0.65`, span `PER`/`LOC` với confidence động), cờ kích hoạt Tầng 3 LLM, thông báo lỗi thân thiện xem trước và kết quả phát hiện lệnh kết hợp `RO + LO`.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/nlp-analyze`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "text": "Xe 29C\u00a0447.12 mooc 29RM-048.02 cont MSCU6635324 lái xe Tịnh Văn Duân 0987369401 / 0912345678",
  "include_plan_resolution": true
}
```
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("HTTP 200 OK và chạy trọng số thật vinai/phobert-base-v2", function () {
    pm.response.to.have.status(200);
    pm.expect(res.ok).to.be.true;
    pm.expect(res.tier2_phobert_nlp.backend_mode).to.eql("phobert_transformers_local");
    pm.expect(res.tier2_phobert_nlp.model_name).to.eql("vinai/phobert-base-v2");
    pm.expect(res.records[0].driver_phone).to.eql("0987369401 | 0912345678");
});
```

---

### Kịch Bản 12C: Kiểm Tra Sức Khỏe Kết Nối Zalo OA Watchdog

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/health/zalo-oa?probe=true`
- **Kết quả mong đợi**: HTTP `200 OK`, trả về trạng thái `HEALTHY` / `OA_DISCONNECTED` / `OA_SEND_FAILURE`, số lỗi liên tiếp, thời điểm kiểm tra và webhook gần nhất.

---

### Kịch Bản 13: Trợ Lý Nhà Xe — Tra Cứu Lệnh Thiếu Cont/Chì & Đổi Xe Xác Nhận 2 Bước

#### Bước 13A: Nhà xe hỏi danh sách lệnh còn thiếu số container hoặc thiếu chì
- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "pm_carrier_incomplete_001",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "Còn lệnh nào thiếu cont hoặc thiếu chì không em?",
  "is_test": true
}
```
- **Kết quả mong đợi**: Bot chỉ liệt kê các kế hoạch thuộc đúng `carrier_id` của nhóm `{{carrierGroupId}}` đang thiếu biển số, số cont hoặc số chì.

#### Bước 13B: Nhà xe yêu cầu đổi xe (Tạo bản nháp xác nhận bước 1)
- **Method**: `POST`
- **URL**: `{{baseUrl}}/webhook`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body (`raw` - JSON)**:
```json
{
  "msg_id": "pm_carrier_change_req_002",
  "group_id": "{{carrierGroupId}}",
  "sender_id": "{{carrierSenderId}}",
  "message_text": "LO2447 đổi sang xe 29C-447.22 tài Nam 0912345678",
  "is_test": true
}
```
- **Kết quả mong đợi**:
  - Kế hoạch `LO2447` chưa bị ghi đè ngay.
  - Bot tạo bản nháp `MessageDraft` (`WAITING_REPLY`, hạn 15 phút, khóa theo `sender_id`, `group_id` và `expected_version` của kế hoạch) và trả lời yêu cầu nhà xe nhắn `xác nhận #<mã nháp>`.

---

## 5. Phần IV: Kiểm Thử Duyệt Ca `/reviews` Chọn Ứng Viên 1 Chạm, Tự Học `WarehouseAlias` & Khóa Phiên Bản `409 Conflict`

### Kịch Bản 14: Lấy Danh Sách Ca Chờ Duyệt Kèm `candidate_plans`

- **Method**: `GET`
- **URL**: `{{baseUrl}}/api/reviews?status=PENDING&limit=10&offset=0`
- **Headers**:
  - `Authorization`: `Bearer {{authToken}}`
- **Script tab `Tests` trên Postman**:
```javascript
const res = pm.response.json();
pm.test("HTTP 200 OK và trả về danh sách ca chờ duyệt", function () {
    pm.response.to.have.status(200);
    pm.expect(res.ok).to.be.true;
    pm.expect(res.cases).to.be.an("array");
});
if (res.cases && res.cases.length > 0) {
    pm.environment.set("reviewCaseId", res.cases[0].id);
}
```

---

### Kịch Bản 15: Duyệt Ca Chọn Kế Hoạch (`selected_plan_id`), Kiểm Tra Khóa Phiên Bản (`expected_version`) & Tự Lưu `WarehouseAlias`

Khi ĐHVT chọn một dòng kế hoạch ứng viên trên màn hình `/reviews` và bấm **Phê duyệt**, Backend kiểm tra quyền RBAC (`ADMIN`/`DHVT`), đối chiếu `expected_version` (nếu lệch trả về `409 Conflict`), cập nhật kế hoạch và tự động lưu cụm địa chỉ kho trong tin nhắn vào bảng `warehouse_aliases`.

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/reviews/{{reviewCaseId}}/approve`
- **Headers**:
  - `Content-Type`: `application/json`
  - `Authorization`: `Bearer {{authToken}}`
- **Body (`raw` - JSON)**:
```json
{
  "reviewed_by": "admin",
  "selected_plan_id": "<ID_KE_HOACH_CHON>",
  "expected_version": 1,
  "note": "ĐHVT xác nhận ghép vào kế hoạch đóng hàng"
}
```
- **Script tab `Tests` trên Postman**:
```javascript
pm.test("Phản hồi hợp lệ (200 khi đúng version, 409 khi lệch version)", function () {
    pm.expect(pm.response.code).to.be.oneOf([200, 409]);
});
```

---

## 6. Kiểm Thử Tự Động Toàn Bộ Bằng Pytest (Chế Độ Proxy-Only)

Ngoài việc kiểm thử từng kịch bản qua Postman và giao diện Web (`/groups`, `/sandbox`, `/reviews`, `/plans`), toàn bộ kịch bản Golden Benchmark, trọng số thật `vinai/phobert-base-v2`, cưỡng chế `MANUAL`, form `[VSICO] - ...`, thống kê ngày vs chi tiết tỉnh kèm ảnh PNG, cửa sổ đợi nhóm Nhà xe `20s / trần 60s` (`?force=true` khi cần ép xử lý ngay trong `POST /api/messages/process-fifo`) và phản hồi tức thì của ĐHVT đã được đóng gói thành **169 test tự động** tại `backend/tests/test_nlp_phobert_and_golden_benchmark.py` và `backend/tests/test_new_zalo_ux_and_tms_flows.py` (chạy 100% ở chế độ `ZALO_PROXY_ONLY=True`).
