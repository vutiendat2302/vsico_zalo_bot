# Tài Liệu Kiểm Thử API – Module Đọc Hiểu & Định Tuyến (F1, F2, F3, Bảng 6.2, TC-01 -> TC-08 & TC-16)

- **Người phụ trách module**: Đạt – Module Đọc hiểu và định tuyến
- **Base URL**: `http://localhost:8000`
- **Swagger UI trực quan**: `http://localhost:8000/docs`

---

## 1. Tổng Quan Trạng Thái Hoàn Thành Yêu Cầu

| # | Hạng mục yêu cầu | Module xử lý trong `src/` | Trạng thái |
|---|---|---|---|
| 1 | **Bộ đọc F1** (nhà xe miền Bắc, ngăn bằng `/`): tách biển số, tài xế, SĐT (có/không `đt:`, dính liền tên), cont, chì | `src/parsing/trip_parser.py` (`TripParser`) | **Hoàn thành 100%** (`TC-01`, `TC-02`, `TC-03`) |
| 2 | **Bộ đọc F2** (form ĐHVT HCM) & **F3** (cú pháp mẫu VSICO có dòng Lệnh & SĐT): xử lý dấu chấm thừa trước ngày (`.9/10/2026`), nhãn kép `Đóng , Trả hàng: Tra 1x20`, alias `Nhựa Long An` -> `Nhựa Á Đông`, giữ nguyên tên `Nguyên Thanh Phong`, `Số seal:` trống, `8h` -> `08:00` | `src/parsing/trip_parser.py` + `src/handlers/extraction_handler.py` | **Hoàn thành 100%** (`TC-04`, `TC-05`) |
| 3 | **Chuẩn hóa & kiểm tra từng trường theo Bảng 6.2**: Cont ISO 6346 Modulo 11 (`TC-06`), SĐT đúng 10 chữ số bắt đầu bằng `0` (`TC-07`), phân biệt biển đầu kéo và biển rơ-moóc `15R...` (`TC-08`), trả về danh sách lỗi (`warnings`) và câu nhắc nhà xe (`reply_to_carrier`) | `src/domain/rules.py` + `src/validation/validators.py` + `src/outbound/templates.py` | **Hoàn thành 100%** (`TC-06`, `TC-07`, `TC-08`) |
| 4 | **Đầu ra Bản ghi chuẩn (`canonical_record`)**: mỗi container 1 bản ghi chuẩn 15 trường; tin xã giao chặn ở bộ lọc 2 tầng (`TC-16`); tin tự do không theo F1/F2/F3 chuyển bước AI (`ZCB-10` / `route_to_ai_zcb10=true`) | `src/domain/models.py` + `src/messaging/classifier.py` + `src/parsing/ai_fallback.py` | **Hoàn thành 100%** (`TC-16`, `ZCB-10`) |
| 5 | **Kết quả mong đợi**: `TC-01` đến `TC-08` và `TC-16` chạy đúng 100%, **không cần gọi AI (`used_ai = false`, `ai_calls_count = 0`)** | `GET/POST /api/messages/test-suite/dat-module` | **9/9 PASS (`ai_calls_count = 0`)** |

---

## 2. Danh Sách Các API Dùng Để Test

### 2.1. API 1: Chạy tự động toàn bộ 9 Test Cases (`TC-01` -> `TC-08` và `TC-16`) chỉ với 1 cú click
- **Method**: `GET` hoặc `POST`
- **URL**: `http://localhost:8000/api/messages/test-suite/dat-module`
- **Công dụng**: Chạy tự động toàn bộ 9 ca kiểm thử chuẩn của module Đạt (`TC-01` đến `TC-08` và `TC-16`), tự động đối chiếu từng trường của `canonical_record`, `warnings`, `reply_to_carrier`, và xác nhận `ai_calls_count = 0`.

**Ví dụ gọi bằng cURL:**
```bash
curl -X POST "http://localhost:8000/api/messages/test-suite/dat-module"
```

**Kết quả JSON trả về (tóm tắt):**
```json
{
  "ok": true,
  "module_owner": "Đạt – Module Đọc hiểu và định tuyến",
  "total_cases": 9,
  "passed_cases": 9,
  "failed_cases": 0,
  "ai_calls_count": 0,
  "summary": "PASS 9/9 test cases (TC-01 -> TC-08, TC-16), số lần gọi AI = 0 (đạt chuẩn 100% Rule-based không cần gọi AI).",
  "results": [
    {
      "tc_id": "TC-01",
      "passed": true,
      "used_ai": false,
      "source_format": "F1",
      "processing_status": "processed"
    }
  ]
}
```

---

### 2.2. API 2: Kiểm thử nhanh bất kỳ nội dung tin nhắn nào (`POST /api/messages/test-parse`)
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/messages/test-parse`
- **Headers**: `Content-Type: application/json`
- **Công dụng**: Truyền trực tiếp câu tin nhắn cần test vào để xem ngay kết quả nhận diện định dạng (`F1`/`F2`/`F3`/`tu_do`), Bản ghi chuẩn (`canonical_records`), danh sách lỗi Bảng 6.2 (`warnings`), câu trả lời nhắc nhà xe (`reply_to_carrier`), và cờ chuyển AI (`route_to_ai_zcb10`).

---

## 3. Chi Tiết Bộ Payload Test Từng Ca (`TC-01` -> `TC-08`, `TC-16` & `ZCB-10`) Trên Postman

### Ca 1 – `TC-01`: Định dạng F1 chuẩn nhà xe miền Bắc
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "1 xe 15C17066/ Phạm Văn Huynh đt:  0986713346 / VSIU2621051 chì 23333878",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng**:
  - `source_format`: `"F1"`
  - `used_ai`: `false`
  - `canonical_records[0]`:
    - `plate`: `"15C17066"`
    - `driver_name`: `"Phạm Văn Huynh"`
    - `driver_phone`: `"0986713346"`
    - `cont_no`: `"VSIU2621051"` (`check_digit_valid = true`)
    - `seal_no`: `"23333878"`
  - `warnings`: `[]`

---

### Ca 2 – `TC-02`: Định dạng F1 (SĐT dính liền tên tài xế, không có chữ `đt:`, chữ `h` viết thường)
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "2 Xe 15h00642 / Đoàn Văn Biên 0984457785/ VSIU2321938 chì 23333310",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng**:
  - `source_format`: `"F1"`, `used_ai`: `false`
  - `plate`: `"15H00642"` (tự động viết hoa chữ `H`)
  - `driver_name`: `"Đoàn Văn Biên"` (tách sạch SĐT khỏi tên)
  - `driver_phone`: `"0984457785"`
  - `cont_no`: `"VSIU2321938"` (`check_digit_valid = true`), `seal_no`: `"23333310"`
  - `warnings`: `[]`

---

### Ca 3 – `TC-03`: Định dạng F1 (Có dấu hai chấm sau chữ `xe:`)
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "3 xe: 15H06722/ Đào Đức Thoại đt:  0364461978/ VSIU2323000 chì 23333330",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng**:
  - `source_format`: `"F1"`, `used_ai`: `false`
  - `plate`: `"15H06722"`, `driver_name`: `"Đào Đức Thoại"`, `driver_phone`: `"0364461978"`
  - `cont_no`: `"VSIU2323000"` (`check_digit_valid = true`), `seal_no`: `"23333330"`
  - `warnings`: `[]`

---

### Ca 4 – `TC-04`: Định dạng F2 (Form ĐHVT HCM với tất cả các điểm khó ở Mục 2)
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "Đầu ĐHVT HCM đang gửi nội dung xe trả hàng:\n1.  Ngày: .9/10/2026 : Đóng , Trả hàng: Tra 1x20 Nhựa Long An\n- Tên lái xe: Nguyên Thanh Phong\n- Sđt: 0931142873\n-  Số xe: 50H-04915\n- Số cont : VSIU2620327\n-  Số seal:\n- Thời gian xe đến kho: 8h",
  "timestamp": "2026-10-08T18:00:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng (`canonical_records[0]`)**:
```json
{
  "source_format": "F2",
  "plan_date": "2026-10-09",
  "order_type": "tra",
  "customer_raw": "Nhựa Long An",
  "customer_id": "Nhựa Á Đông",
  "location_raw": null,
  "warehouse_id": null,
  "plate": "50H04915",
  "driver_name": "Nguyên Thanh Phong",
  "driver_phone": "0931142873",
  "cont_no": "VSIU2620327",
  "cont_size": "20",
  "seal_no": null,
  "eta": "08:00",
  "match_source": "customer_alias"
}
```

---

### Ca 5 – `TC-05`: Định dạng F3 (Cú pháp mẫu chuẩn VSICO có dòng Lệnh và SĐT)
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "Khách hàng: Nhựa Á Đông\nLệnh: Trả\nBiển số xe: 50H-04915\nTên lái xe: Nguyễn Thanh Phong\nSĐT: 0931142873\nSố cont: VSIU2620327\nSố chì:\nĐiểm đóng/trả: Kho Nhựa Á Đông – Long An\nThời gian dự kiến đến kho: 08:00",
  "timestamp": "2026-10-09T07:00:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng (`canonical_records[0]`)**:
```json
{
  "source_format": "F3",
  "plan_date": "2026-10-09",
  "order_type": "tra",
  "customer_raw": "Nhựa Á Đông",
  "customer_id": "Nhựa Á Đông",
  "location_raw": "Kho Nhựa Á Đông – Long An",
  "warehouse_id": null,
  "plate": "50H04915",
  "driver_name": "Nguyễn Thanh Phong",
  "driver_phone": "0931142873",
  "cont_no": "VSIU2620327",
  "cont_size": null,
  "seal_no": null,
  "eta": "08:00",
  "match_source": "direct_match"
}
```

---

### Ca 6 – `TC-06`: Kiểm tra Bảng 6.2 – Số container sai chữ số kiểm tra cuối theo ISO 6346 (`VSIU2323001`)
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2323001 chì 23333878",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng**:
  - `used_ai`: `false`
  - `processing_status`: `"needs_review"`
  - `canonical_records[0].cont_no`: `"VSIU2323001"` (giữ nguyên số nhà xe gửi, không tự ý sửa trong DB)
  - `validation_results[0].check_digit_valid`: `false`
  - `warnings`: `["ISO6346_CHECK_DIGIT_MISMATCH(expected=0,actual=1)"]`
  - `reply_to_carrier`: `"[VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại thông tin sau:\n- Xe 15C-170.66: số container 'VSIU2323001' sai số kiểm tra cuối theo ISO 6346 (gợi ý đúng: VSIU2323000)."`

---

### Ca 7 – `TC-07`: Kiểm tra Bảng 6.2 – SĐT tài xế thiếu chữ số (chỉ có 9 số `098457785` hoặc `098******`)
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 098457785 / VSIU2621051 chì 23333878",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng**:
  - `used_ai`: `false`
  - `processing_status`: `"needs_review"`
  - `canonical_records[0].driver_name`: `"Phạm Văn Huynh"`
  - `canonical_records[0].driver_phone`: `"098457785"`
  - `warnings`: `["INVALID_DRIVER_PHONE"]`
  - `reply_to_carrier`: `"[VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại thông tin sau:\n- Xe 15C-170.66: SĐT tài xế '098457785' không hợp lệ (cần đúng 10 chữ số bắt đầu bằng số 0)."`

---

### Ca 8 – `TC-08`: Kiểm tra Bảng 6.2 – Biển số rơ-moóc (`15R01234`) đặt ở vị trí biển số xe đầu kéo
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "1 xe 15R01234/ Phạm Văn Huynh đt: 0986713346 / VSIU2621051 chì 23333878",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng**:
  - `used_ai`: `false`
  - `processing_status`: `"needs_review"`
  - `canonical_records[0].plate`: `null`
  - `validation_results[0].trailer_plate`: `"15R-012.34"`
  - `warnings`: `["MISSING_TRUCK_PLATE", "TRAILER_PLATE_IN_TRUCK_POSITION(15R-012.34)"]`
  - `reply_to_carrier`: `"[VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại thông tin sau:\n- Xe dòng #1: thiếu biển số xe đầu kéo ('15R-012.34' là biển số rơ-moóc, vui lòng bổ sung biển số đầu kéo)."`

---

### Ca 9 – `TC-16`: Bộ lọc 2 tầng – Tin nhắn xã giao (`ok anh, để em báo tài`)
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "ok anh, để em báo tài",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": false
}
```
- **Kết quả kỳ vọng**:
  - `intent`: `"IGNORE_CHAT"`
  - `processing_status`: `"ignored_chat"`
  - `used_ai`: `false`
  - `canonical_records`: `[]`
  - `reply_to_carrier`: `null`

---

### Ca 10 – Định tuyến sang AI (`ZCB-10`): Tin văn xuôi tự do không theo F1/F2/F3
- **POST** `http://localhost:8000/api/messages/test-parse`
- **Body (JSON)**:
```json
{
  "text": "Anh ơi chiều nay bên em cho tài xế Phong số 0931142873 vào kho đóng hàng khách Nhựa Á Đông nhé",
  "timestamp": "2026-10-09T07:30:00",
  "allow_ai_fallback": true
}
```
- **Kết quả kỳ vọng**:
  - `source_format`: `"tu_do"`
  - `route_to_ai_zcb10`: `true`
  - Khi `allow_ai_fallback = true`, hệ thống tự động che SĐT `0931142873` thành `0931xxxx73` trước khi gửi tới `gemini-3.5-flash` và khôi phục lại `0931142873` trong `canonical_records`.

---

## 4. Test Lưu Thật Vào MySQL Qua `POST /webhook` & Tra Cứu Qua `GET /api/messages/detail/{message_id}`

Nếu muốn kiểm thử luồng lưu vào cơ sở dữ liệu MySQL (tạo bản ghi trong `zalo_messages`, `extraction_runs`, `truck_records`, `container_jobs`, `review_cases`, `bot_replies`):

1. **Gửi tin nhắn vào Webhook**:
   - **POST** `http://localhost:8000/webhook`
   ```json
   {
     "msg_id": "test_tc06_iso6346_01",
     "group_id": "group_nha_xe_mien_bac",
     "sender_id": "user_nha_xe_01",
     "sender_name": "Nhà Xe Hải Phòng",
     "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2323001 chì 23333878",
     "timestamp": "2026-10-09T07:30:00"
   }
   ```
2. **Xem chi tiết kết quả lưu DB (bao gồm cả `review_cases` và `bot_replies`)**:
   - **GET** `http://localhost:8000/api/messages/detail/test_tc06_iso6346_01`
