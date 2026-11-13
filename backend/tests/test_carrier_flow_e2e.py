"""Kiểm thử tích hợp E2E luồng Bot <-> Nhà xe (Text, OCR, LLM, Quote bổ sung, Đổi xe, Sai nhà xe, Lỗi gửi)."""

from datetime import UTC, date, datetime
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
)
from src.domain.rules import compute_iso6346_check_digit
from src.handlers.extraction_handler import ExtractionHandler
from src.infrastructure.ai_service_client import AIExtractResult, AIServiceClient
from src.infrastructure.models import (
    BotReply,
    Carrier,
    ContainerJob,
    Customer,
    FileRecord,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    RouteMap,
    TransportPlan,
    ZaloGroup,
    ZaloMessage,
)
from src.infrastructure.snowflake import snowflake
from src.infrastructure.zalo_dispatcher import ZaloDispatcher


def _post_and_process(client, db, url, **kwargs):
    """Kiểm tra webhook trả QUEUED rồi chạy worker tường minh trong savepoint."""
    response = client.post(url, **kwargs)
    if url == "/webhook" and response.status_code == 200:
        assert response.json()["processing_status"] == "QUEUED"
        ExtractionHandler.process_message_by_id(db, response.json()["record_id"])
        response = client.post(url, **kwargs)
    return response


def _valid_cont(prefix: str = "MSCU", digits6: str = "663532") -> str:
    """Sinh số container chuẩn ISO 6346 phục vụ test."""
    chk = compute_iso6346_check_digit(f"{prefix.upper()}{digits6}0")
    return f"{prefix.upper()}{digits6}{chk}"


def _setup_carrier_customer_env(
    db: Session,
    carrier_name: str = "Đội Xe Tuấn Hưng",
    customer_name: str = "Khách Test Nhựa Á Đông",
    cont_no: str | None = None,
    send_mode: str = SendMode.AUTO.value,
    is_test: bool = True,
) -> dict[str, object]:
    """Khởi tạo bộ dữ liệu Nhà xe - Khách hàng - Nhóm Zalo - RouteMap - TransportPlan trong savepoint."""
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
        tms_customer_id=f"TMS_CUST_{uid}",
        name=customer_name,
        normalized_name=customer_name.lower(),
        is_active=True,
    )
    db.add_all([carrier, customer])
    db.flush()

    src_gid = f"test_carrier_{uid}" if is_test else f"999000{uid}"
    dest_gid = f"test_cust_{uid}" if is_test else f"888000{uid}"

    src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=src_gid,
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
        zalo_group_id=dest_gid,
        name=f"Nhóm {customer_name}",
        group_role=GroupRole.DESTINATION.value,
        send_mode=send_mode,
        is_test=is_test,
        is_active=True,
    )
    db.add_all([src_grp, dest_grp])
    db.flush()

    route = RouteMap(
        id=snowflake.generate(),
        customer_id=customer.id,
        zalo_group_id=dest_grp.id,
        priority=10,
        is_active=True,
    )
    db.add(route)

    plan = None
    if cont_no:
        plan = TransportPlan(
        carrier_id=carrier.id,
            id=snowflake.generate(),
            plan_date=date.today(),
            order_type="dong",
            container_no=cont_no,
            customer_name=customer_name,
            customer_id=customer.id,
            fleet_partner=carrier_name,
            carrier_name=carrier_name,
            delivery_address="Kho Đức Hòa Long An",
            group_id=dest_gid,
        )
        db.add(plan)

    db.flush()
    return {
        "carrier": carrier,
        "customer": customer,
        "src_grp": src_grp,
        "dest_grp": dest_grp,
        "plan": plan,
    }


def test_webhook_ignores_casual_chat(api_client: TestClient, db_session: Session) -> None:
    """Tin nhắn xã giao thông thường phải bị lọc sớm thành IGNORED_CHAT và không tạo ContainerJob."""
    gid = f"test_chat_{uuid4().hex[:6]}"
    resp = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_msg_chat_{uuid4().hex[:8]}",
            "group_id": gid,
            "sender_id": "test_driver_1",
            "message_text": "Chào cả nhà buổi sáng nha",
            "is_test": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processing_status"] == MessageStatus.IGNORED_CHAT.value
    assert body["containers_count"] == 0


def test_happy_path_carrier_dispatch_to_customer_notification(
    monkeypatch, api_client: TestClient, db_session: Session
) -> None:
    """Tin đủ 8 trường + khớp TransportPlan & Nhà xe -> PROCESSED, KHÔNG tốn token gọi LLM ngoài."""
    ai_calls = {"count": 0}
    monkeypatch.setattr(
        AIServiceClient,
        "extract",
        classmethod(lambda cls, **kwargs: ai_calls.__setitem__("count", ai_calls["count"] + 1) or None),
    )

    cont = _valid_cont("VSIO", "262032")
    env = _setup_carrier_customer_env(db_session, cont_no=cont)
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]
    dest_grp: ZaloGroup = env["dest_grp"]  # type: ignore[assignment]

    msg_text = (
        f"Đóng hàng - {env['customer'].name} - Kho Đức Hòa Long An\n"  # type: ignore[attr-defined]
        f"Xe 15C-878.99 tài xế Nguyễn Văn An 0903123456\n"
        f"Cont {cont} 40DC seal VS889900 hẹn 08:30"
    )
    resp = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_ok_{uuid4().hex[:8]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_nha_xe_1",
            "message_text": msg_text,
            "is_test": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_status"] == MessageStatus.PROCESSED.value
    assert data["containers_count"] == 1
    assert ai_calls["count"] == 0
    assert data["data"]["customer_notifications"] == []
    pending = db_session.scalar(select(OutboundMessage).where(OutboundMessage.target_group_id == dest_grp.id))
    assert pending is not None and pending.status == "PENDING_SEND"
    assert cont in pending.content


def test_missing_seal_triggers_bot_reply_then_quote_supplement_resolves(
    api_client: TestClient, db_session: Session
) -> None:
    """Tin thiếu chì -> tạo BotReply PENDING; nhà xe quote bổ sung chì -> merge và gửi thông báo khách."""
    cont = _valid_cont("TEMU", "445566")
    env = _setup_carrier_customer_env(db_session, cont_no=cont)
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]
    dest_grp: ZaloGroup = env["dest_grp"]  # type: ignore[assignment]

    first_mid = f"test_missing_{uuid4().hex[:8]}"
    r1 = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": first_mid,
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_nha_xe_2",
            "message_text": f"Xe 50H-049.15 lái xe Trần Bình 0912345678 trả hàng cont {cont} 40HC hẹn 09:30",
            "is_test": True,
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["processing_status"] == MessageStatus.NEEDS_REVIEW.value
    assert d1["reply_to_carrier"] is not None
    assert "chì" in d1["reply_to_carrier"].lower()

    bot_reply = db_session.scalar(select(BotReply).where(BotReply.message_id == d1["record_id"]))
    assert bot_reply is not None
    assert bot_reply.status == CorrectionStatus.PENDING.value
    # Gán zalo_msg_id giả định để kiểm thử chính xác bước quote reply
    bot_reply.zalo_msg_id = f"test_bot_q_{uuid4().hex[:6]}"
    db_session.flush()

    # Nhà xe reply quote đúng tin nhắc của bot để bổ sung số chì
    r2 = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_supp_{uuid4().hex[:8]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_nha_xe_2",
            "quote_msg_id": bot_reply.zalo_msg_id,
            "message_text": f"Bổ sung cont {cont} số chì HL778899",
            "is_test": True,
        },
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["processing_status"] == MessageStatus.PROCESSED.value

    db_session.refresh(bot_reply)
    assert bot_reply.status == CorrectionStatus.RESOLVED.value

    sent_out = db_session.scalar(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(
            ContainerJob.container_no == cont,
            OutboundMessage.target_group_id == dest_grp.id,
            OutboundMessage.status == OutboundStatus.PENDING_SEND.value,
        )
    )
    assert sent_out is not None
    assert "HL778899" in sent_out.content


def test_update_driver_flow_clarify_missing_cont_and_send_update_notification(
    api_client: TestClient, db_session: Session
) -> None:
    """Luồng đổi xe/tài xế: thiếu cont -> Bot hỏi lại; đủ cont -> gửi THÔNG BÁO CẬP NHẬT và bỏ qua trùng lặp."""
    cont = _valid_cont("CSNU", "778899")
    env = _setup_carrier_customer_env(db_session, cont_no=cont)
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]

    # 1. Tin báo ban đầu đầy đủ
    r1 = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_init_{uuid4().hex[:8]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_nha_xe_3",
            "message_text": f"Xe 15C-111.22 lái xe Nguyễn A 0901112233 đóng cont {cont} 40DC chì SL1122 hẹn 08:00",
            "is_test": True,
        },
    )
    assert r1.status_code == 200
    assert r1.json()["processing_status"] == MessageStatus.PROCESSED.value

    # 2. Nhà xe nhắn đổi xe nhưng quên ghi số cont -> Bot phải hỏi lại số cont
    r_missing_cont = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_upd_nocont_{uuid4().hex[:8]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_nha_xe_3",
            "message_text": "Đổi sang xe 15C-999.88 tài xế Lê Hùng",
            "is_test": True,
        },
    )
    assert r_missing_cont.status_code == 200
    assert r_missing_cont.json()["processing_status"] == MessageStatus.NEEDS_REVIEW.value
    assert "Số Container" in (r_missing_cont.json()["reply_to_carrier"] or "")

    # 3. Nhà xe gửi lệnh đổi xe có đủ số container -> Gửi THÔNG BÁO CẬP NHẬT
    r_upd = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_upd_ok_{uuid4().hex[:8]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_nha_xe_3",
            "message_text": f"Đổi xe cont {cont} sang xe 15C-999.88 tài xế Lê Hùng 0988777666",
            "is_test": True,
        },
    )
    assert r_upd.status_code == 200
    assert r_upd.json()["processing_status"] == MessageStatus.PROCESSED.value

    upd_msg = db_session.scalar(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(
            ContainerJob.container_no == cont,
            OutboundMessage.message_kind == "update",
            OutboundMessage.status == OutboundStatus.PENDING_SEND.value,
        )
    )
    assert upd_msg is not None
    assert "THÔNG BÁO CẬP NHẬT THÔNG TIN XE" in upd_msg.content
    assert "15C-999.88" in upd_msg.content

    # 4. Nhắn lại đúng thông tin xe mới đã gửi -> không spam lại khách
    r_dup = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_upd_dup_{uuid4().hex[:8]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_nha_xe_3",
            "message_text": f"Cập nhật lại cont {cont} vẫn xe 15C-999.88 tài xế Lê Hùng 0988777666",
            "is_test": True,
        },
    )
    assert r_dup.status_code == 200
    dup_out = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.status == OutboundStatus.IGNORED_DUPLICATE.value)
    )
    assert dup_out is not None


def test_wrong_carrier_mismatch_blocks_outbound_and_alerts_dhvt(
    api_client: TestClient, db_session: Session
) -> None:
    """Khi số cont thuộc kế hoạch của nhà xe khác -> chặn gửi nhầm nhóm, tạo ReviewCase CARRIER_MISMATCH."""
    cont = _valid_cont("OOLU", "334455")
    env = _setup_carrier_customer_env(
        db_session,
        carrier_name="Đội Xe Tuấn Hưng",
        cont_no=cont,
    )
    dest_grp: ZaloGroup = env["dest_grp"]  # type: ignore[assignment]

    # Tạo một nhóm Zalo nhà xe KHÁC gửi nhầm cont của Tuấn Hưng
    wrong_carrier = Carrier(
        id=snowflake.generate(),
        code=f"WRONG_{uuid4().hex[:5]}",
        name="Đội Xe Phương Anh",
        normalized_name="doi xe phuong anh",
        is_active=True,
    )
    db_session.add(wrong_carrier)
    db_session.flush()

    wrong_src_grp = ZaloGroup(
        id=snowflake.generate(),
        zalo_group_id=f"test_wrong_car_{uuid4().hex[:6]}",
        name="Nhóm Nhà Xe Phương Anh",
        group_role=GroupRole.SOURCE.value,
        carrier_id=str(wrong_carrier.id),
        carrier_name="Đội Xe Phương Anh",
        send_mode=SendMode.AUTO.value,
        is_test=True,
        is_active=True,
    )
    db_session.add(wrong_src_grp)
    db_session.flush()

    resp = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_mismatch_{uuid4().hex[:8]}",
            "group_id": wrong_src_grp.zalo_group_id,
            "sender_id": "test_wrong_sender",
            "message_text": f"Xe 15C-333.44 tài xế Phạm Văn D 0933445566 đóng cont {cont} 40DC seal AB1234",
            "is_test": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processing_status"] == MessageStatus.NEEDS_REVIEW.value
    assert body["data"]["customer_notifications"] == []

    rc = db_session.scalar(
        select(ReviewCase).where(
            ReviewCase.message_id == body["record_id"],
            ReviewCase.case_type == "CARRIER_MISMATCH",
        )
    )
    assert rc is not None
    # Đảm bảo tuyệt đối không có OutboundMessage gửi cho khách
    bad_out = db_session.scalar(
        select(OutboundMessage).where(OutboundMessage.target_group_id == dest_grp.id)
    )
    assert bad_out is None


def test_image_ocr_and_ai_service_extract_pipeline(
    monkeypatch, api_client: TestClient, db_session: Session
) -> None:
    """Kiểm thử tin nhắn ảnh đi qua OCR -> lưu bảng files -> AI Service extract (che SĐT) -> hoàn tất luồng."""
    cont = _valid_cont("HLXU", "998877")
    env = _setup_carrier_customer_env(db_session, cont_no=cont)
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]

    # Mock OCR & Extract của AIServiceClient để kiểm chứng luồng gọi từ ExtractionHandler
    from src.infrastructure.ai_service_client import AIOCRResult

    monkeypatch.setattr(
        AIServiceClient,
        "perform_ocr",
        classmethod(
            lambda cls, **kwargs: AIOCRResult(
                engine="paddleocr",
                text=f"Dong hang kho Duc Hoa\n15C-555.66 Le Minh 0905123456\nCont {cont} 40DC seal Z99881 hen 08:30",
                confidence=0.91,
                lines=[{"text": f"15C-555.66 cont {cont}", "confidence": 0.91, "box": []}],
                has_text=True,
            )
        ),
    )
    monkeypatch.setattr(
        AIServiceClient,
        "extract",
        classmethod(
            lambda cls, **kwargs: AIExtractResult(
                intent="PARSE_TRUCK_INFO",
                is_multi_vehicle=False,
                items=[
                    {
                        "plate_number": "15C-555.66",
                        "driver_name": "Lê Minh",
                        "driver_phone": "0905123456",
                        "container_no": cont,
                        "container_size": "40",
                        "seal_no": "Z99881",
                        "order_type": "LOAD",
                        "customer_name": "Khách Test Nhựa Á Đông",
                        "warehouse_name": "Kho Đức Hòa Long An",
                        "eta": "08:30",
                        "confidence": 0.95,
                    }
                ],
                model_name="gemini-3.5-flash",
                prompt_version="ai_extract_v2.0",
                raw_masked_text=f"Dong hang kho Duc Hoa\n15C-555.66 Le Minh 0905xxxx56\nCont {cont} 40DC seal Z99881 hen 08:30",
                latency_ms=120,
            )
        ),
    )

    resp = _post_and_process(api_client, db_session,
        "/webhook",
        json={
            "msg_id": f"test_img_{uuid4().hex[:8]}",
            "group_id": src_grp.zalo_group_id,
            "sender_id": "test_img_sender",
            "message_type": "image",
            "message_text": "[ảnh]",
            "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "is_test": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_status"] == MessageStatus.PROCESSED.value
    assert data["containers"][0]["container_no"] == cont

    # Kiểm tra đã ghi metadata vào bảng `files`
    frec = db_session.scalar(select(FileRecord).where(FileRecord.message_id == data["record_id"]))
    assert frec is not None
    assert frec.source_type == "ZALO_IMAGE"


def test_outbound_send_failure_creates_alert_and_mark_manual_sent_resolves(
    monkeypatch, api_client: TestClient, db_session: Session
) -> None:
    """Nếu gửi Zalo khách lỗi sau 3 lần thử -> ReviewCase OUTBOUND_SEND_FAILED + API Đánh dấu đã gửi thủ công."""
    cont = _valid_cont("MAEU", "123123")
    env = _setup_carrier_customer_env(db_session, cont_no=cont, is_test=False)
    src_grp: ZaloGroup = env["src_grp"]  # type: ignore[assignment]

    # Tạo tin nhắn thật trực tiếp qua DB để kích hoạt nhánh gửi thật
    msg = ZaloMessage(
        id=snowflake.generate(),
        zalo_message_id=f"real_fail_{uuid4().hex[:8]}",
        group_id=src_grp.zalo_group_id,
        sender_id="driver_real_fail",
        message_type="text",
        message_text=(
            f"Xe 15C-777.88 tài xế Hoàng Dũng 0977888999 đóng cont {cont} "
            f"40DC seal MK112233 hẹn 10:00"
        ),
        raw_payload={"is_test": False},
        processing_status=MessageStatus.QUEUED.value,
        received_at=datetime.now(UTC),
    )
    db_session.add(msg)
    db_session.flush()

    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", True)
    monkeypatch.setattr(
        ZaloDispatcher,
        "send_to_group",
        classmethod(lambda cls, **kwargs: (False, None, "ZCA Bridge 503 Unavailable")),
    )

    processed = ExtractionHandler.process_message_by_id(db_session, msg.id)
    from contextlib import nullcontext
    from src.infrastructure.outbox_worker import drain_outbox
    outbound_ids = list(db_session.scalars(select(OutboundMessage.id).join(OutboundMessageItem).join(ContainerJob).where(ContainerJob.message_id == msg.id)))
    drain_outbox(lambda: nullcontext(db_session), outbound_ids)
    assert processed is not None
    assert processed.processing_status == MessageStatus.NEEDS_REVIEW.value

    out_msg = db_session.scalar(
        select(OutboundMessage)
        .join(OutboundMessageItem, OutboundMessageItem.outbound_message_id == OutboundMessage.id)
        .join(ContainerJob, ContainerJob.id == OutboundMessageItem.container_job_id)
        .where(ContainerJob.message_id == msg.id)
    )
    assert out_msg is not None
    assert out_msg.status == OutboundStatus.FAILED.value

    rc = db_session.scalar(
        select(ReviewCase).where(
            ReviewCase.message_id == msg.id,
            ReviewCase.case_type == "OUTBOUND_SEND_FAILED",
        )
    )
    assert rc is not None
    assert rc.status == ReviewStatus.PENDING.value

    # ĐHVT copy gửi tay và bấm "Đã gửi thủ công"
    res_manual = api_client.post(f"/api/outbound/messages/{out_msg.id}/mark-manual-sent?note=Sent%20via%20Zalo%20Desktop")
    assert res_manual.status_code == 200
    assert res_manual.json()["status"] == OutboundStatus.SENT.value

    db_session.refresh(out_msg)
    db_session.refresh(rc)
    db_session.refresh(msg)
    assert out_msg.status == OutboundStatus.SENT.value
    assert rc.status == ReviewStatus.RESOLVED.value
    assert msg.processing_status == MessageStatus.PROCESSED.value
