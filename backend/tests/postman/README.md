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
| 13 | [`13_keo_ke_hoach_van_chuyen_tms.md`](./13_keo_ke_hoach_van_chuyen_tms.md) | **Kéo Kế Hoạch Vận Chuyển Theo Ngày & Miền Từ TMS**: Kiểm thử đồng bộ kế hoạch đóng/trả, cân đối vỏ và cảnh báo vỏ từ `be-tms`. | Port 8000 & TMS |
| 14 | [`14_tro_ly_van_tai_phase1.md`](./14_tro_ly_van_tai_phase1.md) | **Trợ Lý Vận Tải Đa Vai Trò (Phase 1)**: Kiểm thử hội thoại trợ lý cho Khách hàng, Nhà xe và ĐHVT. | Port 8000 & 8001 |
| 15 | [`15_kiem_thu_nlp_phobert_rapidfuzz_va_tro_ly_ai.md`](./15_kiem_thu_nlp_phobert_rapidfuzz_va_tro_ly_ai.md) | **NLP Nội Bộ (`Precision Regex + vinai/phobert-base-v2 + RapidFuzz`), API Test NLP & Duyệt Zalo ĐHVT**: Đồng bộ nhóm thật OA Bridge, kiểm thử trực tiếp 3 tầng NLP qua `POST /api/sandbox/nlp-analyze`, kiểm tra sức khỏe Zalo OA Watchdog (`GET /api/health/zalo-oa`), ghép `RO -> LO`, thống kê vùng/tỉnh kèm ảnh PNG và duyệt/sửa/hủy trực tiếp từ nhóm ĐHVT. | Port 8000, 8001, 3000 |
| 16 | [`16_kiem_thu_bo_25000_proxy_tung_sheet.md`](./16_kiem_thu_bo_25000_proxy_tung_sheet.md) | **Kiểm Thử Proxy 25.000 Kịch Bản Theo Từng Sheet, Family & Postman Sandbox**: Hướng dẫn chạy toàn bộ 25.000 test (`run_proxy_25000_eval.py`) với trọng số thật `vinai/phobert-base-v2`, chạy lọc từng sheet / family / `Test ID` / `--only-fail`, đọc 26 chỉ số CSV/Excel và test mẫu 1–12+ chuyến trên `POST /api/sandbox/simulate`. | CLI Proxy & Port 8000 |
| 17 | [`17_tms_dispatch_assignment.md`](./17_tms_dispatch_assignment.md) | **Tích Hợp Cập Nhật Điều Phối Sang TMS (`dispatch-assignment`)**: Kiểm thử trực tiếp API `POST /api/integrations/zalo/dispatch-assignment`, cập nhật từng phần, đa SĐT (`09..1 \| 09..2`), chuẩn hóa biển số có dấu chấm, hội thoại nhiều lượt, tách riêng LO/RO, lệnh kết hợp RO+LO và đối soát `tms_sync_logs` / `activity_logs`. | Port 8000 & TMS |
| 18 | [`vsico_api_zalo_nlp_and_ux_v2.postman_collection.json`](./vsico_api_zalo_nlp_and_ux_v2.postman_collection.json) | **Postman Collection v2.1 Import Sẵn (NLP PhoBERT & Zalo UX v2)**: Bộ request sẵn dùng cho `POST /api/sandbox/nlp-analyze`, `GET /api/health/zalo-oa` và Webhook Nhà xe/ĐHVT. | Port 8000 |

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

1. Nhập cấu hình biến môi trường vào Postman Environment (hoặc import file [`vsico_server.postman_environment.json`](./vsico_server.postman_environment.json)). Toàn bộ kịch bản test gửi về Webhook phải đính kèm `"is_test": true` (hoặc chạy trên backend có `ZALO_PROXY_ONLY=True`) để không bắn tin ra Zalo OA thật.
2. Lưu ý cửa sổ đợi FIFO: Nhóm Nhà xe (`SOURCE`) mặc định đợi 20 giây im lặng (trần 60 giây); nếu cần ép Backend xử lý ngay lập tức trong Postman/Newman sau khi gửi `POST /webhook`, gọi `POST {{baseUrl}}/api/messages/process-fifo?force=true` (nhóm ĐHVT và Khách hàng luôn xử lý ngay).
3. Thiết lập Method, URL, Headers và Params/Body tương ứng từng kịch bản kiểm thử trong các tài liệu từ `01_check_bot_zca.md` đến `17_tms_dispatch_assignment.md`.
4. Kiểm tra kết quả HTTP Status và định dạng JSON trả về đối chiếu với kết quả kỳ vọng được mô tả trong từng tài liệu.

---

## 4. Chạy Trực Tiếp Trên Server (Postman GUI & Newman CLI)

1. **Qua Postman Desktop GUI** (đã cài tại `/snap/bin/postman`):
   - Import [`vsico_api_zalo_nlp_and_ux_v2.postman_collection.json`](./vsico_api_zalo_nlp_and_ux_v2.postman_collection.json) và [`vsico_server.postman_environment.json`](./vsico_server.postman_environment.json).
   - Chọn Environment `VSICO Server (Local / Public API)`, điền `webhookSecret` (khớp `ZALO_SECRET_KEY` trong `.env`) và `adminPassword` vào cột **Current Value**, sau đó bấm **Run** để chạy toàn bộ Collection.
2. **Qua Terminal bằng Newman CLI** (chế độ Dry-Run an toàn trên server):
   ```bash
   npx --yes newman run backend/tests/postman/vsico_api_zalo_nlp_and_ux_v2.postman_collection.json \
     -e backend/tests/postman/vsico_server.postman_environment.json \
     --env-var "baseUrl=http://127.0.0.1:8000" \
     --env-var "webhookSecret=$ZALO_SECRET_KEY" \
     --env-var "adminPassword=<MAT_KHAU_ADMIN>"
   ```
