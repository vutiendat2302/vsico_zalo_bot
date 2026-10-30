# 📮 HƯỚNG DẪN KIỂM THỬ TỰ ĐỘNG BỘ TỆP INPUT TXT (VSICO TEXT FIXTURE RUNNER)
### HỆ THỐNG BOT ZALO TMS VSICO (BÀI TEST 1, BÀI TEST 2, TC-01 ĐẾN TC-20)

Tài liệu này hướng dẫn cách chạy kiểm thử tự động toàn bộ 20 tệp dữ liệu đầu vào trong thư mục [`tests/fixtures/messages/`](./tests/fixtures/messages), cách xem kết quả bóc tách chi tiết trong thư mục [`output/`](./output), và cách thêm tệp mới để hệ thống tự động bóc tách và xuất ra tệp `_output.txt`.

---

## 1. CẤU TRÚC THƯ MỤC KIỂM THỬ

```
backend/tests/vsico_test_txt_files/
├── ALL_TEST_CASES.txt               # Tổng hợp toàn bộ 20 kịch bản test case
├── README.txt                       # Ghi chú tổng quan về bộ fixtures
├── tests/
│   └── fixtures/
│       └── messages/                # Nơi chứa các tệp đầu vào và kỳ vọng
│           ├── TC-01_input.txt      # Tệp đầu vào chứa tin nhắn gốc
│           ├── TC-01_expected.txt   # Kỳ vọng nghiệp vụ đối soát
│           ├── ...                  # Từ TC-01 đến TC-20
│           └── TC-20_input.txt
│
├── output/                          # Thư mục kết quả bóc tách được sinh tự động
│   ├── TC-01_output.txt             # Chi tiết kết quả xe, cont, ISO 6346, JSON
│   ├── ...                          # Đầy đủ 20 tệp output tương ứng
│   └── TC-20_output.txt
│
└── HUONG_DAN_KIEM_THU_TXT_FILES.md  # Tài liệu này
```

---

## 2. CÁCH CHẠY KIỂM THỬ QUA DÒNG LỆNH (CLI RUNNER)

Hệ thống đã có sẵn script Python Runner tại: [`backend/scripts/run_txt_tests.py`](../../scripts/run_txt_tests.py).

### 2.1. Chạy kiểm thử TẤT CẢ các tệp cùng lúc
Mở terminal tại thư mục `backend/` và chạy:
```bash
# Kích hoạt môi trường ảo và chạy toàn bộ tệp:
.venv/bin/python scripts/run_txt_tests.py --all
```
*(Nếu bạn đang ở ngoài thư mục gốc dự án: `backend/.venv/bin/python backend/scripts/run_txt_tests.py --all`)*

**Bảng kết quả in ra terminal:**
```text
🚀 BẮT ĐẦU CHẠY KIỂM THỬ 20 TỆP INPUT...
📂 Thư mục xuất kết quả: .../backend/tests/vsico_test_txt_files/output

STT  | MÃ TEST  | HÀNH ĐỘNG        | TRẠNG THÁI     | XE  | CONT | TỆP OUTPUT
----------------------------------------------------------------------------------------
1    | TC-01    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-01_output.txt
2    | TC-02    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-02_output.txt
3    | TC-03    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-03_output.txt
4    | TC-04    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-04_output.txt
5    | TC-05    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-05_output.txt
6    | TC-06    | PROCESSED_FIFO   | needs_review   | 1   | 1    | TC-06_output.txt
7    | TC-07    | PROCESSED_FIFO   | needs_review   | 1   | 1    | TC-07_output.txt
8    | TC-08    | PROCESSED_FIFO   | needs_review   | 1   | 1    | TC-08_output.txt
9    | TC-09    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-09_output.txt
10   | TC-10    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-10_output.txt
11   | TC-11    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-11_output.txt
12   | TC-12    | PROCESSED_FIFO   | needs_review   | 1   | 1    | TC-12_output.txt
13   | TC-13    | PROCESSED_FIFO   | processed      | 3   | 3    | TC-13_output.txt
14   | TC-14    | PROCESSED_FIFO   | needs_review   | 1   | 2    | TC-14_output.txt
15   | TC-15    | PROCESSED_FIFO   | needs_review   | 1   | 1    | TC-15_output.txt
16   | TC-16    | PROCESSED_FIFO   | ignored_chat   | 0   | 0    | TC-16_output.txt
17   | TC-17    | PROCESSED_FIFO   | needs_review   | 1   | 1    | TC-17_output.txt
18   | TC-18    | PROCESSED_FIFO   | processed      | 1   | 1    | TC-18_output.txt
19   | TC-19    | PROCESSED_FIFO   | ignored_chat   | 0   | 0    | TC-19_output.txt
20   | TC-20    | PROCESSED_FIFO   | needs_review   | 1   | 1    | TC-20_output.txt
----------------------------------------------------------------------------------------
✅ HOÀN THÀNH: 20 Tệp | Đã xử lý (processed): 10 | Cần duyệt (needs_review): 8 | Tin rác (ignored): 2
```

---

### 2.2. Chạy kiểm thử TỪNG TỆP MỘT

Bạn chỉ cần truyền cờ `--file` kèm theo tên tệp (hoặc đường dẫn đầy đủ):

```bash
# Ví dụ 1: Test tệp TC-01
.venv/bin/python scripts/run_txt_tests.py --file TC-01_input.txt

# Ví dụ 2: Test tệp TC-06 (sai ISO check digit)
.venv/bin/python scripts/run_txt_tests.py --file TC-06_input.txt

# Ví dụ 3: Test tệp TC-13 (nhiều xe một tin)
.venv/bin/python scripts/run_txt_tests.py --file TC-13_input.txt

# Ví dụ 4: Truyền đường dẫn đầy đủ tới bất kỳ tệp nào
.venv/bin/python scripts/run_txt_tests.py --file /duong/dan/tuy/y/my_test_message.txt
```

---

## 3. CÁCH THÊM MỘT TỆP MỚI ĐỂ KIỂM THỬ

Khi bạn có thêm dữ liệu tin nhắn mới từ thực tế (ví dụ: `TC-21_input.txt`):

### Bước 1: Tạo tệp input mới
Tạo tệp tại thư mục: `backend/tests/vsico_test_txt_files/tests/fixtures/messages/TC-21_input.txt`.

Nội dung tệp có thể viết theo 2 cách:

* **Cách 1: Định dạng có nhãn chuẩn:**
  ```text
  TEST_ID: TC-21
  FORMAT: F1

  INPUT:
  1 xe 15C-999.88/ Nguyễn Văn Test đt: 0912345678 / VSIU7399796 chì 73957169
  ```

* **Cách 2: Văn bản thuần (Chỉ cần paste trực tiếp tin nhắn nhà xe):**
  ```text
  TRẢ HÀNG cont VSIU7399796 xe 15C-878.99 tx Bảo 0903976359 giờ đến 08:00
  ```

*(Tùy chọn: Bạn có thể tạo thêm tệp `TC-21_expected.txt` trong cùng thư mục để ghi chú kỳ vọng).*

### Bước 2: Chạy kiểm thử tệp mới vừa thêm
```bash
.venv/bin/python scripts/run_txt_tests.py --file TC-21_input.txt
```
Hoặc chạy `--all` để test toàn bộ bao gồm cả tệp mới:
```bash
.venv/bin/python scripts/run_txt_tests.py --all
```

### Bước 3: Mở tệp kết quả
Hệ thống sẽ tự động sinh tệp **`backend/tests/vsico_test_txt_files/output/TC-21_output.txt`** chứa toàn bộ dữ liệu bóc tách được!

---

## 4. CẤU TRÚC CHI TIẾT TỆP OUTPUT ĐƯỢC SINH RA

Mỗi tệp `_output.txt` trong thư mục `output/` được định dạng rõ ràng gồm 6 phần:

```text
============================================================================
TEST_ID: TC-06
FORMAT_DECLARED: F1
SOURCE_INPUT_FILE: TC-06_input.txt
TESTED_AT: 2026-10-27 14:33:42
============================================================================

--- [1. NỘI DUNG ĐẦU VÀO (INPUT TEXT)] ---
1 xe 15C17066/ Phạm Văn Huynh đt: 0986****** / VSIU2323001 chì 23333878

--- [2. KẾT QUẢ XỬ LÝ (PROCESSING RESULT)] ---
HÀNH ĐỘNG (ACTION)       : PROCESSED_FIFO
TRẠNG THÁI (STATUS)      : needs_review
SỐ XE BÓC TÁCH ĐƯỢC      : 1
SỐ CONTAINER BÓC TÁCH    : 1
PHẢN HỒI NHÀ XE          : [VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại thông tin sau:
- Xe 15C-170.66: số container 'VSIU2323001' sai số kiểm tra cuối theo ISO 6346 (gợi ý đúng: VSIU2323000).

--- [3. CHI TIẾT CÁC XE ĐẦU KÉO (TRUCKS)] ---
  Xe #1:
    - Biển số xe   : 15C-170.66
    - Biển rơ-moóc : (trống)
    - Tên tài xế   : Phạm Văn Huynh
    - SĐT tài xế   : 0986******

--- [4. CHI TIẾT CÁC CONTAINER (CONTAINERS)] ---
  Container #1 (Dòng 1):
    - Số Container    : VSIU2323001
    - Kích cỡ cont    : (trống)
    - Số seal / chì   : 23333878
    - Loại lệnh       : (chưa rõ)
    - Gợi ý kho       : (trống)
    - Gợi ý khách     : (trống)
    - Chuẩn ISO 6346  : SAI SỐ KIỂM TRA (FALSE)
    - Trạng thái kiểm : invalid
    - Cảnh báo        : ISO6346_CHECK_DIGIT_MISMATCH(expected=0,actual=1)

--- [5. KỲ VỌNG BAN ĐẦU (EXPECTED FROM FIXTURE)] ---
Phát hiện số kiểm tra ISO 6346 không hợp lệ (nếu bộ validator xác nhận)...

--- [6. DỮ LIỆU JSON CHI TIẾT TRẢ VỀ (RAW JSON RESPONSE)] ---
{
  "ok": true,
  "status": "ENQUEUED_AND_PROCESSED_FIFO",
  "data": { ... }
}
```

---

## 5. CÁCH KIỂM THỬ TRỰC TIẾP QUA POSTMAN

Nếu bạn muốn gửi kiểm thử từng tệp qua giao diện đồ họa **Postman**:

1. **Khởi động server backend**:
   ```bash
   cd backend && .venv/bin/python run.py
   ```
2. **Gửi Request trong Postman**:
   - **Method**: `POST`
   - **URL**: `http://localhost:8000/webhook`
   - **Header**: `Content-Type: application/json`
   - **Body (`raw` -> `JSON`)**:
     Copy nội dung từ tệp input (ví dụ `TC-01_input.txt`):
     ```json
     {
       "app_id": "postman_tester",
       "event_name": "user_send_text",
       "group_id": "2001000000000000001",
       "sender": { "id": "1001", "name": "Điều hành Hải Long" },
       "timestamp": "1791798010000",
       "message": {
         "msg_id": "test_msg_tc01",
         "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 0986****** / VSIU2621051 chì 23333878"
       }
     }
     ```
3. Bấm **Send**: Nhận ngay toàn bộ JSON bóc tách biển số xe, cont, seal, ISO 6346 trong cửa sổ Response!
