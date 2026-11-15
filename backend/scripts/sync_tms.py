"""Script kéo dữ liệu danh mục và kế hoạch ngày từ hệ thống TMS (`be-tms`) về MySQL.

Cách dùng (chạy trong thư mục `backend`):
    .venv/bin/python scripts/sync_tms.py --date 2026-11-13
    .venv/bin/python scripts/sync_tms.py --master-only
    .venv/bin/python scripts/sync_tms.py --plans-only --date 2026-11-13
    .venv/bin/python scripts/sync_tms.py --date 2026-11-13 --dry-run
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

# Đảm bảo import được package `src` khi chạy trực tiếp script
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.infrastructure.database import SessionLocal
from src.infrastructure.models import Carrier, Customer, TransportPlan, Warehouse
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiClient, TmsApiError


def _utc_now() -> datetime:
    """Trả về thời điểm hiện tại theo chuẩn UTC."""
    return datetime.now(timezone.utc)


def _normalize_text(value: Optional[str]) -> str:
    """Chuẩn hóa chuỗi tiếng Việt không dấu, chữ thường để đối chiếu tìm kiếm."""
    if not value:
        return ""
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.replace("đ", "d").replace("Đ", "D").lower().split())


def sync_carriers(db: Session, client: TmsApiClient) -> dict[str, int]:
    """Đồng bộ danh mục nhà xe từ `GET /carriers` vào bảng `carriers`."""
    rows = client.fetch_carriers(active_only=False)
    created, updated = 0, 0
    now = _utc_now()

    for item in rows:
        tms_id = item.get("id")
        if tms_id is None:
            continue
        tms_id_int = int(tms_id)
        name = str(item.get("name") or item.get("short_name") or f"Carrier #{tms_id_int}").strip()
        short_name = str(item.get("short_name")).strip() if item.get("short_name") else None
        is_active = int(item.get("status", 1)) == 1

        existing = db.scalar(select(Carrier).where(Carrier.tms_carrier_id == tms_id_int))
        if existing is None:
            db.add(
                Carrier(
                    id=snowflake.generate(),
                    tms_carrier_id=tms_id_int,
                    code=str(item.get("code")).strip() if item.get("code") else None,
                    name=name,
                    short_name=short_name,
                    normalized_name=_normalize_text(short_name or name),
                    tax_code=str(item.get("tax_code")).strip() if item.get("tax_code") else None,
                    is_active=is_active,
                    synced_at=now,
                )
            )
            created += 1
        else:
            existing.code = str(item.get("code")).strip() if item.get("code") else existing.code
            existing.name = name
            existing.short_name = short_name
            existing.normalized_name = _normalize_text(short_name or name)
            existing.tax_code = str(item.get("tax_code")).strip() if item.get("tax_code") else existing.tax_code
            existing.is_active = is_active
            existing.synced_at = now
            updated += 1

    db.flush()
    return {"fetched": len(rows), "created": created, "updated": updated}


def sync_customers(db: Session, client: TmsApiClient) -> dict[str, int]:
    """Đồng bộ danh mục khách hàng từ `GET /customers/get-dropdown` vào bảng `customers`."""
    rows = client.fetch_customers()
    created, updated = 0, 0
    now = _utc_now()

    for item in rows:
        cid = item.get("id")
        if cid is None:
            continue
        tms_cid = str(cid)
        name = str(item.get("name") or item.get("short_name") or f"Customer #{tms_cid}").strip()
        norm_name = _normalize_text(item.get("short_name") or name)

        existing = db.scalar(select(Customer).where(Customer.tms_customer_id == tms_cid))
        if existing is None:
            db.add(
                Customer(
                    id=snowflake.generate(),
                    tms_customer_id=tms_cid,
                    name=name,
                    normalized_name=norm_name,
                    is_active=True,
                    synced_at=now,
                )
            )
            created += 1
        else:
            existing.name = name
            existing.normalized_name = norm_name
            existing.is_active = True
            existing.synced_at = now
            updated += 1

    db.flush()
    return {"fetched": len(rows), "created": created, "updated": updated}


def _pick_customer_id_from_relations(
    relations: list[dict[str, Any]],
    customer_by_tms_id: dict[str, int],
    forwarder_id: Optional[int],
) -> Optional[int]:
    """Chọn `customers.id` nội bộ từ mảng `forwarder_relations` của kho TMS."""
    for rel in relations:
        if forwarder_id is not None and rel.get("forwarder_id") != forwarder_id:
            continue
        tms_cid = rel.get("customer_id")
        if tms_cid is not None and str(tms_cid) in customer_by_tms_id:
            return customer_by_tms_id[str(tms_cid)]
    for rel in relations:
        tms_cid = rel.get("customer_id")
        if tms_cid is not None and str(tms_cid) in customer_by_tms_id:
            return customer_by_tms_id[str(tms_cid)]
    return None


def sync_warehouses(db: Session, client: TmsApiClient) -> dict[str, int]:
    """Đồng bộ danh mục kho từ `GET /warehouses` vào bảng `warehouses`."""
    rows = client.fetch_warehouses(active_only=False)
    customer_by_tms_id = {
        c.tms_customer_id: c.id for c in db.scalars(select(Customer)).all()
    }
    created, updated = 0, 0
    now = _utc_now()

    for item in rows:
        wid = item.get("id")
        if wid is None:
            continue
        tms_wid = str(wid)
        name = str(item.get("name") or f"Warehouse #{tms_wid}").strip()
        address = str(item.get("address")).strip() if item.get("address") else None
        is_active = int(item.get("status", 1)) == 1
        relations = item.get("forwarder_relations") or []
        local_cust_id = _pick_customer_id_from_relations(
            relations, customer_by_tms_id, client.forwarder_id
        )

        existing = db.scalar(select(Warehouse).where(Warehouse.tms_warehouse_id == tms_wid))
        if existing is None:
            db.add(
                Warehouse(
                    id=snowflake.generate(),
                    tms_warehouse_id=tms_wid,
                    customer_id=local_cust_id,
                    name=name,
                    normalized_name=_normalize_text(name),
                    address=address,
                    is_active=is_active,
                    synced_at=now,
                )
            )
            created += 1
        else:
            if local_cust_id is not None:
                existing.customer_id = local_cust_id
            existing.name = name
            existing.normalized_name = _normalize_text(name)
            existing.address = address
            existing.is_active = is_active
            existing.synced_at = now
            updated += 1

    db.flush()
    return {"fetched": len(rows), "created": created, "updated": updated}


def sync_daily_plans(db: Session, client: TmsApiClient, plan_date: date) -> dict[str, int]:
    """Kéo chuyến ngày `plan_date` từ `/dispatch/confirmed` và nối `/transport-plan/my-orders`."""
    date_str = plan_date.isoformat()
    dispatches = client.fetch_confirmed_dispatches(date_str)
    orders = client.fetch_my_orders(date_str, date_str)

    order_index: dict[tuple[int, str], dict[str, Any]] = {}
    for o in orders:
        oid = o.get("id")
        otype = str(o.get("order_type") or "").strip()
        if oid is not None and otype:
            order_index[(int(oid), otype)] = o

    carrier_by_tms = {
        c.tms_carrier_id: c.id for c in db.scalars(select(Carrier)).all() if c.tms_carrier_id is not None
    }
    customer_by_tms = {c.tms_customer_id: c.id for c in db.scalars(select(Customer)).all()}
    warehouse_by_tms = {w.tms_warehouse_id: w.id for w in db.scalars(select(Warehouse)).all()}

    created, updated = 0, 0
    for disp in dispatches:
        tms_carrier_id = disp.get("carrier_id")
        local_carrier_id = carrier_by_tms.get(int(tms_carrier_id)) if tms_carrier_id is not None else None
        carrier_name = disp.get("carrier_name")
        dispatch_code = disp.get("dispatch_code") or f"DISP-{disp.get('id')}"

        order_pairs = [
            ("dong", "loading-order", disp.get("loading_order")),
            ("tra", "return-order", disp.get("return_order")),
        ]
        for bot_order_type, tms_order_type, order_obj in order_pairs:
            if not isinstance(order_obj, dict) or order_obj.get("id") is None:
                continue
            oid = int(order_obj["id"])
            matched_order = order_index.get((oid, tms_order_type), {})
            container_no = (
                order_obj.get("container_no") or matched_order.get("container_no") or None
            )
            if container_no:
                container_no = str(container_no).strip().upper()
            order_code = order_obj.get("order_code") or matched_order.get("order_code") or dispatch_code

            tms_cust_id = matched_order.get("customer_id")
            local_cust_id = customer_by_tms.get(str(tms_cust_id)) if tms_cust_id is not None else None
            customer_name = matched_order.get("customer_name")

            tms_wh_id = order_obj.get("warehouse_id")
            local_wh_id = warehouse_by_tms.get(str(tms_wh_id)) if tms_wh_id is not None else None
            warehouse_name = order_obj.get("warehouse_name")

            note_tag = f"[TMS:{dispatch_code}/{order_code}]"
            existing = None
            if container_no:
                existing = db.scalar(
                    select(TransportPlan).where(
                        TransportPlan.plan_date == plan_date,
                        TransportPlan.order_type == bot_order_type,
                        TransportPlan.container_no == container_no,
                    )
                )
            if existing is None:
                existing = db.scalar(
                    select(TransportPlan).where(
                        TransportPlan.plan_date == plan_date,
                        TransportPlan.order_type == bot_order_type,
                        TransportPlan.notes.like(f"%{note_tag}%"),
                    )
                )

            if existing is None:
                db.add(
                    TransportPlan(
                        id=snowflake.generate(),
                        carrier_id=local_carrier_id,
                        plan_date=plan_date,
                        order_type=bot_order_type,
                        container_no=container_no,
                        customer_name=customer_name,
                        customer_id=local_cust_id,
                        warehouse_id=local_wh_id,
                        fleet_partner=carrier_name,
                        carrier_name=carrier_name,
                        delivery_address=warehouse_name,
                        notes=note_tag,
                    )
                )
                created += 1
            else:
                existing.carrier_id = local_carrier_id or existing.carrier_id
                existing.fleet_partner = carrier_name or existing.fleet_partner
                existing.carrier_name = carrier_name or existing.carrier_name
                if container_no:
                    existing.container_no = container_no
                if local_cust_id:
                    existing.customer_id = local_cust_id
                if customer_name:
                    existing.customer_name = customer_name
                if local_wh_id:
                    existing.warehouse_id = local_wh_id
                if warehouse_name:
                    existing.delivery_address = warehouse_name
                updated += 1

    db.flush()
    return {
        "dispatches": len(dispatches),
        "orders": len(orders),
        "created": created,
        "updated": updated,
    }


def main() -> int:
    """Điểm vào CLI đồng bộ dữ liệu TMS."""
    parser = argparse.ArgumentParser(description="Đồng bộ dữ liệu từ TMS (be-tms) về MySQL")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Ngày kế hoạch YYYY-MM-DD (mặc định: hôm nay)",
    )
    parser.add_argument("--master-only", action="store_true", help="Chỉ đồng bộ danh mục (carriers, customers, warehouses)")
    parser.add_argument("--plans-only", action="store_true", help="Chỉ đồng bộ kế hoạch ngày (transport_plans)")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử và rollback, không ghi DB")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    client = TmsApiClient()
    db = SessionLocal()

    try:
        client.login()
        print(f"[TMS] Đăng nhập thành công (forwarder_id={client.forwarder_id}).")

        if not args.plans_only:
            c_stats = sync_carriers(db, client)
            print(f"[Carriers]   {c_stats}")
            cu_stats = sync_customers(db, client)
            print(f"[Customers]  {cu_stats}")
            w_stats = sync_warehouses(db, client)
            print(f"[Warehouses] {w_stats}")

        if not args.master_only:
            p_stats = sync_daily_plans(db, client, target_date)
            print(f"[Plans {target_date}] {p_stats}")

        if args.dry_run:
            db.rollback()
            print("[DRY-RUN] Đã rollback, không ghi thay đổi vào MySQL.")
        else:
            db.commit()
            print("[SUCCESS] Đã đồng bộ dữ liệu TMS vào MySQL thành công.")
        return 0
    except TmsApiError as exc:
        db.rollback()
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] Lỗi không mong đợi khi đồng bộ TMS: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
