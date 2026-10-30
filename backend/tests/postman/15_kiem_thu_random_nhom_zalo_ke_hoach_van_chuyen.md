# 🎲 TÀI LIỆU KIỂM THỬ POSTMAN & CURL: PHÂN BỔ NGẪU NHIÊN 3 NHÓM ZALO THẬT CHO KẾ HOẠCH VẬN CHUYỂN

Tài liệu này hướng dẫn chi tiết quy trình kiểm thử thêm nhóm Zalo thật thứ 3 (`test3`) và phân bổ ngẫu nhiên (random) `group_id` giữa 3 nhóm Zalo thật trong Kế hoạch vận chuyển (`transport_plans`).

---

## 1. Danh Sách 3 Nhóm Zalo Thật Của Hệ Thống

| ID | Zalo Group ID | Tên Nhóm Gốc | Tên Hiển Thị Trong Hệ Thống | Vai Trò | Chế Độ Gửi | Trạng Thái |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `3051850159021421440` | `test3` | **Nhóm Test 3 (3051850159021421440)** | `destination` | `cho_duyet` | Đang hoạt động |
| **2** | `6469608867469758994` | `khách hàng` | **Nhóm Khách Hàng VSICO - DC Logistics** | `destination` | `cho_duyet` | Đang hoạt động |
| **3** | `7196206900754562564` | `nhà xe` | **Nhóm Khách Hàng Logitem - Tân Quang** | `destination` | `cho_duyet` | Đang hoạt động |

---

## 2. Lệnh cURL Kiểm Thử API Phân Bổ Ngẫu Nhiên (Randomize Group ID)

### Endpoint: `POST /api/plans/randomize-groups`

#### Request: Random phân bổ ngẫu nhiên toàn bộ 103 bản ghi kế hoạch
```bash
curl -X POST "http://localhost:8000/api/plans/randomize-groups" \
  -H "Content-Type: application/json" \
  -d '[
    "3051850159021421440",
    "6469608867469758994",
    "7196206900754562564"
  ]'
```

#### Phản Hồi Kỳ Vọng (HTTP 200 OK):
```json
{
  "ok": true,
  "status": "OK",
  "message": "Đã cập nhật ngẫu nhiên group_id cho 103 bản ghi kế hoạch giữa 3 nhóm Zalo.",
  "total_updated": 103,
  "group_distribution": {
    "3051850159021421440": 35,
    "6469608867469758994": 34,
    "7196206900754562564": 34
  }
}
```

---

## 3. Lệnh cURL Kiểm Tra Dữ Liệu Sau Khi Random

### Lấy danh sách kế hoạch ngày 2026-10-12
```bash
curl -X GET "http://localhost:8000/api/plans?plan_date=2026-10-12&limit=10" \
  -H "Accept: application/json"
```

Các bản ghi kế hoạch sẽ có cột `group_id` được phân bổ đều và ngẫu nhiên thành một trong 3 nhóm:
- `"3051850159021421440"`
- `"6469608867469758994"`
- `"7196206900754562564"`

---

## 4. Thao Tác Trực Tiếp Trên Web UI Frontend

1. Truy cập trang **Kế Hoạch Vận Chuyển**: `http://localhost:3001/plans` (hoặc port 3000).
2. Tại thanh công cụ trên cùng, nhấn nút màu tím: **`[🎲 Random 3 Nhóm Zalo]`**.
3. Hệ thống sẽ gọi API, tự động đảo ngẫu nhiên toàn bộ kế hoạch và hiển thị banner thông báo số lượng container được phân bổ vào từng nhóm.
4. Truy cập trang **Quản Lý Nhóm Zalo**: `http://localhost:3001/groups` để kiểm tra trạng thái hoạt động và cấu hình chế độ gửi (`cho_duyet` hoặc `tu_dong`) cho cả 3 nhóm thật.
