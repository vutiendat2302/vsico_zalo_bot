"""Module Máy Chủ HTTP & Các Điểm Cuối REST API Chuẩn Toàn Cục (Standardized HTTP API Server).

Cài đặt máy chủ HTTP thuần (Python Standard Library `http.server`), tuân thủ nghiêm ngặt Phần 3:
1. Mỗi request có `request_id` (lấy từ header `X-Request-Id` hoặc sinh UUID ngẫu nhiên).
2. ContextVars tự động lưu `request_id` để mọi dòng nhật ký đều có metadata tương ứng.
3. MỌI endpoint chỉ trả về duy nhất một cấu trúc Envelope chuẩn:
   ```json
   {
     "ok": bool,
     "data": { ... } | null,
     "error": { "code": str, "message": str, "retryable": bool } | null,
     "request_id": str
   }
   ```
4. Quy tắc ánh xạ mã trạng thái HTTP:
   - Chữ ký sai: HTTP 401 (Mã E100).
   - Schema sai / JSON hỏng: HTTP 400 (Mã E101).
   - Lỗi nghiệp vụ miền: HTTP 422 (Mã E422 / E200 / E201).
   - Lỗi hệ thống nội bộ: HTTP 500 (Mã E999, retryable=true).
   - Tin bị bỏ qua (rác, nhóm lạ, trùng lặp): HTTP 200 kèm `data.action` tương ứng.
"""

import json
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional, Type
from ..infrastructure.queue.worker import QueueWorker
from ..infrastructure.repositories.trip_repo import TripRepository
from ..infrastructure.repositories.shipping_repo import ShippingRepository
from ..infrastructure.zalo.signature import verify_zalo_signature
from ..outbound.templates import TemplateEngine
from ..domain.models import Vehicle, SentTrip
from ..domain.rules import validate_iso6346, clean_plate, clean_phone, clean_container
from ..domain.matching.trip_assigner import TripAssigner
from ..domain.enums import MatchStatus
from ..domain.errors import (
    CarrierBotError,
    InvalidSignatureError,
    InvalidSchemaError,
    DomainError,
    TripNotFoundError,
)
from ..validation.validators import VehicleValidator
from ..config.settings import SETTINGS, TZ_VN
from ..observability.logging import (
    request_id_ctx,
    msg_id_ctx,
    seq_ctx,
    make_response_envelope,
    log_event,
)
from .webhook import WebhookController
from .health import HealthController

GLOBAL_REQUEST_SEQ = 0


def create_http_handler(
    webhook_controller: WebhookController,
    worker: QueueWorker,
    trip_repo: TripRepository,
    shipping_repo: Optional[ShippingRepository] = None,
    template_engine: Optional[TemplateEngine] = None,
) -> Type[BaseHTTPRequestHandler]:
    """Nhà máy khởi tạo lớp xử lý HTTP Request (Factory for BotHttpHandler).

    Args:
        webhook_controller (WebhookController): Bộ điều khiển tiếp nhận webhook Zalo.
        worker (QueueWorker): Tiến trình công nhân tiêu thụ hàng đợi tin nhắn.
        trip_repo (TripRepository): Kho lưu trữ thông tin chuyến xe đã gửi.
        shipping_repo (Optional[ShippingRepository], optional): Kho kế hoạch shipping.
        template_engine (Optional[TemplateEngine], optional): Động cơ render thông báo văn bản.

    Returns:
        Type[BaseHTTPRequestHandler]: Lớp con của `BaseHTTPRequestHandler`.
    """

    class BotHttpHandler(BaseHTTPRequestHandler):
        """Lớp xử lý HTTP Request chuẩn toàn cục đóng gói theo cấu trúc Response Envelope."""

        def _send_envelope(
            self,
            status: int,
            ok: bool,
            data: Optional[Dict[str, Any]] = None,
            error: Optional[Dict[str, Any]] = None,
        ) -> None:
            """Tuần tự hóa phản hồi theo cấu trúc Envelope chuẩn và gửi tới máy khách.

            Args:
                status (int): Mã trạng thái HTTP (200, 400, 401, 422, 500).
                ok (bool): Trạng thái thành công hay thất bại.
                data (Optional[Dict[str, Any]], optional): Dữ liệu trả về nếu thành công.
                error (Optional[Dict[str, Any]], optional): Chi tiết lỗi nếu thất bại.
            """
            req_id = request_id_ctx.get() or str(uuid.uuid4())
            envelope = make_response_envelope(ok=ok, data=data, error=error, request_id=req_id)
            body = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")

            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Request-Id", req_id)
            self.end_headers()
            self.wfile.write(body)

        def _init_request_context(self) -> str:
            """Khởi tạo mã Request ID từ HTTP header hoặc sinh UUID ngẫu nhiên."""
            req_id = (
                self.headers.get("X-Request-Id")
                or self.headers.get("X-Request-ID")
                or str(uuid.uuid4())
            )
            request_id_ctx.set(req_id)
            return req_id

        def do_OPTIONS(self) -> None:
            """Xử lý yêu cầu HTTP OPTIONS (CORS Preflight)."""
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-Id, X-Zalo-Signature")
            self.end_headers()

        def do_GET(self) -> None:
            """Xử lý toàn bộ các yêu cầu HTTP GET gửi đến hệ thống."""
            self._init_request_context()
            clean_path = self.path.split("?")[0].rstrip("/")

            try:
                # 1. Điểm cuối Health Check
                if clean_path in ("", "/health", "/api/health"):
                    health_data = HealthController.get_health(
                        total_processed=len(webhook_controller.normalizer.deduplicator._seen_msg_ids),
                        total_trips=len(trip_repo.list_all()),
                    )
                    self._send_envelope(200, ok=True, data=health_data)

                # 2. Điểm cuối xem toàn bộ danh sách chuyến xe
                elif clean_path in ("/trips", "/api/trips"):
                    trips = trip_repo.list_all()
                    trips_data = {
                        "total_trips": len(trips),
                        "trips": [
                            {
                                "carrier_id": t.carrier_id,
                                "cont": t.cont,
                                "shipping_id": t.shipping_id,
                                "version": t.version,
                                "sent_at": t.sent_at,
                                "xe_data": t.xe_data,
                            }
                            for t in trips
                        ],
                    }
                    self._send_envelope(200, ok=True, data=trips_data)

                # 3. Điểm cuối tra cứu chi tiết chuyến xe theo container
                elif clean_path.startswith("/api/trips/"):
                    cont = clean_path.replace("/api/trips/", "").strip().upper()
                    trips = [t for t in trip_repo.list_all() if t.cont == cont]
                    if trips:
                        t = trips[-1]
                        self._send_envelope(
                            200,
                            ok=True,
                            data={
                                "success": True,
                                "carrier_id": t.carrier_id,
                                "cont": t.cont,
                                "shipping_id": t.shipping_id,
                                "version": t.version,
                                "sent_at": t.sent_at,
                                "xe_data": t.xe_data,
                            },
                        )
                    else:
                        self._send_envelope(
                            422,
                            ok=False,
                            error={
                                "code": "E422",
                                "message": f"Không tìm thấy chuyến xe có container {cont}",
                                "retryable": False,
                            },
                        )

                # 4. Điểm cuối xem danh mục kế hoạch shipping
                elif clean_path in ("/shipping", "/api/shipping"):
                    if shipping_repo:
                        orders = list(shipping_repo.get_all().values())
                        shipping_data = {
                            "success": True,
                            "auto_mock_enabled": shipping_repo.is_auto_mock_enabled(),
                            "total_orders": len(orders),
                            "orders": [
                                {
                                    "shipping_id": o.shipping_id,
                                    "so_container": o.so_container,
                                    "nha_xe_id": o.nha_xe_id,
                                    "khach_hang_id": o.khach_hang_id,
                                    "ten_khach_hang": o.ten_khach_hang,
                                    "kho_tra": o.kho_tra,
                                    "dia_chi_kho_tra": o.dia_chi_kho_tra,
                                    "kich_thuoc_cont": o.kich_thuoc_cont,
                                    "trang_thai": o.trang_thai,
                                }
                                for o in orders
                            ],
                        }
                    else:
                        shipping_data = {"success": True, "auto_mock_enabled": False, "total_orders": 0, "orders": []}
                    self._send_envelope(200, ok=True, data=shipping_data)

                else:
                    self._send_envelope(
                        404,
                        ok=False,
                        error={"code": "E404", "message": f"Endpoint GET {clean_path} không tồn tại", "retryable": False},
                    )

            except CarrierBotError as cbe:
                self._send_envelope(
                    cbe.http_status,
                    ok=False,
                    error={"code": cbe.code, "message": cbe.message, "retryable": cbe.retryable},
                )
            except Exception as ex:
                self._send_envelope(
                    500,
                    ok=False,
                    error={"code": "E999", "message": f"Lỗi nội bộ: {str(ex)}", "retryable": True},
                )

        def do_POST(self) -> None:
            """Xử lý toàn bộ các yêu cầu HTTP POST gửi đến hệ thống."""
            global GLOBAL_REQUEST_SEQ
            req_id = self._init_request_context()
            clean_path = self.path.split("?")[0].rstrip("/")

            # 1. Đọc nội dung HTTP Body
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                self._send_envelope(
                    400,
                    ok=False,
                    error={"code": "E101", "message": "Request body trống", "retryable": False},
                )
                return

            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                self._send_envelope(
                    400,
                    ok=False,
                    error={"code": "E101", "message": f"Dữ liệu JSON không hợp lệ: {str(e)}", "retryable": False},
                )
                return

            if not isinstance(body, dict):
                self._send_envelope(
                    400,
                    ok=False,
                    error={"code": "E101", "message": "Payload JSON phải là một đối tượng (object)", "retryable": False},
                )
                return

            GLOBAL_REQUEST_SEQ += 1
            seq = GLOBAL_REQUEST_SEQ
            seq_ctx.set(seq)

            try:
                # =====================================================================
                # CỔNG ZALO WEBHOOK GATEWAY (POST /webhook)
                # =====================================================================
                if clean_path in ("/webhook", ""):
                    sig = self.headers.get("X-Zalo-Signature", "")
                    # Xác thực chữ ký nếu có header
                    if sig and not verify_zalo_signature(b"", sig, SETTINGS.zalo_secret_key):
                        self._send_envelope(
                            401,
                            ok=False,
                            error={"code": "E100", "message": "Chữ ký bảo mật không hợp lệ", "retryable": False},
                        )
                        return

                    status, ack = webhook_controller.handle_webhook_event(seq, body, sig)
                    if status != 200:
                        code = ack.get("code", f"E{status}")
                        msg = ack.get("message", ack.get("error", "Lỗi tiếp nhận webhook"))
                        self._send_envelope(status, ok=False, error={"code": code, "message": msg, "retryable": False})
                        return

                    # Worker tiêu thụ và xử lý tin nhắn
                    results = worker.process_all_queued()
                    if not results:
                        self._send_envelope(200, ok=True, data=ack)
                        return

                    first = results[0]
                    action = first.get("action")
                    reply_to_carrier = (
                        next((r.get("reply_to_carrier") for r in results if r.get("reply_to_carrier")), None)
                        if action == "PARSE"
                        else (first.get("reply_to_carrier") or None)
                    )
                    customer_notifications = [
                        {
                            "target_group_id": r.get("zalo_group_id_gui"),
                            "message_text": r.get("notification_text"),
                            "cont": r.get("cont"),
                            "shipping_id": r.get("shipping_id"),
                            "send_status": r.get("send_status"),
                        }
                        for r in results
                        if r.get("notification_text") and r.get("zalo_group_id_gui")
                    ]
                    needs_review = any(
                        r.get("status") in ("need_admin", "need_supplement") or r.get("admin_alert", False)
                        for r in results
                    )

                    resp_data = {
                        "success": True,
                        "seq": seq,
                        "msg_id": ack.get("msg_id"),
                        "quote_msg_id": body.get("quote_msg_id") or body.get("message", {}).get("quote_msg_id"),
                        "carrier_id": first.get("carrier_id"),
                        "action": action,
                        "needs_review": needs_review,
                        "reply_to_carrier": reply_to_carrier,
                        "customer_notifications": customer_notifications,
                        "reason": first.get("reason"),
                        "admin_alert": any(r.get("admin_alert", False) for r in results),
                        "admin_message": next((r.get("admin_message") for r in results if r.get("admin_message")), ""),
                        "total_vehicles": len(results) if action == "PARSE" else 0,
                        "vehicles": results if action == "PARSE" else [],
                        "operation_detail": {
                            "target_cont": first.get("cont"),
                            "reply_to_carrier": reply_to_carrier,
                            "reason": first.get("reason"),
                        }
                        if action != "PARSE"
                        else None,
                        "junk_verdict": first.get("junk_verdict"),
                        "junk_reason": first.get("junk_reason"),
                        "error_code": first.get("error_code", ""),
                    }
                    self._send_envelope(200, ok=True, data=resp_data)
                    return

                # =====================================================================
                # REST API TẠO CHUYẾN XE TRỰC TIẾP TỪ TMS (POST /api/trips/new)
                # =====================================================================
                elif clean_path in ("/api/trips/new", "/api/trips"):
                    carrier_id = body.get("carrier_id", "NX01").upper()
                    cont = str(body.get("cont", "")).strip().upper()
                    seal = str(body.get("seal", "")).strip()
                    bien_so = clean_plate(str(body.get("bien_so", "")).strip())
                    tai_xe = str(body.get("tai_xe", "")).strip()
                    sdt = clean_phone(str(body.get("sdt", "")).strip())
                    gio_den = str(body.get("gio_den", "")).strip()

                    veh = Vehicle(
                        cont=cont, seal=seal, bien_so=bien_so, tai_xe=tai_xe, sdt=sdt, gio_den=gio_den
                    )
                    veh = VehicleValidator.validate(veh, SETTINGS.required_fields)

                    shipping_order = None
                    if shipping_repo and cont:
                        if shipping_repo.is_auto_mock_enabled() and cont not in shipping_repo.get_all():
                            shipping_repo.create_mock_order(cont, carrier_id=carrier_id)
                        match_status, shipping_order = TripAssigner.match(veh, carrier_id, shipping_repo.get_all())
                        if match_status == MatchStatus.MATCH and shipping_order:
                            veh.in_shipping = True

                    xe_data = {
                        "cont": veh.cont,
                        "seal": veh.seal,
                        "bien_so": veh.bien_so,
                        "tai_xe": veh.tai_xe,
                        "sdt": veh.sdt,
                        "gio_den": veh.gio_den,
                    }
                    trip_record = SentTrip(
                        carrier_id=carrier_id,
                        cont=veh.cont,
                        shipping_id=shipping_order.shipping_id if shipping_order else None,
                        xe_data=xe_data,
                        notification_text="Thông báo điều xe từ TMS",
                        sent_at=datetime.now(TZ_VN).isoformat(),
                        version=1,
                    )
                    trip_repo.save_trip(trip_record)

                    self._send_envelope(
                        200,
                        ok=True,
                        data={
                            "success": True,
                            "action": "CREATE_TRIP",
                            "carrier_id": carrier_id,
                            "cont": cont,
                            "shipping_id": trip_record.shipping_id,
                            "version": 1,
                            "send_status": "SENT_DRY_RUN",
                            "warnings": veh.warnings,
                            "xe_data": xe_data,
                        },
                    )
                    return

                # =====================================================================
                # REST API CẬP NHẬT TÀI XẾ (POST /api/trips/update-driver)
                # =====================================================================
                elif clean_path == "/api/trips/update-driver":
                    carrier_id = body.get("carrier_id", "NX01").upper()
                    bien_so = clean_plate(str(body.get("bien_so", "")).strip())
                    cont = str(body.get("cont", "")).strip().upper()
                    tai_xe_moi = str(body.get("tai_xe_moi", "")).strip()
                    sdt_moi = clean_phone(str(body.get("sdt_moi", "")).strip())

                    target_trip = None
                    if cont:
                        target_trip = trip_repo.get_trip(carrier_id, cont)
                    elif bien_so:
                        trips = trip_repo.find_by_plate(carrier_id, bien_so)
                        if trips:
                            target_trip = trips[-1]

                    if not target_trip:
                        self._send_envelope(
                            422,
                            ok=False,
                            error={
                                "code": "E422",
                                "message": f"Không tìm thấy chuyến xe với cont={cont} hoặc bien_so={bien_so}",
                                "retryable": False,
                            },
                        )
                        return

                    new_xe_data = dict(target_trip.xe_data)
                    old_driver = new_xe_data.get("tai_xe")
                    old_phone = new_xe_data.get("sdt")
                    if tai_xe_moi:
                        new_xe_data["tai_xe"] = tai_xe_moi
                    if sdt_moi:
                        new_xe_data["sdt"] = sdt_moi

                    new_version = target_trip.version + 1
                    updated_trip = SentTrip(
                        carrier_id=carrier_id,
                        cont=target_trip.cont,
                        shipping_id=target_trip.shipping_id,
                        xe_data=new_xe_data,
                        notification_text=f"Cập nhật tài xế: {tai_xe_moi}",
                        sent_at=datetime.now(TZ_VN).isoformat(),
                        version=new_version,
                    )
                    trip_repo.save_trip(updated_trip)

                    self._send_envelope(
                        200,
                        ok=True,
                        data={
                            "success": True,
                            "action": "UPDATE_DRIVER",
                            "cont": target_trip.cont,
                            "version": new_version,
                            "old_driver": old_driver,
                            "new_driver": tai_xe_moi or old_driver,
                            "old_phone": old_phone,
                            "new_phone": sdt_moi or old_phone,
                            "send_status": "SENT_DRY_RUN_UPDATE",
                        },
                    )
                    return

                # =====================================================================
                # REST API BỔ SUNG SEAL / GIỜ ĐẾN (POST /api/trips/supplement)
                # =====================================================================
                elif clean_path == "/api/trips/supplement":
                    carrier_id = body.get("carrier_id", "NX01").upper()
                    cont = str(body.get("cont", "")).strip().upper()
                    seal = str(body.get("seal", "")).strip()
                    gio_den = str(body.get("gio_den", "")).strip()

                    self._send_envelope(
                        200,
                        ok=True,
                        data={
                            "success": True,
                            "action": "SUPPLEMENT",
                            "carrier_id": carrier_id,
                            "cont": cont,
                            "supplemented_fields": {"seal": seal, "gio_den": gio_den},
                            "status": "READY",
                        },
                    )
                    return

                # =====================================================================
                # REST API HỦY CHUYẾN XE (POST /api/trips/cancel)
                # =====================================================================
                elif clean_path == "/api/trips/cancel":
                    carrier_id = body.get("carrier_id", "NX01").upper()
                    cont = str(body.get("cont", "")).strip().upper()
                    ly_do = str(body.get("ly_do", "")).strip()

                    self._send_envelope(
                        200,
                        ok=True,
                        data={
                            "success": True,
                            "action": "CANCEL_REQUEST",
                            "carrier_id": carrier_id,
                            "cont": cont,
                            "reason": ly_do,
                            "admin_alert": True,
                            "admin_message": f"Chuyến cont {cont} ({carrier_id}) yêu cầu hủy: {ly_do}",
                        },
                    )
                    return

                # =====================================================================
                # REST API BẬT/TẮT AUTO-MOCK SHIPPING (POST /api/shipping/mock-mode)
                # =====================================================================
                elif clean_path == "/api/shipping/mock-mode":
                    if not shipping_repo:
                        self._send_envelope(
                            500,
                            ok=False,
                            error={"code": "E500", "message": "ShippingRepository chưa được cấu hình", "retryable": True},
                        )
                        return
                    enabled = bool(body.get("enabled", True))
                    shipping_repo.enable_auto_mock(enabled)
                    self._send_envelope(
                        200,
                        ok=True,
                        data={
                            "success": True,
                            "action": "TOGGLE_AUTO_MOCK_SHIPPING",
                            "auto_mock_enabled": shipping_repo.is_auto_mock_enabled(),
                            "message": (
                                "Đã BẬT tự động tạo shipping giả lập cho container mới"
                                if enabled
                                else "Đã TẮT tự động tạo shipping giả lập"
                            ),
                        },
                    )
                    return

                # =====================================================================
                # REST API TẠO ĐƠN SHIPPING MỚI (POST /api/shipping/new)
                # =====================================================================
                elif clean_path in ("/api/shipping/new", "/api/shipping"):
                    if not shipping_repo:
                        self._send_envelope(
                            500,
                            ok=False,
                            error={"code": "E500", "message": "ShippingRepository chưa được cấu hình", "retryable": True},
                        )
                        return

                    carrier_id = body.get("carrier_id", "NX01").upper()
                    cont = clean_container(str(body.get("cont", "")).strip().upper())
                    if not cont:
                        self._send_envelope(
                            422,
                            ok=False,
                            error={"code": "E422", "message": "Thiếu trường 'cont' hợp lệ", "retryable": False},
                        )
                        return

                    order = shipping_repo.create_mock_order(
                        cont=cont,
                        carrier_id=carrier_id,
                        khach_hang_id=str(body.get("khach_hang_id", "KH_POSTMAN")).strip(),
                        ten_khach_hang=str(body.get("ten_khach_hang", "Khách hàng tạo từ Postman (MOCK)")).strip(),
                        kho_tra=str(body.get("kho_tra", "Kho Chỉ Định TMS")).strip(),
                        dia_chi_kho_tra=str(body.get("dia_chi_kho_tra", "Địa chỉ Kho Chỉ Định")).strip(),
                        kich_thuoc_cont=str(body.get("kich_thuoc_cont", "40DC")).strip(),
                        zalo_group_id_khach=str(body.get("zalo_group_id_khach", "3001000000000000001")).strip(),
                    )
                    self._send_envelope(
                        200,
                        ok=True,
                        data={
                            "success": True,
                            "action": "CREATE_SHIPPING_ORDER",
                            "shipping_id": order.shipping_id,
                            "cont": order.so_container,
                            "carrier_id": order.nha_xe_id,
                            "khach_hang_id": order.khach_hang_id,
                            "ten_khach_hang": order.ten_khach_hang,
                            "kho_tra": order.kho_tra,
                            "dia_chi_kho_tra": order.dia_chi_kho_tra,
                        },
                    )
                    return

                # =====================================================================
                # REST API CHẠY LẠI TẬP TIN NHẮN (POST /api/replay)
                # =====================================================================
                elif clean_path == "/api/replay":
                    messages = body.get("messages", [])
                    replayed = 0
                    vehicles = 0
                    actions = {}

                    for m_idx, m_payload in enumerate(messages, start=1):
                        status, ack = webhook_controller.handle_webhook_event(m_idx, m_payload)
                        res = worker.process_all_queued()
                        replayed += 1
                        for r in res:
                            act = r.get("action", "UNKNOWN")
                            actions[act] = actions.get(act, 0) + 1
                            if act == "PARSE":
                                vehicles += 1

                    self._send_envelope(
                        200,
                        ok=True,
                        data={
                            "action": "REPLAY_SUMMARY",
                            "total_replayed": replayed,
                            "total_vehicles": vehicles,
                            "actions_count": actions,
                        },
                    )
                    return

                else:
                    self._send_envelope(
                        404,
                        ok=False,
                        error={"code": "E404", "message": f"Endpoint POST {clean_path} không tồn tại", "retryable": False},
                    )

            except CarrierBotError as cbe:
                self._send_envelope(
                    cbe.http_status,
                    ok=False,
                    error={"code": cbe.code, "message": cbe.message, "retryable": cbe.retryable},
                )
            except Exception as ex:
                self._send_envelope(
                    500,
                    ok=False,
                    error={"code": "E999", "message": f"Lỗi hệ thống nội bộ: {str(ex)}", "retryable": True},
                )

    return BotHttpHandler
