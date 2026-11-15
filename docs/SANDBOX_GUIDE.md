# Hướng Dẫn Sử Dụng Trang Thử Nghiệm (`/sandbox`)

## 1. Mục đích
Trang **Thử nghiệm thuật toán & bối cảnh** (`/sandbox`) là môi trường chạy thử (Dry-run) toàn bộ luồng xử lý tin nhắn Zalo của hệ thống VSICO Bot:
- Kiểm tra phân loại ý định (Intent), phân đoạn đa xe/đa container, bóc tách thực thể (biển số, tài xế, SĐT, số container, số seal, giờ hẹn).
- Kiểm tra thuật toán kiểm tra chuẩn ISO 6346 (Modulo 11) và đối chiếu kế hoạch TMS.
- Kiểm tra cơ chế xử lý ngữ cảnh hội thoại nhiều lượt (quote tin nhắn, bổ sung thông tin thiếu, đổi xe, hủy chuyến).
- Kiểm tra OCR từ ảnh chụp màn hình hoặc phiếu giao nhận.
- **An toàn dữ liệu**: Mọi thao tác tại trang này đều chạy ở chế độ `persisted = false`, tuyệt đối không ghi dữ liệu vào cơ sở dữ liệu MySQL và không gửi tin nhắn thật ra Zalo.

---

## 2. Cấu trúc giao diện

Giao diện được chia làm 2 cột chính:
- **Cột trái (INPUT)**: Nơi chọn kịch bản mẫu, nạp dữ liệu kế hoạch TMS, nhập nội dung tin nhắn, tải ảnh OCR, cấu hình bối cảnh và tùy chọn chạy.
- **Cột phải (OUTPUT)**: Hiển thị kết quả phân tích chi tiết sau khi chạy kiểm thử (luôn gắn nhãn `persisted = false`).

Thanh tiêu đề phía trên có tùy chọn **Giữ bối cảnh lượt sau** (mặc định bật): tự động lưu tin nhắn và ca vừa xử lý vào bộ nhớ bối cảnh cho lượt test kế tiếp (trừ các tin xã giao/bỏ qua).

---

## 3. Hướng dẫn từng bước sử dụng

### Bước 1: Chọn dữ liệu đầu vào (Input)
Bạn có thể chọn một trong các cách sau:
1. **Dùng kịch bản mẫu nhanh**: Nhấn vào các nút có sẵn như `Đủ 8 trường`, `Thiếu chì`, `Quote bù chì`, `Đổi xe thiếu Cont`, `Đổi xe có Cont`, `Hủy chuyến`, `Đa xe / đa Cont`, `Sai ISO 6346`, `Xã giao`, `Tự do + SĐT`. Hệ thống sẽ tự điền sẵn nội dung tin nhắn mẫu tương ứng.
2. **Nạp số Container từ kế hoạch TMS**: Nhấn vào các mã container hiển thị ở hàng `TMS (...)` (ví dụ: `SELU4411572`, `VSIU2463001`...) để test khả năng đối chiếu đúng với kế hoạch thật đang có trong hệ thống.
3. **Nhập thủ công**: Gõ trực tiếp nội dung tin nhắn điều xe vào ô **Tin nhắn**.
4. **Thử nghiệm OCR ảnh**: Nhấn nút **Ảnh OCR** để tải lên ảnh chứa thông tin xe/container.

### Bước 2: Thiết lập Bối cảnh hội thoại (Tùy chọn)
Dùng khi muốn kiểm thử các tình huống nhà xe nhắn nhiều tin liên tiếp hoặc trả lời (quote) tin cũ:
- **Quote (tùy chọn)**: Nhập nội dung tin nhắn gốc mà tin nhắn hiện tại đang trả lời/trích dẫn.
- **Thêm tin trước đó**: Nhập tin nhắn trước đó vào ô `Thêm tin trước đó...` rồi nhấn **+ Thêm** để đưa vào lịch sử bối cảnh của phiên.
- **Nhà xe giả lập / Giờ gửi ISO**: Điền nếu muốn giả lập cụ thể một nhà xe hoặc mốc thời gian gửi tin theo chuẩn ISO.

### Bước 3: Cấu hình AI Fallback
- **Gọi AI Fallback**: Mặc định là `OFF (0 token)` — hệ thống chỉ chạy bộ bóc tách quy tắc (Regex/Parser F1-F3) để tiết kiệm chi phí và đạt tốc độ nhanh nhất.
- Chỉ tích chọn bật khi bạn muốn kiểm thử các tin nhắn viết tự do phức tạp cần đến LLM (Gemini) xử lý.

### Bước 4: Chạy kiểm thử và đọc kết quả
- Nhấn nút **Chạy kiểm thử** (hoặc dùng phím tắt **Ctrl + Enter**).
- Quan sát kết quả tại cột **OUTPUT**:
  - Trạng thái xử lý (`PROCESSED`, `NEEDS_REVIEW`, `IGNORED_CHAT`, v.v.).
  - Ý định được phân loại (`resolved_intent`) và kết quả phân giải bối cảnh (`context_resolution`).
  - Danh sách xe và container đã bóc tách kèm các cảnh báo lỗi (ví dụ: sai check digit ISO 6346, thiếu số chì, không khớp kế hoạch).
- Để bắt đầu một kịch bản mới hoàn toàn, nhấn **Xóa phiên** ở góc dưới bên trái để làm sạch toàn bộ input, bối cảnh và lịch sử lượt chạy.

---

## 4. Kịch bản kiểm thử mẫu gợi ý (Test Cases)

### Kịch bản 1: Bóc tách chuẩn đủ thông tin
1. Nhấn nút **Đủ 8 trường** ở danh sách kịch bản mẫu.
2. Để `Gọi AI Fallback` ở trạng thái `OFF`.
3. Nhấn **Chạy kiểm thử**.
4. **Kết quả mong đợi**: Trạng thái `PROCESSED`, bóc tách đầy đủ biển số, tài xế, SĐT, số container, số seal, giờ hẹn; không phát sinh cảnh báo thiếu trường.

### Kịch bản 2: Bổ sung thông tin qua nhiều lượt (Quote bù chì)
1. Bật **Giữ bối cảnh lượt sau**.
2. Nhấn **Thiếu chì** -> nhấn **Chạy kiểm thử**.
3. **Kết quả lượt 1**: Hệ thống nhận diện thiếu số seal (`missing_seal` / `NEEDS_REVIEW`), tự động lưu ca vào `Bối cảnh (1 tin | 1 ca)`.
4. Nhấn **Quote bù chì** (hoặc nhập tin bổ sung seal mới và điền tin lượt 1 vào ô `Quote`) -> nhấn **Chạy kiểm thử**.
5. **Kết quả lượt 2**: Hệ thống ghép được số seal mới vào đúng container của lượt 1.

### Kịch bản 3: Kiểm tra bắt lỗi số Container sai chuẩn ISO 6346
1. Nhấn **Sai ISO 6346** -> nhấn **Chạy kiểm thử**.
2. **Kết quả mong đợi**: Hệ thống đánh dấu container không hợp lệ chữ số kiểm tra (`check_digit_valid = false`) và chuyển trạng thái sang cần kiểm tra/duyệt (`NEEDS_REVIEW`).

### Kịch bản 4: Lọc tin nhắn xã giao
1. Nhấn **Xã giao** -> nhấn **Chạy kiểm thử**.
2. **Kết quả mong đợi**: Trạng thái `IGNORED_CHAT`, không tạo ca xe/container và không lưu vào bối cảnh lượt sau.
