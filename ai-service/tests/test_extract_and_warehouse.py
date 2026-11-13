"""Kiểm thử endpoint `/api/v1/extract` (che PII, đa xe, ý định) và `/api/v1/match-warehouse`."""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.providers.base_provider import BaseAIProvider, ProviderResult, VisionOCRResult

client = TestClient(app)


class _SpyMockProvider(BaseAIProvider):
    """Provider giả lập kiểm tra xem prompt gửi đi đã che SĐT hay chưa."""

    last_user_prompt: str = ""

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def generate_structured_json(
        self, system_prompt: str, user_prompt: str, timeout_seconds: float | None = None
    ) -> ProviderResult:
        _SpyMockProvider.last_user_prompt = user_prompt
        return ProviderResult(
            success=True,
            model_name="gemini-3.5-flash",
            latency_ms=42,
            parsed={
                "intent": "PARSE_TRUCK_INFO",
                "is_multi_vehicle": True,
                "items": [
                    {
                        "plate_number": "15C-123.45",
                        "driver_name": "Nguyễn Văn An",
                        "driver_phone": "0903xxxx59",
                        "container_no": "MSCU1234567",
                        "container_size": "40",
                        "seal_no": "VS998811",
                        "order_type": "LOAD",
                        "warehouse_name": "Kho Hải Phòng",
                        "eta": "08:30",
                        "evidence": "15C-12345 An 0903xxxx59 cont MSCU1234567",
                        "confidence": 0.94,
                    },
                    {
                        "plate_number": "15C-678.90",
                        "driver_name": "Trần Bình",
                        "driver_phone": "0912xxxx34",
                        "container_no": "TEMU7654321",
                        "container_size": "20",
                        "seal_no": "VS998822",
                        "order_type": "RETURN",
                        "warehouse_name": "Kho Long An",
                        "eta": "14:00",
                        "evidence": "15C-67890 Bình 0912xxxx34 cont TEMU7654321",
                        "confidence": 0.91,
                    },
                ],
            },
        )

    async def ocr_image_vision(
        self, image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi", timeout_seconds: float | None = None
    ) -> VisionOCRResult:
        return VisionOCRResult(success=False)


def test_extract_masks_phones_for_cloud_and_restores_output(monkeypatch) -> None:
    """Đảm bảo SĐT được che thành `xxxx` trước khi gọi LLM và khôi phục lại số thật khi trả backend."""
    monkeypatch.setattr("app.analyze.service.get_ai_provider", lambda: _SpyMockProvider())

    resp = client.post(
        "/api/v1/extract",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={
            "message_text": "1. Xe 15C-12345 An 0903112259 cont MSCU1234567 chi VS998811\n2. Xe 15C-67890 Binh 0912889934 cont TEMU7654321",
            "group_id": "1001",
            "sender_id": "2002",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # Prompt ra Cloud LLM không được phép chứa số điện thoại thật
    assert "0903112259" not in _SpyMockProvider.last_user_prompt
    assert "0912889934" not in _SpyMockProvider.last_user_prompt
    assert "0903xxxx59" in _SpyMockProvider.last_user_prompt

    assert data["intent"] == "PARSE_TRUCK_INFO"
    assert data["is_multi_vehicle"] is True
    assert len(data["items"]) == 2
    assert data["items"][0]["driver_phone"] == "0903112259"
    assert data["items"][1]["driver_phone"] == "0912889934"
    assert "0903112259" in data["items"][0]["evidence"]


def test_extract_offline_heuristic_handles_update_and_supplement(monkeypatch) -> None:
    """Tin rõ ràng (đổi xe / bổ sung / đủ trường) dùng heuristic cục bộ, KHÔNG gọi tốn token Cloud LLM."""

    class _SpyNeverCalledProvider(BaseAIProvider):
        calls = 0

        @property
        def provider_name(self) -> str:
            return "gemini"

        async def generate_structured_json(self, system_prompt: str, user_prompt: str, timeout_seconds=None):
            _SpyNeverCalledProvider.calls += 1
            return ProviderResult(success=False, error="should_not_be_called")

        async def ocr_image_vision(self, image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi", timeout_seconds=None):
            return VisionOCRResult(success=False)

    monkeypatch.setattr("app.analyze.service.get_ai_provider", lambda: _SpyNeverCalledProvider())

    upd_resp = client.post(
        "/api/v1/extract",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={"message_text": "Đổi xe cont MSCU1234567 sang 15C-999.88 tài xế Dũng 0988777666"},
    )
    assert upd_resp.status_code == 200
    upd_data = upd_resp.json()
    assert upd_data["intent"] == "UPDATE_REQUEST"
    assert upd_data["model_name"] == "local-heuristic-v1"
    assert upd_data["items"][0]["container_no"] == "MSCU1234567"
    assert upd_data["items"][0]["driver_phone"] == "0988777666"
    assert _SpyNeverCalledProvider.calls == 0


def test_match_warehouse_waterfall_tiers() -> None:
    """Kiểm thử map kho theo tầng Habit -> Fuzzy -> Unresolved."""
    candidates = [
        {
            "id": 101,
            "customer_id": 10,
            "name": "Kho Nhựa Á Đông Long An",
            "normalized_name": "kho nhua a dong long an",
            "address": "Lô B2 KCN Đức Hòa, Long An",
            "aliases": ["A Dong LA", "Kho Duc Hoa"],
            "carrier_ids": [55],
        },
        {
            "id": 102,
            "customer_id": 10,
            "name": "Cảng Tân Vũ Hải Phòng",
            "normalized_name": "cang tan vu hai phong",
            "address": "Đình Vũ, Hải Phòng",
            "aliases": ["Tan Vu HP"],
            "carrier_ids": [],
        },
    ]

    # Tầng 1: Khớp theo bí danh + carrier habit
    r_habit = client.post(
        "/api/v1/match-warehouse",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={
            "raw_address": "Kho Đức Hòa",
            "carrier_id": 55,
            "customer_id": 10,
            "candidate_warehouses": candidates,
        },
    )
    assert r_habit.status_code == 200
    assert r_habit.json()["matched"] is True
    assert r_habit.json()["warehouse_id"] == 101
    assert r_habit.json()["source"] == "habit"

    # Tầng 2: Khớp mờ (Fuzzy) theo tên/địa chỉ không dấu
    r_fuzzy = client.post(
        "/api/v1/match-warehouse",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={
            "raw_address": "Dinh Vu Hai Phong",
            "customer_id": 10,
            "candidate_warehouses": candidates,
        },
    )
    assert r_fuzzy.status_code == 200
    assert r_fuzzy.json()["matched"] is True
    assert r_fuzzy.json()["warehouse_id"] == 102
    assert r_fuzzy.json()["source"] == "fuzzy"

    # Không khớp -> unresolved
    r_unres = client.post(
        "/api/v1/match-warehouse",
        headers={"X-Internal-Token": settings.INTERNAL_SECRET},
        json={
            "raw_address": "Địa điểm lạ chưa từng có xyz123",
            "candidate_warehouses": candidates,
        },
    )
    assert r_unres.status_code == 200
    assert r_unres.json()["matched"] is False
    assert r_unres.json()["source"] == "unresolved"
