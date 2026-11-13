"""Kiểm thử toàn diện luồng Bot <-> Khách hàng, Bot <-> ĐHVT và đồng bộ kế hoạch TransportPlan cục bộ."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.domain.enums import (
    CorrectionStatus,
    GroupRole,
    MessageStatus,
    OutboundStatus,
    ReviewStatus,
    SendMode,
    TmsSyncStatus,
)
from src.handlers.dhvt_service import DhvtNotificationService
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
    User,
    Warehouse,
    WarehouseAlias,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.security import create_access_token, hash_password
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher


def _valid_cont(prefix: str = "MSKU", serial: str | None = None) -> str:
    """Sinh mã container 11 ký tự hợp chuẩn ISO 6346 Modulo 11."""
    if serial is None:
        serial = f"{uuid4().int % 1_000_000:06d}"
    letter_map = {
        "A": 10, "B": 12, "C": 13, "D": 14, "E": 15, "F": 16, "G": 17, "H": 18, "I": 19,
        "J": 20, "K": 21, "L": 23, "M": 24, "N": 25, "O": 26, "P": 27, "Q": 28, "R": 29,
        "S": 30, "T": 31, "U": 32, "V": 34, "W": 35, "X": 36, "Y": 37, "Z": 38,
    }
    base = prefix.upper()[:4] + serial[:6]
    total = sum((letter_map[ch] if ch.isalpha() else int(ch)) * (2**idx) for idx, ch in enumerate(base))
    rem = total % 11
    return f"{base}{0 if rem == 10 else rem}"


def _post_and_process(api_client: TestClient, db_session: Session, payload: dict[str, object]) -> ZaloMessage:
    """Gửi payload webhook giả lập và chạy ExtractionHandler trực tiếp trên savepoint."""
    resp = api_client.post("/webhook", json=payload)
    assert resp.status_code == 200
    msg_id = int(resp.json()["record_id"])
    ExtractionHandler.process_message_by_id(db_session, msg_id)
    msg = db_session.get(ZaloMessage, msg_id)
    assert msg is not None
    db_session.refresh(msg)
    return msg


def _create_carrier_customer_dhvt_env(
    db: Session,
    *,
    carrier_name: str = "Đội Xe E2E",
    customer_name: str = "Khách Hàng Alpha",
    cont_no: str | None = None,
    seal_no: str | None = None,
    send_mode: str = SendMode.AUTO.value,
    is_test: bool = True,
) -> dict[str, object]:
    """Tạo đầy đủ thực thể Nhà xe, Khách hàng, Nhóm ĐHVT, RouteMap và TransportPlan trong savepoint."""
    uid = uuid4().hex[:6]
    carrier = Carrier(
        id=snowflake.generate(),
        code=f"CAR_{uid}",
        name=carrier_name,
        short_name=carrier_name,
        normalized_name=carrier_name.lower(),
        is_active=True,
    )
    customer = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"CUST_{uid}",
        name=customer_name,
        normalized_name=customer_name.lower(),
        is_active=True,
    )
    db.add_all([carrier, customer])
    db.flush()

    prefix_t = "test_" if is_test else "real_"
    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"{prefix_t}car_{uid}",
        name=f"Nhóm {carrier_name}",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(carrier.id),
        carrier_name=carrier_name,
        send_mode=send_mode,
        is_test=is_test,
        is_active=True,
    )
    dest_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"{prefix_t}cust_{uid}",
        name=f"Nhóm {customer_name}",
        group_role=GroupRole.CUSTOMER.value,
        send_mode=send_mode,
        is_test=is_test,
        is_active=True,
    )
    dhvt_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"{prefix_t}dhvt_{uid}",
        name="Nhóm ĐHVT Nội Bộ",
        group_role=GroupRole.DHVT.value,
        send_mode=SendMode.AUTO.value,
        is_test=is_test,
        is_active=True,
    )
    db.add_all([src_grp, dest_grp, dhvt_grp])
    db.flush()

    route = RouteMap(
        id=snowflake.generate(),
        customer_id=customer.id,
        zalo_group_id=dest_grp.id,
        priority=10,
        is_active=True,
    )
    db.add(route)

    plan = TransportPlan(
        id=snowflake.generate(),
        carrier_id=carrier.id,
        plan_date=date.today(),
        order_type="dong",
        container_no=cont_no,
        seal_no=seal_no,
        customer_name=customer_name,
        customer_id=customer.id,
        fleet_partner=carrier_name,
        carrier_name=carrier_name,
        delivery_address="Kho Đức Hòa Long An",
        group_id=dest_grp.zalo_group_id,
    )
    db.add(plan)
    db.flush()
    return {
        "carrier": carrier,
        "customer": customer,
        "src_grp": src_grp,
        "dest_grp": dest_grp,
        "dhvt_grp": dhvt_grp,
        "route": route,
        "plan": plan,
    }


def _create_user_headers(db: Session, dhvt_grp: ZaloGroup, username: str, zalo_uid: str, role: str = "DHVT") -> tuple[User, dict[str, str]]:
    """Tạo tài khoản nhân viên ĐHVT/Admin và header Bearer JWT hợp lệ cho TestClient."""
    u = User(
        id=snowflake.generate(),
        username=username,
        email=f"{username}_{uuid4().hex[:4]}@vsico.local",
        password_hash=hash_password("TestPass123!"),
        full_name=f"Nhân viên {username}",
        role=role,
        zalo_user_id=zalo_uid,
        zalo_info_id=dhvt_grp.id,
        is_active=True,
    )
    db.add(u)
    db.flush()
    tok = create_access_token({"sub": str(u.id), "username": u.username, "role": u.role})
    return u, {"Authorization": f"Bearer {tok}"}


def test_local_plan_empty_container_slot_fill_update_and_conflict(
    api_client: TestClient, db_session: Session
) -> None:
    """Khi TMS chưa kết nối: điền trống plan (J2 không có cont trước), update lần sau tăng version và chặn xung đột."""
    # 1. Kế hoạch rỗng container_no thuộc nhà xe (bước J2) -> Fill lần đầu
    env = _create_carrier_customer_dhvt_env(db_session, cont_no=None, is_test=True)
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]
    plan: TransportPlan = env["plan"]  # type: ignore[assignment]
    cont = _valid_cont("TCNU", "700123")

    m1 = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_j2_{uuid4().hex[:6]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_car_sender",
            "message_text": f"Xe 15H-012.34 tài xế Nguyễn Văn Hùng 0903111222 đóng hàng cont {cont} 40HC seal SL1001 hẹn 08:00",
            "is_test": True,
        },
    )
    assert m1.processing_status == MessageStatus.PROCESSED.value
    db_session.refresh(plan)
    assert plan.container_no == cont
    assert plan.seal_no == "SL1001"
    assert plan.driver_name == "Nguyễn Văn Hùng"
    assert plan.driver_phone == "0903111222"
    assert plan.planned_truck_plate is not None and "15H" in plan.planned_truck_plate
    assert plan.version == 2
    assert plan.tms_sync_status == TmsSyncStatus.PENDING.value

    fill_log = db_session.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "PLAN_VEHICLE_FILLED",
            ActivityLog.entity_id == str(plan.id),
        )
    )
    assert fill_log is not None

    # 2. Nhà xe báo đổi xe/tài xế khi kế hoạch đã có xe -> Update thông tin mới và tăng version lên 3
    m2 = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_upd_{uuid4().hex[:6]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_car_sender",
            "message_text": f"Đổi xe cho cont {cont} sang xe 15C-999.88 lái xe Phạm Văn Dũng 0988777666 hẹn 14:30",
            "is_test": True,
        },
    )
    assert m2.processing_status == MessageStatus.PROCESSED.value
    db_session.refresh(plan)
    assert plan.driver_name == "Phạm Văn Dũng"
    assert plan.driver_phone == "0988777666"
    assert plan.planned_truck_plate is not None and "999" in plan.planned_truck_plate
    assert plan.version == 3
    assert plan.tms_sync_status == TmsSyncStatus.PENDING.value

    upd_log = db_session.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "PLAN_VEHICLE_UPDATED",
            ActivityLog.entity_id == str(plan.id),
        )
    )
    assert upd_log is not None

    # 3. Nhà xe báo lệch số chì so với kế hoạch cố định -> tạo PLAN_FIELD_CONFLICT, không ghi đè plan
    cont_conflict = _valid_cont("HLXU", "556677")
    env2 = _create_carrier_customer_dhvt_env(db_session, cont_no=cont_conflict, seal_no="FIXED888", is_test=True)
    src_grp2: ZaloGroup = env2["src_grp"]  # type: ignore[assignment]
    plan2: TransportPlan = env2["plan"]  # type: ignore[assignment]

    m3 = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_conf_{uuid4().hex[:6]}",
            "group_id": src_grp2.zalo_group_id,
            "sender_id": "test_car_conf",
            "message_text": f"Xe 29H-111.22 lái xe Trần Nam 0912000333 đóng hàng cont {cont_conflict} 40HC seal KHAC999 hẹn 10:00",
            "is_test": True,
        },
    )
    assert m3.processing_status == MessageStatus.NEEDS_REVIEW.value
    db_session.refresh(plan2)
    assert plan2.seal_no == "FIXED888"
    rc_conflict = db_session.scalar(
        select(ReviewCase).where(ReviewCase.message_id == m3.id, ReviewCase.case_type == "PLAN_FIELD_CONFLICT")
    )
    assert rc_conflict is not None

    # 4. Nhiều kế hoạch rỗng cùng nhà xe (ambiguous) -> ReviewCase PLAN_SYNC_REQUIRED -> ĐHVT chọn 1 plan duyệt
    cont_multi = _valid_cont("CMAU", "334455")
    env3 = _create_carrier_customer_dhvt_env(db_session, cont_no=None, is_test=True)
    src_grp3: ZaloGroup = env3["src_grp"]  # type: ignore[assignment]
    plan_a: TransportPlan = env3["plan"]  # type: ignore[assignment]
    plan_b = TransportPlan(
        id=snowflake.generate(),
        carrier_id=env3["carrier"].id,  # type: ignore[attr-defined]
        plan_date=date.today(),
        order_type="dong",
        container_no=None,
        customer_id=env3["customer"].id,  # type: ignore[attr-defined]
        customer_name="Khách Hàng Alpha",
        group_id=env3["dest_grp"].zalo_group_id,  # type: ignore[attr-defined]
    )
    db_session.add(plan_b)
    db_session.flush()

    m4 = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_multi_{uuid4().hex[:6]}",
            "group_id": src_grp3.zalo_group_id,
            "sender_id": "test_car_multi",
            "message_text": f"Xe 15H-555.66 tài xế Lê Tuấn 0977888999 đóng hàng cont {cont_multi} 20DC seal SL222 hẹn 11:00",
            "is_test": True,
        },
    )
    assert m4.processing_status == MessageStatus.NEEDS_REVIEW.value
    rc_amb = db_session.scalar(
        select(ReviewCase).where(ReviewCase.message_id == m4.id, ReviewCase.case_type == "PLAN_SYNC_REQUIRED")
    )
    assert rc_amb is not None

    app_resp = api_client.post(f"/api/reviews/{rc_amb.id}/approve", json={"selected_plan_id": plan_b.id})
    assert app_resp.status_code == 200
    assert app_resp.json()["synced_plan_ids"] == [plan_b.id]
    db_session.refresh(plan_a)
    db_session.refresh(plan_b)
    assert plan_a.container_no is None
    assert plan_b.container_no == cont_multi
    assert plan_b.version == 2


def test_customer_outbound_manual_edit_approve_and_cancel_workflow(
    api_client: TestClient, db_session: Session, monkeypatch
) -> None:
    """Chế độ MANUAL gửi cảnh báo mẫu 2 cho ĐHVT, duyệt kèm sửa nội dung và duyệt hủy mẫu default_huy.txt."""
    sent_calls: list[dict[str, str | None]] = []

    def _fake_send(cls, group_id: str, message: str, quote_msg_id: str | None = None, **kwargs):
        sent_calls.append({"group_id": group_id, "message": message, "quote_msg_id": quote_msg_id})
        return True, f"z_sent_{len(sent_calls)}", None

    monkeypatch.setattr(ZaloDispatcher, "send_to_group", classmethod(_fake_send))
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)

    cont = _valid_cont("OOCL", "889900")
    env = _create_carrier_customer_dhvt_env(
        db_session,
        cont_no=cont,
        send_mode=SendMode.MANUAL.value,
        is_test=False,
    )
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]
    dest_grp: ZaloGroup = env["dest_grp"]  # type: ignore[assignment]
    dhvt_grp: ZaloGroup = env["dhvt_grp"]  # type: ignore[assignment]
    plan: TransportPlan = env["plan"]  # type: ignore[assignment]

    _, dhvt_headers = _create_user_headers(db_session, dhvt_grp, f"dhvt_u_{uuid4().hex[:4]}", "z_dhvt_real")

    # 1. Nhà xe gửi thông tin đầy đủ nhưng nhóm ở MANUAL -> chặn ở PENDING_APPROVAL và báo ĐHVT mẫu 2
    m1 = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"real_man_{uuid4().hex[:6]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "driver_sender_1",
            "message_text": f"Xe 15H-090.11 lái xe Bùi Văn Tám 0905123456 đóng hàng cont {cont} 40HC seal SL456 hẹn 13:00",
            "is_test": False,
        },
    )
    assert m1.processing_status == MessageStatus.NEEDS_REVIEW.value
    out_pending = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.target_group_id == dest_grp.id)
    )
    assert out_pending is not None
    assert out_pending.status == OutboundStatus.PENDING_APPROVAL.value
    assert out_pending.review_zalo_msg_id is not None
    assert any(
        c["group_id"] == dhvt_grp.zalo_group_id and "[VSICO - TIN CHO DUYET" in str(c["message"])
        for c in sent_calls
    )

    # 2. ĐHVT duyệt gửi từ Web kèm chỉnh sửa nội dung -> gửi ngay ra nhóm khách hàng
    edited_text = f"[VSICO CAP NHAT] Xe 15H-090.11 se vao dong cont {cont} luc 13h30."
    app_out = api_client.post(
        f"/api/outbound/messages/{out_pending.id}/approve",
        json={"content": edited_text},
        headers=dhvt_headers,
    )
    assert app_out.status_code == 200
    assert app_out.json()["status"] == OutboundStatus.SENT.value
    assert any(c["group_id"] == dest_grp.zalo_group_id and c["message"] == edited_text for c in sent_calls)

    # 3. Nhà xe yêu cầu hủy chuyến -> tạo ReviewCase CANCEL_REQUEST (chưa tự hủy khách hàng)
    m_cancel = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"real_can_{uuid4().hex[:6]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "driver_sender_1",
            "message_text": f"Cho xin hủy chuyến cont {cont} do xe bị sự cố dọc đường",
            "is_test": False,
        },
    )
    assert m_cancel.processing_status == MessageStatus.NEEDS_REVIEW.value
    rc_cancel = db_session.scalar(
        select(ReviewCase).where(ReviewCase.message_id == m_cancel.id, ReviewCase.case_type == "CANCEL_REQUEST")
    )
    assert rc_cancel is not None

    # 4. ĐHVT duyệt hủy trên Web -> phát hành mẫu hủy default_huy.txt tới nhóm khách + cập nhật plan + báo nhà xe
    prev_plan_ver = plan.version
    resp_cancel = api_client.post(
        f"/api/reviews/{rc_cancel.id}/approve",
        json={"cancel_reason": "Xe gặp sự cố, hủy lịch đóng hàng"},
        headers=dhvt_headers,
    )
    assert resp_cancel.status_code == 200
    cancel_om = db_session.scalar(
        select(OutboundMessage).where(
            OutboundMessage.target_group_id == dest_grp.id,
            OutboundMessage.message_kind == "cancel",
        )
    )
    assert cancel_om is not None
    assert cancel_om.status == OutboundStatus.SENT.value
    assert "HỦY" in cancel_om.content.upper()
    assert cont in cancel_om.content
    db_session.refresh(plan)
    assert plan.version == prev_plan_ver + 1
    assert "HUY CHUYEN" in (plan.notes or "")
    assert any(c["group_id"] == src_grp.zalo_group_id and "hủy" in str(c["message"]).lower() for c in sent_calls)


def test_customer_inbound_qa_routemap_isolation_masking_and_change_request(
    api_client: TestClient, db_session: Session
) -> None:
    """Hỏi đáp nhóm Khách hàng: che 6 số cuối SĐT, lọc đúng RouteMap, trả lời giống nhau khi thiếu/lệch tuyến, không tự sửa khi khách xin đổi."""
    cont_a = _valid_cont("SUDU", "112233")
    cont_b = _valid_cont("YMLU", "445566")
    env_a = _create_carrier_customer_dhvt_env(db_session, customer_name="Khách Alpha", cont_no=cont_a, is_test=True)
    env_b = _create_carrier_customer_dhvt_env(db_session, customer_name="Khách Beta", cont_no=cont_b, is_test=True)

    cust_grp_a: ZaloGroup = env_a["dest_grp"]  # type: ignore[assignment]
    src_grp_a: ZaloGroup = env_a["src_grp"]  # type: ignore[assignment]
    src_grp_b: ZaloGroup = env_b["src_grp"]  # type: ignore[assignment]

    # Nạp dữ liệu điều xe cho Alpha (SĐT 0903123459) và Beta (SĐT 0911222333)
    _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_seed_a_{uuid4().hex[:6]}",
            "group_id": src_grp_a.zalo_group_id,
            "sender_id": "test_c_a",
            "message_text": f"Xe 15H-123.45 tài xế Lê Văn Minh 0903123459 đóng hàng cont {cont_a} 40HC seal SLA1 hẹn 08:30",
            "is_test": True,
        },
    )
    _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_seed_b_{uuid4().hex[:6]}",
            "group_id": src_grp_b.zalo_group_id,
            "sender_id": "test_c_b",
            "message_text": f"Xe 29H-888.99 tài xế Ngô Văn Bé 0911222333 đóng hàng cont {cont_b} 40HC seal SLB2 hẹn 09:30",
            "is_test": True,
        },
    )

    # 1. Khách Alpha hỏi đúng cont của mình -> trả lời đúng và che 6 số cuối SĐT
    q_ok = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_qa_ok_{uuid4().hex[:6]}",
            "group_id": cust_grp_a.zalo_group_id,
            "sender_id": "cust_user_a",
            "message_text": f"Cho hỏi xe nào chạy cont {cont_a} mấy giờ tới?",
            "is_test": True,
        },
    )
    assert q_ok.processing_status == MessageStatus.PROCESSED.value
    ans_ok = db_session.scalar(
        select(OutboundMessage)
        .where(OutboundMessage.target_group_id == cust_grp_a.id, OutboundMessage.message_kind == "answer")
        .order_by(OutboundMessage.id.desc())
    )
    assert ans_ok is not None
    assert cont_a in ans_ok.content
    assert "0903123459" in ans_ok.content
    assert "******" not in ans_ok.content

    # 2. Khách Alpha dò hỏi cont_b (của Khách Beta) vs hỏi mã không tồn tại -> câu trả lời giống hệt nhau
    _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_qa_oob_{uuid4().hex[:6]}",
            "group_id": cust_grp_a.zalo_group_id,
            "sender_id": "cust_user_a",
            "message_text": f"Cont {cont_b} đã điều xe chưa?",
            "is_test": True,
        },
    )
    ans_oob = db_session.scalar(
        select(OutboundMessage)
        .where(OutboundMessage.target_group_id == cust_grp_a.id, OutboundMessage.message_kind == "answer")
        .order_by(OutboundMessage.id.desc())
    )
    assert ans_oob is not None
    assert "Ngô Văn Bé" not in ans_oob.content
    assert "0911" not in ans_oob.content

    cont_none = _valid_cont("NONU", "999999")
    _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_qa_miss_{uuid4().hex[:6]}",
            "group_id": cust_grp_a.zalo_group_id,
            "sender_id": "cust_user_a",
            "message_text": f"Cont {cont_none} xe đâu rồi?",
            "is_test": True,
        },
    )
    ans_miss = db_session.scalar(
        select(OutboundMessage)
        .where(OutboundMessage.target_group_id == cust_grp_a.id, OutboundMessage.message_kind == "answer")
        .order_by(OutboundMessage.id.desc())
    )
    assert ans_miss is not None
    assert ans_oob.content == ans_miss.content

    # Nhật ký audit phân biệt nội bộ rõ out_of_scope vs not_found và tự leo thang khi hỏi lại >= 2 lần
    assert db_session.scalar(select(ActivityLog).where(ActivityLog.action == "CUSTOMER_QA_OUT_OF_SCOPE")) is not None
    assert db_session.scalar(select(ActivityLog).where(ActivityLog.action == "CUSTOMER_QA_NOT_FOUND")) is not None
    assert db_session.scalar(select(ReviewCase).where(ReviewCase.case_type == "CUSTOMER_REPEATED_INQUIRY")) is not None

    # 3. Khách nhắn "ok em" -> không tạo ca thay đổi
    m_ack = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_cust_ack_{uuid4().hex[:6]}",
            "group_id": cust_grp_a.zalo_group_id,
            "sender_id": "cust_user_a",
            "message_text": "ok em",
            "is_test": True,
        },
    )
    assert m_ack.processing_status == MessageStatus.PROCESSED.value
    assert db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m_ack.id)) is None

    # 4. Khách xin đổi giờ -> không tự sửa dữ liệu, chuyển thành CUSTOMER_CHANGE_REQUEST
    m_chg = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"test_cust_chg_{uuid4().hex[:6]}",
            "group_id": cust_grp_a.zalo_group_id,
            "sender_id": "cust_user_a",
            "message_text": f"Bên anh xin đổi giờ đóng cont {cont_a} sang 16h nhé",
            "is_test": True,
        },
    )
    assert m_chg.processing_status == MessageStatus.NEEDS_REVIEW.value
    assert db_session.scalar(
        select(ReviewCase).where(ReviewCase.message_id == m_chg.id, ReviewCase.case_type == "CUSTOMER_CHANGE_REQUEST")
    ) is not None
    plan_a: TransportPlan = env_a["plan"]  # type: ignore[assignment]
    db_session.refresh(plan_a)
    assert plan_a.required_time != "16h"


def test_dhvt_zalo_lookup_command_rejection_web_claim_habit_and_overdue(
    api_client: TestClient, db_session: Session, monkeypatch
) -> None:
    """ĐHVT: tra cứu nội bộ đủ SĐT, chặn lệnh duyệt qua Zalo kèm link Web, chống trùng ca, claim lock, lưu thói quen kho và leo thang quá hạn."""
    sent_calls: list[dict[str, str | None]] = []

    def _fake_send(cls, group_id: str, message: str, quote_msg_id: str | None = None, **kwargs):
        sent_calls.append({"group_id": group_id, "message": message, "quote_msg_id": quote_msg_id})
        return True, f"z_d_{len(sent_calls)}", None

    monkeypatch.setattr(ZaloDispatcher, "send_to_group", classmethod(_fake_send))
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)

    cont = _valid_cont("HLXU", "223344")
    env = _create_carrier_customer_dhvt_env(db_session, cont_no=cont, is_test=False)
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]
    dhvt_grp: ZaloGroup = env["dhvt_grp"]  # type: ignore[assignment]
    customer: Customer = env["customer"]  # type: ignore[assignment]

    _, h1 = _create_user_headers(db_session, dhvt_grp, f"dhvt_one_{uuid4().hex[:4]}", "z_u1")
    _, h2 = _create_user_headers(db_session, dhvt_grp, f"dhvt_two_{uuid4().hex[:4]}", "z_u2")

    # Seed dữ liệu xe thiếu chì để tạo ReviewCase + BotReply
    m_missing = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"real_miss_{uuid4().hex[:6]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "real_driver_1",
            "message_text": f"Xe 15H-049.15 tài xế Vũ Văn An 0903123459 đóng hàng cont {cont} 40HC tại Kho Đức Hòa LA",
            "is_test": False,
        },
    )
    job = db_session.scalar(select(ContainerJob).where(ContainerJob.message_id == m_missing.id))
    assert job is not None
    rc = db_session.scalar(select(ReviewCase).where(ReviewCase.container_job_id == job.id))
    assert rc is not None

    # 1. Chống trùng ReviewCase cùng khóa nghiệp vụ
    rc_dup, created = DhvtNotificationService.create_or_merge_review_case(
        db=db_session,
        message_id=m_missing.id,
        case_type=rc.case_type,
        reason="Lặp cảnh báo cùng ca",
        container_job_id=job.id,
        container_no=cont,
        is_test_msg=True,
        notify_zalo=False,
    )
    assert created is False
    assert rc_dup.id == rc.id
    assert rc_dup.details and rc_dup.details.get("occurrence_count", 0) >= 2

    # 2. Người lạ không có trong bảng users hỏi trong nhóm ĐHVT -> bị chặn
    m_stranger = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"real_stranger_{uuid4().hex[:6]}",
            "group_id": dhvt_grp.zalo_group_id,
            "sender_id": "unknown_zalo_user",
            "message_text": cont,
            "is_test": False,
        },
    )
    assert m_stranger.processing_status == MessageStatus.PROCESSED.value
    assert db_session.scalar(select(ActivityLog).where(ActivityLog.action == "DHVT_UNREGISTERED_LOOKUP_BLOCKED")) is not None

    # 3. Nhân viên ĐHVT thật tra cứu cont / biển số / ca chờ / kế hoạch -> xem được đầy đủ SĐT
    for q_txt in (cont, "15H-049.15", "ca chờ", "kế hoạch"):
        _post_and_process(
            api_client,
            db_session,
            {
                "msg_id": f"real_lk_{uuid4().hex[:6]}",
                "group_id": dhvt_grp.zalo_group_id,
                "sender_id": "z_u1",
                "message_text": q_txt,
                "is_test": False,
            },
        )
    dhvt_msgs = [str(c["message"]) for c in sent_calls if c["group_id"] == dhvt_grp.zalo_group_id]
    assert any("0903123459" in m and cont in m for m in dhvt_msgs)
    assert any("Tổng hợp hàng chờ ĐHVT" in m for m in dhvt_msgs)
    assert any("Tổng quan kế hoạch vận chuyển" in m for m in dhvt_msgs)

    # 4. ĐHVT quote thông báo cảnh báo và nhắn "ok" trên Zalo -> BẮT BUỘC TỪ CHỐI + ĐƯA LINK WEB
    quote_id = (rc.details or {}).get("dhvt_zalo_msg_id") if isinstance(rc.details, dict) else None
    assert quote_id is not None
    m_ok = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"real_ok_rej_{uuid4().hex[:6]}",
            "group_id": dhvt_grp.zalo_group_id,
            "sender_id": "z_u1",
            "quote_msg_id": quote_id,
            "message_text": "ok",
            "is_test": False,
        },
    )
    assert m_ok.processing_status == MessageStatus.PROCESSED.value
    db_session.refresh(rc)
    assert rc.status == ReviewStatus.PENDING.value
    assert db_session.scalar(select(ActivityLog).where(ActivityLog.action == "DHVT_ZALO_COMMAND_REJECTED")) is not None
    assert any(
        f"/reviews/{rc.id}" in str(c["message"]) or "/reviews" in str(c["message"])
        for c in sent_calls
        if c["group_id"] == dhvt_grp.zalo_group_id
    )

    # 5. Web claim lock -> người thứ 2 bị 409 -> transfer -> duyệt chọn kho -> lưu WarehouseAlias habit
    wh = Warehouse(
        id=snowflake.generate(),
        tms_warehouse_id=f"WH_{uuid4().hex[:6]}",
        customer_id=customer.id,
        name="Kho Đức Hòa Chính Thức",
        normalized_name="kho đức hòa chính thức",
        is_active=True,
    )
    db_session.add(wh)
    db_session.flush()

    r_claim1 = api_client.post(f"/api/reviews/{rc.id}/claim", headers=h1)
    assert r_claim1.status_code == 200
    r_claim2 = api_client.post(f"/api/reviews/{rc.id}/claim", headers=h2)
    assert r_claim2.status_code == 409
    r_app_blocked = api_client.post(f"/api/reviews/{rc.id}/approve", json={"seal_no": "SL111"}, headers=h2)
    assert r_app_blocked.status_code == 409

    u2_name = db_session.scalar(select(User.username).where(User.zalo_user_id == "z_u2"))
    assert u2_name is not None
    r_transfer = api_client.post(
        f"/api/reviews/{rc.id}/transfer",
        json={"target_username": u2_name, "reason": "Bàn giao ca chiều"},
        headers=h1,
    )
    assert r_transfer.status_code == 200

    r_app_u2 = api_client.post(
        f"/api/reviews/{rc.id}/approve",
        json={"warehouse_id": wh.id, "seal_no": "SL999888", "save_warehouse_habit": True},
        headers=h2,
    )
    assert r_app_u2.status_code == 200
    assert r_app_u2.json()["warehouse_habit_saved"] is True
    db_session.refresh(job)
    assert job.warehouse_id == wh.id
    alias = db_session.scalar(
        select(WarehouseAlias).where(WarehouseAlias.warehouse_id == wh.id, WarehouseAlias.source == "human_review")
    )
    assert alias is not None

    # 6. Từ chối ca rà soát khác -> hủy outbound chờ và báo về nhóm nhà xe
    cont_rej = _valid_cont("PONU", "667788")
    env_r = _create_carrier_customer_dhvt_env(db_session, cont_no=cont_rej, is_test=False)
    src_r: ZaloGroup = env_r["src_grp"]  # type: ignore[assignment]
    m_rej_src = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"real_rej_{uuid4().hex[:6]}",
            "group_id": src_r.zalo_group_id,
            "sender_id": "driver_rej",
            "message_text": f"Xe 15H-222.33 tài xế Hoàng Dũng 0934567890 đóng hàng cont {cont_rej} 40HC",
            "is_test": False,
        },
    )
    rc_rej = db_session.scalar(select(ReviewCase).where(ReviewCase.message_id == m_rej_src.id))
    assert rc_rej is not None
    resp_rej = api_client.post(
        f"/api/reviews/{rc_rej.id}/reject",
        json={"reason": "Sai số container thực tế"},
        headers=h1,
    )
    assert resp_rej.status_code == 200
    assert any(
        c["group_id"] == src_r.zalo_group_id and "từ chối" in str(c["message"]).lower()
        for c in sent_calls
    )

    # 7. Quét leo thang quá hạn BotReply (30p) và ReviewCase (>30p)
    stale_reply = BotReply(
        id=snowflake.generate(),
        message_id=m_missing.id,
        sender_id="real_driver_1",
        reply_text="Nhắc bổ sung chì",
        fix_deadline=datetime.now(UTC) - timedelta(minutes=45),
        status=CorrectionStatus.PENDING.value,
    )
    stale_rc = ReviewCase(
        id=snowflake.generate(),
        message_id=m_missing.id,
        container_job_id=job.id,
        case_type="PLAN_SYNC_REQUIRED",
        reason="Ca quá hạn chờ duyệt thử nghiệm",
        details={"priority": "NORMAL"},
        status=ReviewStatus.PENDING.value,
        created_at=datetime.now(UTC) - timedelta(minutes=40),
    )
    db_session.add_all([stale_reply, stale_rc])
    db_session.commit()

    ov_resp = api_client.post("/api/reviews/check-overdue?is_test_msg=true", headers=h1)
    assert ov_resp.status_code == 200
    ov_data = ov_resp.json()
    assert ov_data["overdue_carrier_replies"] >= 1
    assert ov_data["reminded_review_cases"] >= 1
    db_session.refresh(stale_rc)
    assert stale_rc.details and stale_rc.details.get("reminder_count", 0) >= 1
    assert db_session.scalar(
        select(ReviewCase).where(ReviewCase.case_type == "CARRIER_CORRECTION_OVERDUE")
    ) is not None


def test_customer_and_carrier_qa_always_reply_when_missing_or_invalid(api_client, db_session, monkeypatch) -> None:
    """Đảm bảo nhóm Khách hàng và Nhà xe luôn nhận được phản hồi Q&A rõ ràng khi thiếu RouteMap, thiếu carrier hoặc sai mã cont."""
    from src.infrastructure.zalo_dispatcher import ZaloDispatcher

    monkeypatch.setattr(ZaloDispatcher, "send_to_group", lambda **kwargs: (True, f"z_{uuid4().hex[:6]}", None))

    cust_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"qa_cust_{uuid4().hex[:6]}",
        name="Khách QA chưa RouteMap",
        group_role="DESTINATION",
        send_mode="AUTO",
        is_test=True,
        is_active=True,
    )
    carrier = Carrier(
        id=snowflake.generate(),
        name="Nhà xe QA Test",
        normalized_name="nha xe qa test",
    )
    src_unassigned = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"qa_src_none_{uuid4().hex[:6]}",
        name="Nhà xe chưa gắn carrier",
        group_role="SOURCE",
        carrier_id=None,
        send_mode="AUTO",
        is_test=True,
        is_active=True,
    )
    src_assigned = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"qa_src_ok_{uuid4().hex[:6]}",
        name="Nhà xe đã gắn carrier",
        group_role="SOURCE",
        carrier_id=str(carrier.id),
        send_mode="AUTO",
        is_test=True,
        is_active=True,
    )
    plan_today = TransportPlan(
        id=snowflake.generate(),
        plan_date=date.today(),
        order_type="Đóng hàng",
        container_no="VSIU7399796",
        carrier_id=carrier.id,
        planned_truck_plate="15C-123.45",
        delivery_address="Kho Test QA",
        required_time="09:00",
    )
    db_session.add_all([cust_grp, carrier, src_unassigned, src_assigned, plan_today])
    db_session.commit()

    # 1. Nhóm khách hàng chưa có RouteMap hỏi "cho t xin thông tin cont SELU396800" -> phải phản hồi, không im lặng
    m_no_route = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"qa_c_noroute_{uuid4().hex[:6]}",
            "group_id": cust_grp.zalo_group_id,
            "sender_id": "cust_user_1",
            "message_text": "cho t xin thông tin cont SELU396800",
            "is_test": True,
        },
    )
    assert m_no_route.processing_status == MessageStatus.PROCESSED.value
    out_no_route = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.target_group_id == cust_grp.id)
    )
    assert out_no_route is not None and "routemap" in out_no_route.content.lower()

    # 2. Nhóm khách hàng đã có RouteMap nhưng hỏi mã cont 6 số (SELU396800) -> nhắc đúng chuẩn 11 ký tự
    cust = Customer(
        id=snowflake.generate(),
        tms_customer_id=f"QA_{uuid4().hex[:6]}",
        name="Khách QA",
        normalized_name="khach qa",
    )
    db_session.add(cust)
    db_session.flush()
    db_session.add(
        RouteMap(
            id=snowflake.generate(),
            customer_id=cust.id,
            zalo_group_id=cust_grp.id,
            is_active=True,
        )
    )
    db_session.commit()

    _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"qa_c_badcont_{uuid4().hex[:6]}",
            "group_id": cust_grp.zalo_group_id,
            "sender_id": "cust_user_1",
            "message_text": "cho t xin thông tin cont SELU396800",
            "is_test": True,
        },
    )
    out_bad_cont = db_session.scalar(
        select(OutboundMessage)
        .where(OutboundMessage.target_group_id == cust_grp.id)
        .order_by(OutboundMessage.id.desc())
    )
    assert out_bad_cont is not None and "11 ký tự" in out_bad_cont.content

    # 3. Nhóm Nhà xe chưa gắn carrier_id hỏi "hôm nay có những cont nào" -> phản hồi ngay, không bắn SHIPPING_NOT_FOUND
    m_src_none = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"qa_s_none_{uuid4().hex[:6]}",
            "group_id": src_unassigned.zalo_group_id,
            "sender_id": "driver_qa_1",
            "message_text": "hôm nay có những cont nào",
            "is_test": True,
        },
    )
    assert m_src_none.processing_status == MessageStatus.PROCESSED.value
    out_src_none = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.target_group_id == src_unassigned.id)
    )
    assert out_src_none is not None and "liên kết với nhà xe" in out_src_none.content.lower()

    # 4. Nhóm Nhà xe đã gắn carrier_id hỏi "hôm nay có những cont nào" -> trả đúng danh sách cont của nhà xe đó
    m_src_ok = _post_and_process(
        api_client,
        db_session,
        {
            "msg_id": f"qa_s_ok_{uuid4().hex[:6]}",
            "group_id": src_assigned.zalo_group_id,
            "sender_id": "driver_qa_2",
            "message_text": "hôm nay có những cont nào",
            "is_test": True,
        },
    )
    assert m_src_ok.processing_status == MessageStatus.PROCESSED.value
    out_src_ok = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.target_group_id == src_assigned.id)
    )
    assert out_src_ok is not None and "VSIU7399796" in out_src_ok.content
