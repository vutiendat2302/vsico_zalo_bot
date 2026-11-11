"""Module Cấu Hình Hệ Thống & AI Provider Chung (Application & AI Settings).

Quản lý toàn bộ tham số môi trường từ tệp `.env` thông qua Pydantic Settings:
1. Thông số khởi chạy HTTP Server (`HOST`, `PORT`, `APP_ENV`).
2. Thông số kết nối cơ sở dữ liệu MySQL 8.4 (`DATABASE_URL`).
3. Cấu hình AI Fallback tập trung (`AI_ENABLED`, `AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY`,
   `AI_MODEL_NAME`) giúp dễ dàng chuyển đổi giữa OpenAI, Gemini, Claude, Ollama, vLLM
   chỉ bằng cách sửa file `.env` mà không cần sửa code.
"""

from datetime import timedelta, timezone
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

# Múi giờ chuẩn Việt Nam (GMT+7)
TZ_VN = timezone(timedelta(hours=7))

# Đường dẫn thư mục gốc của backend và thư mục gốc của toàn dự án (Monorepo Root)
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
ROOT_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
FALLBACK_ENV_PATH = os.path.join(BACKEND_ROOT, ".env")


class Settings(BaseSettings):
    """Lớp lưu trữ và xác thực toàn bộ cấu hình của hệ thống Backend VSICO Zalo Bot."""

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_PATH if os.path.exists(ROOT_ENV_PATH) else FALLBACK_ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Cấu hình Server
    APP_ENV: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # 2. Cấu hình MySQL 8.4
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "vsico_zalo_bot"
    DATABASE_URL: str = (
        "mysql+pymysql://root@127.0.0.1:3306/vsico_zalo_bot?charset=utf8mb4"
    )

    # 3. Cấu hình Zalo Webhook
    ZALO_APP_ID: str = "zca_personal_bot"
    ZALO_SECRET_KEY: str = ""

    # 4. Cấu hình AI Fallback Chung (Dễ dàng thay đổi Provider/Model qua .env)
    AI_ENABLED: bool = True
    AI_PROVIDER: str = "gemini"  # Hỗ trợ: gemini, openai_compatible, anthropic, ollama
    AI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    AI_API_KEY: str = ""
    AI_MODEL_NAME: str = "gemini-3.5-flash"
    AI_TIMEOUT_SECONDS: int = 10
    AI_FALLBACK_CONFIDENCE_THRESHOLD: float = 0.65

    # 5. Cấu hình Zalo Outbound Bridge (zca-js bot_api_server)
    ZALO_BRIDGE_URL: str = "http://localhost:3000"
    AUTO_DISPATCH_OUTBOUND: bool = True

    # 6. Cấu hình PaddleOCR Tự Host (Local Self-Hosted PaddleOCR)
    OCR_ENABLED: bool = True
    OCR_PROVIDER: str = "paddleocr"  # paddleocr hoặc gemini_vision
    PADDLE_OCR_URL: str = "http://127.0.0.1:8866/predict/ocr_system"
    OCR_TIMEOUT_SECONDS: int = 15
    OCR_LANG: str = "vi"  # Hỗ trợ: vi (Tiếng Việt), en, ch

    # 7. Cấu hình Snowflake ID 64-bit
    SNOWFLAKE_DATACENTER_ID: int = 1
    SNOWFLAKE_WORKER_ID: int = 1
    SNOWFLAKE_EPOCH_MS: int = 1704067200000

    # 8. Cấu hình Lưu trữ MinIO (S3-Compatible Object Storage)
    MINIO_ENDPOINT: str = "127.0.0.1:9000"
    MINIO_ROOT_USER: str = "minioadmin"
    MINIO_ROOT_PASSWORD: str = ""
    MINIO_BUCKET_NAME: str = "vsico-zalo-files"
    MINIO_SECURE: bool = False
    MINIO_PRESIGNED_EXPIRE_SECONDS: int = 3600

    # 9. Cấu hình Xác thực JWT & RBAC (ĐHVT & Admin Login)
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # 10. Cấu hình Tích hợp TMS (be-tms API)
    TMS_BASE_URL: str = "http://localhost:8080/api"
    TMS_USERNAME: str = ""
    TMS_PASSWORD: str = ""
    TMS_TIMEOUT_SECONDS: int = 15
    TMS_SYNC_ENABLED: bool = False

    # 11. Cấu hình AI Microservice Nội bộ (ai-service)
    AI_SERVICE_URL: str = "http://127.0.0.1:8001"
    INTERNAL_SECRET: str = ""


settings = Settings()
