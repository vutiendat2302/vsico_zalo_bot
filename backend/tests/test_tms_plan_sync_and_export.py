"""Kiểm thử đồng bộ kế hoạch TMS theo ngày, API giao diện điều hành và xuất Excel chuẩn ketnoi.xlsx."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from src.api.app import app
from src.handlers.tms_auto_sync import TmsAutoSyncScheduler
from src.infrastructure.models import Carrier, Customer, TransportPlan, User, Warehouse
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


def test_tms_client_proactive_and_401_relogin(monkeypatch):
    """Kiểm tra TmsApiClient chủ động đăng nhập lại khi token quá tuổi hoặc gặp HTTP 401."""
    client = TmsApiClient(
        base_url="https://mock-tms.local/api",
        username="tms_user",
        password="tms_password",
    )
    login_calls = 0

    def _fake_login() -> str:
        nonlocal login_calls
        login_calls += 1
        client._token = f"tok-{login_calls}"
        client.token_obtained_at = datetime.now(timezone.utc)
        return client._token

    monkeypatch.setattr(client, "login", _fake_login)

    # 1. Token quá tuổi -> tự re-login chủ động trước khi gọi request
    client._token = "stale-tok"
    client.token_obtained_at = datetime.now(timezone.utc) - timedelta(hours=5)
    assert client.ensure_fresh_token() == "tok-1"
    assert login_calls == 1

    # 2. Gặp HTTP 401 -> tự re-login lại một lần rồi retry thành công
    attempt_tokens: list[str] = []

    class _FakeResp:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class _FakeHttpxClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def request(self, _method, _url, params=None, json=None, headers=None):
            attempt_tokens.append(headers["Authorization"])
            if len(attempt_tokens) == 1:
                return _FakeResp(401, {"status": "error", "message": "Token expired"})
            return _FakeResp(200, {"status": "ok", "data": []})

    monkeypatch.setattr("src.infrastructure.tms_client.httpx.Client", _FakeHttpxClient)
    res = client._request_json("GET", "/transport-plan")
    assert res["status"] == "ok"
    assert login_calls == 2
    assert attempt_tokens == ["Bearer tok-1", "Bearer tok-2"]


def test_tms_auto_sync_scheduler_and_status_endpoints(db_session, api_client, monkeypatch):
    """Kiểm tra TmsAutoSyncScheduler chủ động kéo danh mục + kế hoạch và endpoint trạng thái."""
    target_date = date(2099, 12, 31)

    class _FakeTmsClient(TmsApiClient):
        def __init__(self):
            super().__init__(
                base_url="https://mock-tms.local/api",
                username="tms_user",
                password="tms_password",
            )
            self._token = "fake-tok"
            self.token_obtained_at = datetime.now(timezone.utc)
            self.forwarder_id = 1

        def ensure_fresh_token(self, *, force_refresh: bool = False) -> str:
            return "fake-tok"

        def fetch_carriers(self, per_page: int = 100, active_only: bool = True):
            return [{"id": 77, "code": "NX77", "name": "Nhà xe Tự Động", "short_name": "Tự Động", "status": 1}]

        def fetch_customers(self):
            return [{"id": "55", "name": "UNILEVER", "short_name": "UNILEVER"}]

        def fetch_warehouses(self, per_page: int = 100, active_only: bool = True):
            return [
                {
                    "id": "88",
                    "name": "KHO UNILEVER VSIP BẮC NINH",
                    "address": "KCN VSIP, Bắc Ninh",
                    "status": 1,
                    "forwarder_relations": [{"forwarder_id": 1, "customer_id": "55"}],
                }
            ]

        def fetch_trailers(self, per_page: int = 100, active_only: bool = True):
            return []

        def fetch_confirmed_dispatches(self, plan_date: str):
            return []

        def fetch_transport_plan_by_date(self, plan_date: str, region: int = 1):
            if plan_date == target_date.isoformat() and region == 1:
                return _sample_tms_payload()
            return {"data": []}

    class _NoCloseSession:
        """Wrapper ngăn scheduler đóng session fixture kiểm thử."""

        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            return self._inner

        def __exit__(self, *_args):
            return False

    scheduler = TmsAutoSyncScheduler(
        session_factory=lambda: _NoCloseSession(db_session),
        client_factory=_FakeTmsClient,
    )
    scheduler.track_date(target_date, 1)
    summary = scheduler.run_once(force_master=True)

    assert summary["error"] is None
    assert summary["master_synced"] is True
    assert summary["total_synced"] == 3

    carrier = db_session.scalar(select(Carrier).where(Carrier.tms_carrier_id == 77))
    cust = db_session.scalar(select(Customer).where(Customer.tms_customer_id == "55"))
    wh = db_session.scalar(select(Warehouse).where(Warehouse.tms_warehouse_id == "88"))
    assert carrier is not None and carrier.name == "Nhà xe Tự Động"
    assert cust is not None and cust.name == "UNILEVER"
    assert wh is not None and wh.customer_id == cust.id

    st = scheduler.status()
    assert st["total_runs"] == 1
    assert st["last_success_at"] is not None
    assert st["last_error"] is None

    res_status = api_client.get("/api/plans/tms-sync-status")
    assert res_status.status_code == 200
    assert res_status.json()["ok"] is True


def test_auth_refresh_renews_active_session_token(db_session, api_client):
    """Kiểm tra POST /api/auth/refresh cấp lại JWT Access Token mới cho người dùng đang hoạt động."""
    user = User(
        id=snowflake.generate(),
        username="dhvt_refresh_test",
        full_name="ĐHVT Test Refresh",
        role="DHVT",
        email="dhvt_refresh@vsico.com.vn",
        password_hash="hashed",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        res = api_client.post("/api/auth/refresh")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20
    assert body["user"]["username"] == "dhvt_refresh_test"
    assert "vsico_token=" in (res.headers.get("set-cookie") or "")


def test_sync_plan_to_tms_automatically_pulls_updated_plan(db_session, monkeypatch):
    """Sau khi đẩy cập nhật lên TMS thành công, hệ thống phải tự động kéo đồng bộ lại bảng transport_plans."""
    from src.config.settings import settings
    from src.handlers.plan_sync_service import sync_plan_to_tms
    from src.infrastructure.models import ActivityLog

    target_date = date(2099, 12, 31)
    plan = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=990003,
        order_code="LO9003",
        plan_date=target_date,
        region=1,
        order_type="dong",
        cargo_io_type="X",
        planned_truck_plate="15H-008.14",
        driver_name="Nguyễn Văn A",
        driver_phone="0986123456",
        dispatch_state=0,
        tms_sync_status="PENDING",
    )
    db_session.add(plan)
    db_session.commit()

    class _FakeReadAfterWriteClient:
        def push_dispatch_assignment(self, payload, *, idempotency_key=None, correlation_id=None):
            return 200, {"status": "ok", "message": "updated"}

        def fetch_transport_plan_by_date(self, plan_date: str, region: int = 1):
            sample = _sample_tms_payload()
            sample["data"][0]["loading_orders"][0]["dispatch_state"] = 1
            sample["data"][0]["loading_orders"][0]["booking_no_code"] = "BK991100-AFTER-WRITE"
            return sample

    monkeypatch.setattr(settings, "TMS_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "TMS_WRITE_ENABLED", True)

    status = sync_plan_to_tms(
        db_session,
        plan,
        client=_FakeReadAfterWriteClient(),
        changed_fields={"planned_truck_plate": "15H-008.14"},
    )
    db_session.commit()
    db_session.refresh(plan)

    assert status == "SYNCED"
    assert plan.tms_sync_status == "SYNCED"
    assert plan.dispatch_state == 1
    assert plan.booking_no == "BK991100-AFTER-WRITE"
    assert plan.planned_truck_plate == "15H-008.14"

    refresh_log = db_session.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "TMS_POST_WRITE_PLAN_REFRESHED",
            ActivityLog.entity_id == str(plan.id),
        )
    )
    assert refresh_log is not None


def test_trailers_sync_and_master_filters(db_session, api_client, monkeypatch):
    """Kiểm tra đồng bộ rơ-moóc từ TMS và API GET /api/master/trailers với tìm kiếm/bộ lọc."""
    from src.handlers.tms_auto_sync import sync_trailers_from_tms
    from src.infrastructure.models import Trailer

    carrier = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=999434,
        code="CAR_TEST_999434",
        name="CÔNG TY TEST RƠ MOÓC",
        short_name="TESTMOOC",
        normalized_name="testmooc",
        is_active=True,
    )
    db_session.add(carrier)
    db_session.commit()

    sample_rows = [
        {
            "id": 999029,
            "carrier_id": 999434,
            "license_plate": "15R99129",
            "type": 2,
            "model": "CIMC 40FT",
            "note": "Moóc sàn test",
            "status": 1,
        },
        {
            "id": 999030,
            "carrier_id": 999434,
            "license_plate": "29R-99187",
            "type": 1,
            "model": "Thaco 40FT",
            "note": "Moóc xương test",
            "status": 0,
        },
    ]

    monkeypatch.setattr(TmsApiClient, "fetch_trailers", lambda self, per_page=100, active_only=False: sample_rows)
    stats = sync_trailers_from_tms(db_session, TmsApiClient())
    db_session.commit()
    assert stats == {"fetched": 2, "created": 2, "updated": 0}

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="ADMIN")
    try:
        r_all = api_client.get(f"/api/master/trailers?carrier_id={carrier.id}")
        assert r_all.status_code == 200
        body_all = r_all.json()
        assert body_all["total"] == 2
        assert "CIMC 40FT" in body_all["filter_options"]["models"]
        assert "Thaco 40FT" in body_all["filter_options"]["models"]

        # Tìm theo biển số không dấu gạch ngang
        r_search = api_client.get("/api/master/trailers?search=29R99187")
        assert r_search.status_code == 200
        assert r_search.json()["total"] == 1
        assert r_search.json()["items"][0]["license_plate"] == "29R-99187"

        # Lọc theo mooc_type, model, carrier_id và is_active
        r_filtered = api_client.get(
            f"/api/master/trailers?mooc_type=2&model=CIMC+40FT&carrier_id={carrier.id}&is_active=true"
        )
        assert r_filtered.status_code == 200
        assert r_filtered.json()["total"] == 1
        assert r_filtered.json()["items"][0]["tms_mooc_id"] == "999029"

        # Đồng bộ thủ công qua API POST /api/master/trailers/sync (upsert không nhân đôi)
        r_sync = api_client.post("/api/master/trailers/sync")
        assert r_sync.status_code == 200
        assert r_sync.json()["updated"] == 2
        assert db_session.query(Trailer).filter(Trailer.carrier_id == carrier.id).count() == 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        db_session.query(Trailer).filter(Trailer.tms_mooc_id.in_([999029, 999030])).delete(synchronize_session=False)
        db_session.query(Carrier).filter(Carrier.id == carrier.id).delete(synchronize_session=False)
        db_session.commit()


def test_sync_tms_fills_combined_loading_container_from_confirmed_dispatch(db_session):
    """Đồng bộ kế hoạch tự lấy bổ sung container_no của lệnh đóng từ /dispatch/confirmed khi /transport-plan để trống."""
    from src.handlers.tms_plan_sync_service import sync_transport_plans_from_tms

    class _FakeCombinedClient:
        def fetch_transport_plan_by_date(self, plan_date: str, region: int = 1):
            return _sample_tms_payload()

        def fetch_confirmed_dispatches(self, plan_date: str):
            return [
                {
                    "id": 17436,
                    "carrier_id": 434,
                    "carrier_name": "VSICO",
                    "truck_no": "29C46732",
                    "driver_id": 639,
                    "driver_name": "Nguyễn Viết Phú",
                    "loading_order": {
                        "id": 990003,
                        "order_code": "LO9003",
                        "container_no": "TMSU4000770",
                    },
                }
            ]

    res = sync_transport_plans_from_tms(
        db_session,
        plan_date=date(2099, 12, 31),
        region=1,
        client=_FakeCombinedClient(),
        auto_commit=False,
    )
    assert res["total_synced"] >= 3
    lo_plan = db_session.scalar(select(TransportPlan).where(TransportPlan.tms_order_id == 990003))
    assert lo_plan is not None
    assert lo_plan.container_no == "TMSU4000770"
    assert lo_plan.planned_truck_plate == "29C-467.32"
    assert lo_plan.driver_name == "Nguyễn Viết Phú"
