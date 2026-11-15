"""Tầng 3 (Vector Search): Tra cứu ngữ nghĩa địa chỉ kho trên Qdrant Vector DB."""

from typing import Any

import httpx

from app.core.config import settings


async def match_by_vector(
    raw_address: str,
    customer_id: int | None,
    candidates: list[dict[str, Any]],
    query_vector: list[float] | None = None,
    threshold: float = 0.80,
) -> tuple[dict[str, Any], float] | None:
    """Truy vấn Qdrant collection khi có vector embedding 768 chiều hợp lệ."""
    if not settings.QDRANT_URL or not query_vector or len(query_vector) != 768:
        return None

    url = (
        f"{settings.QDRANT_URL.rstrip('/')}/collections/"
        f"{settings.QDRANT_COLLECTION_WAREHOUSES}/points/search"
    )
    body: dict[str, Any] = {
        "vector": query_vector,
        "limit": 3,
        "with_payload": True,
    }
    if customer_id is not None:
        body["filter"] = {
            "must": [{"key": "customer_id", "match": {"value": customer_id}}]
        }

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(url, json=body)
        if resp.status_code != 200:
            return None
        hits = (resp.json() or {}).get("result") or []
        if not hits:
            return None
        top = hits[0]
        score = float(top.get("score") or 0.0)
        if score < threshold:
            return None
        payload = top.get("payload") or {}
        wh_id = payload.get("warehouse_id")
        matched_wh = next((w for w in candidates if str(w.get("id")) == str(wh_id)), None)
        if matched_wh:
            return matched_wh, round(score, 4)
        return ({"id": wh_id, "name": payload.get("warehouse_name")}, round(score, 4))
    except (httpx.HTTPError, ValueError, TypeError):
        return None
