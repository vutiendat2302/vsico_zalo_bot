import unittest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.domain.rules import validate_iso6346, clean_plate, clean_phone, clean_container, clean_driver_name

class TestDomainRules(unittest.TestCase):
    """Bộ kiểm thử đơn vị cho các quy tắc nghiệp vụ lõi (Domain Rules Unit Tests).

    Kiểm tra thuật toán kiểm tra số container ISO 6346 Mod 11,
    hàm làm sạch biển số xe, hàm chuẩn hóa số điện thoại di động Việt Nam,
    chuẩn hóa tên tài xế (Title Case, tách từ dính liền) và chuẩn hóa chuỗi container.
    """

    def test_iso6346_valid(self) -> None:
        """Kiểm tra các số container chuẩn ISO 6346 có chữ số kiểm tra (check digit) hợp lệ."""
        self.assertTrue(validate_iso6346("VSIU7399796"))
        self.assertTrue(validate_iso6346("SEGU7191464"))
        self.assertTrue(validate_iso6346("GAOU9386298"))

    def test_iso6346_invalid(self) -> None:
        """Kiểm tra các trường hợp container sai chữ số kiểm tra hoặc sai cấu trúc định dạng."""
        # Sai check digit (số kiểm tra tính toán phải là 6 thay vì 0)
        self.assertFalse(validate_iso6346("VSIU7399790"))
        # Sai định dạng (không đủ 4 chữ cái hoặc thiếu 7 chữ số)
        self.assertFalse(validate_iso6346("ABC12345"))

    def test_clean_plate(self) -> None:
        """Kiểm tra hàm chuẩn hóa biển số xe về dạng chuẩn có dấu gạch nối (XXY-ZZZZZ)."""
        self.assertEqual(clean_plate("15C-878.99"), "15C-87899")
        self.assertEqual(clean_plate("50H-467.44"), "50H-46744")
        self.assertEqual(clean_plate("72C-64021"), "72C-64021")
        self.assertEqual(clean_plate("15h00814"), "15H-00814")
        self.assertEqual(clean_plate("15H12303"), "15H-12303")

    def test_clean_phone(self) -> None:
        """Kiểm tra hàm làm sạch số điện thoại chuyển đổi mã vùng quốc tế +84 và loại bỏ dấu phân cách."""
        self.assertEqual(clean_phone("+84903976359"), "0903976359")
        self.assertEqual(clean_phone("0903.976.359"), "0903976359")
        self.assertEqual(clean_phone("0903 976 359"), "0903976359")

    def test_clean_driver_name(self) -> None:
        """Kiểm tra chuẩn hóa tên tài xế: loại bỏ tiền tố xưng hô, tách từ dính phím và Title Case."""
        self.assertEqual(clean_driver_name("phạm tiếnhưng"), "Phạm Tiến Hưng")
        self.assertEqual(clean_driver_name("tx nguyễn văn khoa"), "Nguyễn Văn Khoa")
        self.assertEqual(clean_driver_name("anh lêtiếnhưng"), "Lê Tiến Hưng")
        self.assertEqual(clean_driver_name("bác vũđạt"), "Vũ Đạt")

if __name__ == "__main__":
    unittest.main()
