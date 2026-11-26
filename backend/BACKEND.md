# Đặc tả Kỹ thuật Phân hệ Backend (VSICO Zalo Bot v1.5.0)

Phân hệ `backend` là lõi điều phối nghiệp vụ trung tâm của hệ thống **VSICO Zalo Bot & TMS Integration**, được xây dựng bằng **Python 3.12+**, **FastAPI**, **SQLAlchemy 2.0 ORM**, **Alembic**, **Pydantic v2** và **MySQL 8.4+**.

---

## 1. Kiến trúc Phân tầng (Clean Architecture)

Mã nguồn trong `backend/src/` tuân thủ kiến trúc phân tầng rõ ràng, tách biệt hoàn toàn quy tắc nghiệp vụ cốt lõi (`domain/`) khỏi giao thức HTTP, cơ sở dữ liệu và các dịch vụ bên ngoài (`infrastructure/`):

```text
backend/
├── alembic.ini                       # Cấu hình Alembic Migration
├── Makefile                          # Tập lệnh quản trị và khởi chạy dịch vụ
├── requirements.txt                  # Danh sách thư viện Python 3.12+
├── scripts/
│   ├── manage_db.py                  # Công cụ kiểm tra kết nối, trạng thái 24 bảng và dọn dẹp DB
│   └── seed_golden_plans.py          # Script tạo dữ liệu kế hoạch mẫu phục vụ kiểm thử
├── migrations/
│   └── versions/                     # Lịch sử phiên bản schema MySQL 8.4+
├── src/
│   ├── api/                          # Tầng HTTP Router & Pydantic DTO (Biên giao tiếp REST API)
│   │   ├── app.py                    # Khởi tạo FastAPI App (v1.5.0), Lifespan, SSE, Public PNG Report & FIFO Worker
│   │   ├── auth.py                   # Xác thực JWT (httpOnly Cookie & Refresh Token), RBAC (admin/dhvt)
│   │   ├── dashboard.py              # API thống kê tổng quan vận hành
│   │   ├── events.py                 # Server-Sent Events (SSE /api/events/stream)
│   │   ├── groups.py                 # Quản lý nhóm Zalo & đồng bộ nhóm thực tế từ OA/ZCA Bridge
│   │   ├── master_data.py            # API quản lý Danh mục (Nhà xe, Khách, Kho, Xe, Rơ-moóc trailers, Tài xế, Bí danh)
│   │   ├── messages.py               # API tra cứu tin nhắn gốc, lượt bóc tách & xả FIFO (?force=true)
│   │   ├── outbound.py               # API quản lý tin nhắn gửi đi (Duyệt kèm đồng bộ TMS, Hủy, Gửi lại)
│   │   ├── plans.py                  # API Kế hoạch vận chuyển, Import CSV/Excel, Đồng bộ TMS (tms_auto_sync)
│   │   ├── results.py                # API tra cứu kết quả thực thi container_jobs & truck_records
│   │   ├── reviews.py                # API xử lý Ca chờ duyệt (Chọn candidate_plans, Học WarehouseAlias)
│   │   ├── sandbox.py                # API giả lập dry-run (`/api/sandbox/simulate`) & kiểm thử NLP 3 tầng (`/api/sandbox/nlp-analyze`)
│   │   ├── schemas.py                # Toàn bộ Pydantic v2 Request/Response Schema
│   │   ├── users.py                  # API quản trị tài khoản nội bộ (Chỉ dành cho Admin)
│   │   └── webhook.py                # Cổng tiếp nhận POST /webhook siêu mỏng (< 50ms)
│   ├── assistant/                    # Trợ lý ảo vận tải phục vụ 3 vai trò (Khách hàng, Nhà xe, ĐHVT)
│   │   ├── scope_resolver.py         # Xác định vai trò và phạm vi dữ liệu (Scope) theo nhóm/người gửi
│   │   ├── service.py                # Bộ điều phối hội thoại Trợ lý AI & bộ nhớ hội thoại ngắn hạn (10 phút)
│   │   ├── response_formatter.py     # Định dạng câu trả lời chuẩn nghiệp vụ `[VSICO] - ...`
│   │   ├── intent_router.py          # Phân loại ý định (Precision Regex + PhoBERT + RapidFuzz + AI Fallback)
│   │   ├── queries.py                # Truy vấn dữ liệu kế hoạch, thống kê vùng miền/tỉnh thành trong phạm vi cấp phép
│   │   ├── schemas.py                # Cấu trúc dữ liệu nội bộ của Assistant
│   │   ├── tool_registry.py          # Đăng ký công cụ theo từng vai trò (Customer, Carrier, DHVT)
│   │   ├── tools_carrier.py          # Công cụ cho Nhà xe (Xem việc, Lệnh mẫu copy-paste, Xác nhận LO kết hợp / OCR, Cập nhật 2 bước)
│   │   ├── tools_customer.py         # Công cụ cho Khách hàng (Tra cứu lịch giao nhận, Số cont, Tài xế)
│   │   └── tools_dhvt.py             # Công cụ cho ĐHVT (Duyệt/Sửa/Hủy trực tiếp trên Zalo 1 tin duy nhất, Thống kê ngày vs Chi tiết tỉnh, Ảnh PNG)
│   ├── config/
│   │   └── settings.py               # Quản lý biến môi trường tập trung từ `.env` & `VERSION` (`APP_VERSION`, `ZALO_PROXY_ONLY`, `GROUP_PROCESS_DELAY_SECONDS=20`)
│   ├── domain/                       # Lõi quy tắc nghiệp vụ thuần khiết (Không phụ thuộc ORM/HTTP)
│   │   ├── enums.py                  # Tập hợp Enum trạng thái toàn hệ thống
│   │   ├── errors.py                 # Ngoại lệ nghiệp vụ chuẩn hóa
│   │   ├── models.py                 # Thực thể miền (Domain Entities)
│   │   ├── patterns.py               # Bộ Precision Regex dùng chung (biển số đầu kéo/rơ-moóc hỗ trợ NBSP, container ISO, đa SĐT)
│   │   ├── short_link.py             # Tạo/giải mã đường dẫn rút gọn 15 ký tự cho ca duyệt ĐHVT
│   │   └── rules.py                  # Kiểm tra chữ số container ISO 6346 Modulo 11, chuẩn hóa biển số, đa SĐT (`09..1 | 09..2`), mask_phone
│   ├── handlers/                     # Tầng điều phối luồng nghiệp vụ (Use Cases / Application Services)
│   │   ├── carrier_flow_service.py   # Xử lý tin Nhà xe, gom mảnh tin theo cửa sổ đợi 20s/trần 60s, Danh thiếp Zalo, xác nhận OCR & cặp RO+LO
│   │   ├── dhvt_service.py           # Chuẩn hóa `[VSICO] - ...`, nhân hóa mã lỗi, gom lô nhiều ca/quá hạn thành 1 tin & thông báo duyệt ĐHVT
│   │   ├── extraction_handler.py     # Điều phối pipeline bóc tách đa tầng, luồng RO/LO kết hợp & Cont lạ, cưỡng chế duyệt MANUAL
│   │   ├── plan_resolution_engine.py # Động cơ đối chiếu kế hoạch 6 nhánh (TH1-TH6) & resolve_batch
│   │   ├── plan_sync_service.py      # Cập nhật kế hoạch nguyên tử, đồng bộ RO -> LO ghép vỏ & đồng bộ `dispatch-assignment`
│   │   └── tms_plan_sync_service.py  # Kéo danh mục/kế hoạch từ TMS và ghi ngược (Write-back) có kiểm soát
│   ├── infrastructure/               # Tầng giao tiếp CSDL MySQL, MinIO, Zalo Bridge, AI Service, TMS API
│   │   ├── ai_service_client.py      # HTTP Client gọi ai-service (Header X-Internal-Token & PII Masking)
│   │   ├── database.py               # Quản lý SQLAlchemy Engine & Session
│   │   ├── fifo_queue.py             # Hàng đợi bất đồng bộ FIFOExtractionQueue (Đợi 20s/trần 60s riêng nhóm Nhà xe; ĐHVT/Khách xử lý ngay)
│   │   ├── minio_client.py           # Lưu trữ file đính kèm và sinh Presigned URL
│   │   ├── models.py                 # Định nghĩa 24 bảng ORM SQLAlchemy 2.0
│   │   ├── repositories.py           # Truy vấn dữ liệu nghiệp vụ
│   │   ├── snowflake.py              # Bộ sinh khóa chính Snowflake ID 64-bit (BigInteger)
│   │   ├── throttler.py              # Bộ điều tiết ZaloOutboundThrottler (Token Bucket)
│   │   ├── tms_client.py             # HTTP Client tích hợp hệ thống be-tms
│   │   ├── zalo_dispatcher.py        # Phát hành tin nhắn văn bản & ảnh PNG sang Bridge (kèm cô lập `ZALO_PROXY_ONLY` sink)
│   │   └── zalo_watchdog.py          # Giám sát sức khỏe Zalo OA, SSE Event Bus, xả draft hết hạn & quét quá hạn có kiểm soát
│   ├── ingestion/                    # Tiền xử lý, chống trùng lặp (Idempotency) tại cổng Webhook
│   ├── messaging/                    # Phân loại ý định (`classifier.py`), phân đoạn đa xe (`segmenter.py`)
│   ├── observability/                # Cấu hình Logging chuẩn hóa và đo lường latency
│   ├── outbound/                     # Soạn thảo thông báo thân thiện (`templates.py`) & xuất ảnh báo cáo PNG (`report_image_generator.py`)
│   ├── parsing/                      # Bóc tách thông tin văn bản đa tầng
│   │   ├── trip_parser.py            # Tầng 1: Bóc tách tất định bằng Precision Regex & ISO 6346 (hỗ trợ đa SĐT)
│   │   ├── local_nlp_extractor.py    # Tầng 2: Trọng số thật `vinai/phobert-base-v2` (`phobert_transformers_local`) + RapidFuzz + Danh mục TMS
│   │   └── ai_fallback.py            # Tầng 3: Điều kiện kích hoạt và gọi dự phòng AI Service (che SĐT tự động)
│   └── validation/                   # Kiểm tra tính đầy đủ 5 trường bắt buộc & chuẩn ISO 6346
└── tests/                            # Bộ kiểm thử tự động Pytest (169 kịch bản Proxy-only), Proxy 25.000 test & Postman (01 -> 17 + Collection v2)
```

---

## 2. Luồng Xử lý & Bóc tách Đa tầng

```mermaid
sequenceDiagram
    autonumber
    participant Bridge as oa-bridge / zca-js
    participant WH as POST /webhook
    participant Queue as FIFOExtractionQueue
    participant NLP as Tầng 1 (Regex/ISO) + Tầng 2 (PhoBERT + Từ điển + RapidFuzz)
    participant AI as Tầng 3 (ai-service Fallback)
    participant Engine as PlanResolutionEngine (TH1-TH6)
    participant DB as MySQL 8.4 (24 Bảng)

    Bridge->>WH: Gửi sự kiện tin nhắn Zalo (Text / Ảnh / Quote)
    WH->>DB: Lưu thô vào zalo_messages ở trạng thái QUEUED
    WH->>Queue: Xếp hàng đợi FIFO (nhóm Nhà xe đợi im lặng 20s/trần 60s; ĐHVT xử lý ngay)
    WH-->>Bridge: Trả ngay HTTP 200 OK (< 50ms)

    Note over Queue,DB: Nhóm Nhà xe đợi im lặng 20s từ tin cuối (trần tối đa 60s); nhóm ĐHVT & Khách trả lời luôn
    Queue->>NLP: Mở khóa nhóm & khởi chạy xử lý theo thứ tự thời gian
    NLP->>NLP: 1. Giải quyết đồng tham chiếu ("xe trên", "tài xế đó") từ ngữ cảnh
    NLP->>NLP: 2. Tách từ ghép tiếng Việt & nhận diện thực thể bằng PhoBERT
    NLP->>NLP: 3. Đối chiếu Từ điển danh mục (Xe, Tài xế, Khách, Kho) bằng RapidFuzz
    NLP->>NLP: 4. Kiểm tra chữ số kiểm tra Container theo chuẩn ISO 6346 Modulo 11

    alt Đủ trường bắt buộc & Độ tự tin cao
        NLP->>Engine: Chuyển danh sách xe/container đã bóc tách
    else Thiếu trường hoặc tin nhắn phức tạp / có ảnh lệnh
        NLP->>AI: Gọi /api/v1/extract hoặc /api/v1/ocr (Đã che SĐT 0903xxxx59)
        AI-->>NLP: Trả về thực thể bóc tách + kết quả Map kho
        NLP->>Engine: Hợp nhất kết quả và chuyển sang đối chiếu kế hoạch
    end

    Engine->>DB: Đối chiếu transport_plans theo 6 nhánh (TH1 -> TH6)
    Engine->>DB: Đồng bộ nguyên tử RO -> LO (nếu ghép vỏ) & tạo outbound_messages / review_cases
```

### Chi tiết 3 tầng bóc tách (`src/parsing/` & `ai-service`)

1. **Tầng 1 — Precision Regex & ISO 6346 (`src/domain/patterns.py`, `src/parsing/trip_parser.py`, `src/domain/rules.py`)**:
   - Tách biệt rõ biển số đầu kéo (`PLATE_REGEX`, loại trừ seri `R`/`RM`, hỗ trợ ký tự NBSP `\u00a0` của Zalo và chặn số thừa ở đuôi), biển số rơ-moóc (`TRAILER_PLATE_REGEX`), số container 11 ký tự (`CONT_REGEX`, chuẩn ISO 6346 Modulo 11) và hỗ trợ bắt nhiều số điện thoại trên cùng một tài xế (`PHONE_PATTERN`, định dạng lưu & gửi TMS: `09..1 | 09..2`).
2. **Tầng 2 — NLP Nội bộ với trọng số thật `vinai/phobert-base-v2` (`src/parsing/local_nlp_extractor.py`)**:
   - **Trọng số `vinai/phobert-base-v2` (`phobert_transformers_local`)**: Mặc định bật `ENABLE_PHOBERT_TRANSFORMERS=1` chạy hoàn toàn offline từ cache cục bộ; áp dụng khử anisotropy bằng mean-centering (`_mean_emb`), vector hóa cosine similarity theo ma trận, bộ đệm LRU theo bộ khung câu (`_intent_skeleton`), ngưỡng tin cậy `INTENT_MIN_CONFIDENCE = 0.65` (trả `UNKNOWN` khi không đủ tin cậy) và tính confidence động cho thực thể `PER`/`LOC`.
   - **Giải quyết đồng tham chiếu & Từ điển danh mục (`RapidFuzz`)**: Đối chiếu trực tiếp 6 bảng danh mục TMS (`vehicles`, `trailers`, `drivers`, `customers`, `warehouses`, `warehouse_aliases`) để bổ sung thông tin còn thiếu trước khi xét gọi Tầng 3.
   - **API Kiểm thử trực tiếp 3 tầng NLP**: `POST /api/sandbox/nlp-analyze` (dry-run, không ghi DB) trả toàn bộ chi tiết Tầng 1, Tầng 2 (`backend_mode`, `model_name`, `intent_confidence`, `spans`), cờ Tầng 3, cảnh báo nhà xe thân thiện và đối chiếu cặp lệnh kết hợp `RO + LO`.
3. **Tầng 3 — AI & OCR Fallback (`ai-service`)**:
   - Chỉ kích hoạt khi tin nhắn có đính kèm hình ảnh/PDF cần OCR hoặc khi Tầng 1 + Tầng 2 chưa bóc tách đủ trường bắt buộc / không khớp được địa chỉ kho.
   - Trước khi gửi văn bản sang `ai-service`, Backend luôn gọi hàm `mask_phone()` để che số điện thoại tài xế thành dạng `0903xxxx59` và khôi phục lại sau khi nhận phản hồi.

---

## 3. Động cơ Đối chiếu Kế hoạch 6 Nhánh (`PlanResolutionEngine`)

Module `src/handlers/plan_resolution_engine.py` và `src/handlers/plan_sync_service.py` phân loại kết quả đối chiếu từng chuyến xe với bảng `transport_plans` thành 6 trường hợp rõ ràng:

| Nhánh | Mã quyết định | Điều kiện kích hoạt | Hành động của Hệ thống |
| :---: | :--- | :--- | :--- |
| **TH1** | `AUTO_MATCH_RETURN` / `AUTO_MATCH_LOADING` | Khớp duy nhất 1 dòng kế hoạch (`score >= 85`, cách biệt với ứng viên thứ 2 `>= 15` điểm), nhà xe hợp lệ, container đúng chuẩn ISO 6346. | Tự động cập nhật xe/tài xế/cont/seal vào `transport_plans`, tăng `version`, đặt `tms_sync_status = 'PENDING'`, sinh tin nhắn thông báo nhóm Khách hàng và xác nhận cho Nhà xe. |
| **TH2** | `AMBIGUOUS_LOADING` (Nhiều kế hoạch ứng viên) | Tìm thấy từ 2 dòng kế hoạch đóng hàng trở lên có cùng mức điểm cao (cùng khách hàng, kho hoặc kích cỡ cont). | Không tự động gán; mở ca duyệt `review_cases` trên Web kèm danh sách `candidate_plans` đã xếp hạng để ĐHVT chọn bằng 1 cú nhấp chuột. |
| **TH3** | `UNRESOLVED_LOADING` / `NO_PLAN_MATCH` | Không tìm thấy dòng kế hoạch phù hợp hoặc địa chỉ kho mới chưa có trong danh mục / từ điển bí danh. | Mở ca duyệt `review_cases` cho ĐHVT. Khi ĐHVT chọn kế hoạch đúng trên Web, hệ thống tự động lưu địa chỉ thô vào `warehouse_aliases` (`source = 'LEARNED'`) để tự học cho các lần sau. |
| **TH4** | `MISSING_INFO` | Đã xác định được dòng kế hoạch nhưng nhà xe gửi thiếu trường bắt buộc (VD: có số cont nhưng thiếu biển số xe hoặc SĐT tài xế). | Lưu vào bản nháp `message_drafts` (gom mảnh tin trong cửa sổ đợi 20s / trần 60s) và gửi tin nhắn hỏi lại nhà xe phần thông tin còn thiếu (`bot_replies`). |
| **TH5** | `CONFLICT` / `CARRIER_MISMATCH` / `VEHICLE_NOT_IN_FLEET` | Khớp kế hoạch nhưng phát hiện mâu thuẫn: sai nhà xe được phân công, biển số không thuộc đội xe, hoặc đổi xe/tài xế khi chuyến đã khóa. | Chặn tự động cập nhật; tạo cảnh báo ưu tiên cao trong `review_cases` và gửi thông báo về nhóm Zalo ĐHVT nội bộ. |
| **TH6** | `SHELL_WARNING` (Cảnh báo vỏ container) | Lệnh đóng ghép vỏ từ lệnh trả (`linked_return_plan_id`) nhưng vỏ trả bị báo hư hỏng, quá hạn lưu bãi (DEM/DET) hoặc lệch kích cỡ (`20'` vs `40'`). | Ghi nhận cảnh báo vỏ container và tạo ca kiểm tra trên Web cho ĐHVT. |

- **Xử lý theo lô đa xe (`resolve_batch`)**: Khi một tin nhắn báo nhiều xe hoặc một xe kéo 2 container 20 feet, `resolve_batch` phân bổ độc lập các dòng kế hoạch ứng viên, đảm bảo 2 xe trong cùng tin nhắn không bị gán trùng vào một dòng kế hoạch duy nhất.
- **Đồng bộ nguyên tử Lệnh trả -> Lệnh đóng (`RO -> LO`)**: Khi một lệnh trả hàng nhập (`RO`) được cập nhật biển số xe, rơ-moóc, tên tài xế và SĐT, nếu có lệnh đóng hàng xuất (`LO`) đang liên kết ghép vỏ (`linked_return_plan_id == RO.id`) và chưa có xe riêng, hệ thống tự động kế thừa nguyên tử bộ thông tin xe/tài xế sang lệnh đóng trong cùng một giao dịch cơ sở dữ liệu.

---

## 4. Trợ lý AI Vận tải 3 Vai trò (`src/assistant/`)

Trợ lý ảo kiểm soát chặt chẽ quyền truy cập dữ liệu (Scope) ngay tại tầng truy vấn SQL (`src/assistant/queries.py`):

1. **Vai trò Khách hàng (`CUSTOMER` - Nhóm Zalo `TARGET`)**:
   - Phạm vi dữ liệu: Chỉ truy vấn được các kế hoạch thuộc `customer_id` và `warehouse_id` đã cấu hình trong bảng `route_maps` của nhóm Zalo đó.
   - Công cụ hỗ trợ: Tra cứu lịch xe giao/nhận trong ngày, tra theo số container/biển số, xem thông tin tài xế/SĐT, tóm tắt tiến độ đơn hàng và gửi yêu cầu thay đổi (tạo `review_cases` trên Web).
2. **Vai trò Nhà xe (`CARRIER` - Nhóm Zalo `SOURCE`)**:
   - Phạm vi dữ liệu: Chỉ truy vấn và thao tác trên các kế hoạch được giao cho `carrier_id` gắn với nhóm Zalo nhà xe đó.
   - Công cụ hỗ trợ: Xem danh sách việc trong ngày, kiểm tra các chuyến còn thiếu xe/tài xế/cont/seal, và cập nhật thông tin xe theo **cơ chế xác nhận 2 bước** (`carrier_propose_vehicle_update` tạo bản xem trước -> nhà xe nhắn `"Xác nhận"` -> `carrier_confirm_pending_action` mới ghi vào CSDL).
3. **Vai trò Điều hành Vận tải (`DHVT` - Nhóm Zalo `DHVT` nội bộ)**:
   - Phân quyền theo nhóm: Mọi thành viên trong nhóm Zalo ĐHVT đang hoạt động (`group_role = 'DHVT'`, `is_active = True`) đều có đầy đủ chức năng ĐHVT (không bắt buộc gắn `users.zalo_user_id`; nếu đã gắn thì dùng tên tài khoản để ghi vết kiểm toán, ngược lại dùng tên hiển thị Zalo).
   - Công cụ hỗ trợ (`src/assistant/tools_dhvt.py`):
     - `dhvt_get_daily_overview`: Thống kê tổng quan ngày gồm tổng số lệnh, tỷ lệ phần trăm bố trí xe, tỷ lệ phần trăm **lệnh đã đóng / lệnh đang mở**, tỷ lệ phần trăm **lệnh đóng (`LO`) / lệnh trả (`RO`)** theo cỡ container (`20'`, `40'`), tốp địa phương nhiều lệnh nhất, cân đối vỏ, và xuất **ảnh PNG tổng hợp chứa cả bảng thống kê tỷ lệ % lẫn bảng chi tiết các lệnh trong ngày**.
     - `dhvt_get_province_plans`: Tách biệt hoàn toàn với thống kê tổng quát khi ĐHVT hỏi kế hoạch hoặc chi tiết lệnh của một tỉnh/thành cụ thể (ví dụ `"chi tiết lệnh tỉnh Hưng Yên ngày 17/11"`), trả về chỉ số tỷ lệ % riêng của tỉnh đó, **danh sách từng lệnh chi tiết** bằng văn bản và **ảnh PNG chi tiết tỉnh** gồm KPI % + toàn bộ bảng lệnh của tỉnh.
     - `dhvt_search_plans`, `dhvt_check_plan_detail`: Tra cứu chi tiết mọi kế hoạch theo số cont, biển số, nhà xe, khách hàng, kho hoặc vùng/tỉnh.
     - `dhvt_get_container_warnings`: Liệt kê các cảnh báo vỏ container, ghép vỏ `RO -> LO` và lệch thông tin.
     - `dhvt_detect_duplicate_vehicles`: Phát hiện một biển số xe đang bị gán trùng cho nhiều kế hoạch hoạt động cùng khung giờ.
     - `dhvt_get_priority_digest` & `dhvt_explain_review_case`: Tóm tắt danh sách ca chờ duyệt ưu tiên cao và giải thích chi tiết lý do phát sinh ca chờ.
     - `dhvt_get_bot_performance`: Thống kê hiệu suất bóc tách tự động của Bot trong ngày.
     - `dhvt_direct_review_action`: Cho phép mọi thành viên trong nhóm Zalo ĐHVT đang hoạt động nhắn trực tiếp `"ok"`, `"oki"`, `"duyệt"`, `"sửa ..."`, `"hủy ..."`, `"từ chối ..."` (hoặc quote tin báo duyệt) ngay trên nhóm Zalo ĐHVT. Sau khi xử lý thành công (từ Zalo hoặc Web), Bot thông báo công khai vào nhóm ĐHVT theo mẫu `[VSICO] - ...` ghi rõ tên người duyệt (không kèm mã trạng thái kỹ thuật) và phản hồi kết quả ngược lại nhóm Nhà xe.
     - `dhvt_remind_carrier`: Cho phép ĐHVT gõ `"nhắc nhà xe ..."` để Bot tự gửi lời nhắc lịch sự vào đúng nhóm nhà xe tương ứng.
     - `HtmlReportImageGenerator`, `DhvtNotificationService` (gom thông báo lô) & `ZaloOaWatchdog`: Hỗ trợ xuất bảng thống kê + bảng danh sách lệnh HTML sang ảnh PNG qua Headless Chrome (`GET /api/public/reports/{token}.png`); tự động gom nhiều yêu cầu quá hạn hoặc nhiều ca cần duyệt phát sinh cùng lúc cho cùng 1 nhóm thành **1 tin nhắn tổng hợp `[VSICO] - ...` duy nhất**; giám sát kết nối Zalo OA (`GET /api/health/zalo-oa`, SSE `/api/events/stream`, xả bộ đệm draft hết hạn định kỳ). Cờ `ZALO_OVERDUE_ESCALATION_ENABLED` mặc định `False` để tránh vòng lặp nền quét xả các ca cũ.

---

## 5. Luồng Cập Nhật TMS (RO / LO / Kết Hợp / Cont Lạ) & Phản Hồi Nhà Xe

- **Lệnh trả (`RO`) và Lệnh đóng (`LO`) độc lập**: Khi tin đủ 5 trường hợp lệ và khớp kế hoạch, chế độ `AUTO` (cả nhóm nhà xe lẫn nhóm khách hàng đều `AUTO`) cập nhật trực tiếp lên `transport_plans` và TMS ngay (kể cả khi chưa gắn `RouteMap` khách hàng). Khi **nhóm nhà xe hoặc nhóm khách hàng** đang ở chế độ **Chờ duyệt (`MANUAL`)**, hệ thống tuyệt đối không ghi trước vào `transport_plans` và không đẩy TMS (kể cả khi lệnh trả đã đủ toàn bộ 4–5 trường thông tin) mà tạo ca chờ duyệt `group_manual_review` gửi nhóm ĐHVT; chỉ đồng bộ sau khi ĐHVT duyệt trên `/reviews`, `/results` hoặc Zalo ĐHVT.
- **Lệnh đóng kết hợp (`RO + LO` dùng chung số container)**:
  - Khi **nhóm nhà xe hoặc nhóm khách hàng (`RO`/`LO`)** đang ở chế độ **Chờ duyệt (`MANUAL`)**: cả Lần 1 lẫn Lần 2 đều chuyển sang ĐHVT duyệt (`COMBINED_RO_LO_REVIEW` chứa đủ `RO + LO`), không tự ghi `transport_plans`, không tự đẩy TMS và không gửi `combined_lo_confirm` bỏ qua ĐHVT. Khi ĐHVT duyệt 1 lần (trên Web hoặc quote `"duyệt"` trên Zalo), hệ thống đồng bộ cả `RO` và `LO` lên TMS và phản hồi duy nhất **1 tin nhắn chuẩn `[VSICO] - ...`** vào nhóm ĐHVT (không lặp 2 tin).
  - Khi cả nhóm nhà xe và nhóm khách hàng đều `AUTO`: Lần 1 tự đồng bộ `RO` lên TMS ngay và gửi tin hỏi xác nhận lệnh đóng kết hợp về Nhà xe (`combined_lo_confirm`, nhà xe nhắn `"ok"` để đồng bộ tiếp `LO`); Lần 2 (`RO` đã có thông tin) định tuyến thẳng sang `LO`.
- **Container hợp lệ nhưng chưa có trong kế hoạch (`SHIPPING_NOT_FOUND`)**: Đồng thời cảnh báo thân thiện về nhóm Nhà xe và gửi thông báo về nhóm ĐHVT ghi rõ nguồn (`Nguồn: Nhóm <tên nhóm> | Nhà xe: ... | Người gửi: ...`).
- **Thông báo lỗi thân thiện cho Nhà xe**: Chuẩn hóa theo 7 nhóm biểu mẫu `[VSICO] - ...` (`Vấn đề + Thông tin cần kiểm tra + Hướng xử lý`), không lộ Regex, check digit ISO 6346, mã lỗi nội bộ hay chi tiết database; kết hợp cửa sổ đợi nhóm Nhà xe 20s im lặng / trần 60s (`carrier_fragment_buffer`) và bóc tách Danh thiếp Zalo (`contact`/`business_card`).

---

## 6. Bảo mật, Phân quyền & Khóa Phiên bản (Optimistic Locking)

- **Xác thực & Phân quyền Web (`src/api/auth.py`)**:
  - Hỗ trợ đăng nhập qua `POST /api/auth/login` trả về JWT đồng thời thiết lập `httpOnly` cookie.
  - Phân quyền 2 cấp: `admin` (toàn quyền cấu hình hệ thống, quản lý người dùng `/api/users`, quản lý nhóm Zalo) và `dhvt` (vận hành kế hoạch, duyệt ca `/api/reviews`, quản lý danh mục, phê duyệt tin gửi đi `/api/outbound`).
- **Chống ghi đè đồng thời (`expected_version`)**:
  - Khi hai nhân viên ĐHVT cùng mở một dòng kế hoạch (`PATCH /api/plans/{id}/vehicle`) hoặc cùng xử lý một ca chờ duyệt (`POST /api/reviews/{id}/resolve`), Backend kiểm tra `expected_version`. Nếu phiên bản trong DB đã thay đổi, API trả về mã lỗi `409 Conflict` để giao diện cảnh báo và tải lại dữ liệu mới nhất.
- **Đồng bộ nhóm Zalo thực tế (`src/api/groups.py`)**:
  - Khi gọi `GET /api/groups`, Backend tự động gọi `sync_live_groups_from_bridge()` sang `oa-bridge` / `zca-js` (`GET /api/bot/groups`) để đồng bộ danh sách nhóm thực tế (bao gồm nhóm GMF và hội thoại trực tiếp `direct_<user_id>` với vai trò `DIRECT_CHAT`), tuyệt đối không dùng dữ liệu nhóm giả lập.

---

## 7. Kiểm thử & Vận hành

### Chạy bộ kiểm thử tự động Pytest

```bash
cd backend
ENABLE_PHOBERT_TRANSFORMERS=1 HF_HUB_OFFLINE=1 .venv/bin/pytest tests -v
```

Bộ kiểm thử gồm **169 bài test tự động** chạy hoàn toàn ở chế độ **Proxy-only (`ZALO_PROXY_ONLY=True`, 0% cuộc gọi thật tới Zalo OA)**, bao phủ toàn bộ bộ Precision Regex, kiểm tra ISO 6346, đa SĐT (`09..1 | 09..2`), trọng số thật `vinai/phobert-base-v2` (`phobert_transformers_local`), đối chiếu 6 nhánh `TH1`–`TH6`, cưỡng chế Chờ duyệt (`MANUAL`) cho cả lệnh kết hợp `RO + LO` lẫn lệnh trả đủ thông tin, cửa sổ đợi im lặng 20s/trần 60s cho nhóm Nhà xe (`GROUP_PROCESS_DELAY_SECONDS=20`, `GROUP_PROCESS_MAX_WAIT_SECONDS=60`) trong khi nhóm ĐHVT phản hồi ngay, container lạ báo song song ĐHVT & Nhà xe, gom tin + Danh thiếp Zalo, duyệt/sửa/hủy trực tiếp của ĐHVT trên Zalo (đúng 1 tin nhắn duy nhất kèm tên người duyệt), tách biệt thống kê ngày vs chi tiết lệnh theo tỉnh kèm tỷ lệ % đóng/mở và ảnh PNG bảng lệnh, gom thông báo quá hạn/ca duyệt theo chuẩn `[VSICO] - ...`, Watchdog Zalo OA và API `POST /api/sandbox/nlp-analyze`.

### Tài liệu Kiểm thử Postman

Toàn bộ hướng dẫn kiểm thử qua giao diện Postman được đặt tại [`backend/tests/postman/`](./tests/postman/README.md), gồm tài liệu `01` đến `17` và tệp collection import sẵn [`vsico_api_zalo_nlp_and_ux_v2.postman_collection.json`](./tests/postman/vsico_api_zalo_nlp_and_ux_v2.postman_collection.json).
