"""Dịch vụ phân tích hội thoại, phân đoạn đa xe và bóc tách thực thể điều vận bằng LLM."""

import time
from typing import Any

from app.analyze.heuristic_fallback import heuristic_extract, infer_intent
from app.analyze.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.core.config import settings
from app.providers.factory import get_ai_provider
from app.providers.privacy_masker import PrivacyMasker
from app.schemas.extract import ExtractedEntity, ExtractRequest, ExtractResponse

_INTENT_ALIASES = {
    "TAO_MOI": "PARSE_TRUCK_INFO",
    "PARSE_TRUCK_INFO": "PARSE_TRUCK_INFO",
    "BO_SUNG": "SUPPLEMENT",
    "SUPPLEMENT": "SUPPLEMENT",
    "DOI_XE": "UPDATE_REQUEST",
    "UPDATE_REQUEST": "UPDATE_REQUEST",
    "HUY": "CANCEL_REQUEST",
    "CANCEL_REQUEST": "CANCEL_REQUEST",
    "HOI_THONG_TIN": "IGNORE_CHAT",
    "KHONG_RO": "IGNORE_CHAT",
    "IGNORE_CHAT": "IGNORE_CHAT",
}


class AnalyzeService:
    """Điều phối che PII -> gọi LLM Provider (hoặc heuristic fallback) -> khôi phục SĐT."""

    @staticmethod
    def _normalize_intent(raw_intent: str | None, text: str, quote_message: str | None, item_count: int) -> str:
        """Chuẩn hóa nhãn ý định về tập ENUM tiếng Anh viết hoa thống nhất toàn hệ thống."""
        key = (raw_intent or "").strip().upper()
        if key in _INTENT_ALIASES:
            return _INTENT_ALIASES[key]
        return infer_intent(text, quote_message=quote_message, entity_count=item_count)

    @staticmethod
    def _map_llm_items(raw_items: list[dict[str, Any]], phone_map: dict[str, str]) -> list[ExtractedEntity]:
        """Ánh xạ danh sách JSON từ LLM thành danh sách `ExtractedEntity` và khôi phục SĐT."""
        entities: list[ExtractedEntity] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            phone_restored = PrivacyMasker.restore_value(item.get("driver_phone"), phone_map)
            evidence_restored = PrivacyMasker.restore_value(item.get("evidence"), phone_map)
            raw_order = (str(item.get("order_type") or "").strip().upper() or None)
            if raw_order in ("DONG", "XUAT", "LOAD"):
                raw_order = "LOAD"
            elif raw_order in ("TRA", "NHAP", "RETURN"):
                raw_order = "RETURN"
            else:
                raw_order = None

            entities.append(
                ExtractedEntity(
                    plate_number=item.get("plate_number"),
                    trailer_number=item.get("trailer_number"),
                    driver_name=item.get("driver_name"),
                    driver_phone=phone_restored,
                    container_no=str(item.get("container_no")).upper() if item.get("container_no") else None,
                    container_size=str(item.get("container_size")) if item.get("container_size") else None,
                    seal_no=str(item.get("seal_no")).upper() if item.get("seal_no") else None,
                    booking_no=item.get("booking_no"),
                    order_type=raw_order,
                    customer_name=item.get("customer_name"),
                    warehouse_name=item.get("warehouse_name"),
                    eta=item.get("eta"),
                    plan_date=item.get("plan_date"),
                    evidence=evidence_restored,
                    confidence=float(item.get("confidence") or 0.85),
                )
            )
        return entities

    @staticmethod
    def _needs_cloud_llm(
        req: ExtractRequest,
        h_intent: str,
        h_items: list[ExtractedEntity],
    ) -> bool:
        """Quyết định có thực sự cần gọi Cloud LLM hay kết quả heuristic cục bộ đã đủ chính xác.

        Giúp giảm tối đa chi phí token: chỉ gọi Cloud LLM khi tin nhắn tự do/mơ hồ,
        thiếu trường cốt lõi (xe/cont/tài xế) hoặc tham chiếu ngữ cảnh phức tạp.
        """
        if h_intent == "IGNORE_CHAT" and not h_items:
            return False

        if h_intent in ("CANCEL_REQUEST", "SUPPLEMENT", "UPDATE_REQUEST") and h_items:
            has_key = any(
                it.container_no or it.plate_number or it.seal_no or it.driver_phone or it.driver_name or it.eta
                for it in h_items
            )
            if has_key:
                return False

        if h_intent == "PARSE_TRUCK_INFO" and h_items:
            all_clear = all(
                it.plate_number and it.container_no and it.driver_name and it.confidence >= 0.72
                for it in h_items
            )
            if all_clear:
                return False

        return True

    @classmethod
    async def extract(cls, req: ExtractRequest) -> ExtractResponse:
        """Thực thi pipeline ưu tiên Heuristic nội bộ trước -> chỉ gọi Cloud LLM khi thực sự cần."""
        t0 = time.perf_counter()

        # 1. Che toàn bộ SĐT trong tin nhắn chính, quote và ngữ cảnh trước khi xử lý
        masked_msg = PrivacyMasker.mask_text(req.message_text)
        phone_map = dict(masked_msg.phone_map)

        masked_quote = None
        if req.quote_message:
            q_res = PrivacyMasker.mask_text(req.quote_message, existing_map=phone_map)
            masked_quote = q_res.masked_text
            phone_map = q_res.phone_map

        masked_ctx: list[str] = []
        for cm in req.context_messages:
            c_res = PrivacyMasker.mask_text(cm, existing_map=phone_map)
            masked_ctx.append(c_res.masked_text)
            phone_map = c_res.phone_map

        # 2. Chạy bộ bóc tách Heuristic / Rule nội bộ trước (0 token Cloud LLM, < 1ms)
        fb_intent, fb_items = heuristic_extract(masked_msg.masked_text, quote_message=masked_quote)
        if not cls._needs_cloud_llm(req, fb_intent, fb_items):
            for ent in fb_items:
                ent.driver_phone = PrivacyMasker.restore_value(ent.driver_phone, phone_map)
                ent.evidence = PrivacyMasker.restore_value(ent.evidence, phone_map)
            return ExtractResponse(
                intent=fb_intent,
                is_multi_vehicle=len(fb_items) > 1,
                items=fb_items,
                model_name="local-heuristic-v1",
                prompt_version=PROMPT_VERSION,
                raw_masked_text=masked_msg.masked_text,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        # 3. Chỉ gọi Cloud AI Provider khi heuristic chưa đủ độ tin cậy / tin phức tạp
        provider = get_ai_provider()
        user_prompt = build_user_prompt(
            masked_message=masked_msg.masked_text,
            masked_quote=masked_quote,
            context_messages=masked_ctx,
            active_plans=req.active_plans,
        )
        llm_res = await provider.generate_structured_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        if llm_res.success and isinstance(llm_res.parsed, dict):
            raw_items = llm_res.parsed.get("items") or []
            if isinstance(raw_items, list):
                entities = cls._map_llm_items(raw_items, phone_map)
                intent = cls._normalize_intent(
                    llm_res.parsed.get("intent"),
                    masked_msg.masked_text,
                    masked_quote,
                    len(entities),
                )
                latency_ms = llm_res.latency_ms or int((time.perf_counter() - t0) * 1000)
                return ExtractResponse(
                    intent=intent,
                    is_multi_vehicle=bool(llm_res.parsed.get("is_multi_vehicle")) or len(entities) > 1,
                    items=entities,
                    model_name=llm_res.model_name or settings.AI_MODEL_NAME,
                    prompt_version=PROMPT_VERSION,
                    raw_masked_text=masked_msg.masked_text,
                    latency_ms=latency_ms,
                )

        # 4. Fallback về kết quả rule heuristic nếu Cloud AI ngoại tuyến hoặc lỗi
        for ent in fb_items:
            ent.driver_phone = PrivacyMasker.restore_value(ent.driver_phone, phone_map)
            ent.evidence = PrivacyMasker.restore_value(ent.evidence, phone_map)

        return ExtractResponse(
            intent=fb_intent,
            is_multi_vehicle=len(fb_items) > 1,
            items=fb_items,
            model_name="rule_offline_fallback",
            prompt_version=PROMPT_VERSION,
            raw_masked_text=masked_msg.masked_text,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
