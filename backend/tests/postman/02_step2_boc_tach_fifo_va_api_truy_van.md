# Hướng Dẫn Kiểm Thử Postman — Bước 2: Bóc Tách Dữ Liệu FIFO Thời Gian Thực & 4 API Truy Vấn Tin Nhắn Theo Thời Gian

Tài liệu này hướng dẫn kiểm thử trực tiếp trên **Postman** cho toàn bộ luồng **Bước 2**:
1. Tiếp nhận tin nhắn Zalo thời gian thực (cả nhắn trực tiếp 1-1 và nhắn trong Group) qua `POST /webhook`.
2. Bóc tách tuần tự **Vào Trước - Ra Trước (FIFO)** ngay lập tức và lưu vào các bảng MySQL (`zalo_messages`, `extraction_runs`, `truck_records`, `container_jobs`, `review_cases`, `bot_replies`).
3. Kiểm thử **4 API lấy tin nhắn kèm dữ liệu đã bóc tách** (hỗ trợ cả không nhập thời gian để lấy hết, và nhập khoảng thời gian `from_time` / `to_time`).

---

## 0. Thông Tin Máy Chủ Cơ Bản

- **Base URL**: `http://localhost:8000`
- **Swagger UI trực quan**: `http://localhost:8000/docs`
- **Kiểm tra trạng thái hệ thống & hàng đợi FIFO**:
  - **Method**: `GET`
  - **URL**: `http://localhost:8000/api/health`

---

## 1. Giả Lập Gửi Tin Nhắn Qua Webhook & Bóc Tách FIFO Tức Thời

### 1.1. Gửi tin nhắn trong Group Zalo (Đa xe, hợp lệ chuẩn ISO 6346)

- **Method**: `POST`
- **URL**: `http://localhost:8000/webhook`
- **Headers**: `Content-Type: application/json`
- **Body (raw JSON)**:
```json
{
  "msg_id": "postman_fifo_001",
  "group_id": "group_nhaxe_haiphong_01",
  "group_name": "Nhóm Nhà Xe Hải Phòng",
  "sender_id": "user_dieuvan_bao",
  "sender_name": "Anh Bảo Điều Vận",
  "text": "Đóng hàng khách Sun Paper tại Kho 3B\n15C-878.99 / Trần Quốc Bảo / 0903976359 / VSIU7399796 / 40HC\n15H-008.14 / Nguyễn Văn Minh / 0912345678 / MSCU5285725 / 20DC",
  "timestamp": "2026-10-27T08:30:00"
}
```

### 1.2. Gửi tin nhắn nhắn riêng trực tiếp 1-1 (Không truyền `group_id`)

- **Method**: `POST`
- **URL**: `http://localhost:8000/webhook`
- **Headers**: `Content-Type: application/json`
- **Body (raw JSON)**:
```json
{
  "msg_id": "postman_fifo_002",
  "group_id": "",
  "sender_id": "user_taixe_hung",
  "sender_name": "Tài Xế Phạm Hùng",
  "text": "Trả hàng tại Kho Tiên Sơn\nBiển số: 29C-888.99\nMooc: 29R-112.33\nTài xế: Phạm Văn Hùng\nSĐT: 0977665544\nSố cont: VSIU7399796\nSố chì: VN998877\nDự kiến: 14h30 27/10/2026",
  "timestamp": "2026-10-27T10:15:00"
}
```
> Khi `group_id` để trống, hệ thống tự động chuẩn hóa thành `direct_user_taixe_hung` để phân biệt hội thoại trực tiếp 1-1 với Group.

---

## 2. Kiểm Thử 4 API Lấy Tin Nhắn (Kèm Bộ Lọc Thời Gian `from_time` / `to_time`)

> **Quy tắc lọc thời gian chung cho cả 4 API**:
> - **Không truyền `from_time` và `to_time`**: Hệ thống trả về **tất cả** tin nhắn thỏa mãn điều kiện.
> - **Có truyền `from_time` và/hoặc `to_time`** (hoặc bí danh `start_time` / `end_time`): Hệ thống lọc chính xác các tin nhắn nằm trong khoảng thời gian đó.
> - **Định dạng thời gian hỗ trợ linh hoạt**:
>   - Chỉ nhập ngày: `2026-10-27` hoặc `27/10/2026` (Nếu ở `to_time`, tự động mở rộng tới `23:59:59.999999` của ngày đó).
>   - Nhập ngày kèm giờ: `2026-10-27 08:00:00`, `2026-10-27T08:00:00`, hoặc `27/10/2026 14:30:00`.

---

### API 1: Lấy Tất Cả Các Tin Nhắn (`GET /api/messages`)

1. **Lấy toàn bộ tin nhắn (không giới hạn thời gian)**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages`
2. **Lấy tất cả tin nhắn trong khoảng thời gian chỉ định**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages?from_time=2026-10-27 08:00:00&to_time=2026-10-27 12:00:00`

---

### API 2: Lấy Tất Cả Tin Nhắn Bởi User ID (`GET /api/messages/user/{user_id}`)

1. **Lấy toàn bộ tin nhắn của một User (cả nhắn riêng 1-1 lẫn nhắn trong mọi Group)**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/user/user_dieuvan_bao`
2. **Lấy tin nhắn của User đó trong khoảng thời gian**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/user/user_dieuvan_bao?from_time=2026-10-27&to_time=2026-10-27`

---

### API 3: Lấy Tất Cả Tin Nhắn Của Group ID (`GET /api/messages/group/{group_id}`)

1. **Lấy toàn bộ tin nhắn của một Group (không lọc thời gian)**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/group/group_nhaxe_haiphong_01`
2. **Lấy tin nhắn của Group đó trong khoảng thời gian**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/group/group_nhaxe_haiphong_01?from_time=2026-10-27 00:00:00&to_time=2026-10-27 23:59:59`

---

### API 4: Lấy Tất Cả Tin Nhắn Của Một User Trong Một Group

Hỗ trợ cả 2 chiều đường dẫn URL để thuận tiện khi gọi API:
- `GET /api/messages/group/{group_id}/user/{user_id}`
- `GET /api/messages/user/{user_id}/group/{group_id}`

1. **Lấy toàn bộ tin nhắn của `user_dieuvan_bao` trong nhóm `group_nhaxe_haiphong_01` (không lọc thời gian)**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/group/group_nhaxe_haiphong_01/user/user_dieuvan_bao`
2. **Lấy tin nhắn của `user_dieuvan_bao` trong nhóm `group_nhaxe_haiphong_01` có lọc khoảng thời gian**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/group/group_nhaxe_haiphong_01/user/user_dieuvan_bao?from_time=2026-10-27 08:00:00&to_time=2026-10-27 09:00:00`

---

## 3. API Thống Kê Bảng 1 (1.1 -> 1.6) & Bảng 2 (T01 -> T40)

Đếm chính xác cột **"Số tin có"** (số ID tin nhắn riêng biệt chứa hạng mục, không đếm trùng khi 1 tin có nhiều xe) cho **Bảng 1** và phân loại **`primary_type` + `all_matched_types`** cho **40 dạng tin T01 -> T40 (Bảng 2)**:

1. **Thống kê trên toàn bộ tin nhắn**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/statistics`
2. **Thống kê có lọc theo Group / User / Khoảng thời gian**:
   - **Method**: `GET`
   - **URL**: `http://localhost:8000/api/messages/statistics?group_id=group_nhaxe_haiphong_01&from_time=2026-10-27&to_time=2026-10-27`

---

## 4. API Kích Hoạt Thủ Công Vét Hàng Đợi FIFO (Tùy Chọn)

Nếu có bản ghi được chèn trực tiếp vào bảng `zalo_messages` qua DataGrip với trạng thái `received` hoặc `queued`, hệ thống sẽ tự động bóc tách tuần tự theo FIFO hoặc bạn có thể gọi:
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/messages/process-fifo`
