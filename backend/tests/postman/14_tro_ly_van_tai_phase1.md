# Kiểm thử trợ lý vận tải Phase 1

## 1. Chuẩn bị

Dùng nhóm sandbox đã khai báo `is_test=true`, carrier_id hoặc RouteMap thật của môi trường kiểm thử. ĐHVT cần user active gắn đúng nhóm và Zalo sender. Giữ AUTO_DISPATCH_OUTBOUND tắt khi kiểm tra dữ liệu vận hành để không phát hành ra Zalo. Đợt triển khai này không thêm bảng/cột/API public mới.

## 2. Webhook hội thoại

Gửi payload qua `POST /webhook`, header `X-Webhook-Secret` từ môi trường. Mỗi lần dùng `msg_id` riêng; webhook trả QUEUED, xem kết quả sau khi worker xử lý tại messages/outbound trên Web.

```json
{
  "msg_id": "assistant-sandbox-unique-message-id",
  "group_id": "<ID nhóm sandbox đã cấu hình>",
  "sender_id": "<ID người gửi đã cấu hình>",
  "message_text": "Ngày mai có những chuyến nào?",
  "is_test": true
}
```

| Vai trò | Câu kiểm tra | Kết quả cần kiểm |
|---|---|---|
| Khách | `LO<mã thực> xe nào chở?` | Chỉ dữ liệu RouteMap của nhóm; mã ngoài scope và mã không tồn tại cùng thông báo. |
| Khách | `Booking <mã thực> có mấy xe?` | Chỉ chuyến đúng booking, ghi rõ giờ kế hoạch. |
| Khách | `Hủy chuyến LO<mã thực>` | Ca HIGH, plan chưa thay đổi; nhóm khác không đọc được ca. |
| Nhà xe | `Hôm nay lệnh nào thiếu cont/chì?` | Chỉ carrier_id của nhóm, không chứa lệnh chưa gán hoặc nhà xe khác. |
| Nhà xe | `LO<mã thực> đổi sang <biển số mới>` | Nháp WAITING_REPLY, chưa sửa plan. |
| Nhà xe | `xác nhận #<mã nháp>` | Cùng sender/group, còn hạn, cùng version mới được tiếp tục. |
| Nhà xe | Quote câu hỏi + `Đúng` | Chỉ nháp của câu hỏi; không lấy nháp mới nhất tùy tiện. |
| Nhà xe | `LO<mã thực> bổ sung chì <seal>` | FILL khi trống; có mâu thuẫn/đã gửi thì review, không ghi đè. |
| ĐHVT | `Hôm nay bao nhiêu chuyến?`, `Ca chờ`, `Tỷ lệ dùng LLM?` | Số liệu DB; không suy trạng thái thực địa. |
| ĐHVT | `Duyệt ca #<mã>` hoặc quote `ok` | Link Web; trạng thái ca và plan không đổi. |
| ĐHVT | `Nếu hủy LO<mã thực> ảnh hưởng gì?` | Phân tích chỉ đọc, không tạo lệnh hủy. |

## 3. API nội bộ AI

Gửi `POST <AI_SERVICE_URL>/api/v1/assistant-intent` với `X-Internal-Token` của môi trường:

```json
{
  "message_text": "Nhờ tổng hợp các việc cần xử lý gấp",
  "reference_date": "2026-11-09",
  "allowed_tools": ["dhvt_get_priority_digest", "get_role_help"]
}
```

Đầu ra chỉ được chọn tên trong danh sách hoặc UNKNOWN. Kiểm tra thiếu/sai token bị từ chối, JSON chứa tham số quyền không hợp lệ không được sử dụng. Không gửi SĐT nguyên bản khi thử cloud.

## 4. Bất biến cần đối chiếu

Plan version chỉ tăng khi có thay đổi thực; xác nhận lặp không tăng. Plan/job TMS giữ PENDING; không gán SYNCED giả. Hai nhóm cùng số cont không gộp ca. Phản hồi và thông báo được ghi outbox trước khi gửi. Nhóm test không phát hành tới nhóm thật.
