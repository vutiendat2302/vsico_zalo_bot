# Bộ Hướng Dẫn Kiểm Thử Proxy 25.000 Kịch Bản & Từng Sheet (Zalo OA x TMS)

### Dự Án VSICO Zalo Bot (Proxy Core + Local NLP + Postman Dry-Run Sandbox)

Tài liệu này hướng dẫn đầy đủ cách chạy kiểm thử trên **bộ 25.000 kịch bản** ([`zalo_tms_25000_scenarios.jsonl`](../data_test/zalo_tms_25000_scenarios.jsonl) và [`zalo_tms_25000_tests.xlsx`](../data_test/zalo_tms_25000_tests.xlsx)) theo các mức:
1. Chạy **tất cả 25.000 kịch bản** và xuất báo cáo CSV / Excel nhiều sheet.
2. Chạy kiểm thử **riêng từng sheet** (1 trong 7 sheet).
3. Chạy kiểm thử theo **`family`**, **`Test ID`**, smoke test **`--limit`**, lọc **chỉ ca FAIL (`--only-fail`)**.
4. Chạy kiểm thử từng tin nhắn mẫu (1 chuyến, bảng `F3_TABLE`, 12–40 chuyến/tin, hội thoại nhiều lượt) ngay trên **Postman** qua endpoint Dry-Run `POST /api/sandbox/simulate`.

Nguyên tắc thực thi:
- Toàn bộ bộ chạy Proxy (`backend/scripts/run_proxy_25000_eval.py`) và API `POST /api/sandbox/simulate` đều chạy **In-Memory 100%**: **không ghi MySQL**, **không phát hành tin nhắn Zalo OA thật**, **không tiêu tốn token Cloud LLM** (`allow_ai_fallback: false` / đo cờ `should_trigger_ai()`).
- Tài liệu liên quan: [`BAO_CAO_VA_HUONG_DAN_TEST_25000.md`](../data_test/BAO_CAO_VA_HUONG_DAN_TEST_25000.md) (báo cáo kết quả chuẩn 26 chỉ số) và [`HUONG_DAN_TEST_08_FORMAT_ENTITY.md`](../data_test/HUONG_DAN_TEST_08_FORMAT_ENTITY.md) (chi tiết 5.000 ca bóc tách định dạng).

---

## 1. Cấu Trúc 7 Sheet Trong Bộ 25.000 Kịch Bản

Xem danh mục trực tiếp bằng lệnh CLI:

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --list-sheets
```

Tổng hợp 7 sheet kiểm thử + 2 sheet tham chiếu/tổng hợp trong workbook:

| Sheet | Số test | Số `family` | Mã `Test ID` mẫu | Chế độ (`run_mode`) | Nội dung kiểm thử trọng tâm |
|---|---:|---:|---|---|---|
| `01_CONTEXT` | 5.000 | 20 | `CTX-00001` | `WORKFLOW_MOCK` | Hội thoại nhiều lượt, tách xe/cont/tài/SĐT qua nhiều tin, quote/reply, 2 nhà xe xen kẽ, hủy chờ xác nhận |
| `02_RETURN ORDER` | 3.500 | 19 | `RET-00001` | `WORKFLOW_MOCK` | Tra cứu lệnh trả theo container, sai ISO 6346, sai nhà xe, sai khách hàng, sai kho, sai giờ, sai chì |
| `03_LOAD ORDER` | 5.500 | 25 | `LOAD-00001` | `WORKFLOW_MOCK` | Lệnh đóng có/không container, ghép theo mã lệnh / booking / kho / tuyến / giờ, nhận diện thiếu/trùng |
| `04_COMBINED ORDER` | 2.500 | 17 | `COMB-00001` | `WORKFLOW_MOCK` | Phân biệt chặng trả/đóng trùng container, chỉ ghép kết hợp khi có liên kết hợp lệ |
| `05_UPDATE CANCEL` | 2.500 | 20 | `UPD-00001` | `WORKFLOW_MOCK` | Đổi xe/tài/SĐT/giờ, hủy, hoàn tác, `409 Conflict` version cũ, web duyệt/từ chối, TMS timeout retry |
| `06_EDGE CASES` | 1.000 | 20 | `EDGE-00001` | `WORKFLOW_MOCK` | Tin nhiễu, webhook trùng/lộn thứ tự, sai biển/SĐT/cont, prompt injection, phân quyền chéo tenant |
| `08_FORMAT ENTITY` | 5.000 | 13 | `FMT-00001` | `PARSE_ONLY` | Định dạng F1/F2/F3, 1–40 chuyến/tin, đủ dấu ngăn cách, viết tắt/không dấu, tin rời rạc, nhiễu |
| **Tổng cộng** | **25.000** | **134** | — | — | **44.567 sự kiện** đối chiếu trên 225 lệnh TMS trong `07_TMS_FIXTURES` |

---

## 2. Chạy Toàn Bộ 25.000 Kịch Bản & Đọc File Kết Quả CSV / Excel

### 2.1. Lệnh chạy toàn bộ 25.000 ca

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py
```

Thời gian chạy toàn bộ 25.000 ca trên CPU đơn luồng khoảng ~340 giây (~78 kịch bản/giây). Khi hoàn tất, hệ thống ghi ra đầy đủ các tệp kết quả sau:

| Tệp đầu ra | Định dạng / Cấu trúc | Nội dung chính |
|---|---|---|
| `backend/output/eval_25000_detailed_report.csv` | 1 file CSV UTF-8 BOM nhiều phần | Chứa trọn bộ Section 1 (26 chỉ số), Section 2 (kết quả 7 sheet), Section 3 (134 family kèm tỷ lệ Rule/NLP/LLM) |
| `backend/output/csv_sheets/00_TONG_QUAN_26_CHI_SO.csv` | CSV riêng cho Sheet Tổng quan | Bảng 6 nhóm / 26 chỉ số toàn hệ thống |
| `backend/output/csv_sheets/01_KET_QUA_TUNG_SHEET.csv` | CSV riêng cho Sheet Kết quả | Từng dòng cho `01_CONTEXT` .. `08_FORMAT ENTITY` + `ALL_25000` |
| `backend/output/csv_sheets/02_PHAN_TICH_RULE_NLP_LLM.csv` | CSV riêng cho Sheet Tỷ lệ Tier | Số lượng và `%` của `Tier-1 Rule`, `Tier-2 Local NLP`, `Tier-3 LLM Needed`, `LLM Gate Raw`, `Cost/1k` theo 134 family |
| `backend/output/csv_sheets/03_CHI_TIET_25000_CASES.csv` | CSV nhật ký 25.000 dòng | Chi tiết `Test ID`, `PASS/FAIL/BLOCKED`, `Tier`, `Latency (ms)`, `TP/FP/FN`, `Bot Summary`, `Fail Reason` |
| `backend/output/eval_25000_detailed_report.xlsx` | Excel 3 sheet | Sổ báo cáo trình bày `00_TONG_QUAN_26_CHI_SO`, `01_KET_QUA_TUNG_SHEET`, `02_PHAN_TICH_RULE_NLP_LLM` |
| `backend/output/zalo_tms_25000_tests_EVALUATED.xlsx` | Excel 25.000 ca đã chấm | Bản sao của `zalo_tms_25000_tests.xlsx` đã điền đủ 2 cột `Kết quả Bot` và `PASS/FAIL` |

### 2.2. Kết quả đo thực tế mới nhất với trọng số thật `vinai/phobert-base-v2` (`phobert_transformers_local`)

| Hạng mục | Giá trị đo được |
|---|---:|
| Động cơ NLP cục bộ | **`phobert_transformers_local`** (`vinai/phobert-base-v2`, offline cache + mean-centering + skeleton LRU cache) |
| Tổng ca PASS / Tổng test | **24.254 / 25.000 (`97,02%`)** (FAIL: `746`, BLOCKED: `0`, Wall clock: `335,62s`) |
| Entity Precision / Recall / F1 | **99,85%** / **99,21%** / **99,53%** (`TP=92.591`, `FP=141`, `FN=740`) |
| Intent Accuracy / Multi-order Accuracy | **97,50%** / **97,47%** |
| Context Resolution / Reference Resolution / Isolation | **99,07%** / **98,25%** / **99,95%** |
| Order Matching / Workflow Accuracy / False Update Rate | **99,28%** / **97,02%** / **0,12%** |
| Missing Information Detection / Response Relevance | **97,45%** / **99,18%** |
| Hallucination Rate / Error Rate | **0,00%** / **0,00%** |
| Tier-1 Rule Fast-Path / Tier-2 Local NLP | **5,08%** (`1.270` ca) / **79,96%** (`19.991` ca) -> Tổng tự xử lý nội bộ **85,04%** |
| Tier-3 LLM Fallback Needed / Raw AI Gate | **14,96%** (`3.739` ca) / **12,08%** (`3.021` ca) — Chi phí ước tính **$0,0179 / 1.000 tin** |
| Latency P50 / P95 / Throughput | **2,76 ms** / **39,85 ms** / **80,7 kịch bản/s** (`143,8 tin/s`) |

---

## 3. Hướng Dẫn Chạy Kiểm Thử Riêng Từng Sheet

Sử dụng cờ `--sheet "<TÊN_SHEET>"` để kiểm thử riêng từng sheet mà không cần chờ chạy cả 25.000 ca và không ghi đè file báo cáo tổng `eval_25000_detailed_report.csv`. Nếu muốn lưu riêng kết quả CSV của sheet vừa chạy, thêm cờ `--export-filtered` (lưu tại `backend/output/filtered/`).

### 3.1. Sheet `01_CONTEXT` (5.000 ca — Hội thoại nhiều lượt & Ngữ cảnh)

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "01_CONTEXT"
```

- Các `family` chính (20): `SPLIT_TRUCK_CONTAINER_DRIVER_PHONE`, `BOOKING_CONTEXT`, `CONTAINER_REFERENT`, `ONE_SENDER_TWO_CASES_AMBIGUOUS`, `ONE_SENDER_TWO_CASES_WITH_QUOTE`, `QUOTE_WITH_OLDER_CONTAINER`, `REPLY_TO_OLD_MESSAGE`, `INTERLEAVED_TWO_CARRIERS`, `CROSS_MIDNIGHT_TIME`, `NEGATED_CHANGE`, `CANCEL_PENDING_CHANGE`, v.v.
- Điểm cần kiểm tra: `ContextRes`, `RefRes`, `CtxIso` phải đạt gần `100%`, không nhầm chuyến khi hai nhà xe nhắn xen kẽ hoặc quote lại container cũ.

### 3.2. Sheet `02_RETURN ORDER` (3.500 ca — Lệnh Trả & Đối Chiếu Mâu Thuẫn)

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "02_RETURN ORDER"
```

- Các `family` chính (19): `EXACT_CONTAINER_LOOKUP`, `FORMATTED_CONTAINER_LOOKUP`, `CONTAINER_AND_SEAL`, `ISO_CHECKDIGIT_ERROR`, `PLATE_WRONG_CARRIER`, `WRONG_CUSTOMER`, `WRONG_WAREHOUSE`, `WRONG_BOOKING`, `WRONG_SEAL`, `WRONG_TIME`, `UPDATE_TRUCK_NEW`, `WEB_APPROVED_ASSIGN_TRUCK`, v.v.
- Điểm cần kiểm tra: phát hiện đúng sai check-digit ISO 6346, sai nhà xe sở hữu lệnh, sai kho/khách hàng, không tự ý cập nhật khi có xung đột.

### 3.3. Sheet `03_LOAD ORDER` (5.500 ca — Lệnh Đóng Có/Không Container)

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "03_LOAD ORDER"
```

- Các `family` chính (25): `DIRECT_LO_ID`, `HAS_CONTAINER_DIRECT_LO_ID`, `BOOKING_WITH_LO_ID`, `ROUTE_TIME_CUSTOMER_UNIQUE`, `WAREHOUSE_TEXT_PARTIAL`, `MULTI_STOP_ADDRESS`, `NO_CONTAINER_BOOKING_AMBIGUOUS`, `NO_CONTAINER_ROUTE_AMBIGUOUS`, `NO_CONTAINER_NOT_IN_PLAN`, `TIME_OFFSET_30`, `TIME_INCONSISTENT`, `TMS_SYNC_MISSING`, v.v.
- Điểm cần kiểm tra: ghép đúng mã `LO` theo kho/tuyến/booking khi chưa có cont; khi nhiều ứng viên trùng kho/booking phải hỏi lại (`Clarify`) thay vì đoán bừa (`FalseUpdate = 0%`).

### 3.4. Sheet `04_COMBINED ORDER` (2.500 ca — Ghép Chặng Kết Hợp RO–LO)

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "04_COMBINED ORDER"
```

- Các `family` chính (17): `SYNTH_COMBINED_RETURN_LEG`, `SYNTH_COMBINED_LOAD_LEG`, `NO_COMBINED_PROOF`, `SAME_CONTAINER_NO_LINK`, `SAME_CONTAINER_TWO_LEGS_DIFFERENT_WAREHOUSES`, `AMBIGUOUS_LEG`, `NEW_LOAD_WITH_RETURN_CONTAINER`, `CANCEL_LOAD_LEG_ONLY`, `REPLY_TO_LOAD_IN_COMBINED`, `REPLY_TO_RETURN_IN_COMBINED`, v.v.
- Điểm cần kiểm tra: `BLOCKED = 0`, tuyệt đối không ghép chặng trả và chặng đóng nếu thiếu liên kết `synthetic_combined_link` hoặc khác kho không hợp lệ.

### 3.5. Sheet `05_UPDATE CANCEL` (2.500 ca — Đổi Xe / Hủy / State Machine)

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "05_UPDATE CANCEL"
```

- Các `family` chính (20): `CHANGE_TRUCK_PENDING`, `CHANGE_DRIVER_PENDING`, `CHANGE_PHONE`, `CHANGE_TIME`, `REPEATED_CHANGE_LAST_WINS_PENDING`, `CANCEL_PENDING_CHANGE`, `CANCEL_ORDER_VS_CHANGE`, `CONCURRENT_EDIT`, `STALE_VERSION_409`, `TMS_TIMEOUT_ACK_RETRY`, `WEB_APPROVED_TRUCK_UPDATE`, `WEB_REJECTED_TRUCK_UPDATE`, `ROLLBACK_ALREADY_APPLIED`, v.v.
- Điểm cần kiểm tra: đổi nhiều lần giữ giá trị mới nhất khi chờ duyệt, `STALE_VERSION_409` không ghi đè version cũ, từ chối cập nhật trái phép `UNAUTHORIZED_CHANGE`.

### 3.6. Sheet `06_EDGE CASES` (1.000 ca — Nhiễu, Lỗi Dữ Liệu & Bảo Mật)

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "06_EDGE CASES"
```

- Các `family` chính (20): `NOISE_CHAT`, `SHORT_ACK_WITHOUT_CONTEXT`, `PROMPT_INJECTION`, `CROSS_TENANT_REFERENCE`, `UNAUTHORIZED_DATA_REQUEST`, `INVALID_CONTAINER_CHECKDIGIT`, `MALFORMED_PLATE`, `PHONE_INCORRECT_FORMAT`, `DUPLICATE_EVENT_ID`, `OUT_OF_ORDER_WEBHOOK`, `IMAGE_WITHOUT_TEXT`, `OCR_TEXT_SIMULATION`, v.v.
- Điểm cần kiểm tra: `PASS = 100%`, không thực thi prompt injection, không lộ dữ liệu chéo tenant, webhook trùng/lộn thứ tự vẫn an toàn.

### 3.7. Sheet `08_FORMAT ENTITY` (5.000 ca — Định Dạng F1/F2/F3 & 1–40 Chuyến/Tin)

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "08_FORMAT ENTITY" --export-filtered
```

- Các `family` (13): `F1_VERTICAL`, `F2_INLINE`, `F3_TABLE`, `DELIMITERS`, `TEXT_VARIANTS`, `MULTI_2_5`, `MULTI_6_10`, `MULTI_11_20`, `MULTI_21_40`, `FRAGMENTED_LAYOUT`, `NOISE`, `AMBIGUOUS`, `INVALID`.
- Chạy kết hợp nhiều sheet cùng lúc:

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "01_CONTEXT" --sheet "04_COMBINED ORDER" --export-filtered
```

---

## 4. Chạy Nhanh Theo `Family`, Smoke Test `--limit`, Debug `Test ID` & Lọc Ca `FAIL`

| Nhu cầu | Lệnh thực thi từ `backend/` |
|---|---|
| Smoke test nhanh 100 ca đầu của 1 sheet | `.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "03_LOAD ORDER" --limit 100` |
| Test riêng 1 `family` cụ thể | `.venv/bin/python scripts/run_proxy_25000_eval.py --family MULTI_21_40` |
| Test và in toàn bộ mẫu lỗi của 1 sheet | `.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "02_RETURN ORDER" --only-fail --show-fails 50` |
| Debug chính xác 1 hoặc nhiều `Test ID` | `.venv/bin/python scripts/run_proxy_25000_eval.py --test-id CTX-00001 --test-id FMT-00561 --test-id FMT-03801` |
| Xuất riêng CSV cho 1 sheet ra `output/filtered/` | `.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "08_FORMAT ENTITY" --export-filtered` |

---

## 5. Kiểm Thử Từng Mẫu Từ Bộ 25.000 Trên Postman (Dry-Run `/api/sandbox/simulate`)

Bạn có thể lấy bất kỳ tin nhắn nào trong bộ 25.000 để test trực tiếp qua API Backend **`POST {{baseUrl}}/api/sandbox/simulate`**. Endpoint này chạy Dry-Run hoàn toàn (`"persisted": false`), tự động rollback DB trong `finally`, trả đầy đủ kết quả bóc tách từng dòng, kiểm tra ISO 6346, giải quyết ngữ cảnh và cờ `ai_would_trigger` / `ai_executed`.

### Thiết lập nhanh trên Postman
- `baseUrl`: `http://localhost:8000`
- Đăng nhập lấy `authToken` theo Kịch bản 01 tại [`14_tro_ly_van_tai_phase1.md`](./14_tro_ly_van_tai_phase1.md) (nếu môi trường bật auth) hoặc gọi trực tiếp khi chạy dev.
- Header chung: `Content-Type: application/json`, `Authorization: Bearer {{authToken}}`.

### Kịch Bản P1: Mẫu `FMT-00001` (`08_FORMAT ENTITY / F1_VERTICAL`)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/simulate`
- **Body (`raw` - JSON)**:
```json
{
  "text": "Thông tin xe chuyến này:\nXe: 15H17376\nCont: GAOU7816656\nTài xế: DƯƠNG ĐÌNH TRƯỜNG\nSĐT: 0399.994.474",
  "allow_ai_fallback": false
}
```
- **Script tab `Tests`**:
```javascript
pm.test("Dry-run 0 DB write và 0 LLM", function () {
    pm.response.to.have.status(200);
    const res = pm.response.json();
    pm.expect(res.ok).to.be.true;
    pm.expect(res.persisted).to.be.false;
    pm.expect(res.ai_executed).to.be.false;
    pm.expect(res.ai_would_trigger).to.be.false;
    pm.expect(res.records).to.have.lengthOf(1);
    pm.expect(res.records[0].truck_plate).to.eql("15H-173.76");
    pm.expect(res.records[0].container_no).to.eql("GAOU7816656");
    pm.expect(res.records[0].driver_phone).to.eql("0399994474");
    pm.expect(res.records[0].check_digit_valid).to.be.true;
});
```

### Kịch Bản P2: Mẫu `FMT-00561` (`08_FORMAT ENTITY / F3_TABLE` — Dạng Bảng Cột)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/simulate`
- **Body (`raw` - JSON)**:
```json
{
  "text": "STT | BIỂN SỐ | CONTAINER | TÀI XẾ | SĐT\n15C09752 | — | Bùi Văn Quang | 0391.588.346",
  "allow_ai_fallback": false
}
```
- **Kỳ vọng**: `records` có 1 chuyến với `truck_plate = "15C-097.52"`, `driver_name = "Bùi Văn Quang"`, `driver_phone = "0391588346"`, `container_no = null` (không bắt nhầm ký tự `—`), `ai_executed = false`.

### Kịch Bản P3: Mẫu `FMT-03801` (`08_FORMAT ENTITY / MULTI_11_20` — Tách Nhiều Hơn 10 Chuyến)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/simulate`
- **Body (`raw` - JSON)**:
```json
{
  "text": "Danh sách xe hôm nay (12 chuyến):\nChuyến 1: Xe: 50H.44833\nCont: GAOU7821312\nTài xế: THI TẤN THOẢNG\nSĐT: 0391 569 867\nChuyến 2: Xe: 15H.07285\nCont: SELU4341979\nTài xế: ĐINH TRÍ THÔNG\nSĐT: 039-401-6189\nChuyến 3: Xe: 29E.12495\nCont: gaou7801770\nTài xế: NGUYỀN VĂN KHƯƠNG\nSĐT: 0391630732\nChuyến 4: Xe: 15C14412\nTài xế: NGÔ QUANG BÌNH\nSĐT: 039-948-3262\nChuyến 5: Xe: 50H/43788\nTài xế: NGUYỄN VĂN THÔNG\nSĐT: 0398.663.738\nChuyến 6: Xe: 15H-06105\nCont: TMSU4000620\nTài xế: Vũ Đình Thêu\nSĐT: 0398 078 141\nChuyến 7: Xe: 15H-013.96\nCont: GAOU7820384\nTài xế: Nguyễn Văn Duy\nSĐT: 0399.089.657\nChuyến 8: Xe: 15h-12281\nTài xế: BÙI VĂN TÍNH\nSĐT: 0392301595\nChuyến 9: Xe: 15C-33915\nTài xế: Nguyễn Thế Tuấn\nSĐT: 0392.411.825\nChuyến 10: Xe: 29H-881.20\nCont: MSKU1234565\nTài xế: Phạm Văn An\nSĐT: 0912345678\nChuyến 11: Xe: 15C-118.42\nTài xế: Trần Văn Bình\nSĐT: 0987654321\nChuyến 12: Xe: 50H-049.15\nCont: TCNU3322110\nTài xế: Lê Văn Cường\nSĐT: 0909112233",
  "allow_ai_fallback": false
}
```
- **Script tab `Tests`**:
```javascript
pm.test("Bóc tách đúng 12 chuyến (>10 chuyến/tin) bằng Local NLP", function () {
    pm.response.to.have.status(200);
    const res = pm.response.json();
    pm.expect(res.persisted).to.be.false;
    pm.expect(res.ai_executed).to.be.false;
    pm.expect(res.records).to.have.lengthOf(12);
});
```

### Kịch Bản P4: Mẫu `CTX-00001` (`01_CONTEXT / SPLIT_TRUCK_CONTAINER_DRIVER_PHONE` — Hội Thoại Nhiều Lượt)

- **Method**: `POST`
- **URL**: `{{baseUrl}}/api/sandbox/simulate`
- **Body (`raw` - JSON)**:
```json
{
  "text": "sđt 0987829210",
  "context_messages": [
    "lệnh RO2728 cont DRYU3087202 nhận chuyến nhé",
    "xe 15H.12952",
    "tài HỒ KHẮC SINH"
  ],
  "carrier_hint": "NX-321",
  "allow_ai_fallback": false
}
```
- **Kỳ vọng**: Tầng `context_resolution` gộp đầy đủ thông tin từ 3 tin nhắn trước với SĐT ở tin cuối mà không đánh rơi container hay biển số từ tin cũ.

---

## 6. Cách Đọc 26 Chỉ Số & Tỷ Lệ Tầng Xử Lý (Rule / Local NLP / LLM)

Khi mở `backend/output/csv_sheets/00_TONG_QUAN_26_CHI_SO.csv` hoặc `02_PHAN_TICH_RULE_NLP_LLM.csv`:

1. **Nhóm 01 — NLP & Entity**: `Intent Accuracy`, `Entity Precision`, `Entity Recall`, `Entity F1-score`, `Multi-order Extraction Accuracy` (chấm theo từng tập trường xe/cont/tài/SĐT/giờ/chì trên 1 hoặc nhiều chuyến/tin).
2. **Nhóm 02 — Context Understanding**: `Context Resolution Accuracy` (nối lượt), `Reference Resolution Accuracy` (`quote`/`reply_to`/đại từ), `Context Isolation Accuracy` (không nhầm giữa 2 nhà xe hoặc 2 chặng).
3. **Nhóm 03 — Order & Workflow**: `Order Matching Accuracy` (khớp `matched_order_id`), `Order Type Accuracy` (`RETURN`/`LOAD`/`UNKNOWN`), `Workflow Accuracy`, `False Update Rate` (càng gần `0%` càng tốt), `Missing Information Detection`.
4. **Nhóm 04 — Automation & Safety**: `Auto-resolution Rate`, `Clarification Rate`, `Unnecessary Clarification Rate`, `Hallucination Rate` (`0%`), `Human Escalation Rate` (chuyển ĐHVT duyệt trên Web khi có xung đột/rủi ro).
5. **Nhóm 05 — Response Quality**: `Response Accuracy`, `Response Relevance`, `Response Completeness`.
6. **Nhóm 06 — Performance, Cost & Phân tầng xử lý**:
   - `Tier-1 Rule/Regex`: giải quyết thuần bằng luật chuẩn xác, tốc độ < 1 ms, chi phí `$0`.
   - `Tier-2 Local NLP`: giải quyết nội bộ bằng `TripParser` + `PhoBertLocalNlpEngine` + `RapidFuzz` + Context Memory, chi phí `$0`.
   - `Tier-3 LLM Fallback Needed`: tổng các ca hoặc kích hoạt `should_trigger_ai()` (`LLM Gate Raw`) hoặc xử lý local chưa đạt kỳ vọng nên cần Cloud LLM hỗ trợ.

---

## 7. Bộ Pytest Hồi Quy Xác Nhận Lõi Sau Chỉnh Sửa

Chạy từ thư mục `backend/`:

```bash
cd backend
.venv/bin/pytest tests/test_domain_and_templates.py tests/test_nlp_phobert_and_golden_benchmark.py tests/test_sandbox.py tests/test_assistant_phase1.py -v
```

Hoặc chạy toàn bộ bộ unit/integration test backend:

```bash
cd backend
.venv/bin/pytest tests -q
```
