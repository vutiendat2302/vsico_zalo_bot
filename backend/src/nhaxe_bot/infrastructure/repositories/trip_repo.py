"""Module Kho Lưu Trữ Chuyến Xe (Trip Repository).

Quản lý trạng thái và lưu trữ các chuyến xe đã được duyệt gửi thông báo khách hàng:
- Lưu trữ theo cặp khóa (carrier_id, container).
- Hỗ trợ cơ chế phiên bản chuyến xe (Versioning: version 1, 2, 3...).
- Hỗ trợ tra cứu ngược theo biển số xe (Reverse Plate Lookup) khi nhà xe đổi tài xế không ghi số cont.
"""

from typing import Dict, Tuple, Optional, List
from ...domain.models import SentTrip
from ...domain.rules import clean_plate


class TripRepository:
    """Kho lưu trữ trong bộ nhớ quản lý trạng thái và lịch sử các chuyến xe đã gửi."""

    def __init__(self):
        """Khởi tạo kho lưu trữ chuyến xe rỗng."""
        self._sent_trips: Dict[Tuple[str, str], SentTrip] = {}

    def get_trip(self, carrier_id: str, cont: str) -> Optional[SentTrip]:
        """Lấy bản ghi chuyến xe mới nhất của nhà xe theo số container.

        Args:
            carrier_id (str): Mã nhà xe.
            cont (str): Số hiệu container.

        Returns:
            Optional[SentTrip]: Chuyến xe tìm thấy hoặc None.
        """
        return self._sent_trips.get((carrier_id, cont))

    def save_trip(self, trip: SentTrip) -> SentTrip:
        """Lưu hoặc ghi đè một đối tượng SentTrip vào kho lưu trữ.

        Args:
            trip (SentTrip): Đối tượng chuyến xe cần lưu.

        Returns:
            SentTrip: Đối tượng chuyến xe vừa được lưu.
        """
        key = (trip.carrier_id, trip.cont)
        self._sent_trips[key] = trip
        return trip

    def record_trip(
        self,
        carrier_id: str,
        cont: str,
        shipping_id: Optional[str],
        xe_data: dict,
        notification_text: Optional[str],
        sent_at: str,
    ) -> SentTrip:
        """Ghi nhận chuyến xe mới hoặc tự động tăng số phiên bản (Version + 1) nếu chuyến đã tồn tại.

        Args:
            carrier_id (str): Mã nhà xe vận chuyển.
            cont (str): Số hiệu container.
            shipping_id (Optional[str]): Mã lệnh vận chuyển trong kế hoạch Shipping (nếu có).
            xe_data (dict): Dữ liệu chi tiết của xe tại thời điểm lưu.
            notification_text (Optional[str]): Nội dung thông báo đã gửi cho khách hàng.
            sent_at (str): Thời điểm ghi nhận gửi thông báo (ISO 8601).

        Returns:
            SentTrip: Đối tượng chuyến xe mới đã được đánh số phiên bản phù hợp.
        """
        key = (carrier_id, cont)
        version = 1
        # Nếu đã có chuyến xe cũ trong hệ thống, tự động nâng version lên 1 bậc
        if key in self._sent_trips:
            version = self._sent_trips[key].version + 1

        trip = SentTrip(
            carrier_id=carrier_id,
            cont=cont,
            shipping_id=shipping_id,
            xe_data=dict(xe_data),
            notification_text=notification_text,
            sent_at=sent_at,
            version=version,
        )
        self._sent_trips[key] = trip
        return trip

    def find_by_plate(self, carrier_id: str, raw_plate: str) -> List[SentTrip]:
        """Tìm kiếm các chuyến xe của một nhà xe khớp với biển số xe cơ giới (Tra cứu ngược).

        Đặc biệt hữu ích khi nhà xe nhắn tin đổi tài xế:
        'Xe 15C-878.99 đổi sang lái xe Lê Văn Đổi' (không nhắc tới số container).

        Args:
            carrier_id (str): Mã nhà xe gửi tin nhắn.
            raw_plate (str): Biển số xe thô cần tra cứu.

        Returns:
            List[SentTrip]: Danh sách các chuyến xe khớp với biển số xe đó.
        """
        target_plate = clean_plate(raw_plate)
        if not target_plate:
            return []

        matches = []
        for (c_id, cont), trip in self._sent_trips.items():
            if c_id == carrier_id:
                trip_plate = trip.xe_data.get("bien_so")
                if trip_plate and clean_plate(trip_plate) == target_plate:
                    matches.append(trip)
        return matches

    def list_all(self) -> List[SentTrip]:
        """Lấy danh sách toàn bộ các chuyến xe đang được lưu trữ trong bộ nhớ.

        Returns:
            List[SentTrip]: Danh sách tất cả các đối tượng SentTrip.
        """
        return list(self._sent_trips.values())

    def reset(self) -> None:
        """Xóa sạch toàn bộ dữ liệu trong kho (dùng cho môi trường Unit Test)."""
        self._sent_trips.clear()
