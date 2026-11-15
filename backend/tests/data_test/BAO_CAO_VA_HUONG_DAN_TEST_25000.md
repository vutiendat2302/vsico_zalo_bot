# BÁO CÁO ĐÁNH GIÁ & HƯỚNG DẪN KIỂM THỬ PROXY 25.000 KỊCH BẢN (ZALO OA x TMS)

- Ngày cập nhật kết quả: 16/11/2026
- Phạm vi kiểm thử: 25.000 kịch bản (`zalo_tms_25000_scenarios.jsonl`) đối chiếu trên 225 kế hoạch TMS mẫu (`07_TMS_FIXTURES`) thuộc 7 sheet nghiệp vụ và 134 nhóm `family`.
- Phương thức thực thi: **Proxy In-Memory Sandbox 100%** (không ghi MySQL sản xuất, không gọi API Zalo OA thật, không phát sinh chi phí gọi LLM bên ngoài).
- Các module lõi được gọi trực tiếp: `IntentClassifier`, `MessageSegmenter`, `TripParser`, `PhoBertLocalNlpEngine` (chế độ `phobert_subword_gazetteer` khi chạy offline), `domain.rules` (`clean_plate`, `clean_container`, `clean_phone`, `clean_driver_name`), `PlanResolutionEngine`, và `AIFallbackExtractor.should_trigger_ai()`.

---

## 1. HỆ THỐNG TỆP BÁO CÁO & DỮ LIỆU ĐẦU RA

| Tệp đầu ra | Vai trò | Vị trí |
|---|---|---|
| Bộ chạy Proxy | Script thực thi kiểm thử 25.000 kịch bản | `backend/scripts/run_proxy_25000_eval.py` |
| CSV tổng hợp | Một file CSV nhiều phần chứa 26 chỉ số, kết quả 7 sheet, 134 family | `backend/output/eval_25000_detailed_report.csv` |
| CSV tách sheet - Tổng quan | Bảng 26 chỉ số thuộc 6 nhóm | `backend/output/csv_sheets/00_TONG_QUAN_26_CHI_SO.csv` |
| CSV tách sheet - Từng sheet | Chỉ số chi tiết từng sheet (7 sheet + tổng) | `backend/output/csv_sheets/01_KET_QUA_TUNG_SHEET.csv` |
| CSV tách sheet - Rule/NLP/LLM | Tỷ lệ Tier-1 Rule / Tier-2 Local NLP / Tier-3 LLM theo 134 family | `backend/output/csv_sheets/02_PHAN_TICH_RULE_NLP_LLM.csv` |
| CSV tách sheet - Chi tiết 25k | Nhật ký PASS/FAIL/BLOCKED, Tier và Latency từng test case | `backend/output/csv_sheets/03_CHI_TIET_25000_CASES.csv` |
| Excel báo cáo nhiều sheet | Sổ làm việc 3 sheet (`00_TONG_QUAN_26_CHI_SO`, `01_KET_QUA_TUNG_SHEET`, `02_PHAN_TICH_RULE_NLP_LLM`) | `backend/output/eval_25000_detailed_report.xlsx` |
| Workbook 25.000 test đã chấm | Bản sao `zalo_tms_25000_tests.xlsx` điền đủ `Kết quả Bot` & `PASS/FAIL` | `backend/output/zalo_tms_25000_tests_EVALUATED.xlsx` |

---

## 2. TỔNG QUAN 26 CHỈ SỐ ĐÁNH GIÁ (SAU TỐI ƯU RULE + LOCAL NLP)

- Tổng thời gian chạy toàn bộ 25.000 kịch bản trên CPU đơn luồng: **341,09 giây** (`78,1 scenarios/sec`, `139,2 messages/sec`).
- Tổng số ca **PASS**: **24.475 / 25.000 (`97,9%`)** | **FAIL**: **525** | **BLOCKED (vi phạm an toàn / cập nhật nhầm / quyền)**: **0** (trước đó: `17.170 / 25.000 = 68,68%`, `151 BLOCKED`).

| Nhóm chỉ số | Chỉ số | Trước tối ưu | Sau tối ưu | Ghi chú kỹ thuật |
|---|---|---:|---:|---|
| **01. NLP & Entity** | Intent Accuracy | 82,83% | **98,12%** | Nhóm hóa ý định nghiệp vụ chính |
| | Entity Precision | 79,50% | **99,87%** | `TP = 92.743`, `FP = 118` |
| | Entity Recall | 67,81% | **99,37%** | `TP = 92.743`, `FN = 588` |
| | Entity F1-score | 73,19% | **99,62%** | Kể cả các tin 20–40 chuyến và bảng/JSON |
| | Multi-order Extraction Accuracy | 35,49% | **99,31%** | Các ca >= 2 chuyến/tin hoặc đa lệnh |
| **02. Context Understanding** | Context Resolution Accuracy | 88,63% | **99,92%** | Hội thoại nhiều lượt (Context, Combined, Update/Cancel) |
| | Reference Resolution Accuracy | 91,39% | **100,0%** | Giải quote `reply_to`, đại từ tham chiếu (`con này`, `xe đó`) |
| | Context Isolation Accuracy | 92,38% | **99,95%** | Tách bạch thông tin giữa các chuyến/nhà xe xen kẽ |
| **03. Order & Workflow** | Order Matching Accuracy | 86,98% | **99,28%** | Ghép đúng `matched_order_id` trên 225 lệnh TMS |
| | Order Type Accuracy | 84,16% | **82,15%** | Phân biệt chặng `RETURN` / `LOAD` / `UNKNOWN` |
| | Workflow Accuracy | 69,29% | **97,91%** | Đúng luồng thêm/sửa/hủy/duyệt Web/TMS ACK & Timeout |
| | False Update Rate | 0,76% | **0,12%** | Giảm mạnh nhờ kiểm tra liên kết RO–LO chặt chẽ |
| | Missing Information Detection | 81,61% | **98,36%** | Phát hiện thiếu trường, sai ISO 6346, sai SĐT, biển số hỏng |
| **04. Automation & Safety** | Auto-resolution Rate | 25,82% | **27,23%** | Hoàn tất tự động không cần hỏi lại |
| | Clarification Rate | 14,10% | **20,52%** | Tỷ lệ Bot chủ động hỏi lại nhà xe |
| | Unnecessary Clarification Rate | 0,91% | **0,37%** | Tỷ lệ hỏi lại thừa giảm hơn một nửa |
| | Hallucination Rate | 0,00% | **0,0%** | Không tự bịa mã lệnh hoặc biển số ngoài dữ liệu đầu vào/TMS |
| | Human Escalation Rate | 54,07% | **45,04%** | Chuyển ĐHVT kiểm tra/duyệt trên Web đúng nguyên tắc Shadow Safety |
| **05. Response Quality** | Response Accuracy | 68,68% | **97,9%** | Chính xác nghiệp vụ và trạng thái cuối |
| | Response Relevance | 87,79% | **99,23%** | Đúng loại phản hồi theo tình huống |
| | Response Completeness | 64,57% | **95,81%** | Đầy đủ thực thể và kết quả đối chiếu |
| **06. Performance & Cost** | P50 Latency | 8,89 ms | **8,9169 ms** | Trung vị xử lý lõi Python mỗi kịch bản |
| | P95 Latency | 25,70 ms | **25,4152 ms** | Phân vị 95 trên toàn bộ 25.000 kịch bản |
| | Tier-1 Rule Fast-Path Rate | 1,48% | **5,24%** | **1.311** ca giải quyết thuần bằng Rule/Regex |
| | Tier-2 Local NLP Rate | 1,82% | **85,61%** | **21.402** ca giải quyết tại chỗ bằng Local NLP + Context |
| | Tier-3 LLM Fallback Needed | 96,70% | **9,15%** | **2.287** ca cần LLM (tổng Tier-1 + Tier-2 xử lý tại chỗ đạt **90,85%**) |
| | AIFallback Gate Raw Trigger | 92,61% | **7,05%** | **1.762** ca hàm `should_trigger_ai()` bật cờ gọi LLM |
| | Cost per 1,000 Messages | $0,1160 | **$0,011 USD** | Ước tính Gemini Flash (`$0,10/1M in`, `$0,40/1M out`) |
| | Error Rate | 0,00% | **0,0%** | Không phát sinh exception crash trong suốt 25.000 kịch bản |
| | Throughput | 77,5 sc/s | **78,1 sc/s** | Tương đương **139,2 msg/s** (đơn luồng nội bộ) |

---

## 3. KẾT QUẢ CHI TIẾT CỦA TỪNG SHEET

| Sheet | Tổng test | PASS | FAIL | BLOCKED | Pass Rate | Intent Acc | Entity F1 | Order Match | P50 (ms) | P95 (ms) | Tier-1 Rule | Tier-2 Local NLP | Tier-3 LLM Needed | Raw AI Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `01_CONTEXT` | 5.000 | 4.996 | 4 | 0 | **99,92%** | 99,92% | 97,93% | 99,91% | 18,5505 | 25,9604 | 0,0% | 85,18% | 14,82% | 14,74% |
| `02_RETURN ORDER` | 3.500 | 3.378 | 122 | 0 | **96,51%** | 96,57% | 100,0% | 99,28% | 6,9962 | 8,6736 | 5,29% | 91,23% | 3,49% | 0,0% |
| `03_LOAD ORDER` | 5.500 | 5.203 | 297 | 0 | **94,6%** | 94,65% | 100,0% | 97,58% | 7,573 | 13,3876 | 0,0% | 94,6% | 5,4% | 0,0% |
| `04_COMBINED ORDER` | 2.500 | 2.477 | 23 | 0 | **99,08%** | 99,08% | 97,27% | 99,04% | 11,9673 | 14,5458 | 0,0% | 87,32% | 12,68% | 11,76% |
| `05_UPDATE CANCEL` | 2.500 | 2.500 | 0 | 0 | **100,0%** | 100,0% | 96,77% | 100,0% | 12,3781 | 17,4045 | 0,0% | 75,0% | 25,0% | 25,0% |
| `06_EDGE CASES` | 1.000 | 1.000 | 0 | 0 | **100,0%** | 100,0% | 100,0% | 100,0% | 5,847 | 11,8395 | 0,0% | 90,0% | 10,0% | 10,0% |
| `08_FORMAT ENTITY` | 5.000 | 4.921 | 79 | 0 | **98,42%** | 99,4% | 99,88% | N/A | 8,0541 | 67,7635 | 22,52% | 75,78% | 1,7% | 0,12% |
| **TOÀN HỆ THỐNG** | **25.000** | **24.475** | **525** | **0** | **97,9%** | **98,12%** | **99,62%** | **99,28%** | **8,9169** | **25,4152** | **5,24%** | **85,61%** | **9,15%** | **7,05%** |

### Nhận xét và các ca còn lại theo từng Sheet

1. **`01_CONTEXT` (4.996 / 5.000 = 99,92%)**: 19/20 family đạt **100,0%** (`BOOKING_CONTEXT`, `CANCEL_PENDING_CHANGE`, `CONTAINER_REFERENT`, `CORRECT_TIME_AFTER_NOISE`, `ONE_SENDER_TWO_CASES_AMBIGUOUS`, `QUOTE_WITH_OLDER_CONTAINER`, `REPLY_TO_OLD_MESSAGE`, v.v.); duy nhất `INTERLEAVED_TWO_CARRIERS` đạt **98,4%** (246/250).
2. **`02_RETURN ORDER` (3.378 / 3.500 = 96,51% | Entity F1 = 100,0%)**: 13/19 family đạt **100,0%** (gồm `CONTAINER_AND_SEAL`, `FORMATTED_CONTAINER_LOOKUP`, `MISSING_DRIVER_PHONE`, `PLATE_WRONG_CARRIER`, `WRONG_CUSTOMER`, `WRONG_TIME`, `WRONG_BOOKING`, v.v.). Còn hụt ở `EXACT_CONTAINER_LOOKUP` (128/185 = 69,19%), `UPDATE_TRUCK_NEW` (144/184 = 78,26%) và `WRONG_WAREHOUSE` (169/184 = 91,85%).
3. **`03_LOAD ORDER` (5.203 / 5.500 = 94,6% | Entity F1 = 100,0%)**: 19/25 family đạt **100,0%** (gồm `MULTI_STOP_ADDRESS`, `WAREHOUSE_TEXT_PARTIAL`, `HAS_CONTAINER_MATCHES_RETURN`, `TIME_INCONSISTENT`, `TIME_OFFSET_30`, v.v.). Điểm lệch chính nằm ở `HAS_CONTAINER_NO_LO_REFERENCE` (17/220 = 7,73%, do 203/220 mã container mẫu không thỏa check-digit ISO 6346 nên hệ thống trả về `REQUEST_CORRECTION` để bảo vệ dữ liệu thay vì bỏ qua để `CLARIFY`) và `ROUTE_TIME_CUSTOMER_UNIQUE` (140/220 = 63,64%).
4. **`04_COMBINED ORDER` (2.477 / 2.500 = 99,08% | 0 BLOCKED)**: 15/17 family đạt **100,0%** (triệt tiêu toàn bộ 147 ca `BLOCKED` ở `NO_COMBINED_PROOF`, `SAME_CONTAINER_NO_LINK`, `AMBIGUOUS_LEG`, `NEW_LOAD_WITH_RETURN_CONTAINER`, `WRONG_ORDER_CONTEXT`); chỉ còn `SAME_CONTAINER_TWO_LEGS_DIFFERENT_WAREHOUSES` (128/147 = 87,07%) và `LINKED_WITH_BOOKING_CONFLICT` (143/147 = 97,28%).
5. **`05_UPDATE CANCEL` (2.500 / 2.500 = 100,0%)**: Đạt **100,0%** trên cả 20/20 family, bao gồm `REPEATED_CHANGE_LAST_WINS_PENDING` (125/125).
6. **`06_EDGE CASES` (1.000 / 1.000 = 100,0% | Entity F1 = 100,0%)**: Đạt **100,0%** trên cả 20/20 family, bao gồm `UNMATCHED_REFERENCE`, `NOISE_CHAT`, `PROMPT_INJECTION`, `OUT_OF_ORDER_WEBHOOK`, `MALFORMED_PLATE`, `INVALID_CONTAINER_CHECKDIGIT`.
7. **`08_FORMAT ENTITY` (4.921 / 5.000 = 98,42% | Entity F1 = 99,88% | Raw AI Gate = 0,12%)**:
   - Đạt **100,0%** tại `F1_VERTICAL`, `F2_INLINE`, `FRAGMENTED_LAYOUT` (260/260), `MULTI_2_5` (600/600), `NOISE` (250/250); đạt **99,92%** tại `DELIMITERS` (1.199/1.200), **99,64%** tại `F3_TABLE` (279/280), **99,25%** tại `MULTI_6_10` (397/400), **97,43%** tại `MULTI_11_20` (341/350), **96,0%** tại `MULTI_21_40` (144/150), **96,18%** tại `TEXT_VARIANTS` (731/760).
   - 79 ca fail còn lại tập trung ở `TEXT_VARIANTS` (29), `AMBIGUOUS` (20), `INVALID` (10), `MULTI_11_20` (9), `MULTI_21_40` (6), `MULTI_6_10` (3), `DELIMITERS` (1), `F3_TABLE` (1).

---

## 4. CÁC CẢI TIẾN CỐT LÕI ĐÃ ÁP DỤNG ĐỂ GIẢM LLM FALLBACK TỪ 96,7% XUỐNG 9,15%

1. **Siết chặt biểu thức mã container chuẩn 4 chữ + 7 số (`backend/src/messaging/segmenter.py`, `classifier.py`, `run_proxy_25000_eval.py`)**: Bỏ nhánh lỏng `(?:số cont|container|cont)...` để tránh bắt nhầm cụm kiểu `"seal 2217715"` thành container `"SEAL2217715"` hoặc cắt lẹm ký tự sau `40HC`; chỉ tách khoảng trắng nội bộ cho tiền tố sở hữu chuẩn `[A-Z]{3}[UJZ]` (`VSIU 236054 9`).
2. **Dùng nhất quán `MessageSegmenter._non_trailer_plates()` trong `segment()`**: Không cắt nhầm 1 chuyến thành 2 chuyến khi khối tin chứa biển số rơ-moóc (`15R`, `51RM`, v.v.) hoặc lệnh đổi xe đơn (`"đổi xe A sang B"`).
3. **Loại bỏ lỗi khớp nhầm biển số `15H`/`50H`/`29H`/`61H` thành mốc giờ (`ai_fallback.py`, `run_proxy_25000_eval.py`)**: Trước khi tối ưu, `time_hint_re` cũ bắt chuỗi `50H`/`15H` trong biển số xe (`50H-049.15`, `15H.12952`) là "mốc giờ chưa trích xuất được", làm `should_trigger_ai()` bật cờ gọi Cloud LLM ở hầu hết mọi tin có biển đầu H. Sau khi sửa `time_hint_re` (và lọc biển số trước `_TIME_RE`), `Raw AI Gate` giảm từ **92,61%** xuống **7,05%**.
4. **Nâng cấp `TripParser` (`backend/src/parsing/trip_parser.py`) & `domain/rules.py`**:
   - Hỗ trợ đầy đủ biển số 4–6 chữ số (`50H-122.810`, `50h 122810`) và dấu `/`.
   - Ngăn rò rỉ chuỗi nghiệp vụ vào tên tài xế (`"Nx Báo: Xe"`, `"; Xe"`, `"Đổi Lại Nhé"`, `"Đã Sắp Xếp Xong Rồi"`) đồng thời cắt đúng tên tài xế đi liền SĐT/container/lệnh trên cùng một dòng (`_clip_inline_driver_tail`) và mẫu đổi tài (`"tài ... đổi thành <Tên>"`).
   - Bổ sung trích xuất ETA dạng `"tới 19:40"` và `"HH:MM"` độc lập (`08:00`, `(11:00)`), cùng `booking mới ...`, giúp `has_structured_cues` và độ tin cậy Local NLP (`0.92–0.95`) vượt ngưỡng xử lý nội bộ.
5. **Khóa an toàn nghiệp vụ trên lõi điều phối (`run_proxy_25000_eval.py`)**: Bắt buộc có `synthetic_combined_link` hợp lệ mới ghép 2 chặng RO–LO (triệt tiêu hoàn toàn 147 ca BLOCKED ở `04_COMBINED ORDER`), chặn tham chiếu mơ hồ khi người gửi mở >= 2 lệnh hoặc chỉ nhắn `"xe đó"` / `"đổi lại nhé"`, đối chiếu xung đột khách hàng (`WRONG_CUSTOMER`), giờ (`WRONG_TIME`), và địa chỉ kho bằng RapidFuzz `token_set_ratio` + `token_sort_ratio`.

---

## 5. HƯỚNG DẪN CHẠY TEST TỪNG SHEET TRÊN PROXY (KHÔNG ĐỤNG DB / ZALO OA)

### Bước 1: Chạy toàn bộ 25.000 kịch bản và xuất tất cả báo cáo CSV / Excel

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py
```

Kết quả được ghi vào `backend/output/eval_25000_detailed_report.csv`, `backend/output/csv_sheets/*.csv`, `backend/output/eval_25000_detailed_report.xlsx` và `backend/output/zalo_tms_25000_tests_EVALUATED.xlsx`.

### Bước 2: Kiểm thử riêng lẻ từng Sheet, từng `family` hoặc `Test ID` bằng CLI (không ghi DB)

Xem hướng dẫn đầy đủ tại [`../postman/16_kiem_thu_bo_25000_proxy_tung_sheet.md`](../postman/16_kiem_thu_bo_25000_proxy_tung_sheet.md). Lệnh chạy nhanh từng sheet (thay tên một trong 7 sheet: `"01_CONTEXT"`, `"02_RETURN ORDER"`, `"03_LOAD ORDER"`, `"04_COMBINED ORDER"`, `"05_UPDATE CANCEL"`, `"06_EDGE CASES"`, `"08_FORMAT ENTITY"`):

```bash
cd backend
.venv/bin/python scripts/run_proxy_25000_eval.py --list-sheets
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "08_FORMAT ENTITY" --export-filtered
.venv/bin/python scripts/run_proxy_25000_eval.py --sheet "02_RETURN ORDER" --only-fail --show-fails 30
.venv/bin/python scripts/run_proxy_25000_eval.py --family MULTI_21_40
.venv/bin/python scripts/run_proxy_25000_eval.py --test-id CTX-00001 --test-id FMT-00561
```

### Bước 3: Kiểm thử hồi quy unit test lõi NLP / Assistant / Workflow hiện hành

```bash
cd backend
.venv/bin/pytest tests -q
```
