# 📮 BÀI TEST 1 & 2: HƯỚNG DẪN KIỂM THỬ TỪNG FILE HOẶC TẤT CẢ TỆP FIXTURES (TC-01 ĐẾN TC-20)

### DỰ ÁN BOT ZALO TMS VSICO (AUTOMATED TEXT FIXTURE RUNNER)

Tài liệu này được đồng bộ từ [`backend/tests/vsico_test_txt_files/HUONG_DAN_KIEM_THU_TXT_FILES.md`](../vsico_test_txt_files/HUONG_DAN_KIEM_THU_TXT_FILES.md) để hỗ trợ kiểm thử tiện lợi trong bộ tài liệu Postman.

---

## 1. Tóm Tắt Nhanh Các Lệnh Kiểm Thử

### Lệnh 1: Kiểm thử TẤT CẢ các tệp cùng lúc (Xuất đủ 20 tệp `.txt` vào `output/`)

```bash
cd backend
.venv/bin/python scripts/run_txt_tests.py --all
```

### Lệnh 2: Kiểm thử 1 tệp duy nhất bất kỳ

```bash
cd backend
.venv/bin/python scripts/run_txt_tests.py --file TC-01_input.txt
.venv/bin/python scripts/run_txt_tests.py --file TC-06_input.txt
```

### Lệnh 3: Khi bạn thêm một tệp mới (Ví dụ: `TC-21_input.txt`)

Chỉ cần thả tệp vào `backend/tests/vsico_test_txt_files/tests/fixtures/messages/TC-21_input.txt`, sau đó gõ:

```bash
.venv/bin/python scripts/run_txt_tests.py --file TC-21_input.txt
```

➔ Hệ thống tự động bóc tách và xuất ra tệp: `backend/tests/vsico_test_txt_files/output/TC-21_output.txt`.

---

## 2. Vị Trí Thư Mục Output Chứa Kết Quả Bóc Tách

Toàn bộ kết quả chi tiết từng ca kiểm thử được lưu tại:
📁 [`backend/tests/vsico_test_txt_files/output/`](../vsico_test_txt_files/output/)

Mỗi tệp `_output.txt` bao gồm:

1. Nội dung tin nhắn đầu vào (`INPUT TEXT`)
2. Trạng thái xử lý (`processed` / `needs_review` / `ignored_chat`)
3. Chi tiết xe đầu kéo (biển số xe, tên tài xế, SĐT)
4. Chi tiết container (số cont, số seal, kết quả thẩm định ISO 6346 Mod 11, cảnh báo)
5. Đối soát với kỳ vọng ban đầu (`EXPECTED`)
6. Toàn văn phản hồi JSON gốc của hệ thống.
