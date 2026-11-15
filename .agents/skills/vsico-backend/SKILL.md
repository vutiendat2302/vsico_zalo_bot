---
name: vsico-backend
description: >-
  Phát triển, sửa lỗi, refactor, review và kiểm thử Backend VSICO Zalo Bot tại backend/
  sử dụng Python 3.12, FastAPI, SQLAlchemy 2.0 ORM, Alembic, Pydantic v2, MySQL 8.4,
  MinIO, Snowflake ID 64-bit, FIFO Queue, Zalo Outbound Throttler (Token Bucket) và tích hợp
  API be-tms. Sử dụng khi công việc liên quan API router, webhook gateway, extraction handler,
  domain rules (ISO 6346), parsing F1/F2/F3, JWT/RBAC auth (ĐHVT/Admin), MinIO file storage,
  TMS sync hoặc backend pytest. Không sử dụng cho công việc chỉ liên quan Frontend Next.js,
  AI Service độc lập, Docker hoặc tài liệu.
---
# VSICO Backend — Engineering Standards & Development Guide

Làm việc trong thư mục `backend/`.

Luôn đọc implementation hiện có và các file lân cận trước khi chỉnh sửa. Tuân thủ nghiêm ngặt kiến trúc phân tầng **Clean Architecture** của dự án.

---

## 1. Phân lớp Kiến trúc (Clean Layered Architecture)

Hệ thống tuân thủ nguyên tắc phụ thuộc một chiều:

```text
api  ──►  handlers  ──►  domain  ◄──  infrastructure
                │
                ▼
       messaging / parsing / validation / outbound
```

Xác định đúng vị trí khi thêm mới hoặc chỉnh sửa code tại `backend/src/`:

- **REST API & Webhook Gateway** ➔ `src/api/` (`webhook.py`, `messages.py`, `plans.py`, `reviews.py`, `groups.py`, `outbound.py`, `dashboard.py`, `auth.py`)
- **Pydantic Request/Response DTO** ➔ `src/api/schemas.py`
- **Chuẩn hóa Payload Zalo** ➔ `src/ingestion/normalizer.py`
- **Phân đoạn & Phân loại Ý định** ➔ `src/messaging/` (`segmenter.py`, `classifier.py`)
- **Bóc tách Cú pháp (F1/F2/F3/Free)** ➔ `src/parsing/` (`trip_parser.py`, `plan_importer.py`, `ai_fallback.py`)
- **Lõi Nghiệp vụ Thuần khiết** ➔ `src/domain/` (`models.py`, `enums.py`, `rules.py` — ISO 6346 Modulo 11, chuẩn hóa biển số & SĐT)
- **Kiểm tra & Taxonomy** ➔ `src/validation/` (`validators.py`, `taxonomy.py`)
- **Điều phối Nghiệp vụ (Use Cases)** ➔ `src/handlers/` (`extraction_handler.py`)
- **Soạn thảo Thông báo Khách hàng** ➔ `src/outbound/` (`templates.py`, `templates/*.txt`)
- **Cơ sở dữ liệu, Queue, MinIO, Zalo, TMS** ➔ `src/infrastructure/` (`database.py`, `models.py`, `fifo_queue.py`, `throttler.py`, `zalo_dispatcher.py`, `snowflake.py`, `minio_client.py`, `tms_client.py`)
- **Cấu hình Môi trường** ➔ `src/config/settings.py` (đọc từ tệp `.env` duy nhất tại thư mục gốc dự án).

---

## 2. Nguyên tắc Bất biến trong Luồng Xử lý

1. **Lõi `domain/` Thuần khiết (Pure Domain)**:
   - Tuyệt đối không import FastAPI, SQLAlchemy, PyMySQL, HTTP client hay Zalo payload bên trong `src/domain/`.
2. **Cô lập Payload Zalo (Zalo Schema Isolation)**:
   - Cấu trúc JSON thô của Zalo chỉ tồn tại ở `src/api/schemas.py` và `src/ingestion/normalizer.py`.
3. **Cổng Webhook Mỏng & Tốc độ Cao (`POST /webhook` < 50ms)**:
   - Chỉ xác thực, lưu tin nhắn thô vào `zalo_messages`, đẩy vào hàng đợi `FIFOQueue` và trả về ngay `200 OK`.
   - Không chạy OCR, không gọi AI hoặc gọi TMS đồng bộ làm nghẽn luồng tiếp nhận Webhook.
4. **An toàn Tuyệt đối Trước Khi Gửi Khách hàng (Zero Tolerance for Wrong Group)**:
   - Kiểm tra đủ 8 trường cốt lõi (Khách hàng, Loại lệnh, Biển số, Tài xế, SĐT, Số Cont, Size, Số Chì) và chữ số kiểm tra ISO 6346.
   - Bất kỳ nghi ngờ nào (thiếu trường, sai ISO, không khớp kho/khách) hoặc nhóm cấu hình `send_mode = 'pending'` đều phải chuyển vào `review_cases` chờ ĐHVT duyệt.
5. **Điều tiết Tần suất Gửi Zalo (`ZaloOutboundThrottler`)**:
   - Mọi bản tin gửi ra Zalo phải đi qua bộ điều tiết Token Bucket (10 req/s, burst 20) kèm cơ chế Dynamic Backoff khi gặp HTTP 429.

---

## 3. Cơ sở dữ liệu, Snowflake ID & Tích hợp TMS

1. **Chiến lược Khóa chính Snowflake ID 64-bit**:
   - Toàn bộ 17 bảng trong hệ thống sử dụng **Snowflake ID (`BigInteger` 64-bit)** sinh tự động ở tầng ứng dụng, không dùng `AUTO_INCREMENT`.
2. **Khóa Đồng bộ TMS (`BigInteger`)**:
   - Các cột `tms_customer_id`, `tms_warehouse_id`, `tms_carrier_id`, `tms_user_id`, `tms_dispatch_id`, `tms_order_id` đều lưu kiểu **`BigInteger`** để tối ưu tốc độ B-Tree Index và bộ nhớ.
   - Mọi khóa ngoại (`FK`) nội bộ giữa các bảng của Bot đều nối qua khóa chính Snowflake `id` nội bộ.
3. **Quản lý File với MinIO (Bảng `files`)**:
   - Ảnh lệnh điều xe và file Excel kế hoạch được lưu trên MinIO theo `bucket` + `object_key` + `sha256`. Không lưu cứng URL tĩnh trong DB; chỉ sinh Presigned URL tạm thời khi trả API cho Frontend.
4. **Mọi thay đổi Schema phải đi qua Alembic**:
   - Khi sửa `src/infrastructure/models.py`, phải tạo và kiểm tra migration trong `backend/migrations/versions/` (kết hợp skill `vsico-database`).

---

## 4. Bảo mật, Xác thực (JWT + RBAC) & Audit Trail

1. **Đăng nhập Web Quản lý & Duyệt Zalo (Bảng `users`)**:
   - Hỗ trợ phân quyền `role = 'admin'` và `role = 'dhvt'`.
   - Nhân viên ĐHVT sinh hoạt chung trong nhóm Zalo nội bộ (`zalo_info` có `role = 'dhvt'`).
   - Khi ĐHVT quote duyệt `"ok"` trên Zalo, đối chiếu `zalo_messages.sender_id` với `users.zalo_user_id` để ghi nhận chính xác `resolved_by_user_id` / `approved_by_user_id`.
2. **Audit Log (`activity_logs`)**:
   - Mọi thao tác duyệt/từ chối ca (`review_cases`), phát hành tin (`outbound_messages`), import kế hoạch (`transport_plans`), hoặc thay đổi cấu hình nhóm Zalo đều phải ghi nhận vào `activity_logs`.
3. **Không Rò rỉ Bí mật**:
   - Không bao giờ hardcode hoặc log `DB_PASSWORD`, `AI_API_KEY`, `JWT_SECRET_KEY`, `TMS_PASSWORD`, `MINIO_ROOT_PASSWORD`, `INTERNAL_SECRET`.

---

## 5. Quy chuẩn Viết Code, Comment & Kiểm thử

1. **Docstring & Comment Tiếng Việt Chuyên nghiệp**:
   - Toàn bộ class, hàm, phương thức mới đều phải có docstring và comment giải thích rõ nghiệp vụ bằng tiếng Việt.
2. **Thực thi & Kiểm thử tại `backend/`**:
   ```bash
   cd backend
   source .venv/bin/activate
   make test
   # Hoặc chạy pytest cho file cụ thể:
   pytest tests/test_step1_webhook.py -v
   ```
3. **Không báo hoàn thành khi test lỗi**:
   - Luôn chạy lại bộ kiểm thử Pytest liên quan sau khi sửa code để đảm bảo không làm gãy luồng bóc tách F1/F2/F3 và định tuyến.
