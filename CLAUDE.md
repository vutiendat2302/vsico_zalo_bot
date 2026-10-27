# Bot Zalo OA – Chuyển Tin Nhà Xe (VSICO)
**Dự án tích hợp Zalo TMS: Tùng (Zalo Connector) & Đạt (Đọc hiểu & Định tuyến)**  
*Tài liệu chuẩn hóa phát triển theo Hướng dẫn Mục 5 & Jira ZCB-14*

---

## 1. MỤC TIÊU & PHẠM VI DỰ ÁN
Bot đọc tin nhắn nhà xe gửi vào các nhóm Zalo OA / GMF, bóc tách thông tin xe cơ giới (biển số, tài xế, SĐT, số cont, số chì, kho, khách), tự động định tuyến gửi vào đúng nhóm OA của khách hàng và chuẩn bị cập nhật thông tin lên PM TMS.

---

## 2. CÔNG NGHỆ & CẤU TRÚC THƯ MỤC
Repository hợp nhất gồm hai module độc lập:
* **Module 1 (`zca-js/`) - Tùng phụ trách**:
  - Nền tảng: Node.js 18+ (ES Modules), WebSocket Client mô phỏng Zalo Web cá nhân.
  - Tác vụ: Đăng nhập session, nhận sự kiện tin nhắn thời gian thực, gửi tin và quote reply Zalo.
* **Module 2 (`backend/`) - Đạt phụ trách**:
  - Nền tảng: Python 3.10+ (**100% Standard Library**, không cài thêm thư viện ngoài - Zero dependency).
  - Tác vụ: Webhook Gateway, Deduplication, Bộ lọc rác, Bộ đọc F1/F2/F3, Thẩm định ISO 6346 Mod 11, Đối soát Shipping, Định tuyến & Soạn tin gửi khách.

```
vsico_zalo_bot/
├── zca-js/                  # Module 1: Kết nối Zalo (Tùng)
│   ├── src/                 # Thư viện zca-js (Mô phỏng Zalo Web Client)
│   ├── bridge.js            # Cầu nối nhận tin Zalo và chuyển tiếp Webhook
│   ├── mock_bridge.js       # Client giả lập Zalo để Đạt test backend độc lập
│   └── mock_backend.js      # Server giả lập Backend (Node.js) để Tùng test độc lập
│
├── backend/                 # Module 2: Đọc hiểu và định tuyến (Đạt)
│   ├── src/nhaxe_bot/       # Lõi Clean Architecture (Parser, Rules, Handlers, Router)
│   │   ├── api/             # Webhook Gateway HTTP (Port 8000)
│   │   ├── ingestion/       # Lọc trùng msg_id, chuẩn hóa InboundMessage
│   │   ├── messaging/       # Classifier, Lọc tin rác, Segmenter đa xe
│   │   ├── parsing/         # Bộ đọc F1, F2, F3, Bóc tách ngày giờ, biển số, SĐT
│   │   ├── domain/          # ISO 6346 Mod 11, Thẩm định PII, Model nghiệp vụ
│   │   ├── handlers/        # CreateTrip, UpdateDriver, ReviewHandler, Supplement
│   │   └── outbound/        # Template Engine soạn tin khách (không icon)
│   ├── tests/               # Bộ 51 test cases tự động (unit, integration, review)
│   └── run.py               # Điểm khởi động máy chủ API
│
├── DATA_CONTRACT.md         # Hợp đồng trao đổi dữ liệu chi tiết giữa 2 module
└── CLAUDE.md                # Quy chuẩn phát triển và hướng dẫn chạy (tài liệu này)
```

---

## 3. QUY TẮC BẮT BUỘC KHI PHÁT TRIỂN

1. **Bảo mật**: Tuyệt đối không ghi khóa bí mật, cookie hay token trong code. Các biến môi trường nhạy cảm đặt trong `.env` và nằm trong `.gitignore`.
2. **Tuân thủ hợp đồng dữ liệu**: Giao tiếp giữa 2 module phải tuân thủ nghiêm ngặt theo [`DATA_CONTRACT.md`](DATA_CONTRACT.md):
   - **Tùng → Đạt**: Định dạng tin thô (`msg_id`, `group_id`, `sender: {id, name}`, `message: {text}`, `quote_msg_id`, `timestamp`).
   - **Đạt → Tùng**: Định dạng tin gửi (`target_group_id`, `message_text`, `needs_review`, `vehicles`, `reply_to_carrier`, `quote_msg_id`).
3. **Chống trùng lặp tuyệt đối (Idempotency)**: Khóa chống trùng theo `msg_id`. Backend từ chối an toàn nếu Zalo gửi lại webhook trùng `msg_id`. Phía `zca-js` bắt buộc có `if (message.isSelf) return;` để không tự trả lời chính mình.
4. **Kiểm tra chuẩn quốc tế**: Số container bắt buộc kiểm tra theo thuật toán **ISO 6346 Modulo 11**. Sai số kiểm tra thì tạm giữ và báo nhà xe kiểm tra lại số cuối, tuyệt đối không tự sửa.
5. **Định tuyến theo từng container**: Mục tiêu sống còn: **0 tin gửi nhầm khách**. Không chắc chắn về kho/khách thì không gửi, đưa vào trạng thái Chờ duyệt (`needs_review = true`).
6. **Không icon trong tin gửi khách**: Tin gửi vào nhóm khách hàng tuân thủ định dạng chuẩn của Sales: tiêu đề một dòng, có số cont, size, chì, biển số, tài xế, SĐT đã che 6 số cuối, điểm trả và giờ đến.
7. **Cơ chế duyệt trên điện thoại của ĐHVT**: Hỗ trợ ĐHVT quote tin duyệt trên nhóm Zalo nội bộ:
   - Nhắn `ok` -> Duyệt và phát hành tin khách.
   - Nhắn `sửa xe ..., sửa chì ...` -> Cập nhật bản nháp và gửi lại bản mới.
   - Nhắn `huỷ` -> Huỷ phát hành bản tin.
8. **Che giấu dữ liệu cá nhân (PII)**: Mọi log ra terminal hoặc file kiểm thử đều phải che 6 số cuối số điện thoại (ví dụ: `0903******`).
9. **Kiểm thử độc lập bằng bản giả (Mock)**:
   - Tùng chạy `node mock_backend.js` để test kết nối Zalo độc lập mà không cần Python.
   - Đạt chạy `node mock_bridge.js` để test đọc hiểu độc lập mà không cần Zalo thật.

---

## 4. CÁC LỆNH HAY DÙNG

### 4.1. Phía Backend (Đạt)
```bash
# Khởi động Backend Webhook Server (Port 8000)
cd backend && python3 run.py --port 8000

# Chạy toàn bộ 51 unit & integration tests
cd backend && python3 -m unittest discover tests -v

# Chạy công cụ giả lập kiểm thử trực tiếp (Simulator CLI)
cd backend && python3 scripts/simulator.py
```

### 4.2. Phía Zalo Connector (Tùng)
```bash
# Khởi động Mock Backend độc lập bằng Node.js (dành cho Tùng)
cd zca-js && node mock_backend.js

# Chạy Zalo Bridge Client giả lập 7 kịch bản (Happy path, thiếu seal, đổi xe, ĐHVT quote duyệt)
cd zca-js && node mock_bridge.js

# Chạy Zalo Bridge thật kết nối tài khoản Zalo cá nhân
cd zca-js && node bridge.js
```

---

## 5. THUẬT NGỮ CHUYÊN NGÀNH
* **ĐHVT**: Điều hành vận tải (nhân sự VSICO trực tiếp sắp xếp và điều phối xe).
* **Nhà xe**: Các đơn vị thầu phụ vận tải đường bộ sở hữu xe đầu kéo container.
* **Lệnh đóng (Xuất)**: Kho → Cảng. Số cont thường chỉ biết sau khi tài xế lấy vỏ rỗng tại Depot.
* **Lệnh trả (Nhập)**: Cảng → Kho. Số cont có sẵn trong kế hoạch vận chuyển.
* **Vỏ kết hợp**: Cùng một vỏ container vừa được trả cho khách A, sau đó dùng tiếp để đóng hàng cho khách B. Phải tách thành 2 tin riêng cho 2 khách và tuyệt đối không để lộ chữ "kết hợp".
* **Chì**: Số niêm phong (Seal) hải quan hoặc hãng tàu gắn trên cửa container.
