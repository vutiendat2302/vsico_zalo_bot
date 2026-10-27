# TÀI LIỆU QUY CHUẨN INTENTS & PHÂN LOẠI TIN NHẮN (DOCS/INTENTS.MD)

Tài liệu này định nghĩa thứ tự ưu tiên phân loại (Intent Classification Hierarchy), quy tắc giải quyết xung đột (conflict resolution), và ví dụ tin nhắn thực tế.

---

## 1. Thứ Tự Phân Loại Cố Định (Strict Classification Order)

Để đảm bảo tính tất định (deterministic) và không có xung đột, hệ thống thẩm định theo thứ tự 4 cấp sau:

```
[1. CANCEL_REQUEST] 
       │ (Kiểm tra đầu tiên: An toàn & Cứu chuyến)
       ▼
[2. UPDATE_REQUEST / ASK_WHICH_CONT] 
       │ (Kiểm tra thứ hai: Sửa xe, đổi tài xế)
       ▼
[3. SUPPLEMENT] 
       │ (Kiểm tra thứ ba: Bổ sung số chì/seal cho chuyến chờ)
       ▼
[4. PARSE] 
       │ (Kiểm tra thứ tư: Tin báo xe mới - 1 xe hoặc nhiều xe)
       ▼
[5. MANUAL_REVIEW / IGNORE_CHAT] 
         (Mặc định: Cập nhật tiến độ hoặc trao đổi thông thường)
```

---

## 2. Bảng Định Nghĩa Chi Tiết Từng Intent

| Intent | Độ ưu tiên | Từ khóa nhận diện | Hành động hệ thống | Trách nhiệm xử lý |
| :--- | :---: | :--- | :--- | :--- |
| **`CANCEL_REQUEST`** | **1 (Cao nhất)** | `hủy cont`, `hủy chuyến`, `xin hủy`, `xe hỏng` | Bật cờ `admin_alert: true`, chuyển ngay cho ĐHVT xử lý điều xe khác | `CancelTripHandler` |
| **`UPDATE_REQUEST`** | **2** | `đổi tài xế`, `sửa tài xế`, `thay lái xe`, `đổi xe`, `sửa seal` | Tra cứu ngược theo biển số (`find_sent_trips_by_plate`) hoặc số cont, nâng lên Version 2, soạn thông báo gửi khách | `UpdateDriverHandler` |
| **`ASK_WHICH_CONT`** | **2 (Phụ)** | Có từ khóa sửa/đổi nhưng **không có cả số cont lẫn biển số xe** | Nhắn lại nhóm nhà xe yêu cầu nêu rõ cont/biển số, đồng thời cảnh báo Admin | `UnknownHandler` / Router |
| **`SUPPLEMENT`** | **3** | `bổ sung seal`, `seal cont`, `chì cont` | Gộp số seal và giờ đến vào chuyến đang ở trạng thái `HOLD_WAIT_SUPPLEMENT` | `SupplementHandler` |
| **`PARSE`** | **4** | Chứa mẫu số cont chuẩn (4 chữ + 7 số), biển số xe, tên tài xế, SĐT | Bóc tách từng xe, thẩm định ISO 6346 Mod 11, khớp Shipping, render template gửi khách | `CreateTripHandler` |
| **`MANUAL_REVIEW`** | **5** | `đã giao`, `đã trả xong`, `giao xong`, `đã hạ` | Ghi nhận tiến độ vận chuyển, chuyển Admin theo dõi | `UnknownHandler` |
| **`IGNORE_CHAT`** | **6** | `dạ em nhận`, `ok`, `tới chưa anh ơi`, chào hỏi | Ghi log, im lặng bỏ qua, **không spam lỗi vào nhóm** | `UnknownHandler` |

---

## 3. Các Cặp Tình Huống Xung Đột & Nguyên Tắc Phân Xử

### Ca 1: Vừa có từ "hủy" vừa có số cont
* **Ví dụ**: *"anh ơi xe hỏng em xin hủy chuyến cont AHLXU1029021 nhé ạ"*
* **Phân xử**: Nhận diện `CANCEL_REQUEST` (Mức 1), **KHÔNG** nhảy vào bóc tách chuyến mới `PARSE` mặc dù có số cont hợp lệ.

### Ca 2: Đổi tài xế nhưng chỉ nhắn biển số xe
* **Ví dụ**: *"Đổi tài xế xe 15C-878.99 sang Lê Văn Đổi 0988592302 nhé anh"*
* **Phân xử**: Nhận diện `UPDATE_REQUEST` (Mức 2). Handler dùng biển số `15C87899` tra cứu ngược vào danh sách chuyến xe đang chạy (`sent_trips`) của nhà xe để tìm ra cont `VSIU7399796`.

### Ca 3: Đổi thông tin nhưng không có cả cont lẫn biển số
* **Ví dụ**: *"bên em đổi tài xế nhé anh, tài xế mới Nguyễn Văn Lực 0944443210"*
* **Phân xử**: Không đủ dữ kiện để cập nhật tự động $\rightarrow$ Kích hoạt `ASK_WHICH_CONT`, bot tự động phản hồi lại nhóm: *"Bạn cần đổi thông tin cho số cont hoặc biển số xe nào?"*.
