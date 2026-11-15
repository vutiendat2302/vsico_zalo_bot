"""Tiền xử lý ảnh trước khi đưa vào PaddleOCR hoặc Multimodal Vision."""

import io
import struct
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PreprocessResult:
    """Kết quả sau bước kiểm tra và chuẩn hóa kích thước/độ rõ ảnh."""

    image_bytes: bytes
    original_size: Optional[tuple[int, int]] = None
    processed_size: Optional[tuple[int, int]] = None
    applied_steps: list[str] = field(default_factory=list)


def _probe_image_dimensions(raw: bytes) -> Optional[tuple[int, int]]:
    """Đọc nhanh chiều rộng x chiều cao từ header PNG/JPEG không cần thư viện ngoài."""
    if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
        try:
            w, h = struct.unpack(">II", raw[16:24])
            return int(w), int(h)
        except struct.error:
            return None

    if len(raw) >= 4 and raw[:2] == b"\xff\xd8":
        idx = 2
        while idx + 9 < len(raw):
            if raw[idx] != 0xFF:
                break
            marker = raw[idx + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", raw[idx + 5 : idx + 9])
                return int(w), int(h)
            if idx + 4 > len(raw):
                break
            seg_len = struct.unpack(">H", raw[idx + 2 : idx + 4])[0]
            if seg_len < 2:
                break
            idx += 2 + seg_len
    return None


class ImagePreprocessor:
    """Chuẩn hóa ảnh Zalo (xoay EXIF, phóng to ảnh nhỏ, thu gọn ảnh quá khổ)."""

    MIN_WIDTH = 800
    MIN_HEIGHT = 100
    MAX_SIDE = 2000

    @classmethod
    def preprocess(cls, image_bytes: bytes) -> PreprocessResult:
        """Tiền xử lý bytes ảnh; tự động passthrough an toàn nếu thiếu Pillow hoặc ảnh lỗi."""
        if not image_bytes:
            return PreprocessResult(image_bytes=image_bytes, applied_steps=["empty"])

        dims = _probe_image_dimensions(image_bytes)
        try:
            from PIL import Image, ImageEnhance, ImageOps
        except ImportError:
            return PreprocessResult(
                image_bytes=image_bytes,
                original_size=dims,
                processed_size=dims,
                applied_steps=["passthrough"],
            )

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                orig_size = img.size
                steps: list[str] = []

                transposed = ImageOps.exif_transpose(img)
                if transposed is not img:
                    steps.append("exif_transpose")
                work = transposed.convert("RGB")
                w, h = work.size

                if w < cls.MIN_WIDTH or h < cls.MIN_HEIGHT:
                    scale = min(2.0, max(cls.MIN_WIDTH / max(w, 1), cls.MIN_HEIGHT / max(h, 1)))
                    if scale > 1.1:
                        work = work.resize(
                            (int(w * scale), int(h * scale)),
                            Image.Resampling.LANCZOS,
                        )
                        steps.append("upscale_small_image")
                elif max(w, h) > cls.MAX_SIDE:
                    scale = cls.MAX_SIDE / max(w, h)
                    work = work.resize(
                        (int(w * scale), int(h * scale)),
                        Image.Resampling.LANCZOS,
                    )
                    steps.append("downscale_oversize")

                if "upscale_small_image" in steps:
                    work = ImageEnhance.Sharpness(work).enhance(1.2)
                    steps.append("sharpen")

                if not steps:
                    return PreprocessResult(
                        image_bytes=image_bytes,
                        original_size=orig_size,
                        processed_size=orig_size,
                        applied_steps=["unchanged"],
                    )

                out = io.BytesIO()
                work.save(out, format="PNG")
                return PreprocessResult(
                    image_bytes=out.getvalue(),
                    original_size=orig_size,
                    processed_size=work.size,
                    applied_steps=steps,
                )
        except Exception:
            return PreprocessResult(
                image_bytes=image_bytes,
                original_size=dims,
                processed_size=dims,
                applied_steps=["passthrough_invalid_image"],
            )
