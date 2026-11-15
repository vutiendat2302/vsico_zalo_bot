"""Kiểm thử cập nhật kế hoạch nội bộ và giới hạn nhà xe."""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from src.api.plans import update_plan_vehicle
from src.api.schemas import PlanVehicleUpdate
from src.handlers.carrier_flow_service import CarrierFlowService
from src.infrastructure.models import TransportPlan
from src.infrastructure.snowflake import snowflake


def test_vehicle_patch_version_and_pending(db_session):
    """Cập nhật thật trong savepoint, không báo TMS đã đồng bộ và chặn phiên bản cũ."""
    plan = TransportPlan(id=snowflake.generate(), plan_date=date.today(), order_type="LOAD",
                         customer_name="test_" + uuid4().hex, version=1)
    db_session.add(plan)
    db_session.flush()
    user = SimpleNamespace(id=1, role="DHVT")
    result = update_plan_vehicle(plan.id, PlanVehicleUpdate(expected_version=1,
                                driver_name="Tài xế kiểm thử", driver_phone="0901234567"), db_session, user)
    assert result.version == 2
    assert result.tms_sync_status == "PENDING"
    assert result.driver_phone == "0901234567"
    with pytest.raises(HTTPException) as exc:
        update_plan_vehicle(plan.id, PlanVehicleUpdate(expected_version=1, driver_name="Khác"), db_session, user)
    assert exc.value.status_code == 409


def test_ai_context_without_carrier_is_empty(db_session):
    """Thiếu định danh nhà xe không được lấy kế hoạch toàn hệ thống cho AI."""
    assert CarrierFlowService.load_active_plans_for_ai(db_session, "báo xe mới") == []


def test_vehicle_schema_rejects_trailer():
    """Hợp đồng cập nhật kế hoạch không nhận trường rơ-moóc."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PlanVehicleUpdate(expected_version=1, trailer_plate="x")


def test_outbox_updates_plan_without_fake_sent(db_session, monkeypatch):
    """Tắt phát hành vẫn lưu kế hoạch một lần, không tự sinh ID Zalo hay SYNCED."""
    from contextlib import nullcontext
    from src.config.settings import settings
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.outbox_worker import drain_outbox
    from src.infrastructure.models import OutboundMessage, ZaloMessage
    from sqlalchemy import select
    from test_carrier_flow_e2e import _setup_carrier_customer_env, _valid_cont
    env = _setup_carrier_customer_env(db_session, cont_no=_valid_cont())
    msg = ZaloMessage(id=snowflake.generate(), zalo_message_id="test_" + uuid4().hex,
                      group_id=env["src_grp"].zalo_group_id, sender_id="test_driver",
                      message_text=f"Xe 50H-049.15 tài xế Trần Bình 0912345678 đóng cont {_valid_cont()} 40HC seal ABC123 hẹn 09:30",
                      raw_payload={}, processing_status="QUEUED")
    db_session.add(msg)
    db_session.flush()
    ExtractionHandler.process_message_by_id(db_session, msg.id)
    out = db_session.scalar(select(OutboundMessage).where(OutboundMessage.target_group_id == env["dest_grp"].id))
    assert out is not None and out.status == "PENDING_SEND"
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", False)
    drain_outbox(lambda: nullcontext(db_session), [out.id])
    plan = env["plan"]
    db_session.refresh(plan)
    assert plan.driver_phone == "0912345678"
    assert plan.version == 2 and plan.tms_sync_status == "PENDING"
    assert out.status == "PENDING_SEND" and out.zalo_message_id is None
    drain_outbox(lambda: nullcontext(db_session), [out.id])
    db_session.refresh(plan)
    assert plan.version == 2
