# Kiểm tra đề xuất lệnh đóng chưa có cont

1. Cấu hình nhóm nhà xe với `carrier_id` hợp lệ và kế hoạch LOAD trong ngày; dùng dữ liệu kiểm thử trong môi trường riêng.
2. Gửi webhook có header `X-Webhook-Secret`, nội dung báo biển số, tài xế, kho/giờ nhưng chưa có cont.
3. Webhook trả QUEUED; sau khi worker xử lý, xem ca `PLAN_RESOLUTION` trên API danh sách reviews.
4. Kiểm tra `details.resolution`: action, reason, candidates và selected_plan_id. Một slot không có bằng chứng phải ASK_CARRIER; nhiều slot điểm sát nhau không được chọn dòng đầu tiên; sai nhà xe không được AUTO_APPLY.
5. Ở phiên bản hiện tại, ASK_CARRIER được lưu thành đề xuất trên Web, chưa tự gửi câu hỏi lựa chọn; kế hoạch không được ghi bởi nhánh này.

Kiểm tra ngày tương đối bằng thời gian tin gốc. Các ID ứng viên trả trong resolution là chuỗi để giữ nguyên Snowflake 64-bit.
