"""Bộ Kiểm Thử Toàn Diện Cho Module Kế Hoạch Vận Chuyển Hằng Ngày (Transport Plans).

Kiểm tra:
1. Import file Excel thực tế `tests/data_test/ketnoi.xlsx` qua `POST /api/plans/import-excel`.
2. Kiểm tra chính xác 100% các dòng đều có `group_id = 6469608867469758994`.
3. Kiểm tra phân loại lệnh Đóng (`dong`) vs Trả (`tra`) theo cột Hàng (Xuất/Nhập).
4. Kiểm tra đầy đủ các API CRUD:
   - `GET /api/plans` (lọc theo ngày, số cont, khách hàng, loại lệnh)
   - `GET /api/plans/{id}`
   - `POST /api/plans` (tạo thủ công, tự động suy luận order_type và gán group_id mặc định)
   - `PUT /api/plans/{id}` (cập nhật thông tin)
   - `DELETE /api/plans/{id}`
   - `DELETE /api/plans/by-date/{date}`
5. Kiểm tra API Import file CSV: `POST /api/plans/import-csv`.
6. Kiểm tra ghép nối tự động (End-to-End Matching): Tin nhắn Zalo F1 chỉ có số cont `SELU4396800`
   tự động tra bảng kế hoạch để lấy Khách hàng 'Logitem', Lệnh Trả 'tra' và Địa chỉ kho.
"""

from datetime import date
import io
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)

TARGET_GROUP_ID = "6469608867469758994"


def test_01_import_excel_ketnoi() -> None:
    """Kiểm thử import file Excel kế hoạch ngày 12/10/2026 từ ketnoi.xlsx."""
    with open("tests/data_test/ketnoi.xlsx", "rb") as f:
        file_bytes = f.read()

    res = client.post(
        "/api/plans/import-excel",
        files={"file": ("ketnoi.xlsx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        params={"replace_existing": "true"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["plan_date"] == "2026-10-12"
    assert data["total_imported"] >= 95
    assert data["default_group_id_applied"] == TARGET_GROUP_ID

    # Kiểm tra truy vấn danh sách ngày 2026-10-12
    list_res = client.get("/api/plans", params={"plan_date": "2026-10-12", "limit": 200})
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 95

    # Toàn bộ các dòng phải có group_id = 6469608867469758994
    for p in list_data["plans"]:
        assert p["group_id"] == TARGET_GROUP_ID, f"Plan {p['id']} có group_id sai: {p['group_id']}"

    # Kiểm tra phân định Đóng / Trả
    # Row 1 (STT 1): SELU4396800 là Nhập -> tra
    row1 = next((p for p in list_data["plans"] if p["container_no"] == "SELU4396800"), None)
    assert row1 is not None
    assert row1["order_type"] == "tra"
    assert row1["customer_name"] == "Logitem"
    assert "Logitem (Tân Quang)" in (row1["delivery_address"] or "")

    # Row 55 (STT 55): GAOU7820384 là Xuất -> dong
    row_xuat = next((p for p in list_data["plans"] if p["stt"] == 55), None)
    assert row_xuat is not None
    assert row_xuat["order_type"] == "dong"
    assert row_xuat["cargo_io_type"] == "X"


def test_02_crud_transport_plan_endpoints() -> None:
    """Kiểm thử toàn bộ các thao tác CRUD cơ bản trên bảng transport_plans."""
    test_date = "2026-10-30"

    # 1. Tạo mới thủ công (POST /api/plans)
    create_payload = {
        "plan_date": test_date,
        "stt": 999,
        "route_name": "HP - Hà Nội",
        "cargo_io_type": "I",
        "container_no": "TEST9999999",
        "seal_no": "SEAL999",
        "container_size": "40",
        "cargo_weight": 28.5,
        "required_time": "08:30",
        "customer_name": "Công ty Test VSICO",
        "cargo_type": "Hàng tiêu dùng",
        "vessel_voyage": "Vsico Star 01",
        "empty_depot": "Bãi Chùa Vẽ",
        "full_depot": "PTSC Đình Vũ",
        "estimated_drop_time": "17:00",
        "fleet_partner": "Đội xe Test 1",
        "planned_truck_plate": "15C-999.99",
        "delivery_address": "Kho Test Hà Nội",
        # Để trống group_id để hệ thống tự động gán mặc định
    }
    create_res = client.post("/api/plans", json=create_payload)
    assert create_res.status_code == 200, create_res.text
    created = create_res.json()
    plan_id = created["id"]
    assert created["container_no"] == "TEST9999999"
    assert created["order_type"] == "tra"  # Tự động suy luận từ cargo_io_type = 'I'
    assert created["group_id"] == TARGET_GROUP_ID  # Tự động gán mặc định

    # 2. Lấy chi tiết theo ID (GET /api/plans/{id})
    get_res = client.get(f"/api/plans/{plan_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == plan_id

    # 3. Cập nhật (PUT /api/plans/{id})
    update_res = client.put(
        f"/api/plans/{plan_id}",
        json={"required_time": "09:00", "seal_no": "SEAL_UPDATED_888"},
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["required_time"] == "09:00"
    assert updated["seal_no"] == "SEAL_UPDATED_888"

    # 4. Lọc danh sách (GET /api/plans)
    filter_res = client.get(
        "/api/plans",
        params={"plan_date": test_date, "container_no": "TEST9999999"},
    )
    assert filter_res.status_code == 200
    assert filter_res.json()["total"] == 1

    # 5. Xóa theo ID (DELETE /api/plans/{id})
    del_res = client.delete(f"/api/plans/{plan_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "DELETED"

    # Kiểm tra lại không còn tồn tại
    assert client.get(f"/api/plans/{plan_id}").status_code == 404


def test_03_import_csv_endpoint() -> None:
    """Kiểm thử import file CSV qua POST /api/plans/import-csv."""
    csv_content = """STT,Tuyến vận chuyển,Hàng,Số cont,Số Seal,SL 20,SL 40,Tải trọng,YC thời gian,Khách hàng,Loại hàng,Chuyến tàu,Bãi nâng/hạ vỏ,Bãi nâng/hạ hàng,Giờ hạ hàng,Đội xe,Số xe,Địa chỉ đóng/ trả hàng,Group ID,CB giao nhận,Ghi chú,Phát sinh
1,HP - Tân Quang,Nhập,CSVU1111111,SEAL01,,1,10.5,7h,Khách CSV Nhập,Mỳ,Prosper 2633N,,PTSC,,Tuấn Hưng,,Kho Tân Quang,6469608867469758994,,,
2,HP - Bắc Ninh,Xuất,CSVU2222222,SEAL02,,1,24.0,8h,Khách CSV Xuất,Nắp lon,New Vision 2627N,,PTSC,,Minh Ngân,,KCN Quế Võ,,,,
"""
    res = client.post(
        "/api/plans/import-csv",
        files={"file": ("plan_test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        params={"replace_existing": "true", "plan_date": "2026-10-31"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["total_imported"] == 2
    assert data["plan_date"] == "2026-10-31"

    # Kiểm tra trong DB
    list_res = client.get("/api/plans", params={"plan_date": "2026-10-31"})
    assert list_res.status_code == 200
    plans = list_res.json()["plans"]
    assert len(plans) == 2

    p_nhap = next(p for p in plans if p["container_no"] == "CSVU1111111")
    assert p_nhap["order_type"] == "tra"
    assert p_nhap["group_id"] == TARGET_GROUP_ID

    p_xuat = next(p for p in plans if p["container_no"] == "CSVU2222222")
    assert p_xuat["order_type"] == "dong"
    assert p_xuat["group_id"] == TARGET_GROUP_ID  # Tự động điền default_group_id vì ô trong CSV để trống!

    # Dọn dẹp dữ liệu test ngày 2026-10-31
    client.delete("/api/plans/by-date/2026-10-31")


def test_04_e2e_matching_with_f1_message() -> None:
    """Kiểm thử ghép nối End-to-End: Tin nhắn F1 tự động lấy Khách hàng, Loại lệnh và Địa chỉ từ bảng kế hoạch."""
    # Tin nhắn F1 của nhà xe miền Bắc: chỉ có xe, tài xế, cont SELU4396800, seal
    # Tin này KHÔNG CÓ tên khách, KHÔNG CÓ chữ đóng hay trả, KHÔNG CÓ địa chỉ
    f1_msg = "1 xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / SELU4396800 chì VSICO23675080"

    res = client.post(
        "/api/messages/test-parse",
        json={"text": f1_msg, "timestamp": "2026-10-12T08:00:00", "allow_ai_fallback": False},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["source_format"] == "F1"
    assert data["used_ai"] is False

    canon = data["canonical_records"][0]
    assert canon["cont_no"] == "SELU4396800"
    # Nhờ bảng kế hoạch đã import ở test_01:
    assert canon["order_type"] == "tra"
    assert canon["customer_raw"] == "Logitem"
    assert "Logitem (Tân Quang)" in (canon["location_raw"] or "")
    assert canon["match_source"] == "transport_plan"


def test_05_randomize_groups_endpoint() -> None:
    """Kiểm thử API phân bổ ngẫu nhiên Group ID Zalo cho Kế hoạch vận chuyển."""
    res = client.post(
        "/api/plans/randomize-groups",
        json=["3051850159021421440", "6469608867469758994", "7196206900754562564"],
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["total_updated"] >= 95
    dist = data["group_distribution"]
    assert "3051850159021421440" in dist
    assert "6469608867469758994" in dist
    assert "7196206900754562564" in dist
    # Đảm bảo mỗi nhóm đều nhận được ít nhất 20 bản ghi
    for gid, count in dist.items():
        assert count >= 20, f"Nhóm {gid} chỉ có {count} bản ghi (dưới 20)!"

