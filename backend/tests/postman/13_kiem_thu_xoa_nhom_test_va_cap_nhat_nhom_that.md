# 🧪 TÀI LIỆU KIỂM THỬ: XÓA NHÓM TEST & CẬP NHẬT TRẠNG THÁI NHÓM THẬT

Tài liệu này cung cấp các lệnh cURL và kịch bản Postman chi tiết để kiểm thử các API quản lý nhóm Zalo:
1. **Xóa toàn bộ các nhóm thử nghiệm (Test Groups)** khỏi cơ sở dữ liệu (`DELETE /api/groups/test-groups`).
2. **Cập nhật trạng thái nhóm thật theo Zalo Group ID** (`PUT /api/groups/by-zalo-id/{zalo_group_id}/status`).
3. **Cập nhật trạng thái nhóm thật theo Database ID** (`PUT /api/groups/{group_id}/status`).
4. **Chuyển đổi trạng thái gửi tin nhanh** giữa `tu_dong` (Tự động) và `cho_duyet` (Chờ duyệt) (`PUT /api/groups/{group_id}/send-mode`).
5. **Tra cứu danh sách nhóm thật** (`GET /api/groups`).

---

## 1. Xóa tất cả các nhóm test (Test Groups Cleanup)

Hệ thống sẽ lọc và xóa toàn bộ các nhóm có cờ `is_test = true` hoặc các mã định danh chứa tiền tố test (`pytest_`, `grp_test_`, `direct_`, `{{groupId}}`), bảo vệ an toàn 100% cho các nhóm thật.

### cURL
```bash
curl -X DELETE "http://localhost:8000/api/groups/test-groups" \
  -H "Accept: application/json"
```

### Phản hồi mẫu (HTTP 200 OK)
```json
{
  "ok": true,
  "message": "Đã xóa thành công 15 nhóm thử nghiệm khỏi hệ thống.",
  "deleted_count": 15,
  "deleted_groups": [
    "Nhóm Zalo 2001000000000000001 (ID: 1)",
    "Nhóm Zalo direct_6691387223255581446 (ID: 3)",
    "Zalo Group {{groupId}} (ID: 16)",
    "Direct Chat - Anh Bao (ID: 88)",
    "Nhóm Khách Hàng Test - TỰ ĐỘNG (ID: 119)",
    "Nhóm Khách Hàng Test - CHỜ DUYỆT (ID: 120)"
  ],
  "remaining_real_groups": [
    {
      "id": 2,
      "zalo_group_id": "6469608867469758994",
      "name": "Nhóm Khách Hàng VSICO - DC Logistics",
      "send_mode": "tu_dong",
      "is_active": true,
      "is_test": false
    },
    {
      "id": 103,
      "zalo_group_id": "7196206900754562564",
      "name": "Nhóm Khách Hàng Logitem - Tân Quang",
      "send_mode": "tu_dong",
      "is_active": true,
      "is_test": false
    }
  ]
}
```

---

## 2. Cập nhật trạng thái nhóm thật bằng Zalo Group ID (threadId Zalo)

Cho phép điều độ viên hoặc hệ thống cập nhật trực tiếp cấu hình nhóm bằng mã Zalo thực tế (ví dụ `6469608867469758994`).

### cURL
```bash
curl -X PUT "http://localhost:8000/api/groups/by-zalo-id/6469608867469758994/status" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Nhóm Khách Hàng VSICO - DC Logistics",
    "send_mode": "tu_dong",
    "is_active": true,
    "group_role": "destination"
  }'
```

### Phản hồi mẫu (HTTP 200 OK)
```json
{
  "ok": true,
  "message": "Đã cập nhật trạng thái nhóm 'Nhóm Khách Hàng VSICO - DC Logistics' thành công.",
  "group": {
    "id": 2,
    "zalo_group_id": "6469608867469758994",
    "name": "Nhóm Khách Hàng VSICO - DC Logistics",
    "group_role": "destination",
    "send_mode": "tu_dong",
    "send_mode_label": "Tự động",
    "is_active": true,
    "is_test": false
  }
}
```

---

## 3. Cập nhật trạng thái nhóm thật bằng Database ID

### cURL: Chuyển nhóm sang Chờ duyệt (`cho_duyet`) và tạm dừng (`is_active = false`)
```bash
curl -X PUT "http://localhost:8000/api/groups/2/status" \
  -H "Content-Type: application/json" \
  -d '{
    "send_mode": "cho_duyet",
    "is_active": true,
    "name": "Nhóm Khách Hàng VSICO - DC Logistics (Kiểm duyệt)"
  }'
```

### Phản hồi mẫu (HTTP 200 OK)
```json
{
  "ok": true,
  "message": "Đã cập nhật trạng thái nhóm 'Nhóm Khách Hàng VSICO - DC Logistics (Kiểm duyệt)' thành công.",
  "group": {
    "id": 2,
    "zalo_group_id": "6469608867469758994",
    "name": "Nhóm Khách Hàng VSICO - DC Logistics (Kiểm duyệt)",
    "group_role": "destination",
    "send_mode": "cho_duyet",
    "send_mode_label": "Chờ duyệt",
    "is_active": true,
    "is_test": false
  }
}
```

---

## 4. Chuyển đổi nhanh Chế độ phát hành tin (`send_mode`)

### cURL: Chuyển sang Tự động (`tu_dong`)
```bash
curl -X PUT "http://localhost:8000/api/groups/2/send-mode" \
  -H "Content-Type: application/json" \
  -d '{
    "send_mode": "tu_dong"
  }'
```

### Phản hồi mẫu (HTTP 200 OK)
```json
{
  "ok": true,
  "message": "Đã chuyển trạng thái nhóm 'Nhóm Khách Hàng VSICO - DC Logistics' sang 'Tự động'.",
  "group_id": 2,
  "zalo_group_id": "6469608867469758994",
  "send_mode": "tu_dong",
  "send_mode_label": "Tự động"
}
```

---

## 5. Tra cứu danh sách nhóm thật

### cURL
```bash
curl -X GET "http://localhost:8000/api/groups" \
  -H "Accept: application/json"
```

### Phản hồi mẫu (HTTP 200 OK)
```json
{
  "ok": true,
  "total": 2,
  "limit": 50,
  "offset": 0,
  "groups": [
    {
      "id": 2,
      "zalo_group_id": "6469608867469758994",
      "name": "Nhóm Khách Hàng VSICO - DC Logistics",
      "group_role": "destination",
      "send_mode": "tu_dong",
      "send_mode_label": "Tự động",
      "is_active": true,
      "is_test": false
    },
    {
      "id": 103,
      "zalo_group_id": "7196206900754562564",
      "name": "Nhóm Khách Hàng Logitem - Tân Quang",
      "group_role": "destination",
      "send_mode": "tu_dong",
      "send_mode_label": "Tự động",
      "is_active": true,
      "is_test": false
    }
  ]
}
```
