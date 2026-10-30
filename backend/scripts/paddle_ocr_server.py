#!/usr/bin/env python3
"""Dịch Vụ Máy Chủ PaddleOCR Tự Host Cục Bộ (Local Self-Hosted PaddleOCR Server).

Cung cấp REST API nhận diện ký tự quang học (OCR) cho các hình ảnh điều xe / lệnh đóng trả cont:
1. Endpoint tương thích PaddleHub Serving: `POST /predict/ocr_system`
2. Endpoint REST trực tiếp: `POST /ocr`
3. Endpoint kiểm tra sức khỏe: `GET /health`

Khởi chạy độc lập bằng lệnh:
    python scripts/paddle_ocr_server.py --port 8866
Hoặc thông qua Docker:
    docker run -d -p 8866:8866 paddlepaddle/paddleocr:latest
"""

import argparse
import base64
import io
import logging
import sys
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("paddle_ocr_server")

app = FastAPI(
    title="VSICO Local Self-Hosted PaddleOCR Server",
    description="Máy chủ OCR tự host cục bộ phục vụ bóc tách ảnh tin nhắn nhà xe Zalo",
    version="1.0.0",
)

# Khởi tạo PaddleOCR engine nếu có thư viện
ocr_engine = None
try:
    from paddleocr import PaddleOCR
    logger.info("Đang khởi tạo mô hình PaddleOCR tiếng Việt (use_angle_cls=True, lang='vi')...")
    ocr_engine = PaddleOCR(use_angle_cls=True, lang="vi", show_log=False)
    logger.info("✅ Khởi tạo mô hình PaddleOCR thành công!")
except ImportError:
    logger.warning(
        "⚠️ Chưa cài đặt thư viện 'paddleocr' hoặc 'paddlepaddle'. "
        "Server sẽ chạy ở chế độ giả lập (Mock/Simulation). "
        "Để kích hoạt model thật: pip install paddlepaddle paddleocr"
    )
except Exception as e:
    logger.error("❌ Lỗi khi nạp mô hình PaddleOCR: %s", e)


class PaddleHubRequest(BaseModel):
    """Schema tương thích với PaddleHub Serving."""
    images: list[str] = Field(default_factory=list, description="Danh sách ảnh dạng base64")
    image: Optional[str] = Field(default=None, description="Chuỗi base64 của một ảnh")
    lang: Optional[str] = Field(default="vi", description="Ngôn ngữ OCR")


class OCRSimpleRequest(BaseModel):
    """Schema REST API đơn giản."""
    image_base64: Optional[str] = None
    image_url: Optional[str] = None
    lang: Optional[str] = "vi"


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Kiểm tra sức khỏe dịch vụ OCR."""
    return {
        "status": "UP",
        "engine": "paddleocr" if ocr_engine is not None else "mock_engine",
        "model_loaded": ocr_engine is not None,
        "default_lang": "vi",
    }


def _decode_base64_to_bytes(b64_str: str) -> bytes:
    """Giải mã chuỗi base64 thành bytes."""
    clean = b64_str.strip()
    if clean.startswith("data:image/") and ";base64," in clean:
        clean = clean.split(";base64,", 1)[1].strip()
    return base64.b64decode(clean)


def _perform_ocr(img_bytes: bytes) -> list[dict[str, Any]]:
    """Thực thi OCR trên bytes ảnh."""
    if ocr_engine is None:
        # Chế độ Mock nếu chưa cài đặt weights thực
        return [
            {
                "confidence": 0.95,
                "text": "Lệnh đóng hàng - KH: Logitem - Điểm đóng: Kho Logitem Tân Quang",
                "text_region": [[10, 10], [500, 10], [500, 40], [10, 40]],
            },
            {
                "confidence": 0.96,
                "text": "1 xe: 15C-878.99 / Vũ Tiến Đạt / 0903976359 / VSIU7399796 / 40HC / chì 73957169",
                "text_region": [[10, 50], [600, 50], [600, 80], [10, 80]],
            },
        ]

    try:
        from PIL import Image
        import numpy as np
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(image)
        result = ocr_engine.ocr(img_np, cls=True)

        boxes_out = []
        if result and len(result) > 0 and result[0] is not None:
            for line in result[0]:
                box = line[0]
                txt, score = line[1]
                boxes_out.append({
                    "confidence": round(float(score), 4),
                    "text": str(txt).strip(),
                    "text_region": box,
                })
        return boxes_out
    except Exception as e:
        logger.error("Lỗi khi chạy OCR trên ảnh: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý OCR: {e}")


@app.post("/predict/ocr_system")
def predict_ocr_system(payload: PaddleHubRequest) -> dict[str, Any]:
    """Endpoint tương thích PaddleHub Serving (`/predict/ocr_system`)."""
    img_list = payload.images or ([payload.image] if payload.image else [])
    if not img_list:
        raise HTTPException(status_code=400, detail="Không tìm thấy chuỗi base64 ảnh trong payload.")

    all_results = []
    for b64 in img_list:
        try:
            b = _decode_base64_to_bytes(b64)
            detected_lines = _perform_ocr(b)
            all_results.append(detected_lines)
        except Exception as e:
            logger.error("Lỗi giải mã hoặc xử lý ảnh: %s", e)
            all_results.append([])

    return {
        "msg": "success",
        "results": all_results,
        "status": "000",
    }


@app.post("/ocr")
def ocr_endpoint(payload: OCRSimpleRequest) -> dict[str, Any]:
    """Endpoint REST trực tiếp đơn giản hóa."""
    b64 = payload.image_base64
    if not b64:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp `image_base64`.")

    b = _decode_base64_to_bytes(b64)
    boxes = _perform_ocr(b)
    combined_text = "\n".join(b["text"] for b in boxes)
    avg_conf = (
        round(sum(b["confidence"] for b in boxes) / len(boxes), 3) if boxes else 0.0
    )

    return {
        "ok": True,
        "text": combined_text,
        "confidence": avg_conf,
        "lines_count": len(boxes),
        "lines": boxes,
    }


def main():
    parser = argparse.ArgumentParser(description="Chạy máy chủ PaddleOCR tự host cục bộ")
    parser.add_argument("--host", default="127.0.0.1", help="Host bind (Mặc định: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8866, help="Port lắng nghe (Mặc định: 8866)")
    args = parser.parse_args()

    logger.info("🚀 Khởi chạy PaddleOCR Server tại http://%s:%d ...", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
