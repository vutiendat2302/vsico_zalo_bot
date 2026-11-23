"""Kiểm thử intent, phân quyền và xác nhận trợ lý; không gọi Zalo/LLM thật."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.assistant.intent_router import route_local
from src.assistant.schemas import ToolCall
from src.assistant.scope_resolver import resolve_scope
from src.assistant.service import handle_assistant
from src.assistant.tool_registry import execute
from src.config.settings import settings
from src.infrastructure.models import (
    Carrier,
    Customer,
    MessageDraft,
    OutboundMessage,
    ReviewCase,
    RouteMap,
    TransportPlan,
    Vehicle,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake

REFERENCE = datetime(2026, 11, 9, 17, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "role,text,intent",
    [
        ("CUSTOMER", "Ngày mai có những chuyến nào?", "customer_list_trips_by_date"),
        ("CUSTOMER", "Cont GAOU7821312 xe nào chở?", "customer_get_trip_detail"),
        ("CUSTOMER", "Xin số tài xế xe 29C-445.41", "customer_get_vehicle_driver"),
        ("CUSTOMER", "Booking B26110332 có mấy xe?", "customer_query_schedule"),
        ("CUSTOMER", "Tổng hợp lịch hôm nay", "customer_get_summary"),
        ("CUSTOMER", "Hủy chuyến LO2447", "customer_create_change_request"),
        ("CUSTOMER", "Ca #123 duyệt chưa?", "customer_get_request_status"),
        ("CARRIER", "Hôm nay bên anh có mấy chuyến?", "carrier_list_plans_by_date"),
        ("CARRIER", "Lệnh nào thiếu cont/chì?", "carrier_list_incomplete_plans"),
        ("CARRIER", "LO2447 mấy giờ?", "carrier_get_order_detail"),
        ("CARRIER", "Xe 447.22 chạy chuyến nào?", "carrier_get_vehicle_schedule"),
        ("CARRIER", "LO2447 đổi sang 29C-447.22 tài Nam", "carrier_request_vehicle_update"),
        ("CARRIER", "LO2447 bổ sung chì 9988", "carrier_supplement_trip"),
        ("CARRIER", "Hủy chuyến RO2846", "carrier_report_issue_or_cancel"),
        ("CARRIER", "Xe 15C-066.95 tài Hùng 0903123459 cont GAOU7821312", "REPORT_DISPATCH"),
        (
            "CARRIER",
            "Cont này xe 15C-12345 chạy đúng không, nếu chưa có chì cho bổ sung chì 9988",
            "MIXED",
        ),
        ("DHVT", "Hôm nay cân đối vỏ thế nào?", "dhvt_get_daily_overview"),
        ("DHVT", "Xe nào trùng chuyến?", "dhvt_detect_duplicate_vehicles"),
        ("DHVT", "Có vỏ nào cảnh báo hạ rỗng?", "dhvt_get_container_warnings"),
        ("DHVT", "Hôm nay có gì cần xử lý gấp?", "dhvt_get_priority_digest"),
        ("DHVT", "Tại sao ca #123 cần duyệt?", "dhvt_explain_review_case"),
        ("DHVT", "Nếu hủy lệnh LO2447 thì ảnh hưởng gì?", "dhvt_analyze_change_impact"),
        ("DHVT", "Chuyến LO2447 đã đổi những gì?", "dhvt_get_audit_timeline"),
        ("DHVT", "Hôm nay tỷ lệ dùng LLM?", "dhvt_get_bot_performance"),
        ("DHVT", "Duyệt ca #123", "dhvt_direct_review_action"),
        ("DHVT", "ok", "dhvt_direct_review_action"),
        ("CUSTOMER", "Xe tới km nào?", "UNSUPPORTED"),
    ],
)
def test_intent_examples(role, text, intent):
    """Các câu vận hành thường gặp được phân loại local, không tốn LLM."""
    assert route_local(text, role, REFERENCE).intent == intent


def test_dates_use_original_message_timezone():
    """Tin UTC tối đã sang ngày Việt Nam, không phụ thuộc giờ worker xử lý."""
    assert route_local("Ngày mai mấy chuyến?", "CUSTOMER", REFERENCE).entities.plan_date == date(
        2026, 11, 11
    )
    assert route_local("Ngày 15/11 mấy chuyến?", "CUSTOMER", REFERENCE).entities.plan_date == date(
        2026, 11, 15
    )
    assert route_local("Ngày 31/02 mấy chuyến?", "CUSTOMER", REFERENCE).needs_clarification


@pytest.fixture
def assistant_env(db_session, monkeypatch):
    """Tạo hai phạm vi khách/nhà xe tách biệt trong SAVEPOINT, tắt mạng ngoài."""
    from src.infrastructure.ai_service_client import AIServiceClient

    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", False)
    monkeypatch.setattr(AIServiceClient, "assistant_intent", lambda *a, **kw: None)
    token = uuid4().hex
    groups, plans = [], []
    for i in range(2):
        carrier = Carrier(
            id=snowflake.generate(),
            name=f"Carrier {token} {i}",
            normalized_name=f"carrier {token} {i}",
            is_active=True,
        )
        customer = Customer(
            id=snowflake.generate(),
            tms_customer_id=f"AST_{token}_{i}",
            name=f"Customer {token} {i}",
            normalized_name=f"customer {token} {i}",
        )
        db_session.add_all([carrier, customer])
        db_session.flush()
        car = ZaloGroup(
            id=snowflake.generate(),
            zalo_group_id=f"assistant-car-{token}-{i}",
            name="Nhà xe",
            group_role="SOURCE",
            carrier_id=str(carrier.id),
            is_test=True,
            is_active=True,
        )
        cust = ZaloGroup(
            id=snowflake.generate(),
            zalo_group_id=f"assistant-cust-{token}-{i}",
            name="Khách",
            group_role="DESTINATION",
            is_test=True,
            is_active=True,
        )
        db_session.add_all([car, cust])
        db_session.flush()
        db_session.add(
            RouteMap(
                id=snowflake.generate(),
                customer_id=customer.id,
                zalo_group_id=cust.id,
                is_active=True,
            )
        )
        plan = TransportPlan(
            id=snowflake.generate(),
            carrier_id=carrier.id,
            customer_id=customer.id,
            customer_name=customer.name,
            plan_date=date(2026, 11, 10),
            order_type="dong",
            order_code=f"LO{8200 + i}",
            planned_truck_plate=f"29C-44{i}.22",
            version=1,
            group_id="b0301d81c0ee29b070ff",
        )
        db_session.add(plan)
        db_session.add(
            Vehicle(
                id=snowflake.generate(),
                tms_vehicle_id=snowflake.generate(),
                carrier_id=carrier.id,
                plate_no=f"29C-55{i}.22",
                vehicle_type=1,
                is_active=True,
            )
        )
        groups.append((car, cust))
        plans.append(plan)
    db_session.flush()
    return groups, plans


def send(db, group, text, sender="sender", quote=None):
    """Chạy bộ điều phối trên tin test và đọc phản hồi đã lưu trong outbox."""
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=uuid4().hex,
        group_id=group.zalo_group_id,
        sender_id=sender,
        quote_msg_id=quote,
        message_text=text,
        raw_payload={},
        created_at=REFERENCE,
        zalo_sent_at=REFERENCE,
    )
    db.add(msg)
    db.flush()
    handled = handle_assistant(db, msg, group)
    outbound = db.scalar(
        select(OutboundMessage)
        .where(OutboundMessage.target_group_id == group.id)
        .order_by(OutboundMessage.id.desc())
    )
    return msg, outbound.content if outbound and handled else None


def test_customer_cannot_probe_other_customer(db_session, assistant_env):
    """Ngoài phạm vi và không tồn tại phải có phản hồi giống nhau."""
    groups, _plans = assistant_env
    _, outside = send(db_session, groups[0][1], "LO8201 xe nào chở?")
    _, absent = send(db_session, groups[0][1], "LO9999 xe nào chở?")
    assert outside == absent
    _, own = send(db_session, groups[0][1], "LO8200 xe nào chở?")
    assert "29C-440.22" in own and "29C-441.22" not in own


def test_carrier_cannot_see_unassigned_or_other_carrier(db_session, assistant_env):
    """Dòng chưa gán nhà xe không biến thành lệnh mở chung."""
    groups, plans = assistant_env
    plans[0].carrier_id = None
    db_session.flush()
    _, text = send(db_session, groups[0][0], "Hôm nay mấy chuyến?")
    assert "LO8200" not in text and "LO8201" not in text


def test_customer_fallback_to_plan_group_id_when_missing_route_map(db_session, assistant_env):
    """Khi chưa có RouteMap, nhóm khách chỉ xem được kế hoạch khớp transport_plans.group_id."""
    groups, plans = assistant_env
    for route in db_session.scalars(
        select(RouteMap).where(RouteMap.zalo_group_id == groups[0][1].id)
    ).all():
        route.is_active = False
    plans[0].group_id = "other_group_id"
    plans[1].group_id = groups[0][1].zalo_group_id
    db_session.flush()
    _, text_own = send(db_session, groups[0][1], "LO8201 xe nào chở?")
    _, text_other = send(db_session, groups[0][1], "LO8200 xe nào chở?")
    assert "29C-441.22" in text_own
    assert "29C-441.11" not in text_other


def test_two_step_change_sender_version_and_replay(db_session, assistant_env):
    """Chỉ xác nhận chính người gửi; xác nhận lặp không tăng version."""
    groups, plans = assistant_env
    group, plan = groups[0][0], plans[0]
    msg, preview = send(db_session, group, "LO8200 đổi sang 29C-550.22")
    draft = db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == msg.id))
    assert draft is not None and "Chưa ghi" in preview and plan.version == 1
    send(db_session, group, f"xác nhận #{draft.id}", sender="another")
    assert plan.version == 1
    send(db_session, group, f"xác nhận #{draft.id}")
    assert (
        plan.version == 2
        and plan.planned_truck_plate == "29C-550.22"
        and plan.tms_sync_status == "PENDING"
    )
    send(db_session, group, f"xác nhận #{draft.id}")
    assert plan.version == 2


def test_stale_confirmation_does_not_overwrite(db_session, assistant_env):
    """Phiên bản mới từ Web/TMS làm hết hiệu lực xác nhận cũ."""
    groups, plans = assistant_env
    msg, _ = send(db_session, groups[0][0], "LO8200 đổi sang 29C-550.22")
    draft = db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == msg.id))
    plans[0].version += 1
    db_session.flush()
    _, text = send(db_session, groups[0][0], f"xác nhận #{draft.id}")
    assert "đã thay đổi" in text and plans[0].planned_truck_plate == "29C-440.22"


def test_expired_confirmation_and_multiple_drafts(db_session, assistant_env):
    """Hết hạn hoặc nhiều đề xuất thì không ghép mù lời xác nhận."""
    groups, plans = assistant_env
    msg, _ = send(db_session, groups[0][0], "LO8200 đổi sang 29C-550.22")
    first = db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == msg.id))
    send(db_session, groups[0][0], "LO8200 đổi sang 29C-550.22")
    _, text = send(db_session, groups[0][0], "Đúng")
    assert "duy nhất" in text and plans[0].version == 1
    first.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()
    send(db_session, groups[0][0], f"xác nhận #{first.id}")
    assert first.status == "EXPIRED" and plans[0].version == 1


def test_customer_change_request_and_cross_group_case(db_session, assistant_env):
    """Khách tạo ca chứ không đổi kế hoạch; nhóm khác không đọc được ca."""
    groups, plans = assistant_env
    msg, _text = send(db_session, groups[0][1], "Hủy chuyến LO8200")
    case = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == msg.id))
    assert case is not None and plans[0].version == 1 and "HIGH" == case.details["priority"]
    _, other = send(db_session, groups[1][1], f"Ca #{case.id} xong chưa?")
    assert str(case.id) not in other


def test_registry_rejects_role_and_llm_write(db_session, assistant_env):
    """Bỏ qua router cũng không vượt được kiểm quyền registry."""
    groups, _plans = assistant_env
    msg, _ = send(db_session, groups[0][0], "Hướng dẫn")
    scope = resolve_scope(db_session, groups[0][0], msg)
    with pytest.raises(PermissionError):
        execute(db_session, scope, ToolCall(intent="dhvt_get_priority_digest", confidence=1), msg)
    with pytest.raises(PermissionError):
        execute(
            db_session,
            scope,
            ToolCall(intent="carrier_request_vehicle_update", confidence=1, route_source="llm"),
            msg,
        )


def test_replayed_message_does_not_duplicate_reply(db_session, assistant_env):
    """Worker retry cùng message không tạo thêm tin trả lời hoặc tác vụ."""
    groups, _plans = assistant_env
    msg, _ = send(db_session, groups[0][0], "Hôm nay mấy chuyến?")
    before = len(
        db_session.scalars(
            select(OutboundMessage).where(OutboundMessage.target_group_id == groups[0][0].id)
        ).all()
    )
    assert handle_assistant(db_session, msg, groups[0][0])
    after = len(
        db_session.scalars(
            select(OutboundMessage).where(OutboundMessage.target_group_id == groups[0][0].id)
        ).all()
    )
    assert before == after


def dhvt_identity(db):
    """Tạo danh tính ĐHVT hợp lệ gắn đúng nhóm nội bộ."""
    from src.infrastructure.models import User

    group = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=uuid4().hex,
        name="ĐHVT test",
        group_role="DHVT",
        is_active=True,
        is_test=True,
    )
    db.add(group)
    db.flush()
    user = User(
        id=snowflake.generate(),
        username=uuid4().hex,
        password_hash="test-only",
        full_name="Điều hành test",
        role="DHVT",
        is_active=True,
        zalo_user_id="sender",
        zalo_info_id=group.id,
    )
    db.add(user)
    db.flush()
    return group, user


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hôm nay bao nhiêu chuyến?", "KẾ HOẠCH VẬN CHUYỂN"),
        ("Chuyến nào chưa có xe?", "Kế hoạch"),
        ("LO8200 hiện thế nào?", "LO8200"),
        ("Xe 29C-440.22 chạy chuyến nào?", "29C-440.22"),
        ("Có xe nào trùng chuyến không?", "trùng"),
        ("Có vỏ nào hạ rỗng?", "phạm vi"),
        ("Có cont nào chưa khớp?", "kiểm tra"),
        ("Có tin gửi khách thất bại?", "đồng bộ"),
        ("Ca chờ", "hàng chờ"),
        ("Tại sao ca #1 cần duyệt?", "phạm vi"),
        ("Nếu hủy lệnh LO8200 thì ảnh hưởng gì?", "chỉ đọc"),
        ("LO8200 đã đổi những gì?", "phạm vi"),
        ("Hôm nay tỷ lệ dùng LLM?", "lượt"),
        ("Duyệt ca #1", "Chưa xác định được ca"),
    ],
)
def test_dhvt_conversations_are_read_only(db_session, assistant_env, text, expected):
    """Chạy hội thoại qua scope, tool, DB và outbox; ĐHVT không ghi kế hoạch."""
    group, _user = dhvt_identity(db_session)
    _, reply = send(db_session, group, text)
    assert expected in reply
    assert all(p.version == 1 for p in assistant_env[1])


def test_dhvt_wrong_role_or_group_is_denied(db_session, assistant_env):
    """Có zalo_user_id nhưng sai role hoặc sai nhóm vẫn không được tra cứu."""
    group, user = dhvt_identity(db_session)
    user.role = "CUSTOMER"
    db_session.flush()
    _, reply = send(db_session, group, "LO8200 hiện thế nào?")
    assert "chưa được gắn" in reply and "29C-440.22" not in reply
    user.role = "DHVT"
    user.zalo_info_id = assistant_env[0][0][0].id
    db_session.flush()
    _, reply = send(db_session, group, "LO8200 hiện thế nào?")
    assert "chưa được gắn" in reply


def test_carrier_fallback_to_group_id_and_dhvt_unlinked_sender(db_session, assistant_env):
    """Nhà xe chưa gắn carrier_id dùng group_id kế hoạch; ĐHVT chưa gắn user vẫn tra được."""
    groups, plans = assistant_env
    carrier_group = groups[0][0]
    carrier_group.carrier_id = None
    plans[0].group_id = carrier_group.zalo_group_id
    plans[1].group_id = "other_carrier_group"
    db_session.flush()
    _, c_own = send(db_session, carrier_group, "LO8200 mấy giờ?")
    _, c_other = send(db_session, carrier_group, "LO8201 mấy giờ?")
    assert "LO8200" in c_own and "LO8201" not in c_other

    dhvt_group, _user = dhvt_identity(db_session)
    _, dhvt_reply = send(db_session, dhvt_group, "LO8200 hiện thế nào?", sender="oa_unlinked_staff")
    assert "29C-440.22" in dhvt_reply


def test_customer_query_multi_identifiers_across_dates(db_session, assistant_env):
    """Tra Booking và Cont không ghi ngày vẫn tìm được trên ngày khác và trả về cả hai."""
    from datetime import timedelta

    groups, plans = assistant_env
    for route in db_session.scalars(
        select(RouteMap).where(RouteMap.zalo_group_id == groups[0][1].id)
    ).all():
        route.is_active = False
    other_day = REFERENCE.date() - timedelta(days=5)
    plans[0].group_id = groups[0][1].zalo_group_id
    plans[0].plan_date = other_day
    plans[0].booking_no = "B26110492"
    plans[0].container_no = None
    plans[1].group_id = groups[0][1].zalo_group_id
    plans[1].plan_date = other_day
    plans[1].container_no = "TGCU5311133"
    plans[1].booking_no = None
    db_session.flush()
    _, reply = send(
        db_session,
        groups[0][1],
        "Booking B26110492 có mấy xe? Cont TGCU5311133 xe nào chở?",
    )
    assert "Booking B26110492: tổng 1 lệnh" in reply
    assert "TGCU5311133" in reply and "LO8201" in reply
    assert "Kế hoạch None" not in reply
    _, count_only = send(db_session, groups[0][1], "Booking B26110492 có mấy xe?")
    assert "Booking B26110492: tổng 1 lệnh" in count_only and "1. " not in count_only
    from src.assistant.response_formatter import format_plans

    long_plans = []
    for i in range(20):
        p = TransportPlan(
            id=snowflake.generate(),
            plan_date=other_day,
            order_code=f"LO9{i:03d}",
            order_type="dong",
            warehouse_name="KHO CONG TY CO PHAN THUONG MAI VA VAN TAI QUOC TE SIEU DAI " * 2,
            required_time="15:00",
        )
        long_plans.append(p)
    capped = format_plans(long_plans, "Kế hoạch tra cứu:", detail=True)
    assert len(capped.text) <= 1900 and "Còn kết quả khác" in capped.text


def test_sent_or_queued_trip_creates_review_after_confirmation(db_session, assistant_env):
    """Có thông báo đang gửi/đã gửi thì không tự sửa kế hoạch sau xác nhận."""
    from src.assistant.tools_carrier import create_job_snapshot
    from src.infrastructure.models import OutboundMessageItem

    groups, plans = assistant_env
    msg, _ = send(db_session, groups[0][0], "Hướng dẫn")
    job = create_job_snapshot(db_session, msg, plans[0], {})
    outbound = OutboundMessage(
        id=snowflake.generate(),
        target_group_id=groups[0][1].id,
        order_type="dong",
        message_kind="new",
        content="Test",
        idempotency_key=uuid4().hex,
        status="SENT",
    )
    db_session.add(outbound)
    db_session.flush()
    db_session.add(OutboundMessageItem(outbound_message_id=outbound.id, container_job_id=job.id))
    db_session.flush()
    proposal, _ = send(db_session, groups[0][0], "LO8200 đổi sang 29C-550.22")
    draft = db_session.scalar(
        select(MessageDraft).where(MessageDraft.first_message_id == proposal.id)
    )
    confirmation, text = send(db_session, groups[0][0], f"xác nhận #{draft.id}")
    case = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == confirmation.id))
    assert case.case_type == "REVIEW_CHANGE_AFTER_SENT" and plans[0].version == 1
    assert case.container_job_id is not None and "chưa bị thay đổi" in text


def test_fill_missing_seal_stays_local_and_queues_customer_notification(db_session, assistant_env):
    """Điền chì hợp lệ tạo outbox, không giả trạng thái đã gửi hoặc đã đồng bộ."""
    from src.domain.rules import compute_iso6346_check_digit

    groups, plans = assistant_env
    plan = plans[0]
    plan.container_no = "MSCU123456" + str(compute_iso6346_check_digit("MSCU1234560"))
    plan.container_size = "40HC"
    plan.planned_trailer_plate = "29R-181.29"
    plan.driver_name = "Tài xế test"
    plan.driver_phone = "0903123459"
    plan.delivery_address = "Kho test"
    db_session.flush()
    _msg, _text = send(db_session, groups[0][0], "LO8200 bổ sung chì TEST123")
    assert plan.seal_no == "TEST123" and plan.version == 2 and plan.tms_sync_status == "PENDING"
    out = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.target_group_id == groups[0][1].id)
    )
    assert out is not None and out.status == "PENDING_SEND"


def test_scope_filters_route_order_type(db_session, assistant_env):
    """Tuyến chỉ nhận lệnh trả không nhìn thấy lệnh đóng cùng khách."""
    groups, _plans = assistant_env
    route = db_session.scalar(select(RouteMap).where(RouteMap.zalo_group_id == groups[0][1].id))
    route.order_type = "RETURN"
    db_session.flush()
    _, reply = send(db_session, groups[0][1], "LO8200 xe nào chở?")
    assert "29C-440.22" not in reply


def test_same_container_different_customer_requests_do_not_merge(db_session, assistant_env):
    """Hai nhóm cùng số cont ở hai chặng không bị gộp hoặc lộ mã ca nhau."""
    groups, plans = assistant_env
    for p in plans:
        p.container_no = "MSCU1234566"
    db_session.flush()
    first, _ = send(db_session, groups[0][1], "Hủy chuyến LO8200")
    second, _ = send(db_session, groups[1][1], "Hủy chuyến LO8201")
    a = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == first.id))
    b = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == second.id))
    assert a.id != b.id and a.details["transport_plan_id"] == str(plans[0].id)


def test_raw_dispatch_cannot_bypass_change_confirmation(db_session, assistant_env):
    """Báo lại bằng câu thường nhưng đổi xe vẫn cần bước xác nhận."""
    from src.domain.rules import compute_iso6346_check_digit

    groups, plans = assistant_env
    plans[0].container_no = "MSCU123456" + str(compute_iso6346_check_digit("MSCU1234560"))
    db_session.flush()
    msg, text = send(db_session, groups[0][0], f"Xe 29C-550.22 cont {plans[0].container_no}")
    draft = db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == msg.id))
    assert draft is not None and plans[0].version == 1 and "Chưa ghi" in text


def test_llm_cannot_override_role_or_scope(db_session, assistant_env, monkeypatch):
    """Đề xuất tool ngoài vai trò từ AI không được thực thi dù confidence cao."""
    from src.infrastructure.ai_service_client import AIServiceClient

    monkeypatch.setattr(
        AIServiceClient,
        "assistant_intent",
        lambda *a, **kw: {
            "call": {
                "intent": "dhvt_get_priority_digest",
                "confidence": 1,
                "entities": {},
                "needs_clarification": False,
            },
            "model_name": "test-only",
        },
    )
    _, text = send(db_session, assistant_env[0][0][1], "Nhờ rà soát giúp chị nhé")
    assert "hàng chờ" not in text and "chưa rõ" in text


def test_quote_confirmation_resolves_outbound_sent_later(db_session, assistant_env):
    """Quote câu hỏi gửi bởi outbox worker vẫn nối được đúng nháp, không cần gửi ngay."""
    groups, plans = assistant_env
    msg, _ = send(db_session, groups[0][0], "LO8200 đổi sang 29C-550.22")
    draft = db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == msg.id))
    out = db_session.get(OutboundMessage, int(draft.entities["prompt_outbound_id"]))
    out.zalo_message_id = uuid4().hex
    out.status = "SENT"
    db_session.flush()
    send(db_session, groups[0][0], "Đúng", quote=out.zalo_message_id)
    assert plans[0].version == 2


def test_pending_change_question_does_not_start_another_change(db_session, assistant_env):
    """Hỏi tiến độ đổi xe là truy vấn, không tạo thêm nháp sửa xe."""
    groups, _plans = assistant_env
    msg, reply = send(db_session, groups[0][0], "Còn yêu cầu đổi xe nào chưa xong không?")
    assert "đang chờ" in reply
    assert (
        db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == msg.id))
        is None
    )


def test_review_proposal_requires_web_auth_and_current_version(
    api_client, db_session, assistant_env
):
    """API duyệt đề xuất từ trợ lý chặn vô danh và phiên bản cũ."""
    from src.infrastructure.security import create_access_token

    groups, plans = assistant_env
    message, _ = send(db_session, groups[0][1], "Hủy chuyến LO8200")
    case = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == message.id))
    assert api_client.post(f"/api/reviews/{case.id}/approve").status_code == 403
    _group, user = dhvt_identity(db_session)
    token = create_access_token({"sub": str(user.id), "username": user.username, "role": user.role})
    plans[0].version += 1
    db_session.flush()
    response = api_client.post(
        f"/api/reviews/{case.id}/approve", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 409 and case.status == "PENDING"


def test_timeline_includes_actual_bot_reply_and_extraction(db_session, assistant_env):
    """Dòng thời gian tổng hợp các bản ghi có liên kết thật với kế hoạch."""
    from src.assistant.tools_carrier import create_job_snapshot
    from src.infrastructure.models import BotReply, ExtractionRun

    groups, plans = assistant_env
    message, _ = send(db_session, groups[0][0], "Hướng dẫn")
    create_job_snapshot(db_session, message, plans[0], {})
    db_session.add(
        BotReply(
            id=snowflake.generate(),
            message_id=message.id,
            sender_id="sender",
            reply_text="Cần bổ sung chì",
            status="PENDING",
            fix_deadline=datetime.now() + timedelta(minutes=30),
        )
    )
    db_session.add(
        ExtractionRun(
            id=snowflake.generate(),
            message_id=message.id,
            model_name="rule-test",
            prompt_version="test",
            input_data={},
            output_data={},
            status="SUCCESS",
        )
    )
    db_session.flush()
    group, _user = dhvt_identity(db_session)
    _, reply = send(db_session, group, "LO8200 đã đổi những gì?")
    assert "Cần bổ sung chì" in reply and "rule-test" in reply


def test_customer_cancel_request_approve_notifies_customer_group(
    api_client, db_session, assistant_env, monkeypatch
):
    """Duyệt yêu cầu hủy chuyến từ khách (chưa có ContainerJob, sender test_) vẫn tạo và gửi thông báo về nhóm khách."""
    from sqlalchemy import delete
    from src.infrastructure.models import RouteMap
    from src.infrastructure.security import create_access_token
    from src.infrastructure.zalo_dispatcher import ZaloDispatcher

    groups, plans = assistant_env
    cust_group = groups[0][1]
    cust_group.is_test = False
    plans[0].group_id = cust_group.zalo_group_id
    db_session.execute(delete(RouteMap).where(RouteMap.zalo_group_id == cust_group.id))
    db_session.flush()

    message, _ = send(db_session, cust_group, "Hủy chuyến LO8200")
    message.sender_id = "test_customer_user_01"
    message.zalo_message_id = f"zalo_{uuid4().hex[:8]}"
    db_session.flush()

    case = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == message.id))
    assert case is not None
    assert case.case_type == "CUSTOMER_CHANGE_REQUEST"
    assert case.container_job_id is None

    sent_calls: list[dict] = []

    def _fake_send(**kwargs):
        sent_calls.append(kwargs)
        return True, f"z_out_{uuid4().hex[:6]}", None

    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    monkeypatch.setattr(ZaloDispatcher, "send_to_group", _fake_send)

    _group, user = dhvt_identity(db_session)
    token = create_access_token({"sub": str(user.id), "username": user.username, "role": user.role})
    response = api_client.post(
        f"/api/reviews/{case.id}/approve",
        json={"cancel_reason": "Khách báo hủy lệnh trước giờ đóng hàng"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert len(body["cancel_outbound_ids"]) == 1
    assert plans[0].id in body["updated_plan_ids"]

    db_session.refresh(case)
    db_session.refresh(plans[0])
    assert case.status == "APPROVED"
    assert plans[0].version == 2
    assert "HUY CHUYEN" in (plans[0].notes or "")

    om = db_session.get(OutboundMessage, body["cancel_outbound_ids"][0])
    assert om is not None
    assert om.target_group_id == cust_group.id
    assert om.message_kind == "cancel"
    assert om.status == "SENT"
    assert str(case.id) not in om.content
    assert any(c["group_id"] == cust_group.zalo_group_id for c in sent_calls)


def test_customer_cancel_request_reject_notifies_customer_group_without_snowflake_id(
    api_client, db_session, assistant_env, monkeypatch
):
    """Từ chối yêu cầu hủy/đổi từ khách phải lưu OutboundMessage và gửi Zalo lại cho nhóm khách, không lộ Snowflake ID."""
    from src.infrastructure.security import create_access_token
    from src.infrastructure.zalo_dispatcher import ZaloDispatcher

    groups, plans = assistant_env
    cust_group = groups[0][1]
    cust_group.is_test = False
    db_session.flush()

    message, _ = send(db_session, cust_group, "Hủy chuyến LO8200")
    message.sender_id = "test_customer_user_01"
    message.zalo_message_id = f"zalo_{uuid4().hex[:8]}"
    db_session.flush()

    case = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == message.id))
    assert case is not None

    sent_calls: list[dict] = []

    def _fake_send(**kwargs):
        sent_calls.append(kwargs)
        return True, f"z_rej_{uuid4().hex[:6]}", None

    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    monkeypatch.setattr(ZaloDispatcher, "send_to_group", _fake_send)

    _group, user = dhvt_identity(db_session)
    token = create_access_token({"sub": str(user.id), "username": user.username, "role": user.role})
    response = api_client.post(
        f"/api/reviews/{case.id}/reject",
        json={"reason": "Xe đã vào kho lấy hàng"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"

    db_session.refresh(case)
    assert case.status == "REJECTED"
    rej_ids = (case.resolution or {}).get("reject_outbound_ids") or []
    assert len(rej_ids) == 1
    om = db_session.get(OutboundMessage, rej_ids[0])
    assert om is not None
    assert om.target_group_id == cust_group.id
    assert om.message_kind == "answer"
    assert om.status == "SENT"
    assert "LO8200" in om.content
    assert "Xe đã vào kho lấy hàng" in om.content
    assert str(case.id) not in om.content
    assert str(plans[0].id) not in om.content
    assert any(
        c["group_id"] == cust_group.zalo_group_id and "LO8200" in str(c["message"])
        for c in sent_calls
    )


def test_default_carrier_group_covers_all_carriers_and_unassigned_plans(
    db_session, assistant_env, monkeypatch
):
    """Nhóm nhà xe mặc định (3632c4cbeaa503fb5ab4) xem được lệnh của mọi nhà xe và lệnh chưa gắn nhà xe."""
    assert settings.DEFAULT_CARRIER_GROUP_ID == "3632c4cbeaa503fb5ab4"
    groups, plans = assistant_env
    # Tạo thêm 1 kế hoạch chưa gán carrier_id để mô phỏng dữ liệu kéo TMS ban đầu
    unassigned_plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date(2026, 11, 10),
        order_code="RO9999",
        order_type="tra",
        customer_id=plans[0].customer_id,
        customer_name=plans[0].customer_name,
        warehouse_id=plans[0].warehouse_id,
        warehouse_name=plans[0].warehouse_name,
        carrier_id=None,
        group_id="b0301d81c0ee29b070ff",
    )
    db_session.add(unassigned_plan)
    db_session.flush()

    default_group = db_session.scalar(
        select(ZaloGroup).where(ZaloGroup.zalo_group_id == settings.DEFAULT_CARRIER_GROUP_ID)
    )
    if default_group is None:
        default_group = ZaloGroup(
            id=snowflake.generate(),
            zalo_group_id=settings.DEFAULT_CARRIER_GROUP_ID,
            name="TMS Nhà xe - TEST",
            group_role="SOURCE",
            carrier_id=None,
            send_mode="AUTO",
            is_active=True,
            is_test=False,
        )
        db_session.add(default_group)
    else:
        default_group.group_role = "SOURCE"
        default_group.carrier_id = None
        default_group.is_active = True
    db_session.flush()

    _, reply_all = send(db_session, default_group, "Hôm nay lệnh nào thiếu cont hoặc chưa có chì?")
    assert "LO8200" in reply_all
    assert "LO8201" in reply_all
    assert "RO9999" in reply_all

    # Nhóm nhà xe riêng vẫn bị cách ly đúng phạm vi của riêng mình
    _, reply_scoped = send(db_session, groups[0][0], "Hôm nay lệnh nào thiếu cont hoặc chưa có chì?")
    assert "LO8200" in reply_scoped
    assert "LO8201" not in reply_scoped
    assert "RO9999" not in reply_scoped


def test_carrier_group_resolves_by_tms_carrier_id_and_code(db_session, assistant_env):
    """Nhóm nhà xe có thể liên kết qua carriers.tms_carrier_id hoặc carriers.code bên cạnh Snowflake ID."""
    groups, plans = assistant_env
    car_group = groups[0][0]
    carrier = db_session.get(Carrier, plans[0].carrier_id)
    assert carrier is not None
    carrier.tms_carrier_id = 99887766
    carrier.code = f"CAR_{uuid4().hex[:6]}"
    db_session.flush()

    car_group.carrier_id = str(carrier.tms_carrier_id)
    db_session.flush()
    _, reply_tms = send(db_session, car_group, "LO8200 mấy giờ?")
    assert "LO8200" in reply_tms

    car_group.carrier_id = carrier.code
    db_session.flush()
    _, reply_code = send(db_session, car_group, "LO8200 mấy giờ?")
    assert "LO8200" in reply_code


def test_oa_gmf_mention_quote_confirmation_and_normalizer_group_fallback(
    db_session, assistant_env, monkeypatch
):
    """Nhắc tên [@oa_id] xác nhận + quote tin từ nhóm OA GMF (recipient.id) phải khớp đúng nhóm và chốt đề xuất."""
    from src.infrastructure.fifo_queue import fifo_queue
    from src.ingestion.normalizer import WebhookIngestor

    monkeypatch.setattr(fifo_queue, "enqueue", lambda _mid: None)

    groups, plans = assistant_env
    car_group = groups[0][0]
    msg, _ = send(db_session, car_group, "LO8200 đổi sang 29C-550.22", sender="test_carrier_user_01")
    draft = db_session.scalar(select(MessageDraft).where(MessageDraft.first_message_id == msg.id))
    assert draft is not None
    out = db_session.get(OutboundMessage, int(draft.entities["prompt_outbound_id"]))
    out.zalo_message_id = f"gmf_{uuid4().hex[:10]}"
    out.status = "SENT"
    db_session.flush()

    raw_oa_payload = {
        "app_id": "4565940023054009074",
        "event_name": "user_send_group_text",
        "group_id": "",
        "sender": {"id": "2025593064656318114", "name": "User Zalo"},
        "timestamp": "1794782663206",
        "quote_msg_id": out.zalo_message_id,
        "message": {
            "text": "[@2208036998371849749] xác nhận",
            "msg_id": f"eb_{uuid4().hex[:12]}",
            "quote_msg_id": out.zalo_message_id,
        },
        "raw_payload": {
            "oa_id": "2208036998371849749",
            "event_name": "user_send_group_text",
            "recipient": {"id": car_group.zalo_group_id},
        },
    }
    in_msg, is_dup = WebhookIngestor.ingest_webhook_payload(db_session, raw_oa_payload)
    assert not is_dup
    assert in_msg.group_id == car_group.zalo_group_id

    handled = handle_assistant(db_session, in_msg, car_group)
    assert handled is True
    db_session.refresh(plans[0])
    assert plans[0].version == 2
    assert plans[0].planned_truck_plate == "29C-550.22"


def test_carrier_missing_container_warning_is_dispatched_to_zalo(db_session, monkeypatch):
    """Tin báo xe thiếu container tự động gửi BotReply nhắc nhà xe (không tạo ReviewCase ĐHVT) và tự gộp khi nhà xe bổ sung."""
    from src.domain.rules import compute_iso6346_check_digit
    from src.handlers.extraction_handler import ExtractionHandler
    from src.infrastructure.models import BotReply, Customer, OutboundMessage, ReviewCase, RouteMap, TransportPlan
    from src.infrastructure.zalo_dispatcher import ZaloDispatcher

    cust = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"C_MC_{uuid4().hex[:6]}",
        name="Khách Test Auto Cont",
        normalized_name="khách test auto cont",
        is_active=True,
    )
    car_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"real_car_{uuid4().hex[:8]}",
        name="TMS Nhà xe TEST",
        group_role="SOURCE",
        send_mode="AUTO",
        is_test=False,
        is_active=True,
    )
    cust_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"real_cust_{uuid4().hex[:8]}",
        name="TMS Khách TEST",
        group_role="CUSTOMER",
        send_mode="AUTO",
        is_test=False,
        is_active=True,
    )
    db_session.add_all([cust, car_grp, cust_grp])
    db_session.flush()

    cont_ok = "MSKU123456" + str(compute_iso6346_check_digit("MSKU1234560"))
    db_session.add(
        RouteMap(
            id=snowflake.generate(),
            customer_id=cust.id,
            zalo_group_id=cust_grp.id,
            is_active=True,
        )
    )
    db_session.add(
        TransportPlan(
            id=snowflake.generate(),
            tms_order_id=987654321,
            order_code="RO2744",
            plan_date=REFERENCE.date(),
            order_type="RETURN",
            customer_id=cust.id,
            customer_name=cust.name,
            container_no=cont_ok,
            planned_trailer_plate="15R-017.85",
            seal_no="SL998877",
            group_id=cust_grp.zalo_group_id,
        )
    )
    db_session.flush()

    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"z_{uuid4().hex[:10]}",
        group_id=car_grp.zalo_group_id,
        sender_id="2025593064656318114",
        message_text="| 15F-017.85 | Nguyễn Văn Quyên | 0390687729",
        raw_payload={},
        processing_status="QUEUED",
        created_at=REFERENCE,
        zalo_sent_at=REFERENCE,
    )
    db_session.add(msg)
    db_session.flush()

    sent_calls: list[dict] = []

    def _fake_send(**kwargs):
        sent_calls.append(kwargs)
        return True, f"z_warn_{uuid4().hex[:6]}", None

    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    monkeypatch.setattr(ZaloDispatcher, "send_to_group", _fake_send)

    ExtractionHandler.process_message_by_id(db_session, msg.id)

    reply = db_session.scalar(select(BotReply).where(BotReply.message_id == msg.id))
    assert reply is not None
    assert reply.zalo_msg_id is not None
    assert "số container" in reply.reply_text.lower()
    assert "khách hàng" not in reply.reply_text
    assert db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == msg.id)) is None
    assert any(
        c["group_id"] == car_grp.zalo_group_id and "số container" in str(c["message"]).lower()
        for c in sent_calls
    )

    # Nhà xe bổ sung số container (kể cả không quote) -> tự gộp và gửi thông báo khách
    msg_supp = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"z_{uuid4().hex[:10]}",
        group_id=car_grp.zalo_group_id,
        sender_id="2025593064656318114",
        message_text=f"15F-017.85 cont {cont_ok}",
        raw_payload={},
        processing_status="QUEUED",
        created_at=REFERENCE,
        zalo_sent_at=REFERENCE,
    )
    db_session.add(msg_supp)
    db_session.flush()
    ExtractionHandler.process_message_by_id(db_session, msg_supp.id)

    db_session.refresh(reply)
    assert reply.status == "RESOLVED"
    assert db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == msg_supp.id)) is None
    assert any(c["group_id"] == cust_grp.zalo_group_id and cont_ok in str(c["message"]) for c in sent_calls)

    # Khách tra cứu trực tiếp số cont -> chỉ hiển thị thông tin chính, không kèm ghi chú dự kiến hoặc 'Nhà xe báo ... VALID/SENT'
    _, cust_reply = send(db_session, cust_grp, cont_ok)
    assert cont_ok in cust_reply and "15F-017.85" in cust_reply
    assert "Giờ hiển thị là giờ dự kiến" not in cust_reply
    assert "Nhà xe báo" not in cust_reply
    assert "định tuyến SENT" not in cust_reply
