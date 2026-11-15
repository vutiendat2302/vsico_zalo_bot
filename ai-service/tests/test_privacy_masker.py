"""Kiểm thử PrivacyMasker: che SĐT tài xế trước Cloud LLM và khôi phục nguyên bản sau bóc tách."""

from app.providers.privacy_masker import PrivacyMasker


def test_mask_and_restore_single_phone() -> None:
    """Đảm bảo SĐT Việt Nam được che về dạng `0903xxxx59` và khôi phục chính xác."""
    raw = "Xe 15C-87899 tài xế Anh Hùng SĐT 0903123459 đóng cont MSCU1234567"
    masked = PrivacyMasker.mask_text(raw)

    assert "0903123459" not in masked.masked_text
    assert "0903xxxx59" in masked.masked_text
    assert masked.phone_map["0903xxxx59"] == "0903123459"

    restored = PrivacyMasker.restore_value("0903xxxx59", masked.phone_map)
    assert restored == "0903123459"


def test_mask_handles_plus84_dots_and_collisions() -> None:
    """Kiểm tra chuẩn hóa +84, dấu chấm ngăn cách và tránh ghi đè khi trùng 4 số đầu + 2 số cuối."""
    raw = "Tài 1: +84912.345.678; Tài 2: 0912-999-678"
    masked = PrivacyMasker.mask_text(raw)

    assert "0912345678" not in masked.masked_text
    assert "0912999678" not in masked.masked_text
    assert len(masked.phone_map) == 2

    tokens = list(masked.phone_map.keys())
    assert PrivacyMasker.restore_value(tokens[0], masked.phone_map) == "0912345678"
    assert PrivacyMasker.restore_value(tokens[1], masked.phone_map) == "0912999678"
