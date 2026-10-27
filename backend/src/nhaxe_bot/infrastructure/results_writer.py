"""Module Ghi Kết Quả Xử Lý Ra Tệp CSV (Results CSV Writer).

Quản lý xuất bản bản ghi kết quả xử lý của toàn bộ các tin nhắn ra tệp `output/results.csv`,
bổ sung đầy đủ 4 cột trường thông tin mới theo yêu cầu Phần 3:
- `junk_verdict`: Kết quả phân loại rác ('JUNK', 'SUSPECT', 'CANDIDATE').
- `junk_reason`: Diễn giải nguyên nhân phân loại rác.
- `error_code`: Mã lỗi định danh (E1xx, E2xx, E3xx, E999 nếu có lỗi, ngược lại rỗng).
- `request_id`: Mã định danh yêu cầu HTTP liên kết.
"""

import csv
import os
from typing import Dict, Any, List, Optional

# Danh mục 35 cột dữ liệu đầy đủ của results.csv
RESULTS_CSV_FIELDS = [
    "seq", "msg_id", "received_at", "group_id", "sender_id", "carrier_id",
    "action", "xe_index", "loai_hint", "cont", "seal", "bien_so", "tai_xe",
    "sdt", "gio_den", "warnings", "status", "in_shipping", "join_result",
    "shipping_id", "khach_hang_id", "ten_khach_hang", "zalo_group_id_gui",
    "near_match_cont", "send_status", "notification_text", "reply_to_carrier",
    "admin_alert", "admin_message", "reason", "parser_source",
    "junk_verdict", "junk_reason", "error_code", "request_id"
]


class ResultsWriter:
    """Lớp ghi nhận kết quả xử lý tin nhắn ra tệp CSV có cấu trúc."""

    def __init__(self, file_path: str) -> None:
        """Khởi tạo ResultsWriter với đường dẫn tệp CSV đích.

        Args:
            file_path (str): Đường dẫn tuyệt đối hoặc tương đối tới tệp `results.csv`.
        """
        self.file_path = file_path
        self._ensure_header()

    def _ensure_header(self) -> None:
        """Đảm bảo thư mục cha tồn tại và ghi dòng tiêu đề (header) nếu tệp chưa có dữ liệu."""
        os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
        if not os.path.exists(self.file_path) or os.path.getsize(self.file_path) == 0:
            with open(self.file_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(RESULTS_CSV_FIELDS)

    def write_row(self, row_data: Dict[str, Any]) -> None:
        """Ghi một dòng kết quả vào tệp results.csv.

        Args:
            row_data (Dict[str, Any]): Dữ liệu kết quả xử lý của một chuyến xe hoặc thông điệp.
        """
        self.write_rows([row_data])

    def write_rows(self, rows_data: List[Dict[str, Any]]) -> None:
        """Ghi danh sách nhiều dòng kết quả vào tệp results.csv.

        Args:
            rows_data (List[Dict[str, Any]]): Danh sách các bản ghi kết quả xử lý.
        """
        if not rows_data:
            return

        with open(self.file_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for r in rows_data:
                row_vals = []
                for field in RESULTS_CSV_FIELDS:
                    val = r.get(field, "")
                    if val is None:
                        val = ""
                    elif isinstance(val, list):
                        val = ";".join(str(x) for x in val)
                    elif isinstance(val, bool):
                        val = "True" if val else "False"
                    row_vals.append(str(val))
                writer.writerow(row_vals)
