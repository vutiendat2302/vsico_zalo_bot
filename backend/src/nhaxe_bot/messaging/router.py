"""Module Định Tuyến Ý Định Xử Lý (Intent Router).

Thực hiện cơ chế định tuyến Use Case theo nguyên lý Open/Closed Principle (SOLID):
Mỗi Intent được gắn với một Handler chuyên biệt kế thừa BaseHandler.
Khi bổ sung Intent mới, chỉ cần đăng ký vào Router mà không làm sửa đổi luồng điều hướng cũ.
"""

from typing import Dict, List, Any, TYPE_CHECKING
from ..domain.enums import Intent
from ..ingestion.models import InboundMessage

if TYPE_CHECKING:
    from ..handlers.base import BaseHandler
else:
    BaseHandler = Any


class IntentRouter:
    """Bộ định tuyến thông điệp InboundMessage tới đúng Use Case Handler."""

    def __init__(self, default_handler: BaseHandler):
        """Khởi tạo Intent Router.

        Args:
            default_handler (BaseHandler): Handler mặc định dự phòng khi một Intent
                chưa được đăng ký xử lý (thường là UnknownHandler).
        """
        self._handlers: Dict[Intent, BaseHandler] = {}
        self._default_handler = default_handler

    def register(self, intent: Intent, handler: BaseHandler) -> "IntentRouter":
        """Đăng ký một handler mới xử lý cho một loại intent xác định.

        Args:
            intent (Intent): Loại ý định cần xử lý.
            handler (BaseHandler): Đối tượng use case handler thực thi logic nghiệp vụ.

        Returns:
            IntentRouter: Chính đối tượng router để hỗ trợ gọi hàm dạng chuỗi (fluent interface).
        """
        self._handlers[intent] = handler
        return self

    def dispatch(
        self,
        intent: Intent,
        inbound: InboundMessage,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Điều phối và ủy quyền xử lý thông điệp tới Handler tương ứng.

        Args:
            intent (Intent): Ý định đã được nhận diện từ bộ phân loại (Classifier).
            inbound (InboundMessage): Thông điệp nội bộ cần xử lý.
            context (Dict[str, Any]): Dữ liệu ngữ cảnh bổ sung (nhà xe, cài đặt).

        Returns:
            List[Dict[str, Any]]: Danh sách các bản ghi kết quả chuyến xe sau xử lý.
        """
        handler = self._handlers.get(intent, self._default_handler)
        return handler.handle(inbound, context)
