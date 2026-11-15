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

    # Bước 1: Tin báo thiếu chì -> sinh BotReply ảo + virtual_jobs_next (allow_ai_fallback=False)
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

    # Bước 2: Quote lại cảnh báo Bot và bổ sung số chì -> ghép thành công với virtual_job
    r2 = api_client.post(
        "/api/sandbox/simulate",
        json={
            "text": "Bổ sung số chì HL778899",
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
    assert "Số Container" in (r_upd.json()["preview_outputs"]["bot_reply"] or "")

    r_chat = api_client.post(
        "/api/sandbox/simulate",
        json={"text": "Chào buổi sáng cả nhà", "allow_ai_fallback": False},
    )
    assert r_chat.status_code == 200
    assert r_chat.json()["processing_status"] == MessageStatus.IGNORED_CHAT.value
    assert r_chat.json()["ai_would_trigger"] is False
