# TỔNG HỢP BỘ KIỂM THỬ POSTMAN & CURL - VSICO ZALO BOT & BACKEND TMS
### HỆ THỐNG XỬ LÝ & ĐIỀU PHỐI THÔNG BÁO VẬN TẢI CONTAINER ĐA KÊNH

Thư mục này chứa toàn bộ tài liệu đặc tả kiểm thử API qua Postman và cURL định dạng Markdown (`.md`) phục vụ kiểm thử đơn vị, tích hợp và kiểm tra luồng nghiệp vụ hệ thống.

---

## 1. Cấu Trúc Danh Mục Tài Liệu Kiểm Thử

| STT | Tệp tài liệu | Phân hệ / Nội dung kiểm thử | Cổng dịch vụ |
| :---: | :--- | :--- | :---: |
| 01 | [`01_check_bot_zca.md`](./01_check_bot_zca.md) | **Cầu nối Zalo (ZCA Bridge)**: Kiểm tra trạng thái Bot, kết nối WebSocket, lấy danh sách nhóm, thành viên, lịch sử chat và tin nhắn realtime. | Port 3000 |
| 02 | [`02_check_be_connect.md`](./02_check_be_connect.md) | **Cổng Webhook Gateway (Backend)**: Kiểm tra kết nối Backend và quy trình tiếp nhận tin nhắn báo xe cơ bản qua `POST /webhook`. | Port 8000 |
| 03 | [`03_check_db.md`](./03_check_db.md) | **Cơ sở dữ liệu MySQL 8.4**: Kiểm tra sức khỏe kết nối DB (`GET /api/health`), dọn dẹp kế hoạch theo ngày và quản trị DB (`make db-clean`, `make db-status`). | Port 8000 & CLI |
| 04 | [`04_kiem_thu_truy_van_tin_nhan_va_xu_ly.md`](./04_kiem_thu_truy_van_tin_nhan_va_xu_ly.md) | **Truy vấn Tin nhắn & Xử lý (FIFO Extractor)**: Truy vấn tin nhắn theo nhóm, người gửi, lọc tin đã xử lý và test tự động bóc tách xe, tài xế, cont, seal, ISO 6346. | Port 8000 |
| 05 | [`05_kiem_thu_thongbao_loi.md`](./05_kiem_thu_thongbao_loi.md) | **Cảnh báo Lỗi & Phản hồi Nhà xe (`BotReply`)**: Tự động phát hiện tin nhắn thiếu/sai trường nghiệp vụ và sinh cảnh báo nhắc nhà xe bổ sung. | Port 8000 |
| 06 | [`06_user.md`](./06_user.md) | **Xác thực (Auth) & Quản lý Tài khoản (Users)**: Đăng nhập cấp JWT cookie/token, phân quyền RBAC (`admin`, `dhvt`), CRUD tài khoản người dùng theo Snowflake ID. | Port 8000 |
| 07 | [`07_luong_bot_nha_xe_ocr_llm.md`](./07_luong_bot_nha_xe_ocr_llm.md) | **Luồng Bot <-> Nhà xe, OCR & LLM Extraction**: Toàn trình báo xe, thiếu trường nhắc quote, đổi/hủy xe, lỗi gửi Zalo 3 lần, OCR ảnh (`files`) và AI Microservice (`/extract`, `/ocr`, `/match-warehouse`). | Port 8000 & 8001 |
| 08 | [`08_cap_nhat_xe_ke_hoach.md`](./08_cap_nhat_xe_ke_hoach.md) | **Cập nhật Xe trên Kế hoạch (Optimistic Lock)**: Kiểm thử `PATCH /api/plans/{plan_id}/vehicle`, kiểm soát `expected_version` (`409 Conflict`) và trạng thái `tms_sync_status`. | Port 8000 |
| 09 | [`09_luong_bot_khach_hang_va_dhvt.md`](./09_luong_bot_khach_hang_va_dhvt.md) | **Luồng Bot <-> Khách hàng, Bot <-> ĐHVT & Đồng bộ `transport_plans` Cục bộ**: Điền slot trống J2, cập nhật/xung đột plan, chế độ `MANUAL` duyệt sửa outbound, hỏi đáp khách hàng giới hạn `RouteMap` che SĐT, tra cứu chỉ đọc ĐHVT, cấm duyệt trên Zalo, `claim`/`transfer`/`approve`/`reject` và `check-overdue`. | Port 8000 |
| 10 | [`10_kiem_thu_ocr_minio_va_qdrant.md`](./10_kiem_thu_ocr_minio_va_qdrant.md) | **OCR, MinIO Storage, Bảng `files`, Sandbox & Qdrant**: Kiểm thử PaddleOCR (`8866`), `ai-service` `/api/v1/ocr` (`paddleocr` -> `gemini_vision`), MinIO (`9000`/`9001`, Presigned URL, `file_key`), webhook ảnh (`POST /webhook`), metadata bảng `files`, Sandbox OCR (`/api/sandbox/simulate`) và Qdrant (`6333`). | Port 8000, 8001, 8866, 9000, 6333 |

---

## 2. Thiết Lập Môi Trường Kiểm Thử (Postman Environment)

Tạo một môi trường trên Postman với các biến môi trường chuẩn sau:

| Tên biến (Variable) | Giá trị khởi tạo đề xuất | Ý nghĩa nghiệp vụ |
| :--- | :--- | :--- |
| `baseUrl` / `backend_url` | `http://localhost:8000` | Địa chỉ máy chủ FastAPI Backend |
| `bot_url` | `http://localhost:3000` | Địa chỉ máy chủ ZCA Zalo Bridge |
| `groupId` | `6469608867469758994` | Mã nhóm Zalo nhà xe / khách hàng mẫu |
| `userId` / `senderId` | `6691387223255581446` | Mã định danh tài xế / người gửi tin |
| `adminUsername` | `admin` | Tên đăng nhập tài khoản quản trị mặc định |
| `adminPassword` | `123456` | Mật khẩu tài khoản quản trị mặc định |
| `authToken` | *(tự động cập nhật)* | JWT Access Token nhận được sau khi đăng nhập |

Headers chung cho các request `POST` / `PUT`:
- `Content-Type`: `application/json; charset=utf-8`

---

## 3. Quy Trình Khởi Động & Thực Thi Kiểm Thử

### Bước 1: Khởi động Hạ tầng (MySQL 8.4 & MinIO)

Từ thư mục gốc dự án:
```bash
docker compose up -d
```

### Bước 2: Khởi động Cầu nối Zalo Bridge (Cổng 3000)

```bash
cd zca-js
npm start
```

### Bước 3: Khởi động Backend Server (Cổng 8000)

```bash
cd backend
source .venv/bin/activate
make run
```

### Bước 4: Thực thi Kiểm thử

* **Thực thi trên Postman**: Thiết lập các Request theo từng file Markdown hướng dẫn tương ứng (`01_check_bot_zca.md` đến `10_kiem_thu_ocr_minio_va_qdrant.md`).
* **Thực thi qua cURL**: Sao chép trực tiếp các khối lệnh `curl` có sẵn trong từng tài liệu Markdown để chạy trên Terminal.
