"""Router giải quyết đối chiếu địa chỉ kho nhiều tầng (Habit -> Fuzzy -> Vector -> LLM)."""

from fastapi import APIRouter, Depends

from app.core.security import verify_internal_token
from app.schemas.warehouse import MatchWarehouseRequest, MatchWarehouseResponse
from app.warehouse.matcher import WarehouseMatcherService

router = APIRouter(prefix="/api/v1", tags=["3. Map Địa Chỉ Kho"])


@router.post("/match-warehouse", response_model=MatchWarehouseResponse)
async def match_warehouse(
    payload: MatchWarehouseRequest,
    _auth: str = Depends(verify_internal_token),
) -> MatchWarehouseResponse:
    """Đối chiếu địa chỉ kho nhập tự do qua các tầng Habit, Fuzzy, Vector Qdrant và LLM."""
    return await WarehouseMatcherService.match(payload)
