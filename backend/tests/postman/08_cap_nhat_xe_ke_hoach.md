# Cập nhật xe vào kế hoạch nội bộ

## 1. Điều kiện

Đăng nhập bằng tài khoản ĐHVT hoặc Admin. Migration `6b4adb23e478` phải được áp dụng. Lấy `version` hiện tại từ `GET /api/plans/{id}`.

## 2. Cập nhật

```bash
curl -X PATCH "$API_URL/api/plans/$PLAN_ID/vehicle" \
  -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"expected_version":1,"planned_truck_plate":"15C-123.45","driver_name":"Tên tài xế","driver_phone":"0901234567","seal_no":"SEAL123","required_time":"09:30"}'
```

Các giá trị trong ví dụ chỉ dùng kiểm thử. Có thể gửi từng trường; trường không gửi được giữ nguyên, `null` xóa trường tùy chọn. Hỗ trợ thêm `container_no`, `container_size`, `carrier_id`. Không có trường rơ-moóc. Container phải đạt ISO 6346; SĐT gồm 10 số bắt đầu bằng 0.

Kết quả tăng `version`, đặt `tms_sync_status=PENDING`, ghi audit các tên trường thay đổi. `PENDING` nghĩa là đã cập nhật nội bộ, chưa đồng bộ TMS.

- `401/403`: chưa đăng nhập hoặc sai quyền.
- `404`: kế hoạch không tồn tại.
- `409`: phiên bản đã thay đổi; tải lại rồi cập nhật.
- `422`: dữ liệu không hợp lệ.

API này cập nhật kế hoạch, không tự gửi thông báo Zalo. Tin nhà xe hợp lệ được worker ghi vào kế hoạch trước khi phát hành thông báo. Cần gắn `carrier_id` cho cả nhóm và kế hoạch; không tự suy luận quyền sở hữu bằng tên.

## 3. Webhook và phát hành

Webhook trả `QUEUED`, không đợi OCR/AI; dùng API tin nhắn để xem kết quả sau xử lý. Thông báo tự động đi qua `PENDING_SEND` → `SENDING` → `SENT/FAILED`. Khi tắt dispatch, trạng thái vẫn là `PENDING_SEND`, không sinh ID Zalo giả.

`SENDING` còn lại sau sự cố cần đối soát Zalo trước khi thao tác gửi lại. Không tự retry mù vì bridge chưa có hợp đồng chống trùng đầu cuối. Tin `PROCESSING` bị gián đoạn được chuyển `NEEDS_REVIEW` khi worker lấy lại khóa nhóm.

TMS chưa kết nối: không có thao tác ghi TMS thật và không đặt `SYNCED`; dữ liệu nội bộ giữ `PENDING`. Khi tích hợp TMS phải bổ sung client và xác nhận thành công trước khi chuyển `SYNCED`.
