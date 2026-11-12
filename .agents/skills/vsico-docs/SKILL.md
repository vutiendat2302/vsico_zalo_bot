---
name: vsico-docs
description: >-
  Viết, cập nhật, chuẩn hóa và kiểm tra hệ thống tài liệu kỹ thuật của dự án VSICO Zalo Bot
  tại docs/, README.md, backend/BACKEND.md, frontend/FRONTEND.md, ai-service/AISERVICE.md,
  database/DATABASE.md, zca-js/ZCA_BRIDGE.md và backend/tests/postman/*.md. Sử dụng khi cập nhật
  kiến trúc, vẽ sơ đồ Mermaid (ERD, Sequence, Flowchart, State), viết hướng dẫn cài đặt hoặc
  viết tài liệu kiểm thử Postman/cURL.
---

# VSICO Documentation — Technical Writing & Diagram Standards

Quản lý toàn bộ tài liệu kỹ thuật tại thư mục `docs/` và các tệp tài liệu định danh của từng phân hệ.

---

## 1. Quy ước Đặt tên File Tài liệu Chuẩn (Strict Naming Convention)

Dự án áp dụng quy chuẩn đặt tên file tài liệu rõ ràng theo đúng tên từng phân hệ thay vì dùng nhiều file `README.md` trùng tên gây nhầm lẫn:

| Đường dẫn File | Phạm vi & Nội dung Tài liệu |
| :--- | :--- |
| **`README.md`** *(Tại thư mục gốc)* | Tổng quan toàn dự án Monorepo, sơ đồ kiến trúc tổng thể, bảng dẫn link tới từng phân hệ và hướng dẫn Quickstart. |
| **`AGENTS.md`** *(Tại thư mục gốc)* | Quy tắc kiến trúc, quy chuẩn phát triển bắt buộc và danh mục `.agents/skills/` cho AI Agent & Developer. |
| **`backend/BACKEND.md`** | Tài liệu kỹ thuật chi tiết của Backend FastAPI, cấu trúc Clean Architecture, Makefile, CLI và quản trị DB. |
| **`frontend/FRONTEND.md`** | Tài liệu kỹ thuật của Frontend Dashboard (Next.js 14 App Router, TypeScript, Zero Mock Data, UI/UX). |
| **`ai-service/AISERVICE.md`** | Tài liệu kỹ thuật của AI & OCR Microservice (Provider, OCR Vision, NLP Extraction, GP1-GP4 Warehouse Matching). |
| **`database/DATABASE.md`** | Đặc tả chi tiết 19 bảng CSDL MySQL 8.4, Snowflake ID 64-bit, ERD Mermaid và quy tắc đồng bộ TMS. |
| **`zca-js/ZCA_BRIDGE.md`** | Tài liệu kỹ thuật mô-đun cầu nối Zalo WebSocket Listener & Outbound REST Server. |
| **`docs/`** *(Thư mục tài liệu gốc)* | Lưu trữ tập trung toàn bộ tài liệu thiết kế hệ thống, hợp đồng dữ liệu (`DATA_CONTRACT.md`), đặc tả API TMS, báo cáo và slide thuyết trình. |

---

## 2. Quy chuẩn Trình bày & Sơ đồ Mermaid

1. **Ngôn ngữ & Phong cách Chuyên nghiệp**:
   - Viết bằng tiếng Việt chuyên nghiệp, rõ ràng, có cấu trúc phân mục đánh số (`1.`, `1.1.`, `1.2.`) và bảng biểu Markdown.
   - **Tuyệt đối không dùng icon / emoji** trong các tài liệu thiết kế và đặc tả kỹ thuật.
2. **Sơ đồ Mermaid Hợp lệ**:
   - Chỉ sử dụng các loại sơ đồ chuẩn: `flowchart TD` / `flowchart LR`, `sequenceDiagram`, `erDiagram`, `stateDiagram-v2`, `classDiagram`.
   - Luôn đặt nhãn nút có ký tự đặc biệt (ngoặc đơn, ngoặc vuông, dấu hai chấm, `<br/>`) trong dấu ngoặc kép `id["Nhãn (Chi tiết)"]` để tránh lỗi cú pháp render.
3. **Tài liệu Kiểm thử Postman / cURL**:
   - Mọi module hoặc endpoint REST API mới trên Backend/AI Service đều phải có hướng dẫn kiểm thử bằng `curl` hoặc Postman chi tiết dưới dạng file Markdown (`.md`) tại `backend/tests/postman/`.

