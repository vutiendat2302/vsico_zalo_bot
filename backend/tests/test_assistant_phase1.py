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
        ("DHVT", "Duyệt ca #123", "BLOCK_WRITE"),
        ("DHVT", "ok", "BLOCK_WRITE"),
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


def test_customer_scope_required_even_when_plan_group_matches(db_session, assistant_env):
    """Không dùng group_id mặc định để mở quyền khi thiếu RouteMap."""
    groups, plans = assistant_env
    for route in db_session.scalars(
        select(RouteMap).where(RouteMap.zalo_group_id == groups[0][1].id)
    ).all():
        route.is_active = False
    plans[1].group_id = groups[0][1].zalo_group_id
    db_session.flush()
    _, text = send(db_session, groups[0][1], "LO8201 xe nào chở?")
    assert "RouteMap" in text and "29C-441.22" not in text


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
        ("Hôm nay bao nhiêu chuyến?", "Tổng quan"),
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
        ("Duyệt ca #1", "không hỗ trợ"),
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
