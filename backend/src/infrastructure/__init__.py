"""Package Hạ Tầng Cơ Sở Dữ Liệu & Hàng Đợi (Infrastructure Layer).

Cung cấp kết nối SQLAlchemy tới MySQL 8.4, tập hợp 17 ORM Models và hàng đợi xử lý
tin nhắn tuần tự Vào Trước Ra Trước (`FIFOExtractionQueue`).
"""

from src.infrastructure.database import Base, SessionLocal, engine, get_db
from src.infrastructure.fifo_queue import FIFOExtractionQueue, fifo_queue
from src.infrastructure.models import (
    ActivityLog,
    BotReply,
    ContainerJob,
    Customer,
    CustomerAlias,
    ExtractionRun,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    RouteMap,
    TmsSyncLog,
    TransportPlan,
    TruckRecord,
    User,
    Warehouse,
    WarehouseAlias,
    ZaloGroup,
    ZaloMessage,
)

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "FIFOExtractionQueue",
    "fifo_queue",
    "ZaloGroup",
    "Customer",
    "Warehouse",
    "CustomerAlias",
    "WarehouseAlias",
    "TransportPlan",
    "ZaloMessage",
    "ExtractionRun",
    "TruckRecord",
    "ContainerJob",
    "RouteMap",
    "ReviewCase",
    "BotReply",
    "OutboundMessage",
    "OutboundMessageItem",
    "TmsSyncLog",
    "ActivityLog",
    "User",
]
