"""Dịch vụ giám sát sức khỏe Zalo OA (`ZaloOaWatchdog`), phát sự kiện SSE và lập lịch nhắc việc nền.

Chức năng chính:
1. Kiểm tra định kỳ `/api/bot/status` của `oa-bridge` (kết nối & token Zalo OA).
2. Theo dõi chuỗi lỗi gửi tin từ `ZaloDispatcher` và khoảng lặng webhook giờ hành chính.
3. Khi Zalo OA gặp sự cố đọc/gửi: phát sự kiện SSE thời gian thực lên Web Dashboard, ghi
   `ActivityLog(ZALO_OA_HEALTH_ALERT)`, tạo `ReviewCase` ưu tiên `HIGH` và bắn webhook dự phòng (nếu cấu hình).
4. Khi Zalo OA phục hồi: tự động đẩy lại tin nhắn kẹt và gửi thông báo phục hồi vào nhóm Zalo ĐHVT.
5. Chạy định kỳ tác vụ xả bộ đệm gom tin rời rạc 60 giây (`flush_expired_carrier_drafts`) và bản tin chủ động ĐHVT.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import threading
import time
from typing import Any, Optional
import urllib.request
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.config.settings import settings
from src.domain.enums import OutboundStatus, ReviewStatus
from src.infrastructure.database import SessionLocal
from src.infrastructure.models import ActivityLog, OutboundMessage, ReviewCase, ZaloMessage
from src.infrastructure.snowflake import snowflake
from src.observability.logging import get_logger

logger = get_logger(__name__)
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class SseEventBus:
    """Kênh phát sự kiện thời gian thực (Server-Sent Events) an toàn đa luồng tới Web Dashboard."""

    def __init__(self) -> None:
        """Khởi tạo tập subscriber và hàng đợi sự kiện gần nhất."""
        self._lock = threading.Lock()
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = set()
        self._recent: deque[dict[str, Any]] = deque(maxlen=50)

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue[dict[str, Any]]:
        """Đăng ký một kết nối SSE mới từ trình duyệt ĐHVT."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add((loop, q))
        return q

    def unsubscribe(self, loop: asyncio.AbstractEventLoop, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Hủy đăng ký kết nối SSE khi trình duyệt đóng tab."""
        with self._lock:
            self._subscribers.discard((loop, q))

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Phát sự kiện tới toàn bộ trình duyệt đang kết nối SSE."""
        event = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }
        with self._lock:
            self._recent.append(event)
            targets = list(self._subscribers)
        for loop, q in targets:
            try:
                loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass

    def recent_events(self) -> list[dict[str, Any]]:
        """Trả danh sách sự kiện hệ thống gần nhất."""
        with self._lock:
            return list(self._recent)


sse_bus = SseEventBus()


class ZaloOaWatchdog:
    """Bộ giám sát kết nối Zalo OA Bridge, cảnh báo đa kênh và xả bộ đệm gom tin 60 giây."""

    def __init__(self) -> None:
        """Khởi tạo trạng thái sức khỏe Zalo OA và khóa đồng bộ luồng nền."""
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status: str = "HEALTHY"  # HEALTHY | OA_DISCONNECTED | OA_SEND_FAILURE | OA_READ_FAILURE
        self._consecutive_health_failures: int = 0
        self._consecutive_send_failures: int = 0
        self._last_error: Optional[str] = None
        self._last_checked_at: Optional[datetime] = None
        self._last_webhook_at: Optional[datetime] = None
        self._last_alert_at: Optional[datetime] = None
        self._oa_info: Optional[dict[str, Any]] = None

    def record_webhook_received(self) -> None:
        """Ghi nhận thời điểm gần nhất Backend nhận được sự kiện webhook từ Zalo OA."""
        with self._lock:
            self._last_webhook_at = datetime.now(timezone.utc)

    def record_outbound_result(self, ok: bool, error_msg: Optional[str] = None) -> None:
        """Cập nhật kết quả gửi tin từ `ZaloDispatcher` để phát hiện chuỗi lỗi gửi Zalo OA."""
        trigger_alert = False
        recovered = False
        with self._lock:
            if ok:
                was_down = self._status == "OA_SEND_FAILURE"
                self._consecutive_send_failures = 0
                if was_down:
                    self._status = "HEALTHY"
                    self._last_error = None
                    recovered = True
            else:
                self._consecutive_send_failures += 1
                self._last_error = error_msg or "Lỗi gửi tin nhắn Zalo OA"
                is_critical_code = bool(
                    error_msg
                    and any(code in str(error_msg) for code in ("-216", "-124", "-201", "-213", "HTTP 502", "HTTP 503"))
                )
                if self._consecutive_send_failures >= 3 or is_critical_code:
                    if self._status != "OA_SEND_FAILURE":
                        trigger_alert = True
                    self._status = "OA_SEND_FAILURE"

        if trigger_alert:
            self._emit_alert("OA_SEND_FAILURE", self._last_error or "Chuỗi lỗi gửi tin Zalo OA liên tiếp.")
        elif recovered:
            self._emit_recovery()

    def check_bridge_health(self) -> dict[str, Any]:
        """Gọi trực tiếp `GET {ZALO_BRIDGE_URL}/api/bot/status` để kiểm tra sức khỏe Zalo OA & token."""
        url = f"{settings.ZALO_BRIDGE_URL.rstrip('/')}/api/bot/status"
        ok = False
        err_msg: Optional[str] = None
        oa_info: Optional[dict[str, Any]] = None
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=6) as resp:
                body = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
                ok = bool(resp.status == 200 and body.get("ok"))
                oa_info = body.get("oa_info") if isinstance(body.get("oa_info"), dict) else None
                if not ok:
                    err_msg = str(body.get("error") or f"OA Bridge status HTTP {resp.status}")
        except Exception as exc:
            ok = False
            err_msg = f"Không thể kết nối Zalo OA Bridge ({url}): {exc}"

        now = datetime.now(timezone.utc)
        trigger_alert = False
        recovered = False
        with self._lock:
            self._last_checked_at = now
            if ok:
                was_down = self._status != "HEALTHY"
                self._consecutive_health_failures = 0
                self._oa_info = oa_info
                if was_down:
                    self._status = "HEALTHY"
                    self._last_error = None
                    recovered = True
            else:
                self._consecutive_health_failures += 1
                self._last_error = err_msg
                if self._consecutive_health_failures >= 2:
                    if self._status != "OA_DISCONNECTED":
                        trigger_alert = True
                    self._status = "OA_DISCONNECTED"

        if trigger_alert:
            self._emit_alert("OA_DISCONNECTED", err_msg or "Zalo OA Bridge mất kết nối hoặc hết hạn token.")
        elif recovered:
            self._emit_recovery()

        return self.snapshot()

    def _emit_alert(self, state_code: str, error_detail: str) -> None:
        """Phát cảnh báo đa kênh (SSE Web Dashboard + DB ActivityLog/ReviewCase + Fallback Webhook)."""
        import os

        now = datetime.now(timezone.utc)
        with self._lock:
            if self._last_alert_at and (now - self._last_alert_at) < timedelta(minutes=10):
                return
            self._last_alert_at = now

        payload = {
            "status": state_code,
            "severity": "CRITICAL",
            "title": "CẢNH BÁO SỰ CỐ ZALO OA",
            "message": f"Hệ thống phát hiện Zalo OA gặp lỗi ({state_code}): {error_detail}",
            "detected_at": now.isoformat(),
        }
        sse_bus.publish("system.zalo_oa_alert", payload)
        logger.error("[ZALO_WATCHDOG] %s: %s", state_code, error_detail)

        if getattr(settings, "ZALO_PROXY_ONLY", False) or os.getenv("PYTEST_CURRENT_TEST"):
            return

        try:
            with SessionLocal() as db:
                db.add(
                    ActivityLog(
                        id=snowflake.generate(),
                        actor_id="zalo_watchdog",
                        action="ZALO_OA_HEALTH_ALERT",
                        entity_type="system",
                        entity_id=state_code,
                        details=payload,
                    )
                )
                latest_msg_id = db.scalar(
                    select(ZaloMessage.id).order_by(ZaloMessage.id.desc()).limit(1)
                )
                if latest_msg_id is not None:
                    existing_rc = db.scalar(
                        select(ReviewCase).where(
                            ReviewCase.case_type == "ZALO_OA_HEALTH_ALERT",
                            ReviewCase.status.in_([ReviewStatus.PENDING.value, "pending"]),
                        )
                    )
                    if existing_rc is None:
                        db.add(
                            ReviewCase(
                                id=snowflake.generate(),
                                message_id=latest_msg_id,
                                case_type="ZALO_OA_HEALTH_ALERT",
                                reason=payload["message"],
                                details={**payload, "priority": "HIGH"},
                                status=ReviewStatus.PENDING.value,
                            )
                        )
                    else:
                        existing_rc.reason = payload["message"]
                        existing_rc.details = {**(existing_rc.details or {}), **payload, "priority": "HIGH"}
                db.commit()
        except Exception as exc:
            logger.warning("[ZALO_WATCHDOG] Không thể ghi log/ca duyệt cảnh báo OA: %s", exc)

        fallback_url = (getattr(settings, "ZALO_FALLBACK_ALERT_WEBHOOK_URL", "") or "").strip()
        if fallback_url:
            try:
                req = urllib.request.Request(
                    fallback_url,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5).close()
            except Exception as exc:
                logger.warning("[ZALO_WATCHDOG] Lỗi bắn webhook dự phòng: %s", exc)

    def _emit_recovery(self) -> None:
        """Phát thông báo phục hồi trên SSE, tự đẩy lại tin bị kẹt và báo nhóm Zalo ĐHVT."""
        import os

        now = datetime.now(timezone.utc)
        sse_bus.publish(
            "system.zalo_oa_recovered",
            {"status": "HEALTHY", "recovered_at": now.isoformat(), "message": "Kết nối Zalo OA đã phục hồi."},
        )
        if getattr(settings, "ZALO_PROXY_ONLY", False) or os.getenv("PYTEST_CURRENT_TEST"):
            return
        try:
            with SessionLocal() as db:
                from contextlib import nullcontext
                from src.handlers.dhvt_service import DhvtNotificationService
                from src.infrastructure.outbox_worker import drain_outbox

                stuck_ids = list(
                    db.scalars(
                        select(OutboundMessage.id)
                        .where(OutboundMessage.status == OutboundStatus.PENDING_SEND.value)
                        .limit(50)
                    ).all()
                )
                if stuck_ids:
                    drain_outbox(lambda: nullcontext(db), stuck_ids)
                DhvtNotificationService.notify_system_alert(
                    db=db,
                    title="ZALO OA DA PHUC HOI KET NOI",
                    body=(
                        f"Kết nối Zalo OA đã hoạt động trở lại bình thường lúc {datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')}. "
                        f"Hệ thống đã tự động đẩy lại {len(stuck_ids)} tin nhắn chờ phát hành."
                    ),
                    entity_type="system",
                    entity_id="oa_recovered",
                    web_path="/reviews",
                    dedup_minutes=5,
                    is_test_msg=False,
                )
                db.commit()
        except Exception as exc:
            logger.warning("[ZALO_WATCHDOG] Lỗi xử lý phục hồi OA: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        """Trả trạng thái sức khỏe Zalo OA hiện tại cho API `/api/health/zalo-oa`."""
        with self._lock:
            return {
                "ok": self._status == "HEALTHY",
                "status": self._status,
                "consecutive_health_failures": self._consecutive_health_failures,
                "consecutive_send_failures": self._consecutive_send_failures,
                "last_error": self._last_error,
                "last_checked_at": self._last_checked_at.isoformat() if self._last_checked_at else None,
                "last_webhook_at": self._last_webhook_at.isoformat() if self._last_webhook_at else None,
                "oa_info": self._oa_info,
            }

    def _run_loop(self) -> None:
        """Vòng lặp nền: xả bộ đệm 60s mỗi 15s, kiểm tra sức khỏe Zalo OA mỗi 60s và chạy nhắc việc định kỳ."""
        tick = 0
        interval = max(15, int(getattr(settings, "ZALO_WATCHDOG_INTERVAL_SECONDS", 60) or 60))
        while not self._stop_event.wait(15):
            tick += 15
            # 1. Xả các bản nháp gom tin nhà xe đã hết hạn 60 giây
            try:
                from src.handlers.carrier_flow_service import CarrierFlowService

                with SessionLocal() as db:
                    CarrierFlowService.flush_expired_carrier_drafts(db)
            except Exception as exc:
                logger.debug("[ZALO_WATCHDOG] Lỗi xả draft 60s: %s", exc)

            # 2. Kiểm tra sức khỏe Zalo OA Bridge theo chu kỳ
            if tick % interval == 0:
                self.check_bridge_health()

            # 3. Chỉ chạy quét quá hạn định kỳ khi được bật chủ động (mặc định tắt để tránh xả tin cũ)
            if (
                tick % 300 == 0
                and getattr(settings, "ZALO_OVERDUE_ESCALATION_ENABLED", False)
                and not getattr(settings, "ZALO_PROXY_ONLY", False)
            ):
                try:
                    from src.handlers.dhvt_service import DhvtNotificationService

                    with SessionLocal() as db:
                        DhvtNotificationService.check_overdue_escalations(db, is_test_msg=False)
                except Exception as exc:
                    logger.debug("[ZALO_WATCHDOG] Lỗi quét quá hạn: %s", exc)

    def start(self) -> None:
        """Khởi động luồng giám sát nền khi ứng dụng FastAPI khởi chạy."""
        if not getattr(settings, "ZALO_WATCHDOG_ENABLED", True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="zalo-oa-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Dừng luồng giám sát nền an toàn khi tắt máy chủ."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


zalo_watchdog = ZaloOaWatchdog()
