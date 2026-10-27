# DATA CONTRACT: GIAO THỨC TRAO ĐỔI DỮ LIỆU GIỮA MODULE KẾT NỐI ZALO (TÙNG) VÀ MODULE ĐỌC HIỂU ĐỊNH TUYẾN (ĐẠT)
**Hệ thống Bot Zalo TMS - VSICO**  
*Mã task Jira: ZCB-14 (Chốt cách 2 module trao đổi dữ liệu và dựng repo)*  
*Phiên bản: 2.0 (Chính thức - 27/10/2026)*  
*Trạng thái: ĐÃ PHÊ DUYỆT (APPROVED)*

---

## 1. TỔNG QUAN KIẾN TRÚC & PHÂN CHIA TRÁCH NHIỆM

Hệ thống được tổ chức thành 2 module độc lập trong một repository chung (`vsico_zalo_bot`):

```
vsico_zalo_bot/
├── zca-js/                  # MODULE 1: KẾT NỐI ZALO (TÙNG PHỤ TRÁCH)
│   ├── src/                 # Lõi thư viện zca-js (Mô phỏng Zalo Web Client)
│   ├── bridge.js            # Service lắng nghe Zalo thật & chuyển tiếp Webhook
│   ├── mock_bridge.js       # Client giả lập Zalo để Đạt test backend độc lập
│   └── mock_backend.js      # Server giả lập Backend (Node.js) để Tùng test độc lập
│
├── backend/                 # MODULE 2: ĐỌC HIỂU & ĐỊNH TUYẾN (ĐẠT PHỤ TRÁCH)
│   ├── src/nhaxe_bot/       # Lõi nghiệp vụ (Parser F1/F2/F3, Rules, Router, Review)
│   ├── run.py / main.py     # Server REST API / Webhook Gateway (Port 8000)
│   └── tests/               # Bộ kiểm thử đơn vị, tích hợp và 20 test cases
│
├── DATA_CONTRACT.md         # Tài liệu đặc tả hợp đồng dữ liệu 2 chiều (tài liệu này)
└── CLAUDE.md                # Quy chuẩn phát triển, lệnh thực thi và hướng dẫn phối hợp
```

---

## 2. CHIỀU 1: TÙNG → ĐẠT (ĐỊNH DẠNG BẢN GHI TIN THÔ & CÁCH ĐẨY HÀNG ĐỢI)

Mỗi khi `zca-js` nhận được sự kiện tin nhắn qua `api.listener.on("message")`, module của Tùng chuẩn hóa và đẩy sự kiện sang Backend của Đạt qua giao thức HTTP REST:
- **Phương thức & URL**: `POST http://localhost:8000/webhook`
- **Content-Type**: `application/json; charset=utf-8`
- **Cơ chế chống lặp**: Tùng bắt buộc bỏ qua tin bot tự gửi (`if (message.isSelf) return;`).

### 2.1. Cấu trúc Payload Inbound chuẩn (JSON)
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "2001000000000000001",
  "sender": {
    "id": "1001000000000000001",
    "name": "Điều hành Hải Long"
  },
  "timestamp": "1791798010000",
  "quote_msg_id": "optional_msg_id_duoc_trich_dan",
  "message": {
    "msg_id": "msg_zalo_123456789",
    "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026",
    "quote_msg_id": "optional_msg_id_duoc_trich_dan"
  }
}
```

### 2.2. Bảng định nghĩa chi tiết các trường dữ liệu Inbound:
| Tên trường | Kiểu | Bắt buộc | Nguồn trong `zca-js` | Diễn giải |
| :--- | :---: | :---: | :--- | :--- |
| `msg_id` | `string` | **Có** | `message.data.msgId` | Mã định danh duy nhất của tin nhắn Zalo (Khóa chống trùng Idempotency). |
| `group_id` | `string` | **Có** | `message.threadId` | ID của nhóm Zalo gửi tin (`data.idTo`). |
| `sender.id` | `string` | **Có** | `message.data.uidFrom` | User ID của người nhắn tin. |
| `sender.name` | `string` | **Có** | `message.data.dName` | Tên hiển thị Zalo của người gửi (Tài xế / ĐHVT). |
| `message.text` | `string` | **Có** | `message.data.content` | Toàn văn nội dung tin nhắn thô. |
| `quote_msg_id` | `string` | Không | `data.quote?.globalMsgId` | ID tin nhắn gốc được trích dẫn (Dùng khi ĐHVT quote duyệt hoặc nhà xe reply sửa). |
| `timestamp` | `string` | **Có** | `message.data.ts` | Thời điểm gửi (epoch milliseconds). |

### 2.3. Cơ chế đẩy vào Hàng đợi (Queue Push Mechanism)
1. **Tiếp nhận tức thời (< 100ms)**: Cổng Webhook của Đạt kiểm tra chữ ký/cấu trúc, chống trùng theo `msg_id` (`zalo_message_raw`), trả ngay HTTP 200 cho Tùng.
2. **Xử lý nền (Asynchronous Queue)**: Job được đẩy vào hàng đợi nội bộ (`MemoryQueue` / `DatabaseQueue`), Worker lấy job ra để bóc tách F1/F2/F3 và thẩm định theo Bảng luật 6.2.

---

## 3. CHIỀU 2: ĐẠT → TÙNG (ĐỊNH DẠNG TIN CẦN GỬI & DỮ LIỆU ĐIỀU HÀNH)

Backend của Đạt trả về HTTP Response 200 đồng bộ ngay trong cuộc gọi webhook với cấu trúc phong bì chuẩn (Envelope):

### 3.1. Cấu trúc Payload Outbound chuẩn (JSON)
```json
{
  "ok": true,
  "status": "success",
  "data": {
    "action": "PARSE",
    "needs_review": false,
    "quote_msg_id": "msg_zalo_123456789",
    "reply_to_carrier": "Chuyến cont GAOU6422920 còn thiếu: số seal/chì. Vui lòng bổ sung!",
    "customer_notifications": [
      {
        "target_group_id": "3001000000000000001",
        "message_text": "VSICO - THÔNG TIN XE TRẢ HÀNG - 14/10/2026\nKhách hàng: Nhựa Á Đông\n\n1. Biển số xe: 15C-878.99\n   Tên lái xe: Trần Quốc Bảo - SĐT 0903******\n   Số cont: VSIU7399796 (40DC)\n   Số chì: 73957169\n   Điểm trả: Kho Nhựa Long An\n   Thời gian dự kiến đến kho: 08:00\n",
        "cont": "VSIU7399796",
        "shipping_id": "SHP-2026-001001",
        "send_status": "SENT_DRY_RUN"
      }
    ],
    "admin_alert": false,
    "admin_message": null,
    "vehicles": [
      {
        "cont": "VSIU7399796",
        "seal": "73957169",
        "bien_so": "15C-878.99",
        "tai_xe": "Trần Quốc Bảo",
        "sdt": "0903******",
        "gio_den": "08:00 14/10/2026",
        "loai_lenh": "tra",
        "kho": "Kho Nhựa Long An",
        "khach": "Nhựa Á Đông",
        "is_valid_iso": true,
        "warnings": []
      }
    ],
    "junk_verdict": "CANDIDATE",
    "junk_reason": "Có cont hợp lệ ISO 6346",
    "error_code": ""
  },
  "error": null,
  "request_id": "req-7f7cf4ce-26c0-4521"
}
```

### 3.2. Bảng quy chuẩn các trường Outbound để Tùng (`zca-js`) hành động:
| Trường | Kiểu | Mô tả nghiệp vụ | Hành động phía Tùng (`zca-js`) |
| :--- | :---: | :--- | :--- |
| **`target_group_id`** | `string` | ID nhóm Zalo OA khách hàng nhận tin. | Gửi tin vào nhóm Zalo khách hàng tương ứng. |
| **`message_text`** | `string` | Nội dung tin gửi đã chuẩn hóa theo mẫu mục 8 (không icon, che 6 số cuối SĐT). | `api.sendMessage(item.message_text, item.target_group_id, ThreadType.Group)`. |
| **`needs_review`** | `boolean` | `true` nếu tin cần ĐHVT duyệt trước khi gửi khách. | Nếu `true`: Gửi bản nháp vào nhóm "ĐHVT duyệt thông tin xe", chưa gửi nhóm khách. |
| **`reply_to_carrier`** | `string \| null` | Tin nhắn phản hồi nhà xe khi thiếu seal, sai cont, hoặc xác nhận sửa. | Nếu có giá trị: Gọi `api.sendMessage({ msg: reply_to_carrier, quote: originalMsg }, group_id, ThreadType.Group)`. |
| **`vehicles`** | `array` | Danh sách chi tiết các dòng xe đã bóc tách và thẩm định xong. | Dùng để hiển thị chi tiết hoặc ghi log điều hành. |
| **`admin_alert`** | `boolean` | Cảnh báo vi phạm (sai nhà xe, cont lạ, người lạ). | Nếu `true`: Gửi cảnh báo vào nhóm Zalo Admin ĐHVT kèm nội dung `admin_message`. |

---

## 4. HÀM & QUY TRÌNH XỬ LÝ LỆNH SỬA (EDIT COMMAND HANDLERS)

Hệ thống có hai luồng lệnh sửa độc lập: Lệnh sửa từ Nhà xe và Lệnh duyệt/sửa từ Điều hành Vận tải (ĐHVT).

```mermaid
flowchart TD
    MSG["Tin nhắn đến có chứa yêu cầu sửa / trích dẫn"] --> CheckSender{"Ai gửi tin?"}
    
    CheckSender -->|Nhà xe| CarrierFlow["1. Nhà xe sửa / bổ sung"]
    CheckSender -->|ĐHVT (Duyệt Zalo)| AdminFlow["2. ĐHVT quote duyệt trên Zalo"]

    CarrierFlow --> C1["Đổi tài xế / Đổi xe: Cập nhật trip_versions, tăng v2, v3, gửi thông báo CẬP NHẬT"]
    CarrierFlow --> C2["Bổ sung seal / Giờ đến: Gộp vào chuyến đang chờ HOLD_WAIT_SUPPLEMENT"]
    CarrierFlow --> C3["Hủy chuyến: Đánh dấu CANCEL, báo Admin ĐHVT"]

    AdminFlow --> A1["ĐHVT quote 'ok' -> Phê duyệt phát hành tin cho nhóm khách"]
    AdminFlow --> A2["ĐHVT quote 'sửa xe ..., sửa chì ...' -> Cập nhật bản nháp, đăng lại bản mới"]
    AdminFlow --> A3["ĐHVT quote 'huỷ' -> Huỷ bỏ bản nháp, không gửi khách"]
```

### 4.1. Luồng 1: Xử lý lệnh sửa từ Nhà xe (`handle_carrier_update`)
* **Signature**:
  ```python
  def handle_carrier_update(inbound: InboundMessage, context: dict) -> List[dict]:
      """Xử lý các tình huống nhà xe đổi tài xế, đổi biển số, bổ sung seal hoặc hủy chuyến."""
  ```
* **Các tình huống**:
  1. **Đổi tài xế / Biển số** (`UPDATE_REQUEST`):
     - Xác định cont mục tiêu (trực tiếp từ tin hoặc tra ngược qua biển số xe trong `TripRepository`).
     - Lập danh sách thay đổi: `Biển số xe: Cũ -> Mới`, `Tài xế: Cũ -> Mới`.
     - Render template CẬP NHẬT (`default_capnhat.txt`), lưu phiên bản mới (`version = version + 1`).
     - Trả về thông báo gửi nhóm khách để cập nhật.
  2. **Bổ sung số seal** (`SUPPLEMENT`):
     - Khớp số cont đang ở trạng thái `HOLD_WAIT_SUPPLEMENT`.
     - Bổ sung seal hợp lệ -> chuyển sang `READY` -> Soạn tin thông báo trả hàng gửi khách.
  3. **Hủy chuyến** (`CANCEL_REQUEST`):
     - Kích hoạt `admin_alert = true`, gửi cảnh báo cho ĐHVT sắp xếp xe thay thế.

---

### 4.2. Luồng 2: Xử lý lệnh sửa / duyệt từ ĐHVT qua Zalo (`handle_dhvt_review`)
Theo quy định tại **Mục 8.2 tab Đặc tả**, ĐHVT duyệt trực tiếp trên điện thoại bằng cách trích dẫn (quote) tin nhắn nháp trong nhóm nội bộ:

* **Signature**:
  ```python
  def handle_dhvt_review(inbound: InboundMessage, pending_repo: PendingTripRepository) -> dict:
      """Xử lý lệnh phản hồi trích dẫn của ĐHVT: 'ok', 'sửa xe...', 'huỷ'."""
  ```
* **Quy tắc nhận diện & xử lý**:
  1. **Lệnh Phê duyệt (`ok`)**:
     - Điều kiện: Tin gửi trong nhóm ĐHVT, có `quote_msg_id` trỏ vào tin nháp, nội dung là `ok` (hoặc `được`, `gửi đi`).
     - Hành động: Lấy thông báo nháp đã chuẩn bị sẵn, chuyển `needs_review = false`, phát hành lệnh gửi tới nhóm khách hàng mục tiêu qua `customer_notifications`.
  2. **Lệnh Sửa thông tin nháp (`sửa xe 15H-06722, sửa chì 23333330...`)**:
     - Điều kiện: Tin bắt đầu bằng từ khóa `sửa` / `sua`.
     - Bóc tách trường cần sửa (biển số mới, số chì mới, tên tài xế mới).
     - Áp dụng giá trị mới vào bản ghi nháp.
     - Soạn lại tin mẫu chuẩn và gửi lại vào nhóm ĐHVT để duyệt lần 2.
  3. **Lệnh Hủy (`huỷ` / `hủy` / `bỏ qua`)**:
     - Điều kiện: Tin là `huỷ` / `hủy`.
     - Hành động: Hủy bỏ bản ghi nháp, ghi log từ chối, không gửi bất kỳ tin nào ra nhóm khách.

---

## 5. CƠ CHẾ KIỂM THỬ ĐỘC LẬP BẰNG BẢN GIẢ (MOCKS)

Nhằm đảm bảo Đạt và Tùng có thể làm việc và kiểm thử độc lập 100%:

### 5.1. Phía Tùng (`zca-js`): Dùng `mock_backend.js` để test Zalo Bridge
Tùng không cần cài đặt Python. Tùng chỉ cần chạy server giả lập bằng Node.js thuần:
```bash
cd /home/datbritget/Documents/vsico_zalo_bot/zca-js
node mock_backend.js
```
`mock_backend.js` tự động mở cổng HTTP 8000, đón nhận mọi webhook và phản hồi chính xác JSON Envelope theo hợp đồng này cho các trường hợp:
- Báo xe chuẩn 1 xe -> Trả về `customer_notifications`.
- Báo xe thiếu seal -> Trả về `reply_to_carrier`.
- Báo đổi tài xế -> Trả về thông báo Cập nhật (v2).
- ĐHVT quote `ok` -> Trả về duyệt thành công.

### 5.2. Phía Đạt (`backend`): Dùng `mock_bridge.js` để test đọc hiểu & định tuyến
Đạt không cần đăng nhập tài khoản Zalo thật. Đạt chỉ cần chạy:
```bash
cd /home/datbritget/Documents/vsico_zalo_bot/zca-js
node mock_bridge.js
```
Script sẽ gửi tuần tự các kịch bản thực tế vào Backend Python đang chạy và in ra đầy đủ log hành động giả lập.
