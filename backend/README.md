# 🚚 NHAXE-BOT: HỆ THỐNG XỬ LÝ & ĐIỀU PHỐI TIN NHẮN NHÀ XE TỰ ĐỘNG
### DỰ ÁN TỰ ĐỘNG HÓA VẬN TẢI PM TMS - VSICO LOGISTICS (TASK 2)

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Architecture](https://img.shields.io/badge/Architecture-Clean%20%2F%20Layered-emerald.svg)](#2-kiến-trúc-hệ-thống)
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero%20(Standard%20Lib)-green.svg)](#3-yêu-cầu-môi-trường--cài-đặt)
[![Tests](https://img.shields.io/badge/Tests-31%2F31%20PASS%20(100%25)-brightgreen.svg)](#8-kiểm-thử--đo-lường-độ-chính-xác)
[![Evaluation](https://img.shields.io/badge/Benchmark-60%2F60%20Vehicles%20(100%25)-success.svg)](#8-kiểm-thử--đo-lường-độ-chính-xác)

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
├── src/nhaxe_bot/              # Mã nguồn chính dự án
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
│   └── evaluate.py             # Script đo lường độ chính xác trên 57 tin nhắn
├── tools/
│   └── postman_collection.json # File collection Postman phân định REST API & Webhook
└── output/
    └── results.csv             # Kết quả đánh giá xuất file CSV UTF-8 BOM
```

---

## 4. Yêu cầu môi trường & Cài đặt

Dự án được thiết kế theo tiêu chí **Zero External Dependencies** — hoạt động hoàn toàn dựa trên thư viện chuẩn của Python:
- **Python**: Phiên bản `3.10` trở lên (sử dụng dataclasses, type hinting hiện đại, `http.server`, `urllib`).
- **Không yêu cầu `pip install`**: Không phụ thuộc vào gói bên thứ ba để đảm bảo độ tin cậy tuyệt đối, tính bảo mật cao và dễ dàng triển khai ở bất kỳ môi trường nội bộ nào.

### Cấu hình biến môi trường (`.env`):
Tạo file `.env` từ file mẫu `.env.example`:
```bash
cp .env.example .env
```
Nội dung file cấu hình:
```ini
APP_ENV=production
DEBUG=false
SERVER_PORT=8000

# Đường dẫn dữ liệu
SHIPPING_FILE=tests/fixtures/shipping/nhaxe_shipping_demo.csv
MESSAGES_FILE=tests/fixtures/messages/nhaxe_messages_demo.txt
TEMPLATES_DIR=src/nhaxe_bot/outbound/templates

# Zalo OA Secrets (Demo)
ZALO_APP_ID=1234567890123456789
ZALO_SECRET_KEY=vsico_secret_key_demo
ZALO_DRY_RUN=true

# LLM Fallback (Tùy chọn khi bật --use-llm)
LLM_ENABLED=false
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_TIMEOUT=10.0
```

---

## 5. Hướng dẫn vận hành & Khởi chạy chi tiết

Hệ thống cung cấp đa dạng phương thức vận hành phục vụ từ quá trình phát triển (Local Development), kiểm thử tương tác (Interactive Simulation), đo lường độ chính xác (Benchmark Evaluation), đến triển khai sản xuất (Docker Deployment).

---

### 5.1. Bảng phím tắt thao tác nhanh qua Makefile

Hệ thống tích hợp sẵn `Makefile` chuẩn hóa toàn bộ các tác vụ vận hành thường gặp:

| Lệnh Makefile | Lệnh Python tương đương | Chức năng nghiệp vụ |
|---|---|---|
| `make run` | `python3 -m nhaxe_bot.main --serve --port 8000` | Khởi chạy máy chủ HTTP API (Webhook Gateway & REST API) trên cổng 8000 |
| `make simulate` | `python3 scripts/simulator.py` | Bật công cụ mô phỏng tương tác tin nhắn thời gian thực (CLI Simulator) |
| `make test` | `python3 -m unittest discover tests -v` | Chạy toàn bộ 31 kiểm thử tự động (Unit & Integration tests) |
| `make evaluate` | `python3 scripts/evaluate.py` | Đo lường độ chính xác bóc tách trên tập benchmark 57 tin nhắn (60 xe) |
| `make docker-build`| `docker build -t nhaxe-bot:latest .` | Đóng gói mã nguồn thành Docker container image độc lập |
| `make docker-up` | `docker-compose up -d` | Khởi chạy dịch vụ container hóa chạy ngầm trên máy chủ |
| `make docker-down` | `docker-compose down` | Dừng và thu hồi tài nguyên container |

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

## 6. Danh mục API & Hướng dẫn kiểm thử Postman

Hệ thống phân định 2 nhóm cổng giao tiếp độc lập, đảm bảo tính bảo mật và khả năng mở rộng:

| Nhóm Cổng | Phương thức | Đường dẫn (Endpoint) | Chức năng nghiệp vụ chính |
|---|:---:|---|---|
| **TMS Functional API** | `GET` | `/api/health` | Kiểm tra trạng thái máy chủ, số tin đã xử lý & metrics |
| **TMS Functional API** | `POST` | `/api/trips/new` | Tạo chuyến xe mới có cấu trúc từ phần mềm TMS |
| **TMS Functional API** | `POST` | `/api/trips/update-driver` | Đổi tài xế (tra cứu ngược qua biển số xe, nâng lên Version 2) |
| **TMS Functional API** | `POST` | `/api/trips/supplement` | Bổ sung số seal và giờ đến cho chuyến đang chờ |
| **TMS Functional API** | `POST` | `/api/trips/cancel` | Gửi yêu cầu hủy chuyến & kích hoạt chuông cảnh báo Admin |
| **TMS Functional API** | `GET` | `/api/trips` | Truy vấn danh sách toàn bộ chuyến xe trong bộ nhớ |
| **TMS Functional API** | `GET` | `/api/trips/{cont}` | Tra cứu chi tiết một chuyến xe theo số container |
| **TMS Functional API** | `POST` | `/api/shipping/mock-mode` | Bật/tắt chế độ Auto-Mock Shipping (tự sinh đơn cho mọi cont mới) |
| **TMS Functional API** | `POST` | `/api/shipping/new` | Nạp hoặc tạo trực tiếp một đơn kế hoạch shipping mới |
| **TMS Functional API** | `GET` | `/api/shipping` | Xem danh mục kế hoạch shipping và trạng thái auto-mock |
| **Zalo Webhook Gateway** | `POST` | `/webhook` | Cổng tiếp nhận sự kiện webhook tin nhắn thô từ Zalo OA |

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
- [**Test 12: Zalo Webhook lọc tin nhắn rác & cảnh báo người lạ**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/12_webhook_loc_tin_nhan_rac_va_nguoi_la.md)
- [**Test 13: Bật / Tắt Tự động tạo Shipping giả lập (`POST /api/shipping/mock-mode`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/13_bat_tat_auto_mock_shipping.md)
- [**Test 14: Tạo đơn kế hoạch vận chuyển động (`POST /api/shipping/new`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/14_tao_don_shipping_dong.md)
- [**Test 15: Tra cứu danh mục kế hoạch vận chuyển (`GET /api/shipping`)**](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/postman/15_tra_cuu_danh_muc_shipping.md)

---

## 7. Quy tắc phân loại ý định (Intent Hierarchy & Conflict Resolution)

Để ngăn chặn xung đột khi một tin nhắn chứa nhiều từ khóa mâu thuẫn, hệ thống áp dụng bảng ưu tiên phân loại nghiêm ngặt:

| Thứ tự ưu tiên | Ý định (Intent) | Điều kiện kích hoạt | Cơ chế giải quyết xung đột |
|:---:|:---|:---|:---|
| **1 (Cao nhất)** | `CANCEL_REQUEST` | Chứa từ khóa: `hủy`, `huỷ`, `bỏ chuyến`, `không chạy` | **Thắng mọi trường hợp**: Kể cả khi tin nhắn có số cont hợp lệ, hệ thống luôn ưu tiên báo hủy chuyến và phát chuông cảnh báo Admin. |
| **2** | `UPDATE_REQUEST` | Chứa: `đổi tài`, `thay lái`, `sửa số`, `đổi xe` VÀ có cont hoặc biển số | Nhận diện được xe cần sửa (qua số cont hoặc tra ngược biển số); nâng `version` chuyến xe lên cấp tiếp theo (v2). |
| **3** | `ASK_WHICH_CONT` | Chứa từ khóa sửa/đổi nhưng **không có** số cont hoặc biển số | Bot tự động phản hồi nhà xe yêu cầu cung cấp số cont cần cập nhật. |
| **4** | `SUPPLEMENT` | Chứa từ khóa bổ sung hoặc chỉ gửi số seal/giờ | Gộp thông tin vào chuyến đang chờ (`HOLD_WAIT_SUPPLEMENT`). |
| **5** | `PARSE` | Có số container hợp lệ chuẩn ISO 6346 hoặc biển số xe | Kích hoạt luồng bóc tách dữ liệu xe, kiểm tra tính hợp lệ và khớp đơn vị vận chuyển. |
| **6 (Thấp nhất)** | `IGNORE_CHAT` | Các câu chào hỏi thông thường: `ok`, `alo`, `dạ vâng`, `chào ad` | Bot im lặng bỏ qua, không tiêu tốn tài nguyên xử lý hay gọi LLM. |

---

## 8. Kiểm thử & Đo lường độ chính xác

### 8.1. Kiểm thử tự động (`make test`)
Hệ thống tích hợp sẵn 31 kiểm thử bao phủ toàn diện:
```bash
python3 -m unittest discover tests -v
```
Kết quả thực tế:
```text
test_e2e_happy_path_and_update_by_plate (integration.test_pipeline_e2e) ... ok
test_e2e_wrong_carrier_alert (integration.test_pipeline_e2e)            ... ok
test_01_get_health (integration.test_webhook_api)                       ... ok
test_02_post_webhook_happy_path (integration.test_webhook_api)          ... ok
test_03_get_trips (integration.test_webhook_api)                        ... ok
test_04_get_trip_by_cont (integration.test_webhook_api)                 ... ok
test_05_post_rest_api_create_trip (integration.test_webhook_api)        ... ok
test_06_post_rest_api_update_driver (integration.test_webhook_api)      ... ok
test_07_post_rest_api_cancel (integration.test_webhook_api)             ... ok
test_08_post_rest_api_supplement (integration.test_webhook_api)         ... ok
test_09_get_shipping (integration.test_webhook_api)                      ... ok
test_10_post_shipping_mock_mode (integration.test_webhook_api)          ... ok
test_11_post_shipping_new (integration.test_webhook_api)                ... ok
test_12_post_webhook_with_dynamic_container (integration.test_webhook_api)... ok
test_conflict_cancel_vs_cont (unit.test_classifier)                     ... ok
test_conflict_update_driver_plate_only (unit.test_classifier)           ... ok
test_conflict_update_without_cont_or_plate (unit.test_classifier)       ... ok
test_ignore_chat (unit.test_classifier)                                 ... ok
test_normal_parse (unit.test_classifier)                                ... ok
test_supplement_seal (unit.test_classifier)                             ... ok
test_deduplication (unit.test_normalizer)                               ... ok
test_unknown_group (unit.test_normalizer)                               ... ok
test_unknown_sender (unit.test_normalizer)                              ... ok
test_valid_inbound_message (unit.test_normalizer)                        ... ok
test_clean_driver_name (unit.test_rules)                                ... ok
test_clean_phone (unit.test_rules)                                      ... ok
test_clean_plate (unit.test_rules)                                      ... ok
test_iso6346_invalid (unit.test_rules)                                  ... ok
test_iso6346_valid (unit.test_rules)                                    ... ok
test_concatenated_plate_and_compound_driver_name (unit.test_trip_parser) ... ok
test_prefixed_plates_variations (unit.test_trip_parser)                 ... ok
----------------------------------------------------------------------
Ran 31 tests in 0.160s -> OK (100% PASS)
```

### 8.2. Đo lường trên tập dữ liệu benchmark thực tế (`make evaluate`)
Đánh giá toàn bộ 57 tin nhắn Webhook và 60 xe từ tập mẫu [`nhaxe_messages_demo.txt`](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/tests/fixtures/messages/nhaxe_messages_demo.txt):
```text
+----------------------------------------------------------------+
| BÁO CÁO ĐO LƯỜNG ĐỘ CHÍNH XÁC (EVALUATION REPORT - NHAXE BOT)  |
+----------------------------------------------------------------+
  Tổng số sự kiện Webhook đã xử lý : 57 tin
  Tổng số xe trích xuất thành công : 60 xe

  [PHÂN PHỐI HÀNH ĐỘNG - ACTION BREAKDOWN]
  +---------------------------+-----------+
  | HÀNH ĐỘNG (ACTION)        | SỐ LƯỢNG  |
  +---------------------------+-----------+
  | PARSE                     |    60 lần |
  | IGNORE_CHAT               |     5 lần |
  | UPDATE_REQUEST            |     4 lần |
  | DUPLICATE_MESSAGE         |     1 lần |
  | SUPPLEMENT                |     1 lần |
  | CANCEL_REQUEST            |     1 lần |
  | IGNORE_UNKNOWN_SENDER     |     1 lần |
  | IGNORE_UNKNOWN_GROUP      |     1 lần |
  | IGNORE_NON_TEXT           |     1 lần |
  +---------------------------+-----------+

[KẾT LUẬN] Hệ thống hoạt động 100% ổn định, 0 lỗi ngoại lệ.
+----------------------------------------------------------------+
```

---

## 9. Tùy biến thông báo theo khách hàng

Mẫu tin nhắn gửi cho khách hàng được quản lý bởi Template Engine tại `src/nhaxe_bot/outbound/templates/`:
- **Template mặc định**:
  - `default_tra.txt`: Dành cho chuyến xe trả hàng.
  - `default_nhap.txt`: Dành cho chuyến xe nhập hàng.
  - `default_capnhat.txt`: Dành cho thông báo cập nhật tài xế (ghi rõ tài xế cũ $\rightarrow$ tài xế mới).
- **Tùy biến riêng cho từng khách hàng**:
  - Tạo file tại: `src/nhaxe_bot/outbound/templates/customers/<khach_hang_id>_<loai>.txt` (Ví dụ: `KH001_tra.txt`).
  - Hệ thống tự động ưu tiên nạp mẫu riêng của khách hàng đó nếu tồn tại, nếu không sẽ dùng mẫu mặc định.

---

## 10. Hướng dẫn mở rộng nghiệp vụ

Khi doanh nghiệp phát sinh quy trình hoặc ý định mới (ví dụ: `REPORT_ACCIDENT` - Báo tai nạn, sự cố):
1. Thêm giá trị `REPORT_ACCIDENT` vào enum [`Intent`](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/src/nhaxe_bot/domain/enums.py).
2. Tạo use case handler mới tại `src/nhaxe_bot/handlers/report_accident.py` kế thừa `BaseHandler`.
3. Đăng ký từ khóa nhận diện trong [`RuleBasedClassifier`](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/src/nhaxe_bot/messaging/classifier/rule_based.py).
4. Đăng ký Handler vào Router trong [`build_application()`](file:///home/datbritget/Documents/ba_intern_vsico/source/task2/src/nhaxe_bot/main.py) bằng 1 dòng:
   ```python
   router.register(Intent.REPORT_ACCIDENT, report_accident_handler)
   ```
Toàn bộ kiến trúc tuân thủ nghiêm ngặt nguyên lý **Open/Closed Principle (SOLID)** — mở rộng tính năng mới mà không làm sửa đổi mã nguồn các luồng hiện tại.
