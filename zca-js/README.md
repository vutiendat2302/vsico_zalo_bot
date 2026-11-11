# VSICO Zalo Connector Bridge (Module zca-js)

Tài liệu kỹ thuật mô-đun cầu nối tích hợp Zalo cho hệ thống Điều hành Vận tải VSICO TMS.

---

## 1. Tổng quan

Mô-đun `zca-js` đóng vai trò là tầng giao tiếp trung gian (Bridge) giữa nền tảng Zalo và hệ thống xử lý nghiệp vụ Backend Python (FastAPI/HTTP Server) của VSICO.

Mô-đun thực hiện 2 chức năng chính:

1. **Lắng nghe sự kiện hai chiều (Realtime WebSocket Listener)**:
   - Tiếp nhận tin nhắn văn bản, hình ảnh, trích dẫn (quote) từ các nhóm chat nhà xe và khách hàng theo thời gian thực.
   - Chuẩn hóa payload theo chuẩn dữ liệu nội bộ và đẩy tự động sang Webhook Backend Python (`POST /webhook`).
2. **Cung cấp giao diện REST API điều khiển (Outbound & Inspection HTTP Server)**:
   - Cho phép Backend hoặc kỹ sư vận hành gửi tin nhắn trực tiếp đến tài khoản cá nhân hoặc nhóm chat Zalo.
   - Truy vấn thông tin nhóm, danh sách thành viên, danh bạ bạn bè, trạng thái kết nối WebSocket và lịch sử tin nhắn realtime.
   - Tự động hóa tiếp nhận và phê duyệt lời mời kết bạn.

---

## 2. Cấu trúc thư mục

| Tên tệp             | Định dạng        | Mô tả chức năng                                                                                                                                                    |
| :-------------------- | :------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bot_api_server.js` | Node.js (ESM)       | Máy chủ chính: tích hợp đồng thời bộ lắng nghe sự kiện Zalo và dịch vụ HTTP REST API (cổng mặc định 3000 hoặc cấu hình qua biến môi trường). |
| `bridge.js`         | Node.js (ESM)       | Kịch bản chuyển tiếp tối giản: lắng nghe tin nhắn từ Zalo và đẩy thẳng sang Webhook Backend Python kèm cơ chế tự động phản hồi.                   |
| `package.json`      | JSON                | Khai báo gói phụ thuộc (`zca-js`) và các lệnh thực thi chuẩn của dự án.                                                                                  |
| `package-lock.json` | JSON                | Khóa cố định phiên bản các thư viện phụ thuộc đảm bảo tính nhất quán trên mọi môi trường.                                                        |
| `credentials.json`  | JSON *(Tự sinh)* | Lưu trữ phiên đăng nhập (Cookie, IMEI, User-Agent). Tệp này được hệ thống Git bỏ qua nhằm bảo mật tài khoản.                                        |
| `qr.png`            | PNG *(Tự sinh)*  | Hình ảnh mã QR đăng nhập sinh ra khi chưa có phiên đăng nhập hoặc khi phiên cũ hết hạn.                                                               |

---

## 3. Yêu cầu môi trường & Cài đặt

### 3.1. Yêu cầu hệ thống

- Node.js phiên bản 18.0.0 trở lên (khuyến nghị Node.js 20 LTS).
- Trình quản lý gói `npm` (đi kèm Node.js).

### 3.2. Cài đặt các gói phụ thuộc

Tại thư mục gốc của dự án hoặc thư mục `zca-js`, thực hiện lệnh:

```bash
cd zca-js
npm install
```

---

## 4. Hướng dẫn vận hành

### 4.1. Khởi động máy chủ chính (Khuyến nghị)

Khởi động máy chủ REST API kết hợp bộ lắng nghe sự kiện:

```bash
npm start
# Hoặc chạy trực tiếp:
node bot_api_server.js
```

### 4.2. Khởi động kịch bản Bridge tối giản

Trong trường hợp chỉ cần chuyển tiếp tin nhắn một chiều sang Webhook Backend:

```bash
npm run bridge
# Hoặc chạy trực tiếp:
node bridge.js
```

### 4.3. Quy trình đăng nhập Zalo

1. Khi khởi động lần đầu (chưa tồn tại `credentials.json`), hệ thống sẽ tạo tệp `qr.png` trong thư mục `zca-js`.
2. Mở ứng dụng Zalo trên thiết bị di động, chọn tính năng quét mã QR và quét mã tại tệp `qr.png`.
3. Sau khi xác nhận đăng nhập trên điện thoại, hệ thống sẽ tự động lưu thông tin phiên vào `credentials.json`.
4. Trong các lần khởi động tiếp theo, hệ thống tự động tái sử dụng phiên đã lưu mà không yêu cầu quét lại mã.

---

## 5. Danh mục REST API (`bot_api_server.js`)

Mặc định máy chủ phục vụ tại địa chỉ `http://localhost:3000`.

### 5.1. Nhóm kiểm tra hệ thống

- `GET /health` hoặc `GET /api/health` hoặc `GET /api/bot/status`
  - Mô tả: Kiểm tra trạng thái hoạt động của Bot, thông tin tài khoản đăng nhập và trạng thái kết nối WebSocket.

### 5.2. Nhóm quản lý nhóm chat

- `GET /api/bot/groups`
  - Mô tả: Lấy danh sách toàn bộ mã nhóm (groupId) mà tài khoản đang tham gia.
- `GET /api/bot/groups/:groupId/info`
  - Mô tả: Lấy thông tin chi tiết của nhóm chat, danh sách mã thành viên và hồ sơ người dùng trong nhóm.
- `GET /api/bot/groups/:groupId/messages?count=50`
  - Mô tả: Lấy lịch sử tin nhắn trong nhóm chat (tự động chuyển sang bộ nhớ cache realtime nếu Zalo chặn endpoint cũ).
- `GET /api/bot/groups/:groupId/users/:userId/messages?count=100`
  - Mô tả: Lọc các tin nhắn của một thành viên cụ thể trong nhóm chat.

### 5.3. Nhóm quản lý người dùng & Bạn bè

- `GET /api/bot/users?count=1000`
  - Mô tả: Lấy danh sách toàn bộ bạn bè của tài khoản.
- `GET /api/bot/users/:userId`
  - Mô tả: Lấy thông tin hồ sơ chi tiết của một người dùng.
- `GET /api/bot/friends/pending`
  - Mô tả: Lấy danh sách các lời mời kết bạn đang chờ phê duyệt.
- `POST /api/bot/friends/accept`
  - Body: `{"userId": "string"}`
  - Mô tả: Chấp thuận lời mời kết bạn từ người dùng chỉ định.
- `POST /api/bot/friends/request`
  - Body: `{"userId": "string", "message": "string"}`
  - Mô tả: Gửi lời mời kết bạn kèm lời nhắn đến người dùng chỉ định.

### 5.4. Nhóm gửi tin nhắn (Outbound Messaging)

- `POST /api/bot/send/user`
  - Body: `{"userId": "string", "message": "string"}`
  - Mô tả: Gửi tin nhắn trực tiếp đến một người dùng. Có cơ chế tự động gửi lời mời kết bạn nếu người nhận chặn tin nhắn từ người lạ (Mã lỗi Zalo 123).
- `POST /api/bot/send/group`
  - Body: `{"groupId": "string", "message": "string", "quoteMsgId": "string (tùy chọn)"}`
  - Mô tả: Gửi tin nhắn vào nhóm chat, hỗ trợ trích dẫn tin nhắn cũ và tự động fallback sang tin nhắn thường nếu trích dẫn thất bại.

### 5.5. Nhóm bộ nhớ đệm Realtime

- `GET /api/bot/realtime/messages?limit=20`
  - Mô tả: Xem danh sách các tin nhắn vừa nhận được theo thời gian thực được lưu tạm trong bộ nhớ RAM.
- `POST /api/bot/realtime/clear`
  - Mô tả: Xóa sạch hàng đợi tin nhắn tạm trong RAM.

---

## 6. Biến môi trường cấu hình

Các thông số có thể cấu hình thông qua biến môi trường của hệ điều hành hoặc tệp `.env`:

| Tên biến              | Kiểu giá trị | Mặc định                       | Mô tả                                                                |
| :---------------------- | :-------------- | :-------------------------------- | :--------------------------------------------------------------------- |
| `BOT_API_PORT`        | Số nguyên     | `3000`                          | Cổng dịch vụ HTTP REST API của `bot_api_server.js`.              |
| `BACKEND_WEBHOOK_URL` | Chuỗi URL      | `http://localhost:8000/webhook` | Địa chỉ Webhook của Backend Python tiếp nhận tin nhắn từ Zalo. |

---

## 7. Quy trình cập nhật thư viện `zca-js`

Khi nhà phát triển thư viện phát hành phiên bản mới để thích ứng với các thay đổi từ Zalo, tiến hành nâng cấp theo các bước sau:

1. Thực hiện nâng cấp gói:
   ```bash
   cd zca-js
   npm install zca-js@latest
   ```
2. Kiểm tra tính tương thích cú pháp:
   ```bash
   node --check bot_api_server.js
   node --check bridge.js
   ```
3. Lưu vết thay đổi vào hệ thống quản lý phiên bản Git:
   ```bash
   git add package.json package-lock.json
   git commit -m "chore(deps): nang cap thu vien zca-js len phien ban moi nhat"
   ```
