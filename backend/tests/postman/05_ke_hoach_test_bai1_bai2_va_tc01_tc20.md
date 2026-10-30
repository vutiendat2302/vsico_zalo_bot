# 📮 KẾ HOẠCH & BỘ TEST POSTMAN: BÀI TEST 1, BÀI TEST 2 VÀ BỘ TEST CASE DỮ LIỆU (TC-01 ĐẾN TC-20)
### DỰ ÁN BOT ZALO TMS - VSICO (TASK 2 / JIRA ZALO)

Tài liệu này chuẩn hóa toàn bộ các kịch bản kiểm thử theo đúng tài liệu đặc tả ngày 27/10:
- **Phần 1: Bài test 1** – Bot thử nghiệm thu dữ liệu cá nhân (`zca-js` - Port 3000)
- **Phần 2: Bài test 2** – Bot Zalo OA trong nhóm (`Zalo OA GMF` - Port 8000)
- **Phần 3: Bộ Test Case dữ liệu (TC-01 -> TC-20)** – Thử nghiệm 3 định dạng F1, F2, F3 và kiểm tra bóc tách, chuẩn hóa ISO 6346 Mod 11, ghép kế hoạch.

---

## 1. TỔNG QUAN: CÁC API PHỤC VỤ KIỂM THỬ

Hệ thống đã có đầy đủ 2 nhóm API:
1. **API Nhập tin nhắn và nhận ngay kết quả xử lý bóc tách**:
   - `POST {{baseUrl}}/webhook` (hoặc `/webhook/zalo`)
   - **Cơ chế**: Nhập vào tin nhắn thô ➔ Server tự động đưa vào hàng đợi FIFO, chạy bóc tách (F1, F2, F3), thẩm định biển số, SĐT, số cont (ISO 6346 Mod 11), số chì và **trả về ngay lập tức JSON kết quả xe & cont đã bóc tách**.
2. **API Truy vấn và đối soát kết quả**:
   - `GET {{baseUrl}}/api/messages`: Xem tất cả tin nhắn và kết quả bóc tách.
   - `GET {{baseUrl}}/api/messages/detail/{message_id}`: Xem chi tiết 1 tin nhắn và kết quả bóc tách theo ID/MessageID.
   - `GET {{baseUrl}}/api/messages/group/{group_id}`: Xem tin nhắn theo nhóm A/B.
   - `GET {{baseUrl}}/api/messages/user/{user_id}`: Xem tin nhắn theo người gửi.

---

## 2. BÀI TEST 1: BOT THỬ NGHIỆM THU DỮ LIỆU (ZCA-JS - PORT 3000)

* **Mục tiêu**: Lấy tin thô từ nhóm Zalo cá nhân về server, ghi vào bảng `zalo_messages` / `zalo_message_raw`, giữ nguyên `raw_payload`.

| Mã | Tên Request Postman | Endpoint / Thao tác | Dữ liệu kiểm tra | Kết quả mong đợi |
| :---: | :--- | :--- | :--- | :--- |
| **B1-01** | Nhận tin chữ thường | Gửi vào nhóm Zalo Test | `"xe 15c12345 di kho long an"` | Bot nhận được qua WebSocket, đẩy về `POST /webhook` lưu DB thô. |
| **B1-02** | Tin có nhắc tên bot | Gửi vào nhóm Zalo Test | `"@bot kiem tra cont VSIU2621051"` | Bot nhận được cả khi nhắc và không nhắc tên. |
| **B1-03** | Tin F1 nhiều dòng | `POST {{botUrl}}/api/bot/send/group` | Tin F1 có xuống dòng `\n` | Giữ nguyên vẹn ký tự xuống dòng `\n`, không bị dồn 1 hàng. |
| **B1-04** | Tin F2 có tiếng Việt có dấu | `POST {{botUrl}}/api/bot/send/group` | `"Đóng , Trả hàng: Tra 1x20 Nhựa Long An"` | UTF-8 nguyên vẹn, không bị lỗi font/mất dấu tiếng Việt. |
| **B1-05** | Gửi ảnh chụp tin/lệnh | Bắn sự kiện ảnh qua Webhook | `event_name: "user_send_image"` | Server ghi nhận `message_type: image`, lưu link ảnh an toàn. |
| **B1-06** | Trả lời (quote) tin khác | `POST {{baseUrl}}/webhook` kèm `quote_msg_id` | `quote_msg_id: "msg_goc_001"` | Server lưu đúng ID tin nhắn gốc vào trường `quote_msg_id`. |
| **B1-07** | Sửa / thu hồi tin | Bắn sự kiện edit/undo | `event_name: "undo"` | Server cập nhật cờ `is_deleted` hoặc ghi log thu hồi. |
| **B1-08** | Tin gửi trước khi bot vào | `GET {{botUrl}}/api/bot/groups/{id}/messages` | `count: 50` | Zalo Web API trả về 404 (chặn đọc lịch sử quá khứ). Server fallback lấy tin realtime đã lưu trong DB. |
| **B1-09** | 10 tin liên tiếp trong 1 phút | Chạy Runner 10 request | 10 tin nhắn khác nhau | Hàng đợi FIFO xử lý đủ 10/10 tin, không sót tin nào. |
| **B1-10** | Tắt server 5 phút rồi bật lại | Dừng server 5p ➔ Khởi động lại | Gửi tin trong lúc tắt | Kiểm tra Zalo / ZCA có retry kết nối lại và đẩy bù tin không. |

---

## 3. BÀI TEST 2: BOT ZALO OA TRONG NHÓM (ZALO OA GMF - PORT 8000)

* **Mục tiêu**: Xác nhận Zalo OA nhận được sự kiện trong nhóm A và gửi được tin vào nhóm B.

### Request B2-02: Thành viên gửi tin trong nhóm A
* **Method**: `POST`
* **URL**: `{{baseUrl}}/webhook`
* **Body (`raw` -> `JSON`)**:
```json
{
  "app_id": "zalo_oa_official",
  "event_name": "user_send_group_text",
  "group_id": "group_A_dhvt",
  "sender": {
    "id": "user_lai_xe_01",
    "name": "Lái xe Nguyễn Văn A"
  },
  "timestamp": "1791798010000",
  "quote_msg_id": null,
  "message": {
    "msg_id": "b2_02_msg_001",
    "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2621051 chì 23333878"
  }
}
```
* **Kỳ vọng**: Server trả về `200 OK`, `status: "ENQUEUED_AND_PROCESSED_FIFO"`, lưu `group_id: "group_A_dhvt"`.

---

### Request B2-06: Bot gửi tin chuẩn sang nhóm B
* **Method**: `POST`
* **URL**: `{{botUrl}}/api/bot/send/group`
* **Body (`raw` -> `JSON`)**:
```json
{
  "groupId": "group_B_khach_hang",
  "message": "VSICO - THÔNG TIN XE TRẢ HÀNG - 27/10/2026\nKhách hàng: Nhựa Á Đông\n\n1. Biển số xe: 15C-170.66\n   Tên lái xe: Phạm Văn Huynh - SĐT: 0986******\n   Số cont: VSIU2621051 (20DC)\n   Số chì: 23333878\n   Điểm trả: Kho Nhựa Long An\n   Thời gian dự kiến đến kho: 08:00"
}
```
* **Kỳ vọng**: Tin nhắn hiện chuẩn mẫu không icon trong nhóm B của khách hàng.

---

### Request B2-09: Giả lập Zalo gửi Webhook trùng lặp 2 lần (Idempotency)
* **Method**: `POST`
* **URL**: `{{baseUrl}}/webhook`
* **Thực hiện**: Bấm Send 2 lần với cùng `msg_id: "b2_09_duplicate_001"`.
* **Kỳ vọng**: Lần 1 `PROCESSED_FIFO`, Lần 2 trả về `"status": "DUPLICATE"`, không lưu bản ghi thứ 2 vào MySQL.

---

### Request B2-12: ĐHVT Quote Duyệt "ok" hoặc "sửa chì ..."
* **Method**: `POST`
* **URL**: `{{baseUrl}}/webhook`
* **Body**:
```json
{
  "app_id": "zalo_oa_official",
  "event_name": "user_send_group_text",
  "group_id": "group_dhvt_review",
  "sender": {
    "id": "dhvt_admin_01",
    "name": "Điều Hành VSICO"
  },
  "timestamp": "1791798030000",
  "quote_msg_id": "b2_02_msg_001",
  "message": {
    "msg_id": "dhvt_quote_ok_001",
    "text": "ok",
    "quote_msg_id": "b2_02_msg_001"
  }
}
```
* **Kỳ vọng**: Backend nhận diện lệnh `ok` trích dẫn tin nháp ➔ Kích hoạt phát hành tin gửi cho nhóm B (khách hàng).

---

## 4. PHẦN 3: BỘ 20 TEST CASE DỮ LIỆU ĐẶC TẢ (TC-01 ĐẾN TC-20)

Mỗi test case dưới đây gửi trực tiếp qua `POST {{baseUrl}}/webhook` và nhận kết quả bóc tách ngay lập tức:

### TC-01: F1 - Báo 1 xe miền Bắc ngăn bằng `/`
* **Đầu vào (`message.text`)**:
  ```text
  1 xe 15C17066/ Phạm Văn Huynh đt:  0986713346 / VSIU2621051 chì 23333878
  ```
* **Kỳ vọng**: 
  - Biển số: `15C-170.66` (chuẩn hóa)
  - Tài xế: `Phạm Văn Huynh`
  - SĐT: `0986713346`
  - Cont: `VSIU2621051` (`check_digit_valid: true`)
  - Chì: `23333878`

---

### TC-02: F1 - SĐT dính liền tên tài xế
* **Đầu vào (`message.text`)**:
  ```text
  2 Xe 15h00642 / Đoàn Văn Biên 0984457785/ VSIU2321938 chì 23333310
  ```
* **Kỳ vọng**: Tách riêng tên tài xế `"Đoàn Văn Biên"` và SĐT `"0984457785"`. Biển số viết hoa `"15H-006.42"`.

---

### TC-03: F1 - Có chữ "xe:" và số thứ tự đầu dòng
* **Đầu vào (`message.text`)**:
  ```text
  3 xe: 15H06722/ Đào Đức Thoại đt:  0364461978/ VSIU2323000 chì 23333330
  ```
* **Kỳ vọng**: Bỏ `3 xe:`, SĐT đầu `03` hợp lệ (`0364461978`), cont `VSIU2323000`.

---

### TC-04: F2 - ĐHVT HCM Form có nhãn (Khách qua ký hiệu gọi tắt)
* **Đầu vào (`message.text`)**:
  ```text
  1.  Ngày: .9/10/2026 : Đóng , Trả hàng: Tra 1x20 Nhựa Long An
  - Tên lái xe: Nguyên Thanh Phong
  - Sđt: 0931142873
  -  Số xe: 50H-04915
  - Số cont : VSIU2620327
  -  Số seal:
  - Thời gian xe đến kho: 8h
  ```
* **Kỳ vọng**:
  - `source_format`: `F2`
  - `plan_date`: `2026-10-09` (bỏ dấu chấm thừa `.9/10/2026`)
  - `order_type`: `tra`
  - `customer_raw`: `Nhựa Long An` ➔ map `customer_id: Nhựa Á Đông` qua alias
  - `plate`: `50H-049.15`, tài xế: `Nguyên Thanh Phong`, SĐT: `0931142873`
  - `cont_no`: `VSIU2620327` (đúng ISO 6346), `cont_size`: `20`
  - `seal_no`: `null` (để trống)
  - `eta`: `08:00`

---

### TC-05: F3 - Cú pháp chuẩn mẫu VSICO
* **Đầu vào (`message.text`)**:
  ```text
  Khách hàng: Nhựa Á Đông
  Lệnh: Trả
  Biển số xe: 50H-04915
  Tên lái xe: Nguyễn Thanh Phong
  SĐT: 0931142873
  Số cont: VSIU2620327
  Số chì: 12345678
  Điểm đóng/trả: Kho Nhựa Á Đông – Long An
  Thời gian dự kiến đến kho: 08:00
  ```
* **Kỳ vọng**: Bóc tách chính xác 100% từng trường theo nhãn.

---

### TC-06: Cont sai Check Digit ISO 6346 Modulo 11
* **Đầu vào (`message.text`)**:
  ```text
  1 xe 15C17066/ Phạm Văn Huynh / 0986713346 / VSIU2323001 chì 23333878
  ```
* **Kỳ vọng**: `check_digit_valid: false`. Cảnh báo trong mảng `warnings: ["INVALID_ISO_CHECK_DIGIT"]`. `reply_to_carrier`: Báo nhà xe kiểm tra lại số container.

---

### TC-07: SĐT thiếu số (9 chữ số)
* **Đầu vào (`message.text`)**:
  ```text
  1 xe 15C17066/ Phạm Văn Huynh / 098457785 / VSIU2621051 chì 23333878
  ```
* **Kỳ vọng**: `warnings: ["INVALID_PHONE_LENGTH"]`, yêu cầu nhà xe bổ sung SĐT 10 số.

---

### TC-08: Ghi biển rơ-moóc (`15R...`) ở vị trí biển xe đầu kéo
* **Đầu vào (`message.text`)**:
  ```text
  1 xe 15R01234/ Phạm Văn Huynh / 0986713346 / VSIU2621051 chì 23333878
  ```
* **Kỳ vọng**: Hệ thống nhận diện biển `15R` là rơ-moóc (`trailer_plate`), cảnh báo thiếu biển đầu kéo (`truck_plate`).

---

### TC-09: F2 có ký hiệu khách lạ chưa có trong từ điển
* **Đầu vào (`message.text`)**:
  ```text
  1. Ngày: 27/10/2026 : Trả hàng: Tra 1x20 Nhựa XYZ
  - Tên lái xe: Trần Văn B - Sđt: 0912345678 - Số xe: 15C-12345 - Số cont: VSIU2621051
  ```
* **Kỳ vọng**: Đưa vào hàng chờ ĐHVT (`processing_status: "needs_review"`), không gửi nhầm khách.

---

### TC-10: F1 không có tên khách, không có kho, cont chưa có trong kế hoạch
* **Đầu vào (`message.text`)**:
  ```text
  1 xe 15C12345/ Nguyen Van A / 0912345678 / VSIU2621051 chì 112233
  ```
* **Kỳ vọng**: `needs_review: true`, `reply_to_carrier`: Yêu cầu bổ sung kho hoặc tên khách hàng.

---

### TC-15: Gửi lại cont của TC-04 kèm số seal bổ sung
* **Đầu vào (`message.text`)**:
  ```text
  Bổ sung seal cont VSIU2620327 số chì 99887766
  ```
* **Kỳ vọng**: Cập nhật bản ghi của cont `VSIU2620327`, chuyển trạng thái từ `needs_review` sang `processed`, tạo thông báo Cập Nhật.

---

### TC-16: Tin nhắn rác trao đổi thông thường
* **Đầu vào (`message.text`)**:
  ```text
  ok anh, để em báo tài
  ```
* **Kỳ vọng**: `action: "IGNORE_CHAT"`, không tạo bản ghi xe nào trong hệ thống.

---

## 5. HƯỚNG DẪN IMPORT & CHẠY TRÊN POSTMAN

Tôi đã đóng gói toàn bộ các kịch bản trên vào tệp Postman Collection v2.1:
📁 **File:** [`backend/tests/postman/vsico_zalo_bot_full_20_test_cases.json`](file:///home/datbritget/Documents/vsico_zalo_bot/backend/tests/postman/vsico_zalo_bot_full_20_test_cases.json)

1. Mở Postman ➔ Bấm **Import** ➔ Chọn file `vsico_zalo_bot_full_20_test_cases.json`.
2. Chọn Environment `baseUrl = http://localhost:8000` và `botUrl = http://localhost:3000`.
3. Bấm **Run Collection** để chạy tự động kiểm thử toàn bộ 20 Test Cases!
