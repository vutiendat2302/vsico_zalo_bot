"""Kiểm thử API Sandbox `/api/sandbox/simulate` (Dry-run không ghi CSDL & hiểu bối cảnh)."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.domain.enums import Intent, MessageStatus
from src.domain.rules import compute_iso6346_check_digit
from src.infrastructure.models import ContainerJob, ZaloMessage


def _valid_cont(prefix: str = "MSCU", digits6: str = "663532") -> str:
    chk = compute_iso6346_check_digit(f"{prefix}{digits6}0")
    return f"{prefix}{digits6}{chk}"


def test_sandbox_simulate_zero_db_persistence_and_context_flow(
    api_client: TestClient, db_session: Session
) -> None:
    """Kiểm tra Sandbox chạy nối tiếp Thiếu chì -> Quote bổ sung -> Đổi xe -> Đủ diff mà không ghi DB."""
    before_msgs = db_session.scalar(select(func.count(ZaloMessage.id))) or 0
    before_jobs = db_session.scalar(select(func.count(ContainerJob.id))) or 0

    cont = _valid_cont("TEMU", "445566")

    # Bước 1: Tin báo thiếu rơ-moóc -> sinh BotReply ảo + virtual_jobs_next (allow_ai_fallback=False)
    r1 = api_client.post(
        "/api/sandbox/simulate",
        json={
            "text": f"Khách hàng: Daikin, Xe 50H-049.15 lái xe Trần Bình 0912345678 trả hàng cont {cont} 40HC hẹn 09:30",
            "allow_ai_fallback": False,
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["persisted"] is False
    assert d1["ai_executed"] is False
    assert d1["processing_status"] == MessageStatus.NEEDS_REVIEW.value
    assert d1["preview_outputs"]["bot_reply"] is not None
    assert len(d1["virtual_jobs_next"]) == 1

    # Bước 2: Quote lại cảnh báo Bot và bổ sung rơ-moóc + số chì -> ghép thành công với virtual_job
    r2 = api_client.post(
        "/api/sandbox/simulate",
        json={
            "text": "Bổ sung mooc 15R-181.29 số chì HL778899",
            "quote_message": d1["preview_outputs"]["bot_reply"],
            "context_messages": [d1["effective_text"]],
            "virtual_jobs": d1["virtual_jobs_next"],
            "allow_ai_fallback": False,
        },
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["persisted"] is False
    assert d2["resolved_intent"] == Intent.SUPPLEMENT.value
    assert d2["context_resolution"]["resolution_type"] == "SUPPLEMENT_MERGE"
    assert d2["records"][0]["seal_no"] == "HL778899"
    assert d2["records"][0]["plate"] == "50H04915"

    # Bước 3: Đổi xe có cont -> tính đúng diff Biển số/Tài xế + render THÔNG BÁO CẬP NHẬT
    r3 = api_client.post(
        "/api/sandbox/simulate",
        json={
            "text": f"Đổi xe cont {cont} sang xe 15C-999.88 tài xế Lê Hùng 0988777666",
            "context_messages": [d1["effective_text"], d2["effective_text"]],
            "virtual_jobs": d2["virtual_jobs_next"],
            "allow_ai_fallback": False,
        },
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["resolved_intent"] == Intent.UPDATE_REQUEST.value
    assert d3["context_resolution"]["resolution_type"] == "UPDATE_DIFF"
    assert any("15C-999.88" in ch for ch in d3["context_resolution"]["changes_list"])
    assert "THÔNG BÁO CẬP NHẬT THÔNG TIN XE" in (d3["preview_outputs"]["customer_notification"] or "")

    # Xác nhận 0 dòng mới được lưu xuống MySQL
    after_msgs = db_session.scalar(select(func.count(ZaloMessage.id))) or 0
    after_jobs = db_session.scalar(select(func.count(ContainerJob.id))) or 0
    assert after_msgs == before_msgs
    assert after_jobs == before_jobs


def test_sandbox_update_missing_cont_and_casual_chat(api_client: TestClient) -> None:
    """Đổi xe thiếu số container phải hỏi lại; tin xã giao phải chặn ngay Gatekeeper."""
    r_upd = api_client.post(
        "/api/sandbox/simulate",
        json={"text": "Đổi sang xe 15C-999.88 tài xế Lê Hùng", "allow_ai_fallback": False},
    )
    assert r_upd.status_code == 200
    assert r_upd.json()["context_resolution"]["clarify_missing_container"] is True
    assert "chưa xác định được chuyến xe" in (r_upd.json()["preview_outputs"]["bot_reply"] or "").lower()

    r_chat = api_client.post(
        "/api/sandbox/simulate",
        json={"text": "Chào buổi sáng cả nhà", "allow_ai_fallback": False},
    )
    assert r_chat.status_code == 200
    assert r_chat.json()["processing_status"] == MessageStatus.IGNORED_CHAT.value
    assert r_chat.json()["ai_would_trigger"] is False


def test_sandbox_tms_dispatch_payloads_preview(api_client: TestClient, db_session) -> None:
    """Kiểm thử API sandbox trả về `tms_dispatch_payloads` chuẩn format gửi về TMS (Dry-Run)."""
    from datetime import date

    from src.infrastructure.snowflake import snowflake
    from src.infrastructure.models import TransportPlan

    plan = TransportPlan(
        id=snowflake.generate(),
        plan_date=date.today(),
        order_code="LO99881",
        order_type="Đóng",
        customer_name="CÔNG TY TEST TMS",
        container_no="MSKU9070323",
    )
    db_session.add(plan)
    db_session.commit()

    # 1. Không có container khớp DB -> trả về NO_MATCHED_PLAN kèm normalized_fields
    r_unmatched = api_client.post(
        "/api/sandbox/simulate",
        json={
            "text": "Xe 15H-012.34 mooc 15R-181.29 cont TCNU1234561 tai xe Le Van Minh 0912345678",
            "allow_ai_fallback": False,
        },
    )
    assert r_unmatched.status_code == 200
    previews_unmatched = r_unmatched.json()["tms_dispatch_payloads"]
    assert len(previews_unmatched) == 1
    assert previews_unmatched[0]["plan_found"] is False
    assert previews_unmatched[0]["blocked_reason"] == "NO_MATCHED_PLAN"
    assert previews_unmatched[0]["normalized_fields"]["planned_truck_plate"] == "15H-012.34"

    # 2. Khớp theo order_code qua /api/sandbox/nlp-analyze -> dựng đủ payload gửi TMS
    r_nlp = api_client.post(
        "/api/sandbox/nlp-analyze",
        json={
            "text": "LO99881 Xe 15H-012.34 mooc 15R-181.29 cont MSKU9070323 tai xe Le Van Minh 0912345678",
            "plan_date": date.today().isoformat(),
            "include_plan_resolution": True,
        },
    )
    assert r_nlp.status_code == 200
    previews = r_nlp.json()["tms_dispatch_payloads"]
    assert len(previews) == 1
    assert previews[0]["plan_found"] is True
    assert previews[0]["ready"] is True
    assert previews[0]["order_code"] == "LO99881"
    assert previews[0]["payload"]["order_code"] == "LO99881"
    assert previews[0]["payload"]["container_no"] == "MSKU9070323"
    assert previews[0]["payload"]["planned_truck_plate"] == "15H-012.34"
    assert "planned_truck_plate" in previews[0]["requested_fields"]
