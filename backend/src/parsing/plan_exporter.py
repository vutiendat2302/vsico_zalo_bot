"""Module Xuất Tệp Excel Kế Hoạch Vận Chuyển Chuẩn Mẫu VSICO (`ketnoi.xlsx`).

Sinh workbook `.xlsx` gồm tiêu đề công ty, ngày kế hoạch và 23 cột dữ liệu
tương thích hoàn toàn với trình import ngược lại (`PlanFileParser.parse_excel`).
"""

from __future__ import annotations

from datetime import date
import io
from typing import Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from src.infrastructure.models import TransportPlan

VN_WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
DEFAULT_GROUP_ID = "b0301d81c0ee29b070ff"


def _format_plan_title(plan_date: Optional[date]) -> str:
    """Tạo dòng tiêu đề ngày kế hoạch theo mẫu chuẩn `DD/MM/YYYY (T2..CN)`."""
    effective = plan_date or date.today()
    wd = VN_WEEKDAYS[effective.weekday()]
    return f"KẾ HOẠCH VẬN CHUYỂN NGÀY {effective.strftime('%d/%m/%Y')} ({wd})"


def _format_truck_cell(plan: TransportPlan) -> Optional[str]:
    """Ghép tên tài xế và biển số xe vào cột `Số xe` tương thích định dạng `ketnoi.xlsx`."""
    plate = (plan.planned_truck_plate or "").strip()
    driver = (plan.driver_name or "").strip()
    if driver and plate:
        return f"{driver} {plate}"
    return plate or driver or None


def export_plans_to_ketnoi_excel(
    plans: list[TransportPlan],
    plan_date: Optional[date] = None,
) -> bytes:
    """Xuất danh sách `TransportPlan` thành tệp Excel (.xlsx) đúng chuẩn `ketnoi.xlsx`.

    Args:
        plans (list[TransportPlan]): Danh sách bản ghi kế hoạch lấy từ MySQL.
        plan_date (Optional[date]): Ngày kế hoạch hiển thị ở tiêu đề sheet.

    Returns:
        bytes: Nội dung nhị phân của file `.xlsx`.
    """
    effective_date = plan_date or (plans[0].plan_date if plans else date.today())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = str(effective_date.day)

    bold_font = Font(name="Arial", size=10, bold=True)
    regular_font = Font(name="Arial", size=10)
    title_font = Font(name="Arial", size=12, bold=True)
    header_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    thin_side = Side(style="thin", color="CBD5E1")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    # Dòng 1 - 4: Tiêu đề đơn vị và ngày kế hoạch giống ketnoi.xlsx
    ws.cell(1, 1, "Công ty CP Hàng Hải Vsico").font = bold_font
    ws.cell(2, 1, "P. Điều Hành Vận Tải").font = bold_font
    ws.cell(4, 2, _format_plan_title(effective_date)).font = title_font

    # Dòng 6 - 7: Header 23 cột chuẩn ketnoi.xlsx
    row6 = [
        "Stt",
        "Tuyến \nvận chuyển",
        "Hàng",
        None,
        "Số cont",
        "Số Seal",
        "SL",
        None,
        "Tải trọng (cả vỏ)",
        "YC t.gian có mặt",
        "Khách hàng",
        "Loại hàng hóa",
        "C.tàu/ Số",
        "Bãi nâng/ hạ vỏ",
        "Bãi nâng/hạ hàng",
        "Giờ dự kiến hạ hàng",
        "Đội xe",
        "Số xe",
        "Địa chỉ đóng/ trả hàng",
        "Group ID",
        "CB giao nhận",
        "Chi chú",
        "Phát sinh",
    ]
    row7 = [
        None,
        None,
        "Xuất",
        "Nhập",
        None,
        None,
        '20"',
        '40"',
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    ]

    for col_idx, val in enumerate(row6, start=1):
        c6 = ws.cell(6, col_idx, val)
        c6.font = bold_font
        c6.fill = header_fill
        c6.border = cell_border
        c6.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        c7 = ws.cell(7, col_idx, row7[col_idx - 1])
        c7.font = bold_font
        c7.fill = header_fill
        c7.border = cell_border
        c7.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Gộp các ô tiêu đề nhóm (Hàng -> Xuất/Nhập, SL -> 20"/40")
    ws.merge_cells(start_row=6, start_column=3, end_row=6, end_column=4)
    ws.merge_cells(start_row=6, start_column=7, end_row=6, end_column=8)
    for col_idx in range(1, 24):
        if col_idx not in (3, 4, 7, 8):
            ws.merge_cells(start_row=6, start_column=col_idx, end_row=7, end_column=col_idx)

    # Dòng 8+: Dữ liệu từng lệnh kế hoạch
    for idx, p in enumerate(plans, start=1):
        r_idx = 7 + idx
        is_dong = (p.order_type or "").lower() == "dong"
        is_20 = str(p.container_size or "").startswith("20")
        is_40 = str(p.container_size or "").startswith(("40", "45"))
        weight_val = float(p.cargo_weight) if p.cargo_weight is not None else None

        note_parts = []
        if p.order_code:
            note_parts.append(p.order_code)
        if p.booking_no:
            note_parts.append(f"BK:{p.booking_no}")
        if p.bill_of_lading_no:
            note_parts.append(f"BL:{p.bill_of_lading_no}")
        if p.notes:
            note_parts.append(p.notes)
        combined_note = " | ".join(note_parts) if note_parts else None

        row_values = [
            p.stt if p.stt is not None else idx,
            p.route_name,
            1 if is_dong else None,
            1 if not is_dong else None,
            p.container_no,
            p.seal_no,
            1 if is_20 else None,
            1 if is_40 else None,
            weight_val,
            p.required_time,
            p.customer_name,
            p.cargo_type,
            p.vessel_voyage,
            p.empty_depot,
            p.full_depot,
            p.estimated_drop_time,
            p.fleet_partner or p.carrier_name,
            _format_truck_cell(p),
            p.delivery_address or p.address,
            (p.group_id or DEFAULT_GROUP_ID),
            p.operator_staff or p.forwarder_name,
            combined_note,
            p.extra_fee_notes,
        ]
        for col_idx, val in enumerate(row_values, start=1):
            cell = ws.cell(r_idx, col_idx, val)
            cell.font = regular_font
            cell.border = cell_border
            if col_idx in (1, 3, 4, 7, 8, 10):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(vertical="center", wrap_text=(col_idx == 19))

    # Độ rộng cột gọn gàng
    col_widths = {
        1: 6, 2: 24, 3: 7, 4: 7, 5: 15, 6: 16, 7: 6, 8: 6,
        9: 14, 10: 14, 11: 20, 12: 20, 13: 20, 14: 14, 15: 14,
        16: 16, 17: 20, 18: 18, 19: 46, 20: 24, 21: 16, 22: 28, 23: 18,
    }
    for c_idx, width in col_widths.items():
        col_letter = openpyxl.utils.get_column_letter(c_idx)
        ws.column_dimensions[col_letter].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
