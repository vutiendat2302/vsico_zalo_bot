from datetime import datetime
from typing import Dict, Any
from ..config.settings import TZ_VN, SETTINGS

class HealthController:
    """Tầng giao tiếp điều khiển kiểm tra sức khỏe hệ thống (System Health Controller).

    Cung cấp trạng thái hoạt động thực tế của dịch vụ `nhaxe-bot`, phiên bản đang chạy,
    môi trường thực thi (development/production) và các số liệu thống kê cơ bản
    về số lượng tin nhắn đã tiêu thụ và số chuyến xe đã điều phối.
    """

    @staticmethod
    def get_health(total_processed: int, total_trips: int) -> Dict[str, Any]:
        """Tạo đối tượng phản hồi trạng thái sức khỏe và thông số đo lường của dịch vụ.

        Args:
            total_processed (int): Tổng số lượng tin nhắn webhook hợp lệ đã được tiếp nhận
                và khử trùng lặp qua bộ nhớ deduplicator.
            total_trips (int): Tổng số bản ghi chuyến xe hiện đang được lưu trữ trong kho dữ liệu TripRepository.

        Returns:
            Dict[str, Any]: Từ điển chứa thông tin chi tiết về tình trạng hệ thống:
                - status: 'UP' nếu dịch vụ đang sẵn sàng nhận yêu cầu.
                - service: Tên định danh dịch vụ.
                - version: Phiên bản ứng dụng hiện tại.
                - environment: Tên môi trường (development/staging/production).
                - server_time: Thời gian hiện tại của máy chủ theo múi giờ Việt Nam (ISO 8601).
                - metrics: Các chỉ số vận hành cơ bản (processed messages, sent trips).
        """
        return {
            "status": "UP",
            "service": "nhaxe-bot (VSICO TMS)",
            "version": "1.0.0",
            "environment": SETTINGS.app_env,
            "server_time": datetime.now(TZ_VN).isoformat(),
            "metrics": {
                "total_processed_messages": total_processed,
                "total_sent_trips": total_trips
            }
        }
