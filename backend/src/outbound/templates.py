"""Module Tạo Nội Dung Phản Hồi & Thông Báo Theo Mẫu (Outbound Template Engine).

Tuân thủ nghiêm ngặt nguyên tắc Template Isolation (Mục 1.6 - AGENTS.md):
- Tuyệt đối không hardcode chuỗi thông báo tiếng Việt gửi khách hàng trong mã nguồn xử lý.
- Mọi nội dung gửi đi được nạp và render thông qua `TemplateEngine` từ thư mục `outbound/templates/`.
- Hỗ trợ ghi đè mẫu tin theo từng mã khách hàng cụ thể (`templates/customers/<khach_hang_id>_<loai>.txt`).
- Hiển thị đầy đủ SĐT tài xế trong thông báo kết quả gửi đi (không che/ẩn thành `***` hoặc `xxxx`).
- Kiểm tra tính đầy đủ của 8 trường thông tin cốt lõi trước khi gửi:
  (1) Khách hàng, (2) Lệnh, (3) Xe, (4) Tài xế, (5) SĐT, (6) Cont, (7) Size, (8) Chì.
  Giờ dự kiến và Ghi chú là tùy chọn (có thể null).
"""

import os
import re
from datetime import date, datetime
from typing import Any, Optional

from src.domain.models import ExtractedContainerLine
from src.domain.rules import clean_plate, compute_iso6346_check_digit, is_valid_phone_list


def format_license_plate_display(clean_plate: Optional[str]) -> str:
    """Định dạng chuỗi biển số xe viết liền thành dạng có dấu gạch và chấm thẩm mỹ.

    Ví dụ: '15C17066' -> '15C-170.66', '29H1234' -> '29H-1234'.
    """
    if not clean_plate:
        return ""
    p = clean_plate.upper().replace("-", "").replace(".", "").strip()
    m5 = re.match(r"^(\d{2}[A-Z]{1,2})(\d{3})(\d{2})$", p)
    if m5:
        return f"{m5.group(1)}-{m5.group(2)}.{m5.group(3)}"
    m4 = re.match(r"^(\d{2}[A-Z]{1,2})(\d{4})$", p)
    if m4:
        return f"{m4.group(1)}-{m4.group(2)}"
    return clean_plate


def format_masked_phone(phone: Optional[str]) -> str:
    """Giữ nguyên đầy đủ SĐT tài xế khi hiển thị trên kết quả gửi (không ẩn/che số)."""
    if not phone:
        return ""
    return str(phone).strip()


def format_plan_date_display(plan_date_val: Any) -> str:
    """Định dạng ngày kế hoạch vận chuyển sang chuẩn DD/MM/YYYY."""
    if not plan_date_val:
        return ""
    if isinstance(plan_date_val, datetime):
        return plan_date_val.strftime("%d/%m/%Y")
    if isinstance(plan_date_val, date):
        return plan_date_val.strftime("%d/%m/%Y")
    s = str(plan_date_val).strip()
    if not s:
        return ""
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", s):
        return s
    try:
        return date.fromisoformat(s[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return s


def format_arrival_time_display(eta_val: Any) -> str:
    """Định dạng chuỗi giờ đến dự kiến thân thiện."""
    if not eta_val:
        return "Chưa có"
    if isinstance(eta_val, datetime):
        return eta_val.strftime("%H:%M, %d/%m/%Y")
    s = str(eta_val).strip()
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%H:%M, %d/%m/%Y")
    except Exception:
        return s if s else "Chưa có"


class TemplateEngine:
    """Động cơ nạp và render mẫu tin nhắn gửi khách hàng từ tệp văn bản."""

    def __init__(self, templates_dir: Optional[str] = None):
        if templates_dir is None:
            templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
        self.templates_dir = templates_dir

    @staticmethod
    def _normalize_template_kind(loai: Optional[str]) -> str:
        """Chuẩn hóa mã loại lệnh (LOAD/RETURN/dong/tra/capnhat/huy) sang tên file template."""
        val = (loai or "").strip().lower()
        if val in ("load", "dong", "xuat"):
            return "dong"
        if val in ("capnhat", "update", "update_request"):
            return "capnhat"
        if val in ("huy", "cancel", "cancel_request"):
            return "huy"
        if val in ("return", "tra", "nhap"):
            return "tra"
        return ""

    def get_template(self, loai: str, customer_id: Optional[str] = None) -> str:
        """Nạp tệp mẫu tương ứng.

        Thứ tự ưu tiên:
        1. Mẫu riêng của khách hàng: `templates/customers/<customer_id>_<loai>.txt`
        2. Mẫu mặc định chung: `templates/default_<loai>.txt`
        3. Fallback nội bộ nếu thiếu tệp trên đĩa.
        """
        loai_clean = self._normalize_template_kind(loai) or "tra"

        if customer_id:
            safe_cid = str(customer_id).strip().replace("/", "_").replace("\\", "_")
            cust_path = os.path.join(self.templates_dir, "customers", f"{safe_cid}_{loai_clean}.txt")
            if os.path.exists(cust_path):
                try:
                    with open(cust_path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass

        default_path = os.path.join(self.templates_dir, f"default_{loai_clean}.txt")
        if os.path.exists(default_path):
            try:
                with open(default_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass

        # Fallback nội bộ nếu thiếu file trên đĩa
        if loai_clean == "tra":
            return (
                "VSICO - THÔNG BÁO XE TRẢ HÀNG\n"
                "Khách hàng: {ten_khach_hang}{dong_ke_hoach_ngay}\n\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}{dong_mooc}\n"
                "- Lái xe: {tai_xe} - SĐT: {sdt}\n"
                "- Điểm trả: {diem_tra}\n"
                "- Giờ đến dự kiến: {gio_den}{dong_ghi_chu}\n"
            )
        elif loai_clean == "capnhat":
            return (
                "VSICO - THÔNG BÁO CẬP NHẬT THÔNG TIN XE\n"
                "Khách hàng: {ten_khach_hang}{dong_ke_hoach_ngay}\n\n"
                "Cập nhật thông tin xe cho cont {so_cont}:\n"
                "Các thông tin thay đổi:\n{thay_doi}\n\n"
                "Thông tin xe hiện tại:\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}{dong_mooc}\n"
                "- Lái xe: {tai_xe} - SĐT: {sdt}\n"
                "- Điểm đến: {diem_den}\n"
                "- Giờ đến dự kiến: {gio_den}{dong_ghi_chu}\n"
            )
        elif loai_clean == "huy":
            return (
                "VSICO - THÔNG BÁO HỦY CHUYẾN\n"
                "Khách hàng: {ten_khach_hang}{dong_ke_hoach_ngay}\n\n"
                "Chuyến xe đã được xác nhận hủy:\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Biển số xe: {bien_so}{dong_mooc}\n"
                "- Điểm đến: {diem_den}\n"
                "- Lý do: {ly_do}{dong_ghi_chu}\n"
            )
        else:
            return (
                "VSICO - THÔNG BÁO XE ĐÓNG HÀNG\n"
                "Khách hàng: {ten_khach_hang}{dong_ke_hoach_ngay}\n\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}{dong_mooc}\n"
                "- Lái xe: {tai_xe} - SĐT: {sdt}\n"
                "- Điểm đóng: {diem_dong}\n"
                "- Giờ đến dự kiến: {gio_den}{dong_ghi_chu}\n"
            )

    def render_notification(
        self,
        loai: str,
        context: dict[str, Any],
        customer_id: Optional[str] = None,
    ) -> str:
        """Điền dữ liệu thực tế vào mẫu thông báo."""
        tpl = self.get_template(loai, customer_id)
        bien_so_fmt = format_license_plate_display(context.get("bien_so") or context.get("truck_plate"))
        mooc_fmt = format_license_plate_display(context.get("ro_mooc") or context.get("mooc") or context.get("trailer_plate"))
        dong_mooc = f"\n- Biển số rơ-moóc: {mooc_fmt}" if mooc_fmt else ""
        sdt_fmt = str(context.get("sdt") or context.get("driver_phone") or "").strip()
        gio_den_fmt = format_arrival_time_display(context.get("gio_den") or context.get("eta"))
        ke_hoach_ngay_fmt = format_plan_date_display(context.get("ke_hoach_ngay") or context.get("plan_date"))
        dong_ke_hoach_ngay = f"\nKế hoạch ngày: {ke_hoach_ngay_fmt}" if ke_hoach_ngay_fmt else ""

        note = context.get("ghi_chu") or context.get("note")
        dong_ghi_chu = f"\n- Ghi chú: {note}" if note else ""

        mapping = {
            "ten_khach_hang": context.get("ten_khach_hang") or context.get("customer_name") or "Quý khách hàng",
            "ke_hoach_ngay": ke_hoach_ngay_fmt,
            "dong_ke_hoach_ngay": dong_ke_hoach_ngay,
            "so_cont": context.get("so_cont") or context.get("container_no") or "",
            "so_chi": context.get("so_chi") or context.get("seal_no") or "Chưa có",
            "bien_so": bien_so_fmt,
            "ro_mooc": mooc_fmt,
            "mooc": mooc_fmt,
            "dong_mooc": dong_mooc,
            "tai_xe": context.get("tai_xe") or context.get("driver_name") or "",
            "sdt": sdt_fmt,
            "diem_tra": context.get("diem_tra") or context.get("warehouse_name") or context.get("location") or "Theo kế hoạch",
            "diem_dong": context.get("diem_dong") or context.get("warehouse_name") or context.get("location") or "Theo kế hoạch",
            "diem_den": context.get("diem_den") or context.get("warehouse_name") or context.get("location") or "Theo kế hoạch",
            "gio_den": gio_den_fmt,
            "kich_thuoc": context.get("kich_thuoc") or context.get("container_size") or "40DC",
            "dong_ghi_chu": dong_ghi_chu,
            "thay_doi": context.get("thay_doi") or "- Cập nhật thông tin xe",
            "ly_do": context.get("ly_do") or "Theo yêu cầu điều vận",
        }

        res = tpl
        for k, v in mapping.items():
            res = res.replace(f"{{{k}}}", str(v))
        return res


class OutboundTemplateBuilder:
    """Bộ khởi tạo văn bản phản hồi cho Nhà xe và Nhóm khách hàng theo mẫu chuẩn VSICO."""

    @classmethod
    def check_core_fields_completeness(cls, line: ExtractedContainerLine) -> tuple[bool, list[str]]:
        """Kiểm tra 5 trường bắt buộc đối với nhà xe:
        1. Biển số xe đầu kéo (đủ 5 chữ số chuẩn hoặc khớp danh mục)
        2. Biển số rơ-moóc (đủ 5 chữ số chuẩn hoặc khớp danh mục)
        3. Số container (đúng định dạng và số kiểm tra ISO 6346)
        4. Tên tài xế (ít nhất 2 ký tự)
        5. SĐT tài xế (đúng 10 số bắt đầu bằng 0)
        Các trường khác (Khách hàng, Kho, Loại lệnh, Số chì, Kích thước, Giờ dự kiến...) là tùy chọn:
        có thì bắt và cập nhật, không có vẫn hợp lệ.

        Returns:
            tuple[bool, list[str]]: (is_complete, danh_sach_truong_thieu_hoac_sai)
        """
        missing: list[str] = []

        # 1. Xe (biển số đầu kéo đủ 5 chữ số chuẩn XXA-123.45 hoặc khớp danh mục)
        raw_truck = line.truck_plate or line.plate_compact
        norm_truck = clean_plate(raw_truck) if raw_truck else None
        if not norm_truck:
            missing.append("Biển số xe")
        elif (
            not re.match(r"^\d{2}[A-Z]{1,2}-\d{3}\.\d{2}$", norm_truck)
            and line.field_evidences.get("truck_plate") not in ("carrier_vehicle_catalog", "carrier_vehicle_suffix")
        ):
            missing.append("Biển số xe (phải đủ 5 chữ số)")

        # 2. Rơ-moóc (bắt buộc: phải đủ 5 chữ số chuẩn XXR/RM-123.45 hoặc khớp danh mục)
        if not line.trailer_plate:
            missing.append("Biển số rơ-moóc")
        else:
            norm_trailer = clean_plate(line.trailer_plate) or line.trailer_plate
            if (
                not re.match(r"^\d{2}[A-Z]?R[M]?-\d{3}\.\d{2}$", norm_trailer)
                and line.field_evidences.get("trailer_plate")
                not in ("carrier_trailer_catalog", "carrier_trailer_suffix", "carrier_trailer_catalog_reclassified")
            ):
                missing.append("Biển số rơ-moóc (phải đủ 5 chữ số)")

        # 3. Tên tài xế
        if not line.driver_name or len(line.driver_name.strip()) < 2:
            missing.append("Tên tài xế")

        # 4. SĐT tài xế (hỗ trợ 1 hoặc nhiều SĐT dạng '09..1 | 09..2')
        if not line.driver_phone:
            missing.append("SĐT tài xế")
        elif not is_valid_phone_list(line.driver_phone):
            missing.append("SĐT tài xế (phải đúng 10 số bắt đầu bằng 0)")

        # 5. Số container
        if not line.container_no:
            missing.append("Số container")
        elif "INVALID_CONTAINER_FORMAT" in (line.warnings or []):
            missing.append("Số container (chưa đúng định dạng 4 chữ + 7 số)")
        elif line.check_digit_valid is False or any(w.startswith("ISO6346_CHECK_DIGIT_MISMATCH") for w in line.warnings):
            missing.append("Số container (sai số kiểm tra cuối)")

        is_complete = (len(missing) == 0)
        return is_complete, missing

    @classmethod
    def build_customer_notification(
        cls,
        line: ExtractedContainerLine,
        customer_name: Optional[str] = None,
        warehouse_name: Optional[str] = None,
        customer_id: Optional[str] = None,
        plan_date: Optional[Any] = None,
    ) -> str:
        """Tạo nội dung thông báo gửi nhóm khách hàng theo mẫu chuẩn."""
        engine = TemplateEngine()
        loai = TemplateEngine._normalize_template_kind(line.order_type) or "tra"

        ctx = {
            "ten_khach_hang": customer_name or line.customer_hint or "Quý khách hàng",
            "ke_hoach_ngay": plan_date or line.plan_date,
            "so_cont": line.container_no,
            "kich_thuoc": line.canonical_cont_size or line.container_size or "40DC",
            "so_chi": line.seal_no or "Chưa có",
            "bien_so": line.truck_plate or line.plate_compact,
            "ro_mooc": line.trailer_plate,
            "tai_xe": line.driver_name,
            "sdt": line.driver_phone,
            "diem_tra": warehouse_name or line.warehouse_hint or "Kho khách hàng",
            "diem_dong": warehouse_name or line.warehouse_hint or "Bãi/Cảng đóng hàng",
            "gio_den": line.eta_time or line.estimated_at or line.eta_text,
            "ghi_chu": line.note,
        }
        return engine.render_notification(loai, ctx, customer_id=customer_id)

    @classmethod
    def build_update_notification(
        cls,
        line: ExtractedContainerLine,
        changes_list: list[str],
        customer_name: Optional[str] = None,
        warehouse_name: Optional[str] = None,
        customer_id: Optional[str] = None,
        plan_date: Optional[Any] = None,
    ) -> str:
        """Tạo nội dung thông báo CẬP NHẬT thông tin xe gửi khách hàng khi có thay đổi."""
        engine = TemplateEngine()
        changes_str = "\n".join(changes_list) if changes_list else "- Cập nhật thông tin điều vận"
        ctx = {
            "ten_khach_hang": customer_name or line.customer_hint or "Quý khách hàng",
            "ke_hoach_ngay": plan_date or line.plan_date,
            "so_cont": line.container_no,
            "kich_thuoc": line.canonical_cont_size or line.container_size or "40DC",
            "so_chi": line.seal_no or "Chưa có",
            "bien_so": line.truck_plate or line.plate_compact,
            "ro_mooc": line.trailer_plate,
            "tai_xe": line.driver_name,
            "sdt": line.driver_phone,
            "diem_den": warehouse_name or line.warehouse_hint or "Kho khách hàng",
            "diem_tra": warehouse_name or line.warehouse_hint or "Kho khách hàng",
            "diem_dong": warehouse_name or line.warehouse_hint or "Bãi/Cảng đóng hàng",
            "gio_den": line.eta_time or line.estimated_at or line.eta_text,
            "ghi_chu": line.note,
            "thay_doi": changes_str,
        }
        return engine.render_notification("capnhat", ctx, customer_id=customer_id)

    @classmethod
    def build_cancel_notification(
        cls,
        line: ExtractedContainerLine,
        reason: str = "Theo yêu cầu điều vận",
        customer_name: Optional[str] = None,
        warehouse_name: Optional[str] = None,
        customer_id: Optional[str] = None,
        plan_date: Optional[Any] = None,
    ) -> str:
        """Tạo nội dung thông báo HỦY CHUYẾN gửi khách hàng sau khi ĐHVT xác nhận."""
        engine = TemplateEngine()
        ctx = {
            "ten_khach_hang": customer_name or line.customer_hint or "Quý khách hàng",
            "ke_hoach_ngay": plan_date or line.plan_date,
            "so_cont": line.container_no,
            "kich_thuoc": line.canonical_cont_size or line.container_size or "40DC",
            "bien_so": line.truck_plate or line.plate_compact,
            "ro_mooc": line.trailer_plate,
            "diem_den": warehouse_name or line.warehouse_hint or "Kho khách hàng",
            "ly_do": reason,
            "ghi_chu": line.note,
        }
        return engine.render_notification("huy", ctx, customer_id=customer_id)

    @classmethod
    def evaluate_timing_deadline(
        cls,
        order_type: Optional[str],
        eta_raw: Any,
        message_time: Optional[datetime] = None,
        plan_date_str: Optional[str] = None,
    ) -> tuple[str, str]:
        """Đánh giá thời hạn gửi tin nhắn theo quy tắc nghiệp vụ VSICO:
        1. Lệnh Đóng (vỏ kết hợp): Hạn trước 10:00 của ngày đóng xe.
        2. Lệnh Trả: So sánh thời điểm nhận tin với giờ xe đến kho (ETA).
        """
        loai = TemplateEngine._normalize_template_kind(order_type) or "tra"
        if not message_time:
            return "not_evaluated", "Không áp dụng (không xác định được thời gian gửi tin)"

        # 1. Quy tắc Lệnh Đóng: Hạn gửi trước 10:00 ngày đóng xe (vỏ kết hợp)
        if loai == "dong":
            if message_time.hour > 10 or (message_time.hour == 10 and message_time.minute > 0):
                return (
                    "overdue_warning",
                    f"QUÁ HẠN: Gửi lúc {message_time.strftime('%H:%M')} sau 10:00 ngày đóng (vỏ kết hợp) → cảnh báo ĐHVT (vẫn gửi)",
                )
            return "on_time", f"OK: Gửi lúc {message_time.strftime('%H:%M')} trước hạn 10:00 ngày đóng (vỏ kết hợp)"

        # 2. Quy tắc Lệnh Trả: Gửi trước giờ xe đến kho (khách có tin trước khi xe tới)
        eta_str = str(eta_raw or "").strip()
        eta_hour: Optional[int] = None
        eta_minute: int = 0

        # Thử bóc tách giờ từ chuỗi (VD: '8h', '8h30', '08:00', '14:30 14/10/2026')
        m_hm = re.search(r"(\d{1,2})[h:](\d{1,2})", eta_str)
        if m_hm:
            eta_hour = int(m_hm.group(1))
            eta_minute = int(m_hm.group(2))
        else:
            m_h = re.search(r"(\d{1,2})\s*h\b", eta_str, re.IGNORECASE)
            if m_h:
                eta_hour = int(m_h.group(1))
                eta_minute = 0

        if eta_hour is not None and 0 <= eta_hour <= 23:
            eta_time_obj = message_time.replace(hour=eta_hour, minute=eta_minute, second=0, microsecond=0)
            if message_time > eta_time_obj:
                return (
                    "late_warning",
                    f"CẢNH BÁO: Gửi lúc {message_time.strftime('%H:%M')} muộn hơn giờ xe đến {eta_hour:02d}:{eta_minute:02d} (khách chưa có tin khi xe đã tới)",
                )
            return (
                "on_time",
                f"OK: Gửi lúc {message_time.strftime('%H:%M')} trước giờ xe đến kho {eta_hour:02d}:{eta_minute:02d}",
            )

        return "not_evaluated", "Không áp dụng (tin nhắn không có giờ xe đến kho cụ thể)"

    @classmethod
    def build_carrier_warning_reply(cls, lines: list[ExtractedContainerLine]) -> str:
        """Tạo phản hồi thân thiện, chuẩn hóa nhắc nhà xe khi thông tin xe/container bị thiếu hoặc chưa chính xác.

        Tuyệt đối không hiển thị Regex, check digit, gợi ý đoán số đúng, mã lỗi nội bộ hay chi tiết DB;
        chỉ trình bày theo công thức: Vấn đề + Thông tin cần kiểm tra + Hướng xử lý.

        Args:
            lines (list[ExtractedContainerLine]): Danh sách các dòng xe/container trong tin nhắn.

        Returns:
            str: Chuỗi thông báo thân thiện gửi nhà xe, hoặc chuỗi rỗng nếu tất cả đều hợp lệ.
        """
        per_line_categories: list[tuple[ExtractedContainerLine, list[str]]] = []

        for line in lines:
            categories: list[str] = []
            warnings = list(line.warnings or [])
            is_comp, missing = cls.check_core_fields_completeness(line)

            # 1. Phân loại lỗi số container
            has_cont_invalid = (
                line.check_digit_valid is False
                or any(
                    w.startswith("ISO6346_CHECK_DIGIT_MISMATCH") or w == "INVALID_CONTAINER_FORMAT"
                    for w in warnings
                )
            )
            has_cont_missing = (
                not has_cont_invalid
                and (
                    not line.container_no
                    or "Số container" in missing
                    or any(w in ("MISSING_CONTAINER_NO", "PENDING_CONTAINER_NO") for w in warnings)
                )
            )
            if has_cont_invalid:
                categories.append("INVALID_CONTAINER")
            elif has_cont_missing:
                categories.append("MISSING_CONTAINER")

            # 2. Phân loại lỗi biển số xe đầu kéo
            has_truck_invalid = any(
                w == "INVALID_TRUCK_PLATE_FORMAT" or w.startswith("TRAILER_PLATE_IN_TRUCK_POSITION")
                for w in warnings
            ) or any("Biển số xe" in m and line.truck_plate for m in missing)
            has_truck_missing = (
                not has_truck_invalid
                and (
                    not line.truck_plate
                    or "Biển số xe" in missing
                    or "MISSING_TRUCK_PLATE" in warnings
                )
            )
            if has_truck_invalid:
                categories.append("INVALID_TRUCK_PLATE")
            elif has_truck_missing:
                categories.append("MISSING_TRUCK_PLATE")

            # 3. Phân loại lỗi biển số rơ-moóc
            has_trailer_invalid = "INVALID_TRAILER_PLATE_FORMAT" in warnings or any(
                "rơ-moóc" in m.lower() and line.trailer_plate for m in missing
            )
            has_trailer_missing = (
                not has_trailer_invalid
                and (
                    not line.trailer_plate
                    or "Biển số rơ-moóc" in missing
                    or "MISSING_TRAILER_PLATE" in warnings
                )
            )
            if has_trailer_invalid:
                categories.append("INVALID_TRAILER_PLATE")
            elif has_trailer_missing:
                categories.append("MISSING_TRAILER_PLATE")

            # 4. Phân loại lỗi số điện thoại tài xế
            has_phone_invalid = "INVALID_DRIVER_PHONE" in warnings or any(
                "sđt" in m.lower() and line.driver_phone for m in missing
            )
            if has_phone_invalid:
                categories.append("INVALID_PHONE")

            # 5. Tách riêng hoàn toàn lỗi thiếu tên tài xế và thiếu SĐT tài xế (thiếu gì nhắc đấy)
            has_driver_name_missing = (
                not line.driver_name
                or "Tên lái xe" in missing
                or "Tên tài xế" in missing
                or "MISSING_DRIVER_NAME" in warnings
            )
            has_driver_phone_missing = (
                not has_phone_invalid
                and (
                    not line.driver_phone
                    or "SĐT lái xe" in missing
                    or "SĐT tài xế" in missing
                    or "MISSING_DRIVER_PHONE" in warnings
                )
            )
            if has_driver_name_missing:
                categories.append("MISSING_DRIVER_NAME")
            if has_driver_phone_missing:
                categories.append("MISSING_DRIVER_PHONE")

            if categories:
                per_line_categories.append((line, categories))

        if not per_line_categories:
            return ""

        single_templates: dict[str, tuple[str, str]] = {
            "MISSING_CONTAINER": ("📝", "Anh/chị vui lòng bổ sung số container giúp hệ thống nhé."),
            "INVALID_CONTAINER": ("🔎", "Số container có thể chưa chính xác. Anh/chị vui lòng kiểm tra lại nhé."),
            "INVALID_TRUCK_PLATE": ("🔎", "Biển số xe đầu kéo chưa hợp lệ. Anh/chị vui lòng kiểm tra lại giúp hệ thống nhé."),
            "MISSING_TRUCK_PLATE": ("📝", "Anh/chị vui lòng bổ sung biển số xe đầu kéo giúp hệ thống nhé."),
            "INVALID_TRAILER_PLATE": ("🔎", "Biển số rơ-moóc chưa hợp lệ. Anh/chị vui lòng kiểm tra lại giúp hệ thống nhé."),
            "MISSING_TRAILER_PLATE": ("📝", "Anh/chị vui lòng bổ sung biển số rơ-moóc giúp hệ thống nhé."),
            "MISSING_DRIVER_NAME": ("📝", "Anh/chị vui lòng bổ sung tên tài xế giúp hệ thống nhé."),
            "MISSING_DRIVER_PHONE": ("📝", "Anh/chị vui lòng bổ sung SĐT tài xế giúp hệ thống nhé."),
            "INVALID_PHONE": ("🔎", "Số điện thoại tài xế có thể chưa chính xác. Anh/chị vui lòng kiểm tra lại nhé."),
        }
        field_labels: dict[str, str] = {
            "MISSING_CONTAINER": "số container",
            "INVALID_CONTAINER": "số container",
            "INVALID_TRUCK_PLATE": "biển số xe đầu kéo",
            "MISSING_TRUCK_PLATE": "biển số xe đầu kéo",
            "INVALID_TRAILER_PLATE": "biển số rơ-moóc",
            "MISSING_TRAILER_PLATE": "biển số rơ-moóc",
            "MISSING_DRIVER_NAME": "tên tài xế",
            "MISSING_DRIVER_PHONE": "SĐT tài xế",
            "INVALID_PHONE": "SĐT tài xế",
        }

        def _cap_first(text_val: str) -> str:
            """Viết hoa chữ cái đầu mà vẫn giữ nguyên các cụm viết tắt như SĐT."""
            return (text_val[0].upper() + text_val[1:]) if text_val else text_val

        if len(per_line_categories) == 1:
            line, cats = per_line_categories[0]
            if len(cats) == 1:
                if cats[0] == "INVALID_CONTAINER" and line.container_no:
                    if "INVALID_CONTAINER_FORMAT" in (line.warnings or []):
                        return (
                            f"[VSICO] - 🔎 Số container {line.container_no} chưa đúng định dạng "
                            "(cần đủ 4 chữ cái và 7 chữ số). Anh/chị vui lòng kiểm tra lại nhé."
                        )
                    return (
                        f"[VSICO] - 🔎 Số container có thể chưa chính xác ({line.container_no}). "
                        "Anh/chị vui lòng kiểm tra lại nhé."
                    )
                icon, msg = single_templates[cats[0]]
                return f"[VSICO] - {icon} {msg}"
            if set(cats) == {"MISSING_DRIVER_NAME", "MISSING_DRIVER_PHONE"}:
                return "[VSICO] - 📝 Anh/chị vui lòng bổ sung tên và SĐT tài xế giúp hệ thống nhé."

            is_only_missing = all(c.startswith("MISSING_") for c in cats)
            is_only_invalid = all(c.startswith("INVALID_") for c in cats)
            icon = "📝" if is_only_missing else "🔎"
            title = "Cần bổ sung thông tin chuyến xe" if is_only_missing else "Cần kiểm tra lại thông tin chuyến xe"
            ref = line.container_no or line.truck_plate
            ref_line = f"\n\n📦 Chuyến xe: {ref}" if ref else ""

            if is_only_missing:
                labels = list(dict.fromkeys(field_labels[c] for c in cats))
                intro_line = "Hệ thống cần anh/chị bổ sung:"
                bullet_lines = "\n".join(f"• {_cap_first(lbl)}." for lbl in labels)
                closing = "Anh/chị bổ sung giúp hệ thống nhé."
            elif is_only_invalid:
                labels = list(dict.fromkeys(field_labels[c] for c in cats))
                intro_line = "Hệ thống cần anh/chị kiểm tra lại:"
                bullet_lines = "\n".join(f"• {_cap_first(lbl)}." for lbl in labels)
                closing = "Anh/chị kiểm tra và gửi lại giúp hệ thống nhé."
            else:
                action_items: list[str] = []
                for c in cats:
                    prefix = "Kiểm tra lại" if c.startswith("INVALID_") else "Bổ sung"
                    item_str = f"• {prefix} {field_labels[c]}."
                    if item_str not in action_items:
                        action_items.append(item_str)
                intro_line = "Hệ thống cần anh/chị rà soát và bổ sung:"
                bullet_lines = "\n".join(action_items)
                closing = "Anh/chị kiểm tra và gửi bổ sung giúp hệ thống nhé."

            return (
                f"[VSICO] - {icon} {title}{ref_line}\n\n"
                f"{intro_line}\n{bullet_lines}\n\n"
                f"{closing}"
            )

        # Nhiều chuyến xe cùng có lỗi trong 1 tin nhắn -> gom gọn thành 1 thông báo duy nhất
        detail_lines: list[str] = []
        for idx, (line, cats) in enumerate(per_line_categories, start=1):
            ref = line.container_no or line.truck_plate or f"chuyến thứ {line.line_no}"
            inv_labels = list(dict.fromkeys(field_labels[c] for c in cats if c.startswith("INVALID_")))
            mis_labels = list(dict.fromkeys(field_labels[c] for c in cats if c.startswith("MISSING_")))
            parts: list[str] = []
            if inv_labels:
                parts.append(f"kiểm tra {', '.join(inv_labels)}")
            if mis_labels:
                parts.append(f"bổ sung {', '.join(mis_labels)}")
            detail_lines.append(f"{idx}. 📦 {ref}: cần {' và '.join(parts)}.")
        return (
            f"[VSICO] - 🔎 Có {len(per_line_categories)} chuyến xe cần bổ sung hoặc kiểm tra lại\n\n"
            + "\n".join(detail_lines)
            + "\n\nAnh/chị rà soát và gửi bổ sung giúp hệ thống nhé."
        )

    @classmethod
    def build_clarify_container_reply(cls) -> str:
        """Tạo câu hỏi phản hồi thân thiện khi hệ thống chưa xác định được chuyến xe cần cập nhật."""
        return (
            "[VSICO] - 🔍 Chưa xác định được chuyến xe cần cập nhật\n\n"
            "Anh/chị vui lòng gửi kèm số container hoặc mã lệnh (RO/LO) để hệ thống đối chiếu chính xác nhé."
        )

    @classmethod
    def build_unknown_container_carrier_warning(cls, container_no: Optional[str] = None) -> str:
        """Tạo cảnh báo thân thiện gửi nhà xe khi số container không tồn tại trong kế hoạch vận chuyển."""
        if container_no:
            return (
                "[VSICO] - 🔎 Cần kiểm tra lại số container\n\n"
                f"📦 Container: {container_no}\n\n"
                "Số container này hiện chưa có trong kế hoạch vận chuyển của nhà xe. "
                "Anh/chị vui lòng kiểm tra lại số container hoặc chờ ĐHVT đối chiếu nhé."
            )
        return cls.build_clarify_container_reply()

    @classmethod
    def build_combined_lo_confirm_reply(
        cls,
        *,
        container_no: str,
        ro_order_code: Optional[str],
        lo_order_code: Optional[str],
        truck_plate: Optional[str],
        lo_warehouse: Optional[str] = None,
    ) -> str:
        """Tạo tin nhắn hỏi xác nhận/duyệt lệnh đóng kết hợp gửi nhà xe sau khi lệnh trả đã tự động cập nhật."""
        ro_lbl = ro_order_code or "lệnh trả"
        lo_lbl = lo_order_code or "lệnh đóng kết hợp"
        wh_line = f"\n• Kho đóng: {lo_warehouse}" if lo_warehouse else ""
        plate_part = f"xe {truck_plate} " if truck_plate else ""
        return (
            "[VSICO] - ⚠️ Xác nhận cập nhật lệnh đóng kết hợp\n\n"
            f"📦 Container: {container_no}\n"
            f"• Đã cập nhật {plate_part}cho lệnh trả {ro_lbl}.\n"
            f"• Container này có lệnh đóng kết hợp {lo_lbl}.{wh_line}\n\n"
            f"👉 Anh/chị nhắn 'ok' (hoặc gửi số chì mới) để hệ thống cập nhật tiếp cho {lo_lbl} nhé."
        )

    @classmethod
    def build_update_confirm_reply(
        cls,
        container_no: str,
        changes_list: list[str],
    ) -> str:
        """Tạo tin xác nhận gửi lại nhà xe sau khi đã cập nhật thông tin điều xe mới."""
        changes_str = ", ".join(ch.lstrip("- ").strip() for ch in changes_list) if changes_list else "thông tin điều xe"
        return (
            "[VSICO] - ✅ Đã ghi nhận cập nhật chuyến xe\n\n"
            f"📦 Container: {container_no}\n"
            f"• Nội dung cập nhật: {changes_str}\n\n"
            "Hệ thống đã đồng bộ kế hoạch và chuyển thông báo tới ĐHVT / khách hàng."
        )
