# Ca Kiểm Thử 13: Bật / Tắt Tự Động Tạo Kế Hoạch Shipping Giả Lập (Auto-Mock Mode)

## 1. Mục đích kiểm thử
Xác minh tính năng chuyển đổi chế độ **Auto-Mock Shipping** qua API `POST /api/shipping/mock-mode`.
Khi chế độ này được **BẬT (`true`)**: Mọi số container hợp lệ gửi qua Webhook hoặc TMS REST API nếu chưa có trong kế hoạch đều sẽ được tự động cấp một đơn hàng giả lập, giúp kiểm thử luồng tạo chuyến và render thông báo gửi khách hàng chủ động 100% mà không phụ thuộc vào tệp CSV tĩnh.

---

## 2. Thông tin Request

- **Method**: `POST`
- **URL**: `http://localhost:8000/api/shipping/mock-mode`
- **Headers**:
  ```http
  Content-Type: application/json
  ```
- **Body (JSON)**:
  ```json
  {
    "enabled": true
  }
  ```

---

## 3. Lệnh Curl kiểm thử nhanh

```bash
curl -X POST http://localhost:8000/api/shipping/mock-mode \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

---

## 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status**: `200 OK`
- **Response Body**:
  ```json
  {
    "success": true,
    "action": "TOGGLE_AUTO_MOCK_SHIPPING",
    "auto_mock_enabled": true,
    "message": "Đã BẬT tự động tạo shipping giả lập cho container mới"
  }
  ```

---

## 5. Tiêu chuẩn đánh giá (Validation Criteria)
1. Trường `success` bằng `true`.
2. Trường `auto_mock_enabled` phản ánh đúng giá trị gửi lên (`true` hoặc `false`).
3. Sau khi bật, khi gửi tin nhắn Zalo chứa container mới bất kỳ qua `POST /webhook`, hệ thống sẽ tự động ghép lệnh thành công (khớp `kho_tra`, `ten_khach_hang`) và đạt trạng thái `SENT_DRY_RUN` thay vì bị giữ lại `HOLD_ADMIN`.
