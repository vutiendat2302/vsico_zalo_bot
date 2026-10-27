"""Module Động Cơ Mẫu Thông Báo (Outbound Template Engine).

Chịu trách nhiệm nạp, quản lý và render nội dung thông báo gửi cho khách hàng:
- Định dạng hiển thị biển số xe (15C-878.99 hoặc 29H-102.39).
- Định dạng hiển thị ngày giờ đến kho thân thiện.
- Hỗ trợ ghi đè mẫu tin theo từng mã khách hàng cụ thể (`templates/customers/<khach_id>_<loai>.txt`).
- Cách ly hoàn toàn văn bản tiếng Việt ra khỏi logic code xử lý (Template Isolation).
"""

import os
import re
from datetime import datetime
from typing import Optional, Dict, Any


def format_license_plate_display(clean_plate: Optional[str]) -> str:
    """Định dạng chuỗi biển số xe viết liền thành dạng có dấu gạch và chấm thẩm mỹ.

    Ví dụ: '15C87899' -> '15C-878.99', '29H1234' -> '29H-1234'.

    Args:
        clean_plate (Optional[str]): Chuỗi biển số xe đã làm sạch.

    Returns:
        str: Chuỗi biển số định dạng hiển thị đẹp mắt hoặc chuỗi rỗng.
    """
    if not clean_plate:
        return ""
    p = clean_plate.upper().replace("-", "").replace(".", "").strip()
    m5 = re.match(r'^(\d{2}[A-Z]{1,2})(\d{3})(\d{2})$', p)
    if m5:
        return f"{m5.group(1)}-{m5.group(2)}.{m5.group(3)}"
    m4 = re.match(r'^(\d{2}[A-Z]{1,2})(\d{4})$', p)
    if m4:
        return f"{m4.group(1)}-{m4.group(2)}"
    return clean_plate


def format_arrival_time_display(iso_time_str: Optional[str]) -> str:
    """Chuyển đổi chuỗi ngày giờ sang định dạng hiển thị thân thiện với người dùng.

    Args:
        iso_time_str (Optional[str]): Chuỗi thời gian (ISO hoặc dạng 'HH:MM DD/MM/YYYY').

    Returns:
        str: Chuỗi ngày giờ hiển thị dạng 'HH:MM, DD/MM/YYYY' hoặc giữ nguyên nếu không parse được.
    """
    if not iso_time_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_time_str)
        return dt.strftime("%H:%M, %d/%m/%Y")
    except Exception:
        return iso_time_str


class TemplateEngine:
    """Bộ máy nạp và điền dữ liệu vào mẫu thông báo Outbound."""

    def __init__(self, templates_dir: str = "templates"):
        """Khởi tạo TemplateEngine.

        Args:
            templates_dir (str): Đường dẫn tới thư mục chứa các tệp mẫu thông báo (.txt).
        """
        self.templates_dir = templates_dir

    def get_template(self, loai: str, customer_id: Optional[str] = None) -> str:
        """Nạp nội dung tệp mẫu thông báo tương ứng.

        Thứ tự ưu tiên:
        1. Mẫu riêng theo mã khách hàng: `templates/customers/<customer_id>_<loai>.txt`.
        2. Mẫu mặc định chung: `templates/default_<loai>.txt`.
        3. Chuỗi mẫu dự phòng nội bộ (hardcoded fallback) nếu tệp không tồn tại trên đĩa.

        Args:
            loai (str): Loại mẫu ('tra', 'nhap', 'capnhat').
            customer_id (Optional[str]): Mã khách hàng cụ thể nếu có (ví dụ: 'KH001').

        Returns:
            str: Nội dung chuỗi mẫu thông báo với các placeholder {bien}.
        """
        if customer_id:
            cust_path = os.path.join(
                self.templates_dir, "customers", f"{customer_id}_{loai}.txt"
            )
            if os.path.exists(cust_path):
                with open(cust_path, "r", encoding="utf-8") as f:
                    return f.read()

        default_path = os.path.join(self.templates_dir, f"default_{loai}.txt")
        if os.path.exists(default_path):
            with open(default_path, "r", encoding="utf-8") as f:
                return f.read()

        # Mẫu dự phòng nội bộ nếu thư mục templates bị thiếu file
        if loai == "capnhat":
            return (
                "THÔNG BÁO CẬP NHẬT THÔNG TIN XE\n\n"
                "Kính gửi Quý khách hàng,\n"
                "VSICO xin thông báo cập nhật thông tin xe cho cont {so_cont}:\n\n"
                "Các thông tin thay đổi:\n"
                "{thay_doi}\n\n"
                "Thông tin xe hiện tại:\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}\n"
                "- Tài xế: {tai_xe}\n"
                "- SĐT: {sdt}\n"
                "- Điểm trả: {diem_tra}\n"
                "- Dự kiến đến kho: {gio_den}\n"
            )
        else:
            return (
                "THÔNG BÁO XE TRẢ HÀNG\n\n"
                "Kính gửi Quý khách hàng,\n"
                "VSICO xin thông báo thông tin xe trả hàng:\n\n"
                "- Số cont: {so_cont} ({kich_thuoc})\n"
                "- Số chì: {so_chi}\n"
                "- Biển số xe: {bien_so}\n"
                "- Tài xế: {tai_xe}\n"
                "- SĐT: {sdt}\n"
                "- Điểm trả: {diem_tra}\n"
                "- Dự kiến đến kho: {gio_den}\n"
            )

    def render_notification(
        self, loai: str, context: Dict[str, Any], customer_id: Optional[str] = None
    ) -> str:
        """Điền dữ liệu thực tế vào mẫu thông báo để tạo ra tin nhắn hoàn chỉnh.

        Args:
            loai (str): Loại mẫu thông báo ('tra', 'nhap', 'capnhat').
            context (Dict[str, Any]): Từ điển dữ liệu chứa thông tin xe và chuyến.
            customer_id (Optional[str]): Mã khách hàng nhận tin (nếu có tùy biến mẫu).

        Returns:
            str: Nội dung thông báo hoàn chỉnh sẵn sàng gửi đi.
        """
        tpl = self.get_template(loai, customer_id)
        bien_so_fmt = format_license_plate_display(context.get("bien_so"))
        gio_den_fmt = format_arrival_time_display(context.get("gio_den"))

        mapping = {
            "so_cont": context.get("cont") or "",
            "so_chi": context.get("seal") or "",
            "bien_so": bien_so_fmt,
            "tai_xe": context.get("tai_xe") or "",
            "sdt": context.get("sdt") or "",
            "diem_tra": context.get("kho_tra") or context.get("dia_chi_kho_tra") or "",
            "gio_den": gio_den_fmt,
            "kich_thuoc": context.get("kich_thuoc_cont") or "40DC",
            "thay_doi": context.get("thay_doi") or "- Cập nhật thông tin xe",
        }

        # Thay thế từng placeholder {key} trong mẫu
        res = tpl
        for k, v in mapping.items():
            res = res.replace(f"{{{k}}}", str(v))
        return res
