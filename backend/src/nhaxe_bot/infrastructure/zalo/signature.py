"""Module Xác Thực Chữ Ký Số Zalo Webhook (Zalo Signature Verification).

Chịu trách nhiệm kiểm tra tính toàn vẹn và nguồn gốc của dữ liệu sự kiện gửi đến từ Zalo OA
thông qua thuật toán mã hóa băm HMAC SHA-256.
"""

import hmac
import hashlib


def verify_zalo_signature(body: bytes, signature: str, secret_key: str) -> bool:
    """Xác thực chữ ký HMAC-SHA256 của Webhook gửi từ máy chủ Zalo.

    Args:
        body (bytes): Chuỗi byte nguyên bản của nội dung HTTP Request Body.
        signature (str): Chữ ký gửi kèm trong HTTP Header ('X-Zalo-Signature' hoặc 'Mac').
        secret_key (str): Khóa bí mật của Zalo OA (Zalo App Secret Key).

    Returns:
        bool: True nếu chữ ký hợp lệ hoặc bỏ qua trong môi trường dev/demo (khi secret_key trống),
              ngược lại False nếu chữ ký sai lệch.
    """
    # Bỏ qua xác thực chữ ký nếu cấu hình không đặt secret_key (môi trường dev / test offline)
    if not secret_key:
        return True
    if not signature:
        return False

    # Tính toán chữ ký băm kỳ vọng
    expected = hmac.new(secret_key.encode('utf-8'), body, hashlib.sha256).hexdigest()
    # So sánh an toàn chống tấn công Timing Attack
    return hmac.compare_digest(expected, signature)
