# Zalo OA – TMS | Tổng quan bộ 25.000 test

> **Trạng thái:** Dữ liệu test đã sinh và đối chiếu số lượng, **chưa chạy Bot**. Đây là bộ dữ liệu mô phỏng có tham chiếu dữ liệu TMS người dùng cung cấp, không phải 25.000 hội thoại Zalo thực tế.

## 1. Mục đích

Bộ test đánh giá khả năng Bot điều hành vận tải khi xử lý tin nhắn Zalo lộn xộn: tách biển số xe, mã container, tên/SĐT tài xế; liên kết nhiều tin nhắn cùng chuyến; xác định lệnh trả / lệnh đóng / lệnh kết hợp; giải quyết các ứng viên không có container; bổ sung, cập nhật, đổi xe, hủy, hoàn tác, và đảm bảo không ghi nhầm TMS.

**Đơn vị test:** `1 scenario = 1 Test ID`. Một scenario có thể chứa một hoặc nhiều sự kiện (`messages`), gồm tin nhắn hoặc sự kiện nghiệp vụ giả lập. Không đồng nhất số scenario với số tin nhắn hay số lệnh.

## 2. Thống kê đã đối chiếu lại từ JSONL gốc

| Chỉ số | Số lượng |
|---|---:|
| Tổng scenario | **25,000** |
| Workflow scenarios | **20.000** |
| Format & Entity scenarios | **5.000** |
| Tổng sự kiện trong `messages[]` | **44,567** |
| Sự kiện workflow | **39,567** |
| Sự kiện Format & Entity | **5.000** |
| Họ tình huống (theo sheet + family) | **134** |
| Bản ghi chuyến được gán nhãn trong FORMAT | **19,031** |
| Test FORMAT có trên 10 chuyến/tin | **500** |
| Số chuyến tối đa trong một tin FORMAT | **40** |

Lưu ý: các sự kiện workflow bao gồm cả `web_approval`, `tms_response`, `tms_timeout`, `forward`, v.v. nên không thể gọi toàn bộ chúng là tin nhắn Zalo. Các số trên được đếm lại từ file JSONL hiện tại (thay thế số lượt tin nhắn từng nêu ở tài liệu cũ).

## 3. Cấu trúc file và nội dung từng sheet Excel

File Excel: `zalo_tms_25000_tests.xlsx`. Có **7 sheet test + 1 sheet TMS fixtures + 1 Dashboard**.

| Sheet Excel thực tế | Test | Mục tiêu | Các cột |
|---|---:|---|---|
| `01_CONTEXT` | 5.000 | Nhiều lượt, cùng người/khác người, quote/reply, tin chen ngang, bối cảnh không rõ | `Test ID`, `Bối cảnh trước`, `Tin nhắn mới`, `Case/Lệnh kỳ vọng`, `Hành động kỳ vọng`, `Kết quả Bot`, `PASS/FAIL` |
| `02_RETURN ORDER` | 3.500 | Tra container, lệnh trả và phát hiện mâu thuẫn/thiếu | `Test ID`, `Tin nhắn`, `Container`, `Lệnh trả kỳ vọng`, `Hành động kỳ vọng`, `Kết quả Bot`, `PASS/FAIL` |
| `03_LOAD ORDER` | 5.500 | Lệnh đóng có/không có container; mapping theo lệnh/kho/tuyến/thời gian/booking; biết hỏi lại | `Test ID`, `Tin nhắn`, `Container (nếu có)`, `Lệnh đóng kỳ vọng`, `Lý do ghép lệnh`, `Hành động kỳ vọng`, `Kết quả Bot`, `PASS/FAIL` |
| `04_COMBINED ORDER` | 2.500 | Trùng cont trả/đóng, phân biệt chặng và quan hệ kết hợp giả lập | `Test ID`, `Tin nhắn`, `Container`, `Lệnh/Chặng kỳ vọng`, `Hành động kỳ vọng`, `Kết quả Bot`, `PASS/FAIL` |
| `05_UPDATE CANCEL` | 2.500 | Đổi xe/tài xế, bổ sung, sửa, hủy pending, state transition | `Test ID`, `Bối cảnh trước`, `Tin nhắn mới`, `Lệnh kỳ vọng`, `Trạng thái cuối kỳ vọng`, `Kết quả Bot`, `PASS/FAIL` |
| `06_EDGE CASES` | 1.000 | Tin nhiễu, dữ liệu sai, webhook lặp/trễ, phân quyền, OCR giả lập | `Test ID`, `Dữ liệu đầu vào`, `Kết quả kỳ vọng`, `Kết quả Bot`, `PASS/FAIL` |
| `08_FORMAT ENTITY` | 5.000 | Đa dạng cách viết, dấu phân cách, F1/F2/F3, 1–40 chuyến/tin, ghép đúng cặp xe–cont–tài–SĐT | `Test ID`, `Tin nhắn`, `Thông tin kỳ vọng (JSON)`, `Kết quả Bot`, `PASS/FAIL` |
| `07_TMS_FIXTURES` | — | Snapshot 225 lệnh RO/LO để tra cứu/đối chiếu | Thông tin lệnh, tuyến, container, seal, booking, địa chỉ, thời gian… |
| `00_DASHBOARD` | — | Đếm tổng, PASS, FAIL, NOT RUN, Pass Rate theo sheet | Tổng hợp tự động từ cột `PASS/FAIL` |

**Tỷ trọng ưu tiên:** `CONTEXT + RETURN ORDER + LOAD ORDER = 14.000/25.000 = 56%`. Nếu tính riêng 20.000 test nghiệp vụ thì ba nhóm này chiếm **70%**. `FORMAT & ENTITY` thêm 20% toàn bộ để kiểm tra tầng đầu vào.

### Định dạng trong FORMAT & ENTITY

| Họ tình huống | Test | Ghi chú |
|---|---:|---|
| F1_VERTICAL | 280 | Nhiều dòng theo từng trường |
| F2_INLINE | 280 | Một hàng nhiều trường |
| F3_TABLE | 280 | Dạng bảng/cột |
| DELIMITERS | 1.200 | Phẩy, chấm phẩy, tab, pipe, slash, dấu cách, emoji, hỗn hợp |
| TEXT_VARIANTS | 760 | Viết tắt, thiếu dấu, chữ hoa/thường, đổi thứ tự, lỗi gõ |
| MULTI_2_5 | 600 | 2–5 chuyến/tin |
| MULTI_6_10 | 400 | 6–10 chuyến/tin |
| MULTI_11_20 | 350 | 11–20 chuyến/tin |
| MULTI_21_40 | 150 | 21–40 chuyến/tin |
| FRAGMENTED_LAYOUT | 260 | Rời rạc trong cùng tin, ghép theo index/nhãn |
| NOISE | 250 | Tin nhiễu, xã giao, phần thừa |
| AMBIGUOUS | 100 | Thực thể có nhưng chưa đủ căn cứ để ghép |
| INVALID | 90 | Biển số/cont/SĐT không hợp lệ |
| **Tổng** | **5.000** | |

**Quan trọng:** F1/F2/F3 là *quy ước tạm của bộ sinh test*: nhiều dòng, một hàng, bảng. `zalo.md` gốc có nhắc F1/F2/F3 nhưng không định nghĩa đầy đủ các format; phải so lại backend trước khi coi đây là bộ tên chính thức.

## 4. Nguồn dữ liệu và ranh giới dữ liệu thật/giả lập

Nguồn được cung cấp:

- `ke_hoach_van_chuyen_2026-11-09.xlsx`: **225 dòng lệnh**, gồm **137 RETURN (`RO...`) có container** và **88 LOAD (`LO...`) chủ yếu chưa có container** trong snapshot. Cách gọi RETURN/LOAD là mapping cho bộ test, cần so khớp quy ước TMS thực.
- `carriers.csv`, `customers.csv`, `drivers.csv`, `warehouses.csv`, `vehicles.csv`: danh mục tham khảo. Không coi việc ghép xe + tài xế cùng carrier trong bài test là bằng chứng phân công vận tải thật.
- `zalo_tms_25000_tms_fixtures.json`: bản sao snapshot lệnh có metadata nguồn; chưa có gán xe/tài/trạng thái TMS xác thực.

**Giả lập bắt buộc phải nhận diện:**

- Toàn bộ nội dung chat; danh tính sender giả lập; yêu cầu đổi xe, duyệt Web, phản hồi TMS giả lập.
- Gán xe, tài xế, nhà xe vào lệnh trong `fixture.assumptions_NOT_in_source`; đây là điều kiện giả định của từng bài test.
- Các liên kết RETURN–LOAD trong `synthetic_combined_link`; **không xác nhận TMS đã có các quan hệ đó**.
- SĐT được tự sinh khi nguồn thiếu, có dấu `phone_synthetic` hoặc `phone_synthetic_possible`.
- `ocr_text_mock` / `image_placeholder` chỉ là mô phỏng, **không kiểm tra OCR ảnh thật**.

⚠️ Một số trường thông tin danh mục nguồn, đặc biệt SĐT tài xế, có thể là dữ liệu cá nhân. Chỉ dùng tập này trong môi trường kiểm thử được phép truy cập, không gửi công khai/log không kiểm soát.

## 5. File JSON: định dạng thống nhất, giữ nguyên expected gốc

Đã xuất:

- `zalo_tms_25000_scenarios.json`: **1 đối tượng JSON**, gồm `dataset` (metadata) và `cases` (mảng 25.000 object).
- `zalo_tms_25000_scenarios.jsonl`: **25.000 dòng**, mỗi dòng một object JSON. Khuyên dùng để chạy batch, xử lý streaming và chia tác vụ.
- `zalo_tms_25000_manifest.json`: metadata/thống kê đầy đủ.
- `zalo_tms_25000_schema.json`: JSON Schema kiểm tra cấu trúc chung (không thay thế kiểm thử nghiệp vụ).
- `zalo_tms_25000_examples.json`: một ví dụ có cấu trúc đầy đủ cho mỗi sheet.

Mỗi case vẫn chứa toàn bộ `test_id`, `category`, `family`, `messages`, `fixture`, `expected`, `invariants`, `source_provenance`, `execution_status` và các trường riêng của nguồn. Chỉ **bổ sung**:

| Trường bổ sung | Ý nghĩa |
|---|---|
| `suite` | `transport_workflow` hoặc `format_entity` |
| `run_mode` | `WORKFLOW_MOCK` hoặc `PARSE_ONLY` |
| `sheet_name` | Tên sheet thực tế trong Excel |
| `source_dataset` | Tên JSONL gốc |

**Không ép schema `expected` của hai suite thành một** vì khác nhau về nghiệp vụ: Workflow cần `matched_order_id`, `intent`, `resolution_status`, `tms_write_expected`; Format cần `trips[]`, `expected_trip_count`, `parse_status`, `validation_errors`.

### 5.1 Các trường quan trọng trong workflow case

- `messages[]`: sự kiện theo thứ tự (`message_id`, `sender_id`, `sender_role`, `text`, `reply_to`, `event_kind`, `event_time`). Có thể chứa sự kiện *không phải tin Zalo*: duyệt Web, TMS trả lời, timeout, v.v.
- `fixture.source_orders[]`: ID lệnh được seed từ snapshot.
- `fixture.assumptions_NOT_in_source`: trạng thái giả lập cần áp dụng vào TMS mock **chỉ cho case đó**.
- `expected.intent`, `operation_type`, `matched_order_id`, `matched_leg`, `resolution_status`, `entities`, `reason_codes`, `tms_write_expected`.
- Một số case có thêm `state_after`, `expected_write_count` hoặc `write_count_expected`, `candidate_order_ids`, `combined_id`.
- `invariants[]`: ràng buộc không vi phạm (không ghi sai, không lộ nhầm case, webhook idempotent).

### 5.2 Các trường quan trọng trong FORMAT case

- `messages[0].text`: đầu vào một tin gồm một hoặc nhiều chuyến. Ở suite này sự kiện dùng tên `event_type`; workflow dùng `event_kind`.
- `expected.parse_status`: `OK`, `PARTIAL`, `NEEDS_CLARIFICATION` tùy ca.
- `expected.expected_trip_count` và `expected.trips[]`: từng chuyến theo `trip_index`, các field có thể gồm `truck_plate`, `container_no`, `driver_name`, `driver_phone`.
- `expected.validation_errors`, `unassigned_entities`: thông tin lỗi hoặc entity chưa thể ghép.
- `expected.pairing_policy`, `must_not_infer_missing_fields`, `must_not_cross_pair_trips`, `must_not_write_tms`.
- Một số case có thêm `expected.changes` để phân biệt xe cũ/xe mới, hoặc `expected.expected_reason`.

### 5.3 Một case gọn (rút trích cấu trúc minh họa)

```json
{
  "test_id": "FMT-00001",
  "category": "FORMAT & ENTITY",
  "suite": "format_entity",
  "run_mode": "PARSE_ONLY",
  "sheet_name": "08_FORMAT ENTITY",
  "messages": [{"message_id":"FMT-00001-M1","sender_id":"NHA_XE_DEMO","text":"Xe: 15H17376\nCont: GAOU7816656\n...","event_type":"message"}],
  "expected": {"expected_trip_count":1,"trips":[{"trip_index":1,"container_no":"GAOU7816656","truck_plate":"15H17376"}]},
  "execution_status": "NOT RUN"
}
```

Đoạn rút trích này chỉ để giải thích cách đọc, không phải object đầy đủ. Xem `zalo_tms_25000_examples.json` hoặc JSONL để lấy object hoàn chỉnh.

## 6. Cách chạy test tự động

**Bước 1 — Chọn test:** đọc JSONL từng dòng; lọc `category`, `family`, `test_id`, `run_mode`.

**Bước 2 — Reset môi trường cho mỗi case:** tách biệt trạng thái DB mock, session/context, hàng đợi, message cache. Không ghi production TMS.

**Bước 3 — Seed fixture:**

- `WORKFLOW_MOCK`: lấy các `fixture.source_orders` từ `zalo_tms_25000_tms_fixtures.json`, sau đó **chỉ trong sandbox** áp dụng `assumptions_NOT_in_source`, gồm cả liên kết kết hợp giả lập nếu có.
- `PARSE_ONLY`: không cần tạo lệnh TMS hoặc quyền ghi. Chỉ chạy extractor/parser với text và phụ trợ đọc danh mục (nếu có) để chuẩn hóa.

**Bước 4 — Replay tuần tự** từng `messages[]`. Dùng `event.get('event_kind', event.get('event_type','message'))` để chuẩn hóa loại sự kiện. `reply_to` và thứ tự sự kiện cần được truyền nguyên trạng. `web_approval` và `tms_response` là sự kiện mô phỏng của runner, **không được gửi dưới dạng tin chat thông thường**.

**Bước 5 — Lấy structured output** của Bot; so với `expected` và kiểm tra trạng thái mock TMS cuối case. Nếu backend API có các tên trường khác, chuẩn hóa bằng adapter trước khi so.

**Bước 6 — Chấm assertion:** xem mục 7. Cần so `matched_order_id` và `matched_leg` chính xác; so biển số/cont sau chuẩn hóa *không làm mất vai trò cũ/mới*, SĐT sau bỏ khoảng trắng/dấu chấm; các trường không xuất hiện trong tin phải không được tự suy diễn. Khi một case kỳ vọng `NEEDS_CLARIFICATION` hoặc không match, Bot hỏi lại là PASS nếu đúng hành động và không tự ghi TMS.

**Bước 7 — Lưu log:** theo `test_id`, Bot version, seed, `expected`, `actual`, các assertion, latency, token/LLM fallback, mock DB diff, lỗi gốc và trạng thái `PASS`/`FAIL`/`BLOCKED`.

**Bước 8 — Điền Excel:** ghi kết quả JSON vào cột `Kết quả Bot`, cập nhật `PASS/FAIL`. Dashboard tính số đạt dựa trên công thức, chưa tự gọi API Bot.

### Gợi ý pseudo-code

```python
import json

with open('zalo_tms_25000_scenarios.jsonl', encoding='utf-8') as f:
    for line in f:
        case = json.loads(line)
        mock = reset_and_seed(case['fixture']) if case['run_mode'] == 'WORKFLOW_MOCK' else None
        actual = run_scenario(case['messages'], case['run_mode'], mock)
        verdict = evaluate(actual, case['expected'], case['invariants'], mock)
        save_result(case['test_id'], actual, verdict)
```

Các hàm `reset_and_seed`, `run_scenario`, `evaluate`, `save_result` là **giao diện minh họa**, phải nối vào backend/test runner của m; không phải thư viện có sẵn.

## 7. Chỉ số đánh giá và quy tắc PASS/FAIL

| Chỉ số | Cách đo / ý nghĩa |
|---|---|
| Scenario Pass Rate | `PASS / (PASS + FAIL + BLOCKED)`. Báo riêng `NOT RUN`, `SKIP`, coverage. |
| Intent Accuracy | Số case có intent đúng / số case có gán nhãn intent. |
| Entity Field Match | Đúng giá trị và **vai trò** (`old_truck_plate` ≠ `new_truck_plate`), kể cả quan hệ ghép chuyến. |
| Entity Precision / Recall / F1 | Cần nhãn entity *đầy đủ* trên tập đánh giá; workflow `expected.entities` thường chỉ ghi một số trường mục tiêu, nên không đủ để tính F1 tuyệt đối. |
| Context Target Accuracy | Đúng case/đúng người/đúng tin được tham chiếu, hoặc đúng hành vi hỏi lại. |
| Order/Leg Exact Match | Đúng `matched_order_id` và `matched_leg`, bao gồm trường hợp null/không ghép. |
| False Match Rate | Các lệnh đã được Bot ghép nhưng sai / tổng lệnh Bot đã ghép (đo riêng). |
| Correct Abstention Rate | Các trường hợp mơ hồ mà Bot chủ động hỏi lại/không ghép đúng / tổng trường hợp cần abstain. |
| Workflow State Accuracy | Đúng trạng thái pending, hủy yêu cầu, duyệt, sau ghi; kiểm mock DB, không chỉ văn bản Bot. |
| Critical Safety Failures | Ghi sai đơn, ghi nhầm chặng, lộ dữ liệu, vượt quyền, ghi trùng từ webhook. Bất kỳ lỗi nào → `BLOCKED`. |
| Latency P50/P95 | Đo riêng parse-only, workflow, OCR/vision nếu có. |

**PASS:** tất cả assertion bắt buộc đạt. **FAIL:** có assertion sai. **BLOCKED:** vi phạm an toàn nghiêm trọng; phải chặn phát hành dù điểm tổng cao. **NOT RUN:** chưa thực thi; **SKIP:** chủ động bỏ qua có lý do. Dashboard ban đầu chỉ tổng hợp PASS/FAIL/NOT RUN theo ô Excel, nên nếu dùng BLOCKED/SKIP cần bổ sung công thức thống kê tương ứng.

Không thể suy ra Bot đạt 95% chỉ từ việc sinh 25.000 mẫu; phải chạy và có actual output. Bộ này là regression tổng hợp, chưa thay thế kiểm thử trên log Zalo thật được ẩn danh.

## 8. Những rủi ro cần theo dõi

1. **Lệnh trả:** container trùng lịch sử/ngày khác; không được chỉ tra cont rồi cập nhật mù quáng.
2. **Lệnh đóng không cont:** cân nhắc booking, kho, tuyến, thời gian, nhà xe, xe, tài; khi nhiều lệnh gần giống phải hỏi lại.
3. **Lệnh kết hợp:** cùng cont có thể là RETURN hoặc LOAD; liên kết trong bộ này là giả lập, cần xác minh enum/ID TMS thật.
4. **Context chat nhiều người:** không lấy tin nhắn gần nhất của cả nhóm làm bối cảnh duy nhất; cần người gửi, reply/quote, case/thread và xác nhận.
5. **Sửa/hủy:** hủy pending khác với hủy chuyến TMS; cập nhật thực tế cần kiểm tra phiên bản và quyền trước khi ghi.
6. **Tin nhiều chuyến:** đúng số lượng thôi chưa đủ; mỗi hàng phải ghép đúng xe, cont, tài, SĐT. Với trường hợp mơ hồ, không tự cross-pair.
7. **Dữ liệu cá nhân:** không đưa SĐT nguồn lên dịch vụ ngoài nếu chưa có căn cứ và kiểm soát phù hợp.

## 9. Giới hạn của bộ này / việc cần hoàn thiện tiếp

- Dữ liệu chỉ có snapshot kế hoạch **một ngày**; test nhiều ngày hoặc ca qua đêm giả lập cần bổ sung fixture các ngày liên quan.
- Không có toàn bộ quan hệ thực của xe, tài xế, carrier, kho, lệnh kết hợp, phiên bản TMS; phải xác minh trước production.
- FORMAT 5.000 case có nhãn trip rõ hơn workflow, nhưng với một số ca `PARTIAL`/`NEEDS_CLARIFICATION` cần dùng assertion riêng cho entity không thể gán và validation errors.
- Workflow 20.000 case cần **gán nhãn bổ sung** nếu muốn đo F1 extraction end-to-end thay vì chỉ các field assertion.
- Bộ test ảnh thực tế chưa có: placeholder OCR không được tính vào OCR accuracy.
- Có nhiều biến thể cùng họ, không bảo đảm bao phủ *mọi* tình huống có thể xảy ra; nên lấy lỗi mới từ pilot Zalo đã ẩn danh để thêm vào regression.
- Với 25.000 scenario, nên chạy smoke 50–100 case trước, rồi batch theo sheet và cuối cùng regression toàn bộ, không gửi đồng thời 25.000 yêu cầu vào Bot production.

## 10. Danh sách file đầu ra

| Tên file | Nội dung |
|---|---|
| `zalo_tms_25000_tests.xlsx` | Excel 25.000 test + Dashboard + source fixtures |
| `zalo_tms_25000_README.md` | Tài liệu tổng quan này |
| `zalo_tms_25000_scenarios.json` | Toàn bộ 25.000 case dưới mảng `cases[]`, có metadata |
| `zalo_tms_25000_scenarios.jsonl` | Toàn bộ 25.000 case; mỗi dòng một object |
| `zalo_tms_25000_tms_fixtures.json` | 225 lệnh nguồn đã trích, không có gán xe thật |
| `zalo_tms_25000_manifest.json` | Thống kê số lượng, sự kiện và họ tình huống |
| `zalo_tms_25000_schema.json` | JSON Schema cấu trúc tối thiểu |
| `zalo_tms_25000_examples.json` | 7 ví dụ đầy đủ, một ví dụ cho mỗi sheet |
| `zalo_tms_25000_package.zip` | Bộ đóng gói những file trên |

**Nguyên tắc cuối:** Phân biệt **dữ liệu nguồn**, **giả định test**, **gold label kỳ vọng** và **kết quả thực tế của Bot**. Không ghi vào TMS thật trong bất kỳ bài kiểm thử giả lập nào.
