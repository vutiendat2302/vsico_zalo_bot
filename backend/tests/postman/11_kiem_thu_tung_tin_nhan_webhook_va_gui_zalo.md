# 🧪 HƯỚNG DẪN KIỂM THỬ POSTMAN TỪNG TIN NHẮN (WEBHOOK & GỬI TIN ZALO THỜI GIAN THỰC)

Tài liệu này cung cấp đầy đủ các kịch bản kiểm thử từng tin nhắn một thông qua **Postman** hoặc **cURL** vào Cổng Webhook Gateway của hệ thống (`POST http://localhost:8000/webhook`).

---

## 📌 QUY TẮC NGHIỆP VỤ & HIỂN THỊ DỮ LIỆU

1. **Hiển thị Số Điện Thoại (SĐT)**:
   - Hiển thị **đầy đủ 100% số điện thoại thật** trên Web UI (`http://localhost:3001/messages`) và trong nội dung tin nhắn gửi vào nhóm Zalo. Tuyệt đối **không che `******`**.
   - **Chỉ che `xxxx`** khi chuyển văn bản cho AI LLM xử lý (ZCB-10 Fallback) nhằm bảo vệ quyền riêng tư theo tiêu chuẩn bảo mật, sau đó tự động khôi phục lại số thật khi lưu DB và gửi Zalo.
2. **Ưu tiên ghép theo Số Container**:
   - Cứ có `container_no` là hệ thống tự động đối chiếu trực tiếp với bảng Kế Hoạch Vận Chuyển (`transport_plans`).
   - Lấy thẳng Loại lệnh (`đóng`/`trả`), Tên khách hàng, Địa chỉ kho giao nhận và Nhóm Zalo đích từ bảng kế hoạch, tạm bỏ qua các từ khóa gây nhiễu trong nội dung chat.
3. **Gửi tin nhắn tức thì (Realtime Dispatch)**:
   - Khi tin nhắn bóc tách thành công và hợp lệ (`processed`), hệ thống tự động gọi sang ZCA bridge (`http://localhost:3000/api/bot/send/group`) để gửi thông báo ngay lập tức vào Nhóm Zalo thật `6469608867469758994`.

---

## ⚙️ CẤU HÌNH POSTMAN CHUNG

- **Method**: `POST`
- **URL**: `http://localhost:8000/webhook` (hoặc `http://localhost:8000/webhook/zalo`)
- **Headers**:
  ```http
  Content-Type: application/json; charset=utf-8
  ```

---

## 📝 DANH SÁCH 6 CA KIỂM THỬ TỪNG TIN NHẮN CHI TIẾT

---

### Ca 1: Lệnh Đóng rõ ràng (1 Xe, 1 Cont SELU4396800)

- **Mục tiêu**: Bóc tách định dạng F1, ghép cont `SELU4396800` với kế hoạch của khách hàng **Logitem**, gửi tin thông báo với đầy đủ SĐT `0981695322`.

#### Body (Raw JSON):
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "6469608867469758994",
  "sender": {
    "id": "6691387223255581446",
    "name": "Lái xe Hải Long"
  },
  "timestamp": "1791798030000",
  "message": {
    "msg_id": "postman_test_ca_01",
    "text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n1 xe: 36H74446/ Hoàng Thanh Bình đt:  0981695322 / SELU4396800 chì 23331731"
  }
}
```

#### cURL Lệnh mẫu:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "6469608867469758994",
    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
    "timestamp": "1791798030000",
    "message": {
      "msg_id": "postman_test_ca_01",
      "text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n1 xe: 36H74446/ Hoàng Thanh Bình đt:  0981695322 / SELU4396800 chì 23331731"
    }
  }'
```

#### Kết quả gửi vào Nhóm Zalo (`6469608867469758994`):
```text
VSICO - THÔNG BÁO XE TRẢ HÀNG
Khách hàng: Logitem

- Số cont: SELU4396800 (40)
- Số chì: 23331731
- Biển số xe: 36H-744.46
- Lái xe: Hoàng Thanh Bình - SĐT: 0981695322
- Điểm trả: Kho Logitem (Tân Quang). LH thủ kho Mr Sơn 096 7327975
- Giờ đến dự kiến: Chưa có
```

---

### Ca 2: Lệnh Trả cont rõ ràng (1 Xe, 1 Cont SELU4429550)

- **Mục tiêu**: Bóc tách định dạng F1 có nhãn "Lệnh trả cont", ghép kế hoạch cont `SELU4429550` -> Logitem, SĐT thật `0362825445`.

#### Body (Raw JSON):
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "6469608867469758994",
  "sender": {
    "id": "6691387223255581446",
    "name": "Lái xe Hải Long"
  },
  "timestamp": "1791798030000",
  "message": {
    "msg_id": "postman_test_ca_02",
    "text": "Lệnh trả cont - KH: Logitem - Trả về: kho Logitem Tân Quang - 8h\n1 xe: 51D38931/ Trần Minh Tuấn đt:  0362825445 / SELU4429550 chì 23338065"
  }
}
```

#### cURL Lệnh mẫu:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "6469608867469758994",
    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
    "timestamp": "1791798030000",
    "message": {
      "msg_id": "postman_test_ca_02",
      "text": "Lệnh trả cont - KH: Logitem - Trả về: kho Logitem Tân Quang - 8h\n1 xe: 51D38931/ Trần Minh Tuấn đt:  0362825445 / SELU4429550 chì 23338065"
    }
  }'
```

#### Kết quả gửi vào Nhóm Zalo (`6469608867469758994`):
```text
VSICO - THÔNG BÁO XE TRẢ HÀNG
Khách hàng: Logitem

- Số cont: SELU4429550 (40)
- Số chì: 23338065
- Biển số xe: 51D-389.31
- Lái xe: Trần Minh Tuấn - SĐT: 0362825445
- Điểm trả: Kho Logitem (Tân Quang). LH thủ kho Mr Sơn 096 7327975
- Giờ đến dự kiến: Chưa có
```

---

### Ca 3: Lệnh Viết Không Dấu 'lenh tra hang' (Cont GAOU7957079)

- **Mục tiêu**: Kiểm tra khả năng chuẩn hóa tiếng Việt không dấu, ghép cont `GAOU7957079` -> Logitem, SĐT thật `0913251729`.

#### Body (Raw JSON):
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "6469608867469758994",
  "sender": {
    "id": "6691387223255581446",
    "name": "Lái xe Hải Long"
  },
  "timestamp": "1791798030000",
  "message": {
    "msg_id": "postman_test_ca_03",
    "text": "lenh tra hang - KH: Logitem - Trả về: kho Logitem Tân Quang - 8h\n1 xe: 15B23237/ Lê Hữu Phong đt:  0913251729 / GAOU7957079 chì 23334238"
  }
}
```

#### cURL Lệnh mẫu:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "6469608867469758994",
    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
    "timestamp": "1791798030000",
    "message": {
      "msg_id": "postman_test_ca_03",
      "text": "lenh tra hang - KH: Logitem - Trả về: kho Logitem Tân Quang - 8h\n1 xe: 15B23237/ Lê Hữu Phong đt:  0913251729 / GAOU7957079 chì 23334238"
    }
  }'
```

---

### Ca 4: Tin Phức Tạp 2 Xe, 2 Container Trong Cùng 1 Tin

- **Mục tiêu**: Bóc tách đa dòng (2 xe, 2 container `GAOU7806508` và `GAOU7801569`), ghép kế hoạch khách hàng **DC**, tự động sinh 2 tin nhắn gửi ra nhóm Zalo tương ứng với 2 số điện thoại thật (`0932237840` và `0936636567`).

#### Body (Raw JSON):
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "6469608867469758994",
  "sender": {
    "id": "6691387223255581446",
    "name": "Lái xe Hải Long"
  },
  "timestamp": "1791798030000",
  "message": {
    "msg_id": "postman_test_ca_04",
    "text": "Lệnh đóng và trả - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\nĐóng: 1 Xe 15D41566 / Bùi Văn Tuấn 0932237840/ GAOU7806508 chì 23339832\nTrả: 2 xe 30D15459/ Hoàng Đức Nam đt:  0936636567 / GAOU7801569 chì 23333240"
  }
}
```

#### cURL Lệnh mẫu:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "6469608867469758994",
    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
    "timestamp": "1791798030000",
    "message": {
      "msg_id": "postman_test_ca_04",
      "text": "Lệnh đóng và trả - KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\nĐóng: 1 Xe 15D41566 / Bùi Văn Tuấn 0932237840/ GAOU7806508 chì 23339832\nTrả: 2 xe 30D15459/ Hoàng Đức Nam đt:  0936636567 / GAOU7801569 chì 23333240"
    }
  }'
```

#### Kết quả gửi vào Nhóm Zalo (Sinh 2 tin liên tiếp):
- **Tin 1**:
  ```text
  VSICO - THÔNG BÁO XE TRẢ HÀNG
  Khách hàng: DC

  - Số cont: GAOU7806508 (40)
  - Số chì: 23339832
  - Biển số xe: 15D-415.66
  - Lái xe: Bùi Văn Tuấn - SĐT: 0932237840
  - Điểm trả: DC HẢI DƯƠNG
  - Giờ đến dự kiến: Chưa có
  ```
- **Tin 2**:
  ```text
  VSICO - THÔNG BÁO XE TRẢ HÀNG
  Khách hàng: DC

  - Số cont: GAOU7801569 (40)
  - Số chì: 23333240
  - Biển số xe: 30D-154.59
  - Lái xe: Hoàng Đức Nam - SĐT: 0936636567
  - Điểm trả: DC HẢI DƯƠNG
  - Giờ đến dự kiến: Chưa có
  ```

---

### Ca 5: Không Có Từ Khóa Lệnh (Suy Từ Kế Hoạch - GAOU7822999)

- **Mục tiêu**: Tin nhắn nhà xe không ghi loại lệnh ("đóng" hay "trả"). Hệ thống tự tra số cont `GAOU7822999` trong bảng `transport_plans`, xác định lệnh `tra`, khách hàng `DC`, điểm trả `DC HẢI DƯƠNG`, SĐT `0987541192`.

#### Body (Raw JSON):
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "6469608867469758994",
  "sender": {
    "id": "6691387223255581446",
    "name": "Lái xe Hải Long"
  },
  "timestamp": "1791798030000",
  "message": {
    "msg_id": "postman_test_ca_05",
    "text": "KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n1 xe 14C13296/ Đào Minh Cường đt:  0987541192 / GAOU7822999 chì 23331375"
  }
}
```

#### cURL Lệnh mẫu:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "6469608867469758994",
    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
    "timestamp": "1791798030000",
    "message": {
      "msg_id": "postman_test_ca_05",
      "text": "KH: Logitem - Điểm đóng: kho Logitem Tân Quang - 8h\n1 xe 14C13296/ Đào Minh Cường đt:  0987541192 / GAOU7822999 chì 23331375"
    }
  }'
```

---

### Ca 6: Ca Cảnh Báo Lỗi ISO 6346 (Sai Check Digit) — Kiểm Tra Giao Diện Lỗi & Hàng Đợi Duyệt

- **Mục tiêu**: Số cont `VSIU2323001` sai số kiểm tra cuối (số đúng theo ISO 6346 phải là `0` -> `VSIU2323000`).
- **Kỳ vọng**:
  - Trạng thái tin nhắn chuyển thành `needs_review` (chờ duyệt).
  - **KHÔNG gửi tin ra nhóm Zalo khách hàng**.
  - Tự động sinh ca rà soát trong bảng `review_cases`.
  - Sinh tin nhắn Bot nhắc lỗi nhà xe: `[VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại thông tin sau: - Xe 15C-170.66: số container 'VSIU2323001' sai số kiểm tra cuối theo ISO 6346 (gợi ý đúng: VSIU2323000)`.
  - Trên Web UI hiển thị hộp cảnh báo màu đỏ/cam và nút duyệt.

#### Body (Raw JSON):
```json
{
  "app_id": "zca_personal_bot",
  "event_name": "user_send_text",
  "group_id": "6469608867469758994",
  "sender": {
    "id": "6691387223255581446",
    "name": "Lái xe Hải Long"
  },
  "timestamp": "1791798030000",
  "message": {
    "msg_id": "postman_test_ca_06_error_iso",
    "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 0962362615 / VSIU2323001 chì 23333878"
  }
}
```

#### cURL Lệnh mẫu:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "zca_personal_bot",
    "event_name": "user_send_text",
    "group_id": "6469608867469758994",
    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
    "timestamp": "1791798030000",
    "message": {
      "msg_id": "postman_test_ca_06_error_iso",
      "text": "1 xe 15C17066/ Phạm Văn Huynh đt: 0962362615 / VSIU2323001 chì 23333878"
    }
  }'
```

---

## 🔍 CÁCH KIỂM TRA ĐỐI CHIẾU KẾT QUẢ TẠI 3 NƠI

### 1. Kiểm tra trực tiếp trên Ứng dụng Zalo
- Mở nhóm Zalo `6469608867469758994`.
- Ngay sau khi gửi request thành công, bạn sẽ thấy thông báo điều xe với đầy đủ số điện thoại thật của tài xế hiển thị trong nhóm.

### 2. Kiểm tra trên Giao diện Web (Frontend)
- **Quản lý Tin Nhắn**: [http://localhost:3001/messages](http://localhost:3001/messages)
  - Bấm nút **Xem** tại từng tin nhắn.
  - Tin thành công: Hiển thị ngay **Form tin nhắn đã gửi đi** với đầy đủ nội dung, Zalo msgId, nhóm đích, SĐT thật.
  - Tin lỗi (Ca 6): Hiển thị **Hộp cảnh báo lỗi nghiệp vụ màu đỏ/cam** chỉ rõ sai ISO Check digit và tin Bot nhắc lỗi. Bản ghi chuẩn 15 trường được thu gọn bên dưới.
- **Kết quả Outbound**: [http://localhost:3001/results](http://localhost:3001/results)
  - Xem danh sách thông báo điều vận, thẻ KPI và nút Phê duyệt / Gửi lại.
- **Hàng Đợi Rà Soát**: [http://localhost:3001/reviews](http://localhost:3001/reviews)
  - Xem các ca cảnh báo nghiệp vụ (Ca 6), bấm **Phê duyệt** để kích hoạt gửi ra Zalo sau khi điều độ viên xác nhận.

### 3. Kiểm tra trong Cơ sở dữ liệu MySQL
```bash
# Xem thống kê số bản ghi nghiệp vụ đã tạo:
python scripts/manage_db.py status

# Dọn dẹp dữ liệu để test lại từ đầu:
python scripts/manage_db.py clean --runtime -y
```
