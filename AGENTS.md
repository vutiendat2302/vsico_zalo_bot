# AGENTS.md

## Tổng quan dự án

**VSICO Zalo Bot & TMS Integration** là hệ thống tự động hóa tiếp nhận, bóc tách, đối chiếu kế hoạch và điều phối thông báo vận tải container đa kênh gồm các thành phần:

- **`backend`**: Backend FastAPI sử dụng Python 3.12+, SQLAlchemy 2.0 ORM, Alembic, Pydantic v2, MySQL 8.4+, MinIO, Snowflake ID 64-bit, hàng đợi bất đồng bộ `FIFOQueue`, bộ điều tiết `ZaloOutboundThrottler` (Token Bucket) và tích hợp hai chiều với phần mềm `be-tms` (Tài liệu: [`backend/BACKEND.md`](./backend/BACKEND.md)).
- **`frontend`**: Frontend Web Quản lý (dành cho ĐHVT & Admin) sử dụng Next.js 16+ (App Router, Turbopack), React 19+, TypeScript 5+, Tailwind CSS v4+, Lucide Icons, Shadcn. (Tài liệu: [`frontend/FRONTEND.md`](./frontend/FRONTEND.md)).
- **`ai-service`**: Service AI & OCR riêng biệt (Python 3.12+, FastAPI), stateless: backend gửi kèm ngữ cảnh (tin trước, chuyến đang hoạt động) trong mỗi request, service không truy cập MySQL. Đảm nhiệm: phân loại ý định (tạo mới / bổ sung / đổi xe / hủy / hỏi thông tin / không rõ), phân đoạn đa xe/đa lệnh, bóc tách và liên kết thực thể (biển số, tài xế, SĐT, số cont, seal) kèm `confidence` và `evidence`, OCR ảnh/PDF scan (PaddleOCR, fallback Gemini Vision), và map địa chỉ kho nhiều tầng (thói quen nhà xe → fuzzy → LLM chọn ứng viên). Mọi kiểm tra tất định (ISO 6346, chuẩn hóa biển số/SĐT) thuộc `backend`; SĐT được che trước khi gọi cloud LLM. Chỉ giao tiếp nội bộ với `backend` (Tài liệu: [`ai-service/AISERVICE.md`](./ai-service/AISERVICE.md)).
- **`database`**: Đặc tả thiết kế các bảng dữ liệu MySQL, sơ đồ ERD, quy ước khóa chính Snowflake ID 64-bit và khóa đồng bộ TMS (Tài liệu: [`database/DATABASE.md`](./database/DATABASE.md)).
- **`zca-js`**: Cầu nối Zalo (Node.js ESM) lắng nghe sự kiện WebSocket thời gian thực từ các nhóm Zalo và cung cấp HTTP REST Server để phát hành tin nhắn (Tài liệu: [`zca-js/ZCA_BRIDGE.md`](./zca-js/ZCA_BRIDGE.md)).
- **`docs`**: Thư mục lưu trữ tập trung tài liệu kiến trúc, đặc tả tích hợp API TMS và quy trình nghiệp vụ ĐHVT và các test Postman.
- **`docker-compose.yml` & `.env`**: Cấu hình chạy hạ tầng (MySQL 8.4+, MinIO) và tệp biến môi trường cục bộ **duy nhất** đặt tại thư mục gốc của dự án.
- **Không dùng dữ liệu fake, mock, giả ở cả FE và BE (trong code chạy thật)**: Chỉ lấy dữ liệu thật từ cơ sở dữ liệu qua API; nếu không có dữ liệu thì hiển thị trạng thái trống (`EmptyState` một dòng). Trong môi trường kiểm thử (`tests/`) được phép dùng MSW (Mock Service Worker) hoặc mock tương ứng.
- **Quy chuẩn Comment/Docstring**: Tất cả các class, hàm, phương thức đều phải có comment/docstring tiếng Việt ngắn gọn nêu rõ đặc điểm và nghiệp vụ chính của phương thức đó.
- **Quy chuẩn viết tài liệu**: Mọi tài liệu thiết kế chuyên nghiệp, không được dùng icon.
---

## Hệ thống Kỹ năng Chuyên biệt (`.agents/skills/`)

Trước khi thực hiện công việc ở phân hệ nào, Agent cần đọc và áp dụng skill tương ứng tại `.agents/skills/`:

- [`vsico-backend`](./.agents/skills/vsico-backend/SKILL.md): Phát triển, sửa lỗi, refactor và kiểm thử Backend FastAPI tại `backend/`.
- [`vsico-frontend`](./.agents/skills/vsico-frontend/SKILL.md): Phát triển, sửa lỗi, refactor và kiểm thử Frontend Next.js 16+ tại `frontend/`.
- [`vsico-ai-service`](./.agents/skills/vsico-ai-service/SKILL.md): Phát triển AI Provider, OCR Vision, NLP Extraction và Map kho GP1–GP4 tại `ai-service/`.
- [`vsico-database`](./.agents/skills/vsico-database/SKILL.md): Thiết kế schema, Snowflake ID, khóa TMS và quản lý Alembic migrations.
- [`vsico-infra`](./.agents/skills/vsico-infra/SKILL.md): Quản lý `docker-compose.yml`, tệp `.env` tập trung, MinIO và cầu nối Zalo `zca-js/`.
- [`vsico-docs`](./.agents/skills/vsico-docs/SKILL.md): Chuẩn hóa tài liệu kỹ thuật (`BACKEND.md`, `FRONTEND.md`, `AISERVICE.md`, `DATABASE.md`, `docs/`) và sơ đồ Mermaid.

---

## Quy tắc làm việc chung

- Đọc phần triển khai liên quan và các quy ước ở những file lân cận trước khi chỉnh sửa.
- Chỉ thay đổi trong phạm vi yêu cầu; không tái cấu trúc những phần không liên quan.
- Bảo toàn mọi thay đổi hiện có của người dùng vì working tree có thể chưa sạch.
- Không xóa, ghi đè hoặc định dạng lại các file không liên quan.
- Ưu tiên giải pháp nhỏ nhất nhưng vẫn giải quyết đầy đủ yêu cầu.
- Không thêm thư viện mới nếu không thực sự cần thiết.
- Không commit kết quả build (`.next/`, `dist/`, `__pycache__/`), file sinh tự động, cấu hình IDE, phiên đăng nhập Zalo (`credentials.json`, `cookies.json`, `qr.png`), thông tin bí mật hoặc file môi trường cục bộ (`.env`).
- Cập nhật tài liệu tương ứng (`BACKEND.md`, `FRONTEND.md`, `AISERVICE.md`, `DATABASE.md`, `ZCA_BRIDGE.md`, `docs/`) khi hành vi, cấu hình hoặc quy trình phát triển thay đổi.

---

## Quy ước backend

- Chạy các lệnh Python, Pytest, Alembic và Makefile từ thư mục `backend` (sử dụng môi trường ảo `.venv`).
- Tuân theo cấu trúc phân tầng Clean Architecture hiện có trong `backend/src`, gồm: `api`, `ingestion`, `messaging`, `parsing`, `domain`, `validation`, `handlers`, `outbound`, `infrastructure`, `observability` và `config`.
- Giữ router (`src/api/`) và cổng `POST /webhook` mỏng (< 50ms): chỉ xác thực, lưu tin nhắn thô vào `zalo_messages`, đẩy vào `FIFOQueue` và trả ngay `200 OK`.
- Đặt nghiệp vụ điều phối trong `handlers/`, quy tắc nghiệp vụ thuần khiết (kiểm tra chữ số container ISO 6346 Modulo 11, chuẩn hóa biển số xe, SĐT 10 số) trong `domain/`, và truy cập dữ liệu MySQL / MinIO / Zalo Bridge / TMS API trong `infrastructure/`. Lõi `domain/` tuyệt đối không import thư viện HTTP hay ORM bên ngoài.
- Sử dụng Pydantic request/response schema (`src/api/schemas.py`) tại biên API, không trả trực tiếp SQLAlchemy ORM entity.
- **Quy ước ID**:
  - Toàn bộ khóa chính `id` của các bảng trong hệ thống Bot sử dụng **Snowflake ID 64-bit (`BigInteger`)** sinh ở tầng ứng dụng (không dùng `AUTO_INCREMENT`).
  - Toàn bộ khóa đồng bộ từ phần mềm TMS (`tms_customer_id`, `tms_warehouse_id`, `tms_carrier_id`, `tms_user_id`, `tms_dispatch_id`, `tms_order_id`) đều lưu dưới dạng **`BigInteger` (8 bytes)** có đánh Index để tối ưu bộ nhớ và tốc độ truy vấn; các mã chữ lưu riêng ở cột `code`.
- **Quản lý Tài khoản (`users`), Nhà xe (`carriers`) & Nhóm Zalo (`zalo_info`)**:
  - Tất cả nhân viên ĐHVT sinh hoạt chung trong nhóm Zalo ĐHVT nội bộ (`zalo_info` có `role = 'dhvt'`), liên kết qua `users.zalo_info_id` (quan hệ Nhiều `users` - Một `zalo_info`).
  - Định danh nhân viên ĐHVT khi tra cứu nội bộ trên Zalo thông qua đối chiếu `zalo_messages.sender_id == users.zalo_user_id`, và dùng chung tài khoản `users` đó cho tính năng đăng nhập Web quản lý (phân quyền `role = 'admin' | 'dhvt'`).
  - **Không cho phép duyệt trên Zalo**: Mọi thao tác duyệt, sửa, từ chối hoặc xác nhận hủy của ĐHVT phải thực hiện trên Web quản lý. Zalo ĐHVT chỉ dùng để nhận thông báo và tra cứu nội bộ (chỉ đọc). Khi nhận lệnh thao tác hoặc quote `"ok"` trên Zalo, Bot chỉ hướng dẫn mở ca trên Web, không thay đổi trạng thái nghiệp vụ.
  - Nhóm Zalo nhà xe (`role = 'car'`) và Kế hoạch vận chuyển (`transport_plans`) liên kết trực tiếp với bảng `carriers` qua khóa ngoại `carrier_id`.
- **Lưu trữ File & Ảnh (MinIO)**: Lưu thông tin file trong bảng `files` gồm `file_key`, `bucket`, `object_key`, `sha256` (không lưu cứng URL tĩnh); khi cần xem thì sinh Presigned URL tạm thời.
- Không thay đổi ID, quan hệ khóa ngoại, trường audit (`activity_logs`) và thời điểm trong vòng đời đối tượng nếu nghiệp vụ không yêu cầu.
- Thêm hoặc cập nhật unit/integration test (`backend/tests/`) khi thay đổi hành vi nghiệp vụ.
- Mọi lời gọi sang `ai-service` và `be-tms` phải đi qua client dùng chung, luôn gửi kèm header xác thực nội bộ (`X-Internal-Token` hoặc Bearer Token TMS), tự động che SĐT tài xế (`0903xxxx59`) trước khi gửi AI và không log nội dung nhạy cảm.

### Kiểm tra backend

```bash
cd backend
pytest tests -v
```

Kiểm tra kết nối MySQL và trạng thái bảng:

```bash
cd backend
python scripts/manage_db.py check
python scripts/manage_db.py status
```

---

## Quy ước frontend

- Chạy các lệnh `npm` từ thư mục `frontend`.
- **Tổ chức theo domain (`src/features/<domain>/`)**: Không dồn mọi endpoint và interface vào một file duy nhất. `src/lib/api/client.ts` chỉ làm fetch wrapper dùng chung (base URL, xử lý lỗi, bắt 401); từng nghiệp vụ (`reviews`, `messages`, `outbound`, `plans`, `directory`, `statistics`, `users`) tách riêng `api.ts`, `hooks.ts`, `columns.tsx`, `components/`.
- **Đồng bộ kiểu dữ liệu từ OpenAPI**: Sử dụng `openapi-typescript` sinh tự động từ schema OpenAPI của FastAPI ra `src/types/api.d.ts` (không sửa tay file này).
- **Quản lý dữ liệu, Bảng & Realtime**: Dùng **TanStack Query** cho server state/caching và **TanStack Table** cho bảng dữ liệu (`DataTable`). Cập nhật thời gian thực sử dụng **SSE (`/api/events/stream`)** kết hợp **Polling có chu kỳ (`refetchInterval: 10000` khi tab active)** làm dự phòng.
- **Xác thực & Phân quyền (`Auth`)**: Lưu token trong **`httpOnly` cookie** (không dùng `localStorage`). Sử dụng `src/middleware.ts` để chặn route theo phiên đăng nhập và phân quyền `role` (`dhvt` / `admin`, riêng `/admin/users` chỉ dành cho `admin`).
- **Tái sử dụng thành phần dùng chung**: Đặt primitive của `shadcn/ui` (`--radius: 0.25rem`) tại `src/components/ui/` và thành phần dùng chung (`DataTable`, `StatusText`, `PageHeader`, `EmptyState`, `FilterBar`) tại `src/components/shared/`.
- Khi chỉnh sửa màn hình lấy dữ liệu, bắt buộc xử lý đầy đủ các trạng thái: `loading`, dữ liệu rỗng (`EmptyState`), `error` (`error.tsx`) và phân quyền (`admin` / `dhvt`).
- **Quy ước Snowflake ID**: Định nghĩa một lần `export type Id = string;`. Backend trả Snowflake ID 64-bit dưới dạng chuỗi trong JSON và Frontend giữ nguyên kiểu `string` (tránh vượt quá `Number.MAX_SAFE_INTEGER` của JavaScript).
- Tuân thủ nghiêm ngặt nguyên tắc thiết kế giao diện điều hành trong [`frontend/FRONTEND.md`](./frontend/FRONTEND.md) (bảng dữ liệu là trung tâm, trang `reviews` bố cục 2 cột Master–Detail, bo góc tối đa `rounded-sm`, không đổ bóng/gradient/icon trang trí).
- **FE không bao giờ gọi trực tiếp `ai-service`, `zca-js`, `MySQL`, `MinIO` hay `be-tms`**; mọi tính năng đều phải gọi qua REST API của `backend` (`NEXT_PUBLIC_API_URL`).

### Kiểm tra frontend

```bash
cd frontend
npm run lint
npm run build
```

---

## Quy ước ai-service

- Chạy các lệnh Python từ thư mục `ai-service`, trong virtual environment riêng (`.venv`), không cài package vào Python hệ thống.
- Tuân theo cấu trúc thư mục chuẩn: `providers`, `ocr`, `context`, `extraction`, `warehouse_matcher` (`gp1` ➔ `gp4`), `routers`, `schemas`, `core`.
- Provider AI phải implement theo interface chung `base_provider.py`; không gọi thẳng SDK của Gemini (hoặc provider khác) từ router hay service ngoài lớp `providers`.
- Định nghĩa schema request/response bằng Pydantic v2 tại `schemas/`, đặc biệt với các endpoint yêu cầu structured output (danh sách xe/container bóc tách, phân loại ý định, kết quả map kho); không trả JSON/dict tự do không có schema.
- Toàn bộ endpoint expose cho `backend` phải xác thực bằng header nội bộ (`X-Internal-Token` khớp `INTERNAL_SECRET`); không expose endpoint ra ngoài mạng công cộng, không nhận traffic trực tiếp từ FE.
- **Bảo mật dữ liệu cá nhân (PII Masking)**: Bắt buộc che SĐT tài xế (`0903xxxx59`) trước khi gửi prompt lên Cloud LLM và khôi phục lại sau khi nhận kết quả; không log nội dung chứa dữ liệu nhạy cảm; ghi nhận đầy đủ `model_name`, `prompt_version`, `latency_ms` để đồng bộ vào bảng `extraction_runs`.
- **Chiến lược Map địa chỉ kho**: Nếu dòng kế hoạch đã có số container thì lấy kho trực tiếp từ kế hoạch (`plan_cont`). Nếu chưa, chạy tuần tự và dừng ở tầng đầu tiên đủ confidence: `habit` (thói quen nhà xe theo `address_normalized`, `carrier_id`) ➔ `fuzzy` (khớp chuỗi trên danh mục kho của khách) ➔ `vector` (Qdrant 768-dim, chưa triển khai) ➔ `llm` (chọn trong danh sách kho ứng viên do backend gửi). Không đủ confidence thì trả `unresolved` để backend tạo ca duyệt cho ĐHVT. `classifier` chỉ làm khi đủ dữ liệu huấn luyện. Mỗi kết quả trả về `warehouse_id`, `confidence`, `source`.
- Không tự ý thêm provider mới (Groq, OpenRouter, v.v.) hoặc đổi model mặc định (`gemini-3.5-flash`) nếu không có yêu cầu rõ ràng; khi thêm phải tuân theo đúng interface `base_provider.py`.
- Giữ type hint đầy đủ cho toàn bộ các hàm/phương thức public và kiểm tra format/type bằng `ruff` / `mypy` nếu đã cấu hình.
- Không commit API key (`AI_API_KEY`, `INTERNAL_SECRET`, v.v.) vào source; chỉ đọc từ tệp `.env` duy nhất ở thư mục gốc dự án.

### Kiểm tra ai-service

```bash
cd ai-service
pytest -v
```

---

## Thay đổi database và API

- Xem schema các bảng (`database/DATABASE.md`) và ORM model (`backend/src/infrastructure/models.py`) là hợp đồng dữ liệu dùng chung giữa `backend`, `frontend` và `ai-service`.
- **Mọi thay đổi về bảng, cột, kiểu dữ liệu hoặc quan hệ đều phải thông báo rõ ràng với người dùng**, cập nhật đồng bộ tài liệu `database/DATABASE.md` và tạo script migration Alembic (`alembic revision --autogenerate -m "..."`, `alembic upgrade head`). Tuyệt đối không sửa thủ công các file migration đã áp dụng trong `backend/migrations/versions/`.
- Khi thay đổi hợp đồng API của `backend`, phải cập nhật đồng bộ Pydantic DTO (`backend/src/api/schemas.py`), chạy lại `openapi-typescript` để cập nhật `frontend/src/types/api.d.ts`, cập nhật `frontend/src/features/<domain>/api.ts` và tài liệu liên quan.
- Khi thay đổi hợp đồng API giữa `backend` và `ai-service` (request/response của `/extract`, `/ocr`, `/match-warehouse`), phải cập nhật đồng bộ client phía `backend`, schema Pydantic phía `ai-service` và tài liệu [`ai-service/AISERVICE.md`](./ai-service/AISERVICE.md).
- Không đưa thông tin đăng nhập, mật khẩu, token hoặc dữ liệu thật vào mã nguồn hay tệp mẫu `.env.example`.

---

## Kiểm tra và bàn giao

- Chạy kiểm tra đúng phạm vi trước, sau đó chạy test/build toàn bộ phân hệ bị ảnh hưởng nếu có thể.
- Chạy `git diff --check` và xem lại diff cuối cùng trước khi hoàn thành.
- Báo cáo rõ nội dung đã thay đổi, kiểm tra nào đã thành công và kiểm tra nào chưa thể chạy.
- Không thông báo hoàn thành nếu biên dịch, lint hoặc test vẫn lỗi; cần mô tả rõ lỗi còn lại.
