# 📮 TEST CASE 02: TẠO CHUYẾN XE MỚI QUA TMS REST API

### 1. Mục tiêu kiểm thử

Mô phỏng trường hợp điều phối viên trên giao diện phần mềm TMS tạo một chuyến xe mới trực tiếp qua REST API (không thông qua tin nhắn Zalo).

Hệ thống sẽ:

1. Thẩm định thuật toán số kiểm tra container theo chuẩn quốc tế **ISO 6346 Mod 11**.
2. Chuẩn hóa biển số xe và số điện thoại Việt Nam.
3. Tự động đối chiếu số container với danh mục lệnh vận chuyển (`nhaxe_shipping_demo.csv`).
4. Khởi tạo chuyến xe phiên bản đầu tiên (**Version 1**), lưu trữ vào bộ nhớ và kết xuất thông tin điều phối.

---

### 2. Thông tin Request trên Postman

| Thông số        | Giá trị                               |
| ----------------- | --------------------------------------- |
| **Method**  | `POST`                                |
| **URL**     | `http://localhost:8000/api/trips/new` |
| **Headers** | `Content-Type: application/json`      |

#### Request Body (JSON Raw):

```json
{
  "carrier_id": "NX01",
  "cont": "VSIU7399796",
  "seal": "73957169",
  "bien_so": "15C-878.99",
  "tai_xe": "Trần Quốc Bảo",
  "sdt": "0903976359",
  "gio_den": "08:00 14/10/2026"
}
```

#### Giải thích ý nghĩa các trường dữ liệu:

- `carrier_id`: Mã nhà xe vận chuyển (Ví dụ: `NX01` - Vận tải Hải Long).
- `cont`: Số container (Gồm 4 chữ cái + 7 chữ số, chữ số thứ 7 là Check Digit chuẩn ISO 6346).
- `seal`: Số niêm chì hải quan do hãng tàu cấp.
- `bien_so`: Biển kiểm soát xe đầu kéo hoặc rơ-moóc.
- `tai_xe`: Họ và tên người lái xe nhận cuốc.
- `sdt`: Số điện thoại liên hệ tài xế (bot tự động chuẩn hóa dạng `0903976359`).
- `gio_den`: Thời gian xe dự kiến có mặt tại kho khách hàng để bốc/trả hàng.

---

### 3. Các bước thực hiện trên Postman

1. Nhấn **New Request**, chọn phương thức **POST**.
2. Nhập URL: `http://localhost:8000/api/trips/new`.
3. Chuyển sang tab **Body**, chọn kiểu **raw**, chọn định dạng là **JSON**.
4. Dán nội dung JSON ở trên vào khung soạn thảo.
5. Bấm nút **Send**.

---

### 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status Code**: `200 OK`
- **Response Format**: `application/json; charset=utf-8`

**Body mẫu trả về:**

```json
{
  "success": true,
  "action": "CREATE_TRIP",
  "carrier_id": "NX01",
  "cont": "VSIU7399796",
  "shipping_id": "DH00000001",
  "version": 1,
  "send_status": "SENT_DRY_RUN",
  "warnings": [],
  "xe_data": {
    "cont": "VSIU7399796",
    "seal": "73957169",
    "bien_so": "15C-878.99",
    "tai_xe": "Trần Quốc Bảo",
    "sdt": "0903976359",
    "gio_den": "08:00 14/10/2026"
  }
}
```

---

### 5. Tiêu chí đánh giá Pass/Fail

- [X] **Pass**:
  - `success` là `true`.
  - Khớp thành công lệnh vận chuyển `shipping_id: "DH00000001"`.
  - Phiên bản ban đầu là `version: 1`.
  - Trạng thái gửi là `send_status: "SENT_DRY_RUN"`.
  - Danh sách cảnh báo rỗng: `warnings: []`.
- [ ] **Fail**: Bị trả về mã lỗi 400 hoặc container không khớp được mã lệnh vận chuyển.
