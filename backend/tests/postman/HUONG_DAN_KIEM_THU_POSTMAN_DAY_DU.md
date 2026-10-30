# 📮 TỔNG HỢP TOÀN DIỆN: TÀI LIỆU KIỂM THỬ POSTMAN — BOT ZCA & BACKEND
### DỰ ÁN BOT ZALO TMS VSICO (MODULE 1: `zca-js` & MODULE 2: `backend`)

Tài liệu này cung cấp hướng dẫn kiểm thử chi tiết từng phần trên **Postman** cho toàn bộ hệ thống Bot ZCA và Cổng Webhook Backend, bao gồm:
- **Phần 1**: Các API tương tác trực tiếp với Bot ZCA (`bot_api_server.js` - Cổng 3000)
- **Phần 2**: Cổng Webhook Gateway và Quy trình Nghiệp vụ (`main.py` - Cổng 8000)
- **Phần 3**: Danh mục biến môi trường và Tệp Collection JSON sẵn sàng Import vào Postman

---

## 1. Thiết Lập Môi Trường Kiểm Thử (Environment Setup)

### 1.1. Khởi động 2 máy chủ độc lập

Mở 2 cửa sổ Terminal độc lập:

* **Terminal 1: Khởi động HTTP REST API cho Bot ZCA (Port 3000)**
  ```bash
  cd /home/datbritget/Documents/vsico_zalo_bot/zca-js
  node bot_api_server.js
  ```
  *(Khi khởi động, server tự động đọc `credentials.json` để kết nối WebSocket Zalo và mở cổng REST API 3000).*

* **Terminal 2: Khởi động Backend Python Webhook Gateway (Port 8000)**
  ```bash
  cd /home/datbritget/Documents/vsico_zalo_bot/backend
  .venv/bin/python run.py
  ```

---

### 1.2. Cấu hình Environment trong Postman

Tạo một Environment mới trong Postman đặt tên là: `VSICO_Zalo_Bot_Env` với các biến:

| Variable Name | Giá trị khởi tạo (Initial Value) | Ý nghĩa |
| :--- | :--- | :--- |
| `bot_url` | `http://localhost:3000` | URL máy chủ điều khiển Bot ZCA |
| `backend_url` | `http://localhost:8000` | URL máy chủ Backend Python Webhook |
| `group_id` | `2001000000000000001` | ID nhóm Zalo test (sẽ tự động gán khi gọi API) |
| `user_id` | `1001000000000000001` | ID người dùng Zalo test (sẽ tự động gán) |

---

## 2. PHẦN 1: KIỂM THỬ CÁC API CỦA BOT ZCA (PORT 3000)

---

### Request 1.1: Kiểm tra trạng thái Bot và kết nối WebSocket Zalo
* **Tên Request**: `01. Bot ZCA - Status`
* **Method**: `GET`
* **URL**: `{{bot_url}}/api/bot/status`
* **Header**: Không yêu cầu
* **cURL Command**:
  ```bash
  curl -X GET http://localhost:3000/api/bot/status
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "status": "RUNNING",
    "websocket_connected": true,
    "bot_user": {
      "userId": "1001000000000000001",
      "name": "Bot VSICO TMS"
    },
    "realtime_cached_count": 0
  }
  ```

---

### Request 1.2: Lấy tất cả `groupId` của các nhóm Bot đang tham gia
* **Tên Request**: `02. Bot ZCA - Lấy tất cả Group IDs`
* **Method**: `GET`
* **URL**: `{{bot_url}}/api/bot/groups`
* **Mục đích**: Gọi trực tiếp hàm `api.getAllGroups()` của `zca-js` để lấy toàn bộ ID các nhóm Zalo.
* **cURL Command**:
  ```bash
  curl -X GET http://localhost:3000/api/bot/groups
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "total_groups": 3,
    "group_ids": [
      "2001000000000000001",
      "2002000000000000001",
      "3001000000000000001"
    ],
    "grid_ver_map": {
      "2001000000000000001": "1729000000",
      "2002000000000000001": "1729000050",
      "3001000000000000001": "1729000099"
    }
  }
  ```
* **Postman Tests Script**:
  ```javascript
  const res = pm.response.json();
  if (res.group_ids && res.group_ids.length > 0) {
      pm.environment.set("group_id", res.group_ids[0]);
  }
  ```

---

### Request 1.3: Lấy thông tin chi tiết nhóm và danh sách thành viên
* **Tên Request**: `03. Bot ZCA - Lấy chi tiết Group và Thành viên`
* **Method**: `GET`
* **URL**: `{{bot_url}}/api/bot/groups/{{group_id}}/info`
* **Mục đích**: Gọi `api.getGroupInfo(groupId)` để lấy danh sách `memVerList` chứa `userId` thành viên.
* **cURL Command**:
  ```bash
  curl -X GET http://localhost:3000/api/bot/groups/2001000000000000001/info
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "group_id": "2001000000000000001",
    "data": {
      "grid": "2001000000000000001",
      "name": "Nhóm Vận Tải Hải Long - VSICO",
      "totalMember": 12,
      "memVerList": [
        "1001000000000000001_0",
        "1002000000000000002_0"
      ]
    }
  }
  ```

---

### Request 1.4: Lấy tất cả `userId` (Danh bạ bạn bè của Bot)
* **Tên Request**: `04. Bot ZCA - Lấy tất cả User IDs (Bạn bè)`
* **Method**: `GET`
* **URL**: `{{bot_url}}/api/bot/users?count=1000`
* **Mục đích**: Gọi `api.getAllFriends()` để trích xuất danh sách tất cả bạn bè Zalo của bot.
* **cURL Command**:
  ```bash
  curl -X GET "http://localhost:3000/api/bot/users?count=1000"
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "total_users": 2,
    "user_ids": [
      "1001000000000000001",
      "1002000000000000002"
    ],
    "users": [
      {
        "userId": "1001000000000000001",
        "displayName": "Điều hành Hải Long",
        "zaloName": "Hải Long Vận Tải"
      }
    ]
  }
  ```
* **Postman Tests Script**:
  ```javascript
  const res = pm.response.json();
  if (res.user_ids && res.user_ids.length > 0) {
      pm.environment.set("user_id", res.user_ids[0]);
  }
  ```

---

### Request 1.5: Lấy lịch sử tất cả tin nhắn trong một nhóm
* **Tên Request**: `05. Bot ZCA - Lịch sử tin nhắn nhóm`
* **Method**: `GET`
* **URL**: `{{bot_url}}/api/bot/groups/{{group_id}}/messages?count=50`
* **Mục đích**: Gọi `api.getGroupChatHistory(groupId, count)` để lấy các tin nhắn gần nhất.
* **cURL Command**:
  ```bash
  curl -X GET "http://localhost:3000/api/bot/groups/2001000000000000001/messages?count=50"
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "group_id": "2001000000000000001",
    "total_messages": 1,
    "messages": [
      {
        "msg_id": "msg_001",
        "sender_id": "1001000000000000001",
        "sender_name": "Điều hành Hải Long",
        "content": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903******",
        "timestamp": "1791798010000"
      }
    ]
  }
  ```

---

### Request 1.6: Lấy tất cả tin nhắn của `userId` cụ thể trong một nhóm
* **Tên Request**: `06. Bot ZCA - Tin nhắn của UserId trong Group`
* **Method**: `GET`
* **URL**: `{{bot_url}}/api/bot/groups/{{group_id}}/users/{{user_id}}/messages?count=100`
* **Mục đích**: Lấy lịch sử nhóm và lọc chính xác các tin nhắn do `userId` gửi.
* **cURL Command**:
  ```bash
  curl -X GET "http://localhost:3000/api/bot/groups/2001000000000000001/users/1001000000000000001/messages?count=100"
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "group_id": "2001000000000000001",
    "user_id": "1001000000000000001",
    "matched_messages_count": 1,
    "messages": [
      {
        "msg_id": "msg_001",
        "sender_id": "1001000000000000001",
        "sender_name": "Điều hành Hải Long",
        "content": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903******",
        "timestamp": "1791798010000"
      }
    ]
  }
  ```

---

### Request 1.7: Gửi tin nhắn đến `userId` (Chat 1-1)
* **Tên Request**: `07. Bot ZCA - Gửi tin nhắn đến UserId`
* **Method**: `POST`
* **URL**: `{{bot_url}}/api/bot/send/user`
* **Header**: `Content-Type: application/json`
* **Body (`raw` -> `JSON`)**:
  ```json
  {
    "userId": "{{user_id}}",
    "message": "Xin chào! Đây là tin nhắn tự động từ Bot VSICO TMS gửi riêng cho bạn."
  }
  ```
* **cURL Command**:
  ```bash
  curl -X POST http://localhost:3000/api/bot/send/user \
    -H "Content-Type: application/json" \
    -d '{
      "userId": "1001000000000000001",
      "message": "Xin chào! Đây là tin nhắn tự động từ Bot VSICO TMS gửi riêng cho bạn."
    }'
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "message": "Đã gửi tin nhắn đến userId thành công",
    "recipient_id": "1001000000000000001",
    "result": {
      "message": { "msgId": 123456789 },
      "attachment": []
    }
  }
  ```

---

### Request 1.8: Gửi tin nhắn đến `groupId` (Chat Nhóm)
* **Tên Request**: `08. Bot ZCA - Gửi tin nhắn đến GroupId`
* **Method**: `POST`
* **URL**: `{{bot_url}}/api/bot/send/group`
* **Header**: `Content-Type: application/json`
* **Body (`raw` -> `JSON`)**:
  ```json
  {
    "groupId": "{{group_id}}",
    "message": "THÔNG BÁO TỪ HỆ THỐNG:\nChuyến cont VSIU7399796 đã được tiếp nhận và xử lý thành công."
  }
  ```
* **cURL Command**:
  ```bash
  curl -X POST http://localhost:3000/api/bot/send/group \
    -H "Content-Type: application/json" \
    -d '{
      "groupId": "2001000000000000001",
      "message": "THÔNG BÁO TỪ HỆ THỐNG:\nChuyến cont VSIU7399796 đã được tiếp nhận và xử lý thành công."
    }'
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "message": "Đã gửi tin nhắn đến groupId thành công",
    "group_id": "2001000000000000001",
    "result": {
      "message": { "msgId": 987654321 },
      "attachment": []
    }
  }
  ```

---

### Request 1.9: Lấy danh sách tin nhắn bắt được Realtime
* **Tên Request**: `09. Bot ZCA - Tin nhắn Realtime mới nhất`
* **Method**: `GET`
* **URL**: `{{bot_url}}/api/bot/realtime/messages?limit=20`
* **Mục đích**: Kiểm tra các tin nhắn vừa nhắn trên Zalo mà WebSocket của Bot đã bắt được trong bộ nhớ đệm.
* **cURL Command**:
  ```bash
  curl -X GET "http://localhost:3000/api/bot/realtime/messages?limit=20"
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "total_cached": 1,
    "messages": [
      {
        "id": "msg_001",
        "threadId": "2001000000000000001",
        "type": "group",
        "senderId": "1001000000000000001",
        "senderName": "Điều hành Hải Long",
        "content": "TRẢ HÀNG\nCont: VSIU7399796...",
        "timestamp": "1791798010000",
        "receivedAt": "2026-10-27T04:40:00.000Z"
      }
    ]
  }
  ```

---

## 3. PHẦN 2: KIỂM THỬ CỔNG WEBHOOK GATEWAY & BACKEND PYTHON (PORT 8000)

---

### Request 2.1: Kiểm tra kết nối MySQL Backend
* **Method**: `GET`
* **URL**: `{{backend_url}}/api/health`
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "status": "UP",
    "database": "mysql_connected",
    "stats": {
      "total_groups": 1,
      "total_messages": 1
    }
  }
  ```

---

### Request 2.2: Tiếp nhận Webhook báo xe chuẩn 1 xe (Happy Path)
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Header**: `Content-Type: application/json; charset=utf-8`
* **Body (`raw` -> `JSON`)**:
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
    "quote_msg_id": null,
    "message": {
      "msg_id": "zalo_webhook_test_001",
      "text": "TRẢ HÀNG\nCont: VSIU7399796\nSeal: 73957169\nBiển số: 15C-878.99\nTài xế: Trần Quốc Bảo\nSĐT: 0903976359\nGiờ đến: 08:00 14/10/2026"
    }
  }
  ```
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "status": "success",
    "data": {
      "id": 1,
      "msg_id": "zalo_webhook_test_001",
      "action": "STORED_RAW",
      "processing_status": "received",
      "reason": "Đã lưu tin nhắn thô vào bảng zalo_messages trong MySQL thành công"
    }
  }
  ```

---

### Request 2.3: Kiểm tra chống trùng lặp Webhook (Idempotency)
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Mô tả**: Gửi lại chính xác body ở **Request 2.2** với cùng `msg_id: "zalo_webhook_test_001"`.
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "status": "success",
    "data": {
      "id": 1,
      "msg_id": "zalo_webhook_test_001",
      "action": "DUPLICATE_MESSAGE",
      "processing_status": "received",
      "reason": "Tin nhắn đã tồn tại trong MySQL, bỏ qua xử lý trùng lặp"
    }
  }
  ```

---

### Request 2.4: ĐHVT Quote Duyệt Tin Nháp ('ok')
* **Method**: `POST`
* **URL**: `{{backend_url}}/webhook`
* **Body (`raw` -> `JSON`)**:
  ```json
  {
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "2000000000000000001",
    "sender": {
      "id": "9001000000000000001",
      "name": "Điều Hành VSICO"
    },
    "timestamp": "1791798030000",
    "quote_msg_id": "zalo_webhook_test_001",
    "message": {
      "msg_id": "dhvt_quote_ok_001",
      "text": "ok",
      "quote_msg_id": "zalo_webhook_test_001"
    }
  }
  ```

---

### Request 2.5: Tra cứu danh sách tin thô đã lưu trong MySQL
* **Method**: `GET`
* **URL**: `{{backend_url}}/api/messages?limit=20`
* **Response Kỳ Vọng (`200 OK`)**:
  ```json
  {
    "ok": true,
    "total_returned": 2,
    "items": [
      {
        "id": 1,
        "zalo_message_id": "zalo_webhook_test_001",
        "group_id": "2001000000000000001",
        "sender_id": "1001000000000000001",
        "sender_name": "Điều hành Hải Long",
        "message_text": "TRẢ HÀNG\nCont: VSIU7399796...",
        "processing_status": "received",
        "received_at": "2026-10-27T04:26:50+00:00"
      }
    ]
  }
  ```

---

## 4. Hướng Dẫn Import Bộ Collection Vào Phần Mềm Postman

1. Mở phần mềm **Postman**.
2. Bấm vào nút **Import** ở góc trên bên trái.
3. Chọn tệp JSON đã được tạo sẵn trong dự án:
   `backend/tests/postman/vsico_zalo_bot_postman_collection.json`
4. Chọn **Environment** là `VSICO_Zalo_Bot_Env` với `bot_url = http://localhost:3000` và `backend_url = http://localhost:8000`.
5. Bạn có thể nhấn vào từng Request để gửi, hoặc bấm **Run Collection** để chạy tự động toàn bộ 18 test cases liên hoàn!
