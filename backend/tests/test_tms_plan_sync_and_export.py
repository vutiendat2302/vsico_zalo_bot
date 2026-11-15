"""Kiểm thử đồng bộ kế hoạch TMS theo ngày, API giao diện điều hành và xuất Excel chuẩn ketnoi.xlsx."""

from datetime import date
from types import SimpleNamespace

from src.api.app import app
from src.infrastructure.models import TransportPlan
from src.infrastructure.security import get_current_user
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiClient
from src.parsing.plan_exporter import export_plans_to_ketnoi_excel
from src.parsing.plan_importer import PlanFileParser


def _sample_tms_payload() -> dict:
    """Tạo dữ liệu phản hồi TMS giả lập phục vụ kiểm thử đơn vị và tích hợp."""
    return {
        "data": [
            {
                "province_id": 27,
                "province_name": "Tỉnh Bắc Ninh",
                "return_orders": [
                    {
                        "id": 990001,
                        "order_code": "RO9001",
                        "plan_date": "31/12/2099",
                        "forwarder_id": 1,
                        "fwd_name": "VSICO Log",
                        "customer_name": "UNILEVER",
                        "warehouse_name": "KHO UNILEVER VSIP BẮC NINH",
                        "warehouse_address": "KCN VSIP, Từ Sơn, Bắc Ninh",
                        "ward_name": "Phường Từ Sơn",
                        "terminal_name": "PTSC",
                        "vessel_voyage_name": "PROSPER 2637N",
                        "commodity_name": "HOA MY PHAM",
                        "gross_weight": 26.5,
                        "required_time": "07:00",
                        "bill_of_lading_no_code": "VS991100",
                        "container_type": "HC",
                        "container_size": "40",
                        "container_no": "GAOU7821312",
                        "container_seal": "22554258",
                        "container_grade_id": 1,
                        "container_ownership": 1,
                        "delivery_term": 1,
                        "dispatch_state": 1,
                        "container_warning": "normal",
                        "container_status_message": "Bình thường",
                    },
                    {
                        "id": 990002,
                        "order_code": "RO9002",
                        "plan_date": "31/12/2099",
                        "forwarder_id": 2,
                        "fwd_name": "VEX Đông Nam",
                        "customer_name": "ACECOOK",
                        "warehouse_name": "KHO ACECOOK TIÊN SƠN",
                        "warehouse_address": "KCN Tiên Sơn, Bắc Ninh",
                        "ward_name": "Phường Tam Sơn",
                        "terminal_name": "NAM HẢI",
                        "commodity_name": "MY AN LIEN",
                        "gross_weight": 14.2,
                        "required_time": "09:00",
                        "container_type": "DC",
                        "container_size": "20",
                        "container_no": "VSIU2623434",
                        "container_warning": "empty_drop",
                        "container_status_message": "Chỉ định hạ rỗng",
                        "delivery_term": 2,
                        "dispatch_state": 0,
                    },
                ],
                "loading_orders": [
                    {
                        "id": 990003,
                        "order_code": "LO9003",
                        "plan_date": "31/12/2099",
                        "forwarder_id": 1,
                        "fwd_name": "VSICO Log",
                        "customer_name": "HONDA",
                        "warehouse_name": "KHO HONDA ĐỒNG VĂN",
                        "warehouse_address": "KCN Đồng Văn, Hà Nam",
                        "ward_name": "Phường Đồng Văn",
                        "terminal_name": "PTSC",
                        "commodity_name": "XE MAY",
                        "required_time": "14:00",
                        "booking_no_code": "BK991100",
                        "container_size": "40",
                        "container_type": "HC",
                        "delivery_term": 1,
                        "dispatch_state": 0,
                        "etd": "2099-12-31 18:00:00",
                        "points": [
                            {
                                "warehouse_name": "KHO HONDA ĐỒNG VĂN",
                                "ward_name": "Phường Đồng Văn",
                                "address": "KCN Đồng Văn, Hà Nam",
                                "required_time": "14:00",
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_sync_tms_upsert_master_and_export_excel(api_client, monkeypatch):
    """Kiểm tra đồng bộ TMS, upsert cập nhật lại, API master theo tỉnh và xuất Excel 23 cột."""
    payload = _sample_tms_payload()

    def _fake_fetch(self, plan_date: str, region: int = 1):
        """Giả lập phản hồi GET /transport-plan từ TMS."""
        assert plan_date == "2099-12-31"
        assert region == 1
        return payload

    monkeypatch.setattr(TmsApiClient, "fetch_transport_plan_by_date", _fake_fetch)

    # 1. Đồng bộ lần đầu qua API
    res1 = api_client.post("/api/plans/sync-tms?plan_date=2099-12-31&region=1")
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["ok"] is True
    assert body1["inserted"] == 3
    assert body1["updated"] == 0
    assert body1["return_orders_count"] == 2
    assert body1["loading_orders_count"] == 1
    assert body1["default_group_id_applied"] == "b0301d81c0ee29b070ff"

    # 2. Đồng bộ lại lần 2 -> phải upsert (updated=3, inserted=0)
    payload["data"][0]["loading_orders"][0]["booking_no_code"] = "BK991100-UPD"
    res2 = api_client.post("/api/plans/sync-tms?plan_date=2099-12-31&region=1")
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["inserted"] == 0
    assert body2["updated"] == 3

    # 3. Kiểm tra danh sách kế hoạch chính GET /api/plans
    res_list = api_client.get("/api/plans?plan_date=2099-12-31&q=BK991100-UPD")
    assert res_list.status_code == 200
    list_body = res_list.json()
    assert list_body["total"] == 1
    assert list_body["plans"][0]["order_code"] == "LO9003"
    assert list_body["plans"][0]["group_id"] == "b0301d81c0ee29b070ff"
    assert list_body["plans"][0]["delivery_term"] == 1

    # 4. Kiểm tra API giao diện Tùy chọn -> Kế hoạch TMS (cần đăng nhập)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="ADMIN")
    try:
        res_master = api_client.get("/api/master/transport-plans?plan_date=2099-12-31&region=1")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert res_master.status_code == 200
    m_body = res_master.json()
    assert m_body["total_orders"] == 3
    bal_total = m_body["summary"]["container_balance"]["total"]
    assert bal_total == {
        "return_count": 2,
        "unmatchable_count": 1,
        "matchable_count": 1,
        "loading_count": 1,
        "balance": 0,
    }
    assert m_body["summary"]["container_warning_counts"]["empty_drop"] == 1
    assert len(m_body["provinces"]) == 1
    assert len(m_body["provinces"][0]["return_orders"]) == 2
    assert len(m_body["provinces"][0]["loading_orders"]) == 1

    # 5. Kiểm tra xuất Excel chuẩn ketnoi.xlsx và đọc ngược lại bằng PlanFileParser
    res_xls = api_client.get("/api/plans/export-excel?plan_date=2099-12-31")
    assert res_xls.status_code == 200
    assert "spreadsheetml.sheet" in res_xls.headers["content-type"]

    parsed_date, parsed_records = PlanFileParser.parse_excel(
        file_bytes=res_xls.content,
        default_group_id="b0301d81c0ee29b070ff",
    )
    assert parsed_date == date(2099, 12, 31)
    assert len(parsed_records) == 3
    assert all(r["group_id"] == "b0301d81c0ee29b070ff" for r in parsed_records)


def test_plan_exporter_empty_and_group_default():
    """Kiểm tra xuất Excel trực tiếp giữ nguyên group_id mặc định b0301d81c0ee29b070ff."""
    plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 31),
        stt=1,
        order_code="RO9999",
        order_type="tra",
        cargo_io_type="I",
        container_no="GAOU7821312",
        container_size="40",
        customer_name="UNILEVER",
        delivery_address="KCN VSIP",
    )
    raw = export_plans_to_ketnoi_excel([plan], plan_date=date(2099, 12, 31))
    parsed_date, records = PlanFileParser.parse_excel(raw)
    assert parsed_date == date(2099, 12, 31)
    assert len(records) == 1
    assert records[0]["group_id"] == "b0301d81c0ee29b070ff"
    assert records[0]["order_type"] == "tra"
