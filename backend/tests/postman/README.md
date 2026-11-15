# TỔNG HỢP BỘ KIỂM THỬ POSTMAN - VSICO ZALO BOT & BACKEND TMS
### HỆ THỐNG XỬ LÝ & ĐIỀU PHỐI THÔNG BÁO VẬN TẢI CONTAINER ĐA KÊNH

Thư mục này chứa toàn bộ tài liệu đặc tả kiểm thử API qua Postman định dạng Markdown (`.md`) phục vụ kiểm thử đơn vị, tích hợp và kiểm tra luồng nghiệp vụ hệ thống.

---

## 1. Cấu Trúc Danh Mục Tài Liệu Kiểm Thử

| STT | Tệp tài liệu | Phân hệ / Nội dung kiểm thử | Cổng dịch vụ |
| :---: | :--- | :--- | :---: |
| 01 | [`01_check_bot_zca.md`](./01_check_bot_zca.md) | **Cầu nối Zalo (ZCA Bridge)**: Kiểm tra trạng thái Bot, kết nối WebSocket, lấy danh sách nhóm, thành viên, lịch sử chat và tin nhắn realtime. | Port 3000 |
| 02 | [`02_check_be_connect.md`](./02_check_be_connect.md) | **Cổng Webhook Gateway (Backend)**: Kiểm tra kết nối Backend và quy trình tiếp nhận tin nhắn báo xe cơ bản qua `POST /webhook`. | Port 8000 |
| 03 | [`03_check_db.md`](./03_check_db.md) | **Cơ sở dữ liệu MySQL 8.4**: Kiểm tra sức khỏe kết nối DB (`GET /api/health`), dọn dẹp kế hoạch theo ngày và quản trị DB. | Port 8000 |
| 04 | [`04_kiem_thu_truy_van_tin_nhan_va_xu_ly.md`](./04_kiem_thu_truy_van_tin_nhan_va_xu_ly.md) | **Truy vấn Tin nhắn & Xử lý (FIFO Extractor)**: Truy vấn tin nhắn theo nhóm, người gửi, lọc tin đã xử lý và test tự động bóc tách xe, tài xế, cont, seal, ISO 6346. | Port 8000 |
| 05 | [`05_kiem_thu_thongbao_loi.md`](./05_kiem_thu_thongbao_loi.md) | **Cảnh báo Lỗi & Phản hồi Nhà xe (`BotReply`)**: Tự động phát hiện tin nhắn thiếu/sai trường nghiệp vụ và sinh cảnh báo nhắc nhà xe bổ sung. | Port 8000 |
| 06 | [`06_user.md`](./06_user.md) | **Xác thực (Auth) & Quản lý Tài khoản (Users)**: Đăng nhập cấp JWT cookie/token, phân quyền RBAC (`admin`, `dhvt`), CRUD tài khoản người dùng theo Snowflake ID. | Port 8000 |
| 07 | [`07_luong_bot_nha_xe_ocr_llm.md`](./07_luong_bot_nha_xe_ocr_llm.md) | **Luồng Bot <-> Nhà xe, OCR & LLM Extraction**: Toàn trình báo xe, thiếu trường nhắc quote, đổi/hủy xe, lỗi gửi Zalo 3 lần, OCR ảnh (`files`) và AI Microservice (`/extract`, `/ocr`, `/match-warehouse`). | Port 8000 & 8001 |
| 08 | [`08_cap_nhat_xe_ke_hoach.md`](./08_cap_nhat_xe_ke_hoach.md) | **Cập nhật Xe trên Kế hoạch (Optimistic Lock)**: Kiểm thử `PATCH /api/plans/{plan_id}/vehicle`, kiểm soát `expected_version` (`409 Conflict`) và trạng thái `tms_sync_status`. | Port 8000 |
| 09 | [`09_luong_bot_khach_hang_va_dhvt.md`](./09_luong_bot_khach_hang_va_dhvt.md) | **Luồng Bot <-> Khách hàng, Bot <-> ĐHVT & Đồng bộ `transport_plans` Cục bộ**: Điền slot trống J2, cập nhật/xung đột plan, chế độ `MANUAL` duyệt sửa outbound, hỏi đáp khách hàng giới hạn `RouteMap` che SĐT, tra cứu chỉ đọc ĐHVT, cấm duyệt trên Zalo, `claim`/`transfer`/`approve`/`reject` và `check-overdue`. | Port 8000 |
| 10 | [`10_kiem_thu_ocr_minio_va_qdrant.md`](./10_kiem_thu_ocr_minio_va_qdrant.md) | **OCR, MinIO Storage, Bảng `files`, Sandbox & Qdrant**: Kiểm thử PaddleOCR (`8866`), `ai-service` `/api/v1/ocr` (`paddleocr` -> `gemini_vision`), MinIO (`9000`/`9001`, Presigned URL, `file_key`), webhook ảnh (`POST /webhook`), metadata bảng `files`, Sandbox OCR (`/api/sandbox/simulate`) và Qdrant (`6333`). | Port 8000, 8001, 8866, 9000, 6333 |
| 11 | [`11_kiem_thu_zalo_oa_bridge.md`](./11_kiem_thu_zalo_oa_bridge.md) | **Cầu nối Zalo Official Account (`oa-bridge`)**: Kiểm tra trạng thái Bot OA, quản lý nhóm GMF, người theo dõi, gửi tin nhắn và webhook OA. | Port 3000 |
| 12 | [`12_dong_bo_master_data_tms.md`](./12_dong_bo_master_data_tms.md) | **Đồng bộ Master Data TMS (`be-tms`)**: Kiểm thử endpoint kéo danh mục Nhà xe, Khách hàng, Kho, Cảng, Depot và cập nhật MySQL. | Port 8000 & TMS |

---

## 2. Thiết Lập Môi Trường Kiểm Thử (Postman Environment)

Tạo một môi trường trên Postman với các biến môi trường chuẩn sau:

| Tên biến (Variable) | Giá trị khởi tạo đề xuất | Ý nghĩa nghiệp vụ |
| :--- | :--- | :--- |
| `baseUrl` / `backend_url` | `http://localhost:8000` | Địa chỉ máy chủ FastAPI Backend |
| `bot_url` | `http://localhost:3000` | Địa chỉ máy chủ ZCA Zalo Bridge / OA Bridge |
| `ai_url` | `http://localhost:8001` | Địa chỉ máy chủ AI & OCR Microservice |
| `groupId` | `6469608867469758994` | Mã nhóm Zalo nhà xe / khách hàng mẫu |
| `userId` / `senderId` | `6691387223255581446` | Mã định danh tài xế / người gửi tin |
| `adminUsername` | `admin` | Tên đăng nhập tài khoản quản trị mặc định |
| `adminPassword` | `123456` | Mật khẩu tài khoản quản trị mặc định |
| `authToken` | *(tự động cập nhật sau đăng nhập)* | JWT Access Token nhận được sau khi đăng nhập |
| `webhook_secret` | `secret123` | Mã bí mật Webhook cấu hình tại ZALO_SECRET_KEY |

Headers chung cho các request `POST` / `PUT` / `PATCH`:
- `Content-Type`: `application/json; charset=utf-8`

---

## 3. Hướng Dẫn Thực Thi Trên Postman

1. Nhập cấu hình biến môi trường vào Postman Environment.
2. Thiết lập Method, URL, Headers và Params/Body tương ứng từng kịch bản kiểm thử trong các tài liệu từ `01_check_bot_zca.md` đến `12_dong_bo_master_data_tms.md`.
3. Kiểm tra kết quả HTTP Status và định dạng JSON trả về đối chiếu với kết quả kỳ vọng được mô tả trong từng tài liệu.
