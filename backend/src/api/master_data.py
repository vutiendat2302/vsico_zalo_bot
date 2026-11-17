"""Module REST API Chỉ Đọc Cho Dữ Liệu Danh Mục TMS (Master Data APIs).

Cung cấp các endpoint tra cứu, tìm kiếm và lọc dữ liệu đồng bộ từ hệ thống TMS:
1. Danh sách nhà xe: `GET /api/master/carriers`
2. Danh sách tùy chọn nhà xe cho dropdown: `GET /api/master/carriers/options`
3. Danh sách tài xế: `GET /api/master/drivers`
4. Danh sách xe đầu kéo / rơ-moóc: `GET /api/master/vehicles`
5. Danh sách khách hàng: `GET /api/master/customers`
6. Danh sách kho khách hàng / cảng / depot: `GET /api/master/warehouses`
"""

import math
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.plans import parse_date_str
from src.api.schemas import TransportPlanOut
from src.handlers.tms_auto_sync import sync_trailers_from_tms, tms_auto_sync
from src.handlers.tms_plan_sync_service import build_master_plan_summary
from src.infrastructure.database import get_db
from src.infrastructure.models import Carrier, Customer, Driver, Trailer, TransportPlan, User, Vehicle, Warehouse
from src.infrastructure.security import get_current_user
from src.infrastructure.tms_client import TmsApiError

router = APIRouter(prefix="/api/master", tags=["8. Dữ Liệu Danh Mục TMS (Master Data)"])


class CarrierOptionOut(BaseModel):
    """Schema tùy chọn nhà xe dùng cho bộ lọc dropdown."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str
    code: Optional[str] = None
    name: str
    short_name: Optional[str] = None


class CarrierOut(BaseModel):
    """Schema thông tin nhà xe trả về cho Frontend."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str
    tms_carrier_id: str
    code: Optional[str] = None
    name: str
    short_name: Optional[str] = None
    tax_code: Optional[str] = None
    is_active: bool
    vehicle_count: int = 0
    driver_count: int = 0


class DriverOut(BaseModel):
    """Schema thông tin tài xế trả về cho Frontend."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str
    tms_driver_id: str
    carrier_id: Optional[str] = None
    carrier_name: Optional[str] = None
    full_name: str
    phone: Optional[str] = None
    identity_no: Optional[str] = None
    license_no: Optional[str] = None
    is_active: bool


class VehicleOut(BaseModel):
    """Schema thông tin xe đầu kéo / rơ-moóc trả về cho Frontend."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str
    tms_vehicle_id: str
    carrier_id: Optional[str] = None
    carrier_name: Optional[str] = None
    plate_no: str
    vehicle_type: Optional[int] = None
    payload_capacity: Optional[float] = None
    driver_hint_name: Optional[str] = None
    is_active: bool


class CustomerOut(BaseModel):
    """Schema thông tin khách hàng trả về cho Frontend."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str
    tms_customer_id: str
    name: str
    normalized_name: str
    is_active: bool
    warehouse_count: int = 0


class WarehouseOut(BaseModel):
    """Schema thông tin kho khách hàng / cảng / depot trả về cho Frontend."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str
    tms_warehouse_id: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    location_type: str
    name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: bool


class PaginatedCarriersResponse(BaseModel):
    """Phản hồi phân trang danh sách nhà xe."""

    items: list[CarrierOut]
    total: int
    page: int
    per_page: int
    total_pages: int


class PaginatedDriversResponse(BaseModel):
    """Phản hồi phân trang danh sách tài xế."""

    items: list[DriverOut]
    total: int
    page: int
    per_page: int
    total_pages: int


class PaginatedVehiclesResponse(BaseModel):
    """Phản hồi phân trang danh sách xe đầu kéo."""

    items: list[VehicleOut]
    total: int
    page: int
    per_page: int
    total_pages: int


class TrailerOut(BaseModel):
    """Thông tin rơ-moóc (moóc) chuẩn đồng bộ từ TMS."""

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)

    id: str
    tms_mooc_id: str
    tms_carrier_id: Optional[str] = None
    carrier_id: Optional[str] = None
    carrier_name: Optional[str] = None
    carrier_short_name: Optional[str] = None
    license_plate: str
    normalized_plate: str
    mooc_type: Optional[int] = None
    model: Optional[str] = None
    note: Optional[str] = None
    is_active: bool
    synced_at: Optional[str] = None


class PaginatedTrailersResponse(BaseModel):
    """Phản hồi phân trang danh sách rơ-moóc kèm danh sách model lọc."""

    items: list[TrailerOut]
    total: int
    page: int
    per_page: int
    total_pages: int
    filter_options: dict[str, list[str]] = {"models": []}


class PaginatedCustomersResponse(BaseModel):
    """Phản hồi phân trang danh sách khách hàng."""

    items: list[CustomerOut]
    total: int
    page: int
    per_page: int
    total_pages: int


class PaginatedWarehousesResponse(BaseModel):
    """Phản hồi phân trang danh sách kho khách hàng."""

    items: list[WarehouseOut]
    total: int
    page: int
    per_page: int
    total_pages: int


def _calc_total_pages(total: int, per_page: int) -> int:
    """Tính tổng số trang dựa trên tổng bản ghi và kích thước trang."""
    return max(1, math.ceil(total / per_page)) if total > 0 else 1


@router.get("/carriers/options", response_model=list[CarrierOptionOut])
def list_carrier_options(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[CarrierOptionOut]:
    """Lấy danh sách rút gọn các nhà xe phục vụ bộ lọc dropdown."""
    rows = db.scalars(select(Carrier).order_by(Carrier.name.asc())).all()
    return [CarrierOptionOut.model_validate(row) for row in rows]


@router.get("/carriers", response_model=PaginatedCarriersResponse)
def list_carriers(
    search: Optional[str] = Query(default=None, description="Tìm theo tên, tên viết tắt, mã hoặc MST"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái hoạt động"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedCarriersResponse:
    """Tra cứu danh sách nhà xe có phân trang, tìm kiếm và lọc trạng thái."""
    stmt = select(Carrier)
    count_stmt = select(func.count(Carrier.id))

    if search and search.strip():
        kw = f"%{search.strip()}%"
        cond = or_(
            Carrier.name.ilike(kw),
            Carrier.short_name.ilike(kw),
            Carrier.code.ilike(kw),
            Carrier.tax_code.ilike(kw),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if is_active is not None:
        stmt = stmt.where(Carrier.is_active == is_active)
        count_stmt = count_stmt.where(Carrier.is_active == is_active)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(Carrier.name.asc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    carrier_ids = [r.id for r in rows]
    vehicle_counts: dict[int, int] = {}
    driver_counts: dict[int, int] = {}
    if carrier_ids:
        for cid, cnt in db.execute(
            select(Vehicle.carrier_id, func.count(Vehicle.id))
            .where(Vehicle.carrier_id.in_(carrier_ids))
            .group_by(Vehicle.carrier_id)
        ).all():
            if cid is not None:
                vehicle_counts[cid] = cnt
        for cid, cnt in db.execute(
            select(Driver.carrier_id, func.count(Driver.id))
            .where(Driver.carrier_id.in_(carrier_ids))
            .group_by(Driver.carrier_id)
        ).all():
            if cid is not None:
                driver_counts[cid] = cnt

    items = [
        CarrierOut(
            id=str(r.id),
            tms_carrier_id=str(r.tms_carrier_id),
            code=r.code,
            name=r.name,
            short_name=r.short_name,
            tax_code=r.tax_code,
            is_active=r.is_active,
            vehicle_count=vehicle_counts.get(r.id, 0),
            driver_count=driver_counts.get(r.id, 0),
        )
        for r in rows
    ]

    return PaginatedCarriersResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_calc_total_pages(total, per_page),
    )


@router.get("/drivers", response_model=PaginatedDriversResponse)
def list_drivers(
    search: Optional[str] = Query(default=None, description="Tìm theo tên, SĐT, CCCD hoặc GPLX"),
    carrier_id: Optional[str] = Query(default=None, description="Lọc theo ID nhà xe"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái hoạt động"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedDriversResponse:
    """Tra cứu danh sách tài xế có phân trang, tìm kiếm và lọc theo nhà xe / trạng thái."""
    stmt = select(Driver, Carrier.name.label("carrier_name")).outerjoin(
        Carrier, Driver.carrier_id == Carrier.id
    )
    count_stmt = select(func.count(Driver.id))

    if search and search.strip():
        kw = f"%{search.strip()}%"
        cond = or_(
            Driver.full_name.ilike(kw),
            Driver.phone.ilike(kw),
            Driver.identity_no.ilike(kw),
            Driver.license_no.ilike(kw),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if carrier_id and carrier_id.strip():
        try:
            cid = int(carrier_id.strip())
            stmt = stmt.where(Driver.carrier_id == cid)
            count_stmt = count_stmt.where(Driver.carrier_id == cid)
        except ValueError:
            pass

    if is_active is not None:
        stmt = stmt.where(Driver.is_active == is_active)
        count_stmt = count_stmt.where(Driver.is_active == is_active)

    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        stmt.order_by(Driver.full_name.asc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    items = [
        DriverOut(
            id=str(drv.id),
            tms_driver_id=str(drv.tms_driver_id),
            carrier_id=str(drv.carrier_id) if drv.carrier_id is not None else None,
            carrier_name=carrier_name,
            full_name=drv.full_name,
            phone=drv.phone,
            identity_no=drv.identity_no,
            license_no=drv.license_no,
            is_active=drv.is_active,
        )
        for drv, carrier_name in rows
    ]

    return PaginatedDriversResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_calc_total_pages(total, per_page),
    )


@router.get("/vehicles", response_model=PaginatedVehiclesResponse)
def list_vehicles(
    search: Optional[str] = Query(default=None, description="Tìm theo biển số xe hoặc tên tài xế"),
    vehicle_type: Optional[int] = Query(default=None, description="Lọc loại xe (1=Đầu kéo, 2=Rơ-moóc)"),
    carrier_id: Optional[str] = Query(default=None, description="Lọc theo ID nhà xe"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái hoạt động"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedVehiclesResponse:
    """Tra cứu danh sách xe đầu kéo / rơ-moóc có phân trang, tìm kiếm và lọc."""
    stmt = select(Vehicle, Carrier.name.label("carrier_name")).outerjoin(
        Carrier, Vehicle.carrier_id == Carrier.id
    )
    count_stmt = select(func.count(Vehicle.id))

    if search and search.strip():
        kw = f"%{search.strip()}%"
        cond = or_(
            Vehicle.plate_no.ilike(kw),
            Vehicle.driver_hint_name.ilike(kw),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if vehicle_type is not None:
        stmt = stmt.where(Vehicle.vehicle_type == vehicle_type)
        count_stmt = count_stmt.where(Vehicle.vehicle_type == vehicle_type)

    if carrier_id and carrier_id.strip():
        try:
            cid = int(carrier_id.strip())
            stmt = stmt.where(Vehicle.carrier_id == cid)
            count_stmt = count_stmt.where(Vehicle.carrier_id == cid)
        except ValueError:
            pass

    if is_active is not None:
        stmt = stmt.where(Vehicle.is_active == is_active)
        count_stmt = count_stmt.where(Vehicle.is_active == is_active)

    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        stmt.order_by(Vehicle.plate_no.asc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    items = [
        VehicleOut(
            id=str(veh.id),
            tms_vehicle_id=str(veh.tms_vehicle_id),
            carrier_id=str(veh.carrier_id) if veh.carrier_id is not None else None,
            carrier_name=carrier_name,
            plate_no=veh.plate_no,
            vehicle_type=veh.vehicle_type,
            payload_capacity=veh.payload_capacity,
            driver_hint_name=veh.driver_hint_name,
            is_active=veh.is_active,
        )
        for veh, carrier_name in rows
    ]

    return PaginatedVehiclesResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_calc_total_pages(total, per_page),
    )


@router.get("/trailers", response_model=PaginatedTrailersResponse)
def list_trailers(
    search: Optional[str] = Query(
        default=None,
        description="Tìm theo biển số rơ-moóc, model, ghi chú hoặc tên/mã nhà xe",
    ),
    mooc_type: Optional[int] = Query(default=None, description="Lọc theo loại rơ-moóc (1, 2)"),
    model: Optional[str] = Query(default=None, description="Lọc theo hãng/quy cách model"),
    carrier_id: Optional[str] = Query(default=None, description="Lọc theo ID nhà xe nội bộ"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái hoạt động"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedTrailersResponse:
    """Tra cứu danh sách rơ-moóc có phân trang, tìm kiếm và bộ lọc đầy đủ."""
    stmt = select(
        Trailer,
        Carrier.name.label("carrier_name"),
        Carrier.short_name.label("carrier_short_name"),
    ).outerjoin(Carrier, Trailer.carrier_id == Carrier.id)
    count_stmt = select(func.count(Trailer.id)).outerjoin(
        Carrier, Trailer.carrier_id == Carrier.id
    )

    if search and search.strip():
        raw_kw = search.strip()
        kw = f"%{raw_kw}%"
        norm_kw = f"%{re.sub(r'[^A-Za-z0-9]', '', raw_kw).upper()}%"
        cond = or_(
            Trailer.license_plate.ilike(kw),
            Trailer.normalized_plate.ilike(norm_kw),
            Trailer.model.ilike(kw),
            Trailer.note.ilike(kw),
            Carrier.name.ilike(kw),
            Carrier.short_name.ilike(kw),
            Carrier.code.ilike(kw),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if mooc_type is not None:
        stmt = stmt.where(Trailer.mooc_type == mooc_type)
        count_stmt = count_stmt.where(Trailer.mooc_type == mooc_type)

    if model and model.strip():
        clean_model = model.strip()
        stmt = stmt.where(Trailer.model == clean_model)
        count_stmt = count_stmt.where(Trailer.model == clean_model)

    if carrier_id and carrier_id.strip():
        try:
            cid = int(carrier_id.strip())
            stmt = stmt.where(Trailer.carrier_id == cid)
            count_stmt = count_stmt.where(Trailer.carrier_id == cid)
        except ValueError:
            pass

    if is_active is not None:
        stmt = stmt.where(Trailer.is_active == is_active)
        count_stmt = count_stmt.where(Trailer.is_active == is_active)

    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        stmt.order_by(Trailer.license_plate.asc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    distinct_models = sorted(
        {
            m
            for m in db.scalars(
                select(Trailer.model).where(Trailer.model.is_not(None), Trailer.model != "")
            ).all()
            if m
        }
    )

    items = [
        TrailerOut(
            id=str(tr.id),
            tms_mooc_id=str(tr.tms_mooc_id),
            tms_carrier_id=str(tr.tms_carrier_id) if tr.tms_carrier_id is not None else None,
            carrier_id=str(tr.carrier_id) if tr.carrier_id is not None else None,
            carrier_name=carrier_name,
            carrier_short_name=carrier_short_name,
            license_plate=tr.license_plate,
            normalized_plate=tr.normalized_plate,
            mooc_type=tr.mooc_type,
            model=tr.model,
            note=tr.note,
            is_active=tr.is_active,
            synced_at=tr.synced_at.isoformat() if tr.synced_at else None,
        )
        for tr, carrier_name, carrier_short_name in rows
    ]

    return PaginatedTrailersResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_calc_total_pages(total, per_page),
        filter_options={"models": distinct_models},
    )


@router.post("/trailers/sync", response_model=dict[str, Any])
def sync_trailers_manual(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Kéo và cập nhật ngay toàn bộ danh mục rơ-moóc từ hệ thống TMS về MySQL."""
    try:
        stats = sync_trailers_from_tms(db, tms_auto_sync.get_client())
        db.commit()
    except TmsApiError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "message": (
            f"Đã đồng bộ {stats['fetched']} rơ-moóc từ TMS "
            f"(thêm mới {stats['created']}, cập nhật {stats['updated']})."
        ),
        **stats,
    }


@router.get("/customers", response_model=PaginatedCustomersResponse)
def list_customers(
    search: Optional[str] = Query(default=None, description="Tìm theo tên khách hàng"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái hoạt động"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedCustomersResponse:
    """Tra cứu danh sách khách hàng có phân trang, tìm kiếm và lọc trạng thái."""
    stmt = select(Customer)
    count_stmt = select(func.count(Customer.id))

    if search and search.strip():
        kw = f"%{search.strip()}%"
        cond = or_(
            Customer.name.ilike(kw),
            Customer.normalized_name.ilike(kw),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if is_active is not None:
        stmt = stmt.where(Customer.is_active == is_active)
        count_stmt = count_stmt.where(Customer.is_active == is_active)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(Customer.name.asc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    customer_ids = [r.id for r in rows]
    wh_counts: dict[int, int] = {}
    if customer_ids:
        for cid, cnt in db.execute(
            select(Warehouse.customer_id, func.count(Warehouse.id))
            .where(Warehouse.customer_id.in_(customer_ids))
            .group_by(Warehouse.customer_id)
        ).all():
            if cid is not None:
                wh_counts[cid] = cnt

    items = [
        CustomerOut(
            id=str(r.id),
            tms_customer_id=str(r.tms_customer_id),
            name=r.name,
            normalized_name=r.normalized_name,
            is_active=r.is_active,
            warehouse_count=wh_counts.get(r.id, 0),
        )
        for r in rows
    ]

    return PaginatedCustomersResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_calc_total_pages(total, per_page),
    )


@router.get("/warehouses", response_model=PaginatedWarehousesResponse)
def list_warehouses(
    search: Optional[str] = Query(default=None, description="Tìm theo tên kho hoặc địa chỉ"),
    location_type: Optional[str] = Query(default=None, description="Lọc loại địa điểm (warehouse, port, depot)"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái hoạt động"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedWarehousesResponse:
    """Tra cứu danh sách kho khách hàng, cảng và depot có phân trang, tìm kiếm và lọc."""
    stmt = select(Warehouse, Customer.name.label("customer_name")).outerjoin(
        Customer, Warehouse.customer_id == Customer.id
    )
    count_stmt = select(func.count(Warehouse.id))

    if search and search.strip():
        kw = f"%{search.strip()}%"
        cond = or_(
            Warehouse.name.ilike(kw),
            Warehouse.address.ilike(kw),
            Warehouse.normalized_name.ilike(kw),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if location_type and location_type.strip():
        stmt = stmt.where(Warehouse.location_type == location_type.strip())
        count_stmt = count_stmt.where(Warehouse.location_type == location_type.strip())

    if is_active is not None:
        stmt = stmt.where(Warehouse.is_active == is_active)
        count_stmt = count_stmt.where(Warehouse.is_active == is_active)

    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        stmt.order_by(Warehouse.name.asc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    items = [
        WarehouseOut(
            id=str(wh.id),
            tms_warehouse_id=str(wh.tms_warehouse_id),
            customer_id=str(wh.customer_id) if wh.customer_id is not None else None,
            customer_name=customer_name,
            location_type=wh.location_type,
            name=wh.name,
            address=wh.address,
            latitude=wh.latitude,
            longitude=wh.longitude,
            is_active=wh.is_active,
        )
        for wh, customer_name in rows
    ]

    return PaginatedWarehousesResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_calc_total_pages(total, per_page),
    )


class MasterPlanProvinceGroup(BaseModel):
    """Nhóm kế hoạch vận chuyển theo tỉnh/thành phố phục vụ giao diện điều hành TMS."""

    province_id: Optional[int] = None
    province_name: str
    total_orders: int
    return_orders_count: int
    loading_orders_count: int
    container_balance: dict[str, Any]
    container_warning_counts: dict[str, int]
    return_orders: list[TransportPlanOut]
    loading_orders: list[TransportPlanOut]


class MasterTransportPlansResponse(BaseModel):
    """Phản hồi toàn bộ kế hoạch theo ngày từ MySQL (thống kê, theo tỉnh, danh sách lệnh)."""

    ok: bool = True
    plan_date: str
    region: int
    total_orders: int
    summary: dict[str, Any]
    filter_options: dict[str, list[Any]]
    provinces: list[MasterPlanProvinceGroup]
    orders: list[TransportPlanOut]


def _matches_master_plan_filters(
    row: TransportPlan,
    search_kw: Optional[str],
    forwarder_name: Optional[str],
    order_type: Optional[str],
    container_size: Optional[str],
    delivery_term: Optional[int],
    dispatch_state: Optional[int],
    container_warning: Optional[str],
) -> bool:
    """Kiểm tra bản ghi kế hoạch có thỏa mãn toàn bộ bộ lọc giao diện TMS hay không."""
    if forwarder_name and (row.forwarder_name or "") != forwarder_name:
        return False
    if order_type and row.order_type != order_type:
        return False
    if container_size and not str(row.container_size or "").startswith(container_size):
        return False
    if delivery_term is not None and row.delivery_term != delivery_term:
        return False
    if dispatch_state is not None and row.dispatch_state != dispatch_state:
        return False
    if container_warning:
        if row.order_type != "tra":
            return False
        if container_warning == "soc":
            if row.container_warning != "soc" and row.container_ownership != 2:
                return False
        elif container_warning == "normal":
            if (row.container_warning or "normal") != "normal":
                return False
        elif row.container_warning != container_warning:
            return False
    if search_kw:
        haystack = " ".join(
            str(x)
            for x in (
                row.order_code,
                row.booking_no,
                row.bill_of_lading_no,
                row.container_no,
                row.seal_no,
                row.customer_name,
                row.warehouse_name,
                row.delivery_address,
                row.ward_name,
                row.province_name,
                row.forwarder_name,
                row.planned_truck_plate,
                row.planned_trailer_plate,
                row.driver_name,
            )
            if x
        ).lower()
        if search_kw not in haystack:
            return False
    return True


@router.get("/transport-plans", response_model=MasterTransportPlansResponse)
def get_master_transport_plans(
    plan_date: str = Query(default="2026-11-09", description="Ngày kế hoạch (YYYY-MM-DD hoặc DD/MM/YYYY)"),
    region: int = Query(default=1, ge=1, le=3, description="Mã miền (1=Bắc, 2=Trung, 3=Nam)"),
    search: Optional[str] = Query(default=None, description="Tìm mã lệnh, số cont, tên kho, khách hàng..."),
    forwarder_name: Optional[str] = Query(default=None, description="Lọc theo đơn vị Forwarder"),
    order_type: Optional[str] = Query(default=None, description="Lọc loại lệnh ('tra' hoặc 'dong')"),
    container_size: Optional[str] = Query(default=None, description="Lọc size cont ('20' hoặc '40')"),
    delivery_term: Optional[int] = Query(default=None, description="Lọc phương thức GN (1=Nguyên cont, 2=Kiểm đếm)"),
    dispatch_state: Optional[int] = Query(default=None, description="Lọc trạng thái điều phối"),
    container_warning: Optional[str] = Query(default=None, description="Lọc tình trạng vỏ lệnh trả"),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> MasterTransportPlansResponse:
    """Truy vấn kế hoạch vận chuyển từ MySQL theo giao diện điều vận TMS (tổng hợp + gom nhóm tỉnh)."""
    p_date = parse_date_str(plan_date)
    if not p_date:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng ngày không hợp lệ: '{plan_date}'. Vui lòng dùng 'YYYY-MM-DD' hoặc 'DD/MM/YYYY'.",
        )

    tms_auto_sync.track_date(p_date, region)

    all_rows = list(
        db.scalars(
            select(TransportPlan)
            .where(
                TransportPlan.plan_date == p_date,
                or_(TransportPlan.region == region, TransportPlan.region.is_(None))
                if region == 1
                else TransportPlan.region == region,
            )
            .order_by(TransportPlan.stt.asc(), TransportPlan.id.asc())
        ).all()
    )

    summary = build_master_plan_summary(all_rows)
    filter_options = {
        "forwarders": sorted({r.forwarder_name for r in all_rows if r.forwarder_name}),
        "dispatch_states": sorted({r.dispatch_state for r in all_rows if r.dispatch_state is not None}),
    }

    search_kw = search.strip().lower() if search and search.strip() else None
    filtered_rows = [
        r
        for r in all_rows
        if _matches_master_plan_filters(
            row=r,
            search_kw=search_kw,
            forwarder_name=forwarder_name.strip() if forwarder_name and forwarder_name.strip() else None,
            order_type=order_type.strip().lower() if order_type and order_type.strip() else None,
            container_size=container_size.strip() if container_size and container_size.strip() else None,
            delivery_term=delivery_term,
            dispatch_state=dispatch_state,
            container_warning=container_warning.strip() if container_warning and container_warning.strip() else None,
        )
    ]

    grouped: dict[tuple[Optional[int], str], list[TransportPlan]] = {}
    for r in filtered_rows:
        p_name = (r.province_name or "").strip() or "Chưa phân tỉnh"
        key = (r.province_id, p_name)
        grouped.setdefault(key, []).append(r)

    province_groups: list[MasterPlanProvinceGroup] = []
    for (prov_id, prov_name), rows in grouped.items():
        prov_summary = build_master_plan_summary(rows)
        ret_outs = [TransportPlanOut.model_validate(r) for r in rows if r.order_type == "tra"]
        load_outs = [TransportPlanOut.model_validate(r) for r in rows if r.order_type == "dong"]
        province_groups.append(
            MasterPlanProvinceGroup(
                province_id=prov_id,
                province_name=prov_name,
                total_orders=len(rows),
                return_orders_count=len(ret_outs),
                loading_orders_count=len(load_outs),
                container_balance=prov_summary["container_balance"],
                container_warning_counts=prov_summary["container_warning_counts"],
                return_orders=ret_outs,
                loading_orders=load_outs,
            )
        )

    province_groups.sort(key=lambda g: (-g.total_orders, g.province_id or 9999))
    flat_orders = [TransportPlanOut.model_validate(r) for r in filtered_rows]

    return MasterTransportPlansResponse(
        ok=True,
        plan_date=p_date.isoformat(),
        region=region,
        total_orders=len(filtered_rows),
        summary=summary,
        filter_options=filter_options,
        provinces=province_groups,
        orders=flat_orders,
    )
