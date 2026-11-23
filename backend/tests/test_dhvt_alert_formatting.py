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

    from src.domain.short_link import decode_short_token, encode_short_token

    expected_token = encode_short_token("r", rc.id, settings.short_link_secret)
    assert str(rc.id) not in rendered
    assert str(plan.id) not in rendered
    assert "reviewId" not in rendered
    assert "/reviews" not in rendered
    assert "?highlight=" not in rendered
    assert "#" not in rendered
    assert "Duyệt gửi thông báo khách hàng" in rendered
    assert "RO2864 (Trả hàng)" in rendered
    assert "TGCU5312741" in rendered
    assert "KIOWAY" in rendered
    assert "KHO HATECO LONG BIÊN HÀ NỘI" in rendered
    assert "VSICO Log" in rendered
    assert "29C-446.62 - Phạm Đức Vĩ" in rendered
    assert f"https://bot.vtdat.com/{expected_token}" in rendered
    assert decode_short_token(expected_token, settings.short_link_secret) == ("r", rc.id)


def test_render_pending_outbound_alert_has_no_id_and_clean_url(monkeypatch) -> None:
    """Form 2 hiển thị tiếng Việt gọn gàng, không lộ ID/tham số hệ thống và tạo link rút gọn chính xác."""
    from src.domain.short_link import decode_short_token, encode_short_token

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

    rc_id = 987654321098765432
    rendered = DhvtNotificationService.render_pending_outbound_alert(
        outbound=outbound,
        target_group_name="TMS Khách hàng - TEST",
        containers=["TGCU5312741"],
        reason="Tuyến MANUAL cần duyệt trước khi phát hành.",
        review_case_id=rc_id,
    )

    tok_rc = encode_short_token("r", rc_id, settings.short_link_secret)
    assert "[VSICO] - ⚠️ Tin gửi khách hàng đang chờ duyệt" in rendered
    assert str(outbound.id) not in rendered
    assert str(rc_id) not in rendered
    assert "reviewId" not in rendered
    assert "/reviews" not in rendered
    assert "?highlight=" not in rendered
    assert "TMS Khách hàng - TEST" in rendered
    assert "Đóng hàng" in rendered
    assert f"https://bot.vtdat.com/{tok_rc}" in rendered
    assert decode_short_token(tok_rc, settings.short_link_secret) == ("r", rc_id)

    rendered_fallback = DhvtNotificationService.render_pending_outbound_alert(
        outbound=outbound,
        target_group_name="TMS Khách hàng - TEST",
        containers=["TGCU5312741"],
        reason="Tuyến MANUAL cần duyệt trước khi phát hành.",
    )
    tok_out = encode_short_token("o", outbound.id, settings.short_link_secret)
    assert str(outbound.id) not in rendered_fallback
    assert "outboundId" not in rendered_fallback
    assert f"https://bot.vtdat.com/{tok_out}" in rendered_fallback
    assert decode_short_token(tok_out, settings.short_link_secret) == ("o", outbound.id)


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

    # 2. Tra cứu mooc_id từ bảng trailers giống resolve_vehicle_for_plan (khớp DB chỉ trả mooc_id)
    res_tr = resolve_trailer_for_plan(db_session, plan, trailer_plate="29R00787")
    assert res_tr["mooc_id"] == tr_r.tms_mooc_id
    assert "planned_trailer_plate" not in res_tr
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


def test_vertical_message_and_short_plate_phone_validation() -> None:
    """Kiểm tra tin nhắn dạng dọc 1 chuyến không bị tách đôi, đọc đủ lái xe + xe + mooc, và bắt lỗi thiếu số."""
    from src.outbound.templates import OutboundTemplateBuilder
    from src.parsing.trip_parser import TripParser
    from src.validation.validators import ContainerValidator

    # 1. Tin nhắn dạng dọc đủ 5 số cho xe và moóc -> 1 dòng duy nhất, đủ biển số, rơ-moóc, tên lái xe, SĐT, cont
    vertical_valid = "Xe 29C44541  \n29R-30187 \nNguyễn Văn Hải\n0983092922 \nVSIU2321516"
    lines_valid = ContainerValidator.validate_all(TripParser.parse_message(vertical_valid))
    assert len(lines_valid) == 1
    ln_ok = lines_valid[0]
    assert ln_ok.truck_plate == "29C-445.41"
    assert ln_ok.trailer_plate == "29R-301.87"
    assert ln_ok.driver_name == "Nguyễn Văn Hải"
    assert ln_ok.driver_phone == "0983092922"
    assert ln_ok.container_no == "VSIU2321516"
    assert ln_ok.validation_status == "VALID"

    # 2. Tin nhắn dạng dọc có biển số xe thiếu 1 số (29C4471) -> vẫn đọc đủ thực thể trên 1 dòng nhưng đánh dấu INVALID
    vertical_short_plate = "Xe 29C4471\n29RM-04802 \nTịnh Văn Duân\n0987369401\nSELU4508161"
    lines_short = ContainerValidator.validate_all(TripParser.parse_message(vertical_short_plate))
    assert len(lines_short) == 1
    ln_sp = lines_short[0]
    assert ln_sp.truck_plate == "29C-4471"
    assert ln_sp.trailer_plate == "29RM-048.02"
    assert ln_sp.driver_name == "Tịnh Văn Duân"
    assert ln_sp.driver_phone == "0987369401"
    assert ln_sp.container_no == "SELU4508161"
    assert "INVALID_TRUCK_PLATE_FORMAT" in ln_sp.warnings
    assert ln_sp.validation_status == "INVALID"

    # 3. Tin nhắn thiếu 1 số ở cả xe (29C4471), rơ-moóc (29RM-0480) và SĐT (098736941) -> bắt đủ cả 3 lỗi
    short_all = "Xe 29C4471/  29RM-0480 /  Tịnh Văn Duân /098736941/ \nSELU4202340"
    lines_all = ContainerValidator.validate_all(TripParser.parse_message(short_all))
    assert len(lines_all) == 1
    ln_bad = lines_all[0]
    ln_bad.customer_hint = "CHENG LOONG"
    ln_bad.warehouse_hint = "KHO QUANG CHÂU"
    ln_bad.order_type = "RETURN"
    ln_bad.seal_no = "22807515"
    assert "INVALID_TRUCK_PLATE_FORMAT" in ln_bad.warnings
    assert "INVALID_TRAILER_PLATE_FORMAT" in ln_bad.warnings
    assert "INVALID_DRIVER_PHONE" in ln_bad.warnings
    is_complete, missing = OutboundTemplateBuilder.check_core_fields_completeness(ln_bad)
    assert is_complete is False
    assert "Biển số xe (phải đủ 5 chữ số)" in missing
    assert "Biển số rơ-moóc (phải đủ 5 chữ số)" in missing
    assert "SĐT tài xế (phải đúng 10 số bắt đầu bằng 0)" in missing


def test_expected_time_enriched_from_transport_plan_in_db(db_session) -> None:
    """Khi tin nhắn nhà xe không ghi giờ đến nhưng kế hoạch trong DB đã có required_time, tự động lấy giờ dự kiến từ kế hoạch."""
    from src.domain.models import ExtractedContainerLine
    from src.handlers.extraction_handler import ExtractionHandler
    from src.outbound.templates import OutboundTemplateBuilder

    cont_no = "VSIU2321516"
    plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2099, 12, 31),
        order_type="tra",
        order_code="RO8899",
        container_no=cont_no,
        container_size="40",
        seal_no="23998877",
        required_time="08:30",
        customer_name="LOGITEM",
        warehouse_name="KHO TÂN QUANG HƯNG YÊN",
        delivery_address="KCN Như Quỳnh, Văn Lâm, Hưng Yên",
        planned_trailer_plate="29R-301.87",
    )
    db_session.add(plan)
    db_session.flush()

    line = ExtractedContainerLine(
        line_no=1,
        line_text="Xe 29C44541\n29R-30187\nNguyễn Văn Hải\n0983092922\nVSIU2321516",
        truck_plate="29C-445.41",
        trailer_plate="29R-301.87",
        driver_name="Nguyễn Văn Hải",
        driver_phone="0983092922",
        container_no=cont_no,
    )
    ExtractionHandler._enrich_from_catalog_and_plans(db_session, line)

    assert line.eta_time == "08:30"
    assert line.eta_text == "08:30"
    assert line.field_evidences.get("eta_time") == "transport_plan"

    notif = OutboundTemplateBuilder.build_customer_notification(
        line=line,
        customer_name=line.customer_hint,
        warehouse_name=line.warehouse_hint,
    )
    assert "Giờ đến dự kiến: 08:30" in notif
    assert "Giờ đến dự kiến: Chưa có" not in notif


def test_carrier_dispatch_with_chi_chua_co_is_never_routed_as_question() -> None:
    """Tin báo điều xe có cụm 'Chì chưa có' (hoặc tên lái xe có từ khóa hỏi) phải phân loại là REPORT_DISPATCH, không bị nhầm là câu hỏi tra cứu lịch xe."""
    from datetime import datetime
    from src.assistant.intent_router import route_local
    from src.parsing.trip_parser import TripParser

    msg = "Xe 29C-44722/ MOOC 29R-006-45 / lái xe Vũ Văn Công / SĐT: 0338.971.972/  Cont GAOU7798737 / Chì chưa có"
    call = route_local(msg, "CARRIER", datetime(2026, 11, 20, 8, 30, 32))
    assert call.intent == "REPORT_DISPATCH"

    parsed = TripParser.parse_message(msg, reference_time=datetime(2026, 11, 20, 8, 30, 32))
    assert len(parsed) == 1
    ln = parsed[0]
    assert ln.truck_plate == "29C-447.22"
    assert ln.trailer_plate == "29R-006.45"
    assert ln.driver_name == "Vũ Văn Công"
    assert ln.driver_phone == "0338971972"
    assert ln.container_no == "GAOU7798737"
    assert ln.seal_no is None
    assert ln.is_seal_pending is True
    assert ln.seal_status == "DEFERRED"

    # Kể cả khi tên tài xế có chữ 'Lịch' hoặc 'Xem' hoặc có cụm 'Thông tin xe', vẫn phải là REPORT_DISPATCH
    msg_driver_lich = "Thông tin xe: 29C-44722 / lái xe Nguyễn Văn Lịch / 0338971972 / Cont GAOU7798737 / seal chưa có"
    call_lich = route_local(msg_driver_lich, "CARRIER", datetime(2026, 11, 20, 8, 30, 32))
    assert call_lich.intent == "REPORT_DISPATCH"


def _setup_booking_context_db(db_session):
    """Khởi tạo dữ liệu trong db_session mô phỏng đúng bối cảnh BK2026110002 và lệnh RO2711."""
    from datetime import date
    from uuid import uuid4
    from sqlalchemy import select
    from src.infrastructure.models import BotReply, Carrier, Customer, RouteMap, TransportPlan, ZaloGroup
    from src.domain.enums import GroupRole, SendMode

    db = db_session
    uid = uuid4().hex[:6]

    cust_trieu = db.scalar(
        select(Customer).where(Customer.normalized_name == "trieu thuan nguyen", Customer.is_active.is_(True))
    )
    if cust_trieu is None:
        cust_trieu = Customer(
            id=snowflake.generate(),
            tms_customer_id=f"TMS_TTN_{uid}",
            name="Công ty TNHH TM Triều Thuận Nguyên",
            normalized_name="trieu thuan nguyen",
            is_active=True,
        )
        db.add(cust_trieu)

    cust_scan = db.scalar(
        select(Customer).where(Customer.normalized_name == "scan logistics", Customer.is_active.is_(True))
    )
    if cust_scan is None:
        cust_scan = Customer(
            id=snowflake.generate(),
            tms_customer_id=f"TMS_SCAN_{uid}",
            name="SCAN LOGISTICS",
            normalized_name="scan logistics",
            is_active=True,
        )
        db.add(cust_scan)

    carrier = Carrier(
        id=snowflake.generate(),
        code=f"NXTEST_{uid}",
        name=f"TMS Nhà xe TEST {uid}",
        normalized_name=f"tms nha xe test {uid}",
        is_active=True,
    )
    db.add(carrier)
    db.flush()

    grp_src = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_src_bk_{uid}",
        name=f"TMS Nhà xe TEST {uid}",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(carrier.id),
        carrier_name=carrier.name,
        send_mode=SendMode.MANUAL.value,
        is_active=True,
        is_test=True,
    )
    grp_tgt = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_tgt_bk_{uid}",
        name=f"TMS Khách hàng TEST {uid}",
        group_role=GroupRole.DESTINATION.value,
        send_mode=SendMode.MANUAL.value,
        is_active=True,
        is_test=True,
    )
    db.add_all([grp_src, grp_tgt])
    db.flush()
    db.add(
        RouteMap(
            id=snowflake.generate(),
            customer_id=cust_trieu.id,
            zalo_group_id=grp_tgt.id,
            priority=10,
            is_active=True,
        )
    )
    # RO2711 là lệnh TRẢ của SCAN LOGISTICS nhưng trùng số cont GAOU7821230
    plan_ro = TransportPlan(
        id=snowflake.generate(),
        order_code=f"RO2711_{uid}",
        order_type="tra",
        plan_date=date(2026, 11, 20),
        customer_id=cust_scan.id,
        customer_name="SCAN LOGISTICS",
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        container_no="GAOU7821230",
        seal_no="010414",
        version=1,
    )
    # LO2572/LO2573 là lệnh ĐÓNG của Triều Thuận Nguyên theo BK2026110002 (chưa có số cont)
    plan_lo1 = TransportPlan(
        id=snowflake.generate(),
        order_code=f"LO2572_{uid}",
        order_type="dong",
        plan_date=date(2026, 11, 20),
        customer_id=cust_trieu.id,
        customer_name="Công ty TNHH TM Triều Thuận Nguyên",
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        booking_no="BK2026110002",
        container_no=None,
        version=1,
    )
    plan_lo2 = TransportPlan(
        id=snowflake.generate(),
        order_code=f"LO2573_{uid}",
        order_type="dong",
        plan_date=date(2026, 11, 20),
        customer_id=cust_trieu.id,
        customer_name="Công ty TNHH TM Triều Thuận Nguyên",
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        booking_no="BK2026110002",
        container_no=None,
        version=1,
    )
    db.add_all([plan_ro, plan_lo1, plan_lo2])
    db.commit()
    return db, grp_src, cust_trieu


def test_booking_no_not_phone_and_unquoted_supplement_merges_single_job(db_session, monkeypatch):
    """Kiểm tra BK2026110002 không bị nhận nhầm SĐT/RO2711 và tin bổ sung nối đúng 1 đơn."""
    from datetime import UTC, datetime
    from uuid import uuid4
    from sqlalchemy import select
    from src.assistant.service import handle_assistant
    from src.domain.enums import CorrectionStatus, MessageStatus
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import BotReply, ContainerJob, ZaloMessage

    db, grp_src, cust_trieu = _setup_booking_context_db(db_session)
    uid = uuid4().hex[:6]
    monkeypatch.setattr(
        "src.handlers.carrier_flow_service.ZaloDispatcher.send_to_group",
        lambda **kwargs: (True, f"bot_{kwargs.get('quote_msg_id', 'x')}", None),
    )

    msg1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"zalo_msg_1_{uid}",
        group_id=grp_src.zalo_group_id,
        sender_id=f"driver_dat_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text="Đóng Triều Thuận Nguyên BK2026110002 xe 15H-012.34 tài xế Nam cont GAOU7821230",
        raw_payload={"text": "Đóng Triều Thuận Nguyên BK2026110002 xe 15H-012.34 tài xế Nam cont GAOU7821230"},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db.add(msg1)
    db.commit()

    assert handle_assistant(db, msg1, grp_src) is False
    ExtractionHandler.process_message_by_id(db, msg1.id)

    jobs_after_1 = db.scalars(select(ContainerJob).where(ContainerJob.message_id == msg1.id)).all()
    assert len(jobs_after_1) == 1
    job = jobs_after_1[0]
    assert job.truck_record is not None
    assert job.truck_record.driver_phone is None  # Không nhận nhầm 026110002 từ BK2026110002
    assert job.seal_no is None  # Không ghép nhầm RO2711 của SCAN LOGISTICS
    assert job.customer_id == cust_trieu.id
    assert (job.raw_fields or {}).get("booking_no") == "BK2026110002"

    pending_replies = db.scalars(
        select(BotReply).where(BotReply.message_id == msg1.id, BotReply.status == CorrectionStatus.PENDING.value)
    ).all()
    assert len(pending_replies) == 1
    assert "rơ-moóc" in pending_replies[0].reply_text.lower()

    # Tin 2: bổ sung ngắn KHÔNG quote và KHÔNG có từ "bổ sung" (kèm mooc để đủ bộ trường bắt buộc)
    msg2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"zalo_msg_2_{uid}",
        group_id=grp_src.zalo_group_id,
        sender_id=msg1.sender_id,
        sender_name="Vũ Tiến Đạt",
        message_text="0912888777 chì VS998877 mooc 29R-006.45",
        raw_payload={"text": "0912888777 chì VS998877 mooc 29R-006.45"},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db.add(msg2)
    db.commit()

    assert handle_assistant(db, msg2, grp_src) is False
    ExtractionHandler.process_message_by_id(db, msg2.id)
    db.refresh(msg2)
    assert msg2.processing_status != MessageStatus.IGNORED_CHAT.value

    jobs_after_2 = db.scalars(select(ContainerJob).where(ContainerJob.message_id.in_([msg1.id, msg2.id]))).all()
    assert len(jobs_after_2) == 1
    db.refresh(job)
    assert job.truck_record is not None
    assert job.truck_record.truck_plate == "15H-012.34"
    assert job.truck_record.trailer_plate == "29R-006.45"
    assert job.truck_record.driver_name == "Nam"
    assert job.truck_record.driver_phone == "0912888777"
    assert job.seal_no == "VS998877"

    db.refresh(pending_replies[0])
    assert pending_replies[0].status == CorrectionStatus.RESOLVED.value


def test_supplement_with_bo_sung_phrase_routes_to_pending_job_without_duplicate(db_session, monkeypatch):
    """Tin 'Bổ sung sđt ... chì ...' (không quote hoặc quote tin gốc) phải gộp vào đơn cũ, không tạo đơn thứ 2."""
    from datetime import UTC, datetime
    from uuid import uuid4
    from sqlalchemy import select
    from src.assistant.service import handle_assistant
    from src.domain.enums import MessageStatus
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import BotReply, ContainerJob, ZaloMessage

    monkeypatch.setattr(
        "src.handlers.carrier_flow_service.ZaloDispatcher.send_to_group",
        lambda **kwargs: (True, f"bot_{kwargs.get('quote_msg_id', 'x')}", None),
    )
    db, grp_src, _ = _setup_booking_context_db(db_session)

    for idx, use_quote in enumerate((False, True), start=1):
        uid = uuid4().hex[:6]
        sender = f"driver_dat_{idx}_{uid}"
        msg1 = ZaloMessage(
            id=snowflake.generate(),
            zalo_message_id=f"zalo_msg_1_{idx}_{uid}",
            group_id=grp_src.zalo_group_id,
            sender_id=sender,
            sender_name="Vũ Tiến Đạt",
            message_text="Đóng Triều Thuận Nguyên BK2026110002 xe 15H-012.34 tài xế Nam cont GAOU7821230",
            raw_payload={"text": "Đóng Triều Thuận Nguyên BK2026110002 xe 15H-012.34 tài xế Nam cont GAOU7821230"},
            zalo_sent_at=datetime.now(UTC),
            processing_status=MessageStatus.RECEIVED.value,
        )
        db.add(msg1)
        db.commit()

        assert handle_assistant(db, msg1, grp_src) is False
        ExtractionHandler.process_message_by_id(db, msg1.id)

        msg2 = ZaloMessage(
            id=snowflake.generate(),
            zalo_message_id=f"zalo_msg_2_{idx}_{uid}",
            group_id=grp_src.zalo_group_id,
            sender_id=sender,
            sender_name="Vũ Tiến Đạt",
            message_text="Bổ sung sđt 0912888777 chì VS998877",
            raw_payload={"text": "Bổ sung sđt 0912888777 chì VS998877"},
            quote_msg_id=msg1.zalo_message_id if use_quote else None,
            zalo_sent_at=datetime.now(UTC),
            processing_status=MessageStatus.RECEIVED.value,
        )
        db.add(msg2)
        db.commit()

        # Phải nhường cho ExtractionHandler gộp vào đơn pending thay vì assistant tools_carrier
        assert handle_assistant(db, msg2, grp_src) is False
        ExtractionHandler.process_message_by_id(db, msg2.id)

        all_jobs = db.scalars(select(ContainerJob).where(ContainerJob.message_id.in_([msg1.id, msg2.id]))).all()
        assert len(all_jobs) == 1
        assert all_jobs[0].truck_record is not None
        assert all_jobs[0].truck_record.truck_plate == "15H-012.34"
        assert all_jobs[0].truck_record.driver_name == "Nam"
        assert all_jobs[0].truck_record.driver_phone == "0912888777"
        assert all_jobs[0].seal_no == "VS998877"


def test_missing_trailer_triggers_immediate_warning_and_reviews_include_plan_date(api_client, db_session, monkeypatch):
    """Tin thiếu rơ-moóc phải báo ngay cho nhà xe/ĐHVT, và /api/reviews luôn trả plan_date cho candidate_plans."""
    from datetime import UTC, datetime
    from uuid import uuid4
    from sqlalchemy import select
    from src.api.auth import create_access_token
    from src.domain.enums import CorrectionStatus, MessageStatus
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import BotReply, ReviewCase, TransportPlan, User, ZaloMessage

    db, grp_src, _ = _setup_booking_context_db(db_session)
    uid = uuid4().hex[:6]
    monkeypatch.setattr(
        "src.handlers.carrier_flow_service.ZaloDispatcher.send_to_group",
        lambda **kwargs: (True, f"bot_tr_{kwargs.get('quote_msg_id', 'x')}", None),
    )

    from src.domain.rules import compute_iso6346_check_digit
    unique_cont = f"TEMU{uuid4().int % 900000 + 100000}"
    unique_cont = f"{unique_cont}{compute_iso6346_check_digit(unique_cont + '0')}"

    # 1. Tin đủ xe, tài xế, SĐT, cont, chì NHƯNG thiếu rơ-moóc -> phải báo thiếu rơ-moóc ngay
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"zalo_no_tr_{uid}",
        group_id=grp_src.zalo_group_id,
        sender_id=f"driver_tr_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text=f"Đóng Triều Thuận Nguyên BK2026110002 xe 15H-012.34 tài xế Nam 0912888777 cont {unique_cont} chì VS998877",
        raw_payload={"text": "missing trailer"},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db.add(msg)
    db.commit()

    ExtractionHandler.process_message_by_id(db, msg.id)
    db.refresh(msg)
    assert msg.processing_status == MessageStatus.NEEDS_REVIEW.value

    bot_reply = db.scalar(
        select(BotReply).where(BotReply.message_id == msg.id, BotReply.status == CorrectionStatus.PENDING.value)
    )
    assert bot_reply is not None
    assert "bổ sung biển số rơ-moóc" in bot_reply.reply_text.lower()

    rc = db.scalar(select(ReviewCase).where(ReviewCase.message_id == msg.id))
    assert rc is not None
    assert "MISSING_TRAILER_PLATE" in ((rc.details or {}).get("warnings") or [])

    # 2. Kiểm tra GET /api/reviews tự bổ sung plan_date cho candidate_plans (kể cả ca cũ thiếu plan_date trong JSON)
    lo_plan = db.scalar(select(TransportPlan).where(TransportPlan.booking_no == "BK2026110002").order_by(TransportPlan.id.asc()))
    assert lo_plan is not None
    legacy_rc = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        container_job_id=rc.container_job_id,
        case_type="PLAN_SYNC_REQUIRED",
        reason="Test gợi ý có ngày",
        details={
            "candidate_plans": [
                {
                    "plan_id": str(lo_plan.id),
                    "order_code": lo_plan.order_code,
                    "order_type": lo_plan.order_type,
                    "customer_name": lo_plan.customer_name,
                    "score": 80,
                    "evidences": ["matching_slot"],
                }
            ]
        },
        status="PENDING",
    )
    dhvt_user = User(
        id=snowflake.generate(),
        username=f"dhvt_tr_{uid}",
        full_name="ĐHVT Test",
        password_hash="x",
        role="DHVT",
        is_active=True,
    )
    db.add_all([legacy_rc, dhvt_user])
    db.commit()

    token = create_access_token({"sub": str(dhvt_user.id), "username": dhvt_user.username, "role": "DHVT"})
    resp = api_client.get(
        "/api/reviews?case_type=PLAN_SYNC_REQUIRED&limit=20",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json().get("reviews") or []
    matched_case = next((it for it in items if it["id"] == str(legacy_rc.id)), None)
    assert matched_case is not None
    cands = matched_case.get("candidate_plans") or []
    assert len(cands) == 1
    assert cands[0].get("plan_date") == "2026-11-20"


def test_seal_optional_and_review_change_after_sent_renders_diff_update(api_client, db_session, monkeypatch):
    """Không bắt buộc số chì; duyệt REVIEW_CHANGE_AFTER_SENT phải tạo tin THÔNG BÁO CẬP NHẬT ghi rõ cũ -> mới."""
    from datetime import UTC, date, datetime
    from uuid import uuid4
    from sqlalchemy import select
    from src.api.auth import create_access_token
    from sqlalchemy import select

    from src.domain.enums import GroupRole, MessageStatus, SendMode
    from src.domain.models import ExtractedContainerLine
    from src.domain.rules import compute_iso6346_check_digit
    from src.infrastructure.models import (
        Carrier,
        Customer,
        OutboundMessage,
        ReviewCase,
        RouteMap,
        TransportPlan,
        User,
        ZaloGroup,
        ZaloMessage,
    )
    from src.outbound.templates import OutboundTemplateBuilder

    uid = uuid4().hex[:6]
    cont = f"SELU{uuid4().int % 900000 + 100000}"
    cont = f"{cont}{compute_iso6346_check_digit(cont + '0')}"

    # 1. Thiếu số chì nhưng đủ xe + mooc + tài xế + SĐT + cont -> hợp lệ, không đòi số chì
    line_no_seal = ExtractedContainerLine(
        line_no=1,
        truck_plate="29H-234.56",
        trailer_plate="15R-987.65",
        driver_name="Tùng Anh",
        driver_phone="0345032001",
        container_no=cont,
        container_size="40",
        seal_no=None,
        order_type="RETURN",
        customer_hint="THE SUPRA",
        warehouse_hint="KHO MASAN VIỆT HÒA HẢI PHÒNG",
        check_digit_valid=True,
    )
    ok_seal, missing_seal = OutboundTemplateBuilder.check_core_fields_completeness(line_no_seal)
    assert ok_seal is True
    assert missing_seal == []
    rendered_no_seal = OutboundTemplateBuilder.build_customer_notification(line_no_seal)
    assert "Số chì: Chưa có" in rendered_no_seal

    # 2. Duyệt REVIEW_CHANGE_AFTER_SENT -> phải gửi mẫu THÔNG BÁO CẬP NHẬT ghi rõ "- Lái xe: Tùng Anh -> vũ tiến đạt"
    cust = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"SUPRA_{uid}",
        name="CÔNG TY CỔ PHẦN THE SUPRA",
        normalized_name=f"cong ty co phan the supra {uid}",
        is_active=True,
    )
    carrier = Carrier(
        id=snowflake.generate(),
        code=f"CR_{uid}",
        name=f"Nhà xe {uid}",
        normalized_name=f"nha xe {uid}",
        is_active=True,
    )
    db_session.add_all([cust, carrier])
    db_session.flush()

    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_src_upd_{uid}",
        name="Nhà xe test",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(carrier.id),
        send_mode=SendMode.MANUAL.value,
        is_active=True,
        is_test=True,
    )
    tgt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_tgt_upd_{uid}",
        name="Khách test",
        group_role=GroupRole.DESTINATION.value,
        send_mode=SendMode.MANUAL.value,
        is_active=True,
        is_test=True,
    )
    db_session.add_all([src_grp, tgt_grp])
    db_session.flush()
    db_session.add(
        RouteMap(
            id=snowflake.generate(),
            customer_id=cust.id,
            zalo_group_id=tgt_grp.id,
            priority=10,
            is_active=True,
        )
    )
    plan = TransportPlan(
        id=snowflake.generate(),
        order_code=f"RO2908_{uid}",
        order_type="tra",
        plan_date=date(2026, 11, 17),
        customer_id=cust.id,
        customer_name=cust.name,
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        warehouse_name="KHO MASAN VIỆT HÒA HẢI PHÒNG",
        delivery_address="KHO MASAN VIỆT HÒA HẢI PHÒNG",
        container_no=cont,
        seal_no="1112061",
        planned_truck_plate="29H-234.56",
        planned_trailer_plate="15R-987.65",
        driver_name="Tùng Anh",
        driver_phone="0345032001",
        required_time="07:00",
        group_id=tgt_grp.zalo_group_id,
        version=2,
    )
    monkeypatch.setattr("src.api.reviews.sync_plan_to_tms", lambda *a, **kw: "SYNCED")
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_zupd_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"drv_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text="Đổi lái xe sang vũ tiến đạt",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.NEEDS_REVIEW.value,
    )
    dhvt_user = User(
        id=snowflake.generate(),
        username=f"dhvt_upd_{uid}",
        full_name="ĐHVT Update",
        password_hash="x",
        role="DHVT",
        is_active=True,
    )
    db_session.add_all([plan, msg, dhvt_user])
    db_session.flush()

    rc = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        case_type="REVIEW_CHANGE_AFTER_SENT",
        reason="Chuyến đã phát hành; cần duyệt đính chính trên Web.",
        details={
            "transport_plan_id": str(plan.id),
            "expected_version": 2,
            "container_no": cont,
            "proposed_changes": {"driver_name": "vũ tiến đạt"},
        },
        status="PENDING",
    )
    db_session.add(rc)
    db_session.commit()

    token = create_access_token({"sub": str(dhvt_user.id), "username": dhvt_user.username, "role": "DHVT"})
    resp = api_client.post(
        f"/api/reviews/{rc.id}/approve",
        json={"operator_name": dhvt_user.username},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    out = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.idempotency_key.like(f"outbound:approved:%:{rc.id}"))
    )
    assert out is not None
    assert out.message_kind == "update"
    assert "THÔNG BÁO CẬP NHẬT THÔNG TIN XE" in out.content
    assert "- Lái xe: Tùng Anh -> vũ tiến đạt" in out.content


def test_standalone_seal_supplement_merges_after_job_without_seal(db_session, monkeypatch):
    """Không đòi số chì khi đủ xe+mooc+tài+sđt+cont; nhưng gửi mã chì 'VS998877' sau đó phải gộp đúng đơn."""
    from datetime import UTC, date, datetime
    from uuid import uuid4
    from sqlalchemy import select
    from src.assistant.service import handle_assistant
    from src.domain.enums import CorrectionStatus, GroupRole, MessageStatus, OutboundStatus, SendMode
    from src.domain.rules import compute_iso6346_check_digit
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import (
        BotReply,
        Carrier,
        ContainerJob,
        Customer,
        OutboundMessage,
        RouteMap,
        TransportPlan,
        ZaloGroup,
        ZaloMessage,
    )

    uid = uuid4().hex[:6]
    cont = f"DRYU{uuid4().int % 900000 + 100000}"
    cont = f"{cont}{compute_iso6346_check_digit(cont + '0')}"
    monkeypatch.setattr(
        "src.handlers.carrier_flow_service.ZaloDispatcher.send_to_group",
        lambda **kwargs: (True, f"bot_{kwargs.get('quote_msg_id', 'x')}", None),
    )

    cust = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"C_SEAL_{uid}",
        name="CÔNG TY TEST SEAL TÙY CHỌN",
        normalized_name=f"cong ty test seal tuy chon {uid}",
        is_active=True,
    )
    carrier = Carrier(
        id=snowflake.generate(),
        code=f"NXS_{uid}",
        name=f"Nhà xe seal {uid}",
        normalized_name=f"nha xe seal {uid}",
        is_active=True,
    )
    db_session.add_all([cust, carrier])
    db_session.flush()
    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_src_s_{uid}",
        name="Nhà xe test",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(carrier.id),
        send_mode=SendMode.MANUAL.value,
        is_active=True,
        is_test=True,
    )
    tgt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_tgt_s_{uid}",
        name="Khách test",
        group_role=GroupRole.DESTINATION.value,
        send_mode=SendMode.MANUAL.value,
        is_active=True,
        is_test=True,
    )
    db_session.add_all([src_grp, tgt_grp])
    db_session.flush()
    db_session.add(RouteMap(id=snowflake.generate(), customer_id=cust.id, zalo_group_id=tgt_grp.id, is_active=True))
    db_session.add(
        TransportPlan(
            id=snowflake.generate(),
            order_code=f"RO_{uid}",
            order_type="tra",
            plan_date=date(2026, 11, 20),
            customer_id=cust.id,
            customer_name=cust.name,
            carrier_id=carrier.id,
            carrier_name=carrier.name,
            warehouse_name="Kho test",
            delivery_address="Kho test",
            container_no=cont,
            seal_no=None,  # DB kế hoạch chưa có số chì
            group_id=tgt_grp.zalo_group_id,
            version=1,
        )
    )
    db_session.flush()

    sender = f"drv_s_{uid}"
    # 1. Thiếu số cont -> hỏi cont
    m1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_m1_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender,
        sender_name="Vũ Tiến Đạt",
        message_text="29H23456\n15R98765\nTùng Anh\n0345032001",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m1)
    db_session.commit()
    assert handle_assistant(db_session, m1, src_grp) is False
    ExtractionHandler.process_message_by_id(db_session, m1.id)

    # 2. Gửi số cont (chưa có chì) -> KHÔNG được hỏi thiếu chì, tạo ngay thông báo "Số chì: Chưa có"
    m2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_m2_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender,
        sender_name="Vũ Tiến Đạt",
        message_text=cont,
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m2)
    db_session.commit()
    assert handle_assistant(db_session, m2, src_grp) is False
    ExtractionHandler.process_message_by_id(db_session, m2.id)

    bot_replies_after_2 = db_session.scalars(
        select(BotReply).where(
            BotReply.message_id == m2.id,
            BotReply.status == CorrectionStatus.PENDING.value,
        )
    ).all()
    assert bot_replies_after_2 == [], [b.reply_text for b in bot_replies_after_2]
    confirm_reply_2 = db_session.scalar(
        select(BotReply).where(
            BotReply.message_id == m2.id,
            BotReply.status == CorrectionStatus.RESOLVED.value,
        )
    )
    assert confirm_reply_2 is not None and "Đã nhận bổ sung đủ thông tin" in confirm_reply_2.reply_text
    out2 = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.idempotency_key.like(f"outbound:supplement:{m2.id}:%"))
    )
    assert out2 is not None and "Số chì: Chưa có" in out2.content

    # Giả sử thông báo đã gửi xong -> nhà xe gửi thêm mã chì độc lập "VS998877"
    out2.status = OutboundStatus.SENT.value
    job = db_session.scalar(select(ContainerJob).where(ContainerJob.message_id == m1.id))
    assert job is not None
    job.routing_status = "SENT"
    db_session.commit()

    m3 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_m3_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender,
        sender_name="Vũ Tiến Đạt",
        message_text="VS998877",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m3)
    db_session.commit()
    assert handle_assistant(db_session, m3, src_grp) is False
    ExtractionHandler.process_message_by_id(db_session, m3.id)

    db_session.refresh(job)
    assert job.seal_no == "VS998877"
    out3 = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.idempotency_key.like(f"outbound:supplement:{m3.id}:%"))
    )
    assert out3 is not None and out3.message_kind == "update"
    assert "- Số chì: Chưa có -> VS998877" in out3.content


def test_results_only_filter_and_reviews_include_outbound_preview(db_session, api_client):
    """Kiểm tra `/api/outbound/messages?results_only=true` chỉ trả tin đã duyệt/tự động đạt và `/api/reviews` kèm `outbound_preview`."""
    from datetime import UTC, datetime

    from src.domain.enums import OutboundStatus, ReviewStatus
    from src.infrastructure.models import OutboundMessageItem

    uid = uuid4().hex[:8]
    tgt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_tgt_res_{uid}",
        name=f"Khách Res {uid}",
        group_role="TARGET",
        send_mode="AUTO",
        is_test=True,
        is_active=True,
    )
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_msg_res_{uid}",
        group_id=f"test_src_res_{uid}",
        sender_id=f"drv_{uid}",
        sender_name="Tài xế test",
        message_text=f"Cont DRYU8940154 {uid}",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status="NEEDS_REVIEW",
    )
    db_session.add_all([tgt_grp, msg])
    db_session.flush()

    tr_ok = TruckRecord(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_plate="29C-463.08",
        trailer_plate="29R-301.32",
        driver_name="Trịnh Văn Đức",
        driver_phone="0973821189",
    )
    db_session.add(tr_ok)
    db_session.flush()

    job = ContainerJob(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_record_id=tr_ok.id,
        line_no=1,
        container_no="DRYU8940154",
        order_type="dong",
        validation_status="NEEDS_REVIEW",
        routing_status="PENDING",
        tms_sync_status="PENDING",
    )
    db_session.add(job)
    db_session.flush()

    om_pending = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=tgt_grp.id,
        order_type="dong",
        message_kind="initial",
        content=f"PENDING_{uid}",
        idempotency_key=f"res_pend_{uid}",
        status=OutboundStatus.PENDING_APPROVAL.value,
    )
    om_failed = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=tgt_grp.id,
        order_type="dong",
        message_kind="initial",
        content=f"FAILED_{uid}",
        idempotency_key=f"res_fail_{uid}",
        status=OutboundStatus.FAILED.value,
    )
    om_approved = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=tgt_grp.id,
        order_type="dong",
        message_kind="initial",
        content=f"APPROVED_{uid}",
        idempotency_key=f"res_app_{uid}",
        status=OutboundStatus.SENT.value,
        approved_by="dhvt_user",
        approved_at=datetime.now(UTC),
        sent_at=datetime.now(UTC),
    )
    om_auto = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=tgt_grp.id,
        order_type="dong",
        message_kind="initial",
        content=f"AUTO_{uid}",
        idempotency_key=f"res_auto_{uid}",
        status=OutboundStatus.SENT.value,
        approved_by="auto_system",
        approved_at=datetime.now(UTC),
        sent_at=datetime.now(UTC),
    )
    db_session.add_all([om_pending, om_failed, om_approved, om_auto])
    db_session.flush()

    db_session.add(OutboundMessageItem(outbound_message_id=om_pending.id, container_job_id=job.id))
    rc = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        container_job_id=job.id,
        case_type="group_manual_review",
        reason="Chờ duyệt gửi khách",
        details={"outbound_message_id": str(om_pending.id)},
        status=ReviewStatus.PENDING.value,
    )
    db_session.add(rc)
    db_session.commit()

    # 1. `/api/outbound/messages?results_only=true` loại bỏ PENDING_APPROVAL và FAILED
    res_all = api_client.get(f"/api/outbound/messages?results_only=true&search={uid}")
    assert res_all.status_code == 200
    contents = {m["content"] for m in res_all.json()["messages"]}
    assert contents == {f"APPROVED_{uid}", f"AUTO_{uid}"}

    res_app = api_client.get(f"/api/outbound/messages?results_only=true&source_mode=approved&search={uid}")
    assert res_app.status_code == 200
    assert [m["content"] for m in res_app.json()["messages"]] == [f"APPROVED_{uid}"]
    assert res_app.json()["messages"][0]["approval_source"] == "approved"

    res_auto = api_client.get(f"/api/outbound/messages?results_only=true&source_mode=auto&search={uid}")
    assert res_auto.status_code == 200
    assert [m["content"] for m in res_auto.json()["messages"]] == [f"AUTO_{uid}"]
    assert res_auto.json()["messages"][0]["approval_source"] == "auto"

    res_sum = api_client.get("/api/outbound/summary")
    assert res_sum.status_code == 200
    sum_data = res_sum.json()
    assert sum_data["ket_qua_dat"] == sum_data["da_duyet"] + sum_data["tu_dong_dat"]

    # 2. `/api/reviews` trả kèm outbound_preview
    res_rev = api_client.get("/api/reviews?status=PENDING&limit=50")
    assert res_rev.status_code == 200
    matched = [r for r in res_rev.json()["reviews"] if r["id"] == str(rc.id)]
    assert len(matched) == 1
    assert matched[0]["outbound_preview"] is not None
    assert matched[0]["outbound_preview"]["content"] == f"PENDING_{uid}"


def test_update_merges_existing_pending_review_and_preserves_old_fields(db_session, api_client):
    """Tin cập nhật trên ca chờ duyệt phải gộp vào ca cũ (không tách form trống) và kế thừa đủ trường cũ."""
    from datetime import UTC, date, datetime

    from src.assistant.schemas import ScopeContext
    from src.assistant.tools_carrier import apply_change
    from src.domain.enums import ReviewStatus
    from src.infrastructure.models import Carrier, Customer, Warehouse

    uid = uuid4().hex[:8]
    carrier = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=int(snowflake.generate() % 1_000_000_000),
        code=f"MC{uid}",
        name=f"Nhà xe Merge {uid}",
        normalized_name=f"nha xe merge {uid}",
    )
    carrier_id = carrier.id
    db_session.add(carrier)
    db_session.flush()
    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_src_merge_{uid}",
        name=f"Nhà xe Merge {uid}",
        group_role="SOURCE",
        carrier_id=str(carrier_id),
        send_mode="MANUAL",
        is_test=True,
        is_active=True,
    )
    cust = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 1_000_000_000),
        name=f"Khách Merge {uid}",
        normalized_name=f"khach merge {uid}",
    )
    wh = Warehouse(
        id=snowflake.generate(),
        tms_warehouse_id=int(snowflake.generate() % 1_000_000_000),
        name=f"Kho Merge {uid}",
        normalized_name=f"kho merge {uid}",
    )
    db_session.add_all([src_grp, cust, wh])
    db_session.flush()

    cont = "GAOU7821230"
    plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 20),
        order_code=f"RO{uid[:6]}",
        order_type="tra",
        carrier_id=carrier_id,
        carrier_name=src_grp.name,
        customer_id=cust.id,
        customer_name=cust.name,
        warehouse_id=wh.id,
        warehouse_name=wh.name,
        container_no=cont,
        seal_no="010414",
        planned_truck_plate="15H-012.34",
        planned_trailer_plate="15R-099.88",
        driver_name="Nam",
        driver_phone=None,
        version=1,
    )
    m_prop = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_prop_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"drv_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text="Bổ sung sđt 0912888777 chì VS998877",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status="RECEIVED",
    )
    m_conf = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_conf_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"drv_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text="xác nhận",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status="RECEIVED",
    )
    db_session.add_all([plan, m_prop, m_conf])
    db_session.commit()

    scope = ScopeContext(
        role="CARRIER",
        group_id=src_grp.id,
        zalo_group_id=src_grp.zalo_group_id,
        group_role="SOURCE",
        sender_id=f"drv_{uid}",
        carrier_id=carrier_id,
        reference_time=datetime.now(UTC),
    )
    reply = apply_change(
        db_session,
        scope,
        m_conf,
        plan,
        {"driver_phone": "0912888777", "seal_no": "VS998877"},
        proposal_text=m_prop.message_text,
    )
    assert reply.needs_review is True
    db_session.commit()

    # Lần 2 cập nhật thêm biển số mới trong cùng nhóm & cùng kế hoạch -> phải gộp vào 1 ca duy nhất
    m_conf2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"test_conf2_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"drv_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text="xác nhận đổi xe 29H-555.66",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status="RECEIVED",
    )
    db_session.add(m_conf2)
    db_session.flush()
    apply_change(
        db_session,
        scope,
        m_conf2,
        plan,
        {"planned_truck_plate": "29H-555.66"},
        proposal_text="Đổi xe 29H-555.66",
    )
    db_session.commit()

    res = api_client.get("/api/reviews?status=PENDING&limit=50")
    assert res.status_code == 200
    found = [
        r
        for r in res.json()["reviews"]
        if (r.get("details") or {}).get("transport_plan_id") == str(plan.id)
    ]
    assert len(found) == 1
    cd = found[0]["container_details"]
    assert cd["customer_hint"] == cust.name
    assert cd["warehouse_hint"] == wh.name
    assert cd["truck_plate"] == "29H-555.66"
    assert cd["trailer_plate"] == "15R-099.88"
    assert cd["driver_name"] == "Nam"
    assert cd["driver_phone"] == "0912888777"
    assert cd["seal_no"] == "VS998877"
    assert "Bổ sung sđt 0912888777 chì VS998877" in (found[0]["message_context"]["raw_text"] or "")
    assert len(found[0]["details"]["changes"]) == 3


def test_quoted_supplement_cont_resolves_update_and_sends_confirm_reply(db_session):
    """Tin 'Đổi thông tin Xe ...' quote lại tin bổ sung chỉ ghi số cont phải kế thừa số cont và gửi phản hồi."""
    from datetime import UTC, date, datetime

    from sqlalchemy import select
    from src.domain.enums import CorrectionStatus, GroupRole, MessageStatus, OutboundStatus, SendMode
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import BotReply, Carrier, Customer, RouteMap

    uid = uuid4().hex[:8]
    cust = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 1_000_000_000),
        name=f"Khách Quote {uid}",
        normalized_name=f"khach quote {uid}",
        is_active=True,
    )
    carrier = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=int(snowflake.generate() % 1_000_000_000),
        code=f"NXQT_{uid}",
        name=f"Nhà xe Quote {uid}",
        normalized_name=f"nha xe quote {uid}",
        is_active=True,
    )
    db_session.add_all([cust, carrier])
    db_session.flush()
    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_src_qt_{uid}",
        name=f"Nhà xe Quote {uid}",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(carrier.id),
        send_mode=SendMode.AUTO.value,
        is_test=True,
        is_active=True,
    )
    tgt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_tgt_qt_{uid}",
        name=f"Khách Quote {uid}",
        group_role=GroupRole.DESTINATION.value,
        send_mode=SendMode.AUTO.value,
        is_test=True,
        is_active=True,
    )
    db_session.add_all([src_grp, tgt_grp])
    db_session.flush()
    db_session.add(RouteMap(id=snowflake.generate(), customer_id=cust.id, zalo_group_id=tgt_grp.id, is_active=True))

    cont = "VSQU8912340"
    db_session.add(
        TransportPlan(
            id=snowflake.generate(),
            plan_date=date(2026, 11, 20),
            order_code=f"LO{uid[:6]}",
            order_type="dong",
            customer_id=cust.id,
            customer_name=cust.name,
            carrier_id=carrier.id,
            carrier_name=carrier.name,
            warehouse_name="Kho test Quote",
            delivery_address="Kho test Quote",
            container_no=cont,
            group_id=tgt_grp.zalo_group_id,
            version=1,
        )
    )
    db_session.flush()

    sender = f"drv_qt_{uid}"
    m1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"qt_m1_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender,
        sender_name="Vũ Tùng Anh",
        message_text="29H23456\n15R98765\nTùng Anh\n0345032001",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m1)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m1.id)

    m2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"qt_m2_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender,
        sender_name="Vũ Tùng Anh",
        message_text=cont,
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m2)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m2.id)

    # Giả sử đơn 1 đã gửi xong
    orig_job = db_session.scalar(select(ContainerJob).where(ContainerJob.message_id == m1.id))
    assert orig_job is not None and orig_job.container_no == cont
    out2 = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.idempotency_key.like(f"outbound:supplement:{m2.id}:%"))
    )
    assert out2 is not None
    out2.status = OutboundStatus.SENT.value
    orig_job.routing_status = "ROUTED"
    db_session.commit()

    # Người dùng quote lại chính tin bổ sung `m2` ("VSIU2463280") và nhắn "Đổi thông tin Xe 29C46308 ..."
    m3 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"qt_m3_{uid}",
        quote_msg_id=m2.zalo_message_id,
        group_id=src_grp.zalo_group_id,
        sender_id=sender,
        sender_name="Vũ Tùng Anh",
        message_text="Đổi thông tin Xe 29C46308  / 29R-30132/ Trịnh Văn Đức  /  0973821189",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m3)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m3.id)

    pending_warns_m3 = db_session.scalars(
        select(BotReply).where(
            BotReply.message_id == m3.id,
            BotReply.status == CorrectionStatus.PENDING.value,
        )
    ).all()
    assert pending_warns_m3 == [], [b.reply_text for b in pending_warns_m3]
    upd_job = db_session.scalar(select(ContainerJob).where(ContainerJob.message_id == m3.id))
    assert upd_job is not None and upd_job.container_no == cont
    confirm_m3 = db_session.scalar(
        select(BotReply).where(
            BotReply.message_id == m3.id,
            BotReply.status == CorrectionStatus.RESOLVED.value,
        )
    )
    assert confirm_m3 is not None and cont in confirm_m3.reply_text


def test_five_required_fields_reviews_filter_and_customer_output_preview(db_session, api_client):
    """Chỉ bắt buộc 5 trường nhà xe; /api/reviews ẩn ca chưa đủ 5 trường và luôn dựng mẫu output gửi khách."""
    from datetime import UTC, datetime

    from src.domain.enums import ReviewStatus
    from src.domain.models import ExtractedContainerLine
    from src.outbound.templates import OutboundTemplateBuilder

    # 1. Đủ 5 trường (xe, rơ-moóc, cont, tài xế, SĐT), thiếu khách hàng/kho/loại lệnh/chì vẫn đạt
    ok_line = ExtractedContainerLine(
        truck_plate="29C-463.08",
        trailer_plate="29R-301.32",
        container_no="VSQU8912340",
        driver_name="Trịnh Văn Đức",
        driver_phone="0973821189",
    )
    is_comp, missing = OutboundTemplateBuilder.check_core_fields_completeness(ok_line)
    assert is_comp is True and missing == []

    # 2. /api/reviews?status=PENDING chỉ trả ca đã đủ 5 trường và kèm outbound_preview
    uid = uuid4().hex[:8]
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"rev_filt_{uid}",
        group_id=f"test_src_filt_{uid}",
        sender_id=f"drv_{uid}",
        sender_name="Tài xế Test",
        message_text=f"29C46308 / 29R30132 / VSQU8912340 / Trịnh Văn Đức / 0973821189 {uid}",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status="NEEDS_REVIEW",
    )
    db_session.add(msg)
    db_session.flush()

    tr_inc = TruckRecord(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_plate="29C-463.08",
        trailer_plate=None,  # thiếu rơ-moóc
        driver_name="Trịnh Văn Đức",
        driver_phone="0973821189",
    )
    tr_full = TruckRecord(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_plate="29C-463.08",
        trailer_plate="29R-301.32",
        driver_name="Trịnh Văn Đức",
        driver_phone="0973821189",
    )
    db_session.add_all([tr_inc, tr_full])
    db_session.flush()

    job_inc = ContainerJob(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_record_id=tr_inc.id,
        container_no="VSQU8912340",
        order_type="dong",
        validation_status="NEEDS_REVIEW",
        routing_status="PENDING",
    )
    job_full = ContainerJob(
        id=snowflake.generate(),
        message_id=msg.id,
        truck_record_id=tr_full.id,
        container_no="VSQU8912340",
        order_type="dong",
        customer_hint=f"Khách Output {uid}",
        warehouse_hint=f"Kho Output {uid}",
        validation_status="VALID",
        routing_status="PENDING",
    )
    db_session.add_all([job_inc, job_full])
    db_session.flush()

    rc_inc = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        container_job_id=job_inc.id,
        case_type="missing_fields",
        reason="INVALID_DRIVER_PHONE, MISSING_TRAILER_PLATE",
        status=ReviewStatus.PENDING.value,
    )
    rc_inc_conflict = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        container_job_id=job_inc.id,
        case_type="PLAN_FIELD_CONFLICT",
        reason="INVALID_DRIVER_PHONE",
        status=ReviewStatus.PENDING.value,
    )
    rc_full = ReviewCase(
        id=snowflake.generate(),
        message_id=msg.id,
        container_job_id=job_full.id,
        case_type="PLAN_FIELD_CONFLICT",
        reason="INVALID_DRIVER_PHONE",
        details={"changes": ["- Lái xe: Nam -> Trịnh Văn Đức"]},
        status=ReviewStatus.PENDING.value,
    )
    db_session.add_all([rc_inc, rc_inc_conflict, rc_full])
    db_session.commit()

    res = api_client.get("/api/reviews?status=PENDING&limit=100")
    assert res.status_code == 200
    returned_ids = {r["id"] for r in res.json()["reviews"]}
    assert str(rc_inc.id) not in returned_ids
    assert str(rc_inc_conflict.id) not in returned_ids
    assert str(rc_full.id) in returned_ids

    full_item = next(r for r in res.json()["reviews"] if r["id"] == str(rc_full.id))
    assert "INVALID_DRIVER_PHONE" not in (full_item["reason"] or "")
    assert full_item["outbound_preview"] is not None
    assert full_item["outbound_preview"]["status"] == "PREVIEW"
    assert "VSICO - THÔNG BÁO CẬP NHẬT THÔNG TIN XE" in full_item["outbound_preview"]["content"]
    assert "29C-463.08" in full_item["outbound_preview"]["content"]
    assert "29R-301.32" in full_item["outbound_preview"]["content"]
    assert "- Lái xe: Nam -> Trịnh Văn Đức" in full_item["outbound_preview"]["content"]

    res_direct = api_client.get(f"/api/reviews?review_id={rc_full.id}")
    assert res_direct.status_code == 200
    assert [r["id"] for r in res_direct.json()["reviews"]] == [str(rc_full.id)]

    from src.domain.short_link import decode_short_token, encode_short_token

    token = encode_short_token("r", rc_full.id, settings.short_link_secret)
    assert len(token) == 15
    assert str(rc_full.id) not in token
    assert decode_short_token(token, settings.short_link_secret) == ("r", rc_full.id)
    assert decode_short_token(token, "wrong-secret") is None
    tampered = ("b" if token[0] != "b" else "a") + token[1:]
    assert decode_short_token(tampered, settings.short_link_secret) is None

    res_short = api_client.get(f"/api/reviews?short_token={token}")
    assert res_short.status_code == 200
    assert [r["id"] for r in res_short.json()["reviews"]] == [str(rc_full.id)]

    res_bad_short = api_client.get(f"/api/reviews?short_token={tampered}")
    assert res_bad_short.status_code == 200
    assert res_bad_short.json()["reviews"] == []


def test_f1_dispatch_with_trailer_and_shared_container_never_returns_customer_not_found(db_session):
    """Tin F1 có cả moóc + đầu kéo và cont xuất hiện ở cả RO lẫn LO không được trả nhầm lỗi tra cứu khách hàng."""
    from datetime import UTC, date, datetime

    from sqlalchemy import select

    from src.domain.enums import GroupRole, MessageStatus, SendMode
    from src.domain.rules import compute_iso6346_check_digit
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import Carrier, Customer, OutboundMessage, ReviewCase, RouteMap, TransportPlan, ZaloGroup, ZaloMessage

    uid = uuid4().hex[:6]
    cont = "GAOU213153" + str(compute_iso6346_check_digit("GAOU2131530"))
    carrier = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=int(snowflake.generate() % 100_000_000),
        code=f"VS_{uid}",
        name=f"VSICO {uid}",
        normalized_name=f"vsico {uid}",
        is_active=True,
    )
    cust_ro = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 100_000_000),
        name=f"Khach RO {uid}",
        normalized_name=f"khach ro {uid}",
        is_active=True,
    )
    cust_lo = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 100_000_000),
        name=f"Khach LO {uid}",
        normalized_name=f"khach lo {uid}",
        is_active=True,
    )
    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"src_shared_{uid}",
        name="TMS Nhà xe - TEST",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(carrier.id),
        send_mode=SendMode.AUTO.value,
        is_test=True,
        is_active=True,
    )
    tgt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"tgt_shared_{uid}",
        name="TMS Khách - TEST",
        group_role=GroupRole.DESTINATION.value,
        send_mode=SendMode.AUTO.value,
        is_test=True,
        is_active=True,
    )
    db_session.add_all([carrier, cust_ro, cust_lo, src_grp, tgt_grp])
    db_session.flush()
    db_session.add_all([
        RouteMap(id=snowflake.generate(), customer_id=cust_ro.id, zalo_group_id=tgt_grp.id, is_active=True),
        RouteMap(id=snowflake.generate(), customer_id=cust_lo.id, zalo_group_id=tgt_grp.id, is_active=True),
    ])

    plan_ro = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 17),
        order_code=f"RO{uid[:5].upper()}",
        order_type="tra",
        customer_id=cust_ro.id,
        customer_name=cust_ro.name,
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        container_no=cont,
        planned_truck_plate="29C-466.47",
        driver_name="Bùi Thọ Vinh",
        group_id=tgt_grp.zalo_group_id,
        version=1,
    )
    plan_lo = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 17),
        order_code=f"LO{uid[:5].upper()}",
        order_type="dong",
        customer_id=cust_lo.id,
        customer_name=cust_lo.name,
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        container_no=cont,
        planned_truck_plate=None,
        driver_name=None,
        group_id=tgt_grp.zalo_group_id,
        version=1,
    )
    db_session.add_all([plan_ro, plan_lo])
    db_session.flush()

    m = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"msg_shared_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"sender_{uid}",
        sender_name="Vũ Tùng Anh",
        message_text=f"29R-30065 / Xe 29C44662 / Phạm Đức Vĩ / 0979333538 / {cont}",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m.id)

    from src.infrastructure.models import ContainerJob

    outs = db_session.scalars(
        select(OutboundMessage).where(OutboundMessage.target_group_id == src_grp.id)
    ).all()
    assert not any("Quý khách" in (o.content or "") for o in outs)
    jobs = db_session.scalars(select(ContainerJob).where(ContainerJob.message_id == m.id)).all()
    assert len(jobs) == 1
    assert jobs[0].container_no == cont
    assert jobs[0].validation_status == "VALID"
    tgt_outs = db_session.scalars(
        select(OutboundMessage).where(OutboundMessage.target_group_id == tgt_grp.id)
    ).all()
    assert len(tgt_outs) >= 1

    # Trường hợp chỉ có 1 kế hoạch khớp cont và nhà xe gửi tin đổi xe kèm cả biển moóc + đầu kéo
    rc = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m.id))
    if rc is not None:
        db_session.delete(rc)
    db_session.delete(plan_lo)
    db_session.commit()

    m_upd = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"msg_upd_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"sender_{uid}",
        sender_name="Vũ Tùng Anh",
        message_text=f"Đổi xe cont {cont} sang 29R-30065 / Xe 29C99988 / tài xế Trần Văn Mới / 0911222333",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m_upd)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m_upd.id)

    from src.infrastructure.models import MessageDraft

    draft = db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == m_upd.id))
    assert draft is not None and draft.status == "WAITING_REPLY"
    outs_after = db_session.scalars(
        select(OutboundMessage).where(OutboundMessage.target_group_id == src_grp.id)
    ).all()
    assert not any("Quý khách" in (o.content or "") for o in outs_after)


def test_shared_container_ro_then_lo_sequential_dispatch_and_dhvt_alert(db_session):
    """Cùng 1 số cont có cả RO và LO: gửi lần 1 xử lý RO, sau khi RO đã gửi thì gửi lần 2 chuyển sang LO và báo ĐHVT."""
    from datetime import UTC, date, datetime
    from sqlalchemy import select

    from src.domain.enums import GroupRole, MessageStatus, OutboundStatus, ReviewStatus, SendMode
    from src.domain.rules import compute_iso6346_check_digit
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import (
        ActivityLog,
        BotReply,
        Carrier,
        ContainerJob,
        Customer,
        OutboundMessage,
        ReviewCase,
        RouteMap,
        TransportPlan,
        ZaloGroup,
        ZaloMessage,
    )

    uid = uuid4().hex[:6]
    cont = "GAOU313153" + str(compute_iso6346_check_digit("GAOU3131530"))
    carrier = Carrier(
        id=snowflake.generate(),
        tms_carrier_id=int(snowflake.generate() % 100_000_000),
        code=f"MC_{uid}",
        name=f"VSICO {uid}",
        normalized_name=f"vsico {uid}",
        is_active=True,
    )
    cust_ro = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 100_000_000),
        name=f"Khach Tra {uid}",
        normalized_name=f"khach tra {uid}",
        is_active=True,
    )
    cust_lo = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 100_000_000),
        name=f"Khach Dong {uid}",
        normalized_name=f"khach dong {uid}",
        is_active=True,
    )
    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"src_seq_{uid}",
        name="TMS Nhà xe - TEST",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(carrier.id),
        send_mode=SendMode.AUTO.value,
        is_test=True,
        is_active=True,
    )
    tgt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"tgt_seq_{uid}",
        name="TMS Khách hàng - TEST",
        group_role=GroupRole.DESTINATION.value,
        send_mode=SendMode.MANUAL.value,
        is_test=True,
        is_active=True,
    )
    db_session.add_all([carrier, cust_ro, cust_lo, src_grp, tgt_grp])
    db_session.flush()
    db_session.add_all([
        RouteMap(id=snowflake.generate(), customer_id=cust_ro.id, zalo_group_id=tgt_grp.id, is_active=True),
        RouteMap(id=snowflake.generate(), customer_id=cust_lo.id, zalo_group_id=tgt_grp.id, is_active=True),
    ])

    plan_ro = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 17),
        order_code=f"RO{uid[:4].upper()}1",
        order_type="tra",
        customer_id=cust_ro.id,
        customer_name=cust_ro.name,
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        container_no=cont,
        group_id=tgt_grp.zalo_group_id,
        version=1,
    )
    plan_lo = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 17),
        order_code=f"LO{uid[:4].upper()}2",
        order_type="dong",
        customer_id=cust_lo.id,
        customer_name=cust_lo.name,
        carrier_id=carrier.id,
        carrier_name=carrier.name,
        container_no=cont,
        group_id=tgt_grp.zalo_group_id,
        version=1,
    )
    db_session.add_all([plan_ro, plan_lo])
    db_session.flush()

    # Lần 1 -> khớp lệnh trả (RO) và chờ ĐHVT duyệt
    m1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"seq_m1_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"drv_seq_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text=f"29R-30065 / Xe 29C44662 / Phạm Đức Vĩ / 0979333538 / {cont}",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m1)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m1.id)

    rc1 = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m1.id))
    assert rc1 is not None
    out1 = db_session.get(OutboundMessage, int(rc1.details["outbound_message_id"]))
    assert out1 is not None
    # Đánh dấu RO đã duyệt & gửi khách
    out1.status = OutboundStatus.SENT.value
    rc1.status = ReviewStatus.APPROVED.value
    db_session.commit()

    # Lần 2 -> cùng xe/cont -> phải chuyển sang lệnh Đóng hàng (LO), KHÔNG coi là duplicate và phải báo ĐHVT
    m2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"seq_m2_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"drv_seq_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text=f"29R-30065 / Xe 29C44662 / Phạm Đức Vĩ / 0979333538 / {cont}",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m2)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m2.id)

    job2 = db_session.scalar(select(ContainerJob).where(ContainerJob.message_id == m2.id))
    assert job2 is not None and job2.order_type == "LOAD"
    assert str((job2.raw_fields or {}).get("transport_plan_id")) == str(plan_lo.id)
    rc2 = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m2.id))
    assert rc2 is not None and rc2.status == ReviewStatus.PENDING.value
    out2 = db_session.get(OutboundMessage, int(rc2.details["outbound_message_id"]))
    assert out2 is not None and out2.status == OutboundStatus.PENDING_APPROVAL.value
    assert out2.message_kind == "initial"
    alert2 = db_session.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "DHVT_PENDING_OUTBOUND_ALERT",
            ActivityLog.entity_id == str(out2.id),
        )
    )
    assert alert2 is not None

    # Lần 3 -> cả RO lẫn LO đều đã SENT -> trả BotReply nhắc nhà xe không im lặng, không tạo ReviewCase thừa
    out2.status = OutboundStatus.SENT.value
    rc2.status = ReviewStatus.APPROVED.value
    db_session.commit()

    m3 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"seq_m3_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"drv_seq_{uid}",
        sender_name="Vũ Tiến Đạt",
        message_text=f"29R-30065 / Xe 29C44662 / Phạm Đức Vĩ / 0979333538 / {cont}",
        raw_payload={"is_test": True},
        zalo_sent_at=datetime.now(UTC),
        processing_status=MessageStatus.RECEIVED.value,
    )
    db_session.add(m3)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m3.id)

    rc3 = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m3.id))
    assert rc3 is None
    dup_reply = db_session.scalar(select(BotReply).where(BotReply.message_id == m3.id))
    assert dup_reply is not None and "trùng khớp" in dup_reply.reply_text
