# HƯỚNG DẪN DỰ ÁN VSICO ZALO BOT (CLAUDE.MD)
**Hệ thống Bot Zalo Lọc Tin Điều Xe & Định Tuyến Vận Tải (PM TMS VSICO)**  
*Dự án phối hợp: Tùng (Zalo Connector) & Đạt (NLP & Routing Engine)*

---

## 1. CẤU TRÚC THƯ MỤC DỰ ÁN

Repository hợp nhất gồm 2 module chuyên trách:

```
vsico_zalo_bot/
├── zca-js/                     # MODULE 1: ZALO CONNECTOR (TÙNG)
│   ├── src/                    # Lõi giao tiếp Zalo Web Unofficial API (TypeScript)
│   ├── bridge.js               # Service kết nối WebSocket Zalo & chuyển tiếp Webhook
│   ├── mock_bridge.js          # Client giả lập Zalo để Đạt test backend độc lập
│   └── package.json            # Cấu hình phụ thuộc Node.js (ws, crypto-js, pako...)
│
├── backend/                    # MODULE 2: ĐỌC HIỂU & ĐỊNH TUYẾN (ĐẠT)
│   ├── src/nhaxe_bot/          # Lõi Clean Architecture (Python 3.10+ Standard Library)
│   │   ├── api/                # Cổng HTTP Webhook Gateway & REST API (port 8000)
│   │   ├── ingestion/          # Chuẩn hóa payload, Deduplication, Bộ lọc an ninh
│   │   ├── messaging/          # Phân loại Intent, Segmenter đa xe, Lọc tin rác
│   │   ├── parsing/            # Parser F1, F2, F3, Bóc tách ngày giờ, biển số, SĐT
│   │   ├── domain/             # ISO 6346 Mod 11, Thẩm định, Đối soát Shipping
│   │   ├── handlers/           # CreateTrip, UpdateDriver, CancelTrip, Supplement
│   │   └── outbound/           # Template Engine soạn tin gửi nhóm khách
│   ├── tests/                  # Bộ 48 unit/integration tests & 20 test cases
│   ├── scripts/                # evaluate.py (Benchmark), simulator.py (CLI Test)
│   └── run.py                  # Điểm khởi động máy chủ API
│
├── DATA_CONTRACT.md            # Đặc tả kỹ thuật trao đổi dữ liệu Inbound / Outbound
└── CLAUDE.md                   # Hướng dẫn quy chuẩn phát triển (tài liệu này)
```

---

## 2. HƯỚNG DẪN CÀI ĐẶT & CHẠY TỪNG MODULE

### 2.1. Module 2: Backend Đọc hiểu & Định tuyến (`backend/`)
- **Yêu cầu môi trường**: Python 3.10+ (Không cần cài đặt thêm thư viện ngoài - 100% Standard Library).
- **Khởi động server**:
  ```bash
  cd /home/datbritget/Documents/vsico_zalo_bot/backend
  python3 run.py --port 8000
  ```
- **Chạy toàn bộ 48 unit & integration tests**:
  ```bash
  cd /home/datbritget/Documents/vsico_zalo_bot/backend
  python3 -m unittest discover tests -v
  ```
- **Chạy công cụ kiểm thử tương tác (Simulator CLI)**:
  ```bash
  cd /home/datbritget/Documents/vsico_zalo_bot/backend
  python3 scripts/simulator.py
  ```

---

### 2.2. Module 1: Zalo Connector (`zca-js/`)
- **Yêu cầu môi trường**: Node.js 18+ hoặc Bun.
- **Cài đặt thư viện**:
  ```bash
  cd /home/datbritget/Documents/vsico_zalo_bot/zca-js
  npm install
  ```
- **Chạy service kết nối Zalo (Bridge)**:
  ```bash
  cd /home/datbritget/Documents/vsico_zalo_bot/zca-js
  node bridge.js
  ```
  *(Lần đầu sẽ hiển thị mã QR để quét từ Zalo điện thoại, các lần sau tự động đăng nhập từ credentials đã lưu).*

---

## 3. CƠ CHẾ KIỂM THỬ ĐỘC LẬP BẰNG BẢN GIẢ (MOCK)

Để Đạt và Tùng phát triển song song không phụ thuộc vào nhau:

1. **Tùng test độc lập**: 
   - Tùng chỉ cần khởi động backend Python ở chế độ mock (`python3 run.py --port 8000`).
   - `zca-js` gửi webhook sang `http://localhost:8000/webhook` và nhận JSON response chuẩn.
2. **Đạt test độc lập**:
   - Đạt chạy file giả lập Zalo Bridge `zca-js/mock_bridge.js` để bắn các kịch bản tin nhắn mẫu (báo xe, đổi tài xế, thiếu seal, tin rác) vào backend mà không cần tài khoản Zalo thật.

---

## 4. QUY TẮC BẤT BIẾN KHI PHÁT TRIỂN & REVIEW PR

1. **Tuân thủ tuyệt đối [DATA_CONTRACT.md](DATA_CONTRACT.md)**: Mọi thay đổi về cấu trúc payload JSON Inbound hoặc Outbound phải được cả 2 bên thống nhất và cập nhật vào `DATA_CONTRACT.md` trước khi code.
2. **Zero-dependency cho Backend**: Backend Python giữ nguyên tắc không cài thư viện ngoài (zero external pip packages), đảm bảo chạy được trên mọi server nội bộ offline.
3. **Chống lặp tin Zalo**: Phía `zca-js` luôn phải có điều kiện `if (message.isSelf) return;` trước khi gửi webhook để ngăn bot tự trả lời chính mình.
4. **Idempotency**: Mọi tin nhắn đều phải có `msg_id` duy nhất. Backend đảm bảo nhận lại cùng 1 `msg_id` sẽ từ chối an toàn mà không làm nhân bản chuyến xe.
5. **Che giấu thông tin cá nhân (PII)**: Mọi log ra terminal hoặc lưu file phải che 6 số cuối số điện thoại (ví dụ: `0903***359`).
