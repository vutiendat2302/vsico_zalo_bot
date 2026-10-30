"""Module Phân Tích & Import Kế Hoạch Vận Chuyển Hằng Ngày (Plan Importer).

Xử lý nạp dữ liệu kế hoạch vận chuyển từ file CSV hoặc Excel (.xlsx):
1. Tự động nhận diện cấu trúc bảng mẫu điều vận VSICO (tiêu đề ngày, hàng Xuất/Nhập).
2. Tự động nhận diện và phân loại Lệnh:
   - Cột Hàng 'Nhập' / 'I': Lệnh Trả hàng / Mở cont dỡ hàng (`order_type = "tra"`).
   - Cột Hàng 'Xuất' / 'X': Lệnh Đóng hàng (`order_type = "dong"`).
3. Tự động gán mặc định `group_id = "6469608867469758994"` cho toàn bộ các dòng chưa có group_id.
4. Chuẩn hóa số container, số seal, số xe dự kiến, địa chỉ giao nhận.
"""

import csv
from datetime import date, datetime
from decimal import Decimal
import io
import re
from typing import Any, Optional, Union

import openpyxl

from src.domain.rules import clean_container, clean_plate
from src.observability.logging import get_logger

logger = get_logger(__name__)

DEFAULT_GROUP_ID = "6469608867469758994"


class PlanFileParser:
    """Bộ phân tích cú pháp tệp Kế hoạch vận chuyển (Excel .xlsx & CSV)."""

    @classmethod
    def extract_plan_date_from_text(cls, text: str) -> Optional[date]:
        """Trích xuất ngày kế hoạch từ chuỗi tiêu đề (VD: 'KẾ HOẠCH VẬN CHUYỂN NGÀY 12/10/2026 (T2)').

        Args:
            text (str): Đoạn văn bản chứa ngày.

        Returns:
            Optional[date]: Đối tượng date hoặc None nếu không tìm thấy.
        """
        if not text:
            return None
        match = re.search(
            r"(?:ngày\s*|ngay\s*)?(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})",
            str(text),
            flags=re.IGNORECASE,
        )
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                pass
        return None

    @classmethod
    def parse_excel(
        cls,
        file_bytes: bytes,
        default_date: Optional[date] = None,
        default_group_id: str = DEFAULT_GROUP_ID,
    ) -> tuple[date, list[dict[str, Any]]]:
        """Đọc và bóc tách dữ liệu từ file Excel Kế hoạch vận chuyển (.xlsx).

        Args:
            file_bytes (bytes): Nội dung nhị phân của file Excel.
            default_date (Optional[date]): Ngày mặc định nếu file không có tiêu đề ngày.
            default_group_id (str): ID nhóm Zalo mặc định nếu dòng dữ liệu để trống.

        Returns:
            tuple[date, list[dict[str, Any]]]: Cặp (ngày kế hoạch, danh sách bản ghi kế hoạch).
        """
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheet = wb.active

        detected_date: Optional[date] = None

        # 1. Quét tìm tiêu đề ngày trong các dòng đầu tiên
        for r in range(1, 8):
            for c in range(1, 10):
                val = sheet.cell(r, c).value
                if val and "KẾ HOẠCH" in str(val).upper():
                    d = cls.extract_plan_date_from_text(str(val))
                    if d:
                        detected_date = d
                        break
            if detected_date:
                break

        effective_date = detected_date or default_date or date.today()

        # 2. Xác định dòng tiêu đề cột (thường là dòng 6 và 7)
        header_row_idx = 6
        for r in range(1, 15):
            row_vals = [str(sheet.cell(r, c).value or "").strip().lower() for c in range(1, 10)]
            if any("stt" in v for v in row_vals) and any("cont" in v for v in row_vals):
                header_row_idx = r
                break

        # Quét tên cột ở header_row_idx và dòng phụ (header_row_idx + 1)
        sub_header_row_idx = header_row_idx + 1

        col_map: dict[str, int] = {}
        for c in range(1, sheet.max_column + 1):
            h1 = str(sheet.cell(header_row_idx, c).value or "").strip()
            h2 = str(sheet.cell(sub_header_row_idx, c).value or "").strip()
            combined = f"{h1} {h2}".strip().lower()

            if "stt" in combined and "stt" not in col_map:
                col_map["stt"] = c
            elif "tuyến" in combined and "route_name" not in col_map:
                col_map["route_name"] = c
            elif ("hàng" in h1.lower() or "xuất" in h2.lower()) and "xuất" in h2.lower():
                col_map["col_xuat"] = c
            elif ("hàng" in h1.lower() or "nhập" in h2.lower()) and "nhập" in h2.lower():
                col_map["col_nhap"] = c
            elif "số cont" in combined or "cont" in combined:
                if "col_cont" not in col_map:
                    col_map["col_cont"] = c
            elif "seal" in combined and "col_seal" not in col_map:
                col_map["col_seal"] = c
            elif "20" in h2 and "col_size_20" not in col_map:
                col_map["col_size_20"] = c
            elif "40" in h2 and "col_size_40" not in col_map:
                col_map["col_size_40"] = c
            elif "tải trọng" in combined and "col_weight" not in col_map:
                col_map["col_weight"] = c
            elif "có mặt" in combined or "yc t.gian" in combined:
                col_map["col_time"] = c
            elif "khách hàng" in combined and "col_customer" not in col_map:
                col_map["col_customer"] = c
            elif "loại hàng" in combined and "col_cargo_type" not in col_map:
                col_map["col_cargo_type"] = c
            elif "c.tàu" in combined or "tàu" in combined:
                col_map["col_vessel"] = c
            elif "hạ vỏ" in combined or "nâng vỏ" in combined:
                col_map["col_empty_depot"] = c
            elif "hạ hàng" in combined or "nâng hàng" in combined:
                col_map["col_full_depot"] = c
            elif "giờ dự kiến" in combined or "dự kiến hạ" in combined:
                col_map["col_drop_time"] = c
            elif "đội xe" in combined and "col_fleet" not in col_map:
                col_map["col_fleet"] = c
            elif "số xe" in combined and "col_truck" not in col_map:
                col_map["col_truck"] = c
            elif "địa chỉ" in combined and "col_address" not in col_map:
                col_map["col_address"] = c
            elif ("group" in combined or "nhóm" in combined) and "col_group" not in col_map:
                col_map["col_group"] = c
            elif "giao nhận" in combined and "col_staff" not in col_map:
                col_map["col_staff"] = c
            elif ("chi chú" in combined or "ghi chú" in combined) and "col_notes" not in col_map:
                col_map["col_notes"] = c
            elif "phát sinh" in combined and "col_extra" not in col_map:
                col_map["col_extra"] = c

        # 3. Đọc dữ liệu từng dòng
        records: list[dict[str, Any]] = []
        data_start_row = sub_header_row_idx + 1

        for r in range(data_start_row, sheet.max_row + 1):
            stt_val = sheet.cell(r, col_map.get("stt", 1)).value
            cont_raw = sheet.cell(r, col_map.get("col_cont", 5)).value
            addr_raw = sheet.cell(r, col_map.get("col_address", 19)).value
            cust_raw = sheet.cell(r, col_map.get("col_customer", 11)).value

            # Bỏ qua dòng trống hoàn toàn
            if not stt_val and not cont_raw and not addr_raw and not cust_raw:
                continue

            cont_clean = clean_container(str(cont_raw)) if cont_raw else None

            # Nhận diện Lệnh Đóng (Xuất / 'X') hay Lệnh Trả (Nhập / 'I')
            xuat_val = sheet.cell(r, col_map.get("col_xuat", 3)).value if "col_xuat" in col_map else None
            nhap_val = sheet.cell(r, col_map.get("col_nhap", 4)).value if "col_nhap" in col_map else None

            if xuat_val is not None and str(xuat_val).strip() != "":
                order_type = "dong"
                cargo_io_type = "X"
            elif nhap_val is not None and str(nhap_val).strip() != "":
                order_type = "tra"
                cargo_io_type = "I"
            else:
                order_type = "tra"
                cargo_io_type = "I"

            # Kích thước container (20 hay 40)
            sz_20 = sheet.cell(r, col_map.get("col_size_20", 7)).value if "col_size_20" in col_map else None
            sz_40 = sheet.cell(r, col_map.get("col_size_40", 8)).value if "col_size_40" in col_map else None
            container_size = None
            if sz_20 is not None and str(sz_20).strip() != "":
                container_size = "20"
            elif sz_40 is not None and str(sz_40).strip() != "":
                container_size = "40"

            # Tải trọng
            weight_val = sheet.cell(r, col_map.get("col_weight", 9)).value if "col_weight" in col_map else None
            cargo_weight = None
            if weight_val is not None:
                try:
                    cargo_weight = Decimal(str(weight_val).strip())
                except Exception:
                    cargo_weight = None

            # Biển số xe dự kiến
            truck_raw = sheet.cell(r, col_map.get("col_truck", 18)).value if "col_truck" in col_map else None
            truck_str = str(truck_raw).strip() if truck_raw else None

            # Group ID (mặc định map vào default_group_id nếu trống)
            grp_val = sheet.cell(r, col_map.get("col_group", 20)).value if "col_group" in col_map else None
            final_group_id = str(grp_val).strip() if grp_val and str(grp_val).strip() else default_group_id

            stt_int = None
            if stt_val is not None:
                try:
                    stt_int = int(stt_val)
                except Exception:
                    stt_int = None

            record = {
                "plan_date": effective_date,
                "stt": stt_int,
                "route_name": str(sheet.cell(r, col_map.get("route_name", 2)).value or "").strip() or None,
                "cargo_io_type": cargo_io_type,
                "order_type": order_type,
                "container_no": cont_clean,
                "seal_no": str(sheet.cell(r, col_map.get("col_seal", 6)).value or "").strip() or None,
                "container_size": container_size,
                "cargo_weight": cargo_weight,
                "required_time": str(sheet.cell(r, col_map.get("col_time", 10)).value or "").strip() or None,
                "customer_name": str(sheet.cell(r, col_map.get("col_customer", 11)).value or "").strip() or None,
                "cargo_type": str(sheet.cell(r, col_map.get("col_cargo_type", 12)).value or "").strip() or None,
                "vessel_voyage": str(sheet.cell(r, col_map.get("col_vessel", 13)).value or "").strip() or None,
                "empty_depot": str(sheet.cell(r, col_map.get("col_empty_depot", 14)).value or "").strip() or None,
                "full_depot": str(sheet.cell(r, col_map.get("col_full_depot", 15)).value or "").strip() or None,
                "estimated_drop_time": str(sheet.cell(r, col_map.get("col_drop_time", 16)).value or "").strip() or None,
                "fleet_partner": str(sheet.cell(r, col_map.get("col_fleet", 17)).value or "").strip() or None,
                "planned_truck_plate": truck_str,
                "delivery_address": str(sheet.cell(r, col_map.get("col_address", 19)).value or "").strip() or None,
                "group_id": final_group_id,
                "operator_staff": str(sheet.cell(r, col_map.get("col_staff", 21)).value or "").strip() or None,
                "notes": str(sheet.cell(r, col_map.get("col_notes", 22)).value or "").strip() or None,
                "extra_fee_notes": str(sheet.cell(r, col_map.get("col_extra", 23)).value or "").strip() or None,
            }
            records.append(record)

        return effective_date, records

    @classmethod
    def parse_csv(
        cls,
        csv_text_or_bytes: Union[str, bytes],
        default_date: Optional[date] = None,
        default_group_id: str = DEFAULT_GROUP_ID,
    ) -> tuple[date, list[dict[str, Any]]]:
        """Đọc và bóc tách dữ liệu từ file CSV Kế hoạch vận chuyển.

        Hỗ trợ cả CSV dạng phẳng đơn dòng lẫn CSV xuất từ file Excel mẫu VSICO.

        Args:
            csv_text_or_bytes (Union[str, bytes]): Nội dung file CSV.
            default_date (Optional[date]): Ngày mặc định nếu file không có cột plan_date.
            default_group_id (str): ID nhóm Zalo mặc định nếu dòng dữ liệu để trống.

        Returns:
            tuple[date, list[dict[str, Any]]]: Cặp (ngày kế hoạch, danh sách bản ghi kế hoạch).
        """
        if isinstance(csv_text_or_bytes, bytes):
            content = csv_text_or_bytes.decode("utf-8-sig", errors="replace")
        else:
            content = str(csv_text_or_bytes)

        lines = [ln for ln in content.splitlines() if ln.strip()]
        if not lines:
            return default_date or date.today(), []

        # Tự động nhận diện dấu phân cách (, hoặc ; hoặc \t)
        sample = "\n".join(lines[:5])
        delimiter = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except Exception:
            if ";" in lines[0] and lines[0].count(";") > lines[0].count(","):
                delimiter = ";"
            elif "\t" in lines[0]:
                delimiter = "\t"

        reader = list(csv.reader(lines, delimiter=delimiter))

        detected_date: Optional[date] = None
        for row in reader[:5]:
            row_str = " ".join(row)
            if "KẾ HOẠCH" in row_str.upper() or "KE HOACH" in row_str.upper():
                d = cls.extract_plan_date_from_text(row_str)
                if d:
                    detected_date = d
                    break

        effective_date = detected_date or default_date or date.today()

        # Tìm dòng tiêu đề
        header_row_idx = 0
        for idx, row in enumerate(reader[:10]):
            joined = " ".join(row).lower()
            if any(k in joined for k in ("stt", "container", "số cont", "cont_no", "so cont")):
                header_row_idx = idx
                break

        headers = [h.strip().lower() for h in reader[header_row_idx]]

        records: list[dict[str, Any]] = []
        for row in reader[header_row_idx + 1 :]:
            if not any(row):
                continue
            row_dict = {
                headers[i]: row[i].strip()
                for i in range(min(len(headers), len(row)))
                if headers[i]
            }

            def _get(*keys: str) -> Optional[str]:
                for k in keys:
                    for hk, hv in row_dict.items():
                        if k in hk:
                            return hv if hv else None
                return None

            stt_raw = _get("stt", "no")
            stt_int = None
            if stt_raw:
                try:
                    stt_int = int(stt_raw)
                except ValueError:
                    stt_int = None

            cont_raw = _get("số cont", "so cont", "cont_no", "container", "cont")
            cont_clean = clean_container(cont_raw) if cont_raw else None

            # Nhận diện Lệnh Đóng hay Trả từ cột Hàng / cargo_io_type / order_type
            hang_raw = _get("hàng", "hang", "loại lệnh", "loai lenh", "io_type", "order_type", "xuất", "nhập")
            order_type = "tra"
            cargo_io_type = "I"

            if hang_raw:
                hr_lower = hang_raw.lower()
                if any(x in hr_lower for x in ("xuat", "xuất", "dong", "đóng", "x")):
                    order_type = "dong"
                    cargo_io_type = "X"
                elif any(x in hr_lower for x in ("nhap", "nhập", "tra", "trả", "i", "mở", "mo")):
                    order_type = "tra"
                    cargo_io_type = "I"

            sz_raw = _get("sl", "size", "kích cỡ", "kich co", "20", "40")
            container_size = None
            if sz_raw:
                if "40" in sz_raw:
                    container_size = "40"
                elif "20" in sz_raw:
                    container_size = "20"

            weight_raw = _get("tải trọng", "tai trong", "weight")
            cargo_weight = None
            if weight_raw:
                try:
                    cargo_weight = Decimal(re.sub(r"[^\d.]", "", weight_raw))
                except Exception:
                    cargo_weight = None

            grp_raw = _get("group_id", "group id", "group", "nhóm")
            final_group_id = grp_raw.strip() if grp_raw and grp_raw.strip() else default_group_id

            rec_date_raw = _get("plan_date", "ngày", "ngay")
            rec_date = effective_date
            if rec_date_raw:
                parsed_d = cls.extract_plan_date_from_text(rec_date_raw)
                if parsed_d:
                    rec_date = parsed_d

            record = {
                "plan_date": rec_date,
                "stt": stt_int,
                "route_name": _get("tuyến", "tuyen", "route"),
                "cargo_io_type": cargo_io_type,
                "order_type": order_type,
                "container_no": cont_clean,
                "seal_no": _get("seal", "chì", "chi"),
                "container_size": container_size,
                "cargo_weight": cargo_weight,
                "required_time": _get("thời gian", "thoi gian", "có mặt", "co mat", "time"),
                "customer_name": _get("khách hàng", "khach hang", "customer"),
                "cargo_type": _get("loại hàng", "loai hang", "hàng hóa", "hang hoa", "cargo"),
                "vessel_voyage": _get("tàu", "tau", "vessel", "voyage"),
                "empty_depot": _get("hạ vỏ", "nâng vỏ", "bãi vỏ", "empty"),
                "full_depot": _get("hạ hàng", "nâng hàng", "bãi hàng", "full"),
                "estimated_drop_time": _get("hạ hàng", "giờ hạ", "drop_time"),
                "fleet_partner": _get("đội xe", "doi xe", "carrier", "nhà xe"),
                "planned_truck_plate": _get("số xe", "so xe", "biển số", "plate"),
                "delivery_address": _get("địa chỉ", "dia chi", "kho", "address"),
                "group_id": final_group_id,
                "operator_staff": _get("giao nhận", "giao nhan", "staff"),
                "notes": _get("ghi chú", "ghi chu", "chi chú", "note"),
                "extra_fee_notes": _get("phát sinh", "phat sinh", "extra"),
            }
            records.append(record)

        return effective_date, records
