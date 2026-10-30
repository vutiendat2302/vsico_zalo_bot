# 🚚 NHAXE-BOT: HỆ THỐNG XỬ LÝ & ĐIỀU PHỐI TIN NHẮN NHÀ XE TỰ ĐỘNG

### DỰ ÁN TỰ ĐỘNG HÓA VẬN TẢI PM TMS - VSICO LOGISTICS (TASK 2)

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![ORM & DB](https://img.shields.io/badge/Database-SQLAlchemy%202.0%20%7C%20MySQL%208.4-4479A1.svg)](https://www.mysql.com/)
[![Migrations](https://img.shields.io/badge/Migrations-Alembic-red.svg)](https://alembic.sqlalchemy.org/)
[![Tests](https://img.shields.io/badge/Pytest-12%2F12%20PASS%20(100%25)-brightgreen.svg)](#9-kiểm-thử-tự-động--đo-lường-độ-chính-xác)

---

## 1. Giới thiệu & Bối cảnh nghiệp vụ

Trong quy trình vận hành chuỗi cung ứng container tại **VSICO**, các đơn vị vận tải (nhà xe) gửi thông tin điều động xe (biển số, tài xế, số điện thoại, số container, số seal, giờ đến) qua các nhóm **Zalo GMF / Zalo OA**.

Thực tế phát sinh nhiều thách thức:

- **Dữ liệu phi cấu trúc**: Tin nhắn gõ tự do, viết tắt, nhiều xe trong 1 tin, lỗi chính tả.
- **Thay đổi liên tục**: Nhà xe đổi tài xế đột xuất (chỉ báo biển số không kèm cont), hủy chuyến do xe hỏng, gửi bổ sung seal sau khi bốc cont.
- **Rủi ro sai lệch**: Sai số kiểm tra container (ISO 6346), nhà xe nhận cuốc nhưng báo sai container của đơn vị khác, tin nhắn gửi trùng lặp gây spam khách hàng.

**`nhaxe-bot`** là hệ thống backend xử lý trung tâm được xây dựng theo chuẩn **Clean Architecture**, đóng vai trò cầu nối tự động hóa giữa Zalo OA và phần mềm Quản lý Vận tải (TMS). Hệ thống tự động tiếp nhận webhook, thẩm định nghiệp vụ, đối chiếu kế hoạch vận chuyển (shipping order), quản lý phiên bản chuyến xe và kết xuất thông báo cho khách hàng hoặc gửi cảnh báo cho Điều hành Vận tải (ĐHVT).

---

## 2. Kiến trúc hệ thống

Hệ thống được thiết kế theo mô hình **Phân tầng hướng nghiệp vụ (Layered Architecture / Clean Architecture)**, đảm bảo nguyên tắc phụ thuộc một chiều từ ngoài vào trong:

```
[ Tầng Giao Tiếp (API) ]
  ├── Zalo Webhook Gateway (POST /webhook)
  └── TMS Functional REST APIs (POST/GET /api/trips/...)
           │
           ▼
[ Tầng Tiếp Nhận (Ingestion) ]
  ├── Signature Verification & Idempotency Filter (msg_id)
  └── Payload Normalizer (Zalo Raw -> InboundMessage)
           │
           ▼
[ Hàng Đợi Bất Đồng Bộ (Queue & Worker) ]
  └── In-Memory FIFO Queue (Cách ly I/O, phản hồi Webhook tức thì 200 OK)
           │
           ▼
[ Tầng Xử Lý Thông Điệp (Messaging & Classification) ]
  ├── Context Resolver (Group ID -> Đội xe & Người gửi)
  ├── Text Normalizer & Vehicle Block Segmenter (1 tin -> n xe)
  └── Hierarchical Intent Router (Cancel > Update > Supplement > Parse > Chat)
           │
           ▼
[ Tầng Nghiệp Vụ & Use Cases (Handlers & Domain Core) ]
  ├── Validation: ISO 6346 Check Digit Mod 11, Biển số, SĐT
  ├── Domain Matching: Khớp đơn vị vận chuyển & Shipping Plan
  ├── State & Versioning: Lưu chuyến, tra ngược biển số, tăng version (v1, v2)
  └── Outbound Responder: Soạn tin template theo khách hàng & Gửi cảnh báo Admin
```

### Nguyên tắc bất biến của kiến trúc:

1. **Phụ thuộc 1 chiều**: `api` $\rightarrow$ `handlers` $\rightarrow$ `domain` $\leftarrow$ `infrastructure`. Lõi `domain` không import bất kỳ thư viện HTTP hay bên ngoài nào.
2. **Cô lập Payload Zalo**: Dữ liệu thô của Zalo chỉ tồn tại trong `api/schemas` và `ingestion/normalizer.py`. Toàn bộ hệ thống bên trong chỉ làm việc với model nội bộ `InboundMessage`.
3. **Tách bạch 2 cổng API**:
   - **Zalo Webhook Gateway (`/webhook`)**: Cổng nhận sự kiện từ Zalo OA, xác thực chữ ký, chống trùng, đẩy vào Queue và ack ngay lập tức.
   - **TMS Functional REST APIs (`/api/trips/...`)**: Cổng REST API nghiệp vụ độc lập, phục vụ giao diện web/app TMS quản lý và tra cứu chuyến xe trực tiếp.

---

## 3. Cấu trúc thư mục chuẩn

```text
source/task2/
├── AGENTS.md                   # Quy chuẩn kiến trúc & quy tắc phát triển bắt buộc
├── .agent                      # File cấu hình tham chiếu chỉ dẫn cho AI Agent
├── pyproject.toml              # Cấu hình dự án, packaging, toolchain
├── Makefile                    # Phím tắt tự động hóa: run, test, evaluate, docker
├── Dockerfile                  # Container build chuẩn hóa
├── docker-compose.yml          # Triển khai dịch vụ containerized
├── .env.example                # File mẫu biến môi trường
├── README.md                   # Tài liệu hướng dẫn toàn diện
├── zalo.md                     # Đặc tả thiết kế luồng thông điệp Zalo (bất biến)
│
├── docs/                       # Tài liệu thiết kế hệ thống
│   ├── architecture.md         # Chi tiết kiến trúc phân tầng & pipeline
│   ├── intents.md              # Bảng phân loại intent & quy tắc xử lý xung đột
│   ├── report_zalo_task_2.md   # Báo cáo tổng kết nghiệp vụ Task 2
│   └── adr/                    # Architecture Decision Records
│       └── 0001-layered-architecture.md
│
├── src/              # Mã nguồn chính dự án
│   ├── __init__.py
│   ├── main.py                 # Dependency Injection wiring & CLI runner
│   │
│   ├── config/                 # Cấu hình hệ thống & Timezone GMT+7
│   │   └── settings.py
│   │
│   ├── api/                    # TẦNG GIAO TIẾP (HTTP Endpoints)
│   │   ├── app.py              # HTTP Handler phục vụ REST & Webhook
│   │   ├── webhook.py          # WebhookController: verify, ack, enqueue
│   │   ├── health.py           # HealthController: liveness & metrics
│   │   └── schemas/zalo.py     # Định nghĩa schema payload Zalo
│   │
│   ├── ingestion/              # TẦNG TIẾP NHẬN
│   │   ├── models.py           # InboundMessage (model dữ liệu nội bộ)
│   │   ├── normalizer.py       # Chuyển đổi Zalo Payload -> InboundMessage
│   │   ├── deduplicator.py     # Chống trùng lặp theo msg_id (Idempotency)
│   │   └── filters.py          # Lọc sự kiện không hỗ trợ & người gửi lạ
│   │
│   ├── messaging/              # TẦNG XỬ LÝ THÔNG ĐIỆP
│   │   ├── context.py          # ContextResolver: phân giải group -> nhà xe
│   │   ├── preprocess.py       # Chuẩn hóa khoảng trắng & ký tự
│   │   ├── segmenter.py        # Tách tin nhắn chứa nhiều xe (dấu gạch /)
│   │   ├── router.py           # IntentRouter định tuyến tới Handler
│   │   └── classifier/         # Bộ phân loại ý định
│   │       ├── base.py
│   │       ├── rule_based.py   # Regex & phân cấp ưu tiên xử lý xung đột
│   │       └── llm.py          # Dự phòng LLM cho ca đa nghĩa
│   │
│   ├── parsing/                # TẦNG TRÍCH XUẤT THÔNG TIN
│   │   ├── trip_parser.py      # Bộ bóc tách thông tin chuyến xe hoàn chỉnh
│   │   ├── llm_parser.py       # Fallback parser sử dụng LLM
│   │   └── fields/             # Regex & trích xuất từng trường chuyên biệt
│   │       ├── container.py    # Nhận diện số container
│   │       ├── plate.py        # Nhận diện biển số xe tải / đầu kéo
│   │       ├── phone.py        # Chuẩn hóa số điện thoại VN (+84, 0x)
│   │       └── datetime_parser.py # Chuẩn hóa giờ đến
│   │
│   ├── domain/                 # LÕI NGHIỆP VỤ THUẦN TÚY (Pure Domain)
│   │   ├── models.py           # Vehicle, SentTrip, ShippingOrder, Carrier
│   │   ├── enums.py            # Intent, TripStatus, SendStatus, MatchStatus
│   │   ├── rules.py            # Thuật toán ISO 6346 Mod 11, clean plate/phone
│   │   ├── errors.py           # Domain exceptions
│   │   └── matching/
│   │       └── trip_assigner.py # Khớp xe với đơn hàng vận chuyển (Shipping)
│   │
│   ├── handlers/               # TẦNG USE CASES (Mỗi Intent một file độc lập)
│   │   ├── base.py
│   │   ├── create_trip.py      # Xử lý báo xe mới -> Khớp shipping -> Soạn tin
│   │   ├── update_driver.py    # Xử lý đổi tài xế/biển số -> Tăng version (v2)
│   │   ├── cancel_trip.py      # Xử lý xin hủy chuyến -> Báo động Admin
│   │   ├── supplement.py       # Xử lý gửi bổ sung seal/giờ
│   │   └── unknown.py          # Xử lý chat thông thường / im lặng
│   │
│   ├── validation/             # BỘ KIỂM TRA TÍNH HỢP LỆ
│   │   └── validators.py       # Kiểm tra thiếu trường bắt buộc & cảnh báo
│   │
│   ├── infrastructure/         # TẦNG NGOẠI VI & DỮ LIỆU
│   │   ├── queue/              # Hàng đợi & Worker luồng nền
│   │   │   ├── publisher.py
│   │   │   └── worker.py
│   │   ├── repositories/       # Lưu trữ & truy xuất dữ liệu
│   │   │   ├── trip_repo.py    # In-memory Trip Repository & tra cứu ngược
│   │   │   └── shipping_repo.py # Đọc kế hoạch shipping từ CSV
│   │   ├── zalo/               # Client kết nối Zalo OA & xác thực chữ ký
│   │   │   ├── client.py
│   │   │   └── signature.py
│   │   └── llm/                # Adapter kết nối Ollama/vLLM
│   │       └── client.py
│   │
│   ├── outbound/               # TẦNG XUẤT BẢN & PHẢN HỒI
│   │   ├── responder.py        # Quyết định hành động gửi và nội dung
│   │   ├── templates.py        # Template engine render thông báo
│   │   └── templates/          # Mẫu thông báo (.txt)
│   │       ├── default_tra.txt
│   │       ├── default_nhap.txt
│   │       ├── default_capnhat.txt
│   │       └── customers/      # Mẫu tùy biến theo từng khách hàng
│   │
│   └── observability/          # TẦNG GIÁM SÁT & NHẬT KÝ
│       └── logging.py          # Structured JSON logging kèm `msg_id`
│
├── tests/                      # BỘ KIỂM THỬ TỰ ĐỘNG & TEST CASE CHI TIẾT
│   ├── unit/                   # Unit test: rules, classifier, normalizer
│   │   ├── test_rules.py
│   │   ├── test_classifier.py
│   │   └── test_normalizer.py
│   ├── integration/            # Integration test: pipeline e2e, webhook api
│   │   ├── test_pipeline_e2e.py
│   │   └── test_webhook_api.py
│   ├── postman/                # ĐẶC TẢ CHI TIẾT CÁC TEST POSTMAN (MARKDOWN)
│   │   ├── README.md           # Hướng dẫn thiết lập & danh mục kịch bản
│   │   ├── 01_kiem_tra_suc_khoe_server.md
│   │   ├── 02_tao_chuyen_xe_tms.md
│   │   ├── 03_doi_tai_xe_theo_bien_so.md
│   │   ├── 04_bo_sung_seal_gio_den.md
│   │   ├── 05_huy_chuyen_xe.md
│   │   ├── 06_tra_cuu_danh_sach_va_chi_tiet_chuyen.md
│   │   ├── 07_webhook_bao_xe_chuan.md
│   │   ├── 08_webhook_bao_nhieu_xe_mot_tin.md
│   │   ├── 09_webhook_chong_trung_lap.md
│   │   ├── 10_webhook_thieu_seal_phan_hoi_nha_xe.md
│   │   ├── 11_webhook_sai_nha_xe_canh_bao_admin.md
│   │   └── 12_webhook_loc_tin_nhan_rac_va_nguoi_la.md
│   └── fixtures/               # Dữ liệu mẫu chuẩn benchmark
│       ├── messages/nhaxe_messages_demo.txt
│       └── shipping/nhaxe_shipping_demo.csv
│
├── scripts/
│   ├── manage_db.py            # Tiện ích quản lý, thống kê và dọn dẹp cơ sở dữ liệu MySQL
│   └── run_txt_tests.py        # Runner tự động kiểm thử toàn bộ các tệp TXT fixtures
├── migrations/                 # Alembic Database Migrations
│   ├── env.py                  # Cấu hình môi trường kết nối SQLAlchemy & MySQL
│   └── versions/               # Lịch sử các phiên bản migration
└── tests/postman/              # Đặc tả chi tiết các bài test Postman bằng Markdown (.md)
```

---

## 4. Yêu cầu môi trường & Cài đặt

Hệ thống backend được xây dựng trên nền tảng **Python 3.10+**, **FastAPI**, **SQLAlchemy 2.0** và cơ sở dữ liệu **MySQL 8.4**:

- **Python**: Phiên bản `3.10` trở lên (Khuyên dùng Python 3.12).
- **Cơ sở dữ liệu**: MySQL 8.4 (khởi chạy nhanh qua Docker Compose hoặc kết nối máy chủ MySQL có sẵn).
- **Quản lý gói phụ thuộc**: Sử dụng `pip` hoặc `uv` với tệp chuẩn `pyproject.toml`.

### Khởi tạo môi trường ảo & Cài đặt dependencies:

```bash
# 1. Tạo môi trường ảo
python3 -m venv .venv
source .venv/bin/activate

# 2. Cài đặt các gói phụ thuộc
pip install -e .
```

### Cấu hình biến môi trường (`.env`):

Tạo file `.env` từ file mẫu `.env.example`:

```bash
cp .env.example .env
```

Nội dung file cấu hình chính:

```ini
# 1. Cấu hình máy chủ ứng dụng (Server Settings)
APP_ENV=development
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO

# 2. Kết nối cơ sở dữ liệu MySQL 8.4 (Database Settings)
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=123456
DB_NAME=vsico_zalo_bot
DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3306/vsico_zalo_bot?charset=utf8mb4

# 3. Bảo mật Webhook Zalo (Zalo Webhook Settings)
ZALO_APP_ID=zca_personal_bot
ZALO_SECRET_KEY=

# 4. Cấu hình AI Fallback (Gemini / OpenAI Compatible)
AI_ENABLED=true
AI_PROVIDER=gemini
AI_API_KEY=your_gemini_or_openai_api_key_here
AI_MODEL_NAME=gemini-2.5-flash
AI_TIMEOUT_SECONDS=10
AI_FALLBACK_CONFIDENCE_THRESHOLD=0.65
```

---

## 5. Hướng dẫn vận hành & Khởi chạy chi tiết

Hệ thống cung cấp đa dạng phương thức vận hành phục vụ từ quá trình phát triển (Local Development), kiểm thử tương tác (Interactive Simulation), đo lường độ chính xác (Benchmark Evaluation), đến triển khai sản xuất (Docker Deployment).

---

### 5.1. Bảng phím tắt thao tác nhanh qua Makefile

Hệ thống tích hợp sẵn `Makefile` chuẩn hóa toàn bộ các tác vụ vận hành thường gặp:

| Lệnh Makefile | Lệnh thực thi tương đương | Chức năng nghiệp vụ |
| :--- | :--- | :--- |
| **`make run`** | `python run.py` | Khởi chạy FastAPI Webhook & TMS REST API (Cổng 8000) |
| **`make test`** | `pytest tests -v` | Chạy toàn bộ 12 test suite tự động bằng Pytest |
| **`make test-txt`** | `python scripts/run_txt_tests.py --all` | Chạy kiểm thử toàn bộ 21 tệp input TXT fixtures |
| **`make db-up`** | `docker compose up -d mysql` | Khởi động container MySQL 8.4 ngầm bằng Docker Compose |
| **`make db-down`** | `docker compose stop mysql` | Tạm dừng container MySQL |
| **`make db-check`** | `python scripts/manage_db.py check` | Kiểm tra kết nối MySQL và phiên bản Alembic hiện tại |
| **`make db-status`** | `python scripts/manage_db.py status` | Thống kê chi tiết số lượng bản ghi của toàn bộ 17 bảng |
| **`make db-migrate`** | `alembic upgrade head` | Áp dụng toàn bộ migration Alembic lên bản mới nhất (HEAD) |
| **`make db-shell`** | `docker exec -it vsico-zalo-mysql mysql...` | Mở MySQL Interactive Shell bên trong container |
| **`make db-clean`** | `python scripts/manage_db.py clean --runtime -y` | Dọn dẹp dữ liệu tin nhắn/xe/cont runtime (**GIỮ master data & plans**) |
| **`make db-clean-tests`** | `python scripts/manage_db.py clean --tests` | Dọn dẹp chỉ các bản ghi kiểm thử tự động (`pytest_*`, `test_*`) |
| **`make db-clean-plans`** | `python scripts/manage_db.py clean --plans -y` | Dọn dẹp riêng bảng kế hoạch vận chuyển (`transport_plans`) |
| **`make db-clean-all`** | `python scripts/manage_db.py clean --all -y` | Dọn dẹp **TRẮNG toàn bộ 17 bảng** trong database (giữ cấu trúc) |
| **`make db-reset`** | `python scripts/manage_db.py reset -y` | Reset toàn bộ DB (Drop tables & chạy lại migrations) |
| **`make docker-up`** | `docker compose up -d` | Khởi chạy dịch vụ container hóa chạy ngầm |
| **`make docker-down`** | `docker compose down` | Dừng và thu hồi tài nguyên container |

---

### 5.2. Chế độ 1: Khởi chạy máy chủ HTTP Server (API Gateway & TMS REST)

Máy chủ HTTP tích hợp phục vụ đồng thời 2 luồng: **Zalo Webhook Gateway** tiếp nhận sự kiện thô từ Zalo OA và **TMS Functional REST API** phục vụ giao diện điều hành.

#### Cách 1: Khởi chạy qua Makefile (Khuyên dùng)

```bash
make run
```

#### Cách 2: Khởi chạy trực tiếp qua launcher `run.py` (Đơn giản nhất)

```bash
# 1. Khởi chạy cổng mặc định 8000
python3 run.py

# 2. Khởi chạy tùy chọn cổng khác (ví dụ: cổng 9000)
python3 run.py --port 9000

# 3. Khởi chạy với file kế hoạch Shipping tùy chọn
python3 run.py --port 8000 --shipping /path/to/custom_shipping.csv
```

#### Cách 3: Khởi chạy dạng module Python

```bash
PYTHONPATH=src python3 -m nhaxe_bot.main --serve --port 8000
```

#### Giao diện bàn điều khiển khi khởi động thành công:

```text
+-----------------------------------------------------------------------------+
| NHAXE-BOT SERVER (VSICO TMS) - LISTENING ON PORT 8000                       |
+--------+------------------------------------+-------------------------------+
| METHOD | ENDPOINT                           | CHỨC NĂNG NGHIỆP VỤ           |
+--------+------------------------------------+-------------------------------+
| POST   | /webhook                           | Zalo Webhook Gateway          |
| POST   | /api/trips/new                     | Tạo chuyến xe mới (TMS REST)  |
| POST   | /api/trips/update-driver           | Đổi tài xế / số điện thoại    |
| POST   | /api/trips/supplement              | Bổ sung số seal / giờ đến     |
| POST   | /api/trips/cancel                  | Gửi yêu cầu hủy chuyến xe     |
| GET    | /api/trips                         | Tra cứu danh sách chuyến xe   |
| GET    | /api/shipping                      | Tra cứu danh mục shipping     |
| POST   | /api/shipping/mock-mode            | Bật/tắt Auto-Mock Shipping    |
| POST   | /api/shipping/new                  | Tạo đơn shipping động         |
| GET    | /api/health                        | Health check & Service metrics|
+--------+------------------------------------+-------------------------------+
[INFO] Server sẵn sàng nhận kết nối tại: http://localhost:8000
```

#### Kiểm tra trạng thái máy chủ (Health Check):

Mở một cửa sổ Terminal mới và chạy:

```bash
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

Kết quả phản hồi mẫu:

```json
{
  "status": "UP",
  "app_name": "nhaxe-bot",
  "version": "1.0.0",
  "metrics": {
    "trips_count": 0,
    "shipping_orders_count": 27,
    "auto_mock_shipping": false
  }
}
```

---

### 5.3. Chế độ 2: Công cụ mô phỏng & Thử nghiệm trực tiếp (`scripts/simulator.py`)

Công cụ **Simulator CLI** được thiết kế đặc biệt nhằm giúp BA và Lập trình viên chủ động thử nghiệm mọi cú pháp tin nhắn điều xe phức tạp mà **không cần khởi động server HTTP hay mở Postman**.

> [!TIP]
> **Tính năng Auto-Mock Shipping**: Simulator mặc định kích hoạt tính năng tự động sinh đơn hàng vận chuyển giả lập cho bất kỳ số container nào (ngay cả cont chưa có trong file CSV). Nhờ đó, bạn hoàn toàn chủ động thử nghiệm với số cont mới bất kỳ mà không bị chặn bởi lỗi thiếu kế hoạch shipping.

#### 1. Thử nghiệm nhanh một tin nhắn qua dòng lệnh (One-shot Mode):

```bash
# Ví dụ 1: Tin nhắn viết dính liền biển số và họ tên gõ thiếu dấu cách
python3 scripts/simulator.py --text "Xe15h00814/phạm tiếnhưng/0332308336/GAOU6422920/ kho win yên mỹ"

# Ví dụ 2: Báo xe có đầy đủ biển số, số seal và giờ đến
python3 scripts/simulator.py --text "TRẢ HÀNG 14/10 9h VSIU7399796 Seal: 73957169 Xe: 15C-878.99 TX: Trần Quốc Bảo 0903976359"

# Ví dụ 3: Đổi nhà xe gửi tin (NX02, NX03, NX04) để kiểm tra khớp quyền vận chuyển
python3 scripts/simulator.py --carrier NX02 --text "BKS 29C-123.45 / Lái xe: Nguyễn Văn Khoa 0903976359 / TCNU9951145"

# Ví dụ 4: Tắt Auto-Mock Shipping (chỉ nhận cont thực tế có trong file CSV)
python3 scripts/simulator.py --no-mock --text "Xe 15C-878.99 cont VSIU7399796 tài xế Bảo 0903976359"
```

#### Giao diện hiển thị Pipeline Inspector Trace chi tiết từ Simulator:

```text
  [INGEST  ] Bắt đầu xử lý tin seq 1 (msg_id=sim_0001)
  [CLASSIFY] Nhận diện Intent: PARSE
  [RESULT  ] Hoàn tất xử lý (1 kết quả)

+-----------------------------------------------------------------------------+
| PIPELINE INSPECTOR TRACE (THEO DÕI LUỒNG BÓC TÁCH CHI TIẾT)                 |
+-----------------------------------------------------------------------------+
  [INPUT ] Tin nhắn gốc : 'Xe15h00814/phạm tiếnhưng/0332308336/GAOU6422920/ kho win yên mỹ'
  [CONFIG] Đội xe gửi   : NX01
  [CONFIG] Auto-Mock    : BẬT (Tự tạo shipping nếu cont chưa có)
+-----------------------------------------------------------------------------+

  [KẾT QUẢ 1] Phân loại hành động: PARSE
    - Container       : GAOU6422920 [HỢP LỆ ISO 6346]
    - Số Seal/Chì     : Trống
    - Biển số xe      : 15H00814
    - Tài xế          : Phạm Tiến Hưng
    - Số điện thoại   : 0332308336
    - Giờ đến dự kiến : Trống
    - Trạng thái gửi  : HOLD_WAIT_SUPPLEMENT
    - Cảnh báo        : thieu_gio_den, thieu_seal
    - Phản hồi nhà xe : Chuyến cont GAOU6422920 còn thiếu: số seal/chì, giờ đến. Vui lòng bổ sung!
+-----------------------------------------------------------------------------+
```

#### 2. Chế độ tương tác thời gian thực (Interactive CLI REPL):

Khởi động phiên làm việc tương tác:

```bash
make simulate
# Hoặc: python3 scripts/simulator.py
```

Trong môi trường này, bạn có thể gõ trực tiếp từng tin nhắn để kiểm tra, kèm các lệnh điều khiển nhanh:

- `carrier <MÃ_NX>`: Đổi đội xe gửi tin (ví dụ: `carrier NX02`, `carrier NX03`).
- `mock on` / `mock off`: Bật hoặc tắt tính năng Auto-Mock Shipping.
- `trips`: Hiển thị danh mục toàn bộ các chuyến xe đã được bóc tách và lưu trong phiên.
- `clear`: Xóa màn hình Terminal.
- `exit` hoặc `quit` hoặc `q`: Thoát khỏi chế độ mô phỏng.

---

### 5.4. Chế độ 3: Đo lường độ chính xác Benchmark (`scripts/evaluate.py`)

Chạy đánh giá tự động toàn bộ 57 sự kiện Webhook mẫu và 60 container từ tập dữ liệu thực tế [`nhaxe_messages_demo.txt`](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/fixtures/messages/nhaxe_messages_demo.txt):

```bash
# 1. Chạy đánh giá cơ bản và in báo cáo ra Terminal
make evaluate
# Hoặc: python3 scripts/evaluate.py

# 2. Xuất bảng dữ liệu kết quả phân tích chi tiết ra tệp CSV (chuẩn UTF-8 BOM):
python3 scripts/evaluate.py --output output/results.csv

# 3. Kích hoạt dự phòng LLM Fallback (khi có máy chủ Ollama/vLLM cấu hình trong .env):
python3 scripts/evaluate.py --use-llm
```

---

### 5.5. Chế độ 4: Chạy bộ kiểm thử tự động toàn diện (Test Suite)

Hệ thống sở hữu bộ kiểm thử tự động 31 bài test (Unit & Integration tests) bao phủ 100% các Use Case và quy tắc nghiệp vụ:

```bash
# 1. Chạy toàn bộ 31 bài kiểm thử tự động (PASS 100%)
make test
# Hoặc: python3 -m unittest discover tests -v

# 2. Chỉ chạy nhóm Unit Tests (Domain rules, classifier, trip parser, normalizer):
python3 -m unittest discover tests/unit -v

# 3. Chỉ chạy nhóm Integration Tests (Pipeline E2E, Webhook Gateway & REST API):
python3 -m unittest discover tests/integration -v

# 4. Chạy kiểm thử cho một tệp cụ thể (ví dụ: bóc tách biển số & tên tài xế):
python3 -m unittest tests/unit/test_trip_parser.py -v
```

---

### 5.6. Chế độ 5: Triển khai với Docker & Docker Compose

Dành cho môi trường staging, kiểm thử tải hoặc triển khai trên máy chủ đám mây/nội bộ:

```bash
# 1. Đóng gói Docker Image ứng dụng
make docker-build
# Hoặc: docker build -t nhaxe-bot:latest .

# 2. Khởi chạy container ngầm bằng Docker Compose
make docker-up
# Hoặc: docker compose up -d

# 3. Xem nhật ký hoạt động theo thời gian thực (Live Logs)
docker compose logs -f nhaxe-bot

# 4. Kiểm tra sức khỏe dịch vụ bên trong container
curl -s http://localhost:8000/api/health | python3 -m json.tool

# 5. Dừng và giải phóng tài nguyên container
make docker-down
# Hoặc: docker compose down
```

---

### 5.7. Hướng dẫn thử nghiệm nhanh API bằng `curl`

Khi máy chủ đang chạy (`make run`), bạn có thể mở một Terminal khác và sao chép các lệnh `curl` dưới đây để kiểm thử trực tiếp:

#### 1. Tạo chuyến xe mới qua REST API (Giao diện TMS):

```bash
curl -X POST http://localhost:8000/api/trips/new \
  -H "Content-Type: application/json" \
  -d '{
    "cont": "GAOU6422920",
    "bien_so": "15H00814",
    "tai_xe": "Phạm Tiến Hưng",
    "sdt": "0332308336",
    "seal": "SL889900",
    "gio_den": "14h30",
    "carrier_id": "NX01"
  }'
```

#### 2. Gửi tin nhắn điều xe thô qua Zalo Webhook Gateway:

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "user_send_text",
    "app_id": "1234567890123456789",
    "sender": {"id": "1001000000000000001"},
    "recipient": {"id": "2001000000000000001"},
    "message": {
      "msg_id": "curl_demo_msg_001",
      "text": "Xe15h00814/phạm tiếnhưng/0332308336/GAOU6422920/ kho win yên mỹ"
    },
    "timestamp": 1728950400000
  }'
```

#### 3. Bật chế độ Auto-Mock Shipping qua API:

```bash
curl -X POST http://localhost:8000/api/shipping/mock-mode \
  -H "Content-Type: application/json" \
  -d '{"auto_mock": true}'
```

#### 4. Tra cứu chi tiết một chuyến xe theo số Container:

```bash
curl -s http://localhost:8000/api/trips/GAOU6422920 | python3 -m json.tool
```

#### 5. Đổi tài xế cho chuyến xe vừa tạo (Version tự động tăng lên Version 2):

```bash
curl -X POST http://localhost:8000/api/trips/update-driver \
  -H "Content-Type: application/json" \
  -d '{
    "carrier_id": "NX01",
    "bien_so": "15H00814",
    "tai_xe_moi": "Vũ Đạt",
    "sdt_moi": "0912345678"
  }'
```

---

## 6. Hướng Dẫn Quản Lý & Xử Lý Cơ Sở Dữ Liệu MySQL (Database Operations & Maintenance)

Cơ sở dữ liệu của dự án sử dụng **MySQL 8.4** kết hợp **SQLAlchemy 2.0 ORM** và **Alembic Database Migrations**. Toàn bộ hệ thống quản lý 17 bảng được thiết kế phân tầng hướng nghiệp vụ chặt chẽ, đảm bảo tính toàn vẹn dữ liệu, truy vết đầy đủ và hiệu năng cao.

---

### 6.1. Bảng phân loại 17 bảng trong Cơ Sở Dữ Liệu MySQL

Dữ liệu được tổ chức thành 3 nhóm nghiệp vụ chính:

| Nhóm dữ liệu | Tên bảng (Table Name) | Mô tả vai trò nghiệp vụ | Cơ chế dọn dẹp an toàn |
| :--- | :--- | :--- | :--- |
| **1. Runtime / Nghiệp vụ** | `zalo_messages` | Tin nhắn thô nguyên bản nhận từ Zalo OA Webhook | Xóa khi cần làm sạch môi trường test |
| | `extraction_runs` | Lịch sử các phiên bóc tách (AI / Rule-based) | Xóa khi cần làm sạch môi trường test |
| | `truck_records` | Lượt xe được trích xuất (Biển số, Mooc, Lái xe, SĐT) | Xóa khi cần làm sạch môi trường test |
| | `container_jobs` | Quản lý từng Container (Trạng thái validation, routing, TMS) | Xóa khi cần làm sạch môi trường test |
| | `review_cases` | Hàng đợi duyệt thủ công dành cho Điều hành Vận tải (ĐHVT) | Xóa khi cần làm sạch môi trường test |
| | `bot_replies` | Lịch sử tin bot phản hồi nhà xe nhắc lỗi & hạn sửa 30 phút | Xóa khi cần làm sạch môi trường test |
| | `outbound_messages` | Tin nhắn thông báo điều xe gửi tới nhóm Zalo khách hàng | Xóa khi cần làm sạch môi trường test |
| | `outbound_message_items` | Bảng trung gian liên kết Container vào tin outbound | Xóa khi cần làm sạch môi trường test |
| | `tms_sync_logs` | Nhật ký chi tiết mọi cuộc gọi API đồng bộ sang `be-tms` | Xóa khi cần làm sạch môi trường test |
| | `activity_logs` | Nhật ký thao tác người dùng và sự kiện hệ thống | Xóa khi cần làm sạch môi trường test |
| **2. Kế hoạch vận chuyển** | `transport_plans` | Kế hoạch điều vận hằng ngày (nạp từ file Excel / CSV hoặc API) | Xóa theo ngày hoặc ghi đè khi import mới |
| **3. Master / Danh mục** | `customers` | Danh mục khách hàng chuẩn đồng bộ từ TMS | Bảo toàn dữ liệu (Không xóa khi dọn runtime) |
| | `warehouses` | Danh mục kho đóng/trả hàng chuẩn đồng bộ từ TMS | Bảo toàn dữ liệu (Không xóa khi dọn runtime) |
| | `customer_aliases` | Tên gọi tắt / bí danh của khách hàng | Bảo toàn dữ liệu (Không xóa khi dọn runtime) |
| | `warehouse_aliases` | Tên gọi tắt / bí danh của kho hàng | Bảo toàn dữ liệu (Không xóa khi dọn runtime) |
| | `route_maps` | Bảng ánh xạ: Khách hàng + Kho + Loại lệnh -> Nhóm Zalo nhận tin | Bảo toàn dữ liệu (Không xóa khi dọn runtime) |
| | `zalo_groups` | Danh mục nhóm Zalo (Nhóm nhà xe, Nhóm khách, Nhóm nội bộ) | Bảo toàn dữ liệu (Không xóa khi dọn runtime) |
| **Hệ thống Migration** | `alembic_version` | Quản lý mã revision migration hiện tại của Alembic | **Tuyệt đối KHÔNG xóa** khi clean dữ liệu |

---

### 6.2. Hướng dẫn các phương pháp Dọn Dẹp Cơ Sở Dữ Liệu (Clean DB)

Khi vận hành thực tế hoặc chạy các bộ kiểm thử tự động, dữ liệu tin nhắn rác, xe thử nghiệm sẽ sinh ra trong database. Dự án cung cấp **5 phương thức dọn dẹp** từ đơn giản đến chuyên sâu:

#### 🟢 Phương Án 1: Dọn dẹp nhanh qua Makefile (Khuyên dùng cho Developer)

Hệ thống đã tích hợp sẵn các phím tắt dọn dẹp an toàn:

```bash
# 1. Kiểm tra thống kê số lượng bản ghi của 17 bảng trước khi dọn
make db-status

# 2. DỌN SẠCH DỮ LIỆU RUNTIME (Khuyên dùng nhất):
# Xóa sạch tin nhắn, xe, cont, logs, review_cases...
# BẢO TOÀN NGUYÊN VẸN Danh mục (Khách hàng, Kho, Nhóm) và Kế hoạch vận chuyển (Plans)!
make db-clean

# 3. Chỉ dọn các bản ghi kiểm thử tự động (tiền tố pytest_*, test_*, mock_*):
make db-clean-tests

# 4. Chỉ dọn dẹp bảng kế hoạch vận chuyển (transport_plans):
make db-clean-plans

# 5. DỌN TRẮNG TOÀN BỘ 17 BẢNG TRONG DATABASE (Cân nhắc khi dùng):
# Truncate toàn bộ dữ liệu nhưng giữ nguyên cấu trúc bảng và lịch sử migration.
make db-clean-all

# 6. RESET TOÀN BỘ DATABASE VỀ TRẠNG THÁI KHỞI TẠO BAN ĐẦU:
# Xóa sạch các bảng và chạy lại Alembic migrations lên bản mới nhất.
make db-reset
```

#### 🟡 Phương Án 2: Sử dụng Script Quản trị CLI chuyên dụng (`scripts/manage_db.py`)

File script `scripts/manage_db.py` cung cấp giao diện dòng lệnh linh hoạt với cờ xác nhận `-y` / `--yes`:

```bash
# 1. Kiểm tra kết nối DB và phiên bản máy chủ:
python scripts/manage_db.py check

# 2. Xem thống kê chi tiết 17 bảng:
python scripts/manage_db.py status

# 3. Xuất thống kê dạng JSON (tiện cho việc tích hợp CI/CD):
python scripts/manage_db.py status --json

# 4. Dọn dữ liệu runtime (yêu cầu xác nhận hoặc thêm -y để chạy ngay):
python scripts/manage_db.py clean --runtime -y

# 5. Dọn chỉ các bản ghi test:
python scripts/manage_db.py clean --tests

# 6. Dọn dẹp kế hoạch vận chuyển:
python scripts/manage_db.py clean --plans -y

# 7. Dọn trắng toàn bộ bảng:
python scripts/manage_db.py clean --all -y

# 8. Reset toàn bộ schema và áp dụng migration:
python scripts/manage_db.py reset -y
```

#### 🔵 Phương Án 3: Dọn dẹp Kế hoạch Vận Chuyển qua REST API (Dành cho TMS & Postman)

Khi cần xóa hoặc nạp lại kế hoạch của một ngày cụ thể từ phần mềm quản lý hoặc Postman:

- **Xóa kế hoạch của một ngày cụ thể**:
  ```bash
  curl -X DELETE "http://localhost:8000/api/plans/by-date/2026-10-12"
  ```
- **Xóa một bản ghi kế hoạch theo ID**:
  ```bash
  curl -X DELETE "http://localhost:8000/api/plans/1"
  ```
- **Tự động xóa và ghi đè kế hoạch cũ khi nạp file Excel mới**:
  ```bash
  curl -X POST "http://localhost:8000/api/plans/import-excel?replace_existing=true" \
    -F "file=@tests/data_test/ketnoi.xlsx"
  ```

#### 🟣 Phương Án 4: Dọn dẹp bằng câu lệnh SQL trực tiếp (MySQL Client / DBeaver / Navicat)

> [!CAUTION]
> Do giữa các bảng có ràng buộc khóa ngoại (Foreign Keys), lệnh `TRUNCATE TABLE` mặc định sẽ bị MySQL chặn nếu không tạm thời tắt kiểm tra khóa ngoại. Hãy luôn chạy kèm cặp lệnh `SET FOREIGN_KEY_CHECKS`:

```sql
-- Bước 1: Tạm thời tắt kiểm tra ràng buộc khóa ngoại
SET FOREIGN_KEY_CHECKS = 0;

-- Bước 2: Dọn dẹp dữ liệu nghiệp vụ / runtime (Tin nhắn, xe, cont, logs)
TRUNCATE TABLE `outbound_message_items`;
TRUNCATE TABLE `outbound_messages`;
TRUNCATE TABLE `bot_replies`;
TRUNCATE TABLE `review_cases`;
TRUNCATE TABLE `tms_sync_logs`;
TRUNCATE TABLE `activity_logs`;
TRUNCATE TABLE `container_jobs`;
TRUNCATE TABLE `truck_records`;
TRUNCATE TABLE `extraction_runs`;
TRUNCATE TABLE `zalo_messages`;

-- Bước 3: (Tùy chọn) Dọn dẹp kế hoạch vận chuyển
-- TRUNCATE TABLE `transport_plans`;

-- Bước 4: (Tùy chọn) Dọn dẹp danh mục master data nếu cần trắng tinh
-- TRUNCATE TABLE `route_maps`;
-- TRUNCATE TABLE `warehouse_aliases`;
-- TRUNCATE TABLE `customer_aliases`;
-- TRUNCATE TABLE `warehouses`;
-- TRUNCATE TABLE `customers`;
-- TRUNCATE TABLE `zalo_groups`;

-- Bước 5: BẬT LẠI kiểm tra ràng buộc khóa ngoại (BẮT BUỘC)
SET FOREIGN_KEY_CHECKS = 1;
```

#### 🔴 Phương Án 5: Khởi tạo lại hoàn toàn qua Docker Volume (Fresh Start)

Trong trường hợp dữ liệu bị xung đột nghiêm trọng hoặc cần kiểm thử cài đặt từ con số 0:

```bash
# 1. Dừng container và xóa bỏ hoàn toàn Docker Volume lưu trữ dữ liệu MySQL
docker compose down -v

# 2. Khởi động lại container MySQL mới tinh
docker compose up -d mysql

# 3. Đợi 5-10 giây để MySQL hoàn tất khởi tạo ban đầu, sau đó áp dụng Migrations
sleep 5
make db-migrate
# Hoặc: alembic upgrade head

# 4. Kiểm tra lại trạng thái
make db-status
```

---

### 6.3. Bảng Tổng Hợp Các Câu Lệnh Quan Trọng Xử Lý Database

Bảng dưới đây tổng hợp tất cả các câu lệnh thao tác với cơ sở dữ liệu thường dùng trong quá trình phát triển và vận hành hệ thống:

#### 1. Quản trị Container MySQL (Docker)

| Lệnh | Chức năng chi tiết |
| :--- | :--- |
| `make db-up` hoặc `docker compose up -d mysql` | Khởi chạy container MySQL 8.4 ngầm |
| `make db-down` hoặc `docker compose stop mysql` | Tạm dừng container MySQL |
| `docker compose restart mysql` | Khởi động lại dịch vụ MySQL |
| `docker compose logs -f mysql` | Xem nhật ký hoạt động thời gian thực của MySQL Server |
| `make db-shell` | Mở MySQL Interactive Shell trực tiếp bên trong container |
| `docker exec -it vsico-zalo-mysql mysql -u root -p123456 vsico_zalo_bot` | Đăng nhập thẳng vào schema `vsico_zalo_bot` |

#### 2. Quản lý Phiên Bản Schema & Migrations (Alembic)

| Lệnh | Chức năng chi tiết |
| :--- | :--- |
| `alembic current` | Xem mã revision migration hiện tại đang áp dụng trên database |
| `alembic history --verbose` | Xem toàn bộ lịch sử các bản migrations theo thứ tự thời gian |
| `make db-migrate` hoặc `alembic upgrade head` | Nâng cấp cấu trúc database lên phiên bản mới nhất (HEAD) |
| `alembic downgrade -1` | Lùi lại 1 phiên bản migration gần nhất (Rollback) |
| `alembic downgrade base` | Lùi về điểm khởi đầu (Xóa toàn bộ schema của alembic) |
| `alembic revision --autogenerate -m "mo_ta"` | Tự động phát hiện thay đổi trong `src/infrastructure/models.py` và sinh file migration mới |
| `alembic stamp head` | Đánh dấu database đang ở HEAD mà không chạy lệnh DDL (Dùng sửa lỗi lệch desync) |

#### 3. Kiểm Tra Kết Nối & Sức Khỏe Cơ Sở Dữ Liệu

| Lệnh | Chức năng chi tiết |
| :--- | :--- |
| `make db-check` | Kiểm tra trạng thái kết nối MySQL, host, database name và revision Alembic |
| `make db-status` | Xuất bảng thống kê số dòng hiện có trong từng bảng |
| `curl -s http://localhost:8000/api/health \| jq .` | Kiểm tra kết nối DB và bộ đếm bản ghi qua API Health Check |

#### 4. Sao Lưu (Backup) & Phục Hồi (Restore) Dữ Liệu

| Lệnh | Chức năng chi tiết |
| :--- | :--- |
| `docker exec -i vsico-zalo-mysql mysqldump -u root -p123456 vsico_zalo_bot > backup_vsico_$(date +%Y%m%d_%H%M%S).sql` | Xuất toàn bộ dữ liệu và cấu trúc ra file `.sql` sao lưu |
| `docker exec -i vsico-zalo-mysql mysqldump -u root -p123456 --no-data vsico_zalo_bot > schema_only.sql` | Chỉ sao lưu cấu trúc bảng (không kèm dữ liệu) |
| `docker exec -i vsico-zalo-mysql mysql -u root -p123456 vsico_zalo_bot < backup_file.sql` | Phục hồi toàn bộ dữ liệu từ file sao lưu `.sql` |

#### 5. Các Câu Lệnh SQL Hữu Ích Thường Dùng Khi Giám Sát & Vận Hành

Truy cập MySQL qua `make db-shell` và sử dụng các câu lệnh nhanh:

```sql
-- 1. Xem 5 tin nhắn Zalo nhận gần đây nhất
SELECT id, zalo_message_id, group_id, sender_name, processing_status, received_at 
FROM zalo_messages 
ORDER BY id DESC LIMIT 5;

-- 2. Xem chi tiết các container vừa được bóc tách
SELECT id, message_id, container_no, seal_no, validation_status, routing_status, created_at 
FROM container_jobs 
ORDER BY id DESC LIMIT 10;

-- 3. Xem danh sách các trường hợp đang chờ Điều hành Vận tải duyệt (Pending Review)
SELECT id, message_id, case_type, reason, status, created_at 
FROM review_cases 
WHERE status = 'pending';

-- 4. Thống kê số lượng container theo từng trạng thái kiểm tra (Validation Status)
SELECT validation_status, COUNT(*) AS total 
FROM container_jobs 
GROUP BY validation_status;

-- 5. Xem danh sách lượt xe và tài xế trích xuất gần nhất
SELECT id, truck_plate, trailer_plate, driver_name, driver_phone, created_at 
FROM truck_records 
ORDER BY id DESC LIMIT 5;
```

---

## 7. Danh mục API & Hướng dẫn kiểm thử Postman

Hệ thống phân định 2 nhóm cổng giao tiếp độc lập, đảm bảo tính bảo mật và khả năng mở rộng:

| Nhóm Cổng                    | Phương thức | Đường dẫn (Endpoint)     | Chức năng nghiệp vụ chính                                             |
| ------------------------------ | :------------: | ---------------------------- | -------------------------------------------------------------------------- |
| **TMS Functional API**   |    `GET`    | `/api/health`              | Kiểm tra trạng thái máy chủ, số tin đã xử lý & metrics           |
| **TMS Functional API**   |    `POST`    | `/api/trips/new`           | Tạo chuyến xe mới có cấu trúc từ phần mềm TMS                     |
| **TMS Functional API**   |    `POST`    | `/api/trips/update-driver` | Đổi tài xế (tra cứu ngược qua biển số xe, nâng lên Version 2)   |
| **TMS Functional API**   |    `POST`    | `/api/trips/supplement`    | Bổ sung số seal và giờ đến cho chuyến đang chờ                    |
| **TMS Functional API**   |    `POST`    | `/api/trips/cancel`        | Gửi yêu cầu hủy chuyến & kích hoạt chuông cảnh báo Admin         |
| **TMS Functional API**   |    `GET`    | `/api/trips`               | Truy vấn danh sách toàn bộ chuyến xe trong bộ nhớ                   |
| **TMS Functional API**   |    `GET`    | `/api/trips/{cont}`        | Tra cứu chi tiết một chuyến xe theo số container                      |
| **TMS Functional API**   |    `POST`    | `/api/shipping/mock-mode`  | Bật/tắt chế độ Auto-Mock Shipping (tự sinh đơn cho mọi cont mới) |
| **TMS Functional API**   |    `POST`    | `/api/shipping/new`        | Nạp hoặc tạo trực tiếp một đơn kế hoạch shipping mới            |
| **TMS Functional API**   |    `GET`    | `/api/shipping`            | Xem danh mục kế hoạch shipping và trạng thái auto-mock               |
| **Zalo Webhook Gateway** |    `POST`    | `/webhook`                 | Cổng tiếp nhận sự kiện webhook tin nhắn thô từ Zalo OA             |

### 📖 Chi tiết hướng dẫn thực hành kiểm thử Postman (Tài liệu Markdown)

Toàn bộ kịch bản kiểm thử, dữ liệu đầu vào (Input parameters), hướng dẫn thao tác từng bước trên giao diện Postman và kết quả phân tích nghiệp vụ kỳ vọng đã được tách riêng vào thư mục:
👉 [**`tests/postman/`**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/README.md)

Danh mục 15 kịch bản kiểm thử chi tiết:

- [**Test 01: Kiểm tra sức khỏe máy chủ (`GET /api/health`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/01_kiem_tra_suc_khoe_server.md)
- [**Test 02: Tạo chuyến xe mới qua TMS (`POST /api/trips/new`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/02_tao_chuyen_xe_tms.md)
- [**Test 03: Đổi tài xế theo biển số xe (`POST /api/trips/update-driver`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/03_doi_tai_xe_theo_bien_so.md)
- [**Test 04: Bổ sung số seal và giờ đến (`POST /api/trips/supplement`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/04_bo_sung_seal_gio_den.md)
- [**Test 05: Yêu cầu hủy chuyến xe (`POST /api/trips/cancel`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/05_huy_chuyen_xe.md)
- [**Test 06: Tra cứu danh sách & chi tiết chuyến (`GET /api/trips`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/06_tra_cuu_danh_sach_va_chi_tiet_chuyen.md)
- [**Test 07: Zalo Webhook báo xe chuẩn 1 xe (Happy Path)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/07_webhook_bao_xe_chuan.md)
- [**Test 08: Zalo Webhook báo 2 xe trong 1 tin (dấu gạch chéo `/`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/08_webhook_bao_nhieu_xe_mot_tin.md)
- [**Test 09: Zalo Webhook chống trùng lặp tin nhắn (Idempotency)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/09_webhook_chong_trung_lap.md)
- [**Test 10: Zalo Webhook xử lý xe thiếu seal (`HOLD_WAIT_SUPPLEMENT`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/10_webhook_thieu_seal_phan_hoi_nha_xe.md)
- [**Test 11: Zalo Webhook sai nhà xe nhận cuốc (`HOLD_ADMIN`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/11_webhook_sai_nha_xe_canh_bao_admin.md)
- [**Test 12: Zalo Webhook lọc tin nhắn rác & cảnh báo người lạ**](./tests/postman/12_webhook_loc_tin_nhan_rac_va_nguoi_la.md)
- [**Test 13: Bật / Tắt Tự động tạo Shipping giả lập (`POST /api/shipping/mock-mode`)**](./tests/postman/13_bat_tat_auto_mock_shipping.md)
- [**Test 14: Tạo đơn kế hoạch vận chuyển động (`POST /api/shipping/new`)**](./tests/postman/14_tao_don_shipping_dong.md)
- [**Test 15: Tra cứu danh mục kế hoạch vận chuyển (`GET /api/shipping`)**](./tests/postman/15_tra_cuu_danh_muc_shipping.md)
- [**Test 16: Quản lý, kiểm tra sức khỏe và dọn dẹp cơ sở dữ liệu (`GET /api/health`, `DELETE /api/plans`)**](./tests/postman/09_kiem_thu_quan_ly_va_don_dep_db.md)

---

## 8. Quy tắc phân loại ý định (Intent Hierarchy & Conflict Resolution)

Để ngăn chặn xung đột khi một tin nhắn chứa nhiều từ khóa mâu thuẫn, hệ thống áp dụng bảng ưu tiên phân loại nghiêm ngặt:

|    Thứ tự ưu tiên    | Ý định (Intent) | Điều kiện kích hoạt                                                                      | Cơ chế giải quyết xung đột                                                                                                                                   |
| :-----------------------: | :----------------- | :-------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|  **1 (Cao nhất)**  | `CANCEL_REQUEST` | Chứa từ khóa: `hủy`, `huỷ`, `bỏ chuyến`, `không chạy`                        | **Thắng mọi trường hợp**: Kể cả khi tin nhắn có số cont hợp lệ, hệ thống luôn ưu tiên báo hủy chuyến và phát chuông cảnh báo Admin. |
|        **2**        | `UPDATE_REQUEST` | Chứa: `đổi tài`, `thay lái`, `sửa số`, `đổi xe` VÀ có cont hoặc biển số | Nhận diện được xe cần sửa (qua số cont hoặc tra ngược biển số); nâng `version` chuyến xe lên cấp tiếp theo (v2).                               |
|        **3**        | `ASK_WHICH_CONT` | Chứa từ khóa sửa/đổi nhưng **không có** số cont hoặc biển số               | Bot tự động phản hồi nhà xe yêu cầu cung cấp số cont cần cập nhật.                                                                                    |
|        **4**        | `SUPPLEMENT`     | Chứa từ khóa bổ sung hoặc chỉ gửi số seal/giờ                                        | Gộp thông tin vào chuyến đang chờ (`HOLD_WAIT_SUPPLEMENT`).                                                                                                |
|        **5**        | `PARSE`          | Có số container hợp lệ chuẩn ISO 6346 hoặc biển số xe                                 | Kích hoạt luồng bóc tách dữ liệu xe, kiểm tra tính hợp lệ và khớp đơn vị vận chuyển.                                                             |
| **6 (Thấp nhất)** | `IGNORE_CHAT`    | Các câu chào hỏi thông thường: `ok`, `alo`, `dạ vâng`, `chào ad`            | Bot im lặng bỏ qua, không tiêu tốn tài nguyên xử lý hay gọi LLM.                                                                                         |

---

## 9. Kiểm thử tự động & Đo lường độ chính xác

### 9.1. Kiểm thử tự động toàn diện (`make test`)

Hệ thống tích hợp sẵn bộ kiểm thử tự động 12 test suites bao phủ toàn diện:

```bash
make test
# Hoặc: pytest tests -v
```

Kết quả thực tế:

```text
tests/test_dat_module_tc01_tc08_tc16.py::test_dat_module_suite_tc01_to_tc08_and_tc16 PASSED [  8%]
tests/test_dat_module_tc01_tc08_tc16.py::test_tc07_masked_9_chars_and_zcb10_ai_routing_flag PASSED [ 16%]
tests/test_step1_webhook.py::test_01_health_check_mysql_connected PASSED [ 25%]
tests/test_step1_webhook.py::test_02_receive_webhook_and_deduplicate_in_mysql PASSED [ 33%]
tests/test_step1_webhook.py::test_03_list_stored_messages_from_mysql PASSED [ 41%]
tests/test_step2_extraction_and_apis.py::test_fifo_extraction_and_four_query_apis PASSED [ 50%]
tests/test_taxonomy_table1_and_table2.py::test_comprehensive_table1_and_table2_cases PASSED [ 58%]
tests/test_taxonomy_table1_and_table2.py::test_exact_f1_f2_f3_canonical_records_and_ai_masking PASSED [ 66%]
tests/test_transport_plans.py::test_01_import_excel_ketnoi PASSED        [ 75%]
tests/test_transport_plans.py::test_02_crud_transport_plan_endpoints PASSED [ 83%]
tests/test_transport_plans.py::test_03_import_csv_endpoint PASSED        [ 91%]
tests/test_transport_plans.py::test_04_e2e_matching_with_f1_message PASSED [100%]
======================== 12 passed in 2.83s =========================
```

### 9.2. Kiểm thử tự động với bộ tệp tin nhắn TXT (`make test-txt`)

Chạy đánh giá tự động trên toàn bộ 21 bài kiểm thử định dạng input TXT thực tế:

```bash
make test-txt
# Hoặc: python scripts/run_txt_tests.py --all
```

---

## 10. Tùy biến thông báo theo khách hàng

Mẫu tin nhắn gửi cho khách hàng được quản lý bởi Template Engine tại `src/outbound/templates.py`:

- **Template mặc định**:
  - `default_tra.txt`: Dành cho chuyến xe trả hàng.
  - `default_nhap.txt`: Dành cho chuyến xe nhập hàng.
  - `default_capnhat.txt`: Dành cho thông báo cập nhật tài xế (ghi rõ tài xế cũ $\rightarrow$ tài xế mới).
- **Tùy biến riêng cho từng khách hàng**:
  - Tạo file tại: `src/outbound/templates/customers/<khach_hang_id>_<loai>.txt` (Ví dụ: `KH001_tra.txt`).
  - Hệ thống tự động ưu tiên nạp mẫu riêng của khách hàng đó nếu tồn tại, nếu không sẽ dùng mẫu mặc định.

---

## 11. Hướng dẫn mở rộng nghiệp vụ

Khi doanh nghiệp phát sinh quy trình hoặc ý định mới (ví dụ: `REPORT_ACCIDENT` - Báo tai nạn, sự cố):

1. Thêm giá trị `REPORT_ACCIDENT` vào enum `Intent` trong `src/domain/enums.py`.
2. Tạo use case handler mới tại `src/handlers/report_accident.py` kế thừa `BaseHandler`.
3. Đăng ký từ khóa nhận diện trong bộ phân loại ý định `src/messaging/classifier.py`.
4. Đăng ký Handler vào Router trong `src/api/app.py`.

Toàn bộ kiến trúc tuân thủ nghiêm ngặt nguyên lý **Open/Closed Principle (SOLID)** — mở rộng tính năng mới mà không làm sửa đổi mã nguồn các luồng hiện tại.

---

## 12. Giao Diện Giám Sát & Điều Hành Quản Trị (Frontend Dashboard - Next.js 14)

Để quản lý và vận hành trực quan luồng tin nhắn đồ sộ từ hàng trăm, hàng nghìn nhóm chat Zalo của các nhà xe miền Bắc và miền Nam, hệ thống đã trang bị giao diện Quản trị Dashboard hoàn chỉnh tại thư mục `frontend/`.

### 12.1. Công nghệ & Nguyên tắc kiến trúc Frontend
- **Công nghệ**: **Next.js 14+ (App Router)**, **TypeScript**, **Tailwind CSS**, **Lucide React**.
- **Nguyên tắc bất biến Zero Mock Data**: Toàn bộ dữ liệu hiển thị 100% được truy vấn từ các API REST của Backend (`GET /api/...`). Tuyệt đối không sử dụng dữ liệu giả lập, mảng tĩnh hay mock data trên giao diện.

### 12.2. Các màn hình chức năng chính

1. **Tổng Quan Hệ Thống (`/`)**:
   - **Thẻ chỉ số vận hành thời gian thực (KPI Cards)**: Tổng tin nhận, Tin đã xử lý thành công, Tin chờ rà soát thủ công, Tin rác/xã giao bỏ qua, Số tin đang chờ trong hàng đợi FIFO, Số tin thông báo Bot đã gửi ra Zalo OA.
   - **Giám sát Outbound Rate Limiter**: Theo dõi cơ chế Token Bucket (10 req/s, Burst 20, Dynamic Exponential Backoff khi gặp lỗi HTTP 429 từ máy chủ Zalo).
   - **Quản lý Hàng đợi FIFO**: Kiểm tra độ dài hàng đợi và hỗ trợ nút kích hoạt rút cạn hàng đợi thủ công (*Manual Drain FIFO*).
   - **Biểu đồ thống kê theo ngày** & **Feed tin nhắn trực tiếp**.

2. **Kế Hoạch Vận Chuyển Hằng Ngày (`/plans`)**:
   - Giao diện bảng tương thích 100% tệp mẫu điều độ thực tế `backend/tests/data_test/ketnoi.xlsx` (bao gồm đầy đủ 22 cột: Tuyến vận chuyển, Xuất/Nhập, Số cont, Số seal, Kích cỡ cont, Tải trọng, Giờ hẹn, Khách hàng, Loại hàng, Chuyến tàu, Bãi nâng/hạ, Đội xe, Biển số, Địa chỉ đóng/trả, Group ID, Cán bộ giao nhận, Ghi chú, Phát sinh...).
   - **Tự động phân định Lệnh Đóng/Mở**: Dựa trên cột `Hàng (Xuất/Nhập)` để xác định chính xác `order_type` là `dong` (Xuất) hay `tra` (Nhập).
   - **Bộ lọc đa tiêu chí**: Lọc tức thì theo Ngày kế hoạch, Số cont, Tên khách hàng, Loại lệnh đóng/trả.
   - **Import Excel (.xlsx) / CSV trực tiếp**: Tự động bóc tách ngày vận chuyển từ dòng tiêu đề (ví dụ: `KẾ HOẠCH VẬN CHUYỂN NGÀY 12/10/2026 (T2)`), tự động bổ sung và ánh xạ cột `Group ID = 6469608867469758994` khi đối soát tin nhắn nhà xe.
   - **Hỗ trợ CRUD đầy đủ**: Thêm mới kế hoạch thủ công, xóa dòng kế hoạch trực tiếp trên bảng.

3. **Quản Lý & Truy Vấn Tin Nhắn (`/messages`)**:
   - **Thanh Tab lọc nhanh trạng thái**: Lọc tức thì chỉ với 1 click giữa *Tất cả*, *✅ Thành công (processed)*, *⏳ Chờ duyệt (needs_review)*, *🚫 Bị hủy (cancelled)*, *⚠️ Thất bại (failed)*, *💬 Tin rác / Bỏ qua*.
   - Cột **Trạng thái** trực quan: Phân biệt rõ ràng các badge màu sắc, kèm nút bấm liên kết nhanh `Duyệt ngay` trỏ thẳng tới hàng đợi phê duyệt.
   - Bộ lọc chuyên sâu theo Trạng thái tin nhắn, Group ID Zalo, User ID người gửi, Khoảng ngày bắt đầu và kết thúc.
   - Modal xem chi tiết tin nhắn: Hiển thị Bản ghi chuẩn (Canonical Record JSON), danh sách các xe bóc tách (`truck_plate`, `driver_name`, `driver_phone`), danh sách container (`cont_no`, `seal_no`, `order_type`, `plan_date`), các cảnh báo bất thường ISO 6346, và nội dung tin Bot đã gửi phản hồi cho nhà xe.

4. **Kết Quả Tin Nhắn & Thông Báo Gửi Đi (`/results`)**:
   - Trang chuyên biệt theo dõi toàn diện kết quả các tin nhắn thông báo điều xe gửi ra Zalo OA.
   - **Theo dõi 4 trạng thái cốt lõi**:
     - **Đã gửi (`da_gui`)**: Tin nhắn đã xuất bản thành công tới nhóm Zalo khách hàng.
     - **Chờ duyệt (`cho_duyet`)**: Tin nhắn kết quả đang chờ điều độ viên xác nhận.
     - **Bị hủy (`huy`)**: Tin nhắn bị hủy do thay đổi cuốc xe, hỏng xe hoặc điều độ từ chối.
     - **Thất bại (`that_bai`)**: Gửi thất bại do lỗi mạng hoặc bị giới hạn tốc độ Zalo OA (Rate Limit HTTP 429).
   - Thao tác trực tiếp: Nút **Phê duyệt gửi (Approve)**, **Hủy tin (Cancel)**, **Gửi lại (Resend)**, và nút **Tạo mẫu kiểm thử (Seed Samples)**.

5. **Hàng Đợi Rà Soát & Phê Duyệt (`/reviews`)**:
   - Quy trình **Human-in-the-Loop** dành cho điều độ viên: Tập trung toàn bộ các ca tin nhắn có cảnh báo nghiệp vụ (sai Check Digit container theo ISO 6346 Mod 11, thiếu thông tin bắt buộc, có biển rơ-moóc cần xác minh...).
   - Thao tác trực tiếp: Nhấn **Phê duyệt (Approve)** hoặc **Từ chối (Reject - kèm nhập lý do)**, gọi ngay tới API Backend để cập nhật trạng thái bản ghi trong cơ sở dữ liệu.

6. **Thống Kê Taxonomy Nhận Diện Tin Nhắn (`/statistics`)**:
   - **Bảng 1 (Hạng mục dữ liệu nhận diện)**: Thống kê chi tiết 6 nhóm trường (1.1 Nhận diện lệnh, 1.2 Xe & tài xế, 1.3 Container & chì, 1.4 Địa điểm & tuyến, 1.5 Thời gian, 1.6 Bất thường/phát sinh). Hiển thị số tin phát hiện, tỷ lệ %, các kiểu viết thực tế và trích xuất ví dụ điển hình từ database.
   - **Bảng 2 (40 Tình huống tin nhắn thực tế)**: Liệt kê chi tiết từ T01 đến T40, số tin phân loại chính, số tin có đặc điểm, quy tắc phân loại, và danh sách mã tin nhắn khớp. Hỗ trợ tìm kiếm nhanh theo mã hoặc tên tình huống.

### 12.3. Hướng dẫn khởi chạy Frontend

```bash
# Bước 1: Di chuyển vào thư mục frontend
cd frontend

# Bước 2: Cài đặt các gói phụ thuộc (nếu chưa cài)
npm install

# Bước 3: Khởi chạy môi trường phát triển (Development)
npm run dev

# Hoặc Build bản thương phẩm (Production)
npm run build
npm start
```

Giao diện sẽ chạy tại địa chỉ: **`http://localhost:3000`** và tự động kết nối với API Backend tại **`http://localhost:8000`**.

---

## 13. Tích Hợp Mô Hình PaddleOCR Tự Host (Bóc Tách Tin Nhắn Hình Ảnh)

Bên cạnh việc nhận diện các tin nhắn văn bản thuần gõ qua bàn phím, hệ thống hỗ trợ tiếp nhận và bóc tách tự động dữ liệu từ **Hình ảnh** (ảnh chụp phiếu điều xe, lệnh đóng/trả container, ảnh chụp màn hình tin nhắn...) do nhà xe và tài xế gửi qua Zalo thông qua mô hình **PaddleOCR tự host cục bộ (Local Self-Hosted PaddleOCR)**.

### 13.1. Quy tắc nghiệp vụ cốt lõi

1. **Ảnh không có text $\rightarrow$ Bỏ qua (`bo_qua_anh`)**:
   - Nếu ảnh gửi đến là ảnh phong cảnh, ảnh đời thường không chứa chữ, hoặc OCR không bóc tách được ký tự nào:
   - Hệ thống tự động gán trạng thái `processing_status = "bo_qua_anh"` (`MessageStatus.IGNORED_NON_TEXT`).
   - Không tạo xe/container giả lập, không sinh lỗi hệ thống, không gửi tin nhắn spam khách hàng.
2. **Ảnh tách được text $\rightarrow$ Xử lý giống 100% như tin nhắn văn bản hiện tại**:
   - Văn bản bóc tách từ ảnh được đưa trực tiếp vào chu trình bóc tách chuẩn:
     `TripParser` $\rightarrow$ `ContainerValidator` $\rightarrow$ Thẩm định 8 trường cốt lõi (*Khách hàng, Lệnh, Xe, Tài xế, SĐT, Cont, Size, Chì*).
   - **Nhóm Tự Động (`send_mode = 'tu_dong'`)**: Nếu ảnh chứa đủ 8 trường chuẩn $\rightarrow$ Tự động gửi thông báo điều xe ra nhóm Zalo khách hàng (`da_gui`, `processed`).
   - **Nhóm Chờ Duyệt (`send_mode = 'cho_duyet'`)**: Kể cả ảnh chứa đủ 8 trường $\rightarrow$ Vẫn đưa vào danh sách chờ duyệt (`needs_review`) để Điều độ vận tải (ĐHVT) duyệt trước khi phát hành.
   - **Ảnh thiếu thông tin (thiếu số chì, sai số cont...)**: Tự động chuyển ca rà soát và gửi tin nhắn bot nhắc lỗi nhà xe trong vòng 30 phút.

### 13.2. Cấu trúc cấu hình môi trường (.env)

```ini
# Bật/tắt tính năng OCR
OCR_ENABLED=true
OCR_PROVIDER=paddleocr

# Địa chỉ máy chủ PaddleOCR tự host cục bộ
PADDLE_OCR_URL=http://127.0.0.1:8866/predict/ocr_system
OCR_TIMEOUT_SECONDS=15
OCR_LANG=vi
```

### 13.3. Hướng dẫn khởi chạy máy chủ PaddleOCR cục bộ

Có thể lựa chọn 1 trong 2 phương án sau để chạy máy chủ PaddleOCR nội bộ:

#### Phương án 1: Khởi chạy Microservice Python (Khuyên dùng)
```bash
# Cài đặt thư viện PaddleOCR nếu chưa có
pip install paddlepaddle paddleocr

# Khởi chạy máy chủ OCR cục bộ tại cổng 8866
make ocr-run
# Hoặc: python scripts/paddle_ocr_server.py --host 127.0.0.1 --port 8866
```

#### Phương án 2: Khởi chạy bằng Docker Container
```bash
docker run -d --name vsico-paddleocr \
  -p 8866:8866 \
  --restart always \
  paddlepaddle/paddleocr:latest \
  hub serving start -m ocr_system
```

### 13.4. Định dạng Webhook gửi ảnh & Kiểm thử

Cổng Webhook `POST /webhook` hỗ trợ tiếp nhận ảnh dưới các hình thức:
- **Chuỗi Base64**: `"image_base64": "data:image/png;base64,..."`
- **Đường dẫn URL ảnh**: `"image_url": "https://..."`
- **Đường dẫn file trên server**: `"image_path": "/path/to/image.jpg"`
- **Tệp đính kèm**: `"attachments": [{"type": "image", "url": "..."}]`

Tài liệu kiểm thử chi tiết kèm mã cURL mẫu và kết quả đầu ra:
👉 Xem file [**`backend/tests/postman/13_kiem_thu_tach_text_tu_anh_paddleocr.md`**](./backend/tests/postman/13_kiem_thu_tach_text_tu_anh_paddleocr.md).


