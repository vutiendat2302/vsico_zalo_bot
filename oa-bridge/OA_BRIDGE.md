# VSICO Zalo OA Bridge (`oa-bridge`)

Mô-đun cầu nối cho **Zalo Official Account (API v3)**, giữ nguyên hợp đồng giao tiếp với lõi Backend FastAPI và bộ REST API tương thích `zca-js` để có thể chuyển đổi qua lại mà không sửa đổi lõi Backend hay `zca-js`.

---

## 1. Cấu trúc tệp

| Tệp | Vai trò |
| :--- | :--- |
| `oa_server.js` | HTTP Server (mặc định cổng `3000`): nhận Webhook OA (`/webhook/zalo-oa`) đẩy sang Backend (`/webhook`), đồng thời cung cấp đầy đủ các API `/api/bot/*` tương thích `zca-js`. |
| `oa_client.js` | Gọi Zalo OpenAPI (`getoa`, `message/cs`, `user/detail`, `user/getlist`, `listrecentchat`, `conversation`), tự động refresh token khi gặp mã lỗi hết hạn (`-216`, `-124`). |
| `token_manager.js` | Quản lý vòng đời `ZALO_OA_ACCESS_TOKEN` / `ZALO_OA_REFRESH_TOKEN`, tự động làm mới và cập nhật trực tiếp vào tệp `.env` gốc. |
| `env_loader.js` | Đọc biến môi trường từ tệp `.env` duy nhất ở thư mục gốc dự án. |
| `package.json` | Khai báo lệnh `npm start` và `npm run test-oa`. |

---

## 2. Danh mục REST API (tương thích `zca-js`)

| STT | Method & Endpoint | Chức năng trên Zalo OA |
| :---: | :--- | :--- |
| 1 | `GET /health`, `GET /api/health`, `GET /api/bot/status` | Kiểm tra trạng thái Bridge và thông tin kết nối Zalo OA |
| 2 | `GET /api/bot/groups` | Danh sách hội thoại gần nhất (quy đổi thành `direct_<user_id>`) |
| 3 | `GET /api/bot/groups/:groupId/info` | Chi tiết nhóm GMF (kèm thành viên nếu có quyền) hoặc hồ sơ `direct_<user_id>` |
| 3b | `GET /api/bot/groups/:groupId/members` | Lấy danh sách thành viên theo `groupId` (`?offset=0&count=50`) |
| 4 | `GET /api/bot/users` | Danh sách người dùng đang quan tâm OA (followers) |
| 5 | `GET /api/bot/users/:userId` | Hồ sơ chi tiết một người dùng OA |
| 6 | `GET /api/bot/groups/:groupId/messages` | Lịch sử tin nhắn trong hội thoại `direct_<user_id>` |
| 7 | `GET /api/bot/groups/:groupId/users/:userId/messages` | Lọc tin nhắn của `userId` trong hội thoại `groupId` |
| 8 | `POST /api/bot/send/user` | Gửi tin nhắn 1-1 tới `userId` (`{"userId", "message", "quoteMsgId?"}`) |
| 9 | `POST /api/bot/send/group` | Gửi tin nhắn tới `groupId` (hỗ trợ `direct_<user_id>`) |
| 10 | `GET /api/bot/realtime/messages`, `POST /api/bot/realtime/clear` | Xem / xóa bộ nhớ đệm tin nhắn realtime từ Webhook OA |
| 11 | `POST /webhook/zalo-oa` | Cổng nhận Webhook từ Zalo OA và forward sang Backend `/webhook` |

---

## 3. Chạy và kiểm tra kết nối

1. Kiểm tra kết nối trực tiếp tới Zalo OA:

```bash
cd oa-bridge
npm run test-oa
```

2. Khởi động Bridge (lưu ý tắt `zca-js` nếu cùng dùng cổng `3000`, hoặc đặt `OA_BRIDGE_PORT` riêng):

```bash
cd oa-bridge
npm start
```

3. Cấu hình Webhook trên `developers.zalo.me` trỏ vào `https://<domain>/webhook/zalo-oa` và điền `ZALO_OA_SECRET_KEY` vào `.env`.
