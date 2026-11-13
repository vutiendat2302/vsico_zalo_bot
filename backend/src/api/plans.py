"""Module Các REST API Quản Lý & Import Kế Hoạch Vận Chuyển Hằng Ngày (Transport Plan APIs).

Cung cấp đầy đủ các endpoint CRUD và Import dữ liệu kế hoạch vận chuyển:
1. Danh sách kế hoạch có bộ lọc: `GET /api/plans`
2. Chi tiết kế hoạch theo ID: `GET /api/plans/{plan_id}`
3. Thêm mới kế hoạch: `POST /api/plans`
4. Cập nhật kế hoạch: `PUT /api/plans/{plan_id}`
5. Xóa một dòng kế hoạch: `DELETE /api/plans/{plan_id}`
6. Xóa toàn bộ kế hoạch theo ngày: `DELETE /api/plans/by-date/{plan_date}`
7. Import tệp CSV: `POST /api/plans/import-csv`
8. Import tệp Excel (.xlsx): `POST /api/plans/import-excel`
9. Import đa định dạng (tự nhận diện CSV/Excel): `POST /api/plans/import`
"""

from datetime import date, datetime
import random
import re
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from src.api.schemas import (
    PlanVehicleUpdate,
    TransportPlanCreate,
    TransportPlanImportResponse,
    TransportPlanListResponse,
    TransportPlanOut,
    TransportPlanRandomizeResponse,
    TransportPlanUpdate,
)
from src.infrastructure.database import get_db
from src.infrastructure.models import TransportPlan, Carrier, User, ActivityLog, ZaloGroup
from src.infrastructure.security import get_current_user
from src.domain.rules import clean_plate, clean_container, validate_iso6346
from src.infrastructure.snowflake import snowflake
from src.observability.logging import get_logger
from src.parsing.plan_importer import DEFAULT_GROUP_ID, PlanFileParser

logger = get_logger(__name__)

router = APIRouter(prefix="/api/plans", tags=["3. Kế Hoạch Vận Chuyển Hằng Ngày (Transport Plans)"])


def parse_date_str(val: Optional[str]) -> Optional[date]:
    """Chuyển đổi chuỗi ngày linh hoạt sang đối tượng date (hỗ trợ YYYY-MM-DD và DD/MM/YYYY).

    Args:
        val (Optional[str]): Chuỗi ngày đầu vào.

    Returns:
        Optional[date]: Đối tượng date hoặc None nếu không hợp lệ.
    """
    if not val or not str(val).strip():
        return None
    s = str(val).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    vn_m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$", s)
    if vn_m:
        try:
            return date(int(vn_m.group(3)), int(vn_m.group(2)), int(vn_m.group(1)))
        except ValueError:
            return None
    return None


@router.get("", response_model=TransportPlanListResponse)
def get_transport_plans(
    plan_date: Optional[str] = Query(default=None, description="Lọc theo ngày kế hoạch (YYYY-MM-DD hoặc DD/MM/YYYY)"),
    container_no: Optional[str] = Query(default=None, description="Lọc theo số container"),
    customer_name: Optional[str] = Query(default=None, description="Lọc theo tên khách hàng"),
    order_type: Optional[str] = Query(default=None, description="Lọc theo loại lệnh: 'dong' (Xuất) hoặc 'tra' (Nhập/Mở)"),
    truck_plate: Optional[str] = Query(default=None, description="Lọc theo biển số xe (VD: '29C-445.41' hoặc '29C44541')"),
    driver_name: Optional[str] = Query(default=None, description="Lọc theo tên tài xế"),
    group_id: Optional[str] = Query(default=None, description="Lọc theo Group ID Zalo"),
    route_name: Optional[str] = Query(default=None, description="Lọc theo tuyến vận chuyển"),
    q: Optional[str] = Query(default=None, description="Tìm kiếm nhanh tổng hợp (cont, khách, xe, tài xế, địa chỉ)"),
    limit: Optional[int] = Query(default=500, ge=1, le=5000, description="Giới hạn số lượng bản ghi trả về"),
    offset: int = Query(default=0, ge=0, description="Vị trí bắt đầu phân trang"),
    db: Session = Depends(get_db),
) -> TransportPlanListResponse:
    """Truy vấn danh sách kế hoạch vận chuyển hằng ngày kèm các bộ lọc chi tiết."""
    from sqlalchemy import or_

    stmt = select(TransportPlan)

    p_date = parse_date_str(plan_date)
    if plan_date and not p_date:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng ngày không hợp lệ: '{plan_date}'. Vui lòng dùng 'YYYY-MM-DD' hoặc 'DD/MM/YYYY'.",
        )

    if p_date:
        stmt = stmt.where(TransportPlan.plan_date == p_date)
    if container_no:
        clean_c = container_no.strip().upper()
        stmt = stmt.where(TransportPlan.container_no.like(f"%{clean_c}%"))
    if customer_name:
        stmt = stmt.where(func.lower(TransportPlan.customer_name).like(f"%{customer_name.strip().lower()}%"))
    if order_type:
        stmt = stmt.where(TransportPlan.order_type == order_type.strip().lower())
    if truck_plate:
        clean_tp = re.sub(r"[^A-Za-z0-9]", "", truck_plate).upper()
        # Tìm kiếm theo biển số xe hoặc dạng liền/gạch nối
        stmt = stmt.where(
            or_(
                TransportPlan.planned_truck_plate.like(f"%{truck_plate.strip()}%"),
                func.replace(func.replace(func.replace(TransportPlan.planned_truck_plate, "-", ""), ".", ""), " ", "").like(f"%{clean_tp}%"),
            )
        )
    if driver_name:
        stmt = stmt.where(func.lower(TransportPlan.driver_name).like(f"%{driver_name.strip().lower()}%"))
    if group_id:
        stmt = stmt.where(TransportPlan.group_id == group_id.strip())
    if route_name:
        stmt = stmt.where(func.lower(TransportPlan.route_name).like(f"%{route_name.strip().lower()}%"))
    if q and q.strip():
        search_kw = f"%{q.strip().lower()}%"
        clean_alnum = f"%{re.sub(r'[^A-Za-z0-9]', '', q).upper()}%"
        stmt = stmt.where(
            or_(
                func.lower(TransportPlan.container_no).like(search_kw),
                func.lower(TransportPlan.customer_name).like(search_kw),
                func.lower(TransportPlan.driver_name).like(search_kw),
                func.lower(TransportPlan.planned_truck_plate).like(search_kw),
                func.lower(TransportPlan.delivery_address).like(search_kw),
                func.lower(TransportPlan.route_name).like(search_kw),
                func.lower(TransportPlan.fleet_partner).like(search_kw),
                func.replace(func.replace(func.replace(TransportPlan.planned_truck_plate, "-", ""), ".", ""), " ", "").like(clean_alnum),
            )
        )

    # Đếm tổng số bản ghi khớp điều kiện
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(TransportPlan.plan_date.desc(), TransportPlan.stt.asc(), TransportPlan.id.asc())
    if offset > 0:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    records = list(db.scalars(stmt).all())

    # Lấy thông tin tên nhóm Zalo để trả về kèm
    gids = list({r.group_id for r in records if r.group_id})
    group_name_map: dict[str, str] = {}
    if gids:
        group_rows = db.scalars(select(ZaloGroup).where(ZaloGroup.zalo_group_id.in_(gids))).all()
        for g in group_rows:
            if g.name:
                group_name_map[g.zalo_group_id] = g.name

    out_plans = []
    for r in records:
        out = TransportPlanOut.model_validate(r)
        if r.group_id and r.group_id in group_name_map:
            out.group_name = group_name_map[r.group_id]
        out_plans.append(out)

    return TransportPlanListResponse(
        ok=True,
        status="OK",
        total=total_count,
        total_returned=len(records),
        filters={
            "plan_date": p_date.isoformat() if p_date else None,
            "container_no": container_no,
            "customer_name": customer_name,
            "order_type": order_type,
            "truck_plate": truck_plate,
            "driver_name": driver_name,
            "group_id": group_id,
            "route_name": route_name,
            "q": q,
        },
        plans=out_plans,
    )


@router.get("/{plan_id}", response_model=TransportPlanOut)
def get_transport_plan_by_id(
    plan_id: int,
    db: Session = Depends(get_db),
) -> TransportPlanOut:
    """Lấy chi tiết một bản ghi kế hoạch vận chuyển theo ID."""
    plan = db.get(TransportPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bản ghi kế hoạch ID={plan_id}.")
    out = TransportPlanOut.model_validate(plan)
    if plan.group_id:
        zg = db.scalars(select(ZaloGroup).where(ZaloGroup.zalo_group_id == plan.group_id)).first()
        if zg and zg.name:
            out.group_name = zg.name
    return out


@router.post("", response_model=TransportPlanOut)
def create_transport_plan(
    payload: TransportPlanCreate = Body(...),
    db: Session = Depends(get_db),
) -> TransportPlanOut:
    """Thêm mới một bản ghi kế hoạch vận chuyển thủ công.

    - Nếu `order_type` chưa điền, tự động suy luận từ `cargo_io_type` ('I' -> 'tra', 'X' -> 'dong').
    - Nếu `group_id` để trống, tự động gán mặc định `6469608867469758994`.
    """
    order_type = payload.order_type
    cargo_io_type = payload.cargo_io_type

    if not order_type:
        if cargo_io_type and cargo_io_type.upper() in ("X", "XUẤT", "XUAT"):
            order_type = "dong"
            cargo_io_type = "X"
        else:
            order_type = "tra"
            cargo_io_type = "I"

    final_group_id = (payload.group_id or "").strip() or DEFAULT_GROUP_ID

    plan = TransportPlan(
        plan_date=payload.plan_date,
        stt=payload.stt,
        route_name=payload.route_name,
        cargo_io_type=cargo_io_type,
        order_type=order_type,
        container_no=payload.container_no.strip().upper() if payload.container_no else None,
        seal_no=payload.seal_no.strip() if payload.seal_no else None,
        container_size=payload.container_size,
        cargo_weight=payload.cargo_weight,
        required_time=payload.required_time,
        customer_name=payload.customer_name,
        cargo_type=payload.cargo_type,
        vessel_voyage=payload.vessel_voyage,
        empty_depot=payload.empty_depot,
        full_depot=payload.full_depot,
        estimated_drop_time=payload.estimated_drop_time,
        fleet_partner=payload.fleet_partner,
        planned_truck_plate=payload.planned_truck_plate,
        driver_name=payload.driver_name,
        driver_phone=payload.driver_phone,
        delivery_address=payload.delivery_address,
        group_id=final_group_id,
        operator_staff=payload.operator_staff,
        notes=payload.notes,
        extra_fee_notes=payload.extra_fee_notes,
        # Đồng bộ các cột cũ:
        address=payload.delivery_address,
        carrier_name=payload.fleet_partner,
        eta=payload.required_time,
        combine_note=payload.notes,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return TransportPlanOut.model_validate(plan)


@router.put("/{plan_id}", response_model=TransportPlanOut)
def update_transport_plan(
    plan_id: int,
    payload: TransportPlanUpdate = Body(...),
    db: Session = Depends(get_db),
) -> TransportPlanOut:
    """Cập nhật thông tin một bản ghi kế hoạch vận chuyển."""
    plan = db.get(TransportPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bản ghi kế hoạch ID={plan_id}.")

    update_data = payload.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        if field == "container_no" and val:
            setattr(plan, field, str(val).strip().upper())
        elif field == "delivery_address":
            setattr(plan, "delivery_address", val)
            setattr(plan, "address", val)
        elif field == "fleet_partner":
            setattr(plan, "fleet_partner", val)
            setattr(plan, "carrier_name", val)
        elif field == "required_time":
            setattr(plan, "required_time", val)
            setattr(plan, "eta", val)
        elif field == "group_id":
            setattr(plan, "group_id", (val or "").strip() or DEFAULT_GROUP_ID)
        else:
            setattr(plan, field, val)

    setattr(plan, "updated_at", datetime.now())
    db.commit()
    db.refresh(plan)
    return TransportPlanOut.model_validate(plan)


@router.delete("/{plan_id}")
def delete_transport_plan(
    plan_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Xóa một bản ghi kế hoạch vận chuyển theo ID."""
    plan = db.get(TransportPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bản ghi kế hoạch ID={plan_id}.")
    db.delete(plan)
    db.commit()
    return {"ok": True, "status": "DELETED", "deleted_plan_id": plan_id}


@router.delete("/by-date/{plan_date}")
def delete_plans_by_date(
    plan_date: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Xóa toàn bộ các bản ghi kế hoạch của một ngày cụ thể (tiện cho việc Import lại dữ liệu)."""
    p_date = parse_date_str(plan_date)
    if not p_date:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng ngày không hợp lệ: '{plan_date}'. Vui lòng dùng 'YYYY-MM-DD' hoặc 'DD/MM/YYYY'.",
        )
    deleted_count = db.execute(delete(TransportPlan).where(TransportPlan.plan_date == p_date)).rowcount
    db.commit()
    return {
        "ok": True,
        "status": "DELETED",
        "plan_date": p_date.isoformat(),
        "deleted_count": deleted_count,
    }


def _save_imported_records(
    db: Session,
    effective_date: date,
    records: list[dict[str, Any]],
    replace_existing: bool,
) -> tuple[int, int, list[TransportPlan]]:
    """Lưu danh sách bản ghi đã bóc tách từ file vào cơ sở dữ liệu MySQL."""
    if replace_existing:
        db.execute(delete(TransportPlan).where(TransportPlan.plan_date == effective_date))
        db.flush()

    inserted_objs: list[TransportPlan] = []
    skipped_count = 0

    for item in records:
        cont_no = item.get("container_no")
        # Bản ghi phải có ít nhất STT hoặc Cont hoặc Khách hoặc Địa chỉ
        if not cont_no and not item.get("stt") and not item.get("customer_name") and not item.get("delivery_address"):
            skipped_count += 1
            continue

        plan_obj = TransportPlan(
            plan_date=item.get("plan_date") or effective_date,
            stt=item.get("stt"),
            route_name=item.get("route_name"),
            cargo_io_type=item.get("cargo_io_type"),
            order_type=item.get("order_type") or "tra",
            container_no=cont_no,
            seal_no=item.get("seal_no"),
            container_size=item.get("container_size"),
            cargo_weight=item.get("cargo_weight"),
            required_time=item.get("required_time"),
            customer_name=item.get("customer_name"),
            cargo_type=item.get("cargo_type"),
            vessel_voyage=item.get("vessel_voyage"),
            empty_depot=item.get("empty_depot"),
            full_depot=item.get("full_depot"),
            estimated_drop_time=item.get("estimated_drop_time"),
            fleet_partner=item.get("fleet_partner"),
            planned_truck_plate=item.get("planned_truck_plate"),
            delivery_address=item.get("delivery_address"),
            group_id=item.get("group_id") or DEFAULT_GROUP_ID,
            operator_staff=item.get("operator_staff"),
            notes=item.get("notes"),
            extra_fee_notes=item.get("extra_fee_notes"),
            # Đồng bộ các cột cũ:
            address=item.get("delivery_address"),
            carrier_name=item.get("fleet_partner"),
            eta=item.get("required_time"),
            combine_note=item.get("notes"),
        )
        db.add(plan_obj)
        inserted_objs.append(plan_obj)

    db.commit()
    for o in inserted_objs:
        db.refresh(o)

    return len(inserted_objs), skipped_count, inserted_objs


@router.post("/import-csv", response_model=TransportPlanImportResponse)
async def import_plans_from_csv(
    file: UploadFile = File(..., description="Tệp tin CSV chứa dữ liệu kế hoạch vận chuyển"),
    replace_existing: bool = Query(
        default=True,
        description="Ghi đè/xóa các bản ghi cũ của cùng ngày kế hoạch trước khi nạp",
    ),
    plan_date: Optional[str] = Query(
        default=None,
        description="Ngày kế hoạch ghi đè (nếu file CSV không có cột ngày)",
    ),
    db: Session = Depends(get_db),
) -> TransportPlanImportResponse:
    """API Nạp Kế Hoạch Vận Chuyển Từ Tệp Tin CSV.

    - Tự động nhận diện dấu phân cách (dấu phẩy, chấm phẩy, tab).
    - Tự động phát hiện loại lệnh Đóng (`dong`) hay Trả (`tra`) theo cột Hàng ('Xuất'/'Nhập' hoặc 'X'/'I').
    - Toàn bộ các dòng chưa có group_id sẽ được map tự động về nhóm `6469608867469758994`.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Tệp tin rỗng, vui lòng chọn file CSV hợp lệ.")

    override_d = parse_date_str(plan_date)
    try:
        effective_date, records = PlanFileParser.parse_csv(
            csv_text_or_bytes=content,
            default_date=override_d,
            default_group_id=DEFAULT_GROUP_ID,
        )
    except Exception as exc:
        logger.error("Lỗi phân tích file CSV: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Lỗi khi đọc file CSV: {exc}") from exc

    if override_d:
        effective_date = override_d
        for r in records:
            r["plan_date"] = override_d

    total_inserted, total_skipped, inserted_list = _save_imported_records(
        db=db,
        effective_date=effective_date,
        records=records,
        replace_existing=replace_existing,
    )

    return TransportPlanImportResponse(
        ok=True,
        status="OK",
        message=f"Đã nạp thành công {total_inserted} dòng kế hoạch ngày {effective_date.isoformat()} từ CSV.",
        plan_date=effective_date.isoformat(),
        total_imported=total_inserted,
        total_skipped=total_skipped,
        default_group_id_applied=DEFAULT_GROUP_ID,
        sample_imported=[TransportPlanOut.model_validate(p) for p in inserted_list[:5]],
    )


@router.post("/import-excel", response_model=TransportPlanImportResponse)
async def import_plans_from_excel(
    file: UploadFile = File(..., description="Tệp tin Excel (.xlsx) Kế hoạch vận chuyển"),
    replace_existing: bool = Query(
        default=True,
        description="Ghi đè/xóa các bản ghi cũ của cùng ngày kế hoạch trước khi nạp",
    ),
    plan_date: Optional[str] = Query(
        default=None,
        description="Ngày kế hoạch ghi đè (nếu muốn chỉ định ngày cụ thể)",
    ),
    db: Session = Depends(get_db),
) -> TransportPlanImportResponse:
    """API Nạp Kế Hoạch Vận Chuyển Từ Tệp Tin Excel (.xlsx).

    - Nhận diện trực tiếp tiêu đề sheet 'KẾ HOẠCH VẬN CHUYỂN NGÀY DD/MM/YYYY'.
    - Tự động bóc tách cột Hàng (Xuất $\rightarrow$ `dong`, Nhập $\rightarrow$ `tra`).
    - Tự động map `group_id = 6469608867469758994` cho toàn bộ các dòng.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Tệp tin rỗng, vui lòng chọn file Excel hợp lệ.")

    override_d = parse_date_str(plan_date)
    try:
        effective_date, records = PlanFileParser.parse_excel(
            file_bytes=content,
            default_date=override_d,
            default_group_id=DEFAULT_GROUP_ID,
        )
    except Exception as exc:
        logger.error("Lỗi phân tích file Excel: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Lỗi khi đọc file Excel: {exc}") from exc

    if override_d:
        effective_date = override_d
        for r in records:
            r["plan_date"] = override_d

    total_inserted, total_skipped, inserted_list = _save_imported_records(
        db=db,
        effective_date=effective_date,
        records=records,
        replace_existing=replace_existing,
    )

    return TransportPlanImportResponse(
        ok=True,
        status="OK",
        message=f"Đã nạp thành công {total_inserted} dòng kế hoạch ngày {effective_date.isoformat()} từ Excel.",
        plan_date=effective_date.isoformat(),
        total_imported=total_inserted,
        total_skipped=total_skipped,
        default_group_id_applied=DEFAULT_GROUP_ID,
        sample_imported=[TransportPlanOut.model_validate(p) for p in inserted_list[:5]],
    )


@router.post("/import", response_model=TransportPlanImportResponse)
async def import_plans_universal(
    file: UploadFile = File(..., description="Tệp tin kế hoạch (.csv hoặc .xlsx)"),
    replace_existing: bool = Query(default=True, description="Ghi đè/xóa các bản ghi cũ của cùng ngày"),
    plan_date: Optional[str] = Query(default=None, description="Ngày kế hoạch chỉ định"),
    db: Session = Depends(get_db),
) -> TransportPlanImportResponse:
    """API Nạp Kế Hoạch Vận Chuyển Đa Định Dạng (Tự động nhận diện CSV hoặc Excel theo đuôi file)."""
    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        return await import_plans_from_excel(
            file=file,
            replace_existing=replace_existing,
            plan_date=plan_date,
            db=db,
        )
    return await import_plans_from_csv(
        file=file,
        replace_existing=replace_existing,
        plan_date=plan_date,
        db=db,
    )


REAL_TARGET_GROUPS = [
    "3051850159021421440",  # Nhóm Test 3
    "6469608867469758994",  # Nhóm Khách Hàng (VSICO - DC Logistics)
    "7196206900754562564",  # Nhóm Nhà Xe (Logitem - Tân Quang)
]


@router.post("/randomize-groups", response_model=TransportPlanRandomizeResponse)
def randomize_plan_groups(
    plan_date: Optional[str] = Query(
        default=None,
        description="Ngày kế hoạch cần random (YYYY-MM-DD, bỏ trống để áp dụng cho tất cả)",
    ),
    group_ids: Optional[list[str]] = Body(
        default=None,
        description="Danh sách groupId Zalo cần random (mặc định 3 nhóm Zalo thật)",
    ),
    db: Session = Depends(get_db),
) -> TransportPlanRandomizeResponse:
    """API Phân Bổ Ngẫu Nhiên Group ID Cho Các Bản Ghi Kế Hoạch Vận Chuyển.

    Tự động random đều giữa 3 nhóm Zalo thật của người dùng:
    - 3051850159021421440 (test3)
    - 6469608867469758994 (khách hàng)
    - 7196206900754562564 (nhà xe)

    Args:
        plan_date (Optional[str]): Ngày kế hoạch cần lọc (nếu có).
        group_ids (Optional[list[str]]): Danh sách nhóm đích Zalo tùy chọn.
        db (Session): Phiên làm việc CSDL.

    Returns:
        TransportPlanRandomizeResponse: Báo cáo số lượng bản ghi đã được cập nhật và phân bổ nhóm.
    """
    target_groups = [str(g).strip() for g in (group_ids or REAL_TARGET_GROUPS) if str(g).strip()]
    if not target_groups:
        target_groups = REAL_TARGET_GROUPS

    stmt = select(TransportPlan)
    parsed_d = parse_date_str(plan_date)
    if parsed_d:
        stmt = stmt.where(TransportPlan.plan_date == parsed_d)

    plans = list(db.scalars(stmt).all())
    if not plans:
        return TransportPlanRandomizeResponse(
            ok=True,
            status="OK",
            message="Không tìm thấy bản ghi kế hoạch nào phù hợp để random.",
            total_updated=0,
            group_distribution={},
        )

    # Xáo trộn ngẫu nhiên danh sách và gán vòng tròn để đảm bảo vừa ngẫu nhiên vừa cân bằng số lượng
    shuffled_indices = list(range(len(plans)))
    random.shuffle(shuffled_indices)

    distribution: dict[str, int] = {gid: 0 for gid in target_groups}
    for idx, plan_idx in enumerate(shuffled_indices):
        assigned_grp = target_groups[idx % len(target_groups)]
        plans[plan_idx].group_id = assigned_grp
        distribution[assigned_grp] = distribution.get(assigned_grp, 0) + 1

    db.commit()
    logger.info(
        "Đã phân bổ ngẫu nhiên %s bản ghi kế hoạch vào %s nhóm: %s",
        len(plans),
        len(target_groups),
        distribution,
    )

    return TransportPlanRandomizeResponse(
        ok=True,
        status="OK",
        message=f"Đã cập nhật ngẫu nhiên group_id cho {len(plans)} bản ghi kế hoạch giữa {len(target_groups)} nhóm Zalo.",
        total_updated=len(plans),
        group_distribution=distribution,
    )


@router.post("/set-default-group")
def set_all_plans_default_group(
    group_id: str = Query(
        default="6469608867469758994",
        description="Mã Group ID Zalo muốn gán cho toàn bộ kế hoạch vận chuyển",
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cập nhật toàn bộ group_id trong transport_plans về một nhóm Zalo cụ thể.

    Args:
        group_id (str): Mã Group ID Zalo đích (mặc định: 6469608867469758994).
        db (Session): Phiên làm việc CSDL.

    Returns:
        dict[str, Any]: Kết quả số lượng dòng kế hoạch đã được cập nhật.
    """
    from sqlalchemy import text
    target_gid = str(group_id).strip() or "6469608867469758994"
    result = db.execute(
        text("UPDATE transport_plans SET group_id = :gid"),
        {"gid": target_gid},
    )
    db.commit()
    logger.info("Đã cập nhật toàn bộ %s bản ghi kế hoạch về group_id: %s", result.rowcount, target_gid)
    return {
        "ok": True,
        "message": f"Đã cập nhật toàn bộ {result.rowcount} bản ghi kế hoạch về group_id: {target_gid}",
        "updated_count": result.rowcount,
        "group_id": target_gid,
    }




@router.patch("/{plan_id}/vehicle", response_model=TransportPlanOut)
def update_plan_vehicle(
    plan_id: int,
    payload: PlanVehicleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransportPlanOut:
    """Cập nhật xe trong DB nội bộ, chờ TMS và ghi audit theo phiên bản."""
    if user.role.upper() not in ("ADMIN", "DHVT"):
        raise HTTPException(403, "Chỉ ĐHVT hoặc Admin được cập nhật kế hoạch.")
    values = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    if not values:
        raise HTTPException(422, "Cần ít nhất một trường cập nhật.")
    if values.get("carrier_id") and not db.get(Carrier, values["carrier_id"]):
        raise HTTPException(422, "Nhà xe không tồn tại.")
    if values.get("planned_truck_plate"):
        values["planned_truck_plate"] = clean_plate(values["planned_truck_plate"])
    if values.get("container_no"):
        values["container_no"] = clean_container(values["container_no"])
        if not validate_iso6346(values["container_no"]):
            raise HTTPException(422, "Số container không hợp lệ theo ISO 6346.")
    if "required_time" in values:
        values["eta"] = values["required_time"]
    fields = sorted(values)
    values.update(version=payload.expected_version + 1, tms_sync_status="PENDING", updated_at=datetime.now())
    result = db.execute(update(TransportPlan).where(
        TransportPlan.id == plan_id, TransportPlan.version == payload.expected_version,
    ).values(**values))
    if result.rowcount != 1:
        db.rollback()
        if not db.get(TransportPlan, plan_id):
            raise HTTPException(404, "Không tìm thấy kế hoạch.")
        raise HTTPException(409, "Kế hoạch đã thay đổi; tải lại trước khi cập nhật.")
    db.add(ActivityLog(id=snowflake.generate(), actor_id=str(user.id), action="PLAN_VEHICLE_UPDATED",
                       entity_type="transport_plan", entity_id=str(plan_id),
                       details={"fields": fields, "version": payload.expected_version + 1, "sync": "PENDING"}))
    db.commit()
    plan = db.get(TransportPlan, plan_id)
    db.refresh(plan)
    return TransportPlanOut.model_validate(plan)
