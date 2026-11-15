"""Kiểm thử đơn vị tầng Domain (ISO 6346, ExtractedContainerLine) và Outbound Templates."""

from src.domain.enums import OrderType, ValidationStatus
from src.domain.models import ExtractedContainerLine
from src.domain.rules import compute_iso6346_check_digit, validate_iso6346
from src.outbound.templates import OutboundTemplateBuilder


def make_valid_cont(prefix: str = "MSCU", digits6: str = "663532") -> str:
    """Tạo một số container hợp lệ chuẩn ISO 6346 Modulo 11."""
    partial = f"{prefix.upper()}{digits6}0"
    chk = compute_iso6346_check_digit(partial)
    assert chk is not None
    return f"{prefix.upper()}{digits6}{chk}"


def test_extracted_container_line_attributes_and_serialization() -> None:
    """Đảm bảo ExtractedContainerLine giữ đủ thuộc tính parser cần và plate_compact hợp lệ."""
    cont = make_valid_cont("VSIO", "262032")
    assert validate_iso6346(cont) is True

    line = ExtractedContainerLine(
        line_no=1,
        line_text=f"15C-87899 {cont}",
        source_format="F1",
        truck_plate="15C-878.99",
        raw_truck_plate="15C-87899",
        driver_name="Nguyễn Văn A",
        driver_phone="0903123456",
        container_no=cont,
        container_size="40",
        seal_no="HL998811",
        order_type=OrderType.LOAD.value,
        customer_hint="Nhựa Á Đông",
        warehouse_hint="Kho Đức Hòa",
        eta_time="08:30",
        check_digit_valid=True,
        validation_status=ValidationStatus.VALID.value,
    )

    assert line.plate_compact == "15C87899"
    canonical = line.to_canonical_record()
    assert canonical["plate"] == "15C87899"
    assert canonical["cont_no"] == cont
    assert canonical["order_type"] == "LOAD"

    payload = line.to_dict()
    assert payload["plate"] == "15C87899"
    assert payload["cont_size"] == "40"


def test_template_builder_supports_uppercase_load_and_return_orders() -> None:
    """Kiểm tra check_core_fields_completeness và render mẫu Đóng/Trả/Cập nhật với LOAD/RETURN."""
    cont = make_valid_cont("TEMU", "112233")

    for order_type, expected_header in (
        (OrderType.LOAD.value, "THÔNG BÁO XE ĐÓNG HÀNG"),
        (OrderType.RETURN.value, "THÔNG BÁO XE TRẢ HÀNG"),
    ):
        line = ExtractedContainerLine(
            line_no=1,
            truck_plate="50H-049.15",
            driver_name="Trần Bình",
            driver_phone="0912345678",
            container_no=cont,
            container_size="40",
            seal_no="SEAL12345",
            order_type=order_type,
            customer_hint="Khách Logitem",
            warehouse_hint="Kho VSICO Hải Phòng",
            eta_time="09:00",
            check_digit_valid=True,
        )
        ok, missing = OutboundTemplateBuilder.check_core_fields_completeness(line)
        assert ok is True, f"Không mong đợi thiếu trường cho {order_type}: {missing}"
        rendered = OutboundTemplateBuilder.build_customer_notification(line)
        assert expected_header in rendered
        assert cont in rendered
        assert "50H-049.15" in rendered
        # Không chứa ký tự emoji/icon trang trí
        assert not any(icon in rendered for icon in ("✅", "❌", "⚠️"))

    upd = OutboundTemplateBuilder.build_update_notification(
        line=ExtractedContainerLine(
            truck_plate="15C-999.99",
            driver_name="Lê Hùng",
            driver_phone="0988777666",
            container_no=cont,
            container_size="40",
            seal_no="SEAL12345",
            order_type=OrderType.LOAD.value,
            customer_hint="Khách Logitem",
        ),
        changes_list=["- Biển số xe: 50H-049.15 -> 15C-999.99"],
    )
    assert "THÔNG BÁO CẬP NHẬT THÔNG TIN XE" in upd
    assert "15C-999.99" in upd
