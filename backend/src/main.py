"""Điểm Khởi Chạy Chính Của Ứng Dụng FastAPI (Application Entrypoint).

Xuất khẩu đối tượng `app` từ `src.api.app` để Uvicorn (`run.py` hoặc `uvicorn src.main:app`)
khởi chạy máy chủ HTTP.
"""

from src.api.app import app, create_app

__all__ = ["app", "create_app"]
