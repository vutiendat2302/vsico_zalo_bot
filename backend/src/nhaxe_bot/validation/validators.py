"""Module Thẩm Định Dữ Liệu Chuyến Xe (Vehicle Data Validator).

Kiểm tra tính hợp lệ toàn diện của từng trường dữ liệu xe bóc tách được:
- Số container: Kiểm tra cấu trúc 4 chữ cái + 7 số và thuật toán ISO 6346 Mod 11.
- Số seal/chì: Kiểm tra sự hiện diện của trường bắt buộc.
- Biển số xe: Kiểm tra cấu trúc biển số xe cơ giới Việt Nam.
- Số điện thoại: Kiểm tra định dạng 10 chữ số di động Việt Nam.
- Giờ đến: Kiểm tra tính xác thực của mốc thời gian.
- Phân loại cảnh báo thành Blocking (ngăn chặn gửi tin, yêu cầu bổ sung)
  và Non-blocking (cho phép gửi nhưng ghi chú cảnh báo).
"""

import re
from typing import List, Tuple
from ..domain.models import Vehicle
from ..domain.rules import clean_container, clean_plate, clean_phone, validate_iso6346


def compute_iso6346_check_digit(cont: str):
    """Tính toán chữ số kiểm tra (Check Digit) lý thuyết của container theo chuẩn ISO 6346.

    Args:
        cont (str): Chuỗi số hiệu container (chuẩn 11 ký tự).

    Returns:
        Optional[int]: Chữ số kiểm tra tính toán được (0-9) hoặc None nếu chuỗi không hợp lệ.
    """
    from ..domain.rules import CHAR_MAP

    clean = re.sub(r'[^A-Za-z0-9]', '', cont).upper()
    if len(clean) != 11:
        return None
    total = 0
    for i in range(10):
        c = clean[i]
        if c.isalpha():
            if c not in CHAR_MAP:
                return None
            val = CHAR_MAP[c]
        elif c.isdigit():
            val = int(c)
        else:
            return None
        total += val * (2 ** i)
    rem = total % 11
    return rem % 10


def validate_container(raw_cont: str) -> Tuple[str, List[str]]:
    """Thẩm định tính hợp lệ của số container.

    Args:
        raw_cont (str): Chuỗi số container thô cần kiểm tra.

    Returns:
        Tuple[str, List[str]]:
            - clean: Chuỗi container đã làm sạch ký tự phân cách.
            - warnings: Danh sách mã cảnh báo (['thieu_cont'], ['cont_sai_dinh_dang'], ['cont_sai_check_digit']).
    """
    warnings = []
    if not raw_cont:
        warnings.append("thieu_cont")
        return "", warnings
    clean = re.sub(r'[^A-Za-z0-9]', '', raw_cont).upper()
    if not re.match(r'^[A-Z]{4}\d{7}$', clean):
        warnings.append("cont_sai_dinh_dang")
        return clean, warnings
    expected = compute_iso6346_check_digit(clean)
    if expected is None or int(clean[-1]) != expected:
        warnings.append("cont_sai_check_digit")
    return clean, warnings


def validate_phone(raw_phone: str) -> Tuple[str, List[str]]:
    """Thẩm định số điện thoại tài xế theo quy chuẩn di động Việt Nam.

    Args:
        raw_phone (str): Chuỗi số điện thoại thô.

    Returns:
        Tuple[str, List[str]]:
            - digits: Chuỗi số điện thoại sau khi loại bỏ ký tự lạ.
            - warnings: Danh sách cảnh báo (['thieu_sdt'], ['sdt_sai_dinh_dang']).
    """
    warnings = []
    if not raw_phone:
        warnings.append("thieu_sdt")
        return "", warnings
    digits = re.sub(r'\D', '', raw_phone)
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    if not re.match(r'^0[3-9]\d{8}$', digits):
        warnings.append("sdt_sai_dinh_dang")
    return digits, warnings


def validate_plate(raw_plate: str) -> Tuple[str, List[str]]:
    """Thẩm định và chuẩn hóa biển số xe cơ giới theo quy chuẩn Việt Nam dạng XXY-ZZZZ(Z).

    Args:
        raw_plate (str): Chuỗi biển số xe thô (ví dụ: '15h00814', '15C-878.99', '50H46744').

    Returns:
        Tuple[str, List[str]]:
            - clean: Chuỗi biển số xe chuẩn hóa có dấu gạch nối (ví dụ: '15H-00814', '15C-87899').
            - warnings: Danh sách cảnh báo (['thieu_bien_so'], ['bien_so_sai_dinh_dang']).
    """
    warnings = []
    if not raw_plate:
        warnings.append("thieu_bien_so")
        return "", warnings
    norm = clean_plate(raw_plate)
    if not norm or not re.match(r'^\d{2}[A-Z]{1,2}\-\d{4,5}$', norm):
        warnings.append("bien_so_sai_dinh_dang")
    return norm or raw_plate.strip(), warnings


class VehicleValidator:
    """Bộ thẩm định tính hợp lệ của phương tiện vận chuyển trước khi gửi thông báo."""

    @staticmethod
    def validate(vehicle: Vehicle, required_fields: List[str]) -> Vehicle:
        """Thực hiện chu trình kiểm tra đầy đủ các trường thông tin của đối tượng Vehicle.

        Quy trình thẩm định:
        1. Kiểm tra container: Thiếu cont, sai format, sai số kiểm tra ISO 6346 Mod 11.
        2. Kiểm tra số seal: Phát hiện trường seal bị bỏ trống.
        3. Kiểm tra biển số xe: Chuẩn hóa và kiểm tra định dạng.
        4. Kiểm tra tài xế: Kiểm tra họ tên lái xe.
        5. Kiểm tra SĐT: Kiểm tra đầu số di động 10 số.
        6. Kiểm tra giờ đến: Kiểm tra thiếu giờ hoặc giờ giấc mập mờ ('gio_mo_ho').
        7. Phân định trạng thái: Nếu có lỗi chặn (blocking error), gán `status = 'need_supplement'`.
           Ngược lại gán `status = 'ready'`.

        Args:
            vehicle (Vehicle): Đối tượng phương tiện cần thẩm định.
            required_fields (List[str]): Danh sách các trường bắt buộc phải có.

        Returns:
            Vehicle: Đối tượng phương tiện đã được chuẩn hóa dữ liệu và cập nhật danh sách warnings.
        """
        warnings: List[str] = list(vehicle.warnings)

        # 1. Thẩm định số Container
        if not vehicle.cont:
            if "thieu_cont" not in warnings:
                warnings.append("thieu_cont")
        else:
            norm_cont, cont_warns = validate_container(vehicle.cont)
            vehicle.cont = norm_cont
            for w in cont_warns:
                if w not in warnings:
                    warnings.append(w)

        # 2. Thẩm định số Seal / Niêm chì
        if not vehicle.seal and "seal" in required_fields:
            if "thieu_seal" not in warnings:
                warnings.append("thieu_seal")

        # 3. Thẩm định Biển số xe
        if not vehicle.bien_so and "bien_so" in required_fields:
            if "thieu_bien_so" not in warnings:
                warnings.append("thieu_bien_so")
        elif vehicle.bien_so:
            norm_plate, plate_warns = validate_plate(vehicle.bien_so)
            vehicle.bien_so = norm_plate
            for w in plate_warns:
                if w not in warnings:
                    warnings.append(w)

        # 4. Thẩm định Tên tài xế
        if not vehicle.tai_xe and "tai_xe" in required_fields:
            if "thieu_tai_xe" not in warnings:
                warnings.append("thieu_tai_xe")

        # 5. Thẩm định Số điện thoại
        if not vehicle.sdt and "sdt" in required_fields:
            if "thieu_sdt" not in warnings:
                warnings.append("thieu_sdt")
        elif vehicle.sdt:
            norm_sdt, sdt_warns = validate_phone(vehicle.sdt)
            vehicle.sdt = norm_sdt
            for w in sdt_warns:
                if w not in warnings:
                    warnings.append(w)

        # 6. Thẩm định Giờ đến kho
        if not vehicle.gio_den and "gio_den" in required_fields:
            if "gio_mo_ho" not in warnings and "thieu_gio_den" not in warnings:
                warnings.append("thieu_gio_den")

        # Phân định các cảnh báo có chặn gửi tin (Blocking) hay không
        non_blocking = {"thieu_ngay_dung_ngay_gui", "ngay_lech_so_voi_ngay_gui"}
        blocking = [w for w in warnings if w not in non_blocking]

        vehicle.warnings = warnings
        # Nếu có lỗi chặn, chuyển trạng thái cần bổ sung; nếu không, sẵn sàng gửi khách
        vehicle.status = "need_supplement" if blocking else "ready"
        return vehicle
