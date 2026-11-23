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
        from src.config.settings import settings
        with TestClient(app) as client:
            client.headers["X-Webhook-Secret"] = settings.ZALO_SECRET_KEY or ""
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def proxy_zalo_outbox():
    """Trả về danh sách tin nhắn Zalo đã được ghi vào Proxy Sink trong phiên test hiện tại."""
    from src.infrastructure.zalo_dispatcher import ZaloDispatcher

    ZaloDispatcher.clear_proxy_outbox()
    return ZaloDispatcher._proxy_outbox


@pytest.fixture(autouse=True)
def isolate_background_workers(monkeypatch):
    """Không cho test khởi chạy worker, gọi TMS thật, gửi Zalo thật hoặc seed trên dữ liệu vận hành thật."""
    from src.config.settings import settings
    from src.infrastructure.fifo_queue import fifo_queue
    from src.infrastructure.zalo_dispatcher import ZaloDispatcher
    from src.infrastructure.zalo_watchdog import ZaloOaWatchdog, zalo_watchdog
    import importlib
    app_module = importlib.import_module("src.api.app")
    ZaloDispatcher.clear_proxy_outbox()
    monkeypatch.setattr(fifo_queue, "start_background_worker", lambda: None)
    monkeypatch.setattr(fifo_queue, "stop_background_worker", lambda: None)
    monkeypatch.setattr(app_module, "seed_initial_users", lambda: None)
    monkeypatch.setattr(settings, "TMS_WRITE_ENABLED", False)
    monkeypatch.setattr(settings, "AUTO_DISPATCH_OUTBOUND", False)
    monkeypatch.setattr(settings, "GROUP_PROCESS_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "ZALO_PROXY_ONLY", True)
    monkeypatch.setattr(settings, "ZALO_WATCHDOG_ENABLED", False)
    monkeypatch.setattr(settings, "ZALO_OVERDUE_ESCALATION_ENABLED", False)
    monkeypatch.setattr(zalo_watchdog, "start", lambda: None)
    monkeypatch.setattr(zalo_watchdog, "stop", lambda: None)
    monkeypatch.setattr(
        ZaloOaWatchdog,
        "check_bridge_health",
        lambda self: {"ok": True, "status": "HEALTHY", "proxy": True},
    )
    monkeypatch.setattr(ZaloOaWatchdog, "_emit_alert", lambda self, *a, **kw: None)
    monkeypatch.setattr(ZaloOaWatchdog, "_emit_recovery", lambda self, *a, **kw: None)
    monkeypatch.setattr(
        ZaloDispatcher,
        "send_to_group",
        classmethod(
            lambda cls, group_id, message, quote_msg_id=None, **kw: cls._record_proxy(
                kind="group_text",
                target_id=group_id,
                message=message,
                quote_msg_id=quote_msg_id,
            )
        ),
    )
    monkeypatch.setattr(
        ZaloDispatcher,
        "send_image_to_group",
        classmethod(
            lambda cls, group_id, image_url, caption="", quote_msg_id=None, **kw: cls._record_proxy(
                kind="group_image",
                target_id=group_id,
                message=caption or "Báo cáo hình ảnh",
                quote_msg_id=quote_msg_id,
                image_url=image_url,
            )
        ),
    )
    monkeypatch.setattr(
        ZaloDispatcher,
        "send_to_user",
        classmethod(
            lambda cls, user_id, message, **kw: cls._record_proxy(
                kind="user_text",
                target_id=user_id,
                message=message,
            )
        ),
    )
