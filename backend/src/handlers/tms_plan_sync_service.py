"""Service Đồng Bộ Kế Hoạch Vận Chuyển Từ Hệ Thống TMS (`be-tms`) Về MySQL.

Chịu trách nhiệm:
1. Gọi `TmsApiClient.fetch_transport_plan_by_date(plan_date, region)` kéo toàn bộ
   `return_orders` (Lệnh trả) và `loading_orders` (Lệnh đóng) từ TMS.
2. Làm phẳng dữ liệu vào bảng `transport_plans`, map `customer_id`, `warehouse_id`,
   `carrier_id` và gắn mặc định `group_id = "b0301d81c0ee29b070ff"`.
3. Hỗ trợ cập nhật lại (`upsert`) theo `tms_order_id` hoặc ghi đè sạch dữ liệu ngày.
4. Tính toán tổng hợp cân đối vỏ (20', 40', Tổng) và tình trạng vỏ từ DB thật.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import unicodedata
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.domain.rules import clean_container, clean_phone, clean_plate
from src.infrastructure.models import Carrier, Customer, Driver, TransportPlan, Warehouse
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiClient
from src.observability.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PLAN_GROUP_ID = "b0301d81c0ee29b070ff"


def _normalize_text(val: Optional[str]) -> str:
    """Chuẩn hóa chuỗi tiếng Việt không dấu viết thường phục vụ ánh xạ tên danh mục."""
    if not val:
        return ""
    decomposed = unicodedata.normalize("NFD", str(val).strip())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.replace("đ", "d").replace("Đ", "D").lower().split())


def _to_decimal(val: Any) -> Optional[Decimal]:
    """Chuyển đổi giá trị tải trọng sang Decimal an toàn."""
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _parse_tms_date(raw: Optional[str], fallback: date) -> date:
    """Phân tích ngày dạng `DD/MM/YYYY` hoặc `YYYY-MM-DD` từ payload TMS."""
    if not raw:
        return fallback
    s = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return fallback


def _format_grade(order: dict[str, Any]) -> Optional[str]:
    """Chuẩn hóa phân hạng vỏ container từ `container_grade` hoặc `container_grade_id`."""
    grade = order.get("container_grade")
    if grade:
        return str(grade).strip()
    grade_id = order.get("container_grade_id")
    if grade_id is not None:
        return f"Loại {grade_id}"
    return None


def _format_route(terminal_name: Optional[str], ward_name: Optional[str], province_name: Optional[str]) -> Optional[str]:
    """Tạo chuỗi tuyến vận chuyển gọn từ cảng nhập/xuất và phường/tỉnh điểm kho."""
    left = (terminal_name or "HP").strip()
    raw_loc = (ward_name or province_name or "").strip()
    for prefix in ("Phường ", "Xã ", "Thị trấn ", "Thành phố ", "Tỉnh "):
        if raw_loc.startswith(prefix):
            raw_loc = raw_loc[len(prefix):].strip()
    if raw_loc:
        return f"{left} - {raw_loc}"
    return left


def _format_address(order: dict[str, Any]) -> Optional[str]:
    """Ghép địa chỉ đầy đủ (kể cả khi lệnh có nhiều điểm `points_count > 1`)."""
    points = order.get("points") or []
    if isinstance(points, list) and len(points) > 1:
        parts = []
        for idx, pt in enumerate(points, start=1):
            w_name = (pt.get("warehouse_name") or "").strip()
            addr = (pt.get("address") or "").strip()
            r_time = (pt.get("required_time") or "").strip()
            label = f"Điểm {idx}: {w_name}" if w_name else f"Điểm {idx}"
            if r_time:
                label += f" ({r_time})"
            if addr:
                label += f" - {addr}"
            parts.append(label)
        return " | ".join(parts)
    base_addr = (order.get("warehouse_address") or "").strip()
    if not base_addr and isinstance(points, list) and points:
        base_addr = (points[0].get("address") or "").strip()
    return base_addr or None


def sync_transport_plans_from_tms(
    db: Session,
    plan_date: date,
    region: int = 1,
    default_group_id: str = DEFAULT_PLAN_GROUP_ID,
    replace_existing: bool = False,
    clear_all_before_sync: bool = False,
    client: Optional[TmsApiClient] = None,
    auto_commit: bool = True,
) -> dict[str, Any]:
    """Kéo kế hoạch vận chuyển theo ngày & miền từ TMS và đồng bộ vào `transport_plans`.

    - Hỗ trợ làm sạch dữ liệu cũ (`clear_all_before_sync=True`) hoặc thay thế theo ngày/miền.
    - Mặc định thực hiện upsert theo `(plan_date, tms_order_id)` để khi gọi lại API sẽ cập nhật
      toàn bộ trường mới từ TMS mà vẫn bảo toàn thông tin xe/tài xế đã bổ sung nội bộ.
    - Toàn bộ bản ghi được gắn `group_id = default_group_id` nếu chưa có nhóm riêng.
    """
    tms_client = client or TmsApiClient()
    payload = tms_client.fetch_transport_plan_by_date(plan_date.isoformat(), region=region)
    provinces = payload.get("data") or []

    # Nạp trước các bảng danh mục để ánh xạ nhanh không gây N+1 query
    customer_map: dict[str, int] = {}
    for c_id, c_norm in db.execute(select(Customer.id, Customer.normalized_name)).all():
        if c_norm:
            customer_map[c_norm] = c_id

    warehouse_map: dict[str, int] = {}
    for w_id, tms_wid, ltype in db.execute(
        select(Warehouse.id, Warehouse.tms_warehouse_id, Warehouse.location_type)
    ).all():
        if ltype == "warehouse" and tms_wid:
            warehouse_map[str(tms_wid)] = w_id

    carrier_map: dict[int, tuple[int, str]] = {}
    for cid, tms_cid, cname, cshort in db.execute(
        select(Carrier.id, Carrier.tms_carrier_id, Carrier.name, Carrier.short_name)
    ).all():
        if tms_cid is not None:
            carrier_map[int(tms_cid)] = (cid, cshort or cname)

    driver_phone_by_tms_id: dict[int, str] = {
        int(d_tms_id): str(d_phone)
        for d_tms_id, d_phone in db.execute(select(Driver.tms_driver_id, Driver.phone)).all()
        if d_tms_id is not None and d_phone
    }

    confirmed_by_key: dict[tuple[str, Any], dict[str, Any]] = {}
    if hasattr(tms_client, "fetch_confirmed_dispatches"):
        try:
            for disp in tms_client.fetch_confirmed_dispatches(plan_date.isoformat()):
                if not isinstance(disp, dict):
                    continue
                ro = disp.get("return_order")
                if isinstance(ro, dict):
                    if ro.get("id") is not None:
                        confirmed_by_key[("tra", int(ro["id"]))] = disp
                    if ro.get("order_code"):
                        confirmed_by_key[("tra_code", str(ro["order_code"]).strip().upper())] = disp
                lo = disp.get("loading_order")
                if isinstance(lo, dict):
                    if lo.get("id") is not None:
                        confirmed_by_key[("dong", int(lo["id"]))] = disp
                    if lo.get("order_code"):
                        confirmed_by_key[("dong_code", str(lo["order_code"]).strip().upper())] = disp
        except Exception as exc:
            logger.warning("Không thể kéo chi tiết điều phối /dispatch/confirmed ngày %s: %s", plan_date, exc)

    deleted_count = 0
    if clear_all_before_sync:
        res = db.execute(delete(TransportPlan))
        deleted_count = int(res.rowcount or 0)
        db.flush()
    elif replace_existing:
        res = db.execute(
            delete(TransportPlan).where(
                TransportPlan.plan_date == plan_date,
                TransportPlan.region == region,
            )
        )
        deleted_count = int(res.rowcount or 0)
        db.flush()

    existing_by_order_id: dict[int, TransportPlan] = {}
    if not replace_existing and not clear_all_before_sync:
        existing_rows = db.scalars(
            select(TransportPlan).where(
                TransportPlan.plan_date == plan_date,
                TransportPlan.tms_order_id.is_not(None),
            )
        ).all()
        for row in existing_rows:
            if row.tms_order_id is not None:
                existing_by_order_id[int(row.tms_order_id)] = row

    inserted_count = 0
    updated_count = 0
    return_count = 0
    loading_count = 0
    stt_counter = 0

    for prov in provinces:
        prov_id = prov.get("province_id")
        prov_name = prov.get("province_name")

        order_batches = [
            ("tra", "I", prov.get("return_orders") or []),
            ("dong", "X", prov.get("loading_orders") or []),
        ]

        for otype, io_type, orders in order_batches:
            for order in orders:
                stt_counter += 1
                if otype == "tra":
                    return_count += 1
                else:
                    loading_count += 1

                tms_oid = int(order["id"])
                eff_date = _parse_tms_date(order.get("plan_date"), plan_date)
                cust_name = (order.get("customer_name") or "").strip() or None
                cust_id = customer_map.get(_normalize_text(cust_name)) if cust_name else None

                wh_tms_id = order.get("warehouse_id")
                wh_id = warehouse_map.get(str(wh_tms_id)) if wh_tms_id is not None else None

                order_code_str = (order.get("order_code") or "").strip().upper()
                disp = (
                    confirmed_by_key.get((otype, tms_oid))
                    or (confirmed_by_key.get((f"{otype}_code", order_code_str)) if order_code_str else None)
                )

                tms_cid = order.get("carrier_id") or (disp.get("carrier_id") if disp else None)
                local_cid: Optional[int] = None
                mapped_carrier_name: Optional[str] = None
                if tms_cid is not None and int(tms_cid) in carrier_map:
                    local_cid, mapped_carrier_name = carrier_map[int(tms_cid)]
                elif disp and disp.get("carrier_name"):
                    mapped_carrier_name = str(disp["carrier_name"]).strip() or None

                disp_sub = (
                    disp.get("return_order" if otype == "tra" else "loading_order")
                    if isinstance(disp, dict)
                    else None
                )
                raw_cont = order.get("container_no") or (
                    disp_sub.get("container_no") if isinstance(disp_sub, dict) else None
                )
                clean_cont = clean_container(str(raw_cont)) if raw_cont else None
                raw_seal = order.get("container_seal") or (
                    disp_sub.get("container_seal") if isinstance(disp_sub, dict) else None
                )
                raw_size = order.get("container_size")
                size_str = str(raw_size).strip() if raw_size is not None else None

                points = order.get("points")
                ward_name = (order.get("ward_name") or "").strip() or None
                if not ward_name and isinstance(points, list) and points:
                    ward_name = (points[0].get("ward_name") or "").strip() or None

                terminal_name = (order.get("terminal_name") or "").strip() or None
                route_str = _format_route(terminal_name, ward_name, prov_name)
                addr_str = _format_address(order)

                c_warning = (order.get("container_warning") or "").strip() or None
                c_status_msg = (order.get("container_status_message") or "").strip() or None
                if otype == "tra" and not c_warning:
                    c_warning = "normal"
                    if not c_status_msg:
                        c_status_msg = "Bình thường"

                plan_obj = existing_by_order_id.get(tms_oid)
                if plan_obj is None:
                    plan_obj = TransportPlan(id=snowflake.generate())
                    db.add(plan_obj)
                    inserted_count += 1
                else:
                    updated_count += 1

                plan_obj.tms_order_id = tms_oid
                plan_obj.order_code = (order.get("order_code") or "").strip() or None
                plan_obj.plan_date = eff_date
                plan_obj.region = region
                plan_obj.stt = stt_counter
                plan_obj.route_name = route_str
                plan_obj.cargo_io_type = io_type
                plan_obj.order_type = otype
                plan_obj.container_no = clean_cont
                plan_obj.seal_no = str(raw_seal).strip() or None if raw_seal else None
                plan_obj.container_size = size_str
                plan_obj.container_type = (order.get("container_type") or "").strip() or None
                plan_obj.container_grade = _format_grade(order)
                plan_obj.container_ownership = order.get("container_ownership")
                plan_obj.delivery_term = order.get("delivery_term")
                plan_obj.container_warning = c_warning
                plan_obj.container_status_message = c_status_msg
                plan_obj.dispatch_state = order.get("dispatch_state")
                plan_obj.cargo_weight = _to_decimal(order.get("gross_weight"))
                plan_obj.required_time = (order.get("required_time") or "").strip() or None
                plan_obj.customer_name = cust_name
                plan_obj.customer_id = cust_id
                plan_obj.warehouse_id = wh_id
                plan_obj.warehouse_name = (order.get("warehouse_name") or "").strip() or None
                plan_obj.province_id = prov_id
                plan_obj.province_name = prov_name
                plan_obj.ward_name = ward_name
                plan_obj.forwarder_id = order.get("forwarder_id")
                plan_obj.forwarder_name = (order.get("fwd_name") or "").strip() or None
                plan_obj.booking_no = (order.get("booking_no_code") or "").strip() or None
                plan_obj.bill_of_lading_no = (order.get("bill_of_lading_no_code") or "").strip() or None
                plan_obj.cargo_type = (order.get("commodity_name") or "").strip() or None
                plan_obj.vessel_voyage = (order.get("vessel_voyage_name") or "").strip() or None
                plan_obj.full_depot = terminal_name
                plan_obj.eta = (order.get("eta") or order.get("etd") or "").strip() or None
                plan_obj.delivery_address = addr_str
                plan_obj.address = addr_str
                plan_obj.notes = (order.get("note") or "").strip() or None
                plan_obj.points_json = points if isinstance(points, list) else None
                plan_obj.group_id = (plan_obj.group_id or "").strip() or default_group_id

                if local_cid is not None:
                    plan_obj.carrier_id = local_cid
                if mapped_carrier_name:
                    plan_obj.fleet_partner = mapped_carrier_name
                    plan_obj.carrier_name = mapped_carrier_name

                if disp:
                    disp_plate = (
                        disp.get("truck_no")
                        or ((disp.get("vehicle") or {}).get("truck_no") if isinstance(disp.get("vehicle"), dict) else None)
                    )
                    if disp_plate and str(disp_plate).strip():
                        plan_obj.planned_truck_plate = clean_plate(str(disp_plate)) or str(disp_plate).strip().upper()
                    disp_mooc = (
                        disp.get("ro_mooc_no")
                        or ((disp.get("carrier_mooc") or {}).get("truck_no") if isinstance(disp.get("carrier_mooc"), dict) else None)
                    )
                    if disp_mooc and str(disp_mooc).strip():
                        plan_obj.planned_trailer_plate = clean_plate(str(disp_mooc)) or str(disp_mooc).strip().upper()
                    disp_driver_name = (disp.get("driver_name") or "").strip() or None
                    if disp_driver_name:
                        plan_obj.driver_name = disp_driver_name
                    disp_driver_id = disp.get("driver_id")
                    disp_driver_phone = (
                        disp.get("driver_phone")
                        or (driver_phone_by_tms_id.get(int(disp_driver_id)) if disp_driver_id is not None else None)
                    )
                    if disp_driver_phone and str(disp_driver_phone).strip():
                        plan_obj.driver_phone = clean_phone(str(disp_driver_phone)) or str(disp_driver_phone).strip()

    if auto_commit:
        db.commit()
    else:
        db.flush()
    logger.info(
        "Đồng bộ kế hoạch TMS ngày %s (region=%s): inserted=%s, updated=%s, deleted=%s",
        plan_date.isoformat(),
        region,
        inserted_count,
        updated_count,
        deleted_count,
    )

    return {
        "plan_date": plan_date.isoformat(),
        "region": region,
        "provinces_count": len(provinces),
        "return_orders_count": return_count,
        "loading_orders_count": loading_count,
        "total_synced": inserted_count + updated_count,
        "inserted": inserted_count,
        "updated": updated_count,
        "deleted_old": deleted_count,
        "default_group_id_applied": default_group_id,
    }


def _calc_balance_bucket(rows: list[TransportPlan], size_prefix: Optional[str] = None) -> dict[str, int]:
    """Tính thống kê cân đối vỏ cho một kích thước cont hoặc tổng toàn bộ."""
    filtered = rows
    if size_prefix:
        filtered = [r for r in rows if str(r.container_size or "").startswith(size_prefix)]

    ret_rows = [r for r in filtered if r.order_type == "tra"]
    load_rows = [r for r in filtered if r.order_type == "dong"]

    return_count = len(ret_rows)
    unmatchable_count = sum(1 for r in ret_rows if r.container_warning == "empty_drop")
    matchable_count = return_count - unmatchable_count
    loading_count = len(load_rows)

    return {
        "return_count": return_count,
        "unmatchable_count": unmatchable_count,
        "matchable_count": matchable_count,
        "loading_count": loading_count,
        "balance": matchable_count - loading_count,
    }


def build_master_plan_summary(rows: list[TransportPlan]) -> dict[str, Any]:
    """Tính toán bộ số liệu `container_balance` và `container_warning_counts` từ DB thật."""
    ret_rows = [r for r in rows if r.order_type == "tra"]

    return {
        "container_balance": {
            "size_20ft": _calc_balance_bucket(rows, "20"),
            "size_40ft": _calc_balance_bucket(rows, "40"),
            "total": _calc_balance_bucket(rows, None),
        },
        "container_warning_counts": {
            "normal": sum(1 for r in ret_rows if (r.container_warning or "normal") == "normal"),
            "over_combined": sum(1 for r in ret_rows if r.container_warning == "over_combined"),
            "empty_drop": sum(1 for r in ret_rows if r.container_warning == "empty_drop"),
            "other_requested": sum(1 for r in ret_rows if r.container_warning == "other_requested"),
            "soc": sum(
                1 for r in ret_rows
                if r.container_warning == "soc" or r.container_ownership == 2
            ),
        },
    }
