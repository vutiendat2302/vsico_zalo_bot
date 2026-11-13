---
name: vsico-infra
description: >-
  Quản lý, cấu hình và vận hành hạ tầng toàn hệ thống VSICO Zalo Bot bao gồm docker-compose.yml
  tại thư mục gốc (MySQL 8.4, MinIO S3 Storage), tệp cấu hình tập trung .env và .env.example
  duy nhất tại thư mục gốc, module cầu nối Zalo zca-js/ (Node.js WebSocket Listener & Outbound REST Server),
  và Makefile điều phối dịch vụ. Sử dụng khi thay đổi biến môi trường, cổng dịch vụ, Docker container,
  MinIO bucket hoặc cầu nối Zalo zca-js.
---
# VSICO Infrastructure & Zalo Bridge — Operations Guide

Quản lý hạ tầng tập trung tại thư mục gốc của dự án (`vsico_zalo_bot/`) và cầu nối Zalo tại `zca-js/`.

---

## 1. Nguyên tắc Tập trung Hóa Cấu hình (`.env` & `docker-compose.yml` Duy nhất)

1. **Một tệp `.env` và `.env.example` duy nhất tại thư mục gốc**:
   - Toàn bộ dự án (`backend/`, `frontend/`, `ai-service/`, `zca-js/`, `docker-compose.yml`) sử dụng chung **duy nhất một tệp `.env`** đặt tại thư mục gốc `vsico_zalo_bot/.env`.
   - **Nghiêm cấm** tạo các file `.env` rời rạc bên trong từng thư mục con (`backend/.env`, `ai-service/.env`...).
   - Khi thêm bất kỳ biến môi trường mới nào vào code, bắt buộc phải khai báo đồng thời vào cả `.env` và `.env.example` tại thư mục gốc (trong `.env.example` chỉ để giá trị mẫu, tuyệt đối không commit mật khẩu hay API key thật).
2. **Một tệp `docker-compose.yml` duy nhất tại thư mục gốc**:
   - Quản lý tập trung các dịch vụ hạ tầng & ứng dụng tại `vsico_zalo_bot/docker-compose.yml`:
     - **`mysql` (MySQL 8.4+)**: Cổng `3306`, bảng mã `utf8mb4_unicode_ci`, lưu trữ bền vững tại volume `vsico_mysql_data`.
     - **`minio` (MinIO S3-Compatible Object Storage)**: Cổng API `9000`, cổng Web Console `9001`, lưu trữ ảnh OCR và file Excel kế hoạch tại volume `vsico_minio_data`.
     - **`minio-init`**: Tự động tạo bucket `vsico-zalo-files` khi MinIO sẵn sàng.
     - **`qdrant` (Qdrant Vector Database)**: Cổng REST `6333`, gRPC `6334`, volume `vsico_qdrant_data`.
     - **`paddleocr` (Local Self-Hosted PaddleOCR Server)**: Cổng `8866`, nhận diện chữ từ ảnh lệnh điều xe.
     - **`backend` (FastAPI Webhook & REST API)**: Cổng `8000`.
     - **`ai-service` (AI & OCR Microservice)**: Cổng `8001`.
     - **`frontend` (Next.js 16 Management Dashboard)**: Cổng `3001`.

---

## 2. Sơ đồ Cổng Dịch vụ Chuẩn (Standard Port Allocation)

| Dịch vụ / Module              | Thư mục              |  Cổng Mặc định  | Biến Môi trường | Vai trò                                                             |
| :------------------------------ | :--------------------- | :-----------------: | :------------------ | :------------------------------------------------------------------- |
| **ZCA Zalo Bridge**       | `zca-js/`            |      `3000`      | `BOT_API_PORT`    | Lắng nghe WebSocket Zalo & Outbound HTTP Server                     |
| **Frontend Dashboard**    | `frontend/`          |      `3001`      | `FRONTEND_PORT`   | Giao diện quản trị Next.js 16 cho ĐHVT & Admin                   |
| **Backend API & Webhook** | `backend/`           |      `8000`      | `PORT`            | Cổng Webhook `/webhook` & REST API `/api/...`                   |
| **AI & OCR Microservice** | `ai-service/`        |      `8001`      | `AI_SERVICE_PORT` | Dịch vụ nội bộ bóc tách NLP, Vision OCR & Map kho              |
| **PaddleOCR Server**      | `backend/scripts/`   |      `8866`      | `PADDLE_OCR_URL`  | Máy chủ nhận diện chữ tiếng Việt từ ảnh lệnh xe            |
| **MySQL 8.4**             | `docker-compose.yml` |      `3306`      | `DB_PORT`         | Cơ sở dữ liệu quan hệ trung tâm                               |
| **MinIO S3 Storage**      | `docker-compose.yml` | `9000` / `9001` | `MINIO_ENDPOINT`  | Lưu trữ file đính kèm & ảnh Zalo (`bucket` + `object_key`) |
| **Qdrant Vector DB**      | `docker-compose.yml` |      `6333`      | `QDRANT_URL`      | Cơ sở dữ liệu Vector 768-dim cho GP1 Map Địa chỉ Kho          |

---

## 3. Quản lý Cầu nối Zalo (`zca-js/`)

1. **Chức năng**:
   - `zca-js/bot_api_server.js` duy trì kết nối WebSocket với Zalo, tự động bỏ qua tin do chính Bot gửi (`if (message.isSelf) return;`), chuẩn hóa sự kiện và đẩy sang `BACKEND_WEBHOOK_URL` (`http://localhost:8000/webhook`).
   - Cung cấp REST API nội bộ tại cổng `3000` để Backend gửi tin nhắn ra nhóm khách hàng, nhóm nhà xe và nhóm ĐHVT.
2. **Bảo mật Phiên Đăng nhập Zalo**:
   - Tuyệt đối không xóa, sửa hoặc commit các tệp `credentials.json`, `cookies.json`, `qr.png` lên Git.

---

## 4. Các Lệnh Vận hành Hạ tầng Thường dùng

Khởi chạy từ thư mục gốc `vsico_zalo_bot/`:

```bash
# 1. Khởi động các dịch vụ hạ tầng (MySQL, MinIO, Qdrant, PaddleOCR)
docker compose up -d mysql minio minio-init qdrant paddleocr

# 2. Khởi động toàn bộ hệ thống (cả hạ tầng và ứng dụng backend, frontend, ai-service)
docker compose up -d

# 3. Kiểm tra trạng thái các container
docker compose ps

# 4. Xem log thời gian thực của các dịch vụ
docker compose logs -f backend
docker compose logs -f ai-service
docker compose logs -f frontend
docker compose logs -f paddleocr

# 5. Dừng các dịch vụ Docker (giữ nguyên dữ liệu trong volume)
docker compose stop
```
