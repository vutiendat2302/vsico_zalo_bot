# =============================================================================
# Dockerfile cho AI & OCR Microservice (VSICO Zalo Bot)
# Base: Python 3.12-slim
# Cổng dịch vụ: 8001
# Context: Root monorepo (.)
# =============================================================================

FROM python:3.12-slim

# Thiết lập biến môi trường hệ thống
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8001

WORKDIR /app

# Cài đặt các gói hệ thống cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt dependencies từ pyproject.toml
COPY ai-service/pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy mã nguồn ai-service
COPY ai-service/app ./app

# Expose cổng ứng dụng
EXPOSE 8001

# Kiểm tra sức khỏe dịch vụ
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Lệnh khởi chạy Uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
