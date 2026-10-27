"""Module Xử Lý Tạo Chuyến Xe Mới (Create Trip Use Case Handler).

Thực hiện toàn bộ quy trình nghiệp vụ khi tiếp nhận tin nhắn báo xe mới từ nhà xe:
1. Phân đoạn tin nhắn thành các khối xe độc lập (`split_vehicle_blocks`).
2. Bóc tách thông tin chi tiết từng xe (`TripParser.parse_vehicle`).
3. Thẩm định tính hợp lệ của dữ liệu (`VehicleValidator.validate`).
4. Đối soát container với kế hoạch Shipping của VSICO (`TripAssigner.match`).
5. Kết xuất hành động Outbound (soạn tin khách, nhắc bổ sung, cảnh báo Admin).
6. Lưu trữ thông tin chuyến xe vào cơ sở dữ liệu/kho lưu trữ `TripRepository`.
"""

from typing import List, Dict, Any
from ..ingestion.models import InboundMessage
from ..domain.models import Vehicle
from ..domain.matching.trip_assigner import TripAssigner
from ..domain.enums import MatchStatus
from ..messaging.segmenter import split_vehicle_blocks
from ..parsing.trip_parser import TripParser
from ..validation.validators import VehicleValidator
from ..outbound.responder import OutboundResponder
from ..infrastructure.repositories.shipping_repo import ShippingRepository
from ..infrastructure.repositories.trip_repo import TripRepository
from .base import BaseHandler


class CreateTripHandler(BaseHandler):
    """Use Case Handler chịu trách nhiệm tạo mới các chuyến xe từ tin nhắn nhà xe."""

    def __init__(
        self,
        shipping_repo: ShippingRepository,
        trip_repo: TripRepository,
        responder: OutboundResponder,
        required_fields: List[str],
    ):
        """Khởi tạo Handler tạo chuyến xe mới.

        Args:
            shipping_repo (ShippingRepository): Kho lưu trữ kế hoạch vận chuyển (Shipping Plan).
            trip_repo (TripRepository): Kho lưu trữ trạng thái các chuyến xe đã duyệt.
            responder (OutboundResponder): Bộ xử lý quyết định hành động gửi tin và render template.
            required_fields (List[str]): Danh sách các trường dữ liệu bắt buộc của chuyến xe.
        """
        self.shipping_repo = shipping_repo
        self.trip_repo = trip_repo
        self.responder = responder
        self.required_fields = required_fields

    def handle(self, inbound: InboundMessage, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi chu trình xử lý bóc tách và tạo chuyến xe cho tin nhắn báo xe.

        Args:
            inbound (InboundMessage): Thông điệp nội bộ nhận từ Queue Worker.
            context (Dict[str, Any]): Ngữ cảnh bổ sung của thông điệp.

        Returns:
            List[Dict[str, Any]]: Danh sách các bản ghi kết quả xử lý của từng xe.
        """
        # 1. Tách tin nhắn thành các khối xe độc lập (nếu có nhiều xe trong 1 tin)
        blocks = split_vehicle_blocks(inbound.raw_text)
        results = []
        carrier_id = inbound.carrier_id or "UNKNOWN"

        for idx, blk in enumerate(blocks, start=1):
            # 2. Bóc tách các trường thông tin của xe
            vehicle = TripParser.parse_vehicle(
                blk, inbound.raw_text, inbound.received_at, xe_index=idx
            )

            # 3. Thẩm định tính hợp lệ của dữ liệu xe
            vehicle = VehicleValidator.validate(vehicle, self.required_fields)

            # 4. Đối soát container với kế hoạch vận chuyển (Shipping Plan)
            shipping_order = None
            if vehicle.cont:
                if self.shipping_repo.is_auto_mock_enabled() and vehicle.cont not in self.shipping_repo.get_all():
                    self.shipping_repo.create_mock_order(vehicle.cont, carrier_id=carrier_id)
                match_status, shipping_order = TripAssigner.match(
                    vehicle, carrier_id, self.shipping_repo.get_all()
                )
                if match_status == MatchStatus.WRONG_CARRIER:
                    vehicle.warnings.append("sai_nha_xe")
                    vehicle.status = "need_admin"
                    vehicle.admin_alert = True
                elif match_status == MatchStatus.MATCH:
                    vehicle.in_shipping = True

            # 5. Lấy thông tin chuyến xe cũ đã gửi trước đó (nếu có) để phát hiện gửi lặp
            prev_trip = (
                self.trip_repo.get_trip(carrier_id, vehicle.cont) if vehicle.cont else None
            )

            # 6. Quyết định nội dung và hành động phản hồi Outbound
            vehicle = self.responder.resolve_response(
                vehicle, shipping_order, prev_trip, carrier_id
            )

            # 7. Lưu trữ chuyến xe vào cơ sở dữ liệu nếu đủ điều kiện gửi thành công
            if vehicle.send_status == "SENT_DRY_RUN" and vehicle.cont:
                xe_dict = {
                    "cont": vehicle.cont,
                    "seal": vehicle.seal,
                    "bien_so": vehicle.bien_so,
                    "tai_xe": vehicle.tai_xe,
                    "sdt": vehicle.sdt,
                    "gio_den": vehicle.gio_den,
                }
                self.trip_repo.record_trip(
                    carrier_id,
                    vehicle.cont,
                    vehicle.shipping_id,
                    xe_dict,
                    vehicle.notification_text,
                    inbound.received_at.isoformat(),
                )

            # 8. Đóng gói bản ghi kết quả chi tiết
            row_res = {
                "seq": inbound.seq,
                "msg_id": inbound.msg_id,
                "received_at": inbound.received_at.isoformat(),
                "group_id": inbound.group_id,
                "sender_id": inbound.sender_id,
                "carrier_id": carrier_id,
                "action": "PARSE",
                "xe_index": vehicle.xe_index,
                "loai_hint": vehicle.loai_hint,
                "cont": vehicle.cont,
                "seal": vehicle.seal,
                "bien_so": vehicle.bien_so,
                "tai_xe": vehicle.tai_xe,
                "sdt": vehicle.sdt,
                "gio_den": vehicle.gio_den,
                "warnings": vehicle.warnings,
                "status": vehicle.status,
                "in_shipping": vehicle.in_shipping,
                "shipping_id": vehicle.shipping_id,
                "khach_hang_id": vehicle.khach_hang_id,
                "ten_khach_hang": vehicle.ten_khach_hang,
                "kho_tra": vehicle.kho_tra,
                "zalo_group_id_gui": vehicle.zalo_group_id_gui,
                "send_status": vehicle.send_status,
                "notification_text": vehicle.notification_text,
                "reply_to_carrier": vehicle.reply_to_carrier,
                "admin_alert": vehicle.admin_alert,
                "admin_message": vehicle.admin_message,
                "reason": "Bóc tách thông tin xe thành công",
                "parser_source": vehicle.parser_source,
            }
            results.append(row_res)

        return results
