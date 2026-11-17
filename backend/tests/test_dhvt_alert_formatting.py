"""Kiểm thử định dạng thông báo ĐHVT gửi nhóm Zalo: gọn gàng, tiếng Việt, không lộ ID."""

from datetime import date
from uuid import uuid4

from src.config.settings import settings
from src.handlers.dhvt_service import DhvtNotificationService
from src.infrastructure.models import (
    Carrier,
    ContainerJob,
    OutboundMessage,
    ReviewCase,
    TransportPlan,
    TruckRecord,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake


def test_render_review_case_alert_uses_human_names_and_clean_url(db_session, monkeypatch) -> None:
    """Form 1 hiển thị mã lệnh, khách, kho, nhà xe, xe/tài xế và link sạch không chứa Snowflake ID."""
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://bot.vtdat.com")

    carrier = Carrier(
        id=snowflake.generate(),
        name="VSICO Log",
        normalized_name="vsico log",
        code=f"CAR_{uuid4().hex[:6]}",
        is_active=True,
    )
    src_group = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_src_{uuid4().hex[:8]}",
        name="Nhóm Nhà Xe VSICO",
        group_role="SOURCE",
        send_mode="MANUAL",
        carrier_id=str(carrier.id),
        carrier_name="VSICO Log",
        is_active=True,
        is_test=True,
    )
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"zmsg_{uuid4().hex[:10]}",
        group_id=src_group.zalo_group_id,
        sender_id="driver_test_1",
        sender_name="Tài xế Test",
        message_text="RO2864 xe 29C-446.62 tài Phạm Đức Vĩ",
        raw_payload={"text": "RO2864 xe 29C-446.62 tài Phạm Đức Vĩ"},
        processing_status="NEEDS_REVIEW",
    )
    plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 17),
        order_type="tra",
        order_code="RO2864",
        container_no="TGCU5312741",
        customer_name="KIOWAY",
        warehouse_name="KHO HATECO LONG BIÊN HÀ NỘI",
        carrier_id=carrier.id,
        carrier_name="VSICO Log",
        planned_truck_plate="29C-446.62",
        driver_name="Phạm Đức Vĩ",
    )
    truck = TruckRecord(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_plate="29C-446.62",
        driver_name="Phạm Đức Vĩ",
    )
    job = ContainerJob(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_record_id=truck.id,
        container_no="TGCU5312741",
        order_type="tra",
    )
    db_session.add_all([carrier, src_group, msg, plan, truck, job])
    db_session.flush()

    rc = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        container_job_id=job.id,
        case_type="OUTBOUND_PENDING_APPROVAL",
        reason="Tuyến yêu cầu ĐHVT duyệt gửi trên Web.",
        details={"transport_plan_id": str(plan.id), "container_no": "TGCU5312741"},
        status="PENDING",
    )
    db_session.add(rc)
    db_session.flush()

    rendered = DhvtNotificationService.render_review_case_alert(
        case_obj=rc,
        db=db_session,
        container_no="TGCU5312741",
        priority="NORMAL",
    )

    assert str(rc.id) not in rendered
    assert str(plan.id) not in rendered
    assert "?highlight=" not in rendered
    assert "#" not in rendered
    assert "Duyệt gửi thông báo khách hàng" in rendered
    assert "RO2864 (Trả hàng)" in rendered
    assert "TGCU5312741" in rendered
    assert "KIOWAY" in rendered
    assert "KHO HATECO LONG BIÊN HÀ NỘI" in rendered
    assert "VSICO Log" in rendered
    assert "29C-446.62 - Phạm Đức Vĩ" in rendered
    assert "https://bot.vtdat.com/reviews" in rendered


def test_render_pending_outbound_alert_has_no_id_and_clean_url(monkeypatch) -> None:
    """Form 2 giữ tiêu đề chuẩn cho kiểm thử cũ nhưng bỏ Snowflake ID và dùng URL sạch."""
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://bot.vtdat.com")
    outbound = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=123456789012345678,
        order_type="dong",
        message_kind="initial",
        content="Test content",
        idempotency_key=f"idem_{uuid4().hex[:8]}",
        status="PENDING_APPROVAL",
    )

    rendered = DhvtNotificationService.render_pending_outbound_alert(
        outbound=outbound,
        target_group_name="TMS Khách hàng - TEST",
        containers=["TGCU5312741"],
        reason="Tuyến MANUAL cần duyệt trước khi phát hành.",
    )

    assert "[VSICO - TIN CHO DUYET]" in rendered
    assert str(outbound.id) not in rendered
    assert "?highlight=" not in rendered
    assert "TMS Khách hàng - TEST" in rendered
    assert "Đóng hàng" in rendered
    assert "https://bot.vtdat.com/results" in rendered


def test_verify_plan_and_carrier_handles_lo_empty_slots_and_shared_container(db_session) -> None:
    """Kiểm tra khớp lệnh đóng rỗng cont, tách RO/LO trùng cont và trả candidate_plans khi có nhiều LO giống nhau."""
    from src.domain.models import ExtractedContainerLine
    from src.handlers.carrier_flow_service import CarrierContext, CarrierFlowService
    from src.infrastructure.models import Customer

    cust_nbc = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 100_000_000),
        name=f"NBC TEST {uuid4().hex[:4]}",
        normalized_name=f"nbc test {uuid4().hex[:4]}",
        is_active=True,
    )
    cust_diana = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 100_000_000),
        name=f"DIANA TEST {uuid4().hex[:4]}",
        normalized_name=f"diana test {uuid4().hex[:4]}",
        is_active=True,
    )
    db_session.add_all([cust_nbc, cust_diana])
    db_session.flush()

    lo_unique = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 30),
        order_type="dong",
        order_code="LO9901",
        container_no=None,
        customer_id=cust_nbc.id,
        customer_name=cust_nbc.name,
        warehouse_name="KHO NBC PHỐ NỐI A",
    )
    lo_dup_1 = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 30),
        order_type="dong",
        order_code="LO9902",
        container_no=None,
        customer_id=cust_diana.id,
        customer_name=cust_diana.name,
        warehouse_name="KHO DIANA TÂN CHI",
    )
    lo_dup_2 = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 30),
        order_type="dong",
        order_code="LO9903",
        container_no=None,
        customer_id=cust_diana.id,
        customer_name=cust_diana.name,
        warehouse_name="KHO DIANA TÂN CHI",
    )
    shared_cont = f"ZZZU{uuid4().int % 9_000_000 + 1_000_000}"
    shared_ro = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 30),
        order_type="tra",
        order_code="RO9904",
        container_no=shared_cont,
        customer_id=cust_nbc.id,
        customer_name=cust_nbc.name,
    )
    shared_lo = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 30),
        order_type="dong",
        order_code="LO9905",
        container_no=shared_cont,
        customer_id=cust_nbc.id,
        customer_name=cust_nbc.name,
    )
    db_session.add_all([lo_unique, lo_dup_1, lo_dup_2, shared_ro, shared_lo])
    db_session.flush()

    shared_ctx = CarrierContext(source_group=None, numeric_carrier_id=None, is_unregistered_group=False, is_test_msg=True)

    # 1. Lệnh đóng đơn rỗng cont khớp theo khách trên nhóm dùng chung -> tự khớp đúng LO9901
    line_unique = ExtractedContainerLine(
        line_no=1,
        line_text="Xe 29C46732 đóng hàng VSIU2469993",
        container_no="VSIU2469993",
        order_type="dong",
        warehouse_hint="Kho NBC Phố Nối A",
    )
    res_unique = CarrierFlowService.verify_plan_and_carrier(db_session, line_unique, shared_ctx, cust_nbc.id)
    assert res_unique.matched_plan is not None
    assert res_unique.matched_plan.id == lo_unique.id

    # 2. Nhiều lệnh đóng rỗng giống nhau (DIANA) -> trả candidate_plans để Web ĐHVT chọn
    line_multi = ExtractedContainerLine(
        line_no=1,
        line_text="Xe 29C46732 đóng hàng VSIU2469993",
        container_no="VSIU2469993",
        order_type="dong",
        warehouse_hint="Kho Diana Tân Chi",
    )
    res_multi = CarrierFlowService.verify_plan_and_carrier(db_session, line_multi, shared_ctx, cust_diana.id)
    assert res_multi.is_shipping_missing is True
    cand_ids = {p.id for p in res_multi.candidate_plans}
    assert {lo_dup_1.id, lo_dup_2.id}.issubset(cand_ids)

    # 3. Trùng container giữa RO và LO kết hợp -> order_type='dong' chọn đúng LO9905
    line_comb = ExtractedContainerLine(
        line_no=1,
        line_text=f"Xe 29C46732 đóng cont {shared_cont}",
        container_no=shared_cont,
        order_type="dong",
    )
    res_comb = CarrierFlowService.verify_plan_and_carrier(db_session, line_comb, shared_ctx, None)
    assert res_comb.matched_plan is not None
    assert res_comb.matched_plan.id == shared_lo.id


def test_trailer_catalog_lookup_reclassify_and_plan_resolution(db_session) -> None:
    """Tận dụng bảng `trailers` để tra cứu mooc_id, chuẩn hóa biển và phân biệt mooc không mang chữ R."""
    from sqlalchemy import select
    from src.assistant.queries import plans_statement
    from src.assistant.schemas import Entities, ScopeContext
    from src.domain.models import ExtractedContainerLine
    from src.handlers.plan_sync_service import resolve_trailer_for_plan, resolve_trailer_from_catalog
    from src.infrastructure.models import Trailer

    carrier = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=int(snowflake.generate() % 100_000_000),
        name=f"CARRIER MOOC {uuid4().hex[:4]}",
        normalized_name=f"carrier mooc {uuid4().hex[:4]}",
        is_active=True,
    )
    db_session.add(carrier)
    db_session.flush()

    tr_non_r = Trailer(
        id=snowflake.generate(),
        tms_mooc_id=int(snowflake.generate() % 100_000_000),
        tms_carrier_id=carrier.tms_carrier_id,
        carrier_id=carrier.id,
        license_plate="29C-09999",
        normalized_plate="29C09999",
        mooc_type=2,
        is_active=True,
    )
    tr_r = Trailer(
        id=snowflake.generate(),
        tms_mooc_id=int(snowflake.generate() % 100_000_000),
        tms_carrier_id=carrier.tms_carrier_id,
        carrier_id=carrier.id,
        license_plate="29R-007-87",
        normalized_plate="29R00787",
        mooc_type=2,
        is_active=True,
    )
    plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 30),
        order_type="tra",
        order_code="RO9988",
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        planned_truck_plate="15C-066.95",
        planned_trailer_plate="29R-007.87",
    )
    db_session.add_all([tr_non_r, tr_r, plan])
    db_session.flush()

    # 1. Biển mooc không có R bị parser xếp nhầm vào truck_plate -> tự chuyển sang trailer_plate
    line_mis = ExtractedContainerLine(
        line_no=1,
        truck_plate="29C-099.99",
    )
    assert resolve_trailer_from_catalog(db_session, line_mis, carrier.id) is True
    assert line_mis.truck_plate is None
    assert line_mis.trailer_plate == "29C-099.99"

    # 2. Tra cứu mooc_id từ bảng trailers giống resolve_vehicle_for_plan
    res_tr = resolve_trailer_for_plan(db_session, plan, trailer_plate="29R00787")
    assert res_tr["mooc_id"] == tr_r.tms_mooc_id
    assert res_tr["planned_trailer_plate"] == "29R-007.87"
    assert res_tr["resolution"] == "matched_by_plate"

    # 3. Trợ lý ảo tra cứu theo biển số rơ-moóc khớp vào TransportPlan.planned_trailer_plate
    from datetime import datetime
    scope = ScopeContext(
        role="CARRIER",
        group_id=1,
        zalo_group_id="g",
        sender_id="u",
        carrier_id=carrier.id,
        reference_time=datetime(2099, 12, 30, 8, 0),
    )
    found = list(
        db_session.scalars(
            plans_statement(scope, Entities(plan_date=date(2099, 12, 30), plate_no="29R00787"))
        ).all()
    )
    assert any(p.id == plan.id for p in found)
