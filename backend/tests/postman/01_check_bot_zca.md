# PHẦN 1: BỘ KIỂM THỬ POSTMAN - CÁC API CỦA BOT ZCA (GROUPS, USERS, MESSAGES, REALTIME)

### HỆ THỐNG VSICO ZALO BOT (ZCA-JS HTTP SERVER - PORT 3000)

Tài liệu này đặc tả chi tiết từng Request trong Postman để kiểm thử các tác vụ của Bot ZCA:

1. Lấy tất cả các `groupId` nhóm
2. Lấy tất cả các `userId` (Bạn bè / Thành viên nhóm)
3. Lấy tất cả tin nhắn của một nhóm & Lọc tin nhắn của `userId` trong `groupId`
4. Gửi tin nhắn đến `userId`
5. Gửi tin nhắn đến `groupId`
6. Lấy tin nhắn Realtime
7. Kiểm tra trạng thái Bot và kết nối WebSocket Zalo

---

## 1. Thiết Lập Môi Trường Postman (Environment)

- **Variable Name**: `bot_url` -> **Initial / Current Value**: `http://localhost:3000`
- **Headers chung** cho tất cả các request `POST`:
  - `Content-Type: application/json; charset=utf-8`

---

## 2. Danh Mục Chi Tiết Các Kịch Bản Kiểm Thử

### Kịch Bản 1: Kiểm Tra Trạng Thái Bot & WebSocket

- **Tên Request**: `01. Kiểm tra trạng thái Bot & WebSocket`
- **Method**: `GET`
- **URL**: `{{bot_url}}/api/bot/status`
- **Headers / Bảo mật**: Không yêu cầu
- **Params / Body**: Không có
- **Kết quả mong đợi**: HTTP `200 OK`
  ```json
  {
    "ok": true,
    "status": "RUNNING",
    "websocket_connected": true,
    "bot_user": {
      "userId": "1001000000000000001",
      "name": "Bot VSICO",
      "avatar": "https://..."
    },
    "realtime_cached_count": 0
  }
  ```

---

### Kịch Bản 2: Lấy Tất Cả Các `groupId` Nhóm

- **Tên Request**: `02. Lấy tất cả Group IDs`
- **Method**: `GET`
- **URL**: `{{bot_url}}/api/bot/groups`
- **Headers / Bảo mật**: Không yêu cầu
- **Params / Body**: Không có
- **Postman Tests Script**:
  ```javascript
  pm.test("Status code is 200", () => pm.response.to.have.status(200));
  pm.test("Có danh sách group_ids", () => {
      const json = pm.response.json();
      pm.expect(json.ok).to.be.true;
      pm.expect(json.group_ids).to.be.an('array');
      if (json.group_ids.length > 0) {
          pm.environment.set("group_id", json.group_ids[0]);
      }
  });
  ```
- **Kết quả mong đợi**: HTTP `200 OK`
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

---

### Kịch Bản 3: Lấy Thông Tin Chi Tiết Nhóm & Danh Sách Thành Viên

- **Tên Request**: `03. Lấy chi tiết nhóm và thành viên`
- **Method**: `GET`
- **URL**: `{{bot_url}}/api/bot/groups/{{group_id}}/info`
- **Headers / Bảo mật**: Không yêu cầu
- **Params / Body**:
  - Path variable: `group_id` (ví dụ: `2001000000000000001`)
- **Kết quả mong đợi**: HTTP `200 OK`
  ```json
  {
    "ok": true,
    "group_id": "2001000000000000001",
    "data": {
      "grid": "2001000000000000001",
      "name": "Nhóm Vận Tải Hải Long - VSICO",
      "totalMember": 15,
      "memVerList": [
        "1001000000000000001_0",
        "1002000000000000002_0"
      ]
    }
  }
  ```

---

### Kịch Bản 4: Lấy Tất Cả Các `userId` (Danh Bạ Bạn Bè)

- **Tên Request**: `04. Lấy tất cả User IDs (Bạn bè)`
- **Method**: `GET`
- **URL**: `{{bot_url}}/api/bot/users`
- **Headers / Bảo mật**: Không yêu cầu
- **Params / Body**:
  - Query Params: `count=1000`
- **Postman Tests Script**:
  ```javascript
  pm.test("Status code is 200", () => pm.response.to.have.status(200));
  pm.test("Lưu user_id vào environment", () => {
      const json = pm.response.json();
      if (json.user_ids && json.user_ids.length > 0) {
          pm.environment.set("user_id", json.user_ids[0]);
      }
  });
  ```
- **Kết quả mong đợi**: HTTP `200 OK`
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
        "zaloName": "Hải Long Vận Tải",
        "avatar": "https://..."
      }
    ]
  }
  ```

---

### Kịch Bản 5: Lấy Tất Cả Tin Nhắn Trong Một `groupId`

- **Tên Request**: `05. Lấy lịch sử tin nhắn trong nhóm`
- **Method**: `GET`
- **URL**: `{{bot_url}}/api/bot/groups/{{group_id}}/messages`
- **Headers / Bảo mật**: Không yêu cầu
- **Params / Body**:
  - Path variable: `group_id` (ví dụ: `2001000000000000001`)
  - Query Params: `count=50`
- **Kết quả mong đợi**: HTTP `200 OK`
  ```json
  {
    "ok": true,
    "group_id": "2001000000000000001",
    "total_messages": 2,
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

### Kịch Bản 6: Lấy Tất Cả Tin Nhắn Của `userId` Trong Một `groupId`

- **Tên Request**: `06. Lấy tin nhắn của UserId cụ thể trong GroupId`
- **Method**: `GET`
- **URL**: `{{bot_url}}/api/bot/groups/{{group_id}}/users/{{user_id}}/messages`
- **Headers / Bảo mật**: Không yêu cầu
- **Params / Body**:
  - Path variables: `group_id` (ví dụ: `2001000000000000001`), `user_id` (ví dụ: `1001000000000000001`)
  - Query Params: `count=100`
- **Kết quả mong đợi**: HTTP `200 OK`
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

### Kịch Bản 7: Gửi Tin Nhắn Đến `userId` (Chat 1-1 Cá Nhân)

- **Tên Request**: `07. Gửi tin nhắn đến UserId`
- **Method**: `POST`
- **URL**: `{{bot_url}}/api/bot/send/user`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body** (`raw` -> `JSON`):
  ```json
  {
    "userId": "1001000000000000001",
    "message": "Xin chào! Đây là tin nhắn tự động từ Bot VSICO TMS gửi riêng cho bạn."
  }
  ```
- **Kết quả mong đợi**: HTTP `200 OK`
  ```json
  {
    "ok": true,
    "message": "Đã gửi tin nhắn đến userId thành công",
    "recipient_id": "1001000000000000001",
    "result": {
      "message": {
        "msgId": 123456789
      },
      "attachment": []
    }
  }
  ```

---

### Kịch Bản 8: Gửi Tin Nhắn Đến `groupId` (Chat Nhóm)

- **Tên Request**: `08. Gửi tin nhắn đến GroupId`
- **Method**: `POST`
- **URL**: `{{bot_url}}/api/bot/send/group`
- **Headers / Bảo mật**:
  - `Content-Type: application/json`
- **Params / Body** (`raw` -> `JSON`):
  ```json
  {
    "groupId": "2001000000000000001",
    "message": "THÔNG BÁO TỪ HỆ THỐNG:\nChuyến cont VSIU7399796 đã được tiếp nhận và xử lý thành công."
  }
  ```
- **Kết quả mong đợi**: HTTP `200 OK`
  ```json
  {
    "ok": true,
    "message": "Đã gửi tin nhắn đến groupId thành công",
    "group_id": "2001000000000000001",
    "result": {
      "message": {
        "msgId": 987654321
      },
      "attachment": []
    }
  }
  ```

---

### Kịch Bản 9: Lấy Danh Sách Tin Nhắn Realtime Đã Bắt Được

- **Tên Request**: `09. Lấy tin nhắn Realtime mới nhất`
- **Method**: `GET`
- **URL**: `{{bot_url}}/api/bot/realtime/messages`
- **Headers / Bảo mật**: Không yêu cầu
- **Params / Body**:
  - Query Params: `limit=20`
- **Kết quả mong đợi**: HTTP `200 OK`
  ```json
  {
    "ok": true,
    "total_cached": 1,
    "messages": [
      {
        "id": "msg_zalo_12345",
        "threadId": "2001000000000000001",
        "type": "group",
        "senderId": "1001000000000000001",
        "senderName": "Điều hành Hải Long",
        "content": "TRẢ HÀNG cont VSIU7399796 xe 15C-878.99",
        "timestamp": "1791798010000",
        "receivedAt": "2026-10-27T04:40:00.000Z"
      }
    ]
  }
  ```
