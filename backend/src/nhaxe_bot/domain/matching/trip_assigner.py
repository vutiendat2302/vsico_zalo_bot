"""Module Đối Soát Kế Hoạch Vận Chuyển (Shipping Trip Assigner).

Chịu trách nhiệm thực hiện logic đối soát chéo (Cross-check) giữa container
nhà xe báo với danh mục các lệnh vận chuyển trong kế hoạch của VSICO.
"""

from typing import Optional, Tuple, Dict
from ..models import Vehicle, ShippingOrder
from ..enums import MatchStatus


class TripAssigner:
    """Bộ gán và đối soát chuyến xe với kế hoạch Shipping của VSICO.

    Thực hiện kiểm tra 2 bước:
    1. Container có tồn tại trong danh mục lệnh vận chuyển đang hoạt động không?
    2. Đơn vị vận tải (Carrier) gửi tin có đúng là đơn vị được phân công chạy cuốc này không?
    """

    @staticmethod
    def match(
        vehicle: Vehicle,
        carrier_id: str,
        shipping_map: Dict[str, ShippingOrder],
    ) -> Tuple[MatchStatus, Optional[ShippingOrder]]:
        """Đối chiếu container của xe với danh bạ các lệnh vận chuyển (Shipping Map).

        Args:
            vehicle (Vehicle): Đối tượng xe đã qua bóc tách dữ liệu.
            carrier_id (str): Mã nhà xe gửi tin nhắn (ví dụ: 'NX01').
            shipping_map (Dict[str, ShippingOrder]): Từ điển ánh xạ từ số container sang lệnh vận chuyển.

        Returns:
            Tuple[MatchStatus, Optional[ShippingOrder]]:
                - (MatchStatus.NOT_FOUND, None): Nếu xe không có số cont hoặc cont không có trong shipping.
                - (MatchStatus.WRONG_CARRIER, ShippingOrder): Nếu cont có trong shipping nhưng giao cho nhà xe khác.
                - (MatchStatus.MATCH, ShippingOrder): Nếu khớp chính xác cả số cont và mã nhà xe.
        """
        # Nếu xe không có số container hợp lệ, không thể đối soát
        if not vehicle.cont:
            return MatchStatus.NOT_FOUND, None

        # Tra cứu container trong danh mục lệnh vận chuyển
        shp = shipping_map.get(vehicle.cont)
        if not shp:
            return MatchStatus.NOT_FOUND, None

        # Kiểm tra xem nhà xe gửi tin có khớp với nhà xe được phân công trong đơn hàng không
        if shp.nha_xe_id != carrier_id:
            return MatchStatus.WRONG_CARRIER, shp

        # Khớp chính xác hoàn toàn
        return MatchStatus.MATCH, shp
