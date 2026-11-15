"""Kiểm tra parser intent nội bộ: xác thực, che PII và giới hạn tập công cụ."""

from fastapi.testclient import TestClient

import app.routers.assistant as module
from app.core.config import settings
from app.main import app
from app.providers.base_provider import ProviderResult


class ProviderStub:
    """Provider kiểm thử lưu prompt và trả JSON có kiểm soát."""

    def __init__(self, parsed):
        """Giữ kết quả giả lập chỉ trong môi trường tests."""
        self.parsed = parsed
        self.prompt = ""

    async def generate_structured_json(self, system_prompt, user_prompt, **kwargs):
        """Thu prompt để kiểm chứng dữ liệu nhạy cảm đã bị che."""
        self.prompt = user_prompt
        return ProviderResult(
            success=True, parsed=self.parsed, model_name="test-provider", latency_ms=12
        )


def test_assistant_masks_and_validates_closed_tools(monkeypatch):
    """AI chỉ chọn công cụ cho phép và không nhận SĐT nguyên bản."""
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "test-assistant-token")
    provider = ProviderStub(
        {
            "intent": "carrier_list_plans_by_date",
            "confidence": 0.9,
            "entities": {"plan_date": "2026-11-10"},
            "needs_clarification": False,
        }
    )
    monkeypatch.setattr(module, "get_ai_provider", lambda: provider)
    client = TestClient(app)
    payload = {
        "message_text": "Tra giúp tài xế 0903123459 ngày mai",
        "allowed_tools": ["carrier_list_plans_by_date"],
        "reference_date": "2026-11-09",
    }
    response = client.post(
        "/api/v1/assistant-intent",
        json=payload,
        headers={"X-Internal-Token": "test-assistant-token"},
    )
    assert response.status_code == 200
    assert response.json()["call"]["intent"] == "carrier_list_plans_by_date"
    assert "0903123459" not in provider.prompt and "0903xxxx59" in provider.prompt
    provider.parsed["intent"] = "dhvt_get_priority_digest"
    assert (
        client.post(
            "/api/v1/assistant-intent",
            json=payload,
            headers={"X-Internal-Token": "test-assistant-token"},
        ).json()["call"]["intent"]
        == "UNKNOWN"
    )
    provider.parsed = {
        "intent": "carrier_list_plans_by_date",
        "entities": {"carrier_id": 1},
    }
    assert (
        client.post(
            "/api/v1/assistant-intent",
            json=payload,
            headers={"X-Internal-Token": "test-assistant-token"},
        ).json()["call"]["intent"]
        == "UNKNOWN"
    )


def test_assistant_requires_internal_auth(monkeypatch):
    """Endpoint nội bộ không nhận request thiếu/sai token."""
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "test-assistant-token")
    payload = {
        "message_text": "hôm nay",
        "allowed_tools": ["get_role_help"],
        "reference_date": "2026-11-09",
    }
    client = TestClient(app)
    assert client.post("/api/v1/assistant-intent", json=payload).status_code == 422
    assert (
        client.post(
            "/api/v1/assistant-intent",
            json=payload,
            headers={"X-Internal-Token": "wrong"},
        ).status_code
        == 401
    )
