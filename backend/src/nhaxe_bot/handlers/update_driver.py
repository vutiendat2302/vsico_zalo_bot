"""Module Xử Lý Đổi Tài Xế & Cập Nhật Xe (Update Driver Use Case Handler).

Chịu trách nhiệm xử lý các yêu cầu thay đổi tài xế, đổi xe hoặc sửa seal từ nhà xe:
1. Xác định container mục tiêu: trực tiếp từ tin nhắn hoặc tra cứu ngược qua biển số xe.
2. Tìm bản ghi chuyến xe phiên bản hiện tại trong `TripRepository`.
3. Bóc tách các trường mới (tài xế mới, SĐT mới, biển số mới).
4. So sánh với bản cũ để phát hiện sự thay đổi.
5. Render thông báo cập nhật qua template `default_capnhat.txt`.
6. Lưu trữ bản ghi chuyến xe mới với số phiên bản tăng lên (Version 2, 3).
"""

import re
from typing import List, Dict, Any, Optional
from ..ingestion.models import InboundMessage
from ..domain.rules import clean_plate, clean_phone, clean_driver_name
from ..parsing.fields.container import extract_containers
from ..parsing.fields.plate import extract_plate
from ..parsing.fields.phone import extract_phone
from ..infrastructure.repositories.trip_repo import TripRepository
from ..outbound.templates import TemplateEngine
from .base import BaseHandler


class UpdateDriverHandler(BaseHandler):
    """Use Case Handler xử lý yêu cầu đổi xe hoặc đổi tài xế từ nhà xe."""

    def __init__(self, trip_repo: TripRepository, template_engine: TemplateEngine):
        """Khởi tạo Handler cập nhật thông tin xe/tài xế.

        Args:
            trip_repo (TripRepository): Kho lưu trữ trạng thái chuyến xe (hỗ trợ tra ngược biển số).
            template_engine (TemplateEngine): Công cụ render mẫu thông báo cập nhật gửi khách.
        """
        self.trip_repo = trip_repo
        self.templates = template_engine

    def handle(self, inbound: InboundMessage, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi nghiệp vụ cập nhật tài xế cho chuyến xe đã gửi.

        Quy trình xử lý:
        1. Tìm kiếm số container trong tin nhắn:
           - Nếu có: Dùng trực tiếp số container đó.
           - Nếu không có: Trích xuất biển số xe và gọi `trip_repo.find_by_plate()` để tra cứu ngược container.
        2. Nếu tìm thấy chuyến cũ:
           - Trích xuất tài xế mới, SĐT mới, biển số mới.
           - So sánh và lập danh sách các trường thay đổi (changes).
           - Render thông báo cập nhật gửi khách qua template `capnhat`.
           - Ghi bản ghi mới vào `trip_repo` (phiên bản tự động tăng lên 1).
        3. Đóng gói kết quả với hành động `UPDATE_REQUEST`.

        Args:
            inbound (InboundMessage): Thông điệp nhận từ Queue Worker.
            context (Dict[str, Any]): Dữ liệu ngữ cảnh bổ sung.

        Returns:
            List[Dict[str, Any]]: Bản ghi kết quả cập nhật chuyến xe.
        """
        raw_text = inbound.raw_text
        carrier_id = inbound.carrier_id or "UNKNOWN"
        conts = extract_containers(raw_text)
        plate_in_msg = extract_plate(raw_text)
        target_cont: Optional[str] = None

        # 1. Xác định số container mục tiêu
        if conts:
            target_cont = conts[0]
        elif plate_in_msg:
            # Tra cứu ngược theo biển số xe nếu nhà xe không nhắc tới số cont
            trips = self.trip_repo.find_by_plate(carrier_id, plate_in_msg)
            if trips:
                target_cont = trips[-1].cont

        row: Dict[str, Any] = {
            "seq": inbound.seq,
            "msg_id": inbound.msg_id,
            "received_at": inbound.received_at.isoformat(),
            "group_id": inbound.group_id,
            "sender_id": inbound.sender_id,
            "carrier_id": carrier_id,
            "action": "UPDATE_REQUEST",
            "xe_index": None,
            "loai_hint": None,
            "cont": target_cont,
            "seal": None,
            "bien_so": plate_in_msg,
            "tai_xe": None,
            "sdt": None,
            "gio_den": None,
            "warnings": [],
            "status": None,
            "in_shipping": None,
            "shipping_id": None,
            "khach_hang_id": None,
            "ten_khach_hang": None,
            "zalo_group_id_gui": None,
            "send_status": None,
            "notification_text": None,
            "reply_to_carrier": None,
            "admin_alert": False,
            "admin_message": None,
            "reason": None,
        }

        # 2. Xử lý cập nhật nếu tìm thấy container mục tiêu
        if target_cont:
            old_trip = self.trip_repo.get_trip(carrier_id, target_cont)
            if old_trip:
                old_data = old_trip.xe_data
                row["shipping_id"] = old_trip.shipping_id

                # Bóc tách các thông tin mới
                new_phone = extract_phone(raw_text)
                new_plate = extract_plate(raw_text)

                m_name = re.search(
                    r'sang\s+([A-Za-zÀ-ỹ\s]{3,30}?)(?=(?:\s+0\d|\s*\+84|\n|$))', raw_text, re.I
                )
                new_driver = clean_driver_name(m_name.group(1).strip()) if m_name else None

                updated_xe = dict(old_data)
                changes = []
                if new_driver and new_driver != old_data.get("tai_xe"):
                    changes.append(f"- Tài xế: {old_data.get('tai_xe')} -> {new_driver}")
                    updated_xe["tai_xe"] = new_driver
                if new_phone and new_phone != old_data.get("sdt"):
                    changes.append(f"- SĐT: {old_data.get('sdt')} -> {new_phone}")
                    updated_xe["sdt"] = new_phone
                if new_plate and new_plate != old_data.get("bien_so"):
                    changes.append(f"- Biển số xe: {old_data.get('bien_so')} -> {new_plate}")
                    updated_xe["bien_so"] = new_plate

                # Render template cập nhật thông báo cho khách hàng
                tpl_context = dict(updated_xe)
                tpl_context["thay_doi"] = (
                    "\n".join(changes) if changes else "- Cập nhật thông tin xe"
                )
                rendered_msg = self.templates.render_notification("capnhat", tpl_context)

                # Lưu vào repository phiên bản mới (Version tự tăng)
                self.trip_repo.record_trip(
                    carrier_id,
                    target_cont,
                    old_trip.shipping_id,
                    updated_xe,
                    rendered_msg,
                    inbound.received_at.isoformat(),
                )

                row["send_status"] = "SENT_DRY_RUN"
                row["notification_text"] = rendered_msg
                row["reason"] = f"Đã gộp thông tin thay đổi vào chuyến cont {target_cont}"
            else:
                row["reason"] = f"Yêu cầu sửa thông tin cho cont {target_cont}"
        else:
            row["reason"] = "Yêu cầu sửa thông tin chuyến đã gửi"

        return [row]
