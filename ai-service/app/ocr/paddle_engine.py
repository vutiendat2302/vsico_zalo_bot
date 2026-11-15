"""Engine gọi PaddleOCR nội bộ kết hợp phân tích bố cục và sắp xếp thứ tự đọc."""

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.ocr.layout_analyzer import LayoutAnalysisResult, LayoutAnalyzer
from app.ocr.reading_order import ReadingOrder, is_ui_noise
from app.schemas.ocr import OCRLine


@dataclass
class PaddleResult:
    """Kết quả sau khi nhận diện PaddleOCR và phân tích bố cục hình học."""

    success: bool
    lines: list[OCRLine] = field(default_factory=list)
    joined_text: str = ""
    avg_confidence: float = 0.0
    layout: LayoutAnalysisResult = field(default_factory=LayoutAnalysisResult)
    error: str = ""


class PaddleOCREngine:
    """Client kết nối dịch vụ PaddleOCR HTTP để trích xuất text kèm tọa độ khung chữ."""

    @staticmethod
    def _is_ui_noise(text: str) -> bool:
        """Lọc bỏ các nhãn giao diện thừa khi chụp màn hình tin nhắn."""
        return is_ui_noise(text)

    @staticmethod
    def _group_boxes_into_lines(
        raw_items: list[dict[str, Any]],
        layout: LayoutAnalysisResult | None = None,
    ) -> list[str]:
        """Gom các cụm chữ cùng hàng ngang theo ngưỡng động từ `LayoutAnalyzer`."""
        resolved_layout = layout or LayoutAnalyzer.analyze(raw_items)
        return ReadingOrder.reconstruct(raw_items, resolved_layout)

    @classmethod
    async def recognize(cls, image_bytes: bytes) -> PaddleResult:
        """Gửi ảnh base64 sang server PaddleOCR, phân tích bố cục và tái tạo dòng chữ."""
        url = (settings.PADDLE_OCR_URL or "").strip()
        if not url:
            return PaddleResult(success=False, error="Chưa cấu hình PADDLE_OCR_URL")

        b64_img = base64.b64encode(image_bytes).decode("ascii")
        timeout = float(settings.OCR_TIMEOUT_SECONDS or 15)
        headers: dict[str, str] = {}
        api_key = (settings.OCR_API_KEY or "").strip()
        if api_key:
            headers["X-API-Key"] = api_key
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json={"images": [b64_img]}, headers=headers)
            if resp.status_code != 200:
                return PaddleResult(success=False, error=f"PaddleOCR HTTP {resp.status_code}")

            body = resp.json()
            results = body.get("results") or []
            raw_items = results[0] if results and isinstance(results[0], list) else []
            if not raw_items:
                return PaddleResult(success=True, lines=[], joined_text="", avg_confidence=0.0)

            ocr_lines: list[OCRLine] = []
            confs: list[float] = []
            filtered_items: list[dict[str, Any]] = []
            for item in raw_items:
                txt = str(item.get("text") or "").strip()
                if not txt or cls._is_ui_noise(txt):
                    continue
                filtered_items.append(item)
                conf = float(item.get("confidence") or 0.0)
                box = item.get("text_region") or item.get("box") or []
                clean_box = [
                    [int(pt[0]), int(pt[1])]
                    for pt in box
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2
                ]
                ocr_lines.append(OCRLine(text=txt, confidence=round(conf, 4), box=clean_box))
                confs.append(conf)

            layout = LayoutAnalyzer.analyze(filtered_items)
            grouped_rows = ReadingOrder.reconstruct(filtered_items, layout)
            avg_conf = round(sum(confs) / len(confs), 4) if confs else 0.0
            return PaddleResult(
                success=bool(grouped_rows),
                lines=ocr_lines,
                joined_text="\n".join(grouped_rows),
                avg_confidence=avg_conf,
                layout=layout,
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return PaddleResult(success=False, error=str(exc))
