---
name: vsico-database
description: >-
  Thiết kế, cập nhật schema, viết và kiểm tra Alembic migrations, tối ưu hóa truy vấn và
  chỉ mục MySQL 8.4 cho dự án VSICO Zalo Bot tại database/, backend/src/infrastructure/models.py,
  backend/migrations/ và backend/scripts/manage_db.py. Sử dụng khi thêm bảng mới, sửa cột,
  thiết lập khóa chính Snowflake ID 64-bit, khóa ngoại, đồng bộ ID từ TMS (BigInteger),
  hoặc chạy lệnh quản trị/dọn dẹp dữ liệu MySQL.
---

# VSICO Database — Schema Design & Migration Guide

Làm việc với tài liệu đặc tả tại `database/DATABASE.md` (và `backend/database.md`), ORM Models tại `backend/src/infrastructure/models.py` và Alembic Migrations tại `backend/migrations/`.

---

## 1. Kiến trúc 17 Bảng Cốt lõi & Phân nhóm Dữ liệu

Cơ sở dữ liệu **MySQL 8.4** (`utf8mb4_unicode_ci`) gồm **17 bảng** chia làm 4 phân nhóm:

1. **Danh mục & Tài khoản (Master & Auth Data — 6 bảng)**:
   - `users`: Tài khoản nội bộ (`admin`, `dhvt`) đăng nhập Web quản lý, gắn `zalo_user_id` (khớp `sender_id` Zalo cá nhân) và `zalo_info_id` (trỏ về nhóm Zalo ĐHVT chung).
   - `carriers`: Danh mục Nhà xe / Đội xe đồng bộ từ TMS (`tms_carrier_id`, `code`, `name`, `short_name`).
   - `customers`: Danh mục Khách hàng đồng bộ từ TMS (`tms_customer_id`, `code`, `name`, `short_name`).
   - `warehouses`: Danh mục Kho đóng/trả hàng đồng bộ từ TMS (`tms_warehouse_id`, `customer_id`, `zalo_info_id`).
   - `zalo_info`: Danh bạ nhóm/tài khoản Zalo (`role = 'customer' | 'car' | 'dhvt'`, `carrier_id`, `send_mode`).
   - `route_maps`: Ma trận định tuyến (`customer_id` + `warehouse_id` + `order_type` ➔ `zalo_info_id`).
2. **Kế hoạch Vận chuyển (Planning Data — 1 bảng)**:
   - `transport_plans`: Kế hoạch điều vận hằng ngày kéo từ TMS (`tms_dispatch_id`, `tms_order_id`, `carrier_id`, `customer_id`, `warehouse_id`) hoặc import từ Excel/CSV (`source_file_id`).
3. **Nghiệp vụ Runtime (Runtime Operational Data — 9 bảng)**:
   - `zalo_messages`: Tin nhắn thô từ Webhook Zalo (bất biến).
   - `extraction_runs`: Nhật ký các phiên bóc tách (Regex, PaddleOCR, Gemini AI).
   - `truck_records`: Thông tin lượt xe (Đầu kéo, Lái xe, SĐT, hỗ trợ sửa xe qua `parent_truck_record_id`).
   - `container_jobs`: Thực thể trung tâm quản lý từng container (gắn `transport_plan_id`, `warehouse_id`, `truck_record_id`, `parent_job_id`).
   - `outbound_messages`: Bản tin thông báo gửi nhóm Zalo khách hàng (gắn `container_job_id`, `approved_by_user_id`).
   - `bot_replies`: Theo dõi tin Bot nhắc nhà xe bổ sung thông tin (kèm `fix_deadline`).
   - `review_cases`: Hàng đợi các ca bất thường chờ ĐHVT duyệt (`assigned_to_user_id`, `resolved_by_user_id`).
   - `tms_sync_logs`: Nhật ký gọi API đồng bộ hai chiều với `be-tms`.
   - `activity_logs`: Nhật ký kiểm toán (Audit Trail) gắn `user_id` và cặp `entity_type` + `entity_id`.
4. **Lưu trữ Đối tượng (File Storage — 1 bảng)**:
   - `files`: Quản lý metadata tệp đính kèm và ảnh OCR trên MinIO (`file_key`, `bucket`, `object_key`, `sha256`).

---

## 2. Quy tắc Bất biến về Kiểu Dữ liệu & Khóa (Strict Key Conventions)

1. **Khóa chính Nội bộ (`id`) dùng Snowflake ID 64-bit**:
   - Toàn bộ 17 bảng trong hệ thống Bot bắt buộc dùng kiểu `BigInteger` (`BIGINT`) với giá trị **Snowflake ID 64-bit** sinh từ tầng ứng dụng.
   - **Không sử dụng `AUTO_INCREMENT`** cho các bảng chuẩn mới.
2. **Khóa Đồng bộ từ TMS (`tms_*_id`) dùng `BigInteger`**:
   - Tất cả các trường lưu ID gốc từ phần mềm TMS (`tms_customer_id`, `tms_warehouse_id`, `tms_carrier_id`, `tms_user_id`, `tms_dispatch_id`, `tms_order_id`) đều lưu dưới dạng **`BigInteger` (8 bytes)**, có đánh `Index`.
   - Không lưu ID số của TMS dưới dạng `VARCHAR/String` gây tốn bộ nhớ và làm chậm B-Tree Index. Nếu TMS có mã chữ thì lưu vào cột `code` (`String(64)`).
3. **Mọi Khóa ngoại (`FK`) Nội bộ đều nối qua Snowflake ID**:
   - Các bảng trong DB của Bot chỉ `JOIN` với nhau qua khóa chính `id` nội bộ (`BigInteger`), không `JOIN` qua `tms_*_id` hay chuỗi tên (`car_name`).

---

## 3. Quy trình Làm việc với Alembic Migrations

Khi có bất kỳ thay đổi nào về cấu trúc bảng:

1. **Cập nhật Tài liệu Thiết kế trước**:
   - Cập nhật `database/DATABASE.md` (và đồng bộ `backend/database.md`) kèm thông báo rõ các trường thay đổi cho người dùng.
2. **Cập nhật SQLAlchemy Models**:
   - Chỉnh sửa `backend/src/infrastructure/models.py` khớp 100% với tài liệu thiết kế.
3. **Sinh Kịch bản Migration Tự động**:
   ```bash
   cd backend
   source .venv/bin/activate
   alembic revision --autogenerate -m "mo_ta_ngan_gon_thay_doi"
   ```
4. **Kiểm tra & Áp dụng Migration**:
   - Đọc kỹ file mới sinh ra trong `backend/migrations/versions/` để kiểm tra hàm `upgrade()` và `downgrade()`.
   - Chạy lệnh nâng cấp:
     ```bash
     alembic upgrade head
     ```
5. **Lưu ý Quan trọng**:
   - Tuyệt đối không sửa thủ công các file migration cũ đã được áp dụng lên database.
   - Không xóa bảng `alembic_version` khi dọn dẹp dữ liệu.

---

## 4. Các Lệnh Quản trị & Dọn dẹp Database (`scripts/manage_db.py`)

Thực thi tại thư mục `backend/`:

```bash
# Kiểm tra kết nối MySQL và phiên bản Alembic
make db-check

# Xem thống kê số lượng bản ghi của toàn bộ các bảng
make db-status

# Dọn sạch dữ liệu runtime (tin nhắn, xe, cont, logs) nhưng GIỮ NGUYÊN danh mục & kế hoạch
make db-clean

# Reset toàn bộ DB và chạy lại migration từ đầu
make db-reset
```
