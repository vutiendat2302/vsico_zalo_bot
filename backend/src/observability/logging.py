"""Module Giám Sát & Nhật Ký Hệ Thống (Structured Observability & Logging).

Cung cấp bộ khởi tạo Logger chuẩn hóa kèm thời gian thực (GMT+7).
Lưu ý: Số điện thoại được giữ nguyên trong DB và log nội bộ; chỉ thực hiện che (`xxxx`)
khi gửi văn bản ra ngoài cho AI Provider (`src/parsing/ai_fallback.py`).
"""

from datetime import datetime
import logging
import re

from src.config.settings import TZ_VN, settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("vsico_zalo_bot")


def get_logger(name: str = "vsico_zalo_bot") -> logging.Logger:
    """Khởi tạo hoặc lấy thực thể Logger theo tên module.

    Args:
        name (str): Tên module gọi ghi log (thường truyền `__name__`).

    Returns:
        logging.Logger: Đối tượng Logger đã cấu hình.
    """
    return logging.getLogger(name)


def mask_phone_in_text(text: str) -> str:
    """Che 4 chữ số giữa của số điện thoại bằng `xxxx` CHỈ KHI gửi dữ liệu sang AI bên ngoài.

    Ví dụ: '0931142873' -> '0931xxxx73'.

    Args:
        text (str): Chuỗi văn bản cần che SĐT trước khi gửi cho AI.

    Returns:
        str: Chuỗi văn bản đã che SĐT thành dạng `09xx-xxxx-xx`.
    """
    if not text:
        return ""
    return re.sub(r"\b(0\d{3})\d{4}(\d{2})\b", r"\1xxxx\2", text)


def log_stage(stage: str, message: str, msg_id: str = "-") -> None:
    """Ghi một dòng nhật ký có cấu trúc ra màn hình điều khiển (Console).

    Args:
        stage (str): Tên giai đoạn xử lý ('INGEST', 'FIFO', 'PARSE', 'DB', 'ERROR').
        message (str): Nội dung chi tiết sự kiện.
        msg_id (str, optional): Mã định danh tin nhắn Zalo đang xử lý.
    """
    now_str = datetime.now(TZ_VN).strftime("%Y-%m-%d %H:%M:%S")
    logger.info("[%s] [%-8s] [msg:%s] %s", now_str, stage, msg_id, message)
