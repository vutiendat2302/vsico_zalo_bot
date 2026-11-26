"""Bộ kiểm thử chuyên biệt cho tách thực thể vận tải viết dính liền không dấu cách."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.domain.enums import Intent
from src.domain.patterns import deglue_transport_entities
from src.domain.rules import clean_driver_name
from src.messaging.classifier import IntentClassifier
from src.parsing.ai_fallback import AIFallbackExtractor
from src.parsing.local_nlp_extractor import enrich_local, evaluate_missing_field_signals
from src.parsing.trip_parser import TripParser
from src.validation.validators import ContainerValidator


def _parse_tier1_and_tier2(db: Session, text: str):
    """Chạy đầy đủ Tầng 1 (TripParser) -> Tầng 2 (Local NLP + Validator) trên chuỗi đầu vào."""
    p = ContainerValidator.validate_all(TripParser.parse_message(text))
    e = ContainerValidator.validate_all(
        enrich_local(db, p, None, text, datetime.now(), include_phobert=True)
    )
    dec, sigs = evaluate_missing_field_signals(e[0])
    return e[0], dec, sigs


def test_user_7_glued_entity_samples_pass_end_to_end(db_session: Session) -> None:
    """Kiểm chứng trọn vẹn 7 mẫu thực thể viết dính liền theo yêu cầu nghiệm thu."""
    # 1. 29C44719GAOU2701401
    junk_1, _, _ = IntentClassifier.classify_junk("29C44719GAOU2701401")
    assert junk_1 != "JUNK"
    ln1, dec1, _ = _parse_tier1_and_tier2(db_session, "29C44719GAOU2701401")
    assert ln1.truck_plate == "29C-447.19"
    assert ln1.container_no == "GAOU2701401"
    assert dec1 == "STOP_NO_SIGNAL"

    # 2. Mooc28RM45678
    junk_2, _, _ = IntentClassifier.classify_junk("Mooc28RM45678")
    assert junk_2 != "JUNK"
    ln2, dec2, _ = _parse_tier1_and_tier2(db_session, "Mooc28RM45678")
    assert ln2.trailer_plate == "28RM-456.78"
    assert dec2 == "STOP_NO_SIGNAL"

    # 3. SDDT0345032001
    junk_3, _, _ = IntentClassifier.classify_junk("SDDT0345032001")
    assert junk_3 != "JUNK"
    ln3, dec3, _ = _parse_tier1_and_tier2(db_session, "SDDT0345032001")
    assert ln3.driver_phone == "0345032001"
    assert dec3 == "STOP_NO_SIGNAL"

    # 4. TaiXeVuTungAnh
    junk_4, _, _ = IntentClassifier.classify_junk("TaiXeVuTungAnh")
    assert junk_4 != "JUNK"
    ln4, dec4, _ = _parse_tier1_and_tier2(db_session, "TaiXeVuTungAnh")
    assert ln4.driver_name == "Vu Tung Anh"
    assert dec4 == "STOP_NO_SIGNAL"
    assert AIFallbackExtractor.should_trigger_ai([ln4], intent=Intent.PARSE_TRUCK_INFO) is False

    # 5. 29C44719GAOU2701401SDT0345032001
    junk_5, _, _ = IntentClassifier.classify_junk("29C44719GAOU2701401SDT0345032001")
    assert junk_5 != "JUNK"
    ln5, dec5, _ = _parse_tier1_and_tier2(db_session, "29C44719GAOU2701401SDT0345032001")
    assert ln5.truck_plate == "29C-447.19"
    assert ln5.container_no == "GAOU2701401"
    assert ln5.driver_phone == "0345032001"
    assert dec5 == "STOP_NO_SIGNAL"

    # 6. RO2926xe29C44719taiVuTungAnh
    junk_6, _, _ = IntentClassifier.classify_junk("RO2926xe29C44719taiVuTungAnh")
    assert junk_6 != "JUNK"
    ln6, dec6, _ = _parse_tier1_and_tier2(db_session, "RO2926xe29C44719taiVuTungAnh")
    assert ln6.order_type == "RETURN"
    assert ln6.truck_plate == "29C-447.19"
    assert ln6.driver_name == "Vu Tung Anh"
    assert dec6 == "STOP_NO_SIGNAL"

    # 7. Mooc28RM-45678,SDDT0345032001,VũTùngAnh,29C44719GAOU2701401
    full_glued = "Mooc28RM-45678,SDDT0345032001,VũTùngAnh,29C44719GAOU2701401"
    junk_7, _, _ = IntentClassifier.classify_junk(full_glued)
    assert junk_7 == "CANDIDATE"
    ln7, dec7, sigs7 = _parse_tier1_and_tier2(db_session, full_glued)
    assert ln7.trailer_plate == "28RM-456.78"
    assert ln7.driver_phone == "0345032001"
    assert ln7.driver_name == "Vũ Tùng Anh"
    assert ln7.truck_plate == "29C-447.19"
    assert ln7.container_no == "GAOU2701401"
    assert ln7.validation_status == "VALID"
    assert dec7 == "COMPLETE" and sigs7 == []
    assert AIFallbackExtractor.should_trigger_ai([ln7], intent=Intent.PARSE_TRUCK_INFO) is False


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        (
            "LO2546xe15H01234mooc15R04802contMSCU6635324taixeNguyenVanMinh0912345678",
            {
                "order_type": "LOAD",
                "truck_plate": "15H-012.34",
                "trailer_plate": "15R-048.02",
                "container_no": "MSCU6635324",
                "driver_name": "Nguyen Van Minh",
                "driver_phone": "0912345678",
            },
        ),
        (
            "29C-447.19VũTùngAnh0345032001",
            {
                "truck_plate": "29C-447.19",
                "driver_name": "Vũ Tùng Anh",
                "driver_phone": "0345032001",
            },
        ),
        (
            "0345032001VũTùngAnh",
            {
                "driver_phone": "0345032001",
                "driver_name": "Vũ Tùng Anh",
            },
        ),
        (
            "CONTGAOU2701401SDT0345032001",
            {
                "container_no": "GAOU2701401",
                "driver_phone": "0345032001",
            },
        ),
        (
            "txPhamDucVi",
            {
                "driver_name": {"Pham Duc Vi", "Phạm Đức Vĩ"},
            },
        ),
    ],
)
def test_extended_glued_entity_variants(
    db_session: Session, raw_text: str, expected: dict[str, str | set[str]]
) -> None:
    """Kiểm chứng các biến thể thực thể viết dính liền mở rộng (kể cả 6 thực thể dính 1 mạch)."""
    ln, _, _ = _parse_tier1_and_tier2(db_session, raw_text)
    for field_name, exp_val in expected.items():
        actual = getattr(ln, field_name)
        if isinstance(exp_val, set):
            assert actual in exp_val
        else:
            assert actual == exp_val
    # Xác nhận riêng Tầng 1 tách đúng 'txPhamDucVi' -> 'Pham Duc Vi' trước khi Tầng 2 đối chiếu danh mục tài xế
    if raw_text == "txPhamDucVi":
        assert TripParser.parse_message(raw_text)[0].driver_name == "Pham Duc Vi"


def test_glued_entity_guardrails_no_false_splits() -> None:
    """Đảm bảo bộ tách biên không làm hỏng URL, CCCD/Seal, container thừa số hay cụm từ tiếng Việt thường."""
    # 1. Bảo vệ URL
    url_msg = "Mở ca duyệt tại https://bot.vtdat.com/RO2926xe29C44719 nhé"
    assert "https://bot.vtdat.com/RO2926xe29C44719" in deglue_transport_entities(url_msg)

    # 2. Không bắt nhầm CCCD và SEAL làm SĐT
    safe_lns = TripParser.parse_message(
        "Xe 29C-447.19 mooc 28RM-456.78 Vũ Tùng Anh CCCD0345032001 SEAL0912345678 GAOU2701401"
    )
    assert safe_lns[0].driver_phone is None

    # 3. Container thừa 1 số (12 ký tự) không bị cắt thành container 11 ký tự hợp lệ giả
    overlong = deglue_transport_entities("29C44719 GAOU27014012")
    assert "GAOU27014012" in overlong
    lns_over = ContainerValidator.validate_all(TripParser.parse_message("Xe 29C-447.19 GAOU27014012"))
    assert lns_over[0].validation_status != "VALID"

    # 4. Từ tiếng Việt thường bắt đầu bằng 'tài'/'tai' không bị tách sai và tên có dấu phức tạp không bị cắt hỏng âm tiết
    assert deglue_transport_entities("tài liệu gửi anh") == "tài liệu gửi anh"
    assert deglue_transport_entities("tai nạn kẹt xe") == "tai nạn kẹt xe"
    assert clean_driver_name("TịnhVănDuân") == "Tịnh Văn Duân"
    assert clean_driver_name("ĐặngQuốcĐạt") == "Đặng Quốc Đạt"
    assert clean_driver_name("NguyễnVănDoanh") == "Nguyễn Văn Doanh"


def test_sandbox_nlp_analyze_handles_glued_entities(api_client: TestClient) -> None:
    """Kiểm chứng endpoint `POST /api/sandbox/nlp-analyze` trả đủ 5/5 trường với chuỗi dính liền."""
    resp = api_client.post(
        "/api/sandbox/nlp-analyze",
        json={
            "text": "Mooc28RM-45678,SDDT0345032001,VũTùngAnh,29C44719GAOU2701401",
            "include_plan_resolution": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["tier2_phobert_nlp"]["decision"] == "COMPLETE"
    assert body["tier3_llm_trigger"] is False
    assert body["carrier_warning_preview"] == ""
    rec = body["records"][0]
    assert rec["plate"] == "29C44719"
    assert rec["cont_no"] == "GAOU2701401"
    assert rec["driver_name"] == "Vũ Tùng Anh"
    assert rec["driver_phone"] == "0345032001"
    assert rec["validation_status"] == "VALID"

    resp_ro = api_client.post(
        "/api/sandbox/nlp-analyze",
        json={
            "text": "RO2926xe29C44719taiVuTungAnh",
            "include_plan_resolution": False,
        },
    )
    assert resp_ro.status_code == 200
    body_ro = resp_ro.json()
    rec_ro = body_ro["records"][0]
    assert rec_ro["plate"] == "29C44719"
    assert rec_ro["driver_name"] == "Vu Tung Anh"
    assert rec_ro["order_type"] == "RETURN"


def test_malformed_container_reports_invalid_and_never_hijacks_previous_job_or_empty_plan(
    db_session: Session, monkeypatch
) -> None:
    """Tái hiện sự cố thực tế: cont sai định dạng (VSIU23210) phải báo sai, tuyệt đối không lấy VSIU2421578 từ đơn cũ hoặc slot rỗng."""
    from datetime import UTC, date
    from uuid import uuid4

    from sqlalchemy import select

    from src.config.settings import settings
    from src.handlers.carrier_flow_service import CarrierContext, CarrierFlowService
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import (
        BotReply,
        Carrier,
        ContainerJob,
        Customer,
        TransportPlan,
        ZaloGroup,
        ZaloMessage,
    )
    from src.infrastructure.snowflake import snowflake
    from src.infrastructure.zalo_dispatcher import ZaloDispatcher

    tok = uuid4().hex[:8]
    carrier = Carrier(
        id=snowflake.generate(),
        name=f"NX Glued {tok}",
        normalized_name=f"nx glued {tok}",
        is_active=True,
    )
    customer = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"CGL_{tok}",
        name=f"KH Glued {tok}",
        normalized_name=f"kh glued {tok}",
    )
    db_session.add_all([carrier, customer])
    db_session.flush()

    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"grp_src_glued_{tok}",
        name="TMS Nhà xe Glued",
        group_role="SOURCE",
        carrier_id=str(carrier.id),
        send_mode="MANUAL",
        is_test=False,
        is_active=True,
    )
    cust_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"grp_dst_glued_{tok}",
        name="TMS Khách hàng Glued",
        group_role="DESTINATION",
        send_mode="MANUAL",
        is_test=False,
        is_active=True,
    )
    db_session.add_all([src_grp, cust_grp])
    db_session.flush()

    # Kế hoạch thật cho VSIU2421578 + 1 slot đóng LO trống container để kiểm tra Bước J2 không bắt nhầm VSIU23210
    plan_ok = TransportPlan(
        id=snowflake.generate(),
        plan_date=date.today(),
        order_code=f"RO99{tok[:4]}",
        order_type="tra",
        container_no="VSIU2421578",
        carrier_id=carrier.id,
        customer_id=customer.id,
        customer_name=customer.name,
        group_id=cust_grp.zalo_group_id,
    )
    plan_empty_lo = TransportPlan(
        id=snowflake.generate(),
        plan_date=date.today(),
        order_code=f"LO99{tok[:4]}",
        order_type="dong",
        container_no=None,
        carrier_id=carrier.id,
        customer_id=customer.id,
        customer_name=customer.name,
        group_id=cust_grp.zalo_group_id,
    )
    db_session.add_all([plan_ok, plan_empty_lo])
    db_session.flush()

    sent_calls: list[dict] = []
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    monkeypatch.setattr(settings, "GROUP_PROCESS_DELAY_SECONDS", 0)
    monkeypatch.setattr(
        ZaloDispatcher,
        "send_to_group",
        lambda **kw: (sent_calls.append(kw), (True, f"zm_{uuid4().hex[:6]}", None))[1],
    )

    sender_id = f"sender_glued_{tok}"

    # Bước 1: Gửi đơn hợp lệ VSIU2421578 -> tạo đơn gốc hợp lệ
    m1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"zm1_{tok}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender_id,
        sender_name="Vũ Tiến Đạt",
        message_text="Mooc28RM-45678,SdddT0345032001,VũTùngAnh,29C44719VSIU2421578",
        raw_payload={},
        processing_status="QUEUED",
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m1)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m1.id)
    job1 = db_session.scalar(select(ContainerJob).where(ContainerJob.message_id == m1.id))
    assert job1 is not None and job1.container_no == "VSIU2421578"
    assert job1.truck_record is not None
    assert job1.truck_record.trailer_plate == "28RM-456.78"
    assert job1.truck_record.driver_phone == "0345032001"

    # Bước 2: Gửi chuỗi dính liền không dấu phẩy chứa cont thiếu số VSIU23210
    sent_calls.clear()
    m2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"zm2_{tok}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender_id,
        sender_name="Vũ Tiến Đạt",
        message_text="Mooc28RM-45678SdddT0345032001VũTùngAnh29C44719VSIU23210",
        raw_payload={},
        processing_status="QUEUED",
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m2)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m2.id)

    br2 = db_session.scalar(select(BotReply).where(BotReply.message_id == m2.id))
    assert br2 is not None
    assert "VSIU23210" in br2.reply_text
    assert "chưa đúng định dạng" in br2.reply_text.lower()
    assert "VSIU2421578" not in br2.reply_text
    assert "Đã nhận bổ sung" not in br2.reply_text

    # Bước 3: Gửi chuỗi dính liền sai cả moóc 4 số, SĐT 8 số, biển 4 số và cont 5 số
    sent_calls.clear()
    m3 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"zm3_{tok}",
        group_id=src_grp.zalo_group_id,
        sender_id=sender_id,
        sender_name="Vũ Tiến Đạt",
        message_text="Mooc28RM-4578SdddT03450301VũTùngAnh29C4719VSIU23210",
        raw_payload={},
        processing_status="QUEUED",
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m3)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m3.id)

    br3 = db_session.scalar(select(BotReply).where(BotReply.message_id == m3.id))
    assert br3 is not None
    assert "VSIU2421578" not in br3.reply_text
    assert "VSIU23210" in br3.reply_text
    assert "Số container" in br3.reply_text
    assert "Biển số xe đầu kéo" in br3.reply_text
    assert "Biển số rơ-moóc" in br3.reply_text
    assert "SĐT tài xế" in br3.reply_text
    assert "Tên tài xế" not in br3.reply_text  # Đã tách đúng Vũ Tùng Anh
    job3 = db_session.scalar(select(ContainerJob).where(ContainerJob.message_id == m3.id))
    assert job3 is not None and job3.truck_record is not None
    assert job3.truck_record.driver_name == "Vũ Tùng Anh"

    # Đơn gốc VSIU2421578 tuyệt đối không bị ghi đè hay hỏng dữ liệu
    db_session.refresh(job1)
    db_session.refresh(job1.truck_record)
    assert job1.container_no == "VSIU2421578"
    assert job1.truck_record.trailer_plate == "28RM-456.78"
    assert job1.truck_record.driver_phone == "0345032001"

    # Kiểm chứng các dạng mã cont sai khác + Bước J2 + lớp chống AI bịa số cont từ kế hoạch
    for bad_text, expected_bad in [
        ("Mooc28RM-45678SdddT0345032001VũTùngAnh29C44719VSIU232", "VSIU232"),
        ("Xe 29C-447.19 mooc 28RM-456.78 Vũ Tùng Anh 0345032001 cont VSI2321054", "VSI2321054"),
        ("Xe 29C-447.19 mooc 28RM-456.78 Vũ Tùng Anh 0345032001 GAOU27014012", "GAOU27014012"),
        ("Xe 29C-447.19 mooc 28RM-456.78 Vũ Tùng Anh 0345032001 VSIU2321055", "VSIU2321055"),
    ]:
        ln_bad, _, _ = _parse_tier1_and_tier2(db_session, bad_text)
        assert ln_bad.container_no == expected_bad
        assert ln_bad.check_digit_valid is False
        assert ln_bad.validation_status == "INVALID"
        chk = CarrierFlowService.verify_plan_and_carrier(
            db_session,
            ln_bad,
            CarrierContext(source_group=src_grp, numeric_carrier_id=carrier.id),
            customer.id,
        )
        assert chk.matched_plan is None and chk.is_shipping_missing is True

    # Chuỗi dính liền 100% hợp lệ không dấu phẩy vẫn tách đủ 5/5 trường VALID
    ln_full_no_comma, dec_nc, _ = _parse_tier1_and_tier2(
        db_session, "Mooc28RM-45678SdddT0345032001VũTùngAnh29C44719GAOU2701401"
    )
    assert ln_full_no_comma.trailer_plate == "28RM-456.78"
    assert ln_full_no_comma.driver_phone == "0345032001"
    assert ln_full_no_comma.driver_name == "Vũ Tùng Anh"
    assert ln_full_no_comma.truck_plate == "29C-447.19"
    assert ln_full_no_comma.container_no == "GAOU2701401"
    assert ln_full_no_comma.validation_status == "VALID"
    assert dec_nc == "COMPLETE"

    # Kiểm chứng lớp grounding chặn AI tự chép VSIU2421578 từ active_plans khi tin gốc chỉ ghi VSIU23210
    assert (
        ExtractionHandler._is_container_grounded_in_text(
            "VSIU2421578", "Mooc28RM-45678SdddT0345032001VũTùngAnh29C44719VSIU23210"
        )
        is False
    )
    assert (
        ExtractionHandler._is_container_grounded_in_text(
            "GAOU2701401", "Xe 29C-447.19 GAO U 27014O1"
        )
        is True
    )
