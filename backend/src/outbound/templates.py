"""Module Tạo Nội Dung Phản Hồi & Thông Báo Theo Mẫu (Outbound Template Engine).

Tuân thủ nghiêm ngặt nguyên tắc Template Isolation (Mục 1.6 - AGENTS.md):
- Tuyệt đối không hardcode chuỗi thông báo tiếng Việt gửi khách hàng trong mã nguồn xử lý.
- Mọi nội dung gửi đi được nạp và render thông qua `TemplateEngine` từ thư mục `outbound/templates/`.
- Hỗ trợ ghi đè mẫu tin theo từng mã khách hàng cụ thể (`templates/customers/<khach_hang_id>_<loai>.txt`).
- Che 6 số cuối SĐT tài xế (VD: 0986******) theo chuẩn bảo vệ thông tin riêng tư.
- Kiểm tra tính đầy đủ của 8 trường thông tin cốt lõi trước khi gửi:
  (1) Khách hàng, (2) Lệnh, (3) Xe, (4) Tài xế, (5) SĐT, (6) Cont, (7) Size, (8) Chì.
  Giờ dự kiến và Ghi chú là tùy chọn (có thể null).
"""

import os
import re
from datetime import datetime
from typing import Any, Optional

from src.domain.models import ExtractedContainerLine
from src.domain.rules import compute_iso6346_check_digit


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
    """Che 6 số giữa/cuối của SĐT tài xế (VD: '0986713346' -> '0986******')."""
    if not phone:
        return ""
    p = str(phone).strip()
    if "*" in p:
        return p
    if len(p) == 10 and p.startswith("0"):
        return f"{p[:4]}******"
    return p


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

    def get_template(self, loai: str, customer_id: Optional[str] = None) -> str:
        """Nạp tệp mẫu tương ứng.

        Thứ tự ưu tiên:
        1. Mẫu riêng của khách hàng: `templates/customers/<customer_id>_<loai>.txt`
        2. Mẫu mặc định chung: `templates/default_<loai>.txt`
        3. Fallback nội bộ nếu thiếu tệp trên đĩa.
        """
        loai_clean = loai if loai in ("tra", "dong", "capnhat") else "tra"

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
                "Khách hàng: {ten_khach_hang}\n\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}\n"
                "- Lái xe: {tai_xe} - SĐT: {sdt}\n"
                "- Điểm trả: {diem_tra}\n"
                "- Giờ đến dự kiến: {gio_den}{dong_ghi_chu}\n"
            )
        elif loai_clean == "capnhat":
            return (
                "VSICO - THÔNG BÁO CẬP NHẬT THÔNG TIN XE\n"
                "Khách hàng: {ten_khach_hang}\n\n"
                "Cập nhật thông tin xe cho cont {so_cont}:\n"
                "Các thông tin thay đổi:\n{thay_doi}\n\n"
                "Thông tin xe hiện tại:\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}\n"
                "- Lái xe: {tai_xe} - SĐT: {sdt}\n"
                "- Điểm đến: {diem_den}\n"
                "- Giờ đến dự kiến: {gio_den}{dong_ghi_chu}\n"
            )
        else:
            return (
                "VSICO - THÔNG BÁO XE ĐÓNG HÀNG\n"
                "Khách hàng: {ten_khach_hang}\n\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}\n"
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
        sdt_fmt = str(context.get("sdt") or context.get("driver_phone") or "").strip()
        gio_den_fmt = format_arrival_time_display(context.get("gio_den") or context.get("eta"))

        note = context.get("ghi_chu") or context.get("note")
        dong_ghi_chu = f"\n- Ghi chú: {note}" if note else ""

        mapping = {
            "ten_khach_hang": context.get("ten_khach_hang") or context.get("customer_name") or "Quý khách hàng",
            "so_cont": context.get("so_cont") or context.get("container_no") or "",
            "so_chi": context.get("so_chi") or context.get("seal_no") or "Chưa có",
            "bien_so": bien_so_fmt,
            "tai_xe": context.get("tai_xe") or context.get("driver_name") or "",
            "sdt": sdt_fmt,
            "diem_tra": context.get("diem_tra") or context.get("warehouse_name") or context.get("location") or "Theo kế hoạch",
            "diem_dong": context.get("diem_dong") or context.get("warehouse_name") or context.get("location") or "Theo kế hoạch",
            "diem_den": context.get("diem_den") or context.get("warehouse_name") or context.get("location") or "Theo kế hoạch",
            "gio_den": gio_den_fmt,
            "kich_thuoc": context.get("kich_thuoc") or context.get("container_size") or "40DC",
            "dong_ghi_chu": dong_ghi_chu,
            "thay_doi": context.get("thay_doi") or "- Cập nhật thông tin xe",
        }

        res = tpl
        for k, v in mapping.items():
            res = res.replace(f"{{{k}}}", str(v))
        return res


class OutboundTemplateBuilder:
    """Bộ khởi tạo văn bản phản hồi cho Nhà xe và Nhóm khách hàng theo mẫu chuẩn VSICO."""

    @classmethod
    def check_core_fields_completeness(cls, line: ExtractedContainerLine) -> tuple[bool, list[str]]:
        """Kiểm tra xem dòng dữ liệu có đáp ứng đủ 8 trường cốt lõi theo quy định:
        1. Khách hàng
        2. Lệnh (đóng hoặc trả)
        3. Xe (biển số)
        4. Tài xế (tên)
        5. SĐT (10 số bắt đầu bằng 0)
        6. Cont (số container và check digit hợp lệ)
        7. Size (kích thước cont: 20, 40, 45...)
        8. Chì (số chì / seal)
        (Giờ dự kiến và Ghi chú là tùy chọn - có thể null).

        Returns:
            tuple[bool, list[str]]: (is_complete, danh_sach_truong_thieu_hoac_sai)
        """
        missing: list[str] = []

        # 1. Khách hàng
        if not line.customer_hint and not line.customer_code_or_id:
            missing.append("Khách hàng")

        # 2. Lệnh (đóng/trả)
        if not line.order_type or line.order_type not in ("tra", "dong"):
            missing.append("Loại lệnh (đóng/trả)")

        # 3. Xe (biển số)
        if not line.truck_plate and not line.plate_compact:
            missing.append("Biển số xe")

        # 4. Tài xế (tên)
        if not line.driver_name or len(line.driver_name.strip()) < 2:
            missing.append("Tên tài xế")

        # 5. SĐT tài xế
        if not line.driver_phone:
            missing.append("SĐT tài xế")
        elif "*" not in line.driver_phone and not re.match(r"^0\d{9}$", line.driver_phone):
            missing.append("SĐT tài xế (phải đúng 10 số bắt đầu bằng 0)")

        # 6. Số container
        if not line.container_no:
            missing.append("Số container")
        elif line.check_digit_valid is False or any(w.startswith("ISO6346_CHECK_DIGIT_MISMATCH") for w in line.warnings):
            missing.append("Số container (sai số kiểm tra ISO 6346)")

        # 7. Kích thước container (size)
        if not line.canonical_cont_size and not line.container_size:
            missing.append("Kích thước container (size)")

        # 8. Số chì (seal)
        if not line.seal_no or len(str(line.seal_no).strip()) < 2:
            missing.append("Số chì (seal)")

        is_complete = (len(missing) == 0)
        return is_complete, missing

    @classmethod
    def build_customer_notification(
        cls,
        line: ExtractedContainerLine,
        customer_name: Optional[str] = None,
        warehouse_name: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> str:
        """Tạo nội dung thông báo gửi nhóm khách hàng theo mẫu chuẩn."""
        engine = TemplateEngine()
        loai = line.order_type if line.order_type in ("tra", "dong") else "tra"

        ctx = {
            "ten_khach_hang": customer_name or line.customer_hint or "Quý khách hàng",
            "so_cont": line.container_no,
            "kich_thuoc": line.canonical_cont_size or line.container_size or "40DC",
            "so_chi": line.seal_no,
            "bien_so": line.truck_plate or line.plate_compact,
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
    ) -> str:
        """Tạo nội dung thông báo CẬP NHẬT thông tin xe gửi khách hàng khi có thay đổi."""
        engine = TemplateEngine()
        changes_str = "\n".join(changes_list) if changes_list else "- Cập nhật thông tin điều vận"
        ctx = {
            "ten_khach_hang": customer_name or line.customer_hint or "Quý khách hàng",
            "so_cont": line.container_no,
            "kich_thuoc": line.canonical_cont_size or line.container_size or "40DC",
            "so_chi": line.seal_no or "Chưa có",
            "bien_so": line.truck_plate or line.plate_compact,
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
        loai = (order_type or "tra").lower()
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
        """Tạo nội dung phản hồi nhắc nhà xe khi dữ liệu xe/container bị thiếu hoặc sai chuẩn.

        Args:
            lines (list[ExtractedContainerLine]): Danh sách các dòng xe/container trong tin nhắn.

        Returns:
            str: Chuỗi thông báo nhắc nhà xe kiểm tra lại, hoặc chuỗi rỗng nếu tất cả đều hợp lệ.
        """
        issue_messages: list[str] = []

        for line in lines:
            reasons: list[str] = []

            # Kiểm tra 8 trường cốt lõi
            is_comp, missing = cls.check_core_fields_completeness(line)
            if not is_comp:
                for m in missing:
                    reasons.append(f"thiếu/sai {m.lower()}")

            # Bổ sung các cảnh báo chi tiết nếu có
            if line.warnings:
                for warn in line.warnings:
                    if warn == "MISSING_TRUCK_PLATE" and "thiếu/sai biển số xe" not in reasons:
                        if line.trailer_plate:
                            reasons.append(
                                f"thiếu biển số xe đầu kéo ('{line.trailer_plate}' là biển số rơ-moóc)"
                            )
                        else:
                            reasons.append("thiếu biển số xe đầu kéo")
                    elif warn == "INVALID_DRIVER_PHONE" and not any("sđt" in r for r in reasons):
                        reasons.append(
                            f"SĐT tài xế '{line.driver_phone}' không hợp lệ (cần đúng 10 chữ số bắt đầu bằng số 0)"
                        )
                    elif warn.startswith("ISO6346_CHECK_DIGIT_MISMATCH"):
                        expected = compute_iso6346_check_digit(line.container_no or "")
                        suggested = (
                            f"{line.container_no[:-1]}{expected}"
                            if line.container_no and expected is not None
                            else ""
                        )
                        reasons.append(
                            f"số container '{line.container_no}' sai số kiểm tra cuối"
                            + (f" (gợi ý đúng: {suggested})" if suggested else "")
                        )

            if reasons:
                # Khử trùng lặp lý do
                unique_reasons = []
                for r in reasons:
                    if r not in unique_reasons:
                        unique_reasons.append(r)
                prefix = f"Xe {line.truck_plate or f'dòng #{line.line_no}'}"
                issue_messages.append(f"- {prefix}: {', '.join(unique_reasons)}.")

        if not issue_messages:
            return ""

        header = "[VSICO Bot] Anh/chị vui lòng kiểm tra và bổ sung lại các thông tin còn thiếu/sai sau:\n"
        return header + "\n".join(issue_messages)
