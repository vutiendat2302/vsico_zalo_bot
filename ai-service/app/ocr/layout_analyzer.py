"""Phân tích bố cục hình học từ bounding box để phân biệt ảnh chat, phiếu và bảng."""

import re
from dataclasses import dataclass
from statistics import median
from typing import Any

_TABLE_HEADER_PATTERN = re.compile(
    r"\b(biển\s*số|bien\s*so|tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|"
    r"số\s*cont|so\s*cont|container|số\s*chì|so\s*chi|seal|sđt|sdt|"
    r"địa\s*chỉ|dia\s*chi|kho|giờ|stt)\b",
    re.IGNORECASE,
)


@dataclass
class BoxToken:
    """Thông tin hình học chuẩn hóa của một cụm chữ OCR."""

    text: str
    confidence: float
    x_min: float
    x_max: float
    y_center: float
    height: float
    raw_box: list[list[int]]


@dataclass
class LayoutAnalysisResult:
    """Kết quả phân loại bố cục ảnh và ngưỡng gom dòng động."""

    layout_type: str = "chat_screenshot"
    row_count: int = 0
    estimated_columns: int = 1
    median_box_height: float = 20.0
    row_y_threshold: float = 14.0
    col_x_gap_threshold: float = 36.0
    is_complex_table: bool = False
    reason: str = "default_chat"


def extract_box_tokens(raw_items: list[dict[str, Any]]) -> list[BoxToken]:
    """Chuyển danh sách item thô từ PaddleOCR thành `BoxToken` có tọa độ chuẩn."""
    tokens: list[BoxToken] = []
    for idx, item in enumerate(raw_items):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        conf = float(item.get("confidence") or 0.0)
        box = item.get("text_region") or item.get("box") or []
        clean_box = [
            [int(pt[0]), int(pt[1])]
            for pt in box
            if isinstance(pt, (list, tuple)) and len(pt) >= 2
        ]
        if len(clean_box) >= 4:
            xs = [float(pt[0]) for pt in clean_box]
            ys = [float(pt[1]) for pt in clean_box]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            y_center = (y_min + y_max) / 2.0
            height = max(8.0, y_max - y_min)
        else:
            x_min = 0.0
            x_max = float(max(20, len(text) * 8))
            y_center = float(idx * 24 + 12)
            height = 20.0

        tokens.append(
            BoxToken(
                text=text,
                confidence=conf,
                x_min=x_min,
                x_max=x_max,
                y_center=y_center,
                height=height,
                raw_box=clean_box,
            )
        )
    return tokens


class LayoutAnalyzer:
    """Phân tích tọa độ hộp chữ để xác định bố cục bảng, phiếu hay ảnh tin nhắn."""

    @staticmethod
    def analyze(raw_items: list[dict[str, Any]]) -> LayoutAnalysisResult:
        """Tính ngưỡng Y/X động theo chiều cao chữ và phân loại cấu trúc tài liệu."""
        tokens = extract_box_tokens(raw_items)
        if not tokens:
            return LayoutAnalysisResult(layout_type="unknown", reason="empty_tokens")

        med_h = float(median(t.height for t in tokens))
        row_y_thresh = max(10.0, round(med_h * 0.55, 2))
        col_x_gap = max(24.0, round(med_h * 1.4, 2))

        sorted_tokens = sorted(tokens, key=lambda t: (t.y_center, t.x_min))
        rows: list[list[BoxToken]] = []
        current_row: list[BoxToken] = []
        current_y = sorted_tokens[0].y_center

        for tok in sorted_tokens:
            if abs(tok.y_center - current_y) <= row_y_thresh:
                current_row.append(tok)
                current_y = sum(t.y_center for t in current_row) / len(current_row)
            else:
                if current_row:
                    rows.append(sorted(current_row, key=lambda t: t.x_min))
                current_row = [tok]
                current_y = tok.y_center
        if current_row:
            rows.append(sorted(current_row, key=lambda t: t.x_min))

        col_counts: list[int] = []
        for row in rows:
            cols = 1
            for prev, nxt in zip(row, row[1:]):
                if nxt.x_min - prev.x_max > col_x_gap:
                    cols += 1
            col_counts.append(cols)

        max_cols = max(col_counts) if col_counts else 1
        multi_col_rows = sum(1 for c in col_counts if c >= 2)
        three_plus_col_rows = sum(1 for c in col_counts if c >= 3)
        joined_all = " ".join(t.text for t in tokens)
        has_table_header = len(_TABLE_HEADER_PATTERN.findall(joined_all)) >= 2

        if three_plus_col_rows >= 2 or (multi_col_rows >= 3 and has_table_header):
            is_complex = max_cols >= 3 or len(rows) >= 4
            return LayoutAnalysisResult(
                layout_type="table",
                row_count=len(rows),
                estimated_columns=max_cols,
                median_box_height=round(med_h, 2),
                row_y_threshold=row_y_thresh,
                col_x_gap_threshold=col_x_gap,
                is_complex_table=is_complex,
                reason=f"multi_col_rows={multi_col_rows},max_cols={max_cols}",
            )

        if multi_col_rows >= 2 or (len(rows) >= 3 and ":" in joined_all):
            return LayoutAnalysisResult(
                layout_type="slip",
                row_count=len(rows),
                estimated_columns=max_cols,
                median_box_height=round(med_h, 2),
                row_y_threshold=row_y_thresh,
                col_x_gap_threshold=col_x_gap,
                is_complex_table=False,
                reason="key_value_or_slip_layout",
            )

        return LayoutAnalysisResult(
            layout_type="chat_screenshot",
            row_count=len(rows),
            estimated_columns=max_cols,
            median_box_height=round(med_h, 2),
            row_y_threshold=row_y_thresh,
            col_x_gap_threshold=col_x_gap,
            is_complex_table=False,
            reason="single_column_or_chat",
        )
