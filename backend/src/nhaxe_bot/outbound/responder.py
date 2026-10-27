from typing import Dict, Any, Optional
from ..domain.models import Vehicle, ShippingOrder, SentTrip
from .templates import TemplateEngine

class OutboundResponder:
    """Bộ giải quyết và định tuyến thông báo đi (Outbound Notification Responder).

    Lớp này chịu trách nhiệm:
    1. Kiểm tra trạng thái điều xe của phương tiện (đóng/trả, đủ thông tin hay thiếu).
    2. Xác thực tính nhất quán giữa dữ liệu nhà xe gửi và kế hoạch vận chuyển (shipping order).
    3. Phát hiện lỗi an ninh / phân công sai nhà xe để kích hoạt cảnh báo quản trị (admin alert).
    4. Kiểm tra sự trùng lặp với thông tin chuyến xe đã gửi trước đó để tránh spam khách hàng.
    5. Soạn thảo nội dung thông báo gửi cho khách hàng bằng TemplateEngine theo chuẩn mẫu quy định.
    """

    def __init__(self, template_engine: TemplateEngine) -> None:
        """Khởi tạo OutboundResponder với template engine kết xuất thông báo.

        Args:
            template_engine (TemplateEngine): Động cơ nạp và render các mẫu thông báo văn bản.
        """
        self.templates = template_engine

    def resolve_response(
        self,
        vehicle: Vehicle,
        shipping: Optional[ShippingOrder],
        previous_trip: Optional[SentTrip],
        carrier_id: str
    ) -> Vehicle:
        """Xác định nội dung thông báo, người nhận và trạng thái xuất bản cho một phương tiện.

        Quy trình xử lý nghiệp vụ 6 bước:
        - Bước 1: Kiểm tra loại điều xe (nếu là 'dong' hàng -> hoãn xử lý Phase 2).
        - Bước 2: Kiểm tra dữ liệu bắt buộc (nếu thiếu -> tạo phản hồi yêu cầu nhà xe bổ sung).
        - Bước 3: Kiểm tra an ninh (sai nhà xe hoặc cont không có trong kế hoạch shipping -> chuyển admin xử lý).
        - Bước 4: Hợp nhất dữ liệu kho trả, khách hàng từ kế hoạch shipping vào đối tượng phương tiện.
        - Bước 5: Kiểm tra tính lặp thông tin (nếu dữ liệu tài xế/biển số/seal/giờ giống hệt chuyến cũ -> bỏ qua).
        - Bước 6: Soạn mẫu tin thông báo gửi khách hàng và đánh dấu sẵn sàng gửi (SENT_DRY_RUN).

        Args:
            vehicle (Vehicle): Đối tượng thông tin phương tiện đã được bóc tách và xác thực.
            shipping (Optional[ShippingOrder]): Thông tin đơn hàng vận chuyển tương ứng từ file shipping (nếu có).
            previous_trip (Optional[SentTrip]): Bản ghi chuyến xe đã gửi trước đó cho cont này (nếu có).
            carrier_id (str): Mã định danh nhà xe gửi tin (ví dụ: 'NX01', 'NX02').

        Returns:
            Vehicle: Đối tượng Vehicle đã được cập nhật đầy đủ trạng thái `send_status`,
                `notification_text`, `reply_to_carrier`, hoặc `admin_alert`.
        """
        warnings = vehicle.warnings

        # 1. Nếu là lệnh đóng hàng -> Hoãn xử lý sang Giai đoạn 2 (Phase 2)
        if vehicle.loai_hint == "dong":
            vehicle.send_status = "DEFER_PHASE2_DONG"
            return vehicle

        # 2. Thiếu thông tin bắt buộc -> Yêu cầu nhà xe bổ sung
        if vehicle.status == "need_supplement":
            vehicle.send_status = "HOLD_WAIT_SUPPLEMENT"
            thieu = []
            if "thieu_seal" in warnings:
                thieu.append("số seal/chì")
            if "thieu_gio_den" in warnings:
                thieu.append("giờ đến")
            if "thieu_cont" in warnings:
                thieu.append("số cont")
            if "thieu_bien_so" in warnings:
                thieu.append("biển số xe")
            thieu_str = ", ".join(thieu) if thieu else "thông tin bắt buộc"
            vehicle.reply_to_carrier = f"Chuyến cont {vehicle.cont or 'chưa rõ'} còn thiếu: {thieu_str}. Vui lòng bổ sung!"
            return vehicle

        # 3. Lỗi an ninh: sai nhà xe hoặc không có shipping -> Chuyển điều phối viên kiểm tra
        if "sai_nha_xe" in warnings:
            vehicle.send_status = "HOLD_ADMIN"
            vehicle.status = "need_admin"
            vehicle.admin_alert = True
            vehicle.admin_message = f"Cảnh báo: Cont {vehicle.cont} được phân công cho {shipping.nha_xe_id if shipping else 'khác'} nhưng {carrier_id} lại gửi xe"
            return vehicle

        if not shipping:
            vehicle.send_status = "HOLD_ADMIN"
            vehicle.status = "need_admin"
            vehicle.admin_alert = True
            vehicle.admin_message = f"Cont {vehicle.cont} không tồn tại trong kế hoạch vận chuyển shipping"
            return vehicle

        # 4. Gắn thông tin shipping hợp lệ vào vehicle
        vehicle.in_shipping = True
        vehicle.shipping_id = shipping.shipping_id
        vehicle.khach_hang_id = shipping.khach_hang_id
        vehicle.ten_khach_hang = shipping.ten_khach_hang
        vehicle.kho_tra = shipping.kho_tra
        vehicle.dia_chi_kho_tra = shipping.dia_chi_kho_tra
        vehicle.zalo_group_id_gui = shipping.zalo_group_id_khach

        # 5. Kiểm tra lặp thông tin so với bản ghi trước đó
        if previous_trip:
            old_data = previous_trip.xe_data
            if (old_data.get("bien_so") == vehicle.bien_so and
                old_data.get("tai_xe") == vehicle.tai_xe and
                old_data.get("sdt") == vehicle.sdt and
                old_data.get("seal") == vehicle.seal and
                old_data.get("gio_den") == vehicle.gio_den):
                vehicle.send_status = "SKIPPED_NO_CHANGE"
                return vehicle

        # 6. Soạn nội dung gửi khách hàng thông qua TemplateEngine
        context = {
            "cont": vehicle.cont,
            "seal": vehicle.seal,
            "bien_so": vehicle.bien_so,
            "tai_xe": vehicle.tai_xe,
            "sdt": vehicle.sdt,
            "gio_den": vehicle.gio_den,
            "kho_tra": shipping.kho_tra,
            "dia_chi_kho_tra": shipping.dia_chi_kho_tra,
            "kich_thuoc_cont": shipping.kich_thuoc_cont or "40DC"
        }
        vehicle.notification_text = self.templates.render_notification("tra", context, shipping.khach_hang_id)
        vehicle.send_status = "SENT_DRY_RUN"
        return vehicle
