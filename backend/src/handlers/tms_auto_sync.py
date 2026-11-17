"""Service Tự Động Đồng Bộ Kế Hoạch & Danh Mục Từ TMS (`be-tms`) Theo Chu Kỳ Nền.

Đảm bảo hệ thống luôn chủ động:
1. Dùng `TMS_USERNAME` / `TMS_PASSWORD` để đăng nhập và tự động làm mới Bearer token TMS
   trước khi hết hạn (cộng thêm cơ chế thử lại khi gặp HTTP 401).
2. Định kỳ đồng bộ danh mục Nhà xe, Khách hàng, Kho (`carriers`, `customers`, `warehouses`)
   và kéo kế hoạch ngày hiện tại + ngày kế tiếp + các ngày đang xem trên Web vào `transport_plans`.
3. Cung cấp API trạng thái (`status()`) và kích hoạt đồng bộ tức thì (`trigger_now()`).
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
import os
import re
import threading
import unicodedata
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.handlers.tms_plan_sync_service import sync_transport_plans_from_tms
from src.infrastructure.database import SessionLocal
from src.infrastructure.models import Carrier, Customer, Trailer, Warehouse
from src.infrastructure.snowflake import snowflake
from src.infrastructure.tms_client import TmsApiClient, TmsApiError
from src.observability.logging import get_logger

logger = get_logger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _normalize_ascii(value: Optional[str]) -> str:
    """Chuẩn hóa chuỗi tiếng Việt không dấu, chữ thường để lập chỉ mục tìm kiếm."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).strip())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.replace("đ", "d").replace("Đ", "D").lower().split())


def sync_master_data_from_tms(db: Session, client: TmsApiClient) -> dict[str, dict[str, int]]:
    """Đồng bộ toàn bộ danh mục Nhà xe, Khách hàng và Kho từ `be-tms` về MySQL."""
    now = datetime.now(timezone.utc)

    # 1. Nhà xe (`carriers`)
    carrier_rows = client.fetch_carriers(active_only=False)
    c_created, c_updated = 0, 0
    for item in carrier_rows:
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
                    normalized_name=_normalize_ascii(short_name or name),
                    tax_code=str(item.get("tax_code")).strip() if item.get("tax_code") else None,
                    is_active=is_active,
                    synced_at=now,
                )
            )
            c_created += 1
        else:
            existing.code = str(item.get("code")).strip() if item.get("code") else existing.code
            existing.name = name
            existing.short_name = short_name
            existing.normalized_name = _normalize_ascii(short_name or name)
            existing.tax_code = str(item.get("tax_code")).strip() if item.get("tax_code") else existing.tax_code
            existing.is_active = is_active
            existing.synced_at = now
            c_updated += 1
    db.flush()

    # 2. Khách hàng (`customers`)
    cust_rows = client.fetch_customers()
    cu_created, cu_updated = 0, 0
    for item in cust_rows:
        cid = item.get("id")
        if cid is None:
            continue
        tms_cid = str(cid)
        name = str(item.get("name") or item.get("short_name") or f"Customer #{tms_cid}").strip()
        norm_name = _normalize_ascii(item.get("short_name") or name)
        existing_c = db.scalar(select(Customer).where(Customer.tms_customer_id == tms_cid))
        if existing_c is None:
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
            cu_created += 1
        else:
            existing_c.name = name
            existing_c.normalized_name = norm_name
            existing_c.is_active = True
            existing_c.synced_at = now
            cu_updated += 1
    db.flush()

    # 3. Kho hàng (`warehouses`)
    wh_rows = client.fetch_warehouses(active_only=False)
    customer_by_tms = {
        c.tms_customer_id: c.id for c in db.scalars(select(Customer)).all()
    }
    w_created, w_updated = 0, 0
    for item in wh_rows:
        wid = item.get("id")
        if wid is None:
            continue
        tms_wid = str(wid)
        name = str(item.get("name") or f"Warehouse #{tms_wid}").strip()
        address = str(item.get("address")).strip() if item.get("address") else None
        is_active = int(item.get("status", 1)) == 1
        relations = item.get("forwarder_relations") or []
        local_cust_id: Optional[int] = None
        for prefer_fwd in (True, False):
            for rel in relations:
                if prefer_fwd and client.forwarder_id is not None and rel.get("forwarder_id") != client.forwarder_id:
                    continue
                tms_rel_cid = rel.get("customer_id")
                if tms_rel_cid is not None and str(tms_rel_cid) in customer_by_tms:
                    local_cust_id = customer_by_tms[str(tms_rel_cid)]
                    break
            if local_cust_id is not None:
                break

        existing_w = db.scalar(select(Warehouse).where(Warehouse.tms_warehouse_id == tms_wid))
        if existing_w is None:
            db.add(
                Warehouse(
                    id=snowflake.generate(),
                    tms_warehouse_id=tms_wid,
                    customer_id=local_cust_id,
                    name=name,
                    normalized_name=_normalize_ascii(name),
                    address=address,
                    is_active=is_active,
                    synced_at=now,
                )
            )
            w_created += 1
        else:
            if local_cust_id is not None:
                existing_w.customer_id = local_cust_id
            existing_w.name = name
            existing_w.normalized_name = _normalize_ascii(name)
            existing_w.address = address
            existing_w.is_active = is_active
            existing_w.synced_at = now
            w_updated += 1
    db.flush()

    trailer_stats = sync_trailers_from_tms(db, client)

    return {
        "carriers": {"fetched": len(carrier_rows), "created": c_created, "updated": c_updated},
        "customers": {"fetched": len(cust_rows), "created": cu_created, "updated": cu_updated},
        "warehouses": {"fetched": len(wh_rows), "created": w_created, "updated": w_updated},
        "trailers": trailer_stats,
    }


def sync_trailers_from_tms(db: Session, client: TmsApiClient) -> dict[str, int]:
    """Đồng bộ danh mục rơ-moóc từ `GET /carrier-moocs` vào bảng `trailers`."""
    rows = client.fetch_trailers(active_only=False)
    carrier_by_tms = {
        int(c.tms_carrier_id): c.id
        for c in db.scalars(select(Carrier)).all()
        if c.tms_carrier_id is not None
    }
    now = datetime.now(timezone.utc)
    created, updated = 0, 0

    for item in rows:
        mooc_id = item.get("id")
        raw_plate = (item.get("license_plate") or "").strip()
        if mooc_id is None or not raw_plate:
            continue
        tms_mooc_id = int(mooc_id)
        tms_cid_raw = item.get("carrier_id")
        tms_carrier_id = int(tms_cid_raw) if tms_cid_raw is not None else None
        local_carrier_id = carrier_by_tms.get(tms_carrier_id) if tms_carrier_id is not None else None
        norm_plate = re.sub(r"[^A-Za-z0-9]", "", raw_plate).upper()
        mooc_type_raw = item.get("type")
        mooc_type = int(mooc_type_raw) if mooc_type_raw is not None else None
        model = str(item.get("model")).strip() if item.get("model") else None
        note = str(item.get("note")).strip() if item.get("note") else None
        is_active = int(item.get("status", 1)) == 1

        existing = db.scalar(select(Trailer).where(Trailer.tms_mooc_id == tms_mooc_id))
        if existing is None:
            db.add(
                Trailer(
                    id=snowflake.generate(),
                    tms_mooc_id=tms_mooc_id,
                    tms_carrier_id=tms_carrier_id,
                    carrier_id=local_carrier_id,
                    license_plate=raw_plate.upper(),
                    normalized_plate=norm_plate,
                    mooc_type=mooc_type,
                    model=model,
                    note=note,
                    is_active=is_active,
                    synced_at=now,
                )
            )
            created += 1
        else:
            existing.tms_carrier_id = tms_carrier_id
            if local_carrier_id is not None:
                existing.carrier_id = local_carrier_id
            existing.license_plate = raw_plate.upper()
            existing.normalized_plate = norm_plate
            existing.mooc_type = mooc_type
            existing.model = model
            existing.note = note
            existing.is_active = is_active
            existing.synced_at = now
            updated += 1

    db.flush()
    return {"fetched": len(rows), "created": created, "updated": updated}


def _parse_regions(raw: str) -> list[int]:
    """Phân tích danh sách mã miền TMS từ biến môi trường (mặc định `[1]`)."""
    regions: list[int] = []
    for part in str(raw or "1").split(","):
        s = part.strip()
        if s.isdigit():
            val = int(s)
            if val in (1, 2, 3) and val not in regions:
                regions.append(val)
    return regions or [1]


class TmsAutoSyncScheduler:
    """Bộ lập lịch nền tự động kéo kế hoạch và danh mục từ TMS (`be-tms`) về MySQL."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        client_factory: Optional[Callable[[], TmsApiClient]] = None,
    ) -> None:
        self._session_factory = session_factory
        self._client_factory = client_factory or (lambda: TmsApiClient())
        self._client: Optional[TmsApiClient] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._tracked_targets: deque[tuple[date, int]] = deque(maxlen=6)

        self._last_started_at: Optional[datetime] = None
        self._last_finished_at: Optional[datetime] = None
        self._last_success_at: Optional[datetime] = None
        self._last_master_sync_at: Optional[datetime] = None
        self._next_run_at: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._last_summary: dict[str, Any] = {}
        self._total_runs: int = 0
        self._is_syncing: bool = False

    def is_enabled(self) -> bool:
        """Kiểm tra đồng bộ tự động có được bật và cấu hình hợp lệ hay không."""
        return (
            bool(settings.TMS_SYNC_ENABLED)
            and bool(settings.TMS_AUTO_SYNC_ENABLED)
            and int(settings.TMS_AUTO_SYNC_INTERVAL_MINUTES or 0) > 0
            and self._get_client().has_valid_credentials()
        )

    def get_client(self) -> TmsApiClient:
        """Lấy thực thể `TmsApiClient` dùng chung đang lưu cache Bearer token TMS."""
        return self._get_client()

    def _get_client(self) -> TmsApiClient:
        """Lấy hoặc khởi tạo `TmsApiClient` dùng chung để giữ token TMS qua nhiều chu kỳ."""
        with self._state_lock:
            if self._client is None:
                self._client = self._client_factory()
            return self._client

    def track_date(self, plan_date: date, region: int = 1) -> None:
        """Ghi nhận cặp `(plan_date, region)` người dùng vừa thao tác để luồng nền ưu tiên cập nhật."""
        clean_region = region if region in (1, 2, 3) else 1
        pair = (plan_date, clean_region)
        with self._state_lock:
            if pair in self._tracked_targets:
                self._tracked_targets.remove(pair)
            self._tracked_targets.append(pair)

    def _target_pairs(self) -> list[tuple[date, int]]:
        """Tổng hợp các cặp `(plan_date, region)` cần kéo ở chu kỳ hiện tại."""
        today_vn = datetime.now(VN_TZ).date()
        days_back = max(0, min(7, int(settings.TMS_AUTO_SYNC_DAYS_BACK or 0)))
        days_ahead = max(0, min(7, int(settings.TMS_AUTO_SYNC_DAYS_AHEAD or 1)))
        regions = _parse_regions(settings.TMS_AUTO_SYNC_REGIONS)

        ordered: list[tuple[date, int]] = []
        seen: set[tuple[date, int]] = set()
        for offset in range(-days_back, days_ahead + 1):
            d = today_vn + timedelta(days=offset)
            for reg in regions:
                pair = (d, reg)
                if pair not in seen:
                    seen.add(pair)
                    ordered.append(pair)

        with self._state_lock:
            tracked_copy = list(self._tracked_targets)
        for pair in reversed(tracked_copy):
            if pair not in seen:
                seen.add(pair)
                ordered.append(pair)
        return ordered

    def _needs_master_sync(self, force_master: bool = False) -> bool:
        """Xác định có cần làm mới danh mục Nhà xe/Khách/Kho trong chu kỳ này không."""
        if force_master:
            return True
        interval_min = int(settings.TMS_AUTO_SYNC_MASTER_INTERVAL_MINUTES or 0)
        if interval_min <= 0:
            return False
        with self._state_lock:
            last_master = self._last_master_sync_at
        if last_master is None:
            return True
        return datetime.now(timezone.utc) - last_master >= timedelta(minutes=interval_min)

    def run_once(self, *, force_master: bool = False) -> dict[str, Any]:
        """Thực thi một lượt đồng bộ chủ động từ TMS (có khóa chống chạy chồng chéo)."""
        if not self._run_lock.acquire(blocking=False):
            return {"skipped": True, "reason": "sync_in_progress"}

        client = self._get_client()
        started_at = datetime.now(timezone.utc)
        with self._state_lock:
            self._is_syncing = True
            self._last_started_at = started_at

        master_stats: Optional[dict[str, Any]] = None
        master_error: Optional[str] = None
        plan_results: list[dict[str, Any]] = []
        total_synced = 0
        error_msg: Optional[str] = None

        try:
            if not client.has_valid_credentials():
                error_msg = "Chưa cấu hình tài khoản/mật khẩu TMS hợp lệ."
            else:
                # Bảo đảm Bearer token TMS luôn tươi mới bằng TMS_USERNAME / TMS_PASSWORD
                client.ensure_fresh_token()
                with self._session_factory() as db:
                    if self._needs_master_sync(force_master=force_master):
                        try:
                            master_stats = sync_master_data_from_tms(db, client)
                            db.commit()
                            with self._state_lock:
                                self._last_master_sync_at = datetime.now(timezone.utc)
                        except (TmsApiError, Exception) as exc:
                            db.rollback()
                            master_error = str(exc)
                            logger.warning("TMS Auto-Sync danh mục gặp lỗi (vẫn tiếp tục kéo kế hoạch ngày): %s", master_error)

                    for p_date, reg in self._target_pairs():
                        res = sync_transport_plans_from_tms(
                            db=db,
                            plan_date=p_date,
                            region=reg,
                            client=client,
                        )
                        plan_results.append(res)
                        total_synced += int(res.get("total_synced") or 0)

                with self._state_lock:
                    self._last_success_at = datetime.now(timezone.utc)
                    self._last_error = master_error
                logger.info(
                    "TMS Auto-Sync hoàn tất: %s lượt ngày/miền, tổng %s lệnh đồng bộ.",
                    len(plan_results),
                    total_synced,
                )
        except (TmsApiError, Exception) as exc:
            error_msg = str(exc)
            with self._state_lock:
                self._last_error = error_msg
            logger.warning("TMS Auto-Sync gặp lỗi ở chu kỳ nền: %s", error_msg)
        finally:
            finished_at = datetime.now(timezone.utc)
            interval_sec = max(30, int(settings.TMS_AUTO_SYNC_INTERVAL_MINUTES or 5) * 60)
            summary = {
                "total_synced": total_synced,
                "targets_count": len(plan_results),
                "targets": [
                    {
                        "plan_date": r.get("plan_date"),
                        "region": r.get("region"),
                        "total_synced": r.get("total_synced"),
                        "inserted": r.get("inserted"),
                        "updated": r.get("updated"),
                    }
                    for r in plan_results
                ],
                "master_synced": master_stats is not None,
                "master_error": master_error,
                "error": error_msg or master_error,
            }
            with self._state_lock:
                self._is_syncing = False
                self._last_finished_at = finished_at
                self._next_run_at = finished_at + timedelta(seconds=interval_sec)
                self._total_runs += 1
                self._last_summary = summary
            self._run_lock.release()
        return summary

    def _worker_loop(self) -> None:
        """Vòng lặp chạy nền định kỳ: chờ khởi động ngắn, chạy đồng bộ và nghỉ tới chu kỳ tiếp."""
        # Nhường vài giây để HTTP server mở cổng xong mới kéo lượt đầu tiên
        if self._stop_event.wait(timeout=2.0):
            return

        while not self._stop_event.is_set():
            if self.is_enabled():
                self.run_once()
            interval_sec = max(30, int(settings.TMS_AUTO_SYNC_INTERVAL_MINUTES or 5) * 60)
            woke = self._wake_event.wait(timeout=interval_sec)
            if woke:
                self._wake_event.clear()

    def start(self) -> None:
        """Khởi động luồng đồng bộ TMS nền nếu được bật và không nằm trong pytest."""
        if "PYTEST_CURRENT_TEST" in os.environ:
            return
        if not settings.TMS_SYNC_ENABLED or not settings.TMS_AUTO_SYNC_ENABLED:
            logger.info("TMS Auto-Sync đang tắt theo cấu hình môi trường.")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="tms-auto-sync-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Đã bật TMS Auto-Sync chủ động (chu kỳ %s phút, danh mục %s phút, miền=%s).",
            settings.TMS_AUTO_SYNC_INTERVAL_MINUTES,
            settings.TMS_AUTO_SYNC_MASTER_INTERVAL_MINUTES,
            settings.TMS_AUTO_SYNC_REGIONS,
        )

    def stop(self) -> None:
        """Dừng luồng đồng bộ TMS nền an toàn khi tắt ứng dụng."""
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def trigger_now(self) -> dict[str, Any]:
        """Kích hoạt chạy một lượt đồng bộ ngay lập tức (đồng bộ trực tiếp trong request hoặc đánh thức worker)."""
        return self.run_once()

    def wake_up(self) -> None:
        """Đánh thức worker nền chạy chu kỳ đồng bộ tiếp theo ngay khi có cập nhật mới."""
        if self._thread is not None and self._thread.is_alive():
            self._wake_event.set()

    def status(self) -> dict[str, Any]:
        """Trả về ảnh chụp trạng thái hoạt động hiện tại của bộ đồng bộ TMS tự động."""
        with self._state_lock:
            token_at = self._client.token_obtained_at if self._client else None
            has_creds = self._client.has_valid_credentials() if self._client else TmsApiClient().has_valid_credentials()
            return {
                "enabled": bool(settings.TMS_SYNC_ENABLED and settings.TMS_AUTO_SYNC_ENABLED),
                "credentials_configured": has_creds,
                "running": bool(self._thread and self._thread.is_alive()),
                "is_syncing": self._is_syncing,
                "interval_minutes": int(settings.TMS_AUTO_SYNC_INTERVAL_MINUTES or 5),
                "master_interval_minutes": int(settings.TMS_AUTO_SYNC_MASTER_INTERVAL_MINUTES or 360),
                "regions": _parse_regions(settings.TMS_AUTO_SYNC_REGIONS),
                "tracked_dates": [
                    {"plan_date": d.isoformat(), "region": r}
                    for d, r in self._tracked_targets
                ],
                "total_runs": self._total_runs,
                "last_started_at": self._last_started_at.isoformat() if self._last_started_at else None,
                "last_finished_at": self._last_finished_at.isoformat() if self._last_finished_at else None,
                "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
                "last_master_sync_at": self._last_master_sync_at.isoformat() if self._last_master_sync_at else None,
                "next_run_at": self._next_run_at.isoformat() if self._next_run_at else None,
                "tms_token_obtained_at": token_at.isoformat() if token_at else None,
                "last_error": self._last_error,
                "last_summary": self._last_summary,
            }


tms_auto_sync = TmsAutoSyncScheduler()
