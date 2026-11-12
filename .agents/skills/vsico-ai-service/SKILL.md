---
name: vsico-ai-service
description: >-
  Phát triển, sửa lỗi, refactor, review và kiểm thử AI & OCR Microservice tại ai-service
  (và tầng parsing/AI trong backend) sử dụng Python 3.12, FastAPI, Pydantic v2, Google GenAI SDK
  (Gemini 3.5 Flash / Flash Lite), PaddleOCR Vision, Context-aware Message Segmentation,
  NLP Information Extraction (NER: Biển số, Rơ-moóc, Cont ISO 6346, Seal, Tài xế, SĐT),
  Qdrant Vector Database (768-dim) cho bài toán Map Địa chỉ Kho (GP1-GP4), và Internal Token Security.
  Sử dụng khi làm provider, OCR, message segmenter, NLP extractor, warehouse address matching,
  prompt engineering, privacy masking SĐT hoặc AI unit tests. Không sử dụng cho công việc chỉ
  liên quan CRUD Backend thông thường, Frontend Next.js, SQL migration hoặc tài liệu-only.
---
# VSICO AI Service — Engineering Standards & Development Guide

Làm việc trong thư mục `ai-service/` (và tầng tích hợp AI/OCR tại `backend/src/parsing/ai_fallback.py`, `backend/src/infrastructure/ocr/`).

Mã nguồn trong `ai-service/app/` là trung tâm xử lý trí tuệ nhân tạo chuyên biệt cho bài toán đọc hiểu tin nhắn điều vận container phi cấu trúc từ Zalo và đối chiếu địa chỉ kho thông minh.

---

## 1. Kiến trúc Phân tầng & Trách nhiệm (Clean Layered Architecture)

```text
ai-service/
├── app/
│   ├── core/            # config (đọc ../.env), logging, xác thực X-Internal-Token
│   ├── providers/       # base_provider, Gemini, OpenAI-compatible, privacy_masker
│   ├── ocr/             # paddle_engine, vision_fallback, image_preprocessor
│   ├── analyze/         # service.py: intent + phân đoạn + bóc tách + liên kết, một lần gọi
│   ├── warehouse/       # matcher.py, habit.py, fuzzy.py, llm.py, vector.py (sau), classifier.py (sau)
│   ├── prompts/         # prompt có version
│   ├── schemas/         # Pydantic v2: request/response, có confidence + evidence
│   ├── routers/         # analyze.py, ocr.py, match_warehouse.py, health.py (prefix /v1)
│   └── main.py
├── evals/               # chạy fixtures, đo độ chính xác
├── tests/
├── AISERVICE.md
└── pyproject.toml
```

---

## 2. Quy chuẩn Phát triển AI Provider & Bảo mật Dữ liệu (Privacy-First LLM)

1. **Provider Abstraction**:
   - Mọi tương tác với LLM đều phải kế thừa `BaseProvider` (`app/providers/base_provider.py`).
   - Không được gọi trực tiếp SDK của Google GenAI hoặc OpenAI bên trong Router.
2. **Provider Mặc định**:
   - Sử dụng `gemini-3.5-flash` hoặc `gemini-3.5-flash-lite` làm mô hình mặc định thông qua cấu hình tập trung tại tệp `.env` gốc (`AI_PROVIDER`, `AI_MODEL_NAME`, `AI_BASE_URL`, `AI_API_KEY`).
3. **Bảo mật Số Điện Thoại Tài Xế (Strict PII Masking)**:
   - **BẮT BUỘC**: Trước khi gửi bất kỳ văn bản tin nhắn nào ra Cloud LLM bên ngoài (Gemini/OpenAI), phải chạy qua `PrivacyMasker` để che số điện thoại tài xế thành dạng token hoặc `0931xxxx73`.
   - Sau khi nhận kết quả JSON từ LLM, khôi phục lại số điện thoại gốc từ bộ nhớ đệm cục bộ trước khi trả về cho Backend.
4. **Chiến lược Map Kho 4 Giải Pháp (GP1 ➔ GP4)**:
   - Chỉ kích hoạt khi dòng kế hoạch vận chuyển (`transport_plans`) chưa có sẵn số container (ví dụ lệnh Đóng hàng mới giao cho nhà xe `carrier_id`).
   - Tuân thủ đúng thứ tự thác nước: **GP1 (Vector Search)** ➔ **GP2 (Thói quen nhà xe `address_normalized`)** ➔ **GP3 (Classifier)** ➔ **GP4 (LLM)** và trả về `warehouse_match_source` (`'gp1'`, `'gp2'`, `'gp3'`, `'gp4'`).

---

## 3. Quy chuẩn Router & Pydantic v2 Schemas

1. **Giữ Router Tinh gọn**: Router chỉ thực hiện 4 bước:
   - Nhận Request và Validate qua Pydantic v2 Schema.
   - Xác thực token nội bộ qua Dependency `verify_internal_token` (`X-Internal-Token`).
   - Gọi Pipeline/Service xử lý tương ứng.
   - Trả Response chuẩn hóa kèm `latency_ms` và `model_name` để Backend ghi vào bảng `extraction_runs`.
2. **Structured Output Validation**:
   - Mọi đầu ra từ LLM bắt buộc phải ép kiểu và kiểm tra qua Pydantic Schema (`ExtractedContainerItem`, `ExtractionResultResponse`). Tuyệt đối không trả về `dict` tự do chưa qua kiểm duyệt.

---

## 4. Bảo mật & Zero-Trust Architecture

1. **Internal Service Only**: `ai-service` chỉ phục vụ nội bộ cho `backend`, không phơi trực tiếp ra ngoài Internet hoặc cho `frontend` gọi thẳng.
2. **Xác thực Token Bắt buộc**: Mọi endpoint (trừ `/health`) bắt buộc phải kiểm tra Header `X-Internal-Token` khớp với biến `INTERNAL_SECRET` trong tệp `.env` gốc.
3. **Không Kết nối Trực tiếp MySQL Nghiệp vụ**:
   - `ai-service` không tự ý ghi vào cơ sở dữ liệu MySQL. Toàn bộ dữ liệu ngữ cảnh (danh sách kế hoạch trống của nhà xe, lịch sử câu thoại) do `backend` truyền sang trong request payload, và `backend` chịu trách nhiệm lưu kết quả vào `extraction_runs`, `truck_records`, `container_jobs`.
4. **Không Log Dữ liệu Nhạy cảm**: Không ghi `AI_API_KEY`, `INTERNAL_SECRET` hoặc SĐT chưa che vào log.

---

## 5. Môi trường Thực thi & Kiểm thử (Testing)

1. **Biến môi trường tập trung**:
   - Toàn bộ cấu hình được đọc từ tệp `.env` duy nhất đặt tại thư mục gốc của dự án (`vsico_zalo_bot/.env`). Không tạo file `.env` riêng lẻ bên trong `ai-service/`.
2. **Kiểm thử Tự động với Pytest**:
   ```bash
   cd ai-service
   pytest -v
   ```
3. **Quy tắc Unit Test & Resilience**:
   - Sử dụng Mock cho các lệnh gọi LLM/OCR mạng ngoài khi chạy unit test định kỳ để đảm bảo tốc độ và không tốn quota.
   - Mọi lỗi timeout hoặc ngoại lệ từ LLM/OCR đều phải bắt lại và trả về mã trạng thái rõ ràng để Backend kích hoạt cơ chế Graceful Degradation (chuyển sang Rule-based hoặc đẩy vào `review_cases`).
