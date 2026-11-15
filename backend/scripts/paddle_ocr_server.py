#!/usr/bin/env python3
"""Máy chủ PaddleOCR 3.x tự host cục bộ.

Endpoints:
  POST /predict/ocr_system  (tương thích PaddleHub Serving)
  POST /ocr                 (REST đơn giản)
  GET  /health

Chạy: python scripts/paddle_ocr_server.py --port 8866
Biến môi trường (tùy chọn):
  OCR_API_KEY        nếu đặt, client phải gửi header X-API-Key
  OCR_MAX_SIDE       cạnh dài tối đa của ảnh (mặc định 2000)
  OCR_MAX_B64_CHARS  độ dài base64 tối đa (mặc định 14_000_000 ≈ 10MB ảnh)
"""

import argparse
import base64
import binascii
import logging
import os
import sys
import threading
from typing import Any, Optional

# Bỏ bước kiểm tra kết nối model hosting mỗi lần khởi động (hữu ích khi chạy offline/Docker)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2
import numpy as np
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("paddle_ocr_server")

API_KEY = os.getenv("OCR_API_KEY")
MAX_SIDE = int(os.getenv("OCR_MAX_SIDE", "4000"))
MAX_B64_CHARS = int(os.getenv("OCR_MAX_B64_CHARS", "28000000"))

app = FastAPI(
    title="VSICO Local Self-Hosted PaddleOCR Server",
    description="Máy chủ OCR tự host cục bộ phục vụ bóc tách ảnh tin nhắn nhà xe Zalo",
    version="1.1.0",
)

# ---------------------------------------------------------------------------
# Khởi tạo engine (PaddleOCR 3.x)
# ---------------------------------------------------------------------------
ocr_engine = None
_ocr_lock = threading.Lock()  # PaddleOCR không đảm bảo thread-safe


def _load_engine():
    """Khởi tạo và nạp mô hình PaddleOCR 3.x cho tiếng Việt (tắt oneDNN trên CPU)."""
    try:
        from paddleocr import PaddleOCR

        logger.info("Đang nạp PaddleOCR 3.x (lang='vi', enable_mkldnn=False)...")
        engine = PaddleOCR(
            lang="vi",
            use_doc_orientation_classify=False,  # tắt model xoay tài liệu (đỡ RAM/thời gian)
            use_doc_unwarping=False,             # tắt model nắn phẳng tài liệu
            use_textline_orientation=True,       # thay cho use_angle_cls của 2.x
            enable_mkldnn=False,                 # tắt oneDNN tránh lỗi PIR trên CPU
        )
        logger.info("Nạp PaddleOCR thành công.")
        return engine
    except ImportError:
        logger.error("Chưa cài 'paddleocr'/'paddlepaddle' (pip install paddlepaddle paddleocr).")
    except Exception:
        logger.exception("Lỗi khi nạp mô hình PaddleOCR")
    return None


ocr_engine = _load_engine()


# ---------------------------------------------------------------------------
# Schema & auth
# ---------------------------------------------------------------------------
class PaddleHubRequest(BaseModel):
    """Schema request tương thích với PaddleHub Serving."""

    images: list[str] = Field(default_factory=list, description="Danh sách ảnh base64")
    image: Optional[str] = Field(default=None, description="Một ảnh base64")


class OCRSimpleRequest(BaseModel):
    """Schema request REST đơn giản nhận một ảnh base64."""

    image_base64: Optional[str] = None


def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Xác thực API key tùy chọn qua header X-API-Key."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key không hợp lệ.")


# ---------------------------------------------------------------------------
# Xử lý ảnh + OCR
# ---------------------------------------------------------------------------
def _decode_image(b64_str: str) -> tuple[np.ndarray, list[str]]:
    """Giải mã chuỗi base64 thành ảnh BGR (numpy) và tiền xử lý tăng độ nét cho chữ nhỏ."""
    clean = (b64_str or "").strip()
    if len(clean) > MAX_B64_CHARS:
        raise HTTPException(status_code=413, detail="Ảnh quá lớn.")
    if clean.startswith("data:image/") and ";base64," in clean:
        clean = clean.split(";base64,", 1)[1].strip()
    try:
        raw = base64.b64decode(clean, validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Chuỗi base64 không hợp lệ.")

    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Không đọc được dữ liệu ảnh.")

    steps: list[str] = []
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        steps.append("downscale_oversize")
    elif w < 800 or h < 120:
        # Phóng to 2x ảnh screenshot nhỏ giúp PaddleOCR đọc chuẩn dấu tiếng Việt hơn
        img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        steps.append("upscale_2x_cubic")

    # Thêm viền trắng nhẹ tránh text detector bỏ sót chữ sát mép ảnh
    img = cv2.copyMakeBorder(img, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    steps.append("pad_border")
    return img, steps


def _perform_ocr(img_bgr: np.ndarray) -> list[dict[str, Any]]:
    """Thực thi nhận diện chữ PaddleOCR 3.x trên ảnh BGR với lock an toàn luồng."""
    if ocr_engine is None:
        raise HTTPException(status_code=503, detail="Mô hình PaddleOCR chưa sẵn sàng.")

    try:
        with _ocr_lock:
            results = ocr_engine.predict(img_bgr)  # 3.x: predict(), không dùng ocr()

        lines: list[dict[str, Any]] = []
        for res in results:  # mỗi phần tử ứng với một ảnh đầu vào
            texts = res["rec_texts"]
            scores = res["rec_scores"]
            polys = res["rec_polys"]
            for txt, score, poly in zip(texts, scores, polys):
                txt = str(txt).strip()
                if not txt:
                    continue
                lines.append({
                    "confidence": round(float(score), 4),
                    "text": txt,
                    "text_region": np.asarray(poly).tolist(),  # numpy -> list để JSON hóa
                })
        return lines
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Lỗi khi chạy OCR")
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý OCR: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check() -> dict[str, Any]:
    """Kiểm tra trạng thái sẵn sàng của mô hình PaddleOCR."""
    if ocr_engine is None:
        raise HTTPException(status_code=503, detail="Model chưa nạp.")
    return {"status": "UP", "engine": "paddleocr", "model_loaded": True, "lang": "vi"}


@app.post("/predict/ocr_system", dependencies=[Depends(verify_api_key)])
def predict_ocr_system(payload: PaddleHubRequest) -> dict[str, Any]:
    """Endpoint tương thích PaddleHub Serving nhận nhiều ảnh base64."""
    img_list = payload.images or ([payload.image] if payload.image else [])
    if not img_list:
        raise HTTPException(status_code=400, detail="Không có ảnh base64 trong payload.")

    all_results: list[list[dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    for idx, b64 in enumerate(img_list):
        try:
            img_bgr, _ = _decode_image(b64)
            all_results.append(_perform_ocr(img_bgr))
        except HTTPException as e:
            if e.status_code == 503:
                raise  # model chưa sẵn sàng: lỗi toàn cục
            all_results.append([])
            errors.append({"index": idx, "status_code": e.status_code, "detail": e.detail})

    return {
        "msg": "success" if not errors else "partial_failure",
        "results": all_results,
        "errors": errors,  # client phân biệt được "ảnh không có chữ" và "ảnh lỗi"
        "status": "000" if not errors else "001",
    }


@app.post("/ocr", dependencies=[Depends(verify_api_key)])
def ocr_endpoint(payload: OCRSimpleRequest) -> dict[str, Any]:
    """Endpoint REST đơn giản trả về đúng form chuẩn `OCRResponse` thống nhất với ai-service."""
    if not payload.image_base64:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp image_base64.")

    img_bgr, steps = _decode_image(payload.image_base64)
    raw_lines = _perform_ocr(img_bgr)
    formatted_lines = [
        {
            "text": item["text"],
            "confidence": item["confidence"],
            "box": item["text_region"],
        }
        for item in raw_lines
    ]
    avg_conf = (
        round(sum(item["confidence"] for item in formatted_lines) / len(formatted_lines), 4)
        if formatted_lines
        else 0.0
    )
    joined_text = "\n".join(item["text"] for item in formatted_lines)
    return {
        "engine": "paddleocr",
        "text": joined_text,
        "confidence": avg_conf,
        "lines": formatted_lines,
        "has_text": bool(joined_text.strip()),
        "layout_type": "unknown",
        "preprocessing_applied": steps,
        "error": None,
    }


def main():
    """Điểm khởi chạy CLI của máy chủ PaddleOCR."""
    parser = argparse.ArgumentParser(description="Chạy máy chủ PaddleOCR tự host cục bộ")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8866)
    args = parser.parse_args()

    if ocr_engine is None:
        logger.error("Model không nạp được, thoát để container restart/báo lỗi.")
        sys.exit(1)  # fail-fast thay vì sống mà vô dụng

    logger.info("Khởi chạy PaddleOCR Server tại http://%s:%d ...", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
