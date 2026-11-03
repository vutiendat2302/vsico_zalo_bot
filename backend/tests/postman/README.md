# 📮 TỔNG HỢP BỘ KIỂM THỬ POSTMAN - VSICO ZALO BOT & BACKEND TMS
### HỆ THỐNG XỬ LÝ & ĐIỀU PHỐI TIN NHẮN NHÀ XE (TASK 2 - PM TMS VSICO)

Thư mục này chứa toàn bộ tài liệu đặc tả kiểm thử trên phần mềm **Postman** bằng định dạng Markdown (`.md`) và tệp **Postman Collection (`.json`)** có thể import trực tiếp.

---

## 1. Danh Mục Các Tài Liệu Kiểm Thử

| Tệp tài liệu | Nội dung kiểm thử | Cổng dịch vụ |
| :--- | :--- | :---: |
| 📘 [**`HUONG_DAN_KIEM_THU_POSTMAN_DAY_DU.md`**](./HUONG_DAN_KIEM_THU_POSTMAN_DAY_DU.md) | **Tài liệu tổng hợp toàn diện**: Hướng dẫn cấu hình môi trường, cURL, body và kết quả kỳ vọng cho tất cả các phần. | **Port 3000 & 8000** |
| 📑 [**`01_step1_webhook_va_luu_mysql.md`**](./01_step1_webhook_va_luu_mysql.md) | **Bước 1**: Tiếp nhận Webhook `POST /webhook`, kiểm tra chữ ký, chống trùng lặp và lưu MySQL. | **Port 8000** |
| 📑 [**`02_kiem_thu_bot_zca_chi_tiet.md`**](./02_kiem_thu_bot_zca_chi_tiet.md) | **Các API Bot ZCA**: Lấy tất cả `groupId`, `userId`, lịch sử tin nhắn nhóm/user, gửi tin cá nhân/nhóm và lấy tin realtime. | **Port 3000** |
| 📑 [**`03_kiem_thu_webhook_gateway_full.md`**](./03_kiem_thu_webhook_gateway_full.md) | **Cổng Webhook Gateway**: Happy Path 1 xe, nhiều xe gạch chéo `/`, thiếu seal bổ sung, ĐHVT quote duyệt `ok`/`sửa`/`huỷ`. | **Port 8000** |
| 📑 [**`04_kiem_thu_truy_van_tin_nhan_va_xu_ly.md`**](./04_kiem_thu_truy_van_tin_nhan_va_xu_ly.md) | **Truy vấn tin nhắn & Bóc tách**: Lấy tin nhắn theo group, user, user in group, messageId và lọc tin đã xử lý. | **Port 8000** |
| 📑 [**`05_ke_hoach_test_bai1_bai2_va_tc01_tc20.md`**](./05_ke_hoach_test_bai1_bai2_va_tc01_tc20.md) | **Kế hoạch kiểm thử Bài 1, Bài 2 & TC-01..TC-20**: Đặc tả kiểm thử 3 định dạng F1, F2, F3 theo Jira ZALO ngày 27/10. | **Port 3000 & 8000** |
| 📑 [**`06_kiem_thu_batch_txt_fixtures.md`**](./06_kiem_thu_batch_txt_fixtures.md) | **Runner tự động bộ tệp TXT**: Chạy test toàn bộ 20 tệp input txt hoặc từng tệp lẻ và sinh file output. | **CLI / Python** |
| 📑 [**`07_kiem_thu_module_doc_hieu_f1_f2_f3_tc01_tc16.md`**](./07_kiem_thu_module_doc_hieu_f1_f2_f3_tc01_tc16.md) | **Module Đọc hiểu F1/F2/F3**: Kiểm thử bộ nhận diện quy chuẩn và trích xuất dữ liệu xe/cont. | **Port 8000** |
| 📑 [**`08_kiem_thu_ke_hoach_van_chuyen_crud_va_import.md`**](./08_kiem_thu_ke_hoach_van_chuyen_crud_va_import.md) | **Kế hoạch vận chuyển**: CRUD, Import Excel `ketnoi.xlsx`, Import CSV và tự động matching. | **Port 8000** |
| 📑 [**`09_kiem_thu_quan_ly_va_don_dep_db.md`**](./09_kiem_thu_quan_ly_va_don_dep_db.md) | **Quản lý & Dọn dẹp DB**: Health check kết nối MySQL, xóa kế hoạch theo ngày, dọn dẹp DB qua CLI/API. | **Port 8000 & CLI** |
| 📑 [**`10_kiem_thu_ket_qua_tin_nhan_outbound_messages.md`**](./10_kiem_thu_ket_qua_tin_nhan_outbound_messages.md) | **Kết quả tin nhắn (Outbound Messages)**: Quản lý 4 trạng thái (Đã gửi, Chờ duyệt, Hủy, Thất bại), duyệt gửi lại. | **Port 8000** |
| 📑 [**`11_kiem_thu_tung_tin_nhan_webhook_va_gui_zalo.md`**](./11_kiem_thu_tung_tin_nhan_webhook_va_gui_zalo.md) | **Kiểm thử từng tin nhắn Webhook**: Bóc tách thời gian thực, đối chiếu cont và gửi tin Zalo với SĐT thật. | **Port 8000** |
| 📑 [**`12_kiem_thu_che_do_nhom_duyet_dhvt_va_form_gui_zalo.md`**](./12_kiem_thu_che_do_nhom_duyet_dhvt_va_form_gui_zalo.md) | **Chế độ nhóm & Duyệt ĐHVT**: Nhóm Tự động vs Chờ duyệt, quy trình duyệt ĐHVT và hiển thị Form gửi Zalo. | **Port 8000** |
| 📑 [**`13_kiem_thu_tach_text_tu_anh_paddleocr.md`**](./13_kiem_thu_tach_text_tu_anh_paddleocr.md) | **Bóc tách văn bản từ ảnh (PaddleOCR)**: Tách text từ ảnh, bỏ qua ảnh không có chữ, xử lý ảnh có chữ như tin text. | **Port 8000 & 8866** |
| 📑 [**`14_kiem_thu_tin_nhan_da_xe_emoji_va_khop_lenh_dong.md`**](./14_kiem_thu_tin_nhan_da_xe_emoji_va_khop_lenh_dong.md) | **Tin nhắn đa xe & Emoji**: Bóc tách nhiều xe, icon xe tải, ghép lệnh đóng/trả động theo kế hoạch vận chuyển. | **Port 8000** |
| 📑 [**`15_kiem_thu_random_nhom_zalo_ke_hoach_van_chuyen.md`**](./15_kiem_thu_random_nhom_zalo_ke_hoach_van_chuyen.md) | **Random nhóm Zalo**: Khảo sát phân bổ nhóm khách hàng ngẫu nhiên theo kế hoạch vận chuyển. | **Port 8000** |
| 📑 [**`16_kiem_thu_thong_bao_loi_nha_xe_va_bot_reply.md`**](./16_kiem_thu_thong_bao_loi_nha_xe_va_bot_reply.md) | **Thông báo lỗi nhà xe (Bot Reply)**: Tự động nhắc nhở khi thiếu chì, thiếu size, sai số cont, sai biển số xe. | **Port 8000** |
| 📑 [**`17_kiem_thu_tu_choi_ca_va_tin_nhan_cho_duyet.md`**](./17_kiem_thu_tu_choi_ca_va_tin_nhan_cho_duyet.md) | **Từ chối ca rà soát & Tin nhắn chờ duyệt**: Hủy thông báo gửi khách, cập nhật trạng thái Bị Hủy (cancelled/huy). | **Port 8000** |
| 📦 [**`vsico_zalo_bot_dhvt_approval_and_send_modes.postman_collection.json`**](./vsico_zalo_bot_dhvt_approval_and_send_modes.postman_collection.json) | **Postman Collection Chế độ nhóm & ĐHVT Duyệt**: Import trực tiếp vào Postman để chạy 8 kịch bản tự động. | **Port 8000** |
| 📦 [**`vsico_zalo_bot_postman_collection.json`**](./vsico_zalo_bot_postman_collection.json) | **Tệp Postman Collection v2.1**: Import trực tiếp vào Postman để chạy tự động 18 test cases. | **Tất cả** |
| 📦 [**`vsico_zalo_bot_full_20_test_cases.json`**](./vsico_zalo_bot_full_20_test_cases.json) | **Collection đầy đủ Bài 1, 2 và TC-01..TC-20**: Import trực tiếp chạy 20 kịch bản dữ liệu thực tế. | **Tất cả** |

---

## 2. Cách Chạy Kiểm Thử Nhanh

### Bước 1: Khởi động 2 máy chủ
1. **Khởi động Bot ZCA API Server (Port 3000)**:
   ```bash
   cd zca-js && node bot_api_server.js
   ```
2. **Khởi động Backend Webhook Server (Port 8000)**:
   ```bash
   cd backend && .venv/bin/python run.py
   ```

### Bước 2: Import vào Postman
1. Mở Postman -> Chọn **Import** -> Chọn file [`vsico_zalo_bot_postman_collection.json`](./vsico_zalo_bot_postman_collection.json).
2. Tạo Environment với `bot_url = http://localhost:3000` và `backend_url = http://localhost:8000`.
3. Bấm **Run Collection** để chạy toàn bộ các bài test tự động.
