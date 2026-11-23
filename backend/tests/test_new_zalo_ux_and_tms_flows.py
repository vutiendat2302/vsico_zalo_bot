"""Kiểm thử toàn diện các tính năng nâng cấp: Precision Regex, Thông báo thân thiện,
Luồng RO/LO kết hợp & Cont lạ, Gom tin 60s + Danh thiếp, Duyệt trực tiếp ĐHVT trên Zalo,
Báo cáo ảnh HTML-to-PNG, Watchdog Zalo OA và API kiểm thử NLP PhoBERT (`vinai/phobert-base-v2`).
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.assistant.service import handle_assistant
from src.config.settings import settings
from src.domain.enums import GroupRole, MessageStatus, ReviewStatus, SendMode
from src.domain.patterns import CONT_REGEX, PHONE_PATTERN, PLATE_REGEX, TRAILER_PLATE_REGEX
from src.domain.rules import compute_iso6346_check_digit
from src.handlers.carrier_flow_service import CarrierFlowService
from src.handlers.dhvt_service import DhvtNotificationService
from src.handlers.extraction_handler import ExtractionHandler
from src.infrastructure.models import (
    BotReply,
    Carrier,
    Customer,
    MessageDraft,
    OutboundMessage,
    ReviewCase,
    TransportPlan,
    User,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher
from src.infrastructure.zalo_watchdog import ZaloOaWatchdog
from src.outbound.report_image_generator import HtmlReportImageGenerator
from src.outbound.templates import OutboundTemplateBuilder
from src.parsing.trip_parser import TripParser
from src.validation.validators import ContainerValidator


def _valid_cont(prefix: str, digits6: str) -> str:
    """Sinh số container chuẩn ISO 6346 hợp lệ cho kịch bản test."""
    chk = compute_iso6346_check_digit(f"{prefix}{digits6}0")
    return f"{prefix}{digits6}{chk}"


def test_precision_regex_patterns_and_edge_cases() -> None:
    """Kiểm chứng Precision Regex: biển số NBSP/rơ-moóc/đuôi thừa, số container ISO và đa SĐT."""
    assert [m.group(0) for m in PLATE_REGEX.finditer("Xe 29C\u00a0447.12 20 tấn")] == ["29C\u00a0447.12"]
    assert [m.group(0) for m in PLATE_REGEX.finditer("15H-012.34 0912345678")] == ["15H-012.34"]
    assert PLATE_REGEX.findall("Mooc 29R-048.02 và 29RM-048.02") == []
    assert [m.group(0) for m in TRAILER_PLATE_REGEX.finditer("Mooc 29R-048.02 và 29RM-048.02")] == [
        "29R-048.02",
        "29RM-048.02",
    ]
    assert PLATE_REGEX.findall("Mã hàng 12 345 678 hoặc 29C-12345.6 hoặc 29C-12345-6 hoặc 00C-12345") == []

    c_ok = _valid_cont("MSCU", "663532")
    assert [m.group(0) for m in CONT_REGEX.finditer(f"Cont {c_ok} và MSCU 663 532 9")] == [c_ok, "MSCU 663 532 9"]
    assert CONT_REGEX.findall("MSCA6635329 MSCU66353290") == []

    assert [m.group(0) for m in PHONE_PATTERN.finditer("SĐT +84 912 345 678 / 0903.123.459 / 0903xxxx59")] == [
        "+84 912 345 678",
        "0903.123.459",
        "0903xxxx59",
    ]
    assert PHONE_PATTERN.findall("Sai 09123456789 và 0912345678.1") == []

    lines = TripParser.parse_message(
        f"Xe 29C-447.12 mooc 29RM-048.02 cont {c_ok} tài xế Nguyễn Văn An 0912345678 / 0987654321"
    )
    assert len(lines) == 1
    assert lines[0].driver_phone == "0912345678 | 0987654321"


def test_friendly_carrier_warning_templates_hide_technical_details() -> None:
    """Thông báo lỗi cho nhà xe phải lịch sự, ngắn gọn, không lộ regex/check digit/DB/gợi ý số đúng."""
    forbidden = ("regex", "check digit", "iso 6346", "database", "gợi ý", "modulo", "sql")

    lines_missing_cont = ContainerValidator.validate_all(
        TripParser.parse_message("Xe 29C-447.12 mooc 29RM-048.02 tài xế Trần Bình 0912345678")
    )
    msg_missing_cont = OutboundTemplateBuilder.build_carrier_warning_reply(lines_missing_cont) or ""
    assert "bổ sung số container" in msg_missing_cont.lower()
    assert not any(tok in msg_missing_cont.lower() for tok in forbidden)

    bad_cont = "MSCU6635320" if str(compute_iso6346_check_digit("MSCU6635320")) != "0" else "MSCU6635321"
    lines_bad_cont = ContainerValidator.validate_all(
        TripParser.parse_message(f"Xe 29C-447.12 mooc 29RM-048.02 cont {bad_cont} tài xế Trần Bình 0912345678")
    )
    msg_bad_cont = OutboundTemplateBuilder.build_carrier_warning_reply(lines_bad_cont) or ""
    assert "số container có thể chưa chính xác" in msg_bad_cont.lower()
    assert not any(tok in msg_bad_cont.lower() for tok in forbidden)

    for txt in (
        OutboundTemplateBuilder.build_clarify_container_reply(),
        OutboundTemplateBuilder.build_unknown_container_carrier_warning("MSCU6635329"),
        OutboundTemplateBuilder.build_combined_lo_confirm_reply(
            container_no="MSCU6635329",
            ro_order_code="RO1001",
            lo_order_code="LO2002",
            truck_plate="29C-447.12",
        ),
    ):
        assert txt.strip()
        assert not any(tok in txt.lower() for tok in forbidden)


def _seed_carrier_and_dhvt_groups(
    db: Session, token: str, send_mode: str
) -> tuple[Carrier, Customer, ZaloGroup, ZaloGroup, User]:
    """Khởi tạo nhóm nhà xe, nhóm ĐHVT và tài khoản ĐHVT phục vụ kiểm thử luồng thật trong SAVEPOINT."""
    carrier = Carrier(
        id=snowflake.generate(),
        name=f"Nhà xe {token}",
        normalized_name=f"nha xe {token}",
        is_active=True,
    )
    customer = Customer(
        id=snowflake.generate(),
        tms_customer_id=int(snowflake.generate() % 100_000_000),
        name=f"Khách hàng {token}",
        normalized_name=f"khach hang {token}",
    )
    db.add_all([carrier, customer])
    db.flush()

    dhvt_group = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"dhvt_grp_{token}",
        name=f"Nhóm ĐHVT {token}",
        group_role="DHVT",
        send_mode=SendMode.AUTO.value,
        is_test=False,
        is_active=True,
    )
    source_group = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"car_grp_{token}",
        name=f"Nhóm Nhà Xe Vận Tải {token}",
        group_role="SOURCE",
        carrier_id=str(carrier.id),
        send_mode=send_mode,
        is_test=False,
        is_active=True,
    )
    db.add_all([dhvt_group, source_group])
    db.flush()

    dhvt_user = User(
        id=snowflake.generate(),
        username=f"dhvt_{token}",
        password_hash="test-hash",
        full_name="Nguyễn Điều Hành",
        role="dhvt",
        is_active=True,
        zalo_user_id=f"zalo_dhvt_{token}",
        zalo_info_id=dhvt_group.id,
    )
    db.add(dhvt_user)
    db.flush()
    return carrier, customer, source_group, dhvt_group, dhvt_user


def test_combined_ro_lo_manual_and_auto_flows(db_session: Session, monkeypatch) -> None:
    """Kiểm tra lệnh kết hợp RO + LO lần 1 cho cả hai chế độ MANUAL và AUTO."""
    from src.handlers import plan_sync_service

    synced_orders: list[str] = []
    sent_calls: list[dict[str, str | None]] = []

    def _fake_sync(db, plan, job, **kwargs):
        synced_orders.append(plan.order_code or str(plan.id))
        plan.tms_sync_status = "SYNCED"
        return True, "ok", None

    def _fake_send(cls, group_id: str, message: str, quote_msg_id: str | None = None, **kwargs):
        sent_calls.append({"group_id": group_id, "message": message, "quote_msg_id": quote_msg_id})
        return True, f"z_comb_{len(sent_calls)}", None

    monkeypatch.setattr(plan_sync_service, "sync_plan_to_tms", _fake_sync)
    monkeypatch.setattr(ZaloDispatcher, "send_to_group", classmethod(_fake_send))
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)

    # --- Nhánh 1: MANUAL -> Báo cả 2 lệnh RO + LO tới nhóm ĐHVT kèm tên nhóm nguồn ---
    tok1 = uuid4().hex[:8]
    carrier1, cust1, src1, dhvt1, _ = _seed_carrier_and_dhvt_groups(db_session, tok1, SendMode.MANUAL.value)

    cont1 = _valid_cont("TCNU", f"11{int(tok1[:4], 16) % 9000 + 1000}")
    today = date.today()
    ro1 = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"RO{tok1[:4].upper()}",
        order_type="RO",
        plan_date=today,
        container_no=cont1,
        carrier_id=carrier1.id,
        customer_id=cust1.id,
    )
    lo1 = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"LO{tok1[:4].upper()}",
        order_type="LO",
        plan_date=today,
        container_no=cont1,
        carrier_id=carrier1.id,
        customer_id=cust1.id,
    )
    db_session.add_all([ro1, lo1])
    db_session.flush()

    msg1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_comb_man_{tok1}",
        group_id=src1.zalo_group_id,
        sender_id=f"tx_{tok1}",
        sender_name="Anh Hùng Nhà Xe",
        message_text=f"Xe 29C-447.12 mooc 29RM-048.02 cont {cont1} lái xe Trần Bình 0912345678",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(msg1)
    db_session.commit()

    ExtractionHandler.process_message_by_id(db_session, msg1.id)
    rc1 = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == msg1.id))
    assert rc1 is not None
    assert rc1.case_type == "COMBINED_RO_LO_REVIEW"
    assert isinstance(rc1.details, dict)
    assert rc1.details.get("ro_order_code") == ro1.order_code
    assert rc1.details.get("lo_order_code") == lo1.order_code

    dhvt_alerts1 = [str(c["message"]) for c in sent_calls if c["group_id"] == dhvt1.zalo_group_id]
    assert any(
        src1.name in txt and ro1.order_code in txt and lo1.order_code in txt
        for txt in dhvt_alerts1
    )

    # --- Nhánh 2: AUTO -> Tự sync RO lên TMS + hỏi nhà xe xác nhận LO -> nhà xe nhắn ok -> sync LO ---
    tok2 = uuid4().hex[:8]
    carrier2, cust2, src2, _dhvt2, _ = _seed_carrier_and_dhvt_groups(db_session, tok2, SendMode.AUTO.value)
    cust_auto_grp2 = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"proxy_cust_auto_{tok2}",
        name="TMS Khách hàng AUTO Proxy",
        group_role="DESTINATION",
        send_mode=SendMode.AUTO.value,
        is_active=True,
        is_test=False,
    )
    db_session.add(cust_auto_grp2)
    db_session.flush()

    cont2 = _valid_cont("MSCU", f"22{int(tok2[:4], 16) % 9000 + 1000}")
    ro2 = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"RO{tok2[:4].upper()}",
        order_type="RO",
        plan_date=today,
        container_no=cont2,
        carrier_id=carrier2.id,
        customer_id=cust2.id,
        group_id=cust_auto_grp2.zalo_group_id,
    )
    lo2 = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"LO{tok2[:4].upper()}",
        order_type="LO",
        plan_date=today,
        container_no=cont2,
        carrier_id=carrier2.id,
        customer_id=cust2.id,
        group_id=cust_auto_grp2.zalo_group_id,
    )
    db_session.add_all([ro2, lo2])
    db_session.flush()

    msg2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_comb_auto_{tok2}",
        group_id=src2.zalo_group_id,
        sender_id=f"tx_{tok2}",
        sender_name="Chị Lan Nhà Xe",
        message_text=f"Xe 15H-012.34 mooc 15R-181.29 cont {cont2} tài xế Lê Minh 0987654321",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(msg2)
    db_session.commit()

    ExtractionHandler.process_message_by_id(db_session, msg2.id)
    assert ro2.order_code in synced_orders
    assert lo2.order_code not in synced_orders

    draft = db_session.scalar(
        select(MessageDraft).where(
            MessageDraft.zalo_info_id == src2.id,
            MessageDraft.entities["kind"].as_string() == "combined_lo_confirm",
            MessageDraft.status == "WAITING_REPLY",
        )
    )
    assert draft is not None
    bot_reply = db_session.scalar(select(BotReply).where(BotReply.message_id == msg2.id))
    assert bot_reply is not None and lo2.order_code in bot_reply.reply_text

    # Nhà xe xác nhận "ok" -> đồng bộ luôn lệnh đóng LO lên TMS
    msg2_ok = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_comb_auto_ok_{tok2}",
        group_id=src2.zalo_group_id,
        sender_id=f"tx_{tok2}",
        sender_name="Chị Lan Nhà Xe",
        message_text="ok",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(msg2_ok)
    db_session.commit()
    handled = handle_assistant(db_session, msg2_ok, src2)
    assert handled is True
    assert lo2.order_code in synced_orders
    db_session.refresh(draft)
    assert draft.status == "FLUSHED"


def test_unknown_container_warns_carrier_and_alerts_dhvt_with_source_group(
    db_session: Session, monkeypatch
) -> None:
    """Số container hợp lệ nhưng không có trong kế hoạch -> cảnh báo nhà xe VÀ báo nhóm ĐHVT ghi rõ nguồn."""
    sent_calls: list[dict[str, str | None]] = []

    def _fake_send(cls, group_id: str, message: str, quote_msg_id: str | None = None, **kwargs):
        sent_calls.append({"group_id": group_id, "message": message, "quote_msg_id": quote_msg_id})
        return True, f"z_unk_{len(sent_calls)}", None

    monkeypatch.setattr(ZaloDispatcher, "send_to_group", classmethod(_fake_send))
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)

    tok = uuid4().hex[:8]
    _, _, src, dhvt, _ = _seed_carrier_and_dhvt_groups(db_session, tok, SendMode.AUTO.value)

    unknown_cont = _valid_cont("HLXU", f"77{int(tok[:4], 16) % 9000 + 1000}")
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_unk_{tok}",
        group_id=src.zalo_group_id,
        sender_id=f"tx_{tok}",
        sender_name="Anh Nam",
        message_text=f"Xe 29C-556.78 mooc 29RM-099.11 cont {unknown_cont} lái xe Phạm Văn Hòa 0911223344",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(msg)
    db_session.commit()

    ExtractionHandler.process_message_by_id(db_session, msg.id)

    carrier_reply = db_session.scalar(select(BotReply).where(BotReply.message_id == msg.id))
    assert carrier_reply is not None
    assert unknown_cont in carrier_reply.reply_text
    assert "kế hoạch" in carrier_reply.reply_text.lower()

    rc = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == msg.id))
    assert rc is not None and rc.case_type == "SHIPPING_NOT_FOUND"

    dhvt_alerts = [str(c["message"]) for c in sent_calls if c["group_id"] == dhvt.zalo_group_id]
    assert any(src.name in txt and unknown_cont in txt for txt in dhvt_alerts)


def test_carrier_60s_debounce_and_contact_card_extraction(db_session: Session) -> None:
    """Kiểm tra gom tin rời rạc 60s kết hợp bóc tách Danh thiếp Zalo (Contact Card)."""
    tok = uuid4().hex[:8]
    carrier, cust, src, _dhvt, _ = _seed_carrier_and_dhvt_groups(db_session, tok, SendMode.MANUAL.value)

    cont = _valid_cont("CMAU", f"33{int(tok[:4], 16) % 9000 + 1000}")
    plan = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"RO{tok[:4].upper()}",
        order_type="RO",
        plan_date=date.today(),
        container_no=cont,
        carrier_id=carrier.id,
        customer_id=cust.id,
    )
    db_session.add(plan)
    db_session.flush()

    # Tin 1: chỉ gửi đầu kéo + moóc (chưa đủ 5 trường, bật enable_debounce=True) -> chờ gom, chưa nhắc thiếu
    m1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_deb1_{tok}",
        group_id=src.zalo_group_id,
        sender_id=f"tx_{tok}",
        sender_name="Nhà xe Gom Tin",
        message_text="Xe 29C-881.22 mooc 29R-055.66",
        message_type="text",
        raw_payload={"enable_debounce": True},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m1)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m1.id)
    db_session.refresh(m1)
    assert db_session.scalar(select(BotReply).where(BotReply.message_id == m1.id)) is None
    assert m1.processing_status == MessageStatus.PROCESSED.value

    card_text = CarrierFlowService.extract_contact_card_text(
        {"contact": {"display_name": "Nguyễn Văn Tài", "phone": "0934567890"}}
    )
    assert card_text and "Nguyễn Văn Tài" in card_text and "0934567890" in card_text

    # Tin 2: gửi Danh thiếp tài xế + số cont trong vòng 60s -> gộp đủ 5 trường và xử lý thành công!
    m2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_deb2_{tok}",
        group_id=src.zalo_group_id,
        sender_id=f"tx_{tok}",
        sender_name="Nhà xe Gom Tin",
        message_text=f"Cont {cont}",
        message_type="contact",
        raw_payload={
            "enable_debounce": True,
            "contact": {"display_name": "Nguyễn Văn Tài", "phone": "0934567890"},
        },
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m2)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m2.id)

    rc = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m2.id))
    assert rc is not None
    assert db_session.scalar(select(BotReply).where(BotReply.message_id == m2.id)) is None


def test_dhvt_direct_zalo_approve_edit_and_reject_with_broadcast(
    db_session: Session, monkeypatch
) -> None:
    """ĐHVT nhắn duyệt/sửa/từ chối trực tiếp trên nhóm Zalo ĐHVT -> cập nhật kế hoạch, thông báo công khai & báo nhà xe."""
    from src.handlers import plan_sync_service

    sent_calls: list[dict[str, str | None]] = []

    def _fake_send(cls, group_id: str, message: str, quote_msg_id: str | None = None, **kwargs):
        sent_calls.append({"group_id": group_id, "message": message, "quote_msg_id": quote_msg_id})
        return True, f"z_dir_{len(sent_calls)}", None

    monkeypatch.setattr(plan_sync_service, "sync_plan_to_tms", lambda *a, **kw: (True, "ok", None))
    monkeypatch.setattr(ZaloDispatcher, "send_to_group", classmethod(_fake_send))
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)

    tok = uuid4().hex[:8]
    carrier, cust, src, dhvt, dhvt_user = _seed_carrier_and_dhvt_groups(db_session, tok, SendMode.MANUAL.value)

    cont = _valid_cont("OOLU", f"44{int(tok[:4], 16) % 9000 + 1000}")
    plan = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"LO{tok[:4].upper()}",
        order_type="LO",
        plan_date=date.today(),
        container_no=cont,
        carrier_id=carrier.id,
        customer_id=cust.id,
    )
    db_session.add(plan)
    db_session.flush()

    m_car = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_car_dir_{tok}",
        group_id=src.zalo_group_id,
        sender_id=f"tx_{tok}",
        sender_name="Nhà xe A",
        message_text=f"Xe 29C-111.22 mooc 29R-111.22 cont {cont} tài xế Vũ Văn An 0912345678",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m_car)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m_car.id)

    rc = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m_car.id))
    assert rc is not None and rc.status == "PENDING"

    # ĐHVT gõ "sửa xe 15H-888.99 duyệt #<id>" ngay trong nhóm Zalo ĐHVT
    m_dhvt = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_dhvt_app_{tok}",
        group_id=dhvt.zalo_group_id,
        sender_id=dhvt_user.zalo_user_id,
        sender_name=dhvt_user.full_name,
        message_text=f"sửa xe 15H-888.99 duyệt #{rc.id}",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m_dhvt)
    db_session.commit()
    sent_calls.clear()
    handled = handle_assistant(db_session, m_dhvt, dhvt)
    assert handled is True

    db_session.refresh(rc)
    db_session.refresh(plan)
    assert rc.status == "APPROVED"
    assert plan.planned_truck_plate == "15H-888.99"

    dhvt_app_msgs = [c for c in sent_calls if c["group_id"] == dhvt.zalo_group_id]
    assert len(dhvt_app_msgs) == 1  # Gộp thành đúng 1 tin nhắn duy nhất trong nhóm ĐHVT
    assert dhvt_user.full_name in str(dhvt_app_msgs[0]["message"])
    assert "đã sửa và duyệt" in str(dhvt_app_msgs[0]["message"]).lower()
    assert any(
        c["group_id"] == src.zalo_group_id
        and ("đã duyệt" in str(c["message"]).lower() or "đã xác nhận" in str(c["message"]).lower())
        for c in sent_calls
    )

    # Tạo thêm 1 ca PENDING để kiểm tra lệnh "từ chối #<id>" -> chỉ gửi đúng 1 tin nhắn duy nhất vào nhóm ĐHVT
    rc2 = ReviewCase(
        id=snowflake.generate(),
        message_id=m_car.id,
        case_type="MANUAL_REVIEW",
        reason="Kiểm tra từ chối trên Zalo",
        details={"source_group_id": src.zalo_group_id, "container_no": cont, "order_code": plan.order_code},
        status="PENDING",
    )
    db_session.add(rc2)
    db_session.commit()

    m_dhvt_rej = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_dhvt_rej_{tok}",
        group_id=dhvt.zalo_group_id,
        sender_id=dhvt_user.zalo_user_id,
        sender_name=dhvt_user.full_name,
        message_text=f"từ chối #{rc2.id} sai số moóc",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m_dhvt_rej)
    db_session.commit()
    sent_calls.clear()
    assert handle_assistant(db_session, m_dhvt_rej, dhvt) is True
    db_session.refresh(rc2)
    assert rc2.status == "REJECTED"
    dhvt_rej_msgs = [c for c in sent_calls if c["group_id"] == dhvt.zalo_group_id]
    assert len(dhvt_rej_msgs) == 1  # Không lặp 2 tin khi ĐHVT từ chối/hủy trên Zalo
    assert "Đã từ chối / hủy yêu cầu" in str(dhvt_rej_msgs[0]["message"])
    assert dhvt_user.full_name in str(dhvt_rej_msgs[0]["message"])


def test_html_report_image_generator_and_zalo_oa_watchdog(api_client: TestClient) -> None:
    """Kiểm tra xuất ảnh báo cáo PNG bằng Headless Chrome và cơ chế cảnh báo/tự phục hồi Zalo OA Watchdog."""
    res = HtmlReportImageGenerator.render_daily_stats_report(
        report_date=date.today().isoformat(),
        total_plans=20,
        load_count=8,
        return_count=12,
        missing_vehicle_count=5,
        region_rows=[("Miền Bắc", 12, 5, 7), ("Miền Nam", 8, 3, 5)],
        province_rows=[("Hải Phòng", 7, 3, 4), ("Bình Dương", 5, 2, 3)],
    )
    assert res.get("ok") is True
    token = res["token"]
    img_path = Path(res["png_path"])
    assert img_path.exists()
    data = img_path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 2000

    r_img = api_client.get(f"/api/public/reports/{token}.png")
    assert r_img.status_code == 200
    assert r_img.headers["content-type"].startswith("image/png")

    wd = ZaloOaWatchdog()
    for _ in range(3):
        wd.record_outbound_result(False, "connect timeout")
    snap_fail = wd.snapshot()
    assert snap_fail["consecutive_send_failures"] == 3
    assert snap_fail["status"] in ("DEGRADED", "DOWN", "OA_SEND_FAILURE")

    wd.record_outbound_result(True)
    snap_ok = wd.snapshot()
    assert snap_ok["consecutive_send_failures"] == 0
    assert snap_ok["status"] == "HEALTHY"

    r_health = api_client.get("/api/health/zalo-oa")
    assert r_health.status_code == 200
    assert "status" in r_health.json()


def test_nlp_analyze_endpoint_uses_real_phobert_transformers(api_client: TestClient) -> None:
    """API `POST /api/sandbox/nlp-analyze` phải chạy thật `vinai/phobert-base-v2` và trả đủ kết quả 3 tầng."""
    cont = _valid_cont("MSCU", "663532")
    resp = api_client.post(
        "/api/sandbox/nlp-analyze",
        json={
            "text": f"Xe 29C\u00a0447.12 mooc 29RM-048.02 cont {cont} lái xe Tịnh Văn Duân 0987369401 / 0912345678",
            "include_plan_resolution": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["tier2_phobert_nlp"]["backend_mode"] == "phobert_transformers_local"
    assert body["tier2_phobert_nlp"]["model_name"] == "vinai/phobert-base-v2"
    assert body["tier1_regex"]["regex_hits"]["containers"] == [cont]
    assert len(body["records"]) == 1
    assert body["records"][0]["driver_phone"] == "0987369401 | 0912345678"


def test_proxy_only_isolation_blocks_all_real_zalo_oa_calls(
    db_session: Session, monkeypatch, proxy_zalo_outbox
) -> None:
    """Khẳng định 100% các hàm ZaloDispatcher chạy qua Proxy Sink và KHÔNG BAO GIỜ mở kết nối tới oa-bridge."""
    import urllib.request

    def _forbid_network(*args, **kwargs):
        raise AssertionError("Không được phép gọi mạng thật tới Zalo OA trong phiên test!")

    monkeypatch.setattr(urllib.request, "urlopen", _forbid_network)
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    monkeypatch.setattr(settings, "ZALO_PROXY_ONLY", True)

    ok1, mid1, err1 = ZaloDispatcher.send_to_group("456c699447faaea4f7eb", "Test text proxy")
    ok2, mid2, err2 = ZaloDispatcher.send_image_to_group(
        "456c699447faaea4f7eb", "https://api.vtdat.com/api/public/reports/demo.png", "Test image proxy"
    )
    ok3, mid3, err3 = ZaloDispatcher.send_to_user("2025593064656318114", "Test user proxy")

    assert ok1 and ok2 and ok3
    assert err1 is None and err2 is None and err3 is None
    assert str(mid1).startswith("proxy_mock_")
    assert str(mid2).startswith("proxy_mock_")
    assert str(mid3).startswith("proxy_mock_")
    assert len(proxy_zalo_outbox) == 3
    assert {item["kind"] for item in proxy_zalo_outbox} == {"group_text", "group_image", "user_text"}


def test_friendly_vsico_messages_and_batched_overdue_notifications(
    db_session: Session, monkeypatch, proxy_zalo_outbox
) -> None:
    """Kiểm chứng chuyển ngữ mã lỗi thô sang mẫu [VSICO] - ... thân thiện và gom nhiều ca quá hạn thành 1 tin duy nhất."""
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    uid = uuid4().hex[:6]
    dhvt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"proxy_dhvt_bat_{uid}",
        name="Nhóm ĐHVT Proxy",
        group_role=GroupRole.DHVT.value,
        send_mode=SendMode.AUTO.value,
        is_active=True,
        is_test=False,
    )
    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"proxy_car_bat_{uid}",
        name="Nhóm Nhà xe Proxy",
        group_role=GroupRole.CARRIER.value,
        send_mode=SendMode.AUTO.value,
        is_active=True,
        is_test=False,
    )
    db_session.add_all([dhvt_grp, src_grp])
    db_session.flush()

    m1 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"msg_bat1_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id="proxy_sender_1",
        sender_name="Vũ Tiến Đạt",
        message_text="Cont VSIU2461380",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.NEEDS_REVIEW.value,
        zalo_sent_at=datetime.now(UTC) - timedelta(hours=2),
    )
    m2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"msg_bat2_{uid}",
        group_id=src_grp.zalo_group_id,
        sender_id="proxy_sender_2",
        sender_name="Vũ Tiến Đạt",
        message_text="Cont SELU4508182",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.NEEDS_REVIEW.value,
        zalo_sent_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db_session.add_all([m1, m2])
    db_session.flush()

    old_created = datetime.now(UTC) - timedelta(hours=2)
    rc1 = ReviewCase(
        id=snowflake.generate(),
        message_id=m1.id,
        case_type="missing_fields",
        reason="MISSING_DRIVER_NAME, AMBIGUOUS_VEHICLE_CONTAINER_MAPPING, Thiếu/sai: Tên tài xế",
        details={"container_no": "VSIU2461380", "reminder_count": 1},
        status=ReviewStatus.PENDING.value,
        created_at=old_created,
    )
    rc2 = ReviewCase(
        id=snowflake.generate(),
        message_id=m2.id,
        case_type="missing_fields",
        reason=(
            "MISSING_TRUCK_PLATE, TRAILER_PLATE_IN_TRUCK_POSITION(29R-301.87), Thiếu/sai: Biển số xe "
            "| Lan 2: MISSING_TRAILER_PLATE, Thiếu/sai: Biển số rơ-moóc "
            "| Lan 3: MISSING_DRIVER_NAME, Thiếu/sai: Tên tài xế "
            "| Lan 4: MISSING_DRIVER_PHONE, Thiếu/sai: SĐT tài xế"
        ),
        details={"container_no": "SELU4508182", "reminder_count": 1, "occurrence_count": 4},
        status=ReviewStatus.PENDING.value,
        created_at=old_created,
    )
    db_session.add_all([rc1, rc2])
    db_session.commit()

    # 1. Kiểm chứng render đơn lẻ đúng mẫu thân thiện, 0 mã kỹ thuật
    single_1 = DhvtNotificationService.render_overdue_review_alert(rc1, remind_count=2, db=db_session)
    assert "[VSICO] - ⚠️ Cần xác nhận thông tin điều xe" in single_1
    assert "📦 Container: VSIU2461380" in single_1
    assert "• Chưa có tên tài xế." in single_1
    assert "• Chưa xác định rõ xe nào tương ứng với container." in single_1
    assert "MISSING_DRIVER_NAME" not in single_1
    assert "AMBIGUOUS_VEHICLE_CONTAINER_MAPPING" not in single_1

    single_2 = DhvtNotificationService.render_overdue_review_alert(rc2, remind_count=2, db=db_session)
    assert "[VSICO] - 🔎 Cần rà soát thông tin vận chuyển" in single_2
    assert "📦 Container: SELU4508182" in single_2
    assert "Qua các lần kiểm tra, hệ thống đã ghi nhận một số thông tin cần đối chiếu:" in single_2
    assert "• Biển số xe đầu kéo chưa hợp lệ." in single_2
    assert "• Biển 29R-301.87 có thể đang được nhập nhầm vào vị trí biển xe đầu kéo." in single_2
    assert "• Chưa có đầy đủ thông tin rơ-moóc, tên và SĐT tài xế." in single_2
    assert "TRAILER_PLATE_IN_TRUCK_POSITION" not in single_2
    assert "Lan 2:" not in single_2

    # 2. Kiểm chứng gom 2 ca quá hạn cùng lúc thành 1 thông báo duy nhất
    batched_txt = DhvtNotificationService.render_batched_overdue_alert(
        [
            {"kind": "review_case", "case_obj": rc1, "remind_count": 2},
            {"kind": "review_case", "case_obj": rc2, "remind_count": 2},
        ],
        db=db_session,
    )
    assert "[VSICO] - ⚠️ Có 2 yêu cầu quá hạn cần kiểm tra" in batched_txt
    assert "VSIU2461380" in batched_txt and "SELU4508182" in batched_txt
    assert "MISSING_" not in batched_txt

    # 3. Kiểm chứng gom nhiều ca cần duyệt phát sinh cùng lúc trong batch_dhvt_alerts -> chỉ phát 1 tin
    proxy_zalo_outbox.clear()
    with DhvtNotificationService.batch_dhvt_alerts(db_session, is_test_msg=False):
        DhvtNotificationService.create_or_merge_review_case(
            db=db_session,
            message_id=m1.id,
            case_type="COMBINED_RO_LO_REVIEW",
            reason="Vỏ DRYU3046369 có cảnh báo cấm ghép (empty_drop); cần ĐHVT duyệt.",
            container_no="DRYU3046369",
            priority="HIGH",
            is_test_msg=False,
            notify_zalo=True,
        )
        DhvtNotificationService.create_or_merge_review_case(
            db=db_session,
            message_id=m2.id,
            case_type="SHIPPING_NOT_FOUND",
            reason="Không tìm thấy kế hoạch cho cont TCNU9876540.",
            container_no="TCNU9876540",
            priority="NORMAL",
            is_test_msg=False,
            notify_zalo=True,
        )
    # Chỉ phát đúng 1 tin nhắn gom nhóm duy nhất và không lộ (empty_drop)
    dhvt_sent = [x for x in proxy_zalo_outbox if x["kind"] == "group_text"]
    assert len(dhvt_sent) == 1
    assert "[VSICO] - ⚠️ Có 2 yêu cầu điều xe cần ĐHVT kiểm tra" in dhvt_sent[0]["message"]
    assert "DRYU3046369" in dhvt_sent[0]["message"] and "TCNU9876540" in dhvt_sent[0]["message"]
    assert "empty_drop" not in dhvt_sent[0]["message"]


def test_dhvt_daily_overview_vs_province_detail_and_combined_png(
    db_session: Session, monkeypatch, proxy_zalo_outbox
) -> None:
    """Kiểm chứng tách biệt hoàn toàn 'thống kê kế hoạch ngày' với 'chi tiết lệnh tỉnh' và ảnh PNG kèm bảng lệnh."""
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    uid = uuid4().hex[:6]
    target_day = date(2026, 12, 28)

    dhvt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"proxy_dhvt_st_{uid}",
        name="Nhóm ĐHVT Stats Proxy",
        group_role=GroupRole.DHVT.value,
        send_mode=SendMode.AUTO.value,
        is_active=True,
        is_test=False,
    )
    db_session.add(dhvt_grp)
    db_session.flush()

    dhvt_user = User(
        id=snowflake.generate(),
        username=f"dhvt_st_{uid}",
        password_hash="h",
        full_name="Vũ Tiến Đạt",
        role="dhvt",
        zalo_user_id=f"u_dhvt_st_{uid}",
        zalo_info_id=dhvt_grp.id,
        is_active=True,
    )
    db_session.add(dhvt_user)

    plans = [
        TransportPlan(
            id=snowflake.generate(),
            tms_order_id=9100001 + int(uid[:4], 16),
            order_code=f"RO17A{uid[:2].upper()}",
            plan_date=target_day,
            order_type="tra",
            container_size="40",
            container_no=_valid_cont("DRYU", "304636"),
            customer_name="ÚT LÀNH",
            province_name="Tỉnh Hưng Yên",
            region=1,
            planned_truck_plate="29H-234.56",
            driver_name="Tùng Anh",
            dispatch_state=3,
        ),
        TransportPlan(
            id=snowflake.generate(),
            tms_order_id=9100002 + int(uid[:4], 16),
            order_code=f"LO17B{uid[:2].upper()}",
            plan_date=target_day,
            order_type="dong",
            container_size="20",
            container_no=None,
            customer_name="MINH PHÚ",
            province_name="Tỉnh Hưng Yên",
            region=1,
            planned_truck_plate=None,
            dispatch_state=0,
        ),
        TransportPlan(
            id=snowflake.generate(),
            tms_order_id=9100003 + int(uid[:4], 16),
            order_code=f"RO17C{uid[:2].upper()}",
            plan_date=target_day,
            order_type="tra",
            container_size="40",
            container_no=_valid_cont("MSCU", "663532"),
            customer_name="CÔNG TY HẢI PHÒNG",
            province_name="Thành phố Hải Phòng",
            region=1,
            planned_truck_plate="15H-012.34",
            driver_name="Lê Văn Minh",
            dispatch_state=1,
        ),
    ]
    db_session.add_all(plans)
    db_session.commit()

    def _ask(text: str) -> str:
        msg = ZaloMessage(
            id=snowflake.generate(),
            zalo_message_id=f"m_st_{uuid4().hex[:8]}",
            group_id=dhvt_grp.zalo_group_id,
            sender_id=dhvt_user.zalo_user_id,
            sender_name="Vũ Tiến Đạt",
            message_text=text,
            message_type="text",
            raw_payload={},
            processing_status=MessageStatus.RECEIVED.value,
            zalo_sent_at=datetime(2026, 12, 28, 9, 0, 0),
        )
        db_session.add(msg)
        db_session.commit()
        assert handle_assistant(db_session, msg, dhvt_grp) is True
        out = db_session.scalar(
            select(OutboundMessage)
            .where(OutboundMessage.target_group_id == dhvt_grp.id)
            .order_by(OutboundMessage.id.desc())
        )
        return out.content if out else ""

    # 1. Thống kê kế hoạch tổng quát ngày 28/12 -> form 📊 + tỷ lệ % đóng/mở + gửi kèm ảnh PNG tổng hợp
    proxy_zalo_outbox.clear()
    ans_overview = _ask("thống kê kế hoạch ngày 28/12")
    assert "[VSICO] - 📊 KẾ HOẠCH VẬN CHUYỂN | 28/12" in ans_overview
    assert "Lệnh đã đóng:" in ans_overview and "Lệnh đang mở:" in ans_overview
    assert "Lệnh trả:" in ans_overview and "Lệnh đóng:" in ans_overview
    assert "tra / 20" not in ans_overview and "dong / 40" not in ans_overview
    img_sent = [x for x in proxy_zalo_outbox if x["kind"] == "group_image"]
    assert len(img_sent) == 1
    assert "Bảng thống kê & danh sách lệnh ngày 28/12" in img_sent[0]["message"]

    # 2. Hỏi chi tiết lệnh của tỉnh Hưng Yên ngày 28/12 -> tách riêng form 📍 CHI TIẾT KẾ HOẠCH HƯNG YÊN + danh sách lệnh của Hưng Yên
    proxy_zalo_outbox.clear()
    ans_hy = _ask("chi tiết lệnh tỉnh Hưng Yên ngày 28/12")
    assert "[VSICO] - 📍 CHI TIẾT KẾ HOẠCH HƯNG YÊN | 28/12" in ans_hy
    assert "Danh sách lệnh trong ngày:" in ans_hy
    assert plans[0].order_code in ans_hy
    assert plans[1].order_code in ans_hy
    assert plans[2].order_code not in ans_hy  # Không trộn lệnh Hải Phòng vào chi tiết Hưng Yên
    prov_img_sent = [x for x in proxy_zalo_outbox if x["kind"] == "group_image"]
    assert len(prov_img_sent) == 1
    assert "Hưng Yên" in prov_img_sent[0]["message"]

    # 3. Kiểm tra ảnh PNG render trực tiếp chứa cả phần thống kê % lẫn bảng chi tiết lệnh
    res_combined = HtmlReportImageGenerator.render_daily_stats_report(
        report_date="2026-11-17",
        total_plans=3,
        load_count=1,
        return_count=2,
        missing_vehicle_count=1,
        assigned_count=2,
        closed_count=2,
        open_count=1,
        region_rows=[("Miền Bắc", 3, 1, 2)],
        province_rows=[("Tỉnh Hưng Yên", 2, 1, 1), ("Thành phố Hải Phòng", 1, 0, 1)],
        trips=[
            {
                "order_code": plans[0].order_code,
                "order_type": "Trả 40'",
                "province": "Hưng Yên",
                "container_no": plans[0].container_no or "",
                "customer": "ÚT LÀNH",
                "carrier_name": "VSICO",
                "vehicle": "29H-234.56 · Tùng Anh",
                "status": "Đã đóng",
            }
        ],
    )
    assert res_combined.get("ok") is True
    assert Path(res_combined["png_path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_manual_group_forces_review_for_combined_ro_lo_and_complete_return_order(
    db_session: Session, monkeypatch, proxy_zalo_outbox
) -> None:
    """Khi nhóm ở chế độ MANUAL (Chờ duyệt): cả lệnh kết hợp (RO+LO) lẫn lệnh trả đủ 4-5 trường đều phải qua ĐHVT duyệt."""
    from src.api import reviews as reviews_api
    from src.handlers import plan_sync_service

    synced_orders: list[str] = []

    def _fake_tms_sync(db, plan, **kwargs):
        synced_orders.append(plan.order_code or str(plan.id))
        plan.tms_sync_status = "SYNCED"
        return "SYNCED"

    monkeypatch.setattr(plan_sync_service, "sync_plan_to_tms", _fake_tms_sync)
    monkeypatch.setattr(reviews_api, "sync_plan_to_tms", _fake_tms_sync)
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)

    tok = uuid4().hex[:8]
    today = date.today()
    carrier_a, cust_a, src_auto, dhvt_grp, dhvt_user = _seed_carrier_and_dhvt_groups(
        db_session, tok, SendMode.AUTO.value
    )
    # Nhóm khách hàng ở trạng thái Chờ duyệt (MANUAL), KHÔNG có RouteMap riêng
    cust_manual_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"proxy_cust_man_{tok}",
        name="TMS Khách Hàng MANUAL Proxy",
        group_role="DESTINATION",
        send_mode=SendMode.MANUAL.value,
        is_active=True,
        is_test=False,
    )
    db_session.add(cust_manual_grp)
    db_session.flush()

    # 1. Lệnh kết hợp RO + LO với nhóm khách MANUAL (nhóm nhà xe AUTO) -> PHẢI vào COMBINED_RO_LO_REVIEW, không tự đẩy TMS
    cont_comb = _valid_cont("DRYU", f"31{int(tok[:4], 16) % 9000 + 1000}")
    ro_comb = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"RO{tok[:4].upper()}M",
        order_type="RO",
        plan_date=today,
        container_no=cont_comb,
        carrier_id=carrier_a.id,
        customer_id=cust_a.id,
        group_id=cust_manual_grp.zalo_group_id,
    )
    lo_comb = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"LO{tok[:4].upper()}M",
        order_type="LO",
        plan_date=today,
        container_no=cont_comb,
        carrier_id=carrier_a.id,
        customer_id=cust_a.id,
        group_id=cust_manual_grp.zalo_group_id,
    )
    db_session.add_all([ro_comb, lo_comb])
    db_session.flush()

    m_comb = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_cman_{tok}",
        group_id=src_auto.zalo_group_id,
        sender_id=f"tx_{tok}",
        sender_name="Nhà xe Auto",
        message_text=f"Xe 29H-234.56 mooc 15R-987.65 cont {cont_comb} tài xế Tùng Anh 0345032001",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m_comb)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m_comb.id)

    db_session.refresh(ro_comb)
    db_session.refresh(lo_comb)
    rc_comb = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m_comb.id))
    assert rc_comb is not None
    assert rc_comb.case_type == "COMBINED_RO_LO_REVIEW"
    assert rc_comb.status == "PENDING"
    assert ro_comb.planned_truck_plate is None  # Chưa ghi trước TransportPlan
    assert lo_comb.planned_truck_plate is None
    assert synced_orders == []  # Tuyệt đối chưa đẩy TMS trước khi ĐHVT duyệt

    # 2. Lệnh trả (RO) độc lập đủ đầy đủ 4 thông tin điều xe + số cont, nhóm khách MANUAL -> VẪN PHẢI DUYỆT
    cont_ro = _valid_cont("TGCU", f"52{int(tok[:4], 16) % 9000 + 1000}")
    ro_single = TransportPlan(
        id=snowflake.generate(),
        tms_order_id=snowflake.generate(),
        order_code=f"RO{tok[:4].upper()}S",
        order_type="RO",
        plan_date=today,
        container_no=cont_ro,
        carrier_id=carrier_a.id,
        customer_id=cust_a.id,
        group_id=cust_manual_grp.zalo_group_id,
    )
    db_session.add(ro_single)
    db_session.flush()

    m_ro = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_rman_{tok}",
        group_id=src_auto.zalo_group_id,
        sender_id=f"tx_{tok}",
        sender_name="Nhà xe Auto",
        message_text=f"Xe 15H-555.66 mooc 15R-555.66 cont {cont_ro} tài xế Nguyễn Hùng 0912345678",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m_ro)
    db_session.commit()
    ExtractionHandler.process_message_by_id(db_session, m_ro.id)

    db_session.refresh(ro_single)
    rc_ro = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m_ro.id))
    assert rc_ro is not None
    assert rc_ro.case_type == "group_manual_review"
    assert rc_ro.status == "PENDING"
    assert ro_single.planned_truck_plate is None  # Tuyệt đối không ghi đè kế hoạch cục bộ trước khi duyệt
    assert synced_orders == []

    # 3. Khi ĐHVT duyệt trực tiếp trên Zalo cho lệnh kết hợp -> đồng bộ cả RO + LO lên TMS và chỉ gửi 1 tin duy nhất
    proxy_zalo_outbox.clear()
    m_app_comb = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_dhvt_app_c_{tok}",
        group_id=dhvt_grp.zalo_group_id,
        sender_id=dhvt_user.zalo_user_id,
        sender_name=dhvt_user.full_name,
        message_text=f"duyệt #{rc_comb.id}",
        message_type="text",
        raw_payload={},
        processing_status=MessageStatus.RECEIVED.value,
        zalo_sent_at=datetime.now(UTC),
    )
    db_session.add(m_app_comb)
    db_session.commit()
    assert handle_assistant(db_session, m_app_comb, dhvt_grp) is True
    db_session.refresh(ro_comb)
    db_session.refresh(lo_comb)
    assert ro_comb.planned_truck_plate == "29H-234.56"
    assert lo_comb.planned_truck_plate == "29H-234.56"
    assert ro_comb.order_code in synced_orders and lo_comb.order_code in synced_orders
    dhvt_msgs_after = [x for x in proxy_zalo_outbox if x["target_id"] == dhvt_grp.zalo_group_id]
    assert len(dhvt_msgs_after) == 1


def test_20s_carrier_group_delay_while_dhvt_replies_immediately(
    api_client: TestClient, db_session: Session, monkeypatch, proxy_zalo_outbox
) -> None:
    """Phương án A (20s im lặng / trần 60s) chỉ áp dụng cho nhóm Nhà xe; nhóm ĐHVT & Khách hàng xử lý và trả lời ngay."""
    from src.infrastructure.fifo_queue import fifo_queue

    monkeypatch.setattr(settings, "GROUP_PROCESS_DELAY_SECONDS", 20)
    monkeypatch.setattr(settings, "GROUP_PROCESS_MAX_WAIT_SECONDS", 60)
    monkeypatch.setattr(settings, "CARRIER_DEBOUNCE_SECONDS", 20)
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)

    tok = uuid4().hex[:8]
    carrier, _cust, src_grp, dhvt_grp, dhvt_user = _seed_carrier_and_dhvt_groups(
        db_session, tok, SendMode.MANUAL.value
    )
    cust_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"proxy_cust_delay_{tok}",
        name="Khách Hàng Trả Lời Ngay",
        group_role="DESTINATION",
        send_mode=SendMode.AUTO.value,
        is_active=True,
        is_test=False,
    )
    db_session.add(cust_grp)
    db_session.commit()

    # 1. Gửi tin vào cả 3 nhóm (ĐHVT, Nhà xe, Khách hàng) -> sau khi drain:
    #    - Nhóm ĐHVT và Khách hàng xử lý + trả lời LUÔN (0 đợi)
    #    - Riêng nhóm Nhà xe PHẢI đợi đủ 20s (giữ QUEUED)
    r_dhvt = api_client.post(
        "/webhook",
        json={
            "msg_id": f"m_delay_dhvt_1_{tok}",
            "group_id": dhvt_grp.zalo_group_id,
            "sender_id": dhvt_user.zalo_user_id,
            "sender_name": dhvt_user.full_name,
            "message_text": "thống kê kế hoạch hôm nay",
            "is_test": True,
        },
    )
    r_car = api_client.post(
        "/webhook",
        json={
            "msg_id": f"m_delay_car_1_{tok}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": f"tx_{tok}",
            "sender_name": "Nhà xe Delay",
            "message_text": "Xe 29C-447.12 mooc 29RM-048.02",
            "is_test": True,
        },
    )
    r_cust = api_client.post(
        "/webhook",
        json={
            "msg_id": f"m_delay_cust_1_{tok}",
            "group_id": cust_grp.zalo_group_id,
            "sender_id": f"kh_{tok}",
            "sender_name": "Khách Hàng Trả Lời Ngay",
            "message_text": "Hôm nay có những chuyến nào?",
            "is_test": True,
        },
    )
    assert r_dhvt.status_code == 200 and r_car.status_code == 200 and r_cust.status_code == 200
    assert r_car.json()["group_process_delay_seconds"] == 20

    # UI poll GET /api/messages hoặc FIFO drain chạy ngay:
    # -> ĐHVT & Khách hàng ĐƯỢC XỬ LÝ NGAY, còn Nhà xe VẪN GIỮ QUEUED!
    api_client.get("/api/messages")
    m_dhvt_1 = db_session.get(ZaloMessage, int(r_dhvt.json()["record_id"]))
    m_car_1 = db_session.get(ZaloMessage, int(r_car.json()["record_id"]))
    m_cust_1 = db_session.get(ZaloMessage, int(r_cust.json()["record_id"]))
    assert m_dhvt_1.processing_status == "PROCESSED"
    assert m_cust_1.processing_status == "PROCESSED"
    assert m_car_1.processing_status == "QUEUED"
    assert not [x for x in proxy_zalo_outbox if x["target_id"] == src_grp.zalo_group_id]

    # 2. Kiểm chứng Phương án A cho nhóm Nhà xe (20s im lặng / trần 60s):
    # Tin 1 của Nhà xe đã cũ 25s, NHƯNG tin 2 mới gửi cách đây 8s (< 20s) -> vẫn phải đợi tiếp!
    now_local = datetime.now()
    m_car_1.received_at = now_local - timedelta(seconds=25)
    m_car_1.created_at = now_local - timedelta(seconds=25)
    db_session.commit()

    cont_c = _valid_cont("MSCU", f"81{int(tok[:4], 16) % 9000 + 1000}")
    db_session.add(
        TransportPlan(
            id=snowflake.generate(),
            tms_order_id=snowflake.generate(),
            order_code=f"LO{tok[:4].upper()}D",
            order_type="LO",
            plan_date=date.today(),
            container_no=cont_c,
            carrier_id=carrier.id,
        )
    )
    m_car_2 = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"m_delay_car_2_{tok}",
        group_id=src_grp.zalo_group_id,
        sender_id=f"tx_{tok}",
        sender_name="Nhà xe Delay",
        message_text=f"Cont {cont_c}",
        message_type="text",
        raw_payload={"is_test": True},
        processing_status=MessageStatus.QUEUED.value,
        received_at=now_local - timedelta(seconds=8),
        created_at=now_local - timedelta(seconds=8),
        zalo_sent_at=datetime.now(UTC) - timedelta(seconds=8),
    )
    db_session.add(m_car_2)
    db_session.commit()

    drained_mid = fifo_queue.drain_fifo(db_session)
    assert m_car_1.id not in drained_mid and m_car_2.id not in drained_mid
    db_session.refresh(m_car_1)
    db_session.refresh(m_car_2)
    assert m_car_1.processing_status == "QUEUED" and m_car_2.processing_status == "QUEUED"

    # 3. Kiểm chứng trần tối đa 60s: nếu tin 1 đã chờ >= 62s dù tin 2 mới cách đây 8s -> vẫn mở khóa xử lý ngay!
    m_car_1.received_at = now_local - timedelta(seconds=62)
    m_car_1.created_at = now_local - timedelta(seconds=62)
    db_session.commit()

    car_ready = fifo_queue.drain_fifo(db_session)
    assert m_car_1.id in car_ready and m_car_2.id in car_ready
    db_session.refresh(m_car_2)
    # Đã gộp 2 mảnh và nhắc thiếu ngay (không chờ thêm lần 2)
    car_warn = db_session.scalar(select(BotReply).where(BotReply.message_id == m_car_2.id))
    assert car_warn is not None
    assert "tài xế" in car_warn.reply_text.lower()



