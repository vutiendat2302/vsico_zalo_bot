"""Module Khởi Tạo Ứng Dụng FastAPI & Định Tuyến Endpoint (API Application Factory).

Gắn kết các Router (`/webhook`, `/api/messages`, `/api/health`), đăng ký hàm xử lý
`ExtractionHandler.process_message_by_id` vào hàng đợi `FIFOExtractionQueue` và khởi chạy
Worker nền khi ứng dụng bắt đầu hoạt động.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.auth import router as auth_router
from src.api.dashboard import router as dashboard_router
from src.api.files import router as files_router
from src.api.groups import router as groups_router
from src.api.master_data import router as master_data_router
from src.api.messages import router as messages_router
from src.api.outbound import outbound_router
from src.api.plans import router as plans_router
from src.api.reviews import router as reviews_router
from src.api.sandbox import router as sandbox_router
from src.api.users import router as users_router
from src.api.webhook import router as webhook_router
from src.domain.enums import GroupRole, SendMode, UserRole
from src.handlers.extraction_handler import ExtractionHandler
from src.infrastructure.database import SessionLocal, get_db
from src.infrastructure.fifo_queue import fifo_queue
from src.infrastructure.models import ContainerJob, TruckRecord, User, ZaloGroup, ZaloMessage

# Đăng ký bộ xử lý bóc tách vào hàng đợi FIFO ngay khi nạp module
fifo_queue.register_processor(ExtractionHandler.process_message_by_id)


def seed_initial_users() -> None:
    """Tự động đồng bộ nhóm thật từ Zalo Bridge và khởi tạo tài khoản admin nếu chưa tồn tại."""
    try:
        from src.api.groups import sync_live_groups_from_bridge

        with SessionLocal() as db:
            # 1. Đồng bộ danh sách nhóm thật từ Zalo Bridge (nếu Bridge đang chạy)
            sync_live_groups_from_bridge(db)
            dhvt_grp = db.scalar(
                select(ZaloGroup).where(
                    ZaloGroup.group_role == GroupRole.DHVT.value,
                    ZaloGroup.is_test.is_(False),
                )
            )

            # 2. Kiểm tra xem hệ thống đã có tài khoản quản trị admin hay chưa
            admin_user = db.scalar(
                select(User).where(or_(User.username == "admin", User.role.in_([UserRole.ADMIN.value, "admin"])))
            )
            if not admin_user:
                from src.infrastructure.security import hash_password
                from src.infrastructure.snowflake import snowflake

                new_admin = User(
                    id=snowflake.generate(),
                    username="admin",
                    full_name="Quản Trị Viên Hệ Thống",
                    role=UserRole.ADMIN.value,
                    email="admin@vsico.com.vn",
                    password_hash=hash_password("123456"),
                    zalo_user_id="2025593064656318114",
                    zalo_info_id=dhvt_grp.id if dhvt_grp else None,
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(new_admin)
                db.commit()
            elif dhvt_grp and admin_user.zalo_info_id != dhvt_grp.id:
                admin_user.zalo_info_id = dhvt_grp.id
                db.commit()
    except Exception as exc:
        print(f"[SEED WARN] Không thể tự động kiểm tra/khởi tạo tài khoản admin: {exc}")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Quản lý vòng đời ứng dụng FastAPI: Khởi động và dừng luồng FIFO Worker an toàn.

    Args:
        _app (FastAPI): Thực thể ứng dụng FastAPI.
    """
    seed_initial_users()
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

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Bắt và chuẩn hóa toàn bộ lỗi xác thực Pydantic (HTTP 422) thành định dạng ApiResponse và Form Errors."""
        field_labels: dict[str, str] = {
            "username": "Tên đăng nhập",
            "password": "Mật khẩu",
            "email": "Email",
            "full_name": "Họ và tên",
            "role": "Vai trò",
            "zalo_user_id": "Zalo User ID",
            "zalo_info_id": "Zalo Group ID",
            "tms_user_id": "TMS User ID",
            "forwarder_id": "Forwarder ID",
            "is_active": "Trạng thái kích hoạt",
            "truck_plate": "Biển số xe",
            "trailer_plate": "Biển số rơ-moóc",
            "driver_name": "Tên tài xế",
            "driver_phone": "Số điện thoại tài xế",
            "container_no": "Số container",
            "seal_no": "Số seal",
            "eta_text": "Thời gian dự kiến (ETA)",
        }

        errors: list[dict[str, Any]] = []
        for err in exc.errors():
            loc_parts = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            field_name = ".".join(loc_parts) if loc_parts else "general"
            err_type = str(err.get("type", "invalid"))
            raw_msg = str(err.get("msg", ""))
            label = field_labels.get(field_name, field_name)

            if "missing" in err_type:
                msg = f"{label} là thông tin bắt buộc, không được để trống."
            elif "too_short" in err_type or "min_length" in err_type:
                ctx = err.get("ctx", {})
                min_len = ctx.get("min_length", ctx.get("limit_value", ""))
                msg = f"{label} phải có độ dài tối thiểu {min_len} ký tự."
            elif "too_long" in err_type or "max_length" in err_type:
                ctx = err.get("ctx", {})
                max_len = ctx.get("max_length", ctx.get("limit_value", ""))
                msg = f"{label} không được vượt quá {max_len} ký tự."
            elif "string_type" in err_type:
                msg = f"{label} phải là chuỗi văn bản."
            elif "int_type" in err_type or "int_parsing" in err_type:
                msg = f"{label} phải là số nguyên hợp lệ."
            elif "value_error" in err_type:
                msg = raw_msg
            else:
                msg = f"{label}: {raw_msg}"

            errors.append({
                "field": field_name,
                "message": msg,
                "code": err_type,
            })

        error_summary = (
            f"Dữ liệu gửi lên không hợp lệ ({len(errors)} lỗi): {errors[0]['message']}"
            if errors
            else "Dữ liệu gửi lên không hợp lệ."
        )

        content = {
            "ok": False,
            "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "message": error_summary,
            "detail": error_summary,
            "data": None,
            "errors": errors,
            "meta": None,
        }
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=content)

    @application.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        """Bắt và chuẩn hóa toàn bộ HTTPException nghiệp vụ thành cấu trúc ApiResponse."""
        detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        content = {
            "ok": False,
            "status_code": exc.status_code,
            "message": detail_msg,
            "detail": detail_msg,
            "data": None,
            "errors": [],
            "meta": None,
        }
        return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)

    @application.exception_handler(Exception)
    async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        """Bắt và ghi nhận lỗi ngoại lệ không mong muốn, trả về phản hồi 500 đồng nhất."""
        err_msg = str(exc)
        content = {
            "ok": False,
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "message": "Đã xảy ra lỗi máy chủ nội bộ. Vui lòng liên hệ quản trị viên.",
            "detail": "Đã xảy ra lỗi máy chủ nội bộ. Vui lòng liên hệ quản trị viên.",
            "data": None,
            "errors": [{"field": "server", "message": err_msg, "code": "internal_error"}],
            "meta": None,
        }
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)

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

    application.include_router(auth_router)
    application.include_router(users_router)
    application.include_router(webhook_router)
    application.include_router(messages_router)
    application.include_router(plans_router)
    application.include_router(dashboard_router)
    application.include_router(reviews_router)
    application.include_router(outbound_router)
    application.include_router(groups_router)
    application.include_router(master_data_router)
    application.include_router(files_router)
    application.include_router(sandbox_router)
    return application


app = create_app()
