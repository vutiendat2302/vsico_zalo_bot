"""Điểm khởi chạy ứng dụng FastAPI AI & OCR Microservice.

Chạy tại cổng mặc định 8001. Chỉ phục vụ giao tiếp nội bộ cho Backend.
"""

from typing import Any
from fastapi import FastAPI
from app.core.config import settings
from app.routers.extract import router as extract_router
from app.routers.ocr import router as ocr_router
from app.routers.warehouse import router as warehouse_router

app = FastAPI(
    title="VSICO AI & OCR Microservice",
    description="Dịch vụ đọc hiểu ngữ cảnh hội thoại Zalo, bóc tách NLP & Map địa chỉ kho thông minh",
    version="1.0.0",
)

# Gắn các internal router
app.include_router(extract_router)
app.include_router(ocr_router)
app.include_router(warehouse_router)


@app.get("/health", tags=["0. Giám Sát"])
def health_check() -> dict[str, Any]:
    """Kiểm tra sức khỏe dịch vụ AI Microservice."""
    return {
        "status": "UP",
        "service": "vsico-ai-service",
        "env": settings.APP_ENV,
        "model_name": settings.AI_MODEL_NAME,
        "qdrant_url": settings.QDRANT_URL,
        "paddle_ocr_url": settings.PADDLE_OCR_URL,
    }
