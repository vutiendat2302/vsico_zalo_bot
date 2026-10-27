"""Module Cấu hình Hệ thống (System Settings & Environment Configuration).

Chịu trách nhiệm nạp, xác thực và cung cấp toàn bộ các tham số cấu hình
từ biến môi trường (Environment Variables) hoặc giá trị mặc định cho toàn bộ
các tầng trong hệ thống nhaxe-bot.
"""

import os
from dataclasses import dataclass, field
from datetime import timezone, timedelta
from typing import List

# Múi giờ chuẩn Việt Nam (GMT+7) dùng xuyên suốt hệ thống để chuẩn hóa thời gian nhận tin
TZ_VN = timezone(timedelta(hours=7))

# Thư mục gốc của project (source/task2)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


@dataclass
class Settings:
    """Lớp lưu trữ toàn bộ tham số cấu hình của ứng dụng nhaxe-bot.

    Attributes:
        app_env (str): Môi trường chạy ứng dụng ('development', 'staging', 'production').
        port (int): Cổng lắng nghe của máy chủ HTTP REST & Webhook.
        host (str): Địa chỉ mạng ràng buộc của máy chủ.
        log_level (str): Mức độ ghi log ('DEBUG', 'INFO', 'WARNING', 'ERROR').
        zalo_app_id (str): Mã định danh ứng dụng Zalo OA (App ID).
        zalo_secret_key (str): Khóa bí mật dùng để xác thực chữ ký số webhook (HMAC SHA256).
        zalo_access_token (str): Mã truy cập Zalo OpenAPI để gửi tin nhắn outbound.
        use_llm (bool): Cờ bật/tắt chế độ dự phòng sử dụng Large Language Model.
        llm_base_url (str): Địa chỉ endpoint API của máy chủ LLM (Ollama, vLLM).
        llm_model (str): Tên mô hình ngôn ngữ cần sử dụng.
        llm_timeout (int): Thời gian chờ tối đa (giây) khi gọi tới LLM trước khi fallback.
        shipping_file (str): Đường dẫn tệp CSV chứa kế hoạch vận chuyển (Shipping Plan).
        messages_file (str): Đường dẫn tệp văn bản chứa dữ liệu webhook demo.
        expected_file (str): Đường dẫn tệp kết quả kỳ vọng dùng để đối soát benchmark.
        output_file (str): Đường dẫn tệp CSV lưu trữ kết quả xử lý đầu ra.
        templates_dir (str): Thư mục chứa các mẫu tin nhắn phản hồi khách hàng (.txt).
        required_fields (List[str]): Danh sách các trường dữ liệu bắt buộc của một chuyến xe hợp lệ.
    """

    app_env: str = os.getenv("APP_ENV", "development")
    port: int = int(os.getenv("PORT", "8000"))
    host: str = os.getenv("HOST", "0.0.0.0")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    zalo_app_id: str = os.getenv("ZALO_APP_ID", "1234567890123456789")
    zalo_secret_key: str = os.getenv("ZALO_SECRET_KEY", "")
    zalo_access_token: str = os.getenv("ZALO_ACCESS_TOKEN", "")

    use_llm: bool = os.getenv("USE_LLM", "false").lower() == "true"
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:7b")
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "20"))

    # File paths chuẩn theo cấu trúc mới
    shipping_file: str = os.getenv(
        "SHIPPING_FILE_PATH",
        os.path.join(PROJECT_ROOT, "tests", "fixtures", "shipping", "nhaxe_shipping_demo.csv"),
    )
    messages_file: str = os.getenv(
        "MESSAGES_FILE_PATH",
        os.path.join(PROJECT_ROOT, "tests", "fixtures", "messages", "nhaxe_messages_demo.txt"),
    )
    expected_file: str = os.getenv(
        "EXPECTED_FILE_PATH",
        os.path.join(PROJECT_ROOT, "tests", "fixtures", "messages", "nhaxe_messages_expected.txt"),
    )
    output_file: str = os.getenv(
        "OUTPUT_RESULTS_PATH",
        os.path.join(PROJECT_ROOT, "output", "results.csv"),
    )
    templates_dir: str = os.getenv(
        "TEMPLATES_DIR",
        os.path.join(os.path.dirname(__file__), "..", "outbound", "templates"),
    )

    required_fields: List[str] = field(
        default_factory=lambda: ["cont", "seal", "bien_so", "tai_xe", "sdt", "gio_den"]
    )


# Khởi tạo đối tượng cấu hình dùng chung (Singleton instance)
SETTINGS = Settings()
