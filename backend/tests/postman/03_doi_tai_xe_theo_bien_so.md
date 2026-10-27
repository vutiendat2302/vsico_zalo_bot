# 📮 TEST CASE 03: ĐỔI TÀI XẾ THEO BIỂN SỐ XE QUA REST API

### 1. Mục tiêu kiểm thử

Xác minh tính năng **tra cứu ngược theo biển số xe (Reverse Plate Lookup)** và **quản lý vòng đời phiên bản chuyến xe (Trip Versioning)**.

**Tình huống thực tế:**
Nhà xe điều xe mới hoặc đổi tài xế đột xuất. Họ chỉ báo biển số xe `15C-878.99` kèm tên tài xế mới `Lê Văn Đổi` mà không nhớ hoặc không gửi kèm số container.

Hệ thống phải:

1. Tra cứu trong cơ sở dữ liệu các chuyến xe của nhà xe `NX01` để tìm chuyến xe nào đang gắn với biển số `15C-878.99`.
2. Định vị được số container tương ứng là `VSIU7399796` (đã tạo ở Test Case 02).
3. Cập nhật tài xế mới, tự động nâng số phiên bản từ **Version 1 lên Version 2**.
4. Giữ nguyên các thông tin không thay đổi (số seal, giờ đến, mã đơn hàng).

---

### 2. Thông tin Request trên Postman

| Thông số        | Giá trị                                         |
| ----------------- | ------------------------------------------------- |
| **Method**  | `POST`                                          |
| **URL**     | `http://localhost:8000/api/trips/update-driver` |
| **Headers** | `Content-Type: application/json`                |

#### Request Body (JSON Raw):

```json
{
  "carrier_id": "NX01",
  "bien_so": "15C-878.99",
  "tai_xe_moi": "Lê Văn Đổi",
  "sdt_moi": "0988592302"
}
```

> **Lưu ý**: Payload hoàn toàn **không cần truyền `cont`**. Hệ thống sẽ tự động tra cứu theo `bien_so`!

---

### 3. Các bước thực hiện trên Postman

1. Chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/api/trips/update-driver`.
3. Trong tab **Body**, chọn **raw** $\rightarrow$ **JSON**.
4. Dán payload cập nhật tài xế ở trên.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**

```json
{
  "success": true,
  "action": "UPDATE_DRIVER",
  "cont": "VSIU7399796",
  "version": 2,
  "old_driver": "Trần Quốc Bảo",
  "new_driver": "Lê Văn Đổi",
  "old_phone": "0903976359",
  "new_phone": "0988592302",
  "send_status": "SENT_DRY_RUN_UPDATE"
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - Hệ thống tự động xác định được đúng container `cont: "VSIU7399796"`.
  - Phiên bản được nâng thành công lên `version: 2`.
  - Ghi nhận rõ sự thay đổi từ `old_driver` sang `new_driver`.
  - Trạng thái điều phối cập nhật thành `send_status: "SENT_DRY_RUN_UPDATE"`.
- [ ] **Fail**: Trả về `404 Not Found` (do không tìm thấy chuyến xe với biển số trên, thường do chưa chạy Test Case 02 trước).
