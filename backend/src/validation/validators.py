"""Module Kiểm Tra Tính Hợp Lệ Dữ Liệu Xe & Container (Validation Layer).

Thực hiện đối chiếu từng dòng dữ liệu bóc tách (`ExtractedContainerLine`) với quy chuẩn
nghiệp vụ của VSICO:
- Kiểm tra chữ số cuối container theo tiêu chuẩn quốc tế ISO 6346 Modulo 11 (T19).
- Kiểm tra cấu trúc định dạng số container 4 chữ + 7 số (T18).
- Kiểm tra độ đầy đủ của 4 trường cốt lõi: Biển số xe (T11), Tên tài xế (T13),
  SĐT tài xế (T14), Số container (T10).
- Kiểm tra tính rõ ràng của quan hệ Xe - Container (T34).
- Gắn danh sách mã cảnh báo (`warnings`) và xác lập trạng thái `validation_status`
  (`valid`, `invalid`, `needs_review`).
"""

import re
from src.domain.enums import ValidationStatus
from src.domain.models import ExtractedContainerLine
from src.domain.rules import compute_iso6346_check_digit, validate_iso6346


class ContainerValidator:
    """Bộ thẩm định tính hợp lệ cho từng dòng dữ liệu xe và container đã bóc tách."""

    @classmethod
    def validate_line(cls, line: ExtractedContainerLine) -> ExtractedContainerLine:
        """Kiểm tra toàn diện một đối tượng `ExtractedContainerLine` và cập nhật trạng thái.

        Args:
            line (ExtractedContainerLine): Dòng dữ liệu xe/container sau khi bóc tách.

        Returns:
            ExtractedContainerLine: Chính đối tượng đầu vào đã được bổ sung `check_digit_valid`,
                `warnings`, `confidence` và `validation_status`.
        """
        warnings: list[str] = []
        has_hard_error = False

        # 1. Kiểm tra biển số xe đầu kéo & phân biệt với biển rơ-moóc (Bảng 6.2 & TC-08, T11)
        if not line.truck_plate:
            warnings.append("MISSING_TRUCK_PLATE")
            if line.trailer_plate:
                warnings.append(f"TRAILER_PLATE_IN_TRUCK_POSITION({line.trailer_plate})")
                has_hard_error = True
        elif not re.match(r"^\d{2}[A-Z]{1,2}-\d{3}\.\d{2}$|^\d{2}[A-Z]{1,2}-\d{4,5}$", line.truck_plate):
            warnings.append("UNUSUAL_TRUCK_PLATE_FORMAT")

        # 2. Kiểm tra họ tên tài xế (Bảng 6.2 & T13: ít nhất 2 ký tự, không rỗng)
        if not line.driver_name or len(line.driver_name.strip()) < 2:
            warnings.append("MISSING_DRIVER_NAME")

        # 3. Kiểm tra số điện thoại tài xế (Bảng 6.2 & TC-07, T14: đúng 10 chữ số, bắt đầu bằng 0)
        if not line.driver_phone:
            warnings.append("MISSING_DRIVER_PHONE")
        elif "*" in line.driver_phone:
            # SĐT bị ẩn một phần trong dữ liệu mẫu/log (VD: 0986****** dài 10 ký tự -> hợp lệ; 098****** dài 9 ký tự -> lỗi TC-07)
            if len(line.driver_phone) != 10 or not line.driver_phone.startswith("0"):
                warnings.append("INVALID_DRIVER_PHONE")
                has_hard_error = True
        elif not re.match(r"^0\d{9}$", line.driver_phone):
            warnings.append("INVALID_DRIVER_PHONE")
            has_hard_error = True

        # 4. Kiểm tra số hiệu container (T10, T18, T19)
        if not line.container_no:
            if line.is_container_pending:
                warnings.append("PENDING_CONTAINER_NO")
            else:
                warnings.append("MISSING_CONTAINER_NO")
            line.check_digit_valid = None
        else:
            if not re.match(r"^[A-Z]{4}\d{7}$", line.container_no):
                warnings.append("INVALID_CONTAINER_FORMAT")
                line.check_digit_valid = False
                has_hard_error = True
            else:
                is_valid_iso = validate_iso6346(line.container_no)
                line.check_digit_valid = is_valid_iso
                if not is_valid_iso:
                    expected_digit = compute_iso6346_check_digit(line.container_no)
                    actual_digit = line.container_no[-1]
                    warnings.append(
                        f"ISO6346_CHECK_DIGIT_MISMATCH(expected={expected_digit},actual={actual_digit})"
                    )
                    has_hard_error = True

        # 5. Kiểm tra mâu thuẫn gắn kết Xe - Container (T34)
        if line.has_conflicting_mapping:
            warnings.append("AMBIGUOUS_VEHICLE_CONTAINER_MAPPING")
            has_hard_error = True

        line.warnings = warnings

        # 6. Quyết định trạng thái thẩm định tổng thể (validation_status) và độ tin cậy (confidence)
        # Bảo toàn mức confidence thấp nếu Parser đã đánh dấu định dạng tự do không chắc chắn
        parser_conf = line.confidence
        if has_hard_error:
            line.validation_status = ValidationStatus.INVALID.value
            line.confidence = min(parser_conf, 0.40)
        elif warnings:
            line.validation_status = ValidationStatus.NEEDS_REVIEW.value
            score = max(0.65, round(0.95 - 0.08 * len(warnings), 2))
            line.confidence = min(parser_conf, score)
        else:
            line.validation_status = ValidationStatus.VALID.value
            line.confidence = parser_conf if parser_conf < 0.65 else 0.98

        return line

    @classmethod
    def validate_all(cls, lines: list[ExtractedContainerLine]) -> list[ExtractedContainerLine]:
        """Thẩm định danh sách tất cả các dòng xe/container của một tin nhắn.

        Args:
            lines (list[ExtractedContainerLine]): Danh sách các dòng bóc tách được.

        Returns:
            list[ExtractedContainerLine]: Danh sách đã được cập nhật kết quả thẩm định.
        """
        return [cls.validate_line(line) for line in lines]
