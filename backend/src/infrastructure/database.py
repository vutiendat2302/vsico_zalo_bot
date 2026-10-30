"""Module Kết Nối Cơ Sở Dữ Liệu MySQL (SQLAlchemy 2.0 Database Engine & Session).

Thiết lập kết nối tới MySQL 8.4 thông qua SQLAlchemy 2.0:
- `engine`: Quản lý connection pool tới MySQL với `pool_pre_ping=True` chống đứt kết nối.
- `SessionLocal`: Nhà máy khởi tạo phiên giao dịch (Session) cho mỗi request và worker.
- `Base`: Lớp cơ sở DeclarativeBase cho toàn bộ 17 bảng dữ liệu.
- `get_db`: Dependency Injection cung cấp phiên làm việc DB cho các endpoint FastAPI.
"""

from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from ..config.settings import settings


class Base(DeclarativeBase):
    """Lớp cơ sở (Declarative Base) của SQLAlchemy 2.0 cho mọi bảng trong MySQL."""

    pass


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency cung cấp phiên làm việc (Database Session) cho mỗi HTTP Request.

    Yields:
        Session: Đối tượng phiên làm việc SQLAlchemy 2.0.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
