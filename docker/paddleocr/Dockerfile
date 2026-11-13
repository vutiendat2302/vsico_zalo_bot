# =============================================================================
# Dockerfile cho PaddleOCR Server (Local Self-Hosted PaddleOCR)
# Cổng dịch vụ: 8866
# =============================================================================

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Cài đặt thư viện hệ thống cần thiết cho OpenCV, Pillow và Paddle
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt các gói phụ thuộc chạy máy chủ OCR
RUN pip install --no-cache-dir \
    fastapi>=0.110.0 \
    "uvicorn[standard]>=0.27.0" \
    pydantic>=2.0.0 \
    pillow>=10.0.0 \
    numpy>=1.24.0

# Copy mã nguồn máy chủ PaddleOCR
COPY backend/scripts/paddle_ocr_server.py ./server.py

EXPOSE 8866

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8866/health || exit 1

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8866"]
