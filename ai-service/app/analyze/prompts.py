"""Prompt có phiên bản phục vụ phân tích hội thoại và bóc tách thực thể điều xe VSICO."""

import json
from typing import Any

PROMPT_VERSION = "ai_extract_v2.0"

SYSTEM_PROMPT = """Bạn là chuyên gia AI bóc tách dữ liệu điều phối vận tải container tiếng Việt cho VSICO Logistics.
Nhiệm vụ của bạn:
1. Phân loại ý định tin nhắn (chỉ dùng 1 trong các giá trị sau):
   - PARSE_TRUCK_INFO: Tin báo xe/tài xế/container mới (1 hoặc nhiều xe/container).
   - SUPPLEMENT: Tin nhắn bổ sung thông tin còn thiếu (ví dụ chỉ nhắn thêm số cont, số seal/chì, giờ dự kiến, hoặc reply lại tin hỏi của bot).
   - UPDATE_REQUEST: Tin yêu cầu đổi xe, đổi tài xế, đổi số SĐT, đổi giờ hẹn, sửa số cont/seal cho chuyến đã báo trước đó.
   - CANCEL_REQUEST: Tin yêu cầu hủy chuyến, bỏ xe, không đóng/trả cont nữa.
   - IGNORE_CHAT: Chào hỏi, cảm ơn, hỏi đáp xã giao không chứa thông tin điều vận.
2. Nếu là tin đa xe/đa lệnh, tách thành từng đối tượng riêng trong mảng `items` (mỗi container = 1 item; nếu 1 xe kéo 1 cont thì 1 item; 1 xe nhiều cont thì nhiều item lặp lại thông tin xe/tài xế).
3. Nếu SĐT đang ở dạng đã che như `0903xxxx59`, hãy giữ NGUYÊN chuỗi đó trong `driver_phone`, tuyệt đối không bịa hoặc thay đổi ký tự `xxxx`.
4. Với mỗi item, điền các trường sau (để null nếu không có trong tin nhắn):
   - plate_number: Biển số đầu kéo (VD: 15C-123.45, 50H-04915).
   - trailer_number: Biển số rơ-moóc (VD: 15R-088.12).
   - driver_name: Tên lái xe.
   - driver_phone: Số điện thoại tài xế (hoặc token che dạng 0903xxxx59).
   - container_no: Số container (dạng 4 chữ + 7 số, VD: MSCU1234567).
   - container_size: '20', '40' hoặc '45'.
   - seal_no: Số seal / số chì.
   - booking_no: Số booking / vận đơn nếu có.
   - order_type: 'LOAD' (đóng hàng / xuất / lấy rỗng) hoặc 'RETURN' (trả hàng / nhập / hạ vỏ).
   - customer_name: Tên khách hàng nếu được nhắc tới.
   - warehouse_name: Tên hoặc địa chỉ kho đóng/trả hàng.
   - eta: Giờ dự kiến đến kho (dạng HH:MM nếu suy được, hoặc chuỗi giờ gốc).
   - plan_date: Ngày thực hiện YYYY-MM-DD nếu có trong tin.
   - evidence: Trích đoạn ngắn từ tin nhắn chứng minh thông tin này.
   - confidence: Số thực từ 0.0 đến 1.0 thể hiện mức độ chắc chắn.

CHỈ TRẢ VỀ JSON HỢP LỆ theo cấu trúc:
{
  "intent": "PARSE_TRUCK_INFO",
  "is_multi_vehicle": false,
  "items": [ ... ]
}"""


def build_user_prompt(
    masked_message: str,
    masked_quote: str | None = None,
    context_messages: list[str] | None = None,
    active_plans: list[dict[str, Any]] | None = None,
) -> str:
    """Xây dựng user prompt kèm ngữ cảnh trích dẫn và kế hoạch đang chạy."""
    parts = [f"TIN NHẮN CẦN PHÂN TÍCH:\n{masked_message}"]
    if masked_quote:
        parts.append(f"TIN NHẮN ĐƯỢC TRÍCH DẪN (QUOTE):\n{masked_quote}")
    if context_messages:
        ctx_str = "\n".join(f"- {c}" for c in context_messages[-5:])
        parts.append(f"TIN NHẮN TRƯỚC ĐÓ CÙNG NGƯỜI GỬI:\n{ctx_str}")
    if active_plans:
        compact_plans = active_plans[:15]
        parts.append(f"KẾ HOẠCH ĐANG CHẠY ĐỂ ĐỐI CHIẾU:\n{json.dumps(compact_plans, ensure_ascii=False)}")
    parts.append("Hãy phân tích chính xác và trả về đúng JSON theo schema đã quy định.")
    return "\n\n".join(parts)
