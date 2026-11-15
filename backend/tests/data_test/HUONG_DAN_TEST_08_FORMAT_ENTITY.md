# Hướng dẫn kiểm thử Sheet `08_FORMAT ENTITY` (Format & Entity Parsing)

Tài liệu này hướng dẫn cách tự kiểm thử năng lực phân loại, tách khối (segmentation), bóc tách thực thể (`truck_plate`, `container_no`, `driver_name`, `driver_phone`, `seal_no`, `order_type`, `eta_time`) và kiểm tra tính hợp lệ (ISO 6346, SĐT, biển số) trên nhóm 5.000 test `08_FORMAT ENTITY`, sử dụng dữ liệu từ `backend/tests/data_test/zalo_tms_25000_scenarios.jsonl`.

---

## 1. Phạm vi 13 họ tình huống trong `08_FORMAT ENTITY`

| STT | Họ tình huống (`family`) | Số test | Mục tiêu kiểm thử |
|---:|---|---:|---|
| 1 | `F1_VERTICAL` | 280 | Tin nhắn nhiều dòng, mỗi trường một dòng có nhãn (`Xe:`, `Cont:`, `Tài xế:`, `SĐT:`) |
| 2 | `F2_INLINE` | 280 | Tin nhắn một hàng nhiều trường, ngăn cách bằng dấu gạch chéo `/` hoặc gạch ngang |
| 3 | `F3_TABLE` | 280 | Tin nhắn dạng bảng cột có dòng tiêu đề (`STT | BIỂN SỐ | CONTAINER | TÀI XẾ | SĐT`) |
| 4 | `DELIMITERS` | 1.200 | Đa dạng dấu ngăn cách (`,`, `;`, tab, `|`, `｜`, `/`, `—`, `–`, `·`, `•`, `→`, `#`, emoji, khoảng trắng) |
| 5 | `TEXT_VARIANTS` | 760 | Viết tắt, không dấu, hoa/thường lẫn lộn, đảo thứ tự trường, lỗi gõ |
| 6 | `MULTI_2_5` | 600 | Tin nhắn chứa từ 2 đến 5 chuyến |
| 7 | `MULTI_6_10` | 400 | Tin nhắn chứa từ 6 đến 10 chuyến |
| 8 | `MULTI_11_20` | 350 | Tin nhắn chứa từ 11 đến 20 chuyến (vượt mốc 10 chuyến/tin) |
| 9 | `MULTI_21_40` | 150 | Tin nhắn chứa từ 21 đến 40 chuyến trong cùng 1 tin |
| 10 | `FRAGMENTED_LAYOUT` | 260 | Bố cục rời rạc (`Chuyến 1:... Chuyến 2:...`, tách từng phần theo `#k`, JSON) |
| 11 | `NOISE` | 250 | Tin nhắn có tiền tố/hậu tố nhiễu (`Forwarded message:`, `Ok anh/chị nhé`, chào hỏi thuần) |
| 12 | `AMBIGUOUS` | 100 | Danh sách rời rạc chưa đủ căn cứ ghép cặp (ví dụ: liệt kê `Danh sách xe:` riêng và `Danh sách cont:` riêng) |
| 13 | `INVALID` | 90 | Thực thể sai quy cách (container sai chữ số kiểm tra ISO 6346, SĐT thiếu/thừa số, biển số lỗi) |
| **Tổng** | **13 families** | **5.000** | **19.031 bản ghi chuyến được gán nhãn** |

---

## 2. Cách 1: Kiểm thử tự động bằng Pytest (Nhanh nhất)

Chạy các bộ unit/integration test cho parser, domain rules, Local NLP và Sandbox từ thư mục `backend`:

```bash
cd backend
.venv/bin/pytest tests/test_domain_and_templates.py tests/test_nlp_phobert_and_golden_benchmark.py tests/test_sandbox.py -v
```

Hoặc chạy toàn bộ 99 test backend:

```bash
cd backend
.venv/bin/pytest tests -q
```

---

## 3. Cách 2: Kiểm thử qua Sandbox API (Không ghi DB, không gọi Zalo/LLM)

### 3.1. Qua giao diện Web Dashboard
1. Khởi động backend (`uvicorn src.api.app:app --reload`) và frontend (`npm run dev`).
2. Đăng nhập Web quản lý và vào mục **Thử nghiệm** (`/sandbox`).
3. Dán từng mẫu tin ở **Mục 5** vào ô nội dung, tắt tùy chọn gọi AI Fallback (`allow_ai_fallback = false`) để kiểm tra thuần tầng Rule + Local NLP, sau đó quan sát kết quả từng tầng.

### 3.2. Qua `curl` gọi `POST /api/sandbox/simulate`
(Thay `<JWT_TOKEN>` nếu môi trường bật xác thực bắt buộc, hoặc test trực tiếp trên Swagger `/docs`):

```bash
curl -X POST "http://127.0.0.1:8000/api/sandbox/simulate" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "NX báo: xe 15H/30984 / cont GAOU6147290 / tài Nguyễn Văn Trường / SĐT 0398.288.472",
    "allow_ai_fallback": false
  }'
```

Kiểm tra các trường trong response:
- `ai_executed`: phải là `false` khi `allow_ai_fallback: false`.
- Danh sách chuyến bóc tách được (`truck_plate`, `container_no`, `driver_name`, `driver_phone`) khớp đúng định dạng chuẩn hóa.

---

## 4. Cách 3: Kiểm thử trực tiếp lõi Python và chạy đối chiếu 5.000 test `08_FORMAT ENTITY`

### 4.1. Test nhanh 1 tin nhắn bất kỳ qua CLI
```bash
cd backend
.venv/bin/python -c '
from src.messaging.classifier import IntentClassifier
from src.messaging.segmenter import MessageSegmenter
from src.parsing.trip_parser import TripParser
from src.parsing.ai_fallback import AIFallbackExtractor

msg = """SĐT 0339 872 421, TX Trần Văn Phụng, Xe 50E-33324, Cont GAOU 782812 7"""
intent = IntentClassifier.classify(msg)
segments = MessageSegmenter.segment(msg)
lines = TripParser.parse_message(msg)
need_ai = AIFallbackExtractor.should_trigger_ai(lines, intent)

print("Intent:", intent)
print("Segments count:", len(segments))
print("Need AI fallback:", need_ai)
for idx, ln in enumerate(lines, 1):
    print(idx, {
        "truck_plate": ln.truck_plate,
        "container_no": ln.container_no,
        "driver_name": ln.driver_name,
        "driver_phone": ln.driver_phone,
        "check_digit_valid": ln.check_digit_valid,
        "confidence": ln.confidence,
    })
'
```

### 4.2. Chạy đánh giá riêng toàn bộ 5.000 kịch bản `08_FORMAT ENTITY`
Lệnh dưới đây chạy `ProxyEvaluator.eval_parse_only` trong bộ nhớ (không chạm MySQL, không gọi Zalo/LLM) và in tỷ lệ PASS theo từng family:

```bash
cd backend
.venv/bin/python -c '
import json, sys
from collections import Counter, defaultdict
sys.path.insert(0, ".")
from scripts.run_proxy_25000_eval import JSONL_PATH, ProxyEvaluator

ev = ProxyEvaluator()
by_fam = defaultdict(lambda: [0, 0])
llm_gates = Counter()
with open(JSONL_PATH, "r", encoding="utf-8") as f:
    for line in f:
        sc = json.loads(line)
        if (sc.get("sheet_name") or sc.get("sheet")) != "08_FORMAT ENTITY":
            continue
        res = ev.eval_parse_only(sc)
        fam = sc.get("family", "UNKNOWN")
        by_fam[fam][1] += 1
        if res.passed:
            by_fam[fam][0] += 1
        llm_gates[res.llm_triggered_raw] += 1

tot_p = sum(v[0] for v in by_fam.values())
tot_n = sum(v[1] for v in by_fam.values())
print(f"08_FORMAT ENTITY PASS: {tot_p}/{tot_n} ({tot_p/tot_n*100:.2f}%)")
print("LLM gate triggered:", dict(llm_gates))
for fam, (p, t) in sorted(by_fam.items()):
    print(f"  {fam:20s}: {p:4d}/{t:4d} ({p/t*100:6.2f}%)")
'
```

---

## 5. Bộ test mẫu chuẩn theo 13 họ tình huống (Trích từ tập test)

Dưới đây là 13 test case đại diện trích trực tiếp từ `zalo_tms_25000_scenarios.jsonl` để kiểm thử thủ công qua Sandbox hoặc CLI:

### 5.1. `F1_VERTICAL` (`FMT-00001`)
**Tin nhắn:**
```text
Thông tin xe chuyến này:
Xe: 15H17376
Cont: GAOU7816656
Tài xế: DƯƠNG ĐÌNH TRƯỜNG
SĐT: 0399.994.474
```
**Kỳ vọng:** `parse_status = OK`, `expected_trip_count = 1`, `truck_plate = "15H17376"`, `container_no = "GAOU7816656"`, `driver_name = "DƯƠNG ĐÌNH TRƯỜNG"`, `driver_phone = "0399994474"`.

### 5.2. `F2_INLINE` (`FMT-00281`)
**Tin nhắn:**
```text
NX báo: xe 15H/30984 / cont GAOU6147290 / tài Nguyễn Văn Trường / SĐT 0398.288.472
```
**Kỳ vọng:** `parse_status = OK`, `expected_trip_count = 1`, `truck_plate = "15H30984"`, `container_no = "GAOU6147290"`, `driver_name = "Nguyễn Văn Trường"`, `driver_phone = "0398288472"`.

### 5.3. `F3_TABLE` (`FMT-00561`)
**Tin nhắn:**
```text
STT | BIỂN SỐ | CONTAINER | TÀI XẾ | SĐT
15C09752 | — | Bùi Văn Quang | 0391.588.346
```
**Kỳ vọng:** `parse_status = OK`, `expected_trip_count = 1`, `truck_plate = "15C09752"`, `container_no = null`, `driver_name = "Bùi Văn Quang"`, `driver_phone = "0391588346"`. (Không lấy nhầm chữ `STT`/`TÀI XẾ` ở dòng tiêu đề bảng).

### 5.4. `DELIMITERS` (`FMT-00841`)
**Tin nhắn:**
```text
SĐT 0339 872 421, TX Trần Văn Phụng, Xe 50E-33324, Cont GAOU 782812 7
```
**Kỳ vọng:** `parse_status = OK`, `expected_trip_count = 1`, `truck_plate = "50E33324"`, `container_no = "GAOU7828127"` (ghép đủ số kiểm tra `7` tách bởi khoảng trắng), `driver_name = "Trần Văn Phụng"`, `driver_phone = "0339872421"`.

### 5.5. `TEXT_VARIANTS` (`FMT-02041`)
**Tin nhắn:**
```text
xe 51C.76985 – cont VSIU 246138 0 – SDT 096-861-2693
```
**Kỳ vọng:** `parse_status = OK`, `expected_trip_count = 1`, `truck_plate = "51C76985"`, `container_no = "VSIU2461380"`, `driver_phone = "0968612693"`.

### 5.6. `MULTI_2_5` (`FMT-02801` - 5 chuyến)
**Tin nhắn mẫu (trích đầu):**
```text
Chuyến 1: Xe: 15c-29238
Cont: VSIU 2463871
Tài xế: Phạm Công Chường
SĐT: 039-958-1826
Chuyến 2: Xe: 50H88071
Cont: gaou7959575
Tài xế: LÊ VĂN TUẤN
SĐT: 039-628-2441
```
**Kỳ vọng:** Tách đủ số chuyến (bản đầy đủ của `FMT-02801` gồm 5 chuyến), chuẩn hóa chữ hoa biển số/container (`15C29238`, `GAOU7959575`) và không trộn SĐT/tài xế giữa các chuyến.

### 5.7. `MULTI_6_10`, `MULTI_11_20`, `MULTI_21_40` (`FMT-03401`, `FMT-03801`, `FMT-04151`)
Để test các tin nhắn lớn (12 chuyến đến 36–40 chuyến/tin), lấy trực tiếp nội dung từ JSONL theo `test_id` (`FMT-03801`, `FMT-04151`) bằng lệnh:

```bash
cd backend
.venv/bin/python -c '
import json
from src.parsing.trip_parser import TripParser
targets = {"FMT-03401", "FMT-03801", "FMT-04151"}
with open("tests/data_test/zalo_tms_25000_scenarios.jsonl") as f:
    for line in f:
        sc = json.loads(line)
        if sc["test_id"] in targets:
            lines = TripParser.parse_message(sc["messages"][0]["text"])
            exp_cnt = sc["expected"]["expected_trip_count"]
            print(sc["test_id"], sc["family"], f"extracted={len(lines)}/{exp_cnt}")
'
```

### 5.8. `FRAGMENTED_LAYOUT` (`FMT-04301`)
**Tin nhắn:**
```text
Chuyến 1: Xe: 51D-382.47
Cont: selu4183600
SĐT: 0399 097 943
Chuyến 2: Xe: 51C47858
Cont: TGCU-5311679
Tài xế: PHAN MẠNH LỰC
SĐT: 0398.507.518
Chuyến 3: Xe: 15C/18807
Cont: SELU 4204106
SĐT: 039-266-2938
```
**Kỳ vọng:** `parse_status = OK`, `expected_trip_count = 3`, chuyến 1 & 3 không bị gán nhầm tên `PHAN MẠNH LỰC` từ chuyến 2.

### 5.9. `NOISE` (`FMT-04561`)
**Tin nhắn:**
```text
Forwarded message:
xe 61H07823 / cont gaou2195622 / tài MAI XUÂN TÙNG / SĐT 039-889-3061
Ok anh/chị nhé
```
**Kỳ vọng:** `parse_status = OK`, `expected_trip_count = 1`, `truck_plate = "61H07823"`, `container_no = "GAOU2195622"`, `driver_name = "MAI XUÂN TÙNG"`, `driver_phone = "0398893061"`. Không lấy chữ `"Ok anh/chị nhé"` hoặc `"Forwarded message"` làm thực thể.

### 5.10. `AMBIGUOUS` (`FMT-04811`)
**Tin nhắn:**
```text
Danh sách xe: 50H44833, 60H29729
Danh sách cont: GAOU7953350, SELU4469933
```
**Kỳ vọng:** `parse_status = NEEDS_CLARIFICATION`, `expected_trip_count = 0`. Hệ thống không được tự ý đoán ghép cặp `50H44833` với `GAOU7953350` khi nhà xe chưa xác nhận cặp.

### 5.11. `INVALID` (`FMT-04911`)
**Tin nhắn:**
```text
Xe 50H/01415 cont GAOU2620508 tài PHAN ĐÌNH PHONG sđt 0393834666
```
**Kỳ vọng:** `parse_status = PARTIAL`, `expected_trip_count = 1`, `truck_plate = "50H01415"`, `driver_name = "PHAN ĐÌNH PHONG"`, `driver_phone = "0393834666"`, đồng thời phát hiện lỗi `INVALID_ISO6346_CHECK_DIGIT` cho `GAOU2620508`.

---

## 6. Tiêu chí đạt chuẩn khi nghiệm thu `08_FORMAT ENTITY`

1. Tách đủ số lượng chuyến thực tế từ 1 đến 40 chuyến/tin (`expected_trip_count`).
2. Chuẩn hóa đúng biển số (bỏ `-`, `.`, `/`, khoảng trắng khi đối chiếu TMS), số container (viết hoa 11 ký tự, giữ đủ check digit cuối), SĐT 10 số.
3. Không lẫn dữ liệu giữa các chuyến (`Cross-trip Contamination = 0`).
4. Không bịa/đoán ghép khi danh sách xe và danh sách container tách rời (`AMBIGUOUS -> NEEDS_CLARIFICATION`).
5. Nhận diện và báo lỗi đúng container sai check digit ISO 6346 (`check_digit_valid = False`).
6. Tin nhắn đã bóc tách đủ bằng Rule/Local NLP không tự kích hoạt LLM Fallback (`should_trigger_ai == False`).
