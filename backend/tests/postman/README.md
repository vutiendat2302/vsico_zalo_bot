# 📮 HƯỚNG DẪN KIỂM THỬ POSTMAN - NHAXE BOT & TMS REST APIS
### HỆ THỐNG XỬ LÝ & ĐIỀU PHỐI TIN NHẮN NHÀ XE (TASK 2 - PM TMS VSICO)

Thư mục này chứa tài liệu đặc tả chi tiết từng kịch bản kiểm thử (Test Case) trên công cụ **Postman** bằng định dạng Markdown (`.md`), phân tách tường minh giữa **REST API nghiệp vụ của hệ thống TMS**, **Cổng sự kiện Zalo Webhook Gateway** và **REST API Quản trị Kế hoạch Shipping Động**.

---

## 1. Thiết lập môi trường kiểm thử (Postman Environment)

Trước khi thực hiện các bài test, hãy khởi động máy chủ `nhaxe-bot`:
```bash
# Di chuyển vào thư mục dự án
cd /home/datbritget/Documents/ba_intern_vsico/source/task2

# Khởi chạy server tại cổng 8000
make run
# Hoặc: python3 -m nhaxe_bot.main --serve --port 8000
```

Trong phần mềm Postman:
- Tạo một Environment mới đặt tên: `VSICO_Local`
- Khai báo biến (Variable):
  - **`base_url`**: `http://localhost:8000`
- Header chung cho tất cả các request POST:
  - **`Content-Type`**: `application/json; charset=utf-8`

---

## 2. Danh mục các bài kiểm thử chi tiết

Các kịch bản kiểm thử được phân thành 3 nhóm rõ ràng:

### Phần I: REST API Chức Năng Nghiệp Vụ TMS
Các API độc lập dành cho phần mềm TMS quản trị và điều phối chuyến xe trực tiếp:
1. [**Test 01: Kiểm tra sức khỏe máy chủ (`GET /api/health`)**](./01_kiem_tra_suc_khoe_server.md)
   - Xác nhận trạng thái máy chủ, số lượng tin nhắn đã xử lý và metrics.
2. [**Test 02: Tạo chuyến xe mới qua TMS (`POST /api/trips/new`)**](./02_tao_chuyen_xe_tms.md)
   - Tạo chuyến xe với dữ liệu có cấu trúc, tự động thẩm định ISO 6346 Mod 11 và khớp Shipping.
3. [**Test 03: Đổi tài xế theo biển số xe (`POST /api/trips/update-driver`)**](./03_doi_tai_xe_theo_bien_so.md)
   - Đổi tài xế mà không cần nhập số cont; hệ thống tự tra cứu ngược qua biển số xe và tăng phiên bản (Version 2).
4. [**Test 04: Bổ sung số seal và giờ đến (`POST /api/trips/supplement`)**](./04_bo_sung_seal_gio_den.md)
   - Bổ sung thông tin cho chuyến xe đang ở trạng thái chờ.
5. [**Test 05: Yêu cầu hủy chuyến xe (`POST /api/trips/cancel`)**](./05_huy_chuyen_xe.md)
   - Ghi nhận lý do hủy xe và kích hoạt chuông cảnh báo Admin (`admin_alert: true`).
6. [**Test 06: Tra cứu danh sách & chi tiết chuyến (`GET /api/trips`)**](./06_tra_cuu_danh_sach_va_chi_tiet_chuyen.md)
   - Truy vấn danh sách toàn bộ chuyến xe và xem chi tiết theo từng container cụ thể.

---

### Phần II: Quản Trị Kế Hoạch Vận Chuyển & Giả Lập Chủ Động (Dynamic Shipping APIs)
Các API giúp người kiểm thử chủ động 100%, không bị bó hẹp vào tệp CSV tĩnh:
7. [**Test 13: Bật / Tắt Tự động tạo Shipping giả lập (`POST /api/shipping/mock-mode`)**](./13_bat_tat_auto_mock_shipping.md)
   - Bật cờ `auto_mock_enabled` để bất kỳ số container mới nào gửi đến đều tự động có đơn kế hoạch và đạt trạng thái `SENT_DRY_RUN`.
8. [**Test 14: Tạo đơn kế hoạch vận chuyển động (`POST /api/shipping/new`)**](./14_tao_don_shipping_dong.md)
   - Nạp trực tiếp một đơn kế hoạch mới với kho trả, khách hàng và nhà xe theo ý muốn.
9. [**Test 15: Tra cứu danh mục kế hoạch vận chuyển (`GET /api/shipping`)**](./15_tra_cuu_danh_muc_shipping.md)
   - Kiểm tra trạng thái tính năng auto-mock và xem toàn bộ danh sách các đơn vận chuyển hiện có trong bộ nhớ.

---

### Phần III: Cổng Sự Kiện Zalo Webhook Gateway (`POST /webhook`)
Cổng tiếp nhận webhook sự kiện thô gửi từ Zalo OA, tự động phân loại Intent và xử lý:
10. [**Test 07: Báo xe chuẩn 1 xe (Happy Path)**](./07_webhook_bao_xe_chuan.md)
    - Tiếp nhận tin nhắn báo xe hợp lệ, bóc tách thông tin, khớp đơn hàng và soạn tin gửi khách.
11. [**Test 08: Báo 2 xe trong 1 tin nhắn (Ký tự gạch chéo `/`)**](./08_webhook_bao_nhieu_xe_mot_tin.md)
    - Tự động phân đoạn tin nhắn phức tạp thành 2 chuyến xe độc lập.
12. [**Test 09: Chống trùng lặp tin nhắn (Idempotency)**](./09_webhook_chong_trung_lap.md)
    - Gửi lại tin nhắn cùng `msg_id` để kiểm tra cơ chế chống spam tin khách hàng.
13. [**Test 10: Xử lý xe thiếu seal (`HOLD_WAIT_SUPPLEMENT`)**](./10_webhook_thieu_seal_phan_hoi_nha_xe.md)
    - Nhận diện xe thiếu trường bắt buộc, lưu trạng thái chờ và tạo tin nhắn phản hồi yêu cầu nhà xe bổ sung.
14. [**Test 11: Báo động sai nhà xe nhận cuốc (`HOLD_ADMIN`)**](./11_webhook_sai_nha_xe_canh_bao_admin.md)
    - Container thuộc nhà xe NX01 nhưng tin do NX03 gửi -> Kích hoạt cảnh báo ĐHVT xử lý.
15. [**Test 12: Lọc tin nhắn rác & cảnh báo người lạ**](./12_webhook_loc_tin_nhan_rac_va_nguoi_la.md)
    - Bỏ qua các tin nhắn chào hỏi thông thường (`IGNORE_CHAT`) và cảnh báo khi có tài khoản lạ gửi tin trong nhóm nhà xe (`IGNORE_UNKNOWN_SENDER`).

---

## 3. Thứ tự khuyến nghị khi chạy kiểm thử
Để dữ liệu giữa các bài test có tính liên kết liền mạch:
1. Chạy **Test 01** để xác nhận server hoạt động.
2. (Chủ động) Chạy **Test 13** để BẬT chế độ Auto-Mock Shipping (`{"enabled": true}`). Lúc này bạn có thể test bất kỳ số container nào mà không bao giờ bị báo lỗi thiếu kế hoạch shipping!
3. Chạy **Test 02** để tạo chuyến xe cont `VSIU7399796` (Version 1).
4. Chạy **Test 03** để đổi tài xế cho xe vừa tạo (hệ thống tìm thấy và nâng lên Version 2).
5. Chạy **Test 06** để xác nhận container `VSIU7399796` đã được cập nhật Version 2 trong danh sách chuyến.
6. Chạy các bài test Webhook từ **Test 07** đến **Test 12** để kiểm tra bộ lọc bóc tách thông tin tự động.
