"""Module Kiểm Thử Đơn Vị Bộ Bóc Tách Chuyến Xe (Trip Parser Unit Tests).

Kiểm tra chi tiết khả năng trích xuất và chuẩn hóa trường thông tin xe:
- Biển số xe viết dính liền tiền tố ('Xe15h00814' -> '15H00814').
- Họ tên tài xế dính phím được tách âm tiết và viết hoa Title Case ('phạm tiếnhưng' -> 'Phạm Tiến Hưng').
- Trích xuất số điện thoại di động và số container chuẩn ISO 6346.
"""

import unittest
import sys
import os
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.parsing.trip_parser import TripParser
from nhaxe_bot.messaging.segmenter import split_vehicle_blocks


class TestTripParser(unittest.TestCase):
    """Bộ kiểm thử đơn vị cho chức năng bóc tách xe của TripParser."""

    def test_concatenated_plate_and_compound_driver_name(self) -> None:
        """Kiểm tra bóc tách biển số dính liền tiền tố và chuẩn hóa tên tài xế gõ sai phím cách."""
        text = "Xe15h00814/phạm tiếnhưng/0332308336/GAOU6422920/ kho win yên mỹ"
        now = datetime.now()
        vehicle = TripParser.parse_vehicle(text, text, now)

        self.assertEqual(vehicle.bien_so, "15H-00814")
        self.assertEqual(vehicle.tai_xe, "Phạm Tiến Hưng")
        self.assertEqual(vehicle.sdt, "0332308336")
        self.assertEqual(vehicle.cont, "GAOU6422920")

    def test_prefixed_plates_variations(self) -> None:
        """Kiểm tra nhận diện biển số xe với các tiền tố khác nhau: bks, bsx, xe."""
        now = datetime.now()
        v1 = TripParser.parse_vehicle("bks29c12345/nguyenvankhoa/0903976359/TCNU9951145", "", now)
        self.assertEqual(v1.bien_so, "29C-12345")
        self.assertEqual(v1.tai_xe, "Nguyen Van Khoa")

        v2 = TripParser.parse_vehicle("Xe51d99999/bác lêtiếnhưng/0912345678/GAOU6422920", "", now)
        self.assertEqual(v2.bien_so, "51D-99999")
        self.assertEqual(v2.tai_xe, "Lê Tiến Hưng")

    def test_multiline_and_intraline_segmentation(self) -> None:
        """Kiểm tra bóc tách tin nhắn phức tạp vừa có đánh số vừa có nhiều xe nối tiếp trên một dòng."""
        text = (
            "9h\n"
            "1) 50H-46744 / Lý Hoàng Phúc / sdt 0766544549 / SEGU7191464 / chì 53330158\n"
            "2) 72C-64021 / Trịnh Văn Cường / sdt 0860247525 / HLXU6721270 / seal 72355925"
            "/Xe15h00814/phạm tiếnhưng/0332308336/GAOU6422920/ kho win yên mỹ"
            "/xe 15C17066/ Phạm Văn Huynh đt: 0986713346 / VSIU2621051 chì 23333878"
        )
        blocks = split_vehicle_blocks(text)
        self.assertEqual(len(blocks), 4)

        now = datetime.now()
        vehicles = [TripParser.parse_vehicle(b, text, now, i + 1) for i, b in enumerate(blocks)]
        self.assertEqual(vehicles[0].cont, "SEGU7191464")
        self.assertEqual(vehicles[1].cont, "HLXU6721270")
        self.assertEqual(vehicles[2].cont, "GAOU6422920")
        self.assertEqual(vehicles[3].cont, "VSIU2621051")


if __name__ == "__main__":
    unittest.main()
