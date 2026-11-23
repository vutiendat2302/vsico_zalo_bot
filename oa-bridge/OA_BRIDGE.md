# Đặc tả Kỹ thuật Cầu nối Zalo Official Account (`oa-bridge` v1.5.0)

Module `oa-bridge` là dịch vụ cầu nối viết bằng **Node.js (ESM)**, đóng vai trò trung gian giao tiếp hai chiều giữa nền tảng **Zalo Official Account (OA)** — bao gồm cả nhóm chat GMF (Group Message Feature) và hội thoại cá nhân 1-1 (`direct_<user_id>`) — với phân hệ `backend` FastAPI.

---

## 1. Kiến trúc & Chức năng Chính

1. **Tiếp nhận Webhook từ Zalo OA (`POST /webhook/zalo-oa`)**:
   - Nhận sự kiện thời gian thực từ máy chủ Zalo OA (tin nhắn văn bản, hình ảnh, trích dẫn/quote tin nhắn trong nhóm GMF hoặc chat cá nhân 1-1).
   - Tự động lưu trữ danh sách nhóm GMF và các cuộc trò chuyện cá nhân (`direct_<user_id>`) đang hoạt động.
   - Chuẩn hóa payload về định dạng chuẩn của hệ thống và chuyển tiếp tức thời sang `POST /webhook` của `backend` kèm header bảo mật `X-Webhook-Secret`.
2. **Đồng bộ Danh sách Nhóm Thực tế (`GET /api/bot/groups`)**:
   - Kết nối trực tiếp tới Zalo OA GMF API (`https://openapi.zalo.me/v3.0/oa/group/getgroupsofoa`) để lấy danh sách nhóm thật của OA (tên nhóm, `group_id`, `total_member`, `group_link`, `status`).
   - Kết hợp cùng danh sách hội thoại cá nhân (`type: "oa_direct"`, `group_id: "direct_<userId>"`) và trả về cho `backend` khi `GET /api/groups` gọi đồng bộ tự động (`sync_live_groups_from_bridge`).
3. **Chi tiết Nhóm & Thành viên (`GET /api/bot/groups/:groupId/info`, `/members`, `/messages`)**:
   - Truy vấn thông tin chi tiết nhóm, danh sách thành viên và lịch sử tin nhắn (hoặc cache realtime) phục vụ hiển thị trên màn hình Quản lý Nhóm Zalo (`/groups`) của Frontend Dashboard và Watchdog.
4. **Phát hành Tin nhắn & Ảnh PNG (`POST /api/bot/send/group`, `POST /api/bot/send/user`)**:
   - Nhận lệnh gửi tin văn bản hoặc ảnh báo cáo PNG (`imageUrl`) từ `ZaloOutboundThrottler` của `backend` và tự động phân nhánh gửi vào nhóm GMF hoặc gửi tin nhắn trực tiếp 1-1 (`direct_<user_id>`) qua Zalo OA OpenAPI.

---

## 2. Sơ đồ Luồng Hoạt động

```mermaid
sequenceDiagram
    autonumber
    participant Zalo as Zalo OA Cloud (GMF Group & Direct 1-1)
    participant OAB as oa-bridge (Node.js :3000)
    participant BE as Backend FastAPI (:8000)
    participant FE as Frontend Web (/groups)

    Zalo->>OAB: Sự kiện Webhook (Tin nhắn nhóm GMF / Chat 1-1)
    OAB->>OAB: Ghi nhận trạng thái nhóm / direct_<user_id>
    OAB->>BE: POST /webhook (Header X-Webhook-Secret)
    BE-->>OAB: 200 OK (< 50ms)

    FE->>BE: GET /api/groups
    BE->>OAB: GET /api/bot/groups
    OAB->>Zalo: GET /v3.0/oa/group/getgroupsofoa
    Zalo-->>OAB: Danh sách nhóm thật của OA
    OAB-->>BE: Trả về danh sách nhóm GMF + direct_<user_id>
    BE->>BE: Đồng bộ vào bảng zalo_groups (SOURCE / TARGET / DHVT / DIRECT_CHAT)
    BE-->>FE: Hiển thị danh sách nhóm thực tế

    BE->>OAB: POST /api/bot/send/group (groupId, message, imageUrl, quoteMsgId)
    OAB->>Zalo: Gửi tin nhắn GMF hoặc OA Direct Message
    Zalo-->>OAB: Trả về message_id
    OAB-->>BE: { ok: true, messageId }
```

---

## 3. Danh sách Endpoint của `oa-bridge`

| Phương thức & Đường dẫn | Mô tả chức năng |
| :--- | :--- |
| `GET /health`, `/api/health`, `/api/bot/status` | Kiểm tra trạng thái kết nối và cấu hình Zalo OA Access Token (phục vụ `ZaloOaWatchdog`). |
| `GET /api/oa/test-connection` | Kiểm tra nhanh kết nối tới Zalo OA OpenAPI (`getOaInfo`). |
| `GET /webhook/zalo-oa`, `POST /webhook/zalo-oa` | Xác minh Webhook (`GET`) và tiếp nhận sự kiện Webhook từ Zalo OA (`POST`). |
| `GET /api/bot/groups` | Trả về toàn bộ nhóm GMF thực tế của OA và các hội thoại `direct_<user_id>`. |
| `GET /api/bot/groups/:groupId/info` | Trả về thông tin chi tiết của một nhóm GMF hoặc hội thoại trực tiếp. |
| `GET /api/bot/groups/:groupId/members` | Trả về danh sách thành viên trong một nhóm GMF. |
| `GET /api/bot/groups/:groupId/messages` | Lấy lịch sử tin nhắn của nhóm GMF hoặc hội thoại `direct_<user_id>`. |
| `GET /api/bot/users`, `GET /api/bot/users/:userId` | Lấy danh sách hoặc thông tin chi tiết người dùng đang quan tâm OA. |
| `GET /api/bot/realtime/messages`, `POST /api/bot/realtime/clear` | Tra cứu hoặc xóa bộ nhớ đệm tin nhắn realtime. |
| `POST /api/bot/send/group` | Gửi tin nhắn văn bản hoặc ảnh (`imageUrl`, kèm `quoteMsgId` nếu có) vào nhóm GMF hoặc `direct_<user_id>`. |
| `POST /api/bot/send/user` | Gửi tin nhắn trực tiếp 1-1 tới `userId`. |
| `GET /zalo_verifier<ID>.html` | Phục vụ tệp xác minh tên miền Zalo OA nếu tồn tại trên thư mục gốc bridge. |

---

## 4. Khởi chạy Dịch vụ

Cấu hình các biến `ZALO_OA_APP_ID`, `ZALO_OA_SECRET_KEY`, `ZALO_OA_ACCESS_TOKEN`, `ZALO_OA_REFRESH_TOKEN`, `ZALO_BRIDGE_PORT=3000` và `BACKEND_WEBHOOK_URL=http://localhost:8000/webhook` tại tệp `.env` ở thư mục gốc dự án:

```bash
cd oa-bridge
npm install
npm start
```
