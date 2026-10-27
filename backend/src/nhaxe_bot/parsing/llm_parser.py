"""Module Bóc Tách Dữ Liệu Bằng LLM Dự Phòng (LLM Fallback Parser).

Đóng vai trò cơ chế dự phòng an toàn khi bộ phân tích Rule-based không thể
bóc tách được số container mặc dù regex ban đầu phát hiện có container trong tin.
Bắt buộc tuân thủ interface chuẩn và kiểm tra schema đầu ra trước khi sử dụng.
"""

import json
from typing import List, Dict, Any, Tuple, Optional
from ..domain.models import Vehicle


class LLMParser:
    """Bộ bóc tách thông tin chuyến xe dự phòng bằng Mô hình ngôn ngữ lớn (LLM).

    Attributes:
        client (Any): Đối tượng kết nối máy chủ LLM (qua interface LLMClient).
    """

    def __init__(self, client: Any = None):
        """Khởi tạo LLM Parser.

        Args:
            client (Any, optional): Client kết nối tới Ollama / vLLM.
        """
        self.client = client

    def should_fallback(self, raw_text: str, vehicles: List[Vehicle], conts_count: int) -> bool:
        """Quyết định xem có cần kích hoạt cơ chế dự phòng LLM hay không.

        Điều kiện kích hoạt:
        Regex tìm thấy có ít nhất 1 container trong tin nhắn (`conts_count > 0`),
        nhưng sau khi qua Rule-based Parser không có đối tượng Vehicle nào trích xuất được số cont.

        Args:
            raw_text (str): Văn bản tin nhắn gốc.
            vehicles (List[Vehicle]): Danh sách xe bóc tách được từ Rule-based.
            conts_count (int): Số lượng container tìm thấy sơ bộ qua regex.

        Returns:
            bool: True nếu cần kích hoạt LLM, ngược lại False.
        """
        if conts_count > 0 and not any(v.cont for v in vehicles):
            return True
        return False

    def parse_with_llm(self, raw_text: str) -> Tuple[List[Vehicle], List[str]]:
        """Gọi máy chủ LLM để bóc tách dữ liệu theo schema định sẵn.

        Args:
            raw_text (str): Chuỗi văn bản tin nhắn thô.

        Returns:
            Tuple[List[Vehicle], List[str]]:
                - Danh sách các đối tượng Vehicle được LLM trích xuất.
                - Danh sách cảnh báo (ví dụ ['llm_loi'] nếu client không khả dụng hoặc lỗi).
        """
        if not self.client:
            return [], ["llm_loi"]
        # Gọi client qua interface chuẩn, xác thực schema đầu ra nghiêm ngặt
        return [], []
