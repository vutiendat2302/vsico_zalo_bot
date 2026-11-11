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
│   ├── core/                    # Cấu hình môi trường (config.py đọc từ ../.env), Logging và Security Token
│   ├── providers/               # BaseProvider & GeminiProvider / OpenAICompatibleProvider
│   ├── ocr/                     # Multi-modal OCR Engine:
│   │   ├── paddle_engine.py     # Kết nối máy chủ PaddleOCR tự host (nhận diện lệnh điều xe chụp ảnh)
│   │   ├── vision_fallback.py   # Fallback Gemini Vision khi ảnh mờ, nghiêng hoặc chữ viết tay
│   │   └── image_preprocessor.py# Tiền xử lý ảnh, kiểm tra SHA256 và tải file từ MinIO
│   ├── context/                 # Conversation Context Manager:
│   │   ├── context_builder.py   # Ghép ngữ cảnh hội thoại (Quote/Reply, tin nhắn trước của cùng nhà xe)
│   │   └── intent_resolver.py   # Phân loại ý định: Tạo mới / Bổ sung (Supplement) / Đổi xe (Update) / Hủy
│   ├── extraction/              # NLP Information Extraction Pipeline:
│   │   ├── segmenter.py         # Context-aware Message Segmentation (Tách đa xe, đa cont, kế thừa kho/khách)
│   │   ├── ner_extractor.py     # Bóc tách thực thể: Xe, Rơ-moóc, Tài xế, SĐT, Số Cont, Số Seal, Giờ hẹn
│   │   ├── privacy_masker.py    # Tự động che SĐT (0903xxxx59) trước khi gọi Cloud LLM & khôi phục sau xử lý
│   │   └── iso6346_verifier.py  # Thẩm định chữ số kiểm tra Modulo 11 cho Container
│   ├── warehouse_matcher/       # Giải thuật Map Địa chỉ Kho 4 tầng (GP1 -> GP4):
│   │   ├── gp1_vector_search.py # GP1: Vector hóa địa chỉ so khớp trên Qdrant (768-dim)
│   │   ├── gp2_carrier_habit.py # GP2: Tra cứu trực tiếp theo thói quen viết tắt của từng nhà xe (carrier_id)
│   │   ├── gp3_classifier.py    # GP3: Mô hình phân loại học máy khi dữ liệu huấn luyện đủ lớn
│   │   └── gp4_llm_resolver.py  # GP4: LLM phân giải ngữ cảnh địa chỉ phức tạp / nhập kiểu mới
│   ├── schemas/                 # Pydantic v2 Schemas chặt chẽ cho mọi Request & Response
│   ├── routers/                 # FastAPI Endpoints: extract.py, ocr.py, match_warehouse.py, health.py
│   └── main.py                  # Khởi tạo FastAPI Application và Middleware
├── tests/                       # Pytest Unit & Integration Test Suites
├── AISERVICE.md                 # Tài liệu kỹ thuật chi tiết của AI Service
└── pyproject.toml               # Khai báo Python Dependencies
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
