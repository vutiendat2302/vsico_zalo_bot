"""Module Tích Hợp Nhận Diện Ký Tự Quang Học OCR (Optical Character Recognition).

Hỗ trợ bóc tách văn bản từ ảnh điều xe, lệnh đóng/trả cont do tài xế gửi qua Zalo
sử dụng mô hình PaddleOCR tự host (Self-Hosted Local PaddleOCR).
"""

from src.infrastructure.ocr.paddle_client import PaddleOCRClient

__all__ = ["PaddleOCRClient"]
