"""Bộ điều phối chiến lược Map địa chỉ kho tuần tự nhiều tầng: habit -> fuzzy -> vector -> llm."""

from typing import Any

from app.schemas.warehouse import MatchWarehouseRequest, MatchWarehouseResponse
from app.warehouse.fuzzy import match_by_fuzzy
from app.warehouse.habit import match_by_habit
from app.warehouse.llm import match_by_llm
from app.warehouse.vector import match_by_vector


class WarehouseMatcherService:
    """Chạy tuần tự từng tầng map kho và dừng ngay ở tầng đầu tiên đủ độ tin cậy."""

    @staticmethod
    def _filter_candidates(req: MatchWarehouseRequest) -> list[dict[str, Any]]:
        """Ưu tiên lọc ứng viên theo `customer_id` nếu backend cung cấp."""
        if not req.candidate_warehouses:
            return []
        if req.customer_id is not None:
            filtered = [
                w for w in req.candidate_warehouses
                if w.get("customer_id") is None or str(w.get("customer_id")) == str(req.customer_id)
            ]
            if filtered:
                return filtered
        return req.candidate_warehouses

    @classmethod
    async def match(cls, req: MatchWarehouseRequest) -> MatchWarehouseResponse:
        """Tìm kho khớp nhất cho chuỗi `raw_address`, trả `unresolved` nếu chưa đủ tin cậy."""
        candidates = cls._filter_candidates(req)
        if not req.raw_address.strip() or not candidates:
            return MatchWarehouseResponse(matched=False, source="unresolved", confidence=0.0)

        # Tầng 1: Thói quen nhà xe & bí danh khớp chính xác
        habit_hit = match_by_habit(req.raw_address, req.carrier_id, candidates)
        if habit_hit:
            wh, conf = habit_hit
            return MatchWarehouseResponse(
                matched=True,
                warehouse_id=int(wh["id"]) if wh.get("id") is not None else None,
                warehouse_name=wh.get("name"),
                confidence=conf,
                source="habit",
            )

        # Tầng 2: Khớp chuỗi mờ tiếng Việt không dấu
        fuzzy_hit = match_by_fuzzy(req.raw_address, candidates)
        if fuzzy_hit:
            wh, conf = fuzzy_hit
            return MatchWarehouseResponse(
                matched=True,
                warehouse_id=int(wh["id"]) if wh.get("id") is not None else None,
                warehouse_name=wh.get("name"),
                confidence=conf,
                source="fuzzy",
            )

        # Tầng 3: Vector DB Qdrant (bỏ qua an toàn nếu chưa cấu hình embedding/Qdrant)
        vector_hit = await match_by_vector(req.raw_address, req.customer_id, candidates)
        if vector_hit:
            wh, conf = vector_hit
            return MatchWarehouseResponse(
                matched=True,
                warehouse_id=int(wh["id"]) if wh.get("id") is not None else None,
                warehouse_name=wh.get("name"),
                confidence=conf,
                source="vector",
            )

        # Tầng 4: LLM chọn ứng viên phù hợp nhất
        llm_hit = await match_by_llm(req.raw_address, candidates)
        if llm_hit:
            wh, conf = llm_hit
            return MatchWarehouseResponse(
                matched=True,
                warehouse_id=int(wh["id"]) if wh.get("id") is not None else None,
                warehouse_name=wh.get("name"),
                confidence=conf,
                source="llm",
            )

        return MatchWarehouseResponse(matched=False, source="unresolved", confidence=0.0)
