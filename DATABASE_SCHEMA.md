# 📊 TÀI LIỆU THIẾT KẾ CƠ SỞ DỮ LIỆU CHI TIẾT (DATABASE SCHEMA SPECIFICATION)

### Hệ Thống VSICO Zalo Bot — Quản Lý & Tự Động Hóa Điều Vận Xe Container

*Phiên bản tài liệu: 2.0 | Cập nhật: 03/11/2026*

---

## 1. Tổng Quan Kiến Trúc & 5 Nguyên Tắc Cốt Lõi

Cơ sở dữ liệu của hệ thống **VSICO Zalo Bot** được xây dựng trên nền tảng **MySQL 8.4** (sử dụng SQLAlchemy 2.0 ORM), tuân thủ nghiêm ngặt 5 nguyên tắc thiết kế cơ sở dữ liệu:

1. **Bảo Toàn Tin Nhắn Gốc (Immutability)**:
   - Tin nhắn nhận từ webhook Zalo được lưu trữ nguyên vẹn 100% tại bảng `zalo_messages`. Không có bất kỳ logic nào được phép chỉnh sửa hay ghi đè nội dung gốc.
   - Mọi phiên bóc tách (AI Gemini/PaddleOCR/Regex) được lưu lịch sử độc lập tại `extraction_runs`.
2. **Tách Biệt Đa Tầng (Message ➔ Truck ➔ Container)**:
   - Trong vận tải thực tế: 1 tin nhắn có thể chứa nhiều xe (`truck_records`), và 1 xe có thể chở 2 vỏ container 20ft (`container_jobs`). Vì vậy, hệ thống phân tách thành 3 thực thể riêng biệt với quan hệ 1-N.
3. **Mỗi Container Là Một Thực Thể Độc Lập**:
   - Từng container trong bảng `container_jobs` có vòng đời, trạng thái kiểm tra chữ số kiểm tra (check-digit ISO 6346), đối chiếu kế hoạch vận chuyển và trạng thái đồng bộ TMS hoàn toàn riêng biệt.
4. **An Toàn Tuyệt Đối Trước Khi Gửi Khách Hàng (Zero Tolerance for Wrong Group)**:
   - Mọi trường hợp nghi ngờ (thiếu thông tin, sai số kiểm tra, không khớp kho/khách) lập tức được đưa vào hàng đợi `review_cases` để Điều hành vận tải (ĐHVT) duyệt thủ công. Tuyệt đối không tự động phát hành thông báo nếu độ tin cậy chưa đạt 100%.
5. **Đồng Bộ Hai Chiều Với Phần Mềm Trung Tâm TMS**:
   - Dữ liệu danh mục Khách hàng (`customers`) và Kho (`warehouses`) là bản sao chuẩn từ phần mềm TMS; mọi kết quả bóc tách hợp lệ được đồng bộ ngược sang hệ thống TMS qua `tms_sync_logs`.

---

## 2. Sơ Đồ Quan Hệ Thực Thể (Entity-Relationship Diagram - ERD)

```mermaid
erDiagram
    ZALO_GROUPS ||--o{ OUTBOUND_MESSAGES : "target_group"
    ZALO_GROUPS ||--o{ ROUTE_MAPS : "dest_group"
  
    CUSTOMERS ||--o{ WAREHOUSES : "has"
    CUSTOMERS ||--o{ CUSTOMER_ALIASES : "aliases"
    CUSTOMERS ||--o{ ROUTE_MAPS : "routes"
    CUSTOMERS ||--o{ CONTAINER_JOBS : "owns"
    CUSTOMERS ||--o{ TRANSPORT_PLANS : "assigned"

    WAREHOUSES ||--o{ WAREHOUSE_ALIASES : "aliases"
    WAREHOUSES ||--o{ ROUTE_MAPS : "located_at"
    WAREHOUSES ||--o{ CONTAINER_JOBS : "handled_at"
    WAREHOUSES ||--o{ TRANSPORT_PLANS : "destination"

    ZALO_MESSAGES ||--o{ EXTRACTION_RUNS : "analyzed_by"
    ZALO_MESSAGES ||--o{ TRUCK_RECORDS : "contains_trucks"
    ZALO_MESSAGES ||--o{ CONTAINER_JOBS : "generates_jobs"
    ZALO_MESSAGES ||--o{ REVIEW_CASES : "flagged_in"
    ZALO_MESSAGES ||--o{ BOT_REPLIES : "triggers_replies"

    EXTRACTION_RUNS ||--o{ TRUCK_RECORDS : "produces"

    TRUCK_RECORDS ||--o{ CONTAINER_JOBS : "carries"

    CONTAINER_JOBS ||--o{ CONTAINER_JOBS : "parent_update"
    CONTAINER_JOBS ||--o{ REVIEW_CASES : "has_issue"
    CONTAINER_JOBS ||--o{ OUTBOUND_MESSAGE_ITEMS : "bundled_into"
    CONTAINER_JOBS ||--o{ TMS_SYNC_LOGS : "synced_via"

    OUTBOUND_MESSAGES ||--|{ OUTBOUND_MESSAGE_ITEMS : "contains"
```

---

## 3. Sơ Đồ Luồng Xử Lý Dữ Liệu (Data Flow Diagram - DFD)

```mermaid
flowchart TD
    A["📩 Webhook Inbound Message (Zalo OA / ZCA)"] --> B["Bảng: zalo_messages<br/>(Lưu tin thô, raw_payload)"]
    B --> C{"Bộ lọc tin rác & phân loại"}
    C -->|"Tin rác / Xã giao"| C1["status = ignored"]
    C -->|"Hợp lệ / Có tín hiệu xe"| D["Bảng: extraction_runs<br/>(Lịch sử Regex / PaddleOCR / Gemini)"]
    D --> E["Bảng: truck_records<br/>(Bóc tách: Biển số, Mooc, Lái xe, SĐT)"]
    E --> F["Bảng: container_jobs<br/>(Bóc tách: Số cont, Chì, Kho, Khách, Giờ)"]
  
    F --> G{"Đối soát Kế Hoạch & ISO 6346"}
    G -->|"So khớp Kế Hoạch Vận Chuyển"| H[("Bảng: transport_plans")]
  
    G -->|"Thiếu thông tin / Nghi ngờ"| I["Bảng: review_cases<br/>(Chờ ĐHVT duyệt)"]
    G -->|"Thiếu trường bắt buộc (Nhóm tự động)"| J["Bảng: bot_replies<br/>(Hạn sửa 30 phút, gửi Zalo nhắc lái xe)"]
  
    G -->|"Hợp lệ 100% HOẶC ĐHVT Duyệt"| K["Tạo bản ghi thông báo khách"]
    K --> L["Bảng: outbound_messages<br/>& outbound_message_items"]
    L --> M["Gửi tin Zalo tới Nhóm Khách Hàng<br/>(zalo_groups)"]
    L --> N["Bảng: tms_sync_logs<br/>(Đồng bộ sang be-tms)"]
```

---

## 4. Sơ Đồ Vòng Đời Trạng Thái (State Transition Diagrams)

### 4.1. Vòng Đời Tin Nhắn (`zalo_messages.processing_status`)

```mermaid
stateDiagram-v2
    [*] --> received: Tiếp nhận từ Webhook
    received --> ignored: Tin rác, chào hỏi xã giao
    received --> duplicate: Lọc trùng lặp zalo_message_id
    received --> processing: Đưa vào hàng đợi FIFO bóc tách
    processing --> needs_review: Thiếu trường / Cần ĐHVT duyệt
    processing --> processed: Bóc tách thành công đầy đủ
    needs_review --> processed: ĐHVT duyệt thông qua
    needs_review --> cancelled: ĐHVT từ chối tin
    processed --> [*]
    ignored --> [*]
    cancelled --> [*]
```

### 4.2. Vòng Đời Tin Thông Báo Khách (`outbound_messages.status`)

```mermaid
stateDiagram-v2
    [*] --> cho_duyet: Tạo bản nháp thông báo
    cho_duyet --> da_gui: Tự động gửi (nhóm tự động) HOẶC ĐHVT duyệt
    cho_duyet --> huy: ĐHVT từ chối / Hủy bản nháp
    da_gui --> that_bai: Lỗi mạng / Rate Limit Zalo (HTTP 429)
    that_bai --> da_gui: Thử lại thành công (Token Bucket Retry)
    huy --> [*]
    da_gui --> [*]
```

---

---





## 7. Các Chỉ Mục (Indexes) & Tối Ưu Hóa Hiệu Năng Truy Vấn

Hệ thống được thiết kế sẵn các chỉ mục đơn và chỉ mục kết hợp (Composite Indexes) để phục vụ tra cứu tức thời dưới 10ms kể cả khi bảng đạt hàng triệu dòng:

1. **Khử trùng lặp tin nhắn tức thời**:
   - `zalo_messages.zalo_message_id (UNIQUE)`: Đảm bảo độ trễ check trùng lặp tin chỉ tốn 0.5ms.
2. **Khử trùng lặp phát hành tin gửi khách**:
   - `outbound_messages.idempotency_key (UNIQUE)`: Chống tình trạng gửi lặp 2 thông báo cùng một xe cho khách hàng.
3. **Tra cứu lịch sử bóc tách**:
   - Composite Index: `ix_extraction_runs_msg_started (message_id, started_at)`.
4. **Tra cứu ma trận định tuyến**:
   - Composite Index: `ix_route_maps_lookup (customer_id, warehouse_id, order_type, is_active)`.
5. **Tìm kiếm theo Số Container & Biển Số Xe**:
   - B-Tree Index trên: `container_jobs.container_no`, `truck_records.truck_plate`, `transport_plans.container_no`.
