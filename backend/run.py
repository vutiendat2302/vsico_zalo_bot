"""Điểm khởi chạy máy chủ FastAPI Backend (Entrypoint).

Cách chạy:
    .venv/bin/python run.py
"""

import uvicorn
from src.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=(settings.APP_ENV == "development"),
    )
