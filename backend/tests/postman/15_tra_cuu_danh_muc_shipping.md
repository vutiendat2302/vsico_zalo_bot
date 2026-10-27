# Ca Kiểm Thử 15: Tra Cứu Danh Mục Kế Hoạch Vận Chuyển (List Shipping Orders)

## 1. Mục đích kiểm thử

Xác minh chức năng tra cứu danh bạ toàn bộ các lệnh kế hoạch vận chuyển đang được nạp trong bộ nhớ qua API `GET /api/shipping`.
Giúp người dùng kiểm tra trạng thái của chế độ Auto-Mock, tổng số lượng đơn vận chuyển hiện có và chi tiết từng đơn.

---

## 2. Thông tin Request

- **Method**: `GET`
- **URL**: `http://localhost:8000/api/shipping`
- **Headers**:
  ```http
  Accept: application/json
  ```
- **Body**: Không có (None)

---

## 3. Lệnh Curl kiểm thử nhanh

```bash
curl -X GET http://localhost:8000/api/shipping
```

---

## 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status**: `200 OK`
- **Response Body**:
  ```json
  {
    "success": true,
    "auto_mock_enabled": true,
    "total_orders": 13,
    "orders": [
      {
        "shipping_id": "SHIP_001",
        "so_container": "VSIU7399796",
        "nha_xe_id": "NX01",
        "khach_hang_id": "KH01",
        "ten_khach_hang": "Công ty TNHH Nhựa Phương Nam",
        "kho_tra": "Kho Nhựa Phương Nam",
        "dia_chi_kho_tra": "KCN Đình Vũ, Hải Phòng",
        "kich_thuoc_cont": "40DC",
        "trang_thai": "Chờ thực hiện"
      },
      {
        "shipping_id": "SHIP_MOCK_CSQU3054383",
        "so_container": "CSQU3054383",
        "nha_xe_id": "NX01",
        "khach_hang_id": "KH_SAMSUNG",
        "ten_khach_hang": "Công ty TNHH Samsung Electronics Việt Nam",
        "kho_tra": "Kho Samsung Yên Phong",
        "dia_chi_kho_tra": "KCN Yên Phong, Bắc Ninh",
        "kich_thuoc_cont": "40HC",
        "trang_thai": "Chờ thực hiện"
      }
    ]
  }
  ```

---

## 5. Tiêu chuẩn đánh giá (Validation Criteria)

1. HTTP Status trả về mã `200 OK`.
2. Trường `auto_mock_enabled` hiển thị trạng thái hiện thời của tính năng tự tạo đơn.
3. Mảng `orders` liệt kê đầy đủ cả các đơn tĩnh ban đầu và các đơn động được nạp thêm qua API hoặc sinh tự động.
