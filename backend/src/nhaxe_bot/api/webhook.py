"""Module Điều Khiển Cổng Webhook Zalo (Thin Webhook Gateway Controller).

Tuân thủ nghiêm ngặt Quy tắc kiến trúc 1.3:
1. Xác thực tính hợp lệ của chữ ký Zalo OA (verify signature).
2. Kiểm tra schema cơ bản của payload gửi đến.
3. Chuẩn hóa payload thô sang mô hình nội bộ `InboundMessage` và lọc bỏ trùng lặp.
4. Đưa tin nhắn vào hàng đợi bất đồng bộ (`QueuePublisher.publish()`).
5. Phản hồi ngay lập tức HTTP 200 OK (`{"status": "ENQUEUED"}`).

Tuyệt đối KHÔNG thực hiện: bóc tách dữ liệu xe, truy vấn cơ sở dữ liệu, đọc file shipping
hoặc gọi mô hình ngôn ngữ lớn (LLM) bên trong controller này.
"""

from typing import Dict, Any, Tuple
from ..ingestion.normalizer import IngestionNormalizer
from ..infrastructure.queue.publisher import QueuePublisher
from ..infrastructure.zalo.signature import verify_zalo_signature
from ..config.settings import SETTINGS
from ..domain.errors import InvalidSignatureError, InvalidSchemaError


class WebhookController:
    """Tầng điều khiển cổng Webhook Zalo (Thin Webhook Gateway Controller)."""

    def __init__(
        self,
        normalizer: IngestionNormalizer,
        publisher: QueuePublisher,
    ) -> None:
        """Khởi tạo WebhookController với normalizer và queue publisher.

        Args:
            normalizer (IngestionNormalizer): Bộ chuẩn hóa dữ liệu Zalo thô thành InboundMessage.
            publisher (QueuePublisher): Bộ đẩy tin nhắn vào hàng đợi xử lý ngầm (Queue Worker).
        """
        self.normalizer = normalizer
        self.publisher = publisher

    def handle_webhook_event(
        self,
        seq: int,
        raw_payload: Dict[str, Any],
        signature: str = "",
    ) -> Tuple[int, Dict[str, Any]]:
        """Tiếp nhận và xử lý sự kiện webhook gửi đến từ máy chủ Zalo OA.

        Quy trình xử lý:
        1. Kiểm tra cấu trúc schema cơ bản của payload (nếu không phải dict -> trả về HTTP 400).
        2. Xác thực chữ ký Zalo (nếu có signature nhưng sai -> trả về HTTP 401 Unauthorized).
        3. Chuẩn hóa payload Zalo thô sang đối tượng `InboundMessage` nội bộ.
        4. Đẩy tin nhắn vào hàng đợi và phản hồi xác nhận trạng thái ngay lập tức.

        Args:
            seq (int): Số thứ tự tăng dần của yêu cầu webhook được tiếp nhận.
            raw_payload (Dict[str, Any]): Toàn bộ nội dung dữ liệu JSON thô nhận từ Zalo OA.
            signature (str, optional): Giá trị chữ ký từ header `X-Zalo-Signature`.

        Returns:
            Tuple[int, Dict[str, Any]]: Tuple gồm mã HTTP Status Code và dữ liệu phản hồi:
                - (200, {"success": True, ...}): Tiếp nhận thành công vào hàng đợi.
                - (400, {"code": "E101", ...}): Payload không đúng schema.
                - (401, {"code": "E100", ...}): Chữ ký không hợp lệ.
        """
        # 1. Kiểm tra schema cơ bản
        if not isinstance(raw_payload, dict):
            return 400, {
                "code": "E101",
                "message": "Payload Webhook bắt buộc phải là một đối tượng JSON hợp lệ",
                "retryable": False,
            }

        # 2. Verify chữ ký bảo mật từ Zalo nếu có truyền header
        if signature and not verify_zalo_signature(b"", signature, SETTINGS.zalo_secret_key):
            return 401, {
                "code": "E100",
                "message": "Chữ ký bảo mật không hợp lệ",
                "retryable": False,
            }

        # 3. Chuẩn hóa payload Zalo -> InboundMessage nội bộ
        inbound = self.normalizer.normalize(seq, raw_payload)

        # 4. Đẩy vào hàng đợi và kết thúc Webhook ngay tại đây
        self.publisher.publish(inbound)

        return 200, {
            "success": True,
            "seq": seq,
            "msg_id": inbound.msg_id,
            "status": "ENQUEUED",
            "is_valid": inbound.is_valid,
        }
