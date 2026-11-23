"""Kiểm thử tích hợp TMS Dispatch Assignment (`POST /api/integrations/zalo/dispatch-assignment`).

Bao phủ tối thiểu 22 kịch bản theo hợp đồng API cập nhật từng phần (partial update),
chỉ dùng mock/stub HTTP transport và transaction savepoint, tuyệt đối không ghi TMS thật.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from src.api.app import app
from src.assistant.service import handle_assistant
from src.config.settings import settings
from src.domain.rules import compute_iso6346_check_digit
from src.handlers.extraction_handler import ExtractionHandler
from src.handlers.plan_sync_service import (
    build_dispatch_assignment_payload,
    sync_plan_to_tms,
)
from src.infrastructure.models import (
    ActivityLog,
    Carrier,
    Customer,
    Driver,
    MessageDraft,
    OutboundMessage,
    ReviewCase,
    TmsSyncLog,
    TransportPlan,
    User,
    Vehicle,
    Warehouse,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.security import create_access_token
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiClient, TmsApiError

REF_TIME = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
_REAL_HTTPX_CLIENT = httpx.Client


def _valid_cont(prefix_digits: str) -> str:
    """Tạo số container 11 ký tự hợp lệ ISO 6346 từ 10 ký tự đầu."""
    cd = compute_iso6346_check_digit(prefix_digits + "0")
    return f"{prefix_digits}{cd}"


def _setup_fixture(db_session, *, send_mode: str = "AUTO"):
    """Khởi tạo 2 nhà xe, 2 xe, tài xế, khách hàng, kho, nhóm Zalo và 2 kế hoạch LO/RO mẫu."""
    tok = uuid4().hex[:6]
    car_a = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=snowflake.generate(),
        name=f"Vận Tải A {tok}",
        normalized_name=f"van tai a {tok}",
        is_active=True,
    )
    car_b = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=snowflake.generate(),
        name=f"Vận Tải B {tok}",
        normalized_name=f"van tai b {tok}",
        is_active=True,
    )
    cust = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"CUST_{tok}",
        name=f"Khách {tok}",
        normalized_name=f"khach {tok}",
        is_active=True,
    )
    wh = Warehouse(
        id=snowflake.generate(),
        tms_warehouse_id=f"WH_{tok}",
        customer_id=cust.id,
        name=f"Kho {tok}",
        normalized_name=f"kho {tok}",
        is_active=True,
    )
    db_session.add_all([car_a, car_b, cust, wh])
    db_session.flush()

    veh_a = Vehicle(
        id=snowflake.generate(),
        tms_vehicle_id=123000 + int(tok[:4], 16),
        carrier_id=car_a.id,
        plate_no="15H-00814",
        vehicle_type=1,
        is_active=True,
    )
    veh_b = Vehicle(
        id=snowflake.generate(),
        tms_vehicle_id=456000 + int(tok[:4], 16),
        carrier_id=car_b.id,
        plate_no="15C-999.88",
        vehicle_type=1,
        is_active=True,
    )
    drv_a = Driver(
        id=snowflake.generate(),
        tms_driver_id=789000 + int(tok[:4], 16),
        carrier_id=car_a.id,
        full_name="Trần Văn Hùng",
        normalized_name="tran van hung",
        phone="0986123456",
        is_active=True,
    )
    drv_dup_1 = Driver(
        id=snowflake.generate(),
        tms_driver_id=881000 + int(tok[:4], 16),
        carrier_id=car_a.id,
        full_name="Nguyễn Văn A",
        normalized_name="nguyen van a",
        phone="0901111111",
        is_active=True,
    )
    drv_dup_2 = Driver(
        id=snowflake.generate(),
        tms_driver_id=882000 + int(tok[:4], 16),
        carrier_id=car_a.id,
        full_name="Nguyễn Văn A",
        normalized_name="nguyen van a",
        phone="0902222222",
        is_active=True,
    )
    db_session.add_all([veh_a, veh_b, drv_a, drv_dup_1, drv_dup_2])

    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"pytest_src_{tok}",
        name=f"Nhóm NX {tok}",
        group_role="SOURCE",
        carrier_id=str(car_a.id),
        carrier_name=car_a.name,
        send_mode=send_mode,
        is_active=True,
        is_test=True,
    )
    dest_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"pytest_dest_{tok}",
        name=f"Nhóm KH {tok}",
        group_role="DESTINATION",
        send_mode=send_mode,
        is_active=True,
        is_test=True,
    )
    db_session.add_all([src_grp, dest_grp])
    db_session.flush()

    cont_ro = _valid_cont("MSCU236054")
    lo_code = f"LO{int(tok[:4], 16):05d}"
    lo2_code = f"LO{int(tok[:4], 16) + 1:05d}"
    ro_code = f"RO{int(tok[:4], 16):05d}"

    lo_plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 10),
        order_code=lo_code,
        tms_order_id=9001,
        order_type="dong",
        carrier_id=car_a.id,
        carrier_name=car_a.name,
        customer_id=cust.id,
        customer_name=cust.name,
        warehouse_id=wh.id,
        warehouse_name=wh.name,
        group_id=dest_grp.zalo_group_id,
        version=1,
    )
    lo2_plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 10),
        order_code=lo2_code,
        tms_order_id=9002,
        order_type="dong",
        carrier_id=car_a.id,
        carrier_name=car_a.name,
        customer_id=cust.id,
        customer_name=cust.name,
        warehouse_id=wh.id,
        warehouse_name=wh.name,
        group_id=dest_grp.zalo_group_id,
        version=1,
    )
    ro_plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 10),
        order_code=ro_code,
        tms_order_id=9003,
        order_type="tra",
        container_no=cont_ro,
        carrier_id=car_a.id,
        carrier_name=car_a.name,
        customer_id=cust.id,
        customer_name=cust.name,
        warehouse_id=wh.id,
        warehouse_name=wh.name,
        group_id=dest_grp.zalo_group_id,
        version=1,
    )
    db_session.add_all([lo_plan, lo2_plan, ro_plan])
    db_session.flush()
    return {
        "tok": tok,
        "car_a": car_a,
        "car_b": car_b,
        "veh_a": veh_a,
        "veh_b": veh_b,
        "drv_a": drv_a,
        "cust": cust,
        "wh": wh,
        "src_grp": src_grp,
        "dest_grp": dest_grp,
        "lo_plan": lo_plan,
        "lo2_plan": lo2_plan,
        "ro_plan": ro_plan,
    }


def _install_mock_tms(monkeypatch, handler):
    """Chặn mọi lời gọi HTTP ra TMS bằng `httpx.MockTransport` và bật cờ tích hợp."""
    monkeypatch.setattr(settings, "TMS_BASE_URL", "https://mock-tms.vsico.local/api")
    monkeypatch.setattr(settings, "TMS_ZALO_INTEGRATION_TOKEN", "secret_zalo_integration_token")
    monkeypatch.setattr(settings, "TMS_USERNAME", "admin_user")
    monkeypatch.setattr(settings, "TMS_PASSWORD", "admin_pass")
    monkeypatch.setattr(settings, "TMS_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "TMS_WRITE_ENABLED", True)
    monkeypatch.setattr(settings, "TMS_WRITE_ENDPOINT", "/api/integrations/zalo/dispatch-assignment")

    calls: list[dict] = []

    def _wrapped_client(*args, **kwargs):
        transport = httpx.MockTransport(
            lambda req: _record_and_dispatch(req, calls, handler)
        )
        kwargs["transport"] = transport
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    monkeypatch.setattr("src.infrastructure.tms_client.httpx.Client", _wrapped_client)
    return calls


def _record_and_dispatch(request: httpx.Request, calls: list[dict], handler):
    body = json.loads(request.content.decode("utf-8")) if request.content else {}
    calls.append(
        {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "json": body,
        }
    )
    return handler(request, body)


def _send_zalo(db_session, group: ZaloGroup, text: str, sender: str = "driver_1", quote: str | None = None):
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=uuid4().hex,
        group_id=group.zalo_group_id,
        sender_id=sender,
        quote_msg_id=quote,
        message_text=text,
        raw_payload={"is_test": True},
        created_at=REF_TIME,
        zalo_sent_at=REF_TIME,
    )
    db_session.add(msg)
    db_session.flush()
    handled = handle_assistant(db_session, msg, group)
    return msg, handled


# 1, 2, 13, 21: Chỉ có order_code + biển số xe; có vehicle_id hợp lệ; không ghi đè field khác.
def test_01_02_13_21_only_order_code_and_valid_vehicle_id(db_session, monkeypatch):
    env = _setup_fixture(db_session)
    calls = _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(200, json={"status": "ok", "updated": ["vehicle_id"]}),
    )
    lo = env["lo_plan"]
    lo.driver_name = "Tài Xế Cũ"
    lo.driver_phone = "0909999888"
    lo.container_no = _valid_cont("VSIU236054")
    db_session.flush()

    msg, handled = _send_zalo(db_session, env["src_grp"], f"{lo.order_code} xe 15H/00814")
    assert handled
    assert len(calls) == 1
    assert calls[0]["url"] == "https://mock-tms.vsico.local/api/integrations/zalo/dispatch-assignment"
    assert calls[0]["headers"]["authorization"] == "Bearer secret_zalo_integration_token"
    assert calls[0]["json"] == {
        "order_code": lo.order_code,
        "vehicle_id": env["veh_a"].tms_vehicle_id,
    }
    db_session.refresh(lo)
    assert lo.tms_sync_status == "SYNCED"
    assert lo.driver_name == "Tài Xế Cũ" and lo.driver_phone == "0909999888"


# 2 (plate normalization variants) & 3 (plate not in TMS -> vehicle_id: null + text)
@pytest.mark.parametrize("raw_plate", ["15H-00814", "15H 00814", "15H.00814", "15H/00814", "15H00814"])
def test_02_plate_variants_match_vehicle_id(db_session, raw_plate):
    env = _setup_fixture(db_session)
    payload, fields, err = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"planned_truck_plate": raw_plate},
    )
    assert err is None
    assert payload == {"order_code": env["lo_plan"].order_code, "vehicle_id": env["veh_a"].tms_vehicle_id}
    assert "planned_truck_plate" not in payload
    assert fields == ["vehicle_id"]


def test_03_unknown_vehicle_sends_null_id_and_plate_text(db_session, monkeypatch):
    env = _setup_fixture(db_session)
    calls = _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(200, json={"status": "ok"}),
    )
    msg, handled = _send_zalo(db_session, env["src_grp"], f"{env['lo_plan'].order_code} xe 15H-99881")
    assert handled
    assert len(calls) == 1
    assert calls[0]["json"] == {
        "order_code": env["lo_plan"].order_code,
        "vehicle_id": None,
        "planned_truck_plate": "15H-998.81",
    }
    assert env["lo_plan"].tms_sync_status == "SYNCED"


# 4: vehicle_id hoặc biển số thuộc nhà xe khác -> không dùng ID của nhà xe khác
def test_04_cross_carrier_vehicle_id_and_plate_rejected(db_session):
    env = _setup_fixture(db_session)
    payload_by_id, _, _ = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"planned_truck_plate": env["veh_b"].plate_no},
        requested_vehicle_id=env["veh_b"].tms_vehicle_id,
    )
    assert payload_by_id == {
        "order_code": env["lo_plan"].order_code,
        "vehicle_id": None,
        "planned_truck_plate": env["veh_b"].plate_no,
    }


# 5, 6, 7, 8, 9: Tài xế theo ID, SĐT (0 / +84 / 84), tên đơn, trùng tên không đoán ID
@pytest.mark.parametrize("phone_raw", ["0986123456", "+84986123456", "84986123456"])
def test_05_07_09_driver_phone_variants_resolve_driver_id(db_session, phone_raw):
    env = _setup_fixture(db_session)
    payload, _, err = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"driver_phone": phone_raw},
    )
    assert err is None
    assert payload == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": env["drv_a"].tms_driver_id,
    }


def test_06_unknown_driver_with_phone_and_name_sends_null_id(db_session):
    env = _setup_fixture(db_session)
    payload, _, err = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"driver_name": "Lê Văn Mới", "driver_phone": "+84977665544"},
    )
    assert err is None
    assert payload == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": None,
        "driver_phone": "0977665544",
        "driver_name": "Lê Văn Mới",
    }


def test_07_unknown_driver_phone_only(db_session):
    env = _setup_fixture(db_session)
    payload, _, err = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"driver_phone": "84977665544"},
    )
    assert err is None
    assert payload == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": None,
        "driver_phone": "0977665544",
    }


def test_08_driver_name_only_and_duplicate_name_does_not_guess_id(db_session):
    env = _setup_fixture(db_session)
    # Tên duy nhất -> lấy đúng driver_id
    p_unique, _, _ = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"driver_name": "Trần Văn Hùng"},
    )
    assert p_unique == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": env["drv_a"].tms_driver_id,
    }

    # Trùng nhiều tài xế tên 'Nguyễn Văn A' -> tuyệt đối không đoán driver_id
    p_dup, _, _ = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"driver_name": "Nguyễn Văn A"},
    )
    assert p_dup == {
        "order_code": env["lo_plan"].order_code,
        "driver_name": "Nguyễn Văn A",
    }


# 10, 11, 12: Xử lý container theo loại lệnh RO / LO
def test_10_ro_never_sends_container_no(db_session):
    env = _setup_fixture(db_session)
    ro = env["ro_plan"]
    payload, fields, err = build_dispatch_assignment_payload(
        db_session,
        ro,
        changed_fields={"planned_truck_plate": "15H-00814", "container_no": ro.container_no},
    )
    assert err is None
    assert "container_no" not in payload
    assert payload == {"order_code": ro.order_code, "vehicle_id": env["veh_a"].tms_vehicle_id}
    assert "container_no" not in fields


def test_11_lo_empty_allows_valid_container_and_rejects_bad_check_digit(db_session):
    env = _setup_fixture(db_session)
    lo = env["lo_plan"]
    valid_c = _valid_cont("VSIU236054")
    payload, _, err = build_dispatch_assignment_payload(
        db_session,
        lo,
        changed_fields={"container_no": valid_c},
    )
    assert err is None
    assert payload == {"order_code": lo.order_code, "container_no": valid_c}

    bad_c = valid_c[:-1] + str((int(valid_c[-1]) + 1) % 10)
    bad_payload, _, bad_err = build_dispatch_assignment_payload(
        db_session,
        lo,
        changed_fields={"container_no": bad_c},
    )
    assert bad_payload is None and bad_err.startswith("INVALID_CONTAINER_FORMAT:")


def test_12_lo_existing_container_cannot_be_silently_overwritten(db_session):
    env = _setup_fixture(db_session)
    lo = env["lo_plan"]
    c1 = _valid_cont("VSIU236054")
    c2 = _valid_cont("GAOU780650")
    lo.container_no = c1
    db_session.flush()

    blocked_payload, _, blocked_err = build_dispatch_assignment_payload(
        db_session,
        lo,
        changed_fields={"container_no": c2},
    )
    assert blocked_payload is None and blocked_err.startswith("CONTAINER_OVERRIDE_BLOCKED:")

    # Chỉ khi ĐHVT duyệt ghi đè tường minh mới cho phép gửi container mới
    approved_payload, _, approved_err = build_dispatch_assignment_payload(
        db_session,
        lo,
        changed_fields={"container_no": c2},
        allow_container_override=True,
    )
    assert approved_err is None
    assert approved_payload == {"order_code": lo.order_code, "container_no": c2}


# 14: Nhiều tin nhắn bổ sung dần thông tin qua bản nháp rồi xác nhận gọi TMS đúng một lần
def test_14_multi_turn_partial_accumulation_then_confirm(db_session, monkeypatch):
    env = _setup_fixture(db_session)
    calls = _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(200, json={"status": "ok"}),
    )
    lo = env["lo_plan"]
    cont = _valid_cont("VSIU236054")
    lo.container_no = cont
    lo.planned_truck_plate = "15C-111.11"
    db_session.flush()

    _send_zalo(db_session, env["src_grp"], f"Cont {cont} xe 15H-99881")
    assert len(calls) == 0
    _send_zalo(db_session, env["src_grp"], "Tài Lê Văn Mới")
    assert len(calls) == 0
    _send_zalo(db_session, env["src_grp"], "SĐT +84977665544")
    assert len(calls) == 0

    _send_zalo(db_session, env["src_grp"], "xác nhận")
    assert len(calls) == 1
    assert calls[0]["json"] == {
        "order_code": lo.order_code,
        "vehicle_id": None,
        "planned_truck_plate": "15H-998.81",
        "driver_id": None,
        "driver_phone": "0977665544",
        "driver_name": "Lê Văn Mới",
    }


# 15: Một tin có nhiều lệnh -> xử lý từng lệnh độc lập, không cập nhật nhầm
def test_15_multi_order_message_processed_independently(db_session, monkeypatch):
    env = _setup_fixture(db_session)
    calls = _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(200, json={"status": "ok"}),
    )
    lo1, lo2 = env["lo_plan"], env["lo2_plan"]
    text = f"{lo1.order_code} xe 15H-00814\n{lo2.order_code} tài Phạm Văn Bình sđt 0933444555"
    _send_zalo(db_session, env["src_grp"], text)

    assert len(calls) == 2
    by_order = {c["json"]["order_code"]: c["json"] for c in calls}
    assert by_order[lo1.order_code] == {
        "order_code": lo1.order_code,
        "vehicle_id": env["veh_a"].tms_vehicle_id,
    }
    assert by_order[lo2.order_code] == {
        "order_code": lo2.order_code,
        "driver_id": None,
        "driver_phone": "0933444555",
        "driver_name": "Phạm Văn Bình",
    }


# 16 & 17: Không xác định được order_code hoặc có 2 lệnh ứng viên -> không gọi API TMS
def test_16_17_missing_order_code_and_ambiguous_candidates_never_call_tms(db_session, monkeypatch):
    env = _setup_fixture(db_session)
    calls = _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(200, json={"status": "ok"}),
    )
    env["lo_plan"].order_code = None
    db_session.flush()
    assert (
        sync_plan_to_tms(db_session, env["lo_plan"], changed_fields={"planned_truck_plate": "15H-00814"})
        == "PENDING"
    )
    assert len(calls) == 0

    # Hai kế hoạch khác ngày trùng mã lệnh -> yêu cầu xác nhận rõ, không gọi API TMS
    dup_lo = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 11),
        order_code=env["lo2_plan"].order_code,
        order_type="dong",
        carrier_id=env["car_a"].id,
        group_id=env["dest_grp"].zalo_group_id,
        version=1,
    )
    db_session.add(dup_lo)
    db_session.flush()
    _send_zalo(db_session, env["src_grp"], f"{env['lo2_plan'].order_code} đổi sang xe 15H-00814")
    out = db_session.scalar(
        select(OutboundMessage)
        .where(OutboundMessage.target_group_id == env["src_grp"].id)
        .order_by(OutboundMessage.id.desc())
    )
    assert "nhiều chuyến" in out.content.lower()
    assert len(calls) == 0


# 18, 19, 20: Token sai (401), Validation lỗi (422), Timeout/mạng, Webhook trùng (Idempotency)
def test_18_19_20_auth_validation_timeout_and_idempotency(db_session, monkeypatch, api_client):
    env = _setup_fixture(db_session)
    lo = env["lo_plan"]

    # 401 token sai -> không tự gọi /login và không lộ token trong audit log
    _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(401, json={"message": "Unauthorized"}),
    )
    st_401 = sync_plan_to_tms(db_session, lo, changed_fields={"planned_truck_plate": "15H-00814"})
    assert st_401 == "FAILED" and lo.tms_sync_status == "FAILED"
    act_401 = db_session.scalar(
        select(ActivityLog)
        .where(ActivityLog.action == "TMS_DISPATCH_ASSIGNMENT_SYNC", ActivityLog.entity_id == str(lo.id))
        .order_by(ActivityLog.id.desc())
    )
    assert act_401.details["http_status"] == 401 and act_401.details["retryable"] is False
    assert "secret_zalo_integration_token" not in json.dumps(act_401.details)

    # 422 validation -> giữ FAILED, retryable=False
    _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(422, json={"message": "Invalid plate format"}),
    )
    st_422 = sync_plan_to_tms(db_session, lo, changed_fields={"planned_truck_plate": "15H-99881"})
    assert st_422 == "FAILED"

    # Timeout -> retryable=True, không retry mù quáng (>1 lần)
    def _timeout_handler(req, body):
        raise httpx.ReadTimeout("TMS read timeout")

    calls_timeout = _install_mock_tms(monkeypatch, _timeout_handler)
    st_to = sync_plan_to_tms(db_session, lo, changed_fields={"driver_phone": "0986123456"})
    assert st_to == "FAILED" and len(calls_timeout) == 1
    act_to = db_session.scalar(
        select(ActivityLog)
        .where(ActivityLog.action == "TMS_DISPATCH_ASSIGNMENT_SYNC", ActivityLog.entity_id == str(lo.id))
        .order_by(ActivityLog.id.desc())
    )
    assert act_to.details["retryable"] is True and act_to.details["status"] == "FAILED"

    # Webhook trùng + cùng idempotency_key chỉ gọi TMS 1 lần
    calls_ok = _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(200, json={"status": "ok"}),
    )
    lo.planned_truck_plate = None
    db_session.flush()
    webhook_body = {
        "msg_id": f"dup_{uuid4().hex}",
        "group_id": env["src_grp"].zalo_group_id,
        "sender_id": "driver_1",
        "message_text": f"{lo.order_code} xe 15H-00814",
        "is_test": True,
    }
    from src.infrastructure.fifo_queue import fifo_queue

    monkeypatch.setattr(fifo_queue, "enqueue", lambda mid: None)
    r1 = api_client.post("/webhook", json=webhook_body)
    r2 = api_client.post("/webhook", json=webhook_body)
    assert r1.status_code == 200 and r2.status_code == 200
    msg_row = db_session.scalar(select(ZaloMessage).where(ZaloMessage.zalo_message_id == webhook_body["msg_id"]))
    assert ExtractionHandler.process_message_by_id(db_session, msg_row.id) is not None
    # Lần thứ 2 đồng bộ lại cùng phiên bản & payload phải hit idempotency, không POST lặp
    assert sync_plan_to_tms(db_session, lo, changed_fields={"planned_truck_plate": "15H-00814"}) == "SYNCED"
    assert len(calls_ok) == 1
    # SĐT không lộ thô trong log
    sync_acts = list(
        db_session.scalars(
            select(ActivityLog).where(
                ActivityLog.action == "TMS_DISPATCH_ASSIGNMENT_SYNC",
                ActivityLog.entity_id == str(lo.id),
            )
        ).all()
    )
    assert all("0986123456" not in json.dumps(a.details) for a in sync_acts)


# 22: Workflow xác nhận/duyệt (MANUAL ReviewCase / 2-step draft) trước khi gọi TMS
def test_22_manual_approval_required_before_calling_tms(db_session, monkeypatch, api_client):
    env = _setup_fixture(db_session, send_mode="MANUAL")
    calls = _install_mock_tms(
        monkeypatch,
        lambda req, body: httpx.Response(200, json={"status": "ok"}),
    )
    dhvt = User(
        id=snowflake.generate(),
        username=f"dhvt_{env['tok']}",
        full_name=f"ĐHVT {env['tok']}",
        password_hash="x",
        role="DHVT",
        is_active=True,
    )
    db_session.add(dhvt)
    db_session.flush()
    dhvt_token = create_access_token({"sub": str(dhvt.id), "username": dhvt.username, "role": "DHVT"})

    lo = env["lo_plan"]
    cont = _valid_cont("VSIU236054")
    # Khi đang còn thiếu trường hoặc nhóm MANUAL -> chỉ tạo ReviewCase, chưa gọi TMS
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=uuid4().hex,
        group_id=env["src_grp"].zalo_group_id,
        sender_id="driver_1",
        message_text=f"Xe 15H-00814 tài Trần Văn Hùng 0986123456 đóng cont {cont} 40HC chì SL8899",
        raw_payload={"is_test": True},
        processing_status="QUEUED",
    )
    db_session.add(msg)
    db_session.flush()
    ExtractionHandler.process_message_by_id(db_session, msg.id)
    assert len(calls) == 0

    rc = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == msg.id))
    assert rc is not None
    resp = api_client.post(
        f"/api/reviews/{rc.id}/approve",
        json={"selected_plan_id": lo.id, "expected_version": lo.version},
        headers={"Authorization": f"Bearer {dhvt_token}"},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0]["json"]["order_code"] == lo.order_code
    assert calls[0]["json"]["vehicle_id"] == env["veh_a"].tms_vehicle_id
    assert calls[0]["json"]["driver_id"] == env["drv_a"].tms_driver_id
    assert calls[0]["json"]["container_no"] == cont
    db_session.refresh(lo)
    assert lo.tms_sync_status == "SYNCED"


def test_23_trailer_plate_includes_carrier_mooc_id_and_ro_mooc_no(db_session):
    """Payload đẩy TMS kèm `carrier_mooc_id` và `ro_mooc_no` chuẩn hóa khi kế hoạch có rơ-moóc."""
    from src.infrastructure.models import Trailer

    env = _setup_fixture(db_session)
    tr_a = Trailer(
        id=snowflake.generate(),
        tms_mooc_id=snowflake.generate(),
        tms_carrier_id=env["car_a"].tms_carrier_id,
        carrier_id=env["car_a"].id,
        license_plate="15R-181.29",
        normalized_plate="15R18129",
        mooc_type=2,
        is_active=True,
    )
    db_session.add(tr_a)
    db_session.flush()

    payload_matched, fields_matched, err_matched = build_dispatch_assignment_payload(
        db_session,
        env["ro_plan"],
        changed_fields={
            "planned_truck_plate": "15H-008.14",
            "planned_trailer_plate": "15R18129",
        },
    )
    assert err_matched is None
    assert payload_matched == {
        "order_code": env["ro_plan"].order_code,
        "vehicle_id": env["veh_a"].tms_vehicle_id,
        "carrier_mooc_id": tr_a.tms_mooc_id,
    }
    assert "ro_mooc_no" not in payload_matched
    assert "carrier_mooc_id" in fields_matched
    assert "ro_mooc_no" not in fields_matched

    payload_unknown, _, err_unknown = build_dispatch_assignment_payload(
        db_session,
        env["ro_plan"],
        changed_fields={"planned_trailer_plate": "15R99999"},
    )
    assert err_unknown is None
    assert payload_unknown == {
        "order_code": env["ro_plan"].order_code,
        "carrier_mooc_id": None,
        "ro_mooc_no": "15R-999.99",
    }

    # Khi SĐT khớp tài xế trong DB nhưng tên gửi kèm viết lệch ("Tịnh Văn Duân" vs "Trần Văn Hùng"),
    # hoặc tên khớp nhưng SĐT lạ -> chỉ gửi driver_id, không gửi driver_name/driver_phone
    payload_phone_match, _, err_pm = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"driver_name": "Tịnh Văn Duân", "driver_phone": "0986123456"},
    )
    assert err_pm is None
    assert payload_phone_match == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": env["drv_a"].tms_driver_id,
    }

    payload_name_match, _, err_nm = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={"driver_name": "Trần Văn Hùng", "driver_phone": "0977000111"},
    )
    assert err_nm is None
    assert payload_name_match == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": env["drv_a"].tms_driver_id,
    }


def test_24_multi_phone_extraction_validation_and_tms_payload(db_session):
    """Bắt đủ 2+ SĐT cho 1 tài xế dạng `'09..1 | 09..2'`, hợp lệ hóa và đẩy cả 2 số sang TMS."""
    from src.parsing.trip_parser import TripParser
    from src.validation.validators import ContainerValidator

    env = _setup_fixture(db_session)
    # 1. Nhà xe gửi 2 SĐT cho 1 tài xế + tiền tố dính biển số + tên dính phím
    msg = (
        "Xe29C49670 / 29R-30065 / phạmđứcvĩ / '0394251493/0984131254/ VSIU2461945\n"
        "Xe 29C49722 / 29RM-04802 / Bùi Văn Tuyên / 0375185207 - 0912345678 / VSIU2421290"
    )
    lines = ContainerValidator.validate_all(TripParser.parse_message(msg))
    assert len(lines) == 2
    assert lines[0].truck_plate == "29C-496.70"
    assert lines[0].trailer_plate == "29R-300.65"
    assert lines[0].driver_name == "Phạm Đức Vĩ"
    assert lines[0].driver_phone == "0394251493 | 0984131254"
    assert lines[0].validation_status == "VALID"

    assert lines[1].truck_plate == "29C-497.22"
    assert lines[1].trailer_plate == "29RM-048.02"
    assert lines[1].driver_phone == "0375185207 | 0912345678"
    assert lines[1].validation_status == "VALID"

    # 2. Đẩy TMS khi tài xế khớp DB theo 1 trong 2 SĐT -> vẫn gửi kèm đủ 2 SĐT `'09..1 | 09..2'`
    payload_multi_matched, _, err_mm = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={
            "driver_name": "Trần Văn Hùng",
            "driver_phone": "0986123456 | 0912345678",
        },
    )
    assert err_mm is None
    assert payload_multi_matched == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": env["drv_a"].tms_driver_id,
        "driver_phone": "0986123456 | 0912345678",
    }

    # 3. Đẩy TMS khi tài xế ngoài có 2 SĐT -> driver_id: None + driver_name + cả 2 SĐT
    payload_multi_ext, _, err_me = build_dispatch_assignment_payload(
        db_session,
        env["lo_plan"],
        changed_fields={
            "driver_name": "Lê Văn Ngoài",
            "driver_phone": "0394251493/0984131254",
        },
    )
    assert err_me is None
    assert payload_multi_ext == {
        "order_code": env["lo_plan"].order_code,
        "driver_id": None,
        "driver_phone": "0394251493 | 0984131254",
        "driver_name": "Lê Văn Ngoài",
    }
