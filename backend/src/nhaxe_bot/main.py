import os
import sys
import json
import argparse
from queue import Queue
from http.server import HTTPServer
from typing import Dict, Any

from .config.settings import SETTINGS
from .domain.enums import Intent
from .domain.models import Carrier
from .ingestion.deduplicator import Deduplicator
from .ingestion.normalizer import IngestionNormalizer
from .infrastructure.repositories.shipping_repo import ShippingRepository
from .infrastructure.repositories.trip_repo import TripRepository
from .infrastructure.queue.publisher import QueuePublisher
from .infrastructure.queue.worker import QueueWorker
from .messaging.classifier.rule_based import RuleBasedClassifier
from .messaging.router import IntentRouter
from .outbound.templates import TemplateEngine
from .outbound.responder import OutboundResponder
from .handlers.create_trip import CreateTripHandler
from .handlers.update_driver import UpdateDriverHandler
from .handlers.cancel_trip import CancelTripHandler
from .handlers.supplement import SupplementHandler
from .handlers.unknown import UnknownHandler
from .api.webhook import WebhookController
from .api.app import create_http_handler

def build_application(shipping_file: str = SETTINGS.shipping_file) -> Dict[str, Any]:
    """Khởi tạo và cấu hình toàn bộ đồ thị phụ thuộc của hệ thống (Dependency Injection Container).

    Hàm này khởi tạo tất cả các thành phần theo đúng các tầng kiến trúc Clean Architecture:
    1. Infrastructure Repositories: Quản lý kế hoạch shipping, lịch sử chuyến xe và chống trùng lặp.
    2. Carriers Metadata: Ánh xạ cấu hình định danh các đội xe đối tác demo.
    3. Ingestion Layer: Bộ chuẩn hóa và bộ lọc payload tin nhắn từ Zalo OA.
    4. Outbound & Handlers: Bộ định tuyến mẫu tin phản hồi và các trình xử lý Use Case độc lập.
    5. Intent Classification & Routing: Phân loại ý định tin nhắn và điều phối tới handler phù hợp.
    6. Messaging Queue & Worker: Hàng đợi FIFO và công nhân xử lý tin nhắn ngầm.
    7. Webhook Gateway Controller: Cổng HTTP tiếp nhận webhook Zalo siêu nhẹ (Thin Gateway).

    Args:
        shipping_file (str, optional): Đường dẫn tới tệp dữ liệu kế hoạch vận chuyển CSV.
            Mặc định lấy từ `SETTINGS.shipping_file`.

    Returns:
        Dict[str, Any]: Từ điển chứa các thực thể đã được liên kết dependency đầy đủ:
            - shipping_repo: ShippingRepository
            - trip_repo: TripRepository
            - deduplicator: Deduplicator
            - normalizer: IngestionNormalizer
            - publisher: QueuePublisher
            - worker: QueueWorker
            - webhook_controller: WebhookController
            - template_engine: TemplateEngine
    """
    # 1. Repositories (Tầng ngoại vi lưu trữ)
    shipping_repo = ShippingRepository(shipping_file)
    trip_repo = TripRepository()
    deduplicator = Deduplicator()

    # 2. Carriers metadata (Danh bạ nhà xe đối tác demo)
    carriers_map = {
        "NX01": Carrier("NX01", "Vận tải Hải Long (demo)", "2001000000000000001", ["1001000000000000001", "1001000000000000002"]),
        "NX02": Carrier("NX02", "Vận tải Minh Phát (demo)", "2002000000000000001", ["1002000000000000001"]),
        "NX03": Carrier("NX03", "Vận tải Thành Đạt (demo)", "2003000000000000001", ["1003000000000000001"]),
        "NX04": Carrier("NX04", "Vận tải An Bình (demo)", "2004000000000000001", ["1004000000000000001"]),
    }

    # 3. Ingestion (Tầng tiếp nhận và chuẩn hóa dữ liệu thô)
    normalizer = IngestionNormalizer(carriers_map, deduplicator)

    # 4. Outbound & Handlers (Tầng trường hợp sử dụng nghiệp vụ)
    template_engine = TemplateEngine(SETTINGS.templates_dir)
    responder = OutboundResponder(template_engine)

    unknown_handler = UnknownHandler()
    create_handler = CreateTripHandler(shipping_repo, trip_repo, responder, SETTINGS.required_fields)
    update_handler = UpdateDriverHandler(trip_repo, template_engine)
    cancel_handler = CancelTripHandler()
    supplement_handler = SupplementHandler()

    # 5. Classifier & Router (Quy tắc 1.5: Mở rộng intent mới bằng cách thêm file mới, đăng ký 1 dòng)
    classifier = RuleBasedClassifier()
    router = IntentRouter(default_handler=unknown_handler)
    router.register(Intent.PARSE, create_handler)
    router.register(Intent.UPDATE_REQUEST, update_handler)
    router.register(Intent.CANCEL_REQUEST, cancel_handler)
    router.register(Intent.SUPPLEMENT, supplement_handler)
    router.register(Intent.ASK_WHICH_CONT, unknown_handler)
    router.register(Intent.MANUAL_REVIEW, unknown_handler)
    router.register(Intent.IGNORE_CHAT, unknown_handler)

    # 6. Queue & Worker (Hàng đợi tin nhắn và tiến trình công nhân an toàn)
    from .infrastructure.results_writer import ResultsWriter
    from .infrastructure.error_boundary import ErrorAlertThrottler
    from .messaging.classifier.junk_filter import SuspectMessageBuffer

    msg_queue = Queue()
    publisher = QueuePublisher(msg_queue)
    results_writer = ResultsWriter(SETTINGS.output_file)
    throttler = ErrorAlertThrottler()
    suspect_buffer = SuspectMessageBuffer()

    worker = QueueWorker(
        queue=msg_queue,
        classifier=classifier,
        router=router,
        results_writer=results_writer,
        throttler=throttler,
        suspect_buffer=suspect_buffer,
    )

    # 7. Webhook Controller (Cổng giao tiếp HTTP)
    webhook_controller = WebhookController(normalizer, publisher)

    return {
        "shipping_repo": shipping_repo,
        "trip_repo": trip_repo,
        "deduplicator": deduplicator,
        "normalizer": normalizer,
        "publisher": publisher,
        "worker": worker,
        "webhook_controller": webhook_controller,
        "template_engine": template_engine,
        "results_writer": results_writer,
        "throttler": throttler,
        "suspect_buffer": suspect_buffer,
    }

def run_server(port: int = 8000, shipping_file: str = SETTINGS.shipping_file) -> None:
    """Khởi động máy chủ HTTP API phục vụ cả Zalo Webhook và REST API chức năng.

    Hàm này ràng buộc cổng lắng nghe mạng, khởi tạo lớp điều hướng HTTP
    và in danh sách các điểm cuối API có sẵn ra màn hình bàn điều khiển.

    Args:
        port (int, optional): Cổng mạng máy chủ lắng nghe (mặc định là 8000).
        shipping_file (str, optional): Đường dẫn tệp CSV kế hoạch vận chuyển (mặc định lấy từ SETTINGS).

    Returns:
        None
    """
    app = build_application(shipping_file)
    handler_class = create_http_handler(
        app["webhook_controller"],
        app["worker"],
        app["trip_repo"],
        app.get("shipping_repo"),
        app.get("template_engine")
    )
    server = HTTPServer(("", port), handler_class)
    print("+-----------------------------------------------------------------------------+")
    print(f"| NHAXE-BOT SERVER (VSICO TMS) - LISTENING ON PORT {port:<27}|")
    print("+--------+------------------------------------+-------------------------------+")
    print("| METHOD | ENDPOINT                           | CHỨC NĂNG NGHIỆP VỤ           |")
    print("+--------+------------------------------------+-------------------------------+")
    print("| POST   | /webhook                           | Zalo Webhook Gateway          |")
    print("| POST   | /api/trips/new                     | Tạo chuyến xe mới (TMS REST)  |")
    print("| POST   | /api/trips/update-driver           | Đổi tài xế / số điện thoại    |")
    print("| POST   | /api/trips/supplement              | Bổ sung số seal / giờ đến     |")
    print("| POST   | /api/trips/cancel                  | Gửi yêu cầu hủy chuyến xe     |")
    print("| GET    | /api/trips                         | Tra cứu danh sách chuyến xe   |")
    print("| GET    | /api/shipping                      | Tra cứu danh mục shipping     |")
    print("| POST   | /api/shipping/mock-mode            | Bật/tắt Auto-Mock Shipping    |")
    print("| POST   | /api/shipping/new                  | Tạo đơn shipping động         |")
    print("| GET    | /api/health                        | Health check & Service metrics|")
    print("+--------+------------------------------------+-------------------------------+")
    print(f"[INFO] Server sẵn sàng nhận kết nối tại: http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Đã dừng máy chủ nhaxe-bot an toàn.")

def main() -> None:
    """Điểm khởi nhập chính của ứng dụng phân tích cú pháp dòng lệnh và kích hoạt máy chủ.

    Phân tích các cờ tham số cấu hình:
    - `--serve`: Bật chế độ phục vụ máy chủ HTTP API.
    - `--port`: Cổng lắng nghe mạng (mặc định: 8000).
    - `--shipping`: Tùy biến tệp kế hoạch vận chuyển CSV.
    """
    parser = argparse.ArgumentParser(description="Zalo GMF Bot - VSICO TMS Webhook & Functional REST API")
    parser.add_argument("--serve", action="store_true", help="Chạy máy chủ HTTP API")
    parser.add_argument("--port", type=int, default=8000, help="Cổng chạy server (mặc định: 8000)")
    parser.add_argument("--shipping", type=str, default=SETTINGS.shipping_file, help="Đường dẫn file shipping CSV")
    args = parser.parse_args()

    run_server(args.port, args.shipping)


if __name__ == "__main__":
    main()
