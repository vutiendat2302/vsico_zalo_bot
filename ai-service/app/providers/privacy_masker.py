"""Module che và khôi phục số điện thoại cá nhân (PII Masking) trước khi gọi Cloud LLM."""

import re
from dataclasses import dataclass, field

# Nhận diện SĐT Việt Nam dạng 9-11 chữ số, cho phép dấu chấm, gạch ngang hoặc khoảng trắng
_VN_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]*\d){8,10}(?!\d)")


@dataclass
class MaskedPayload:
    """Kết quả che SĐT gồm văn bản đã ẩn và bảng ánh xạ phục hồi."""

    masked_text: str
    phone_map: dict[str, str] = field(default_factory=dict)


class PrivacyMasker:
    """Bộ che SĐT tài xế dạng `0903xxxx59` trước khi gửi prompt ra Cloud LLM."""

    @staticmethod
    def _normalize_digits(raw_phone: str) -> str:
        """Chuẩn hóa SĐT thô về dạng 10 chữ số bắt đầu bằng 0 nếu là đầu số +84."""
        digits = re.sub(r"\D", "", raw_phone or "")
        if digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        return digits

    @classmethod
    def mask_text(
        cls,
        text: str | None,
        existing_map: dict[str, str] | None = None,
    ) -> MaskedPayload:
        """Che toàn bộ số điện thoại trong văn bản về dạng `0903xxxx59`."""
        phone_map: dict[str, str] = dict(existing_map or {})
        if not text:
            return MaskedPayload(masked_text="", phone_map=phone_map)

        def _replace(match: re.Match[str]) -> str:
            raw_val = match.group(0)
            norm = cls._normalize_digits(raw_val)
            if len(norm) < 9 or len(norm) > 11:
                return raw_val
            base_mask = f"{norm[:4]}xxxx{norm[-2:]}"
            token = base_mask
            idx = 2
            while token in phone_map and phone_map[token] != norm:
                token = f"{base_mask}_{idx}"
                idx += 1
            phone_map[token] = norm
            return token

        masked = _VN_PHONE_RE.sub(_replace, text)
        return MaskedPayload(masked_text=masked, phone_map=phone_map)

    @classmethod
    def restore_value(cls, value: str | None, phone_map: dict[str, str]) -> str | None:
        """Khôi phục số điện thoại thật từ chuỗi có chứa token che."""
        if not value or not phone_map:
            return value
        restored = value
        # Thay thế token dài trước để tránh khớp nhầm tiền tố
        for token in sorted(phone_map.keys(), key=len, reverse=True):
            if token in restored:
                restored = restored.replace(token, phone_map[token])
        return restored
