"""Module Ranh Giới Bắt Lỗi Toàn Cục & Điều Tiết Cảnh Báo (Global Error Boundary & Throttler).

Thực hiện nhiệm vụ cốt lõi trong Phần 2:
- Hàm `run_safely(handler_fn, inbound, alert_fn, ...)`: Bọc an toàn việc xử lý từng tin nhắn,
  bảo đảm không để một tin nhắn cá biệt làm dừng hay sập hàng đợi Queue Worker.
- Chuyển đổi mọi ngoại lệ thành Action.ERROR kèm mã lỗi chuẩn (E1xx, E2xx, E3xx, E999).
- Luôn ghi một dòng trạng thái lỗi vào `results.csv`.
- Ghi nhật ký chi tiết kèm toàn bộ vết ngăn xếp (Stack Trace).
- Điều tiết cảnh báo Admin (`ErrorAlertThrottler`): Cùng một mã lỗi chỉ bắn cảnh báo một lần
  mỗi 5 phút (300s), kèm theo tổng số lần lỗi lặp lại trong khoảng thời gian đó.
"""

import time
import traceback
from typing import Callable, Dict, Any, List, Optional, Tuple
from ..domain.errors import CarrierBotError
from ..domain.enums import Intent
from ..ingestion.models import InboundMessage
from ..observability.logging import log_event, request_id_ctx
from .results_writer import ResultsWriter


class ErrorAlertThrottler:
    """Bộ điều tiết cảnh báo quản trị viên (Admin Alert Throttler).

    Ngăn chặn tình trạng tràn ngập cảnh báo (Alert Fatigue / Spam) khi một lỗi
    hạ tầng hoặc lỗi ngoại vi lặp lại liên tục:
    - Cùng một mã lỗi chỉ được phép kích hoạt cảnh báo quản trị một lần mỗi 5 phút (300s).
    - Tự động tích lũy và báo cáo số lần lặp lại (repetition count).
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        """Khởi tạo bộ điều tiết với độ dài cửa sổ thời gian (mặc định 5 phút = 300s).

        Args:
            window_seconds (float, optional): Thời gian cửa sổ tính bằng giây. Mặc định là 300.0s.
        """
        self.window_seconds = window_seconds
        # Lưu trữ: error_code -> (last_alert_time, accumulated_count)
        self._history: Dict[str, List[float]] = {}
        self._counts: Dict[str, int] = {}

    def record_and_should_alert(
        self, error_code: str, current_time: Optional[float] = None
    ) -> Tuple[bool, int]:
        """Ghi nhận lỗi phát sinh và xác định xem có nên kích hoạt cảnh báo Admin hay không.

        Args:
            error_code (str): Mã lỗi định danh (ví dụ: 'E300', 'E999').
            current_time (Optional[float], optional): Mốc thời gian hiện tại (Unix timestamp).

        Returns:
            Tuple[bool, int]:
                - should_alert (bool): True nếu cần bắn cảnh báo Admin, False nếu đang bị tiết lưu.
                - repetition_count (int): Số lần lỗi đã lặp lại tính từ lần cảnh báo trước.
        """
        now = current_time if current_time is not None else time.time()

        if error_code not in self._history:
            self._history[error_code] = [now]
            self._counts[error_code] = 1
            return True, 1

        last_alert_time = self._history[error_code][0]
        self._counts[error_code] += 1
        count = self._counts[error_code]

        if now - last_alert_time >= self.window_seconds:
            # Đã vượt quá 5 phút kể từ lần cảnh báo trước -> Cho phép cảnh báo kèm số lần lặp
            self._history[error_code] = [now]
            self._counts[error_code] = 1
            return True, count

        # Còn trong phạm vi 5 phút -> Tiết lưu (Throttle)
        return False, count

    def reset(self) -> None:
        """Xóa sạch lịch sử tiết lưu (dùng trong môi trường Unit Test)."""
        self._history.clear()
        self._counts.clear()


def run_safely(
    handler_fn: Callable[[InboundMessage], List[Dict[str, Any]]],
    inbound: InboundMessage,
    alert_fn: Optional[Callable[[str, str, int], None]] = None,
    results_writer: Optional[ResultsWriter] = None,
    throttler: Optional[ErrorAlertThrottler] = None,
) -> List[Dict[str, Any]]:
    """Bọc an toàn toàn bộ quá trình thực thi của một tin nhắn trong Queue Worker.

    Quy trình xử lý an toàn:
    1. Gọi thực thi logic của handler.
    2. Nếu có `CarrierBotError` (E1xx, E2xx, E3xx):
       - Trích xuất mã lỗi, thông điệp và stack trace.
       - Kiểm tra bộ điều tiết throttler; nếu thỏa mãn thì kích hoạt `alert_fn`.
       - Đóng gói bản ghi kết quả với `action = 'ERROR'`, `error_code`.
       - Ghi một dòng vào tệp `results.csv`.
    3. Nếu có `Exception` không lường trước (Unhandled Runtime Error):
       - Gán mã lỗi `E999`.
       - Trích xuất đầy đủ stack trace và log lỗi.
       - Điều tiết cảnh báo Admin.
       - Ghi một dòng vào tệp `results.csv`.
    4. Không để bất kỳ ngoại lệ nào làm sập tiến trình công nhân (Queue Worker).

    Args:
        handler_fn (Callable[[InboundMessage], List[Dict[str, Any]]]): Hàm thực thi xử lý tin nhắn.
        inbound (InboundMessage): Đối tượng thông điệp cần xử lý.
        alert_fn (Optional[Callable[[str, str, int], None]], optional): Hàm gửi cảnh báo tới Admin.
        results_writer (Optional[ResultsWriter], optional): Bộ ghi nhận kết quả ra `results.csv`.
        throttler (Optional[ErrorAlertThrottler], optional): Bộ điều tiết cảnh báo 5 phút.

    Returns:
        List[Dict[str, Any]]: Danh sách kết quả xử lý (nếu có lỗi trả về bản ghi lỗi Action.ERROR).
    """
    active_throttler = throttler or ErrorAlertThrottler()
    req_id = request_id_ctx.get() or ""

    try:
        results = handler_fn(inbound)
        # Ghi nhận kết quả thành công vào results.csv nếu có ResultsWriter
        if results_writer and results:
            for r in results:
                if "request_id" not in r or not r["request_id"]:
                    r["request_id"] = req_id
                if "error_code" not in r:
                    r["error_code"] = ""
            results_writer.write_rows(results)
        return results

    except CarrierBotError as cbe:
        code = cbe.code
        msg = cbe.message
        tb = traceback.format_exc()
        log_event("ERROR", f"CarrierBotError [{code}]: {msg}\n{tb}", msg_id=inbound.msg_id, request_id=req_id)

        should_alert, count = active_throttler.record_and_should_alert(code)
        if should_alert and alert_fn:
            alert_text = f"Cảnh báo hệ thống: Lỗi [{code}] - {msg} (xuất hiện {count} lần trong 5 phút)"
            alert_fn(code, alert_text, count)

        error_row = {
            "seq": inbound.seq,
            "msg_id": inbound.msg_id,
            "received_at": inbound.timestamp,
            "group_id": inbound.group_id,
            "sender_id": inbound.sender_id,
            "carrier_id": inbound.carrier_id,
            "action": Intent.ERROR.value,
            "status": "ERROR",
            "xe_index": 0,
            "admin_alert": True,
            "admin_message": f"Lỗi hệ thống [{code}]: {msg}",
            "reason": msg,
            "error_code": code,
            "request_id": req_id,
            "junk_verdict": getattr(inbound, "junk_verdict", ""),
            "junk_reason": getattr(inbound, "junk_reason", ""),
            "send_status": "FAILED",
            "parser_source": "error_boundary",
        }
        if results_writer:
            results_writer.write_row(error_row)
        return [error_row]

    except Exception as ex:
        code = "E999"
        msg = f"Ngoại lệ không lường trước: {str(ex)}"
        tb = traceback.format_exc()
        log_event("ERROR", f"Unhandled Exception [{code}]: {msg}\n{tb}", msg_id=inbound.msg_id, request_id=req_id)

        should_alert, count = active_throttler.record_and_should_alert(code)
        if should_alert and alert_fn:
            alert_text = f"Cảnh báo hệ thống: Lỗi nghiêm trọng [{code}] - {msg} (xuất hiện {count} lần trong 5 phút)"
            alert_fn(code, alert_text, count)

        error_row = {
            "seq": inbound.seq,
            "msg_id": inbound.msg_id,
            "received_at": inbound.timestamp,
            "group_id": inbound.group_id,
            "sender_id": inbound.sender_id,
            "carrier_id": inbound.carrier_id,
            "action": Intent.ERROR.value,
            "status": "ERROR",
            "xe_index": 0,
            "admin_alert": True,
            "admin_message": f"Ngoại lệ không lường trước [{code}]: {msg}",
            "reason": msg,
            "error_code": code,
            "request_id": req_id,
            "junk_verdict": getattr(inbound, "junk_verdict", ""),
            "junk_reason": getattr(inbound, "junk_reason", ""),
            "send_status": "FAILED",
            "parser_source": "error_boundary",
        }
        if results_writer:
            results_writer.write_row(error_row)
        return [error_row]
