# =============================================================================
# Dockerfile cho Backend FastAPI (VSICO Zalo Bot & TMS Integration)
# Base: Python 3.12-slim
# Cổng dịch vụ: 8000
# Context: Root monorepo (.)
# =============================================================================

FROM python:3.12-slim

# Thiết lập biến môi trường hệ thống
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# Cài đặt các gói hệ thống cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt dependencies từ pyproject.toml
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy mã nguồn backend
COPY backend/alembic.ini backend/run.py ./
COPY backend/migrations ./migrations
COPY backend/scripts ./scripts
COPY backend/src ./src

# Expose cổng ứng dụng
EXPOSE 8000

# Kiểm tra sức khỏe dịch vụ
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Lệnh khởi chạy Uvicorn server
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
