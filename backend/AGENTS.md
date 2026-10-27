# 🤖 NHAXE-BOT: QUY TẮC PHÁT TRIỂN & VẬN HÀNH (DEVELOPER & AGENT RULES)

Tài liệu này định nghĩa các nguyên tắc kiến trúc và quy chuẩn phát triển bắt buộc cho AI Agent và lập trình viên khi làm việc trong dự án **`nhaxe-bot`** (Task 2 - PM TMS VSICO).

---

## 1. Nguyên tắc kiến trúc cốt lõi (Core Architecture Principles)

### 1.1. Phụ thuộc một chiều (One-Way Dependency)

Hệ thống tuân thủ nghiêm ngặt mô hình **Clean Architecture**:

```
api  ──►  handlers  ──►  domain  ◄──  infrastructure
                │
                ▼
            messaging / ingestion
```

- **Lõi `domain/` là thuần khiết (Pure Domain)**:
  - Tuyệt đối **KHÔNG IMPORT** từ `api`, `infrastructure`, `ingestion`, `handlers`.
  - Không import các thư viện HTTP, Web framework, Database driver, hoặc Zalo SDK.
  - Chỉ chứa Domain Models, Enums, Business Rules thuần (ISO 6346, regex chuẩn hóa, matching).
- **Phụ thuộc hướng tâm**: Tầng ngoài phụ thuộc vào tầng trong, tầng trong không biết gì về tầng ngoài.

### 1.2. Cô lập Zalo Payload (Zalo Schema Isolation)

- Cấu trúc Payload thô của Zalo **chỉ được phép tồn tại** tại 2 nơi duy nhất:
  1. `src/nhaxe_bot/api/schemas/zalo.py` (Khai báo cấu trúc dữ liệu HTTP).
  2. `src/nhaxe_bot/ingestion/normalizer.py` (Chuyển đổi thành model nội bộ).
- Từ tầng `messaging`, `handlers`, `domain` trở đi, hệ thống **chỉ sử dụng model nội bộ `InboundMessage`**.
- Khi Zalo thay đổi cấu trúc webhook hoặc hệ thống bổ sung kênh Telegram/Viber, lõi nghiệp vụ hoàn toàn không bị ảnh hưởng.

### 1.3. Cổng Webhook không chứa logic nghiệp vụ (Thin Webhook Gateway)

- `src/nhaxe_bot/api/webhook.py` chỉ thực hiện đúng 3 nhiệm vụ:
  1. Xác thực chữ ký Zalo (`verify_zalo_signature`).
  2. Chuẩn hóa payload sang `InboundMessage` & lọc trùng lặp (`Deduplicator`).
  3. Đẩy vào hàng đợi `QueuePublisher.publish()` và phản hồi ngay lập tức `200 OK` (`{"status": "ENQUEUED"}`).
- **Tuyệt đối KHÔNG**: Bóc tách dữ liệu xe, gọi Database, đọc file shipping hay gọi LLM bên trong Webhook Handler.

### 1.4. Phân định rõ 2 luồng API

- **Zalo Webhook Gateway (`POST /webhook`)**: Dành riêng cho máy chủ Zalo OA đẩy sự kiện tin nhắn thô.
- **TMS Functional REST APIs (`/api/trips/...`, `/api/health`)**: Dành riêng cho phần mềm TMS quản lý chuyến xe trực tiếp qua JSON có cấu trúc rõ ràng.

### 1.5. Mở rộng Intent mới bằng cách thêm file mới (Open/Closed Principle)

- Tuyệt đối không viết chuỗi `if/elif/else` dài trong core logic để xử lý loại tin nhắn mới.
- Khi có Intent mới:
  1. Thêm enum vào `domain/enums.py`.
  2. Tạo một file Handler độc lập trong `handlers/<new_intent>.py` kế thừa `BaseHandler`.
  3. Đăng ký từ khóa nhận diện trong `messaging/classifier/rule_based.py`.
  4. Đăng ký 1 dòng duy nhất vào `IntentRouter` trong `main.py`:
     ```python
     router.register(Intent.NEW_INTENT, new_handler)
     ```

### 1.6. Xuất bản thông báo qua Template (Template Isolation)

- Tuyệt đối không hardcode chuỗi thông báo tiếng Việt gửi khách hàng trong mã nguồn xử lý.
- Mọi nội dung gửi đi phải được nạp và render thông qua `TemplateEngine` từ thư mục `outbound/templates/`.
- Hỗ trợ ghi đè mẫu tin theo từng mã khách hàng cụ thể (`templates/customers/<khach_hang_id>_<loai>.txt`).

### 1.7. Khả năng chống chịu lỗi ngoại vi (Resilience & Graceful Degradation)

- Mọi sự cố ngoại vi (LLM server ngoại tuyến/timeout, Zalo API lỗi mạng, sai định dạng file shipping) **tuyệt đối không được làm sập Queue Worker**.
- Phải luôn có cơ chế Fallback (ví dụ: Fallback từ LLM sang Rule-based Parser) kèm cảnh báo `admin_alert`.

---

## 2. Quy tắc bất biến bắt buộc (Strict Invariants)

1. **Bảo toàn file `zalo.md`**:
   - Tuyệt đối **KHÔNG ĐƯỢC CHẠM VÀO, SỬA ĐỔI HOẶC XÓA** file `source/task2/zalo.md` tại thư mục gốc. Đây là tài liệu thiết kế gốc bất biến.
2. **Zero External Dependencies**:
   - Toàn bộ mã nguồn dự án chỉ sử dụng thư viện chuẩn của **Python 3.10+** (`re`, `json`, `datetime`, `dataclasses`, `http.server`, `urllib`, `queue`, `unittest`).
   - Không được thêm thư viện ngoài (như `requests`, `fastapi`, `flask`, `pydantic`) vào môi trường runtime bắt buộc.
3. **Phạm vi hoạt động**:
   - Tuyệt đối chỉ xử lý và chỉnh sửa các file thuộc phạm vi thư mục `source/task2` (và thư mục mẹ `ba_intern_vsico`). Không truy cập hay ghi file ra ngoài thư mục dự án.
4. **Quy tắc file `.ipynb`**:
   - Tuyệt đối không thêm văn bản giải thích dài dòng hoặc markdown thừa vào trong file `.ipynb`. Mã nguồn chạy đúng yêu cầu nghiệp vụ là ưu tiên hàng đầu.

---

## 3. Quy chuẩn kiểm thử & Đánh giá (Testing & Verification)

Trước khi xác nhận hoàn thành bất kỳ thay đổi nào, bắt buộc phải vượt qua 2 bước kiểm tra:

1. **Kiểm thử tự động**:
   ```bash
   make test
   # Hoặc: python3 -m unittest discover tests -v
   # Bắt buộc: 100% test PASS (24/24 tests)
   ```
2. **Đo lường độ chính xác Benchmark**:
   ```bash
   make evaluate
   # Hoặc: python3 scripts/evaluate.py
   # Bắt buộc: 57/57 sự kiện webhook xử lý thành công, 0 lỗi ngoại lệ.
   ```

## 4. Quy tắc viết comment:

- Tất cả các class, phương thức được sinh ra đều phải viết comment chi tiết, chuyên nghiệp.
