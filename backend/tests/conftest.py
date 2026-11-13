"""Cấu hình Pytest dùng chung cho Backend VSICO Zalo Bot.

Sử dụng giao dịch lồng (`join_transaction_mode="create_savepoint"`) trên kết nối MySQL thật
nhằm đảm bảo toàn bộ kiểm thử tích hợp chạy sát môi trường thực tế nhưng tự động rollback
khi kết thúc test, không để lại dữ liệu rác.
"""

import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.api.app import app
from src.infrastructure.database import engine, get_db


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Cung cấp SQLAlchemy Session cô lập trong SAVEPOINT và tự động rollback sau mỗi test."""
    connection = engine.connect()
    outer_tx = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer_tx.rollback()
        connection.close()


@pytest.fixture()
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient ghi đè dependency `get_db` dùng cùng session cô lập."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolate_background_workers(monkeypatch):
    """Không cho test khởi chạy worker hoặc seed trên dữ liệu vận hành thật."""
    from src.infrastructure.fifo_queue import fifo_queue
    import importlib
    app_module = importlib.import_module("src.api.app")
    monkeypatch.setattr(fifo_queue, "start_background_worker", lambda: None)
    monkeypatch.setattr(fifo_queue, "stop_background_worker", lambda: None)
    monkeypatch.setattr(app_module, "seed_initial_users", lambda: None)
