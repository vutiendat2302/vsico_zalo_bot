"""Sắp xếp thứ tự đọc và tái tạo dòng/cột từ kết quả bounding box PaddleOCR."""

import re
from typing import Any

from app.ocr.layout_analyzer import BoxToken, LayoutAnalysisResult, extract_box_tokens

_NOISE_PATTERNS = [
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^zalo(\s+pc|\s+web)?$", re.IGNORECASE),
    re.compile(r"^(gửi|send|reply|trả lời|chuyển tiếp|forward)$", re.IGNORECASE),
]


def is_ui_noise(text: str) -> bool:
    """Lọc bỏ nhãn giao diện thừa khi chụp màn hình tin nhắn Zalo."""
    clean = (text or "").strip()
    if not clean or len(clean) <= 1:
        return True
    return any(p.match(clean) for p in _NOISE_PATTERNS)


class ReadingOrder:
    """Gom cụm bounding box theo chiều dọc/ngang động và giữ ranh giới cột cho bảng."""

    @staticmethod
    def reconstruct(
        raw_items: list[dict[str, Any]],
        layout: LayoutAnalysisResult,
    ) -> list[str]:
        """Tái tạo danh sách dòng văn bản theo đúng thứ tự đọc từ trên xuống, trái sang phải."""
        tokens = [t for t in extract_box_tokens(raw_items) if not is_ui_noise(t.text)]
        if not tokens:
            return []

        tokens.sort(key=lambda t: (t.y_center, t.x_min))
        rows: list[list[BoxToken]] = []
        current_row: list[BoxToken] = []
        current_y = tokens[0].y_center

        for tok in tokens:
            if abs(tok.y_center - current_y) <= layout.row_y_threshold:
                current_row.append(tok)
                current_y = sum(t.y_center for t in current_row) / len(current_row)
            else:
                if current_row:
                    rows.append(sorted(current_row, key=lambda t: t.x_min))
                current_row = [tok]
                current_y = tok.y_center
        if current_row:
            rows.append(sorted(current_row, key=lambda t: t.x_min))

        lines_out: list[str] = []
        for row in rows:
            row.sort(key=lambda t: t.x_min)
            if layout.layout_type == "table":
                parts: list[str] = [row[0].text]
                for prev, nxt in zip(row, row[1:]):
                    sep = " | " if (nxt.x_min - prev.x_max) > layout.col_x_gap_threshold else " "
                    parts.append(f"{sep}{nxt.text}")
                line_str = "".join(parts).strip()
            else:
                line_str = " ".join(t.text for t in row).strip()

            if line_str and not is_ui_noise(line_str):
                lines_out.append(line_str)
        return lines_out
