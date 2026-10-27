# DATA CONTRACT: GIAO THỨC TRAO ĐỔI DỮ LIỆU GIỮA MODULE KẾT NỐI ZALO (TÙNG) VÀ MODULE ĐỌC HIỂU ĐỊNH TUYẾN (ĐẠT)
**Hệ thống Bot Zalo TMS - VSICO**  
*Mã task Jira liên quan: ZCB-14*  
*Ngày ban hành: 27/10/2026*  
*Trạng thái: ĐÃ THỐNG NHẤT (APPROVED)*

---

## 1. TỔNG QUAN KIẾN TRÚC & PHÂN CHIA TRÁCH NHIỆM

Hệ thống được chia thành 2 module độc lập đặt trong cùng một repository:

```
vsico_zalo_bot/
├── zca-js/                  # Module 1: Kết nối Zalo (Tùng phụ trách)
│   ├── src/                 # Lõi thư viện zca-js (WebSocket + HTTP Zalo)
│   ├── bridge.js            # Service lắng nghe Zalo & chuyển tiếp Webhook
│   └── mock_backend.js      # Mock Backend để Tùng test độc lập
│
├── backend/                 # Module 2: Đọc hiểu & Định tuyến (Đạt phụ trách)
│   ├── src/nhaxe_bot/       # Lõi Clean Architecture (Parser, Rules, Assign, Handlers)
│   ├── run.py / main.py     # Server REST API / Webhook Gateway (Port 8000)
│   └── tests/               # Bộ 48 test cases & 20 kịch bản kiểm thử
│
├── DATA_CONTRACT.md         # Tài liệu đặc tả giao thức dữ liệu chung
└── CLAUDE.md                # Quy chuẩn phát triển và hướng dẫn chạy
```

### 1.1. Trách nhiệm của Module 1 - Kết nối Zalo (`zca-js` - Tùng)
1. Quản lý phiên đăng nhập tài khoản Zalo (QR code, Cookie, IMEI, User-Agent).
2. Duy trì kết nối WebSocket thời gian thực với máy chủ Zalo (`listener.on("message")`).
3. Lọc bỏ tin nhắn do chính bot gửi (`isSelf == true`) để tránh lặp vô tận.
4. Đóng gói tin nhắn thô thành chuẩn **Inbound Webhook Payload** và gửi HTTP `POST http://localhost:8000/webhook` sang Backend.
5. Nhận kết quả từ Backend:
   - Nếu có phản hồi nhà xe (`reply_to_carrier`): Gửi trả lời trích dẫn (Quote reply) vào nhóm nhà xe.
   - Nếu có thông báo khách (`customer_notifications`): Gửi tin nhắn vào từng nhóm Zalo khách hàng tương ứng.
   - Nếu có cảnh báo Admin (`admin_alert == true`): Gửi tin nhắn cảnh báo vào nhóm Điều hành vận tải (ĐHVT).

### 1.2. Trách nhiệm của Module 2 - Đọc hiểu & Định tuyến (`backend` - Đạt)
1. Tiếp nhận webhook payload, kiểm tra schema, deduplicate chống trùng theo `msg_id`.
2. Phân loại ý định (`Intent`): Báo xe mới (`PARSE`), Đổi tài xế (`UPDATE_REQUEST`), Bổ sung (`SUPPLEMENT`), Hủy chuyến (`CANCEL_REQUEST`), Tin rác (`IGNORE_CHAT`).
3. Bóc tách dữ liệu xe (F1 ngăn bằng dấu `/`, F2 form nhãn ĐHVT, F3 cú pháp mẫu).
4. Thẩm định chuẩn: Check-digit container ISO 6346 Modulo 11, chuẩn hóa biển số, chuẩn hóa tên tài xế Title Case, chuẩn hóa SĐT 10 số.
5. Đối soát với kế hoạch vận chuyển (Shipping Plan) để gán khách hàng, kho trả, nhóm Zalo nhận thông báo.
6. Soạn nội dung thông báo theo template chuẩn.
7. Đóng gói **Outbound Response Payload** trả về ngay trong HTTP Response 200 cho Module 1.

---

## 2. ĐẶC TẢ CHI TIẾT GIAO THỨC TRAO ĐỔI DỮ LIỆU

Giao thức trao đổi: **HTTP REST Webhook** qua mạng nội bộ / localhost.
- **Endpoint**: `POST http://localhost:8000/webhook`
- **Content-Type**: `application/json; charset=utf-8`
- **Headers khuyến nghị**: `X-Request-Id: <uuid>` (để trace log toàn hệ thống).

---

### 2.1. Chiều 1: Tùng (`zca-js`) gửi Đạt (`backend`) - Inbound Payload

Mỗi khi có tin nhắn mới từ nhóm hoặc người dùng, `zca-js` gửi một HTTP POST request với body JSON có cấu trúc sau:

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
  "quote_msg_id": "optional_parent_msg_id_if_reply",
  "message": {
    "msg_id": "msg_zalo_123456789",
    "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026",
    "quote_msg_id": "optional_parent_msg_id_if_reply"
  }
}
```

#### Bảng định nghĩa các trường dữ liệu Inbound:
| Tên trường | Kiểu dữ liệu | Bắt buộc | Mô tả |
| :--- | :---: | :---: | :--- |
| `app_id` | `string` | Có | Định danh client gửi (ví dụ: `"zca_personal_bot"`). |
| `event_name` | `string` | Có | Tên sự kiện: `"user_send_text"` (hoặc `"user_send_image"` nếu gửi ảnh). |
| `group_id` | `string` | Có | ID nhóm Zalo (`message.threadId`). Nếu là chat riêng 1-1 thì để chuỗi rỗng `""`. |
| `sender.id` | `string` | Có | User ID người gửi tin nhắn (`message.data.uidFrom`). |
| `sender.name`| `string` | Không | Tên hiển thị Zalo của người gửi (`message.data.dName`). |
| `timestamp` | `string` | Có | Thời điểm gửi tin (epoch millisecond hoặc chuỗi số). |
| `quote_msg_id` | `string` | Không | ID tin nhắn gốc mà người này đang trích dẫn trả lời (nếu có). |
| `message.msg_id` | `string` | Có | ID định danh duy nhất của tin nhắn Zalo (`data.msgId` hoặc `data.cliMsgId`). Dùng để chống trùng lặp. |
| `message.text` | `string` | Có | Nội dung văn bản tin nhắn thô từ người dùng. |

---

### 2.2. Chiều 2: Đạt (`backend`) trả lời Tùng (`zca-js`) - Outbound Response

Backend xử lý xong và phản hồi ngay trong **HTTP Response Body (Status 200 OK)** với cấu trúc Envelope chuẩn:

```json
{
  "ok": true,
  "data": {
    "success": true,
    "seq": 1,
    "msg_id": "msg_zalo_123456789",
    "quote_msg_id": null,
    "carrier_id": "NX01",
    "action": "PARSE",
    "needs_review": false,
    "reply_to_carrier": null,
    "reason": "Bóc tách thông tin xe thành công",
    "admin_alert": false,
    "admin_message": "",
    "total_vehicles": 1,
    "vehicles": [
      {
        "cont": "VSIU7399796",
        "seal": "73957169",
        "bien_so": "15C-87899",
        "tai_xe": "Trần Quốc Bảo",
        "sdt": "0903976359",
        "gio_den": "08:00 14/10/2026",
        "status": "ready",
        "send_status": "SENT_DRY_RUN",
        "shipping_id": "SHP-2026-001001",
        "khach_hang_id": "KH001",
        "ten_khach_hang": "Công ty TNHH Nhựa Phương Nam",
        "kho_tra": "Kho Nhựa Phương Nam",
        "zalo_group_id_gui": "3001000000000000001",
        "notification_text": "THÔNG BÁO XE TRẢ HÀNG\n\nKính gửi Quý khách hàng,\nVSICO xin gửi thông tin xe trả hàng như sau:\n\n- Số cont: VSIU7399796 (40DC)\n- Số chì: 73957169\n- Biển số xe: 15C-878.99\n- Tài xế: Trần Quốc Bảo\n- SĐT: 0903976359\n- Điểm trả: Kho Nhựa Phương Nam\n- Dự kiến đến kho: 08:00 14/10/2026\n",
        "reply_to_carrier": null,
        "warnings": []
      }
    ],
    "customer_notifications": [
      {
        "target_group_id": "3001000000000000001",
        "message_text": "THÔNG BÁO XE TRẢ HÀNG\n\nKính gửi Quý khách hàng,\nVSICO xin gửi thông tin xe trả hàng như sau:\n\n- Số cont: VSIU7399796 (40DC)\n- Số chì: 73957169\n- Biển số xe: 15C-878.99\n- Tài xế: Trần Quốc Bảo\n- SĐT: 0903976359\n- Điểm trả: Kho Nhựa Phương Nam\n- Dự kiến đến kho: 08:00 14/10/2026\n",
        "cont": "VSIU7399796",
        "shipping_id": "SHP-2026-001001",
        "send_status": "SENT_DRY_RUN"
      }
    ],
    "operation_detail": null,
    "junk_verdict": "CANDIDATE",
    "junk_reason": "Có số container hợp lệ",
    "error_code": ""
  },
  "error": null,
  "request_id": "7f7cf4ce-26c0-4521-ac11-e5b161792af4"
}
```

#### Bảng quy chuẩn các trường Outbound để Tùng (`zca-js`) thực hiện gửi tin:
| Trường trong `data` | Ý nghĩa | Hành động Tùng (`zca-js`) cần làm |
| :--- | :--- | :--- |
| **`reply_to_carrier`** | Chuỗi text cần nhắn lại nhà xe (khi thiếu seal, thiếu giờ đến, hoặc hỏi cont). | Nếu có giá trị (`!= null`): Gọi `api.sendMessage({ msg: reply_to_carrier, quote: message.data }, group_id, ThreadType.Group)`. |
| **`customer_notifications`** | Danh sách các thông báo cần gửi tới nhóm khách hàng. | Duyệt mảng: Với mỗi phần tử, gọi `api.sendMessage(item.message_text, item.target_group_id, ThreadType.Group)`. |
| **`admin_alert`** | Cờ boolean cảnh báo bất thường (người lạ vào nhóm, sai nhà xe, cont ngoài kế hoạch, hủy chuyến). | Nếu `true`: Gửi nội dung `admin_message` vào nhóm Zalo Admin (ĐHVT). |
| **`needs_review`** | `true` nếu tin nhắn cần ĐHVT duyệt thủ công trước khi phát hành. | Không tự động gửi tin khách; chỉ báo Admin. |

---

## 3. QUY TẮC XỬ LÝ CÁC TÌNH HUỐNG NGHIỆP VỤ ĐẶC BIỆT

| Hành động (`action`) | Ý nghĩa nghiệp vụ | Phản hồi gửi nhà xe | Thông báo gửi khách hàng |
| :--- | :--- | :--- | :--- |
| **`PARSE`** | Báo xe mới hợp lệ (đầy đủ thông tin, khớp Shipping). | Không (trừ khi có xe con thiếu seal). | **Có**: Gửi thông báo theo template khách. |
| **`UPDATE_REQUEST`** | Đổi tài xế / đổi biển số xe / sửa thông tin. | `"Đã cập nhật tài xế mới cho cont ..."` | **Có**: Gửi thông báo CẬP NHẬT (Version 2) ghi rõ chỗ đổi. |
| **`SUPPLEMENT`** | Bổ sung số chì hoặc giờ đến cho chuyến đang chờ. | `"Đã ghi nhận số seal cho cont ..."` | **Có**: Chuyển trạng thái sang sẵn sàng và gửi thông báo khách. |
| **`CANCEL_REQUEST`** | Nhà xe báo hủy chuyến / xe hỏng. | `"Đã ghi nhận yêu cầu hủy chuyến ..."` | **Không**: Bật `admin_alert = true` để ĐHVT xử lý điều xe khác. |
| **`ASK_WHICH_CONT`** | Yêu cầu sửa nhưng không nêu rõ cont hoặc biển số. | `"Bạn cần đổi thông tin cho số cont hoặc biển số xe nào?"` | Không. |
| **`MANUAL_REVIEW`** | Tin nghi ngờ thiếu thông tin hoặc cập nhật tiến độ ("đã giao", "đã hạ"). | `"Anh/chị gửi đủ biển số, tài xế, SĐT, số cont, số chì giúp em"` | Không; bật cờ báo Admin. |
| **`IGNORE_CHAT`** | Tin nhắn rác, chào hỏi xã giao, cảm ơn, emoji. | **Im lặng tuyệt đối (Không phản hồi)**. | Không. |

---

## 4. HƯỚNG DẪN KIỂM THỬ ĐỘC LẬP BẰNG BẢN GIẢ (MOCK)

### 4.1. Dành cho Tùng (`zca-js`): Test kết nối không cần chạy backend phức tạp
Tùng có thể chạy máy chủ mock backend tích hợp sẵn tại `backend` để kiểm tra việc gửi webhook từ `zca-js`:

```bash
# Khởi động Backend của Đạt (đã tích hợp mock controller sẵn)
cd /home/datbritget/Documents/vsico_zalo_bot/backend
python3 run.py --port 8000
```

Tùng có thể dùng curl để thử gửi payload mẫu:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "2001000000000000001",
    "sender": {"id": "1001000000000000001", "name": "NX Hai Long"},
    "timestamp": "1791798010000",
    "message": {
      "msg_id": "test_mock_001",
      "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026"
    }
  }'
```

### 4.2. Dành cho Đạt (`backend`): Test đọc hiểu không cần quét mã Zalo thật
Đạt có thể dùng script giả lập Zalo Bridge `zca-js/mock_bridge.js` để đẩy các tin nhắn thử nghiệm từ file vào cổng webhook.
