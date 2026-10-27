# Ca Kiểm Thử 14: Tạo Đơn Hàng Kế Hoạch Vận Chuyển Động (Dynamic Shipping Order)

## 1. Mục đích kiểm thử
Xác minh chức năng nạp trực tiếp một đơn kế hoạch vận chuyển (Shipping Order) qua API `POST /api/shipping/new`.
Giúp người kiểm thử hoặc hệ thống TMS chủ động định nghĩa trước thông tin khách hàng, kho trả hàng, và nhà xe cho bất kỳ số container nào trước khi gửi tin nhắn Zalo điều xe.

---

## 2. Thông tin Request

- **Method**: `POST`
- **URL**: `http://localhost:8000/api/shipping/new`
- **Headers**:
  ```http
  Content-Type: application/json
  ```
- **Body (JSON)**:
  ```json
  {
    "carrier_id": "NX01",
    "cont": "CSQU3054383",
    "khach_hang_id": "KH_SAMSUNG",
    "ten_khach_hang": "Công ty TNHH Samsung Electronics Việt Nam",
    "kho_tra": "Kho Samsung Yên Phong",
    "dia_chi_kho_tra": "KCN Yên Phong, Bắc Ninh",
    "kich_thuoc_cont": "40HC"
  }
  ```

---

## 3. Lệnh Curl kiểm thử nhanh

```bash
curl -X POST http://localhost:8000/api/shipping/new \
  -H "Content-Type: application/json" \
  -d '{
    "carrier_id": "NX01",
    "cont": "CSQU3054383",
    "khach_hang_id": "KH_SAMSUNG",
    "ten_khach_hang": "Công ty TNHH Samsung Electronics Việt Nam",
    "kho_tra": "Kho Samsung Yên Phong",
    "dia_chi_kho_tra": "KCN Yên Phong, Bắc Ninh",
    "kich_thuoc_cont": "40HC"
  }'
```

---

## 4. Kết quả phản hồi kỳ vọng (Expected Response)

- **HTTP Status**: `200 OK`
- **Response Body**:
  ```json
  {
    "success": true,
    "action": "CREATE_SHIPPING_ORDER",
    "shipping_id": "SHIP_MOCK_CSQU3054383",
    "cont": "CSQU3054383",
    "carrier_id": "NX01",
    "khach_hang_id": "KH_SAMSUNG",
    "ten_khach_hang": "Công ty TNHH Samsung Electronics Việt Nam",
    "kho_tra": "Kho Samsung Yên Phong",
    "dia_chi_kho_tra": "KCN Yên Phong, Bắc Ninh"
  }
  ```

---

## 5. Tiêu chuẩn đánh giá (Validation Criteria)
1. Đơn kế hoạch được nạp thành công vào bộ nhớ với mã `shipping_id` sinh tự động.
2. Các trường `cont`, `carrier_id`, `kho_tra`, `ten_khach_hang` lưu đúng giá trị truyền vào.
3. Khi gọi `POST /webhook` gửi tin nhắn cho cont `CSQU3054383`, hệ thống tự động gán đúng tên kho trả `Kho Samsung Yên Phong` vào thông báo gửi khách hàng.
