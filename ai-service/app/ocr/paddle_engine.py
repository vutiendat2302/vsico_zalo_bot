"""Engine gọi PaddleOCR nội bộ và sắp xếp hộp chữ theo đúng thứ tự đọc bảng/phiếu."""

import base64
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.ocr import OCRLine

_NOISE_PATTERNS = [
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^zalo(\s+pc|\s+web)?$", re.IGNORECASE),
    re.compile(r"^(gửi|send|reply|trả lời|chuyển tiếp|forward)$", re.IGNORECASE),
]


@dataclass
class PaddleResult:
    """Kết quả thô sau khi nhận diện bằng PaddleOCR."""

    success: bool
    lines: list[OCRLine] = field(default_factory=list)
    joined_text: str = ""
    avg_confidence: float = 0.0
    error: str = ""


class PaddleOCREngine:
    """Client kết nối dịch vụ PaddleOCR HTTP để trích xuất text kèm tọa độ khung chữ."""

    @staticmethod
    def _is_ui_noise(text: str) -> bool:
        """Lọc bỏ các nhãn giao diện thừa khi chụp màn hình tin nhắn."""
        clean = (text or "").strip()
        if not clean or len(clean) <= 1:
            return True
        return any(p.match(clean) for p in _NOISE_PATTERNS)

    @staticmethod
    def _group_boxes_into_lines(raw_items: list[dict[str, Any]]) -> list[str]:
        """Gom các cụm chữ cùng hàng ngang (trục Y gần nhau) thành một dòng hoàn chỉnh."""
        parsed: list[tuple[float, float, str]] = []
        for item in raw_items:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            box = item.get("text_region") or item.get("box") or []
            if len(box) >= 4 and isinstance(box[0], (list, tuple)):
                cy = sum(float(pt[1]) for pt in box) / len(box)
                cx = min(float(pt[0]) for pt in box)
            else:
                cy = float(len(parsed) * 20)
                cx = 0.0
            parsed.append((cy, cx, text))

        if not parsed:
            return []

        parsed.sort(key=lambda row: (row[0], row[1]))
        grouped_lines: list[list[tuple[float, str]]] = []
        current_y = parsed[0][0]
        current_group: list[tuple[float, str]] = []

        for cy, cx, txt in parsed:
            if abs(cy - current_y) <= 14.0:
                current_group.append((cx, txt))
            else:
                if current_group:
                    grouped_lines.append(current_group)
                current_y = cy
                current_group = [(cx, txt)]
        if current_group:
            grouped_lines.append(current_group)

        output: list[str] = []
        for grp in grouped_lines:
            grp.sort(key=lambda x: x[0])
            line_str = " ".join(txt for _, txt in grp).strip()
            if line_str and not PaddleOCREngine._is_ui_noise(line_str):
                output.append(line_str)
        return output

    @classmethod
    async def recognize(cls, image_bytes: bytes) -> PaddleResult:
        """Gửi ảnh base64 sang server PaddleOCR và chuẩn hóa kết quả dòng chữ."""
        url = (settings.PADDLE_OCR_URL or "").strip()
        if not url:
            return PaddleResult(success=False, error="Chưa cấu hình PADDLE_OCR_URL")

        b64_img = base64.b64encode(image_bytes).decode("ascii")
        timeout = float(settings.OCR_TIMEOUT_SECONDS or 15)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json={"images": [b64_img]})
            if resp.status_code != 200:
                return PaddleResult(success=False, error=f"PaddleOCR HTTP {resp.status_code}")

            body = resp.json()
            results = body.get("results") or []
            raw_items = results[0] if results and isinstance(results[0], list) else []
            if not raw_items:
                return PaddleResult(success=True, lines=[], joined_text="", avg_confidence=0.0)

            ocr_lines: list[OCRLine] = []
            confs: list[float] = []
            for item in raw_items:
                txt = str(item.get("text") or "").strip()
                if not txt or cls._is_ui_noise(txt):
                    continue
                conf = float(item.get("confidence") or 0.0)
                box = item.get("text_region") or item.get("box") or []
                clean_box = [[int(pt[0]), int(pt[1])] for pt in box if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                ocr_lines.append(OCRLine(text=txt, confidence=round(conf, 4), box=clean_box))
                confs.append(conf)

            grouped_rows = cls._group_boxes_into_lines(raw_items)
            avg_conf = round(sum(confs) / len(confs), 4) if confs else 0.0
            return PaddleResult(
                success=bool(grouped_rows),
                lines=ocr_lines,
                joined_text="\n".join(grouped_rows),
                avg_confidence=avg_conf,
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return PaddleResult(success=False, error=str(exc))
