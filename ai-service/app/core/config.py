"""Cấu hình môi trường cho phân hệ AI & OCR Microservice.

Đọc biến môi trường từ hệ thống hoặc tệp `.env` duy nhất tại thư mục gốc của dự án.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Lớp cấu hình tập trung cho AI Service."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[3] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Cấu hình máy chủ
    AI_SERVICE_HOST: str = "0.0.0.0"
    AI_SERVICE_PORT: int = 8001
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # 2. Bảo mật Zero-Trust nội bộ
    INTERNAL_SECRET: str = "vsico_internal_zero_trust_secret_2026"

    # 3. Kết nối Qdrant Vector DB
    QDRANT_URL: str = "http://127.0.0.1:6333"
    QDRANT_COLLECTION_WAREHOUSES: str = "vsico_warehouse_addresses"

    # 4. PaddleOCR & Vision
    PADDLE_OCR_URL: str = "http://127.0.0.1:8866/predict/ocr_system"
    OCR_TIMEOUT_SECONDS: int = 15
    OCR_LANG: str = "vi"

    # 5. Cấu hình AI Provider (Gemini / OpenAI)
    AI_PROVIDER: str = "gemini"
    AI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    AI_API_KEY: str = ""
    AI_MODEL_NAME: str = "gemini-3.5-flash"
    AI_TIMEOUT_SECONDS: int = 10
    AI_FALLBACK_CONFIDENCE_THRESHOLD: float = 0.65

    # 6. MinIO S3 Storage
    MINIO_ENDPOINT: str = "127.0.0.1:9000"
    MINIO_ROOT_USER: str = "minioadmin"
    MINIO_ROOT_PASSWORD: str = "minioadmin123"
    MINIO_BUCKET_NAME: str = "vsico-zalo-files"
    MINIO_SECURE: bool = False


settings = Settings()
