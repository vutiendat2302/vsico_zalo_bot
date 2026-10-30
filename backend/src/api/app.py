"""Module Khởi Tạo Ứng Dụng FastAPI & Định Tuyến Endpoint (API Application Factory).

Gắn kết các Router (`/webhook`, `/api/messages`, `/api/health`), đăng ký hàm xử lý
`ExtractionHandler.process_message_by_id` vào hàng đợi `FIFOExtractionQueue` và khởi chạy
Worker nền khi ứng dụng bắt đầu hoạt động.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.dashboard import router as dashboard_router
from src.api.groups import router as groups_router
from src.api.messages import router as messages_router
from src.api.outbound import outbound_router
from src.api.plans import router as plans_router
from src.api.reviews import router as reviews_router
from src.api.webhook import router as webhook_router
from src.handlers.extraction_handler import ExtractionHandler
from src.infrastructure.database import get_db
from src.infrastructure.fifo_queue import fifo_queue
from src.infrastructure.models import ContainerJob, TruckRecord, ZaloMessage

# Đăng ký bộ xử lý bóc tách vào hàng đợi FIFO ngay khi nạp module
fifo_queue.register_processor(ExtractionHandler.process_message_by_id)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Quản lý vòng đời ứng dụng FastAPI: Khởi động và dừng luồng FIFO Worker an toàn.

    Args:
        _app (FastAPI): Thực thể ứng dụng FastAPI.
    """
    fifo_queue.start_background_worker()
    try:
        yield
    finally:
        fifo_queue.stop_background_worker()


def create_app() -> FastAPI:
    """Khởi tạo và cấu hình thực thể ứng dụng FastAPI cho VSICO Zalo Bot Backend.

    Returns:
        FastAPI: Ứng dụng FastAPI đã gắn đầy đủ Router và Lifespan.
    """
    application = FastAPI(
        title="VSICO Zalo Logistics Bot Backend",
        version="2.0.0",
        description=(
            "Hệ thống tiếp nhận tin nhắn Zalo thời gian thực (Direct & Group), "
            "bóc tách thông tin xe/container tuần tự Vào Trước - Ra Trước (FIFO), "
            "kiểm tra chuẩn ISO 6346 Mod 11 và cung cấp API truy vấn theo thời gian."
        ),
        lifespan=lifespan,
    )

    @application.get("/api/health", tags=["0. Giám Sát Hệ Thống (Health)"])
    def health_check(db: Session = Depends(get_db)) -> dict[str, Any]:
        """Kiểm tra trạng thái kết nối MySQL, thống kê số lượng bản ghi và trạng thái hàng đợi FIFO.

        Args:
            db (Session): Phiên làm việc SQLAlchemy.

        Returns:
            dict[str, Any]: Thông tin sức khỏe hệ thống và bộ đếm dữ liệu.
        """
        msg_count = db.scalar(select(func.count(ZaloMessage.id))) or 0
        truck_count = db.scalar(select(func.count(TruckRecord.id))) or 0
        cont_count = db.scalar(select(func.count(ContainerJob.id))) or 0
        return {
            "ok": True,
            "status": "OK",
            "database": "mysql_connected",
            "total_messages": msg_count,
            "total_trucks_extracted": truck_count,
            "total_containers_extracted": cont_count,
            "fifo_queue": fifo_queue.stats(),
        }

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(webhook_router)
    application.include_router(messages_router)
    application.include_router(plans_router)
    application.include_router(dashboard_router)
    application.include_router(reviews_router)
    application.include_router(outbound_router)
    application.include_router(groups_router)
    return application


app = create_app()
