"""Script đồng bộ toàn bộ Master Data từ hệ thống be-tms về cơ sở dữ liệu cục bộ.

Kéo phân trang và upsert theo khóa `tms_*_id` các danh mục:
- Nhà xe (`carriers`)
- Khách hàng (`customers`)
- Kho khách hàng, Cảng, Depot (`warehouses` phân loại theo `location_type`)
- Xe đầu kéo & Rơ-mooc (`vehicles`)
- Tài xế (`drivers`)
"""

from datetime import datetime, timezone
from decimal import Decimal
import sys
import unicodedata
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

# Bảo đảm import được src.* khi chạy trực tiếp từ thư mục gốc hoặc backend/
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.config.settings import settings
from src.domain.rules import clean_phone, compact_plate
from src.infrastructure.database import SessionLocal
from src.infrastructure.models import Carrier, Customer, Driver, Vehicle, Warehouse
from src.infrastructure.snowflake import snowflake


def _normalize_text(val: Optional[str]) -> str:
    """Chuẩn hóa chuỗi tiếng Việt không dấu viết thường phục vụ tra cứu và đối chiếu."""
    if not val:
        return ""
    decomposed = unicodedata.normalize("NFD", val.strip())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.replace("đ", "d").replace("Đ", "D").lower().split())


def _to_decimal(val: Any) -> Optional[Decimal]:
    """Chuyển đổi giá trị số sang Decimal an toàn."""
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _login_tms(client: httpx.Client) -> str:
    """Đăng nhập API be-tms bằng cấu hình trong .env và trả về Bearer token."""
    base_url = settings.TMS_BASE_URL.rstrip("/")
    if not settings.TMS_USERNAME or not settings.TMS_PASSWORD:
        raise RuntimeError("Thiếu TMS_USERNAME hoặc TMS_PASSWORD trong .env")

    resp = client.post(
        f"{base_url}/login",
        json={"username": settings.TMS_USERNAME, "password": settings.TMS_PASSWORD},
    )
    resp.raise_for_status()
    data = resp.json()
    token = (
        (data.get("authorisation") or {}).get("token")
        or data.get("token")
        or data.get("access_token")
    )
    if not token:
        raise RuntimeError(f"Không lấy được token từ API /login: {list(data.keys())}")
    return token


def _fetch_all_pages(
    client: httpx.Client,
    headers: dict[str, str],
    endpoint: str,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    """Tải toàn bộ dữ liệu phân trang từ một endpoint của be-tms."""
    base_url = settings.TMS_BASE_URL.rstrip("/")
    items: list[dict[str, Any]] = []
    page = 1

    while True:
        resp = client.get(
            f"{base_url}/{endpoint.lstrip('/')}",
            params={"per_page": per_page, "page": page},
            headers=headers,
        )
        resp.raise_for_status()
        payload = resp.json()

        data = payload.get("data")
        if isinstance(data, dict) and "data" in data:
            page_items = data.get("data") or []
            last_page = int(data.get("last_page") or 1)
        elif isinstance(data, list):
            page_items = data
            pagination = payload.get("pagination") or {}
            last_page = int(pagination.get("last_page") or 1)
        else:
            page_items = []
            last_page = 1

        items.extend(page_items)
        if page >= last_page or not page_items:
            break
        page += 1

    return items


def sync_carriers(db: Session, rows: list[dict[str, Any]], now: datetime) -> dict[int, int]:
    """Đồng bộ danh mục nhà xe từ TMS và trả về map `tms_carrier_id -> carriers.id`."""
    existing = {
        c.tms_carrier_id: c
        for c in db.scalars(select(Carrier).where(Carrier.tms_carrier_id.is_not(None))).all()
    }
    carrier_map: dict[int, int] = {}

    for row in rows:
        tms_id = int(row["id"])
        name = (row.get("name") or "").strip()
        if not name:
            continue
        short_name = (row.get("short_name") or "").strip() or None
        norm = _normalize_text(short_name or name)
        is_active = int(row.get("status") or 0) == 1

        obj = existing.get(tms_id)
        if obj is None:
            obj = Carrier(
                id=snowflake.generate(),
                tms_carrier_id=tms_id,
                code=row.get("code"),
                name=name,
                short_name=short_name,
                normalized_name=norm,
                tax_code=row.get("tax_code"),
                is_active=is_active,
                synced_at=now,
            )
            db.add(obj)
            existing[tms_id] = obj
        else:
            obj.code = row.get("code")
            obj.name = name
            obj.short_name = short_name
            obj.normalized_name = norm
            obj.tax_code = row.get("tax_code")
            obj.is_active = is_active
            obj.synced_at = now

    db.flush()
    for tms_id, obj in existing.items():
        if tms_id is not None:
            carrier_map[tms_id] = obj.id
    return carrier_map


def sync_customers(db: Session, rows: list[dict[str, Any]], now: datetime) -> int:
    """Đồng bộ danh mục khách hàng từ TMS về bảng `customers`."""
    existing = {
        c.tms_customer_id: c for c in db.scalars(select(Customer)).all()
    }
    count = 0
    for row in rows:
        tms_id = str(row["id"])
        name = (row.get("name") or "").strip()
        if not name:
            continue
        short_name = (row.get("short_name") or "").strip()
        norm = _normalize_text(short_name or name)
        is_active = int(row.get("status") or 0) == 1

        obj = existing.get(tms_id)
        if obj is None:
            obj = Customer(
                id=snowflake.generate(),
                tms_customer_id=tms_id,
                name=name,
                normalized_name=norm,
                is_active=is_active,
                synced_at=now,
            )
            db.add(obj)
            existing[tms_id] = obj
        else:
            obj.name = name
            obj.normalized_name = norm
            obj.is_active = is_active
            obj.synced_at = now
        count += 1
    db.flush()
    return count


def sync_locations(
    db: Session,
    rows: list[dict[str, Any]],
    location_type: str,
    id_prefix: str,
    now: datetime,
) -> int:
    """Đồng bộ Kho khách hàng, Cảng và Depot vào bảng `warehouses` theo `location_type`."""
    existing = {
        w.tms_warehouse_id: w for w in db.scalars(select(Warehouse)).all()
    }
    count = 0
    for row in rows:
        tms_id = f"{id_prefix}{row['id']}"
        name = (row.get("name") or "").strip()
        if not name:
            continue
        norm = _normalize_text(name)
        is_active = int(row.get("status") or 0) == 1

        obj = existing.get(tms_id)
        if obj is None:
            obj = Warehouse(
                id=snowflake.generate(),
                tms_warehouse_id=tms_id,
                location_type=location_type,
                name=name,
                normalized_name=norm,
                address=row.get("address"),
                latitude=_to_decimal(row.get("latitude")),
                longitude=_to_decimal(row.get("longitude")),
                is_active=is_active,
                synced_at=now,
            )
            db.add(obj)
            existing[tms_id] = obj
        else:
            obj.location_type = location_type
            obj.name = name
            obj.normalized_name = norm
            obj.address = row.get("address")
            obj.latitude = _to_decimal(row.get("latitude"))
            obj.longitude = _to_decimal(row.get("longitude"))
            obj.is_active = is_active
            obj.synced_at = now
        count += 1
    db.flush()
    return count


def sync_vehicles(
    db: Session,
    rows: list[dict[str, Any]],
    carrier_map: dict[int, int],
    now: datetime,
) -> int:
    """Đồng bộ danh mục xe đầu kéo & rơ-mooc từ TMS về bảng `vehicles`."""
    existing = {
        v.tms_vehicle_id: v for v in db.scalars(select(Vehicle)).all()
    }
    count = 0
    for row in rows:
        tms_id = int(row["id"])
        raw_plate = (row.get("truck_no") or "").strip()
        if not raw_plate:
            continue
        plate_no = compact_plate(raw_plate) or raw_plate.upper()
        tms_carrier_id = int(row["carrier_id"]) if row.get("carrier_id") else None
        carrier_id = carrier_map.get(tms_carrier_id) if tms_carrier_id else None
        driver_hint = (row.get("vehicle_identification_number") or "").strip() or None
        v_type = int(row.get("vehicles_type") or 1)
        is_active = int(row.get("status") or 0) == 1

        obj = existing.get(tms_id)
        if obj is None:
            obj = Vehicle(
                id=snowflake.generate(),
                tms_vehicle_id=tms_id,
                tms_carrier_id=tms_carrier_id,
                carrier_id=carrier_id,
                plate_no=plate_no,
                vehicle_type=v_type,
                payload_capacity=_to_decimal(row.get("payload_capacity")),
                driver_hint_name=driver_hint,
                is_active=is_active,
                synced_at=now,
            )
            db.add(obj)
            existing[tms_id] = obj
        else:
            obj.tms_carrier_id = tms_carrier_id
            obj.carrier_id = carrier_id
            obj.plate_no = plate_no
            obj.vehicle_type = v_type
            obj.payload_capacity = _to_decimal(row.get("payload_capacity"))
            obj.driver_hint_name = driver_hint
            obj.is_active = is_active
            obj.synced_at = now
        count += 1
    db.flush()
    return count


def sync_drivers(
    db: Session,
    rows: list[dict[str, Any]],
    carrier_map: dict[int, int],
    now: datetime,
) -> int:
    """Đồng bộ danh mục tài xế từ TMS về bảng `drivers`."""
    existing = {
        d.tms_driver_id: d for d in db.scalars(select(Driver)).all()
    }
    count = 0
    for row in rows:
        tms_id = int(row["id"])
        full_name = (row.get("full_name") or "").strip()
        if not full_name:
            continue
        tms_carrier_id = int(row["carrier_id"]) if row.get("carrier_id") else None
        carrier_id = carrier_map.get(tms_carrier_id) if tms_carrier_id else None
        phone = clean_phone(row.get("phone")) or (row.get("phone") or "").strip() or None
        is_active = int(row.get("status") or 0) == 1

        obj = existing.get(tms_id)
        if obj is None:
            obj = Driver(
                id=snowflake.generate(),
                tms_driver_id=tms_id,
                tms_carrier_id=tms_carrier_id,
                carrier_id=carrier_id,
                full_name=full_name,
                normalized_name=_normalize_text(full_name),
                phone=phone,
                identity_no=(row.get("identity_no") or "").strip() or None,
                license_no=(row.get("license_no") or "").strip() or None,
                is_active=is_active,
                synced_at=now,
            )
            db.add(obj)
            existing[tms_id] = obj
        else:
            obj.tms_carrier_id = tms_carrier_id
            obj.carrier_id = carrier_id
            obj.full_name = full_name
            obj.normalized_name = _normalize_text(full_name)
            obj.phone = phone
            obj.identity_no = (row.get("identity_no") or "").strip() or None
            obj.license_no = (row.get("license_no") or "").strip() or None
            obj.is_active = is_active
            obj.synced_at = now
        count += 1
    db.flush()
    return count


def main() -> None:
    """Chạy toàn bộ tiến trình đồng bộ Master Data từ API be-tms về MySQL cục bộ."""
    now = datetime.now(timezone.utc)
    timeout = httpx.Timeout(settings.TMS_TIMEOUT_SECONDS)

    with httpx.Client(timeout=timeout) as client:
        print(f"[TMS_SYNC] Đang đăng nhập {settings.TMS_BASE_URL} ...")
        token = _login_tms(client)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        carriers_raw = _fetch_all_pages(client, headers, "carriers")
        customers_raw = _fetch_all_pages(client, headers, "customers")
        warehouses_raw = _fetch_all_pages(client, headers, "warehouses")
        ports_raw = _fetch_all_pages(client, headers, "ports")
        depots_raw = _fetch_all_pages(client, headers, "depots")
        vehicles_raw = _fetch_all_pages(client, headers, "vehicles")
        drivers_raw = _fetch_all_pages(client, headers, "drivers")

    with SessionLocal() as db:
        carrier_map = sync_carriers(db, carriers_raw, now)
        n_cust = sync_customers(db, customers_raw, now)
        n_wh = sync_locations(db, warehouses_raw, "warehouse", "", now)
        n_port = sync_locations(db, ports_raw, "port", "PORT:", now)
        n_depot = sync_locations(db, depots_raw, "depot", "DEPOT:", now)
        n_veh = sync_vehicles(db, vehicles_raw, carrier_map, now)
        n_drv = sync_drivers(db, drivers_raw, carrier_map, now)
        db.commit()

    print("[TMS_SYNC] Hoàn tất đồng bộ Master Data:")
    print(f"  - Nhà xe (carriers)     : {len(carrier_map)}")
    print(f"  - Khách hàng (customers): {n_cust}")
    print(f"  - Kho KH (warehouses)   : {n_wh}")
    print(f"  - Cảng (ports)          : {n_port}")
    print(f"  - Depot (depots)        : {n_depot}")
    print(f"  - Xe & Mooc (vehicles)  : {n_veh}")
    print(f"  - Tài xế (drivers)      : {n_drv}")


if __name__ == "__main__":
    main()
