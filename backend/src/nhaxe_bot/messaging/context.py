"""Module Phân Giải Ngữ Cảnh Tin Nhắn (Context Resolver).

Chịu trách nhiệm tra cứu và ánh xạ mã định danh nhóm Zalo GMF (group_id)
thành thực thể Đơn vị vận tải (Carrier) tương ứng.
"""

from typing import Dict, Optional
from ..domain.models import Carrier


class ContextResolver:
    """Bộ phân giải ngữ cảnh điều phối từ thông tin nhóm Zalo."""

    def __init__(self, carriers_map: Dict[str, Carrier]):
        """Khởi tạo bộ phân giải ngữ cảnh với danh mục nhà xe.

        Args:
            carriers_map (Dict[str, Carrier]): Từ điển lưu trữ danh bạ nhà xe theo carrier_id.
        """
        self.carriers_map = carriers_map

    def resolve_carrier(self, group_id: str) -> Optional[Carrier]:
        """Tìm kiếm đối tượng Carrier sở hữu mã nhóm Zalo được cung cấp.

        Args:
            group_id (str): Mã định danh nhóm Zalo GMF nhận tin.

        Returns:
            Optional[Carrier]: Đối tượng nhà xe nếu tìm thấy, ngược lại None.
        """
        for c in self.carriers_map.values():
            if c.group_id == group_id:
                return c
        return None
