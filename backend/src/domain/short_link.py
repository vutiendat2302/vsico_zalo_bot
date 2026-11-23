"""Module mã hóa và giải mã liên kết rút gọn ẩn thông tin hệ thống (Opaque Short Links).

Chuyển đổi `(loại thực thể, ID Snowflake 64-bit)` thành chuỗi chữ-số ngắn 15 ký tự
chỉ gồm chữ thường và số (`[0-9a-z]`), không để lộ ID cơ sở dữ liệu hay đường dẫn
nội bộ trên URL gửi cho ĐHVT.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Literal, Optional

ShortEntityKind = Literal["r", "o"]

_BASE36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_BASE36_INDEX = {ch: idx for idx, ch in enumerate(_BASE36_ALPHABET)}
_TOKEN_LENGTH = 15
_MASK_32 = 0xFFFFFFFF
_MASK_63 = (1 << 63) - 1
_MASK_12 = 0xFFF
_TOKEN_RE = re.compile(r"^[0-9a-z]{15}$")


def _derive_key(secret: str, purpose: bytes) -> bytes:
    """Sinh khóa dẫn xuất 32 byte từ khóa bí mật hệ thống theo mục đích sử dụng."""
    raw_secret = (secret or "vsico-short-link-default-secret").encode("utf-8")
    return hmac.new(raw_secret, purpose, hashlib.sha256).digest()


def _feistel_round_fn(half: int, round_idx: int, key: bytes) -> int:
    """Hàm F cho mạng Feistel 4 vòng trên nửa 32-bit."""
    msg = round_idx.to_bytes(1, "big") + half.to_bytes(4, "big")
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return int.from_bytes(digest[:4], "big")


def _scramble_64(value: int, key: bytes, reverse: bool = False) -> int:
    """Hoán vị đảo được trên số nguyên 64-bit bằng mạng Feistel 4 vòng."""
    left = (value >> 32) & _MASK_32
    right = value & _MASK_32
    rounds = (3, 2, 1, 0) if reverse else (0, 1, 2, 3)
    if reverse:
        for r in rounds:
            old_right = left
            old_left = right ^ _feistel_round_fn(old_right, r, key)
            left, right = old_left, old_right
    else:
        for r in rounds:
            new_left = right
            new_right = left ^ _feistel_round_fn(right, r, key)
            left, right = new_left, new_right
    return ((left & _MASK_32) << 32) | (right & _MASK_32)


def _compute_tag_12(scrambled_64: int, mac_key: bytes) -> int:
    """Tính mã xác thực toàn vẹn 12-bit chống sửa/đoán token."""
    digest = hmac.new(mac_key, scrambled_64.to_bytes(8, "big"), hashlib.sha256).digest()
    return int.from_bytes(digest[:2], "big") & _MASK_12


def _to_base36_fixed(value: int, length: int = _TOKEN_LENGTH) -> str:
    """Chuyển số nguyên không âm sang chuỗi base36 độ dài cố định."""
    chars = ["0"] * length
    cur = value
    for idx in range(length - 1, -1, -1):
        cur, rem = divmod(cur, 36)
        chars[idx] = _BASE36_ALPHABET[rem]
    return "".join(chars)


def _from_base36(token: str) -> Optional[int]:
    """Giải mã chuỗi base36 về số nguyên không âm."""
    total = 0
    for ch in token:
        digit = _BASE36_INDEX.get(ch)
        if digit is None:
            return None
        total = total * 36 + digit
    return total


def encode_short_token(kind: ShortEntityKind, entity_id: int, secret: str) -> str:
    """Mã hóa `(kind, entity_id)` thành mã liên kết rút gọn 15 ký tự chữ-số thường."""
    if kind not in ("r", "o"):
        raise ValueError(f"Unsupported short link kind: {kind}")
    if entity_id <= 0 or entity_id > _MASK_63:
        raise ValueError(f"Invalid entity_id for short link: {entity_id}")

    kind_bit = 0 if kind == "r" else 1
    packed_64 = (kind_bit << 63) | (entity_id & _MASK_63)

    enc_key = _derive_key(secret, b"vsico-short-link-feistel-v1")
    mac_key = _derive_key(secret, b"vsico-short-link-hmac-v1")

    scrambled = _scramble_64(packed_64, enc_key, reverse=False)
    tag = _compute_tag_12(scrambled, mac_key)
    combined_76 = (scrambled << 12) | tag
    return _to_base36_fixed(combined_76, _TOKEN_LENGTH)


def decode_short_token(token: str, secret: str) -> Optional[tuple[ShortEntityKind, int]]:
    """Giải mã và kiểm tra toàn vẹn mã liên kết rút gọn về `(kind, entity_id)`."""
    clean = (token or "").strip().lower()
    if not _TOKEN_RE.match(clean):
        return None

    combined_76 = _from_base36(clean)
    if combined_76 is None or combined_76 >= (1 << 76):
        return None

    scrambled = (combined_76 >> 12) & ((1 << 64) - 1)
    tag = combined_76 & _MASK_12

    enc_key = _derive_key(secret, b"vsico-short-link-feistel-v1")
    mac_key = _derive_key(secret, b"vsico-short-link-hmac-v1")

    expected_tag = _compute_tag_12(scrambled, mac_key)
    if not hmac.compare_digest(tag.to_bytes(2, "big"), expected_tag.to_bytes(2, "big")):
        return None

    packed_64 = _scramble_64(scrambled, enc_key, reverse=True)
    kind_bit = (packed_64 >> 63) & 1
    entity_id = packed_64 & _MASK_63
    if entity_id <= 0:
        return None

    kind: ShortEntityKind = "o" if kind_bit == 1 else "r"
    return (kind, entity_id)
