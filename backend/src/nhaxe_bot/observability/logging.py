"""Module Ghi Nhật Ký & Đo Lường Hệ Thống (Observability & Logging).

Cung cấp:
- Quản lý ngữ cảnh luồng xử lý với ContextVars (`request_id`, `msg_id`, `seq`).
- Che giấu thông tin cá nhân (PII Masking) cho số điện thoại theo quy chuẩn: giữ 3 số đầu và 3 số cuối.
- Định dạng nhật ký có cấu trúc không chứa biểu tượng emoji, đảm bảo giao diện console chuyên nghiệp.
- Hàm trợ giúp đóng gói phản hồi chuẩn `make_response_envelope`.
"""

import re
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Dict, Any, Optional

# Ngữ cảnh lưu trữ Request ID, Message ID và Sequence Number theo từng luồng xử lý
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
msg_id_ctx: ContextVar[str] = ContextVar("msg_id", default="")
seq_ctx: ContextVar[Optional[int]] = ContextVar("seq", default=None)


def mask_phone(text: str) -> str:
    """Che giấu số điện thoại di động trong chuỗi văn bản nhằm bảo vệ thông tin riêng tư.

    Quy tắc: Giữ lại 3 chữ số đầu và 3 chữ số cuối, thay thế các chữ số ở giữa bằng '***'.
    Ví dụ: '0903976359' -> '090***359', '+84903976359' -> '+849***359'.

    Args:
        text (str): Chuỗi văn bản có thể chứa số điện thoại.

    Returns:
        str: Chuỗi văn bản đã được che giấu số điện thoại.
    """
    if not text:
        return text

    # Che giấu số nội địa 10 chữ số (09xxxxxxxx)
    masked = re.sub(r'\b(0\d{2})\d{4}(\d{3})\b', r'\1***\2', str(text))
    # Che giấu số quốc tế (+84xxxxxxxxx): giữ +84 + 1 số đầu (+849) và 3 số cuối
    masked = re.sub(r'(\+84\d)\d{5}(\d{3})\b', r'\1***\2', masked)
    return masked


def log_event(
    step: str,
    message: str,
    msg_id: Optional[str] = None,
    seq: Optional[int] = None,
    request_id: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Ghi nhận sự kiện có cấu trúc (Structured Logging) với đầy đủ metadata và ContextVars.

    Tự động đính kèm `request_id`, `msg_id`, `seq` từ `ContextVar` hiện tại nếu không được
    truyền tường minh, đồng thời tự động che giấu số điện thoại trong nội dung log.

    Args:
        step (str): Giai đoạn xử lý (ví dụ: 'INGEST', 'CLASSIFY', 'DISPATCH', 'RESULT', 'ERROR').
        message (str): Nội dung thông báo log.
        msg_id (Optional[str], optional): ID tin nhắn Zalo liên kết. Mặc định đọc từ context.
        seq (Optional[int], optional): Thứ tự gói tin. Mặc định đọc từ context.
        request_id (Optional[str], optional): ID yêu cầu HTTP. Mặc định đọc từ context.
        **kwargs (Any): Dữ liệu bổ sung.
    """
    actual_req_id = request_id or request_id_ctx.get() or "N/A"
    actual_msg_id = msg_id or msg_id_ctx.get() or "N/A"
    actual_seq = seq if seq is not None else seq_ctx.get()
    seq_str = str(actual_seq) if actual_seq is not None else "N/A"

    safe_message = mask_phone(message)
    prefix = f"[{step:<8}] [req:{actual_req_id[:8]}] [seq:{seq_str}] [msg:{actual_msg_id[:12]}]"
    print(f"  {prefix} {safe_message}")


def make_response_envelope(
    ok: bool,
    data: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tạo cấu trúc vỏ bọc dữ liệu phản hồi (Response Envelope) chuẩn toàn cục.

    Định dạng phản hồi duy nhất cho toàn bộ hệ thống:
    ```json
    {
      "ok": bool,
      "data": { ... } | null,
      "error": { "code": str, "message": str, "retryable": bool } | null,
      "request_id": str
    }
    ```

    Args:
        ok (bool): Trạng thái thành công hay thất bại.
        data (Optional[Dict[str, Any]], optional): Dữ liệu payload nếu thành công.
        error (Optional[Dict[str, Any]], optional): Chi tiết lỗi nếu thất bại.
        request_id (Optional[str], optional): Mã định danh yêu cầu HTTP.

    Returns:
        Dict[str, Any]: Đối tượng từ điển tuân thủ định dạng envelope chuẩn.
    """
    req_id = request_id or request_id_ctx.get() or str(uuid.uuid4())
    return {
        "ok": bool(ok),
        "data": data if data is not None else None,
        "error": error if error is not None else None,
        "request_id": req_id,
    }
