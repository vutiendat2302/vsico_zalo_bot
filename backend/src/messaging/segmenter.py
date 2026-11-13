"""Module Phân Đoạn Tin Nhắn Đa Xe / Đa Container / Đa Lệnh (Multi-Vehicle & Multi-Order Segmenter).

Hỗ trợ phân tách toàn bộ các bố cục tin nhắn thực tế trong Bảng 1.6 và Bảng 2:
- F1: Mỗi dòng là 1 xe ngăn cách bằng dấu gạch chéo `/`, gạch ngang `-`, dấu sổ thẳng `|` hoặc tab `\t` (dạng bảng).
- F2: Khối nhiều dòng có nhãn (`Biển số:`, `Tài xế:`, `SĐT:`, `Số cont:`), cách nhau bởi dòng trống.
- F3: Danh sách đánh số thứ tự (`1.`, `2.`, `Xe 1:`, `Xe 2:`) hoặc ký hiệu đầu dòng (`*`, `-`, `#`, emoji).
- T09 / T24 / T25: Một tin nhắn chứa nhiều nhóm lệnh (Đóng + Trả) hoặc nhiều Kho / Khách hàng khác nhau.
- T31: Tin nhắn trích dẫn / chuyển tiếp (tách phần nội dung mới khỏi phần trích dẫn cũ).
"""

import re


class MessageSegmenter:
    """Bộ phân tách tin nhắn phức hợp thành danh sách các khối văn bản độc lập kèm ngữ cảnh lệnh/kho/khách."""

    _PLATE_REGEX = re.compile(
        r"\b\d{2}[A-Za-z]{1,2}(?:[\s.\-]*\d{3}[\s.\-]*\d{1,2}|[\s.\-]*\d{4,5})\b"
    )
    _CONT_REGEX = re.compile(
        r"\b[A-Za-z]{3}[UJuZujz][\s.\-]*\d{5,8}\b|(?:số\s*cont|so\s*cont|container|cntr)\s*[:\-]?\s*[A-Za-z0-9\-]{5,15}",
        re.IGNORECASE,
    )
    _CONTEXT_HEADER_REGEX = re.compile(
        r"(?:lệnh\s*đóng|lenh\s*dong|đóng\s*hàng|dong\s*hang|đóng\s*cont|dong\s*cont|lấy\s*cont\s*rỗng|lay\s*cont\s*rong|"
        r"lệnh\s*trả|lenh\s*tra|trả\s*hàng|tra\s*hang|trả\s*cont|tra\s*cont|hạ\s*cont|ha\s*cont|hạ\s*bãi|ha\s*bai|"
        r"hàng\s*xuất|hang\s*xuat|hàng\s*nhập|hang\s*nhap|"
        r"khách\s*hàng|khach\s*hang|chủ\s*hàng|chu\s*hang|"
        r"kho\s+|nhà\s*máy|nha\s*may|cảng\s+|cang\s+|kcn\s+|khu\s*công\s*nghiệp|điểm\s*đóng|điểm\s*trả|"
        r"booking|mã\s*lệnh|ma\s*lenh|số\s*lệnh|so\s*lenh)",
        re.IGNORECASE,
    )

    @classmethod
    def strip_quoted_block(cls, raw_text: str) -> tuple[str, str]:
        """Tách phần nội dung mới và phần nội dung trích dẫn/chuyển tiếp cũ (nếu có - T31).

        Args:
            raw_text (str): Nội dung tin nhắn gốc.

        Returns:
            tuple[str, str]: Cặp `(new_content, quoted_content)`.
        """
        lines = (
            raw_text.replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
        )
        new_lines: list[str] = []
        quoted_lines: list[str] = []
        in_quote_block = False

        for ln in lines:
            stripped = ln.strip()
            if re.match(r"^(?:>{1,3}|❝|---+\s*(?:tin\s*nhắn\s*chuyển\s*tiếp|trích\s*dẫn|forwarded))", stripped, flags=re.IGNORECASE):
                in_quote_block = True
                quoted_lines.append(re.sub(r"^(?:>{1,3}|❝)\s*", "", stripped))
                continue
            if in_quote_block and stripped == "---":
                in_quote_block = False
                continue
            if in_quote_block:
                quoted_lines.append(stripped)
            else:
                new_lines.append(ln)

        new_text = "\n".join(new_lines).strip()
        quoted_text = "\n".join(quoted_lines).strip()
        if not new_text and quoted_text:
            return quoted_text, ""
        return new_text, quoted_text

    @classmethod
    def segment(cls, raw_text: str) -> list[str]:
        """Tách một tin nhắn văn bản thành danh sách các đoạn, mỗi đoạn ứng với 1 xe/container.

        Tự động theo dõi sự thay đổi ngữ cảnh (Đóng/Trả, Kho, Khách hàng, Booking) dọc theo
        các dòng tin nhắn để hỗ trợ tin có nhiều lệnh (T09), nhiều kho (T24), nhiều khách (T25).

        Args:
            raw_text (str): Nội dung tin nhắn gốc từ Zalo.

        Returns:
            list[str]: Danh sách các đoạn văn bản đã được gắn kèm ngữ cảnh tương ứng.
        """
        if not raw_text or not raw_text.strip():
            return []

        main_text, quoted_text = cls.strip_quoted_block(raw_text)
        cleaned_text = main_text.strip()
        lines = [ln.strip() for ln in cleaned_text.split("\n") if ln.strip()]
        if not lines:
            return []

        # Nếu toàn bộ tin nhắn chỉ có tối đa 1 biển số xe và 1 số container -> chắc chắn là 1 khối duy nhất (F2 nhiều dòng)
        all_plates = cls._PLATE_REGEX.findall(cleaned_text)
        all_conts = cls._CONT_REGEX.findall(cleaned_text)
        if len(all_plates) <= 1 and len(all_conts) <= 1:
            return [cleaned_text]

        # Trường hợp 1: Phân đoạn theo ranh giới xe rõ ràng (Emoji xe 🚛🚚🚗, "Xe 1:", "Xe 2:", "1.", "2.", "Biển số:", "BKS:")
        # Lưu ý: Không tách theo nhãn "Cont:" đơn lẻ vì F2 nhiều dòng có "Xe: ..." ở trên và "Cont: ..." ở dưới thuộc cùng 1 xe.
        vehicle_split = re.split(
            r"(?m)(?=^[ \t]*(?:[🚛🚚🚗🏎️🚜]|\d+[\.\)]\s*(?:xe|cont|bks|biển)?|(?:xe\s*\d*|biển\s*số|bien\s*so|bks|số\s*xe|so\s*xe|đầu\s*kéo|dau\s*keo)\s*[:\-])\s*)",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        vehicle_parts = [p.strip() for p in vehicle_split if p.strip()]
        vehicle_candidates = [
            p for p in vehicle_parts if cls._PLATE_REGEX.search(p) or cls._CONT_REGEX.search(p)
        ]
        if len(vehicle_candidates) >= 2:
            first_has_vehicle = bool(
                cls._PLATE_REGEX.search(vehicle_parts[0]) or cls._CONT_REGEX.search(vehicle_parts[0])
            )
            if not first_has_vehicle and len(vehicle_parts) >= 3:
                header = vehicle_parts[0]
                return [
                    f"{header}\n{b}".strip()
                    for b in vehicle_parts[1:]
                    if cls._PLATE_REGEX.search(b) or cls._CONT_REGEX.search(b)
                ]
            if first_has_vehicle:
                return vehicle_candidates

        # Trường hợp 2: Kiểm tra F1 - Nhiều dòng mà mỗi dòng tự thân là 1 xe (ngăn cách bằng '/', '|', '\t')
        lines_with_plate = [ln for ln in lines if cls._PLATE_REGEX.search(ln)]
        if len(lines_with_plate) >= 2:
            # Nhận diện dòng có nhãn trường hoặc biểu tượng đại diện trường để phân biệt F1 và tin nhiều dòng
            labeled_field_lines = [
                ln for ln in lines
                if re.match(
                    r"^(?:[👤👨🧑🪪📞📱☎️📦🏷️🧰🚛🚚🚗]|tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|sđt|sdt|đt|số\s*cont|so\s*cont|cont|seal|số\s*chì|bks|biển\s*số)\b|^[👤👨🧑🪪📞📱☎️📦🏷️🧰🚛🚚🚗]",
                    ln,
                    flags=re.IGNORECASE,
                )
            ]
            if not labeled_field_lines:
                results: list[str] = []
                active_headers: list[str] = []
                for ln in lines:
                    has_plate = bool(cls._PLATE_REGEX.search(ln))
                    has_cont = bool(cls._CONT_REGEX.search(ln))
                    if has_plate or has_cont:
                        prefix = "\n".join(active_headers).strip()
                        if quoted_text and not prefix:
                            prefix = quoted_text
                        results.append(f"{prefix}\n{ln}".strip() if prefix else ln)
                    else:
                        if cls._CONTEXT_HEADER_REGEX.search(ln) and results:
                            active_headers = [ln]
                        else:
                            active_headers.append(ln)
                if len(results) >= 2:
                    return results

        # Trường hợp 3: Định dạng F2 - Các khối cách nhau bằng dòng trống (blank lines)
        raw_blocks = [
            blk.strip()
            for blk in re.split(r"\n\s*\n+", cleaned_text)
            if blk.strip()
        ]
        if len(raw_blocks) >= 2:
            vehicle_blocks: list[str] = []
            current_context_headers: list[str] = []
            for blk in raw_blocks:
                if cls._PLATE_REGEX.search(blk) or cls._CONT_REGEX.search(blk):
                    prefix = "\n".join(current_context_headers).strip()
                    vehicle_blocks.append(f"{prefix}\n{blk}".strip() if prefix else blk)
                else:
                    if cls._CONTEXT_HEADER_REGEX.search(blk) and vehicle_blocks:
                        current_context_headers = [blk]
                    else:
                        current_context_headers.append(blk)
            if len(vehicle_blocks) >= 2:
                return vehicle_blocks

        # Trường hợp 4: Nhiều khối bắt đầu bằng STT ("1.", "2.", "Xe 1:", "Xe 2:")
        numbered_split = re.split(
            r"(?m)(?=^(?:xe\s*\d+|\d+[\.)])\s*[:\-]?)",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        numbered_blocks = [b.strip() for b in numbered_split if b.strip()]
        if len(numbered_blocks) >= 2:
            first_has_vehicle = bool(
                cls._PLATE_REGEX.search(numbered_blocks[0])
                or cls._CONT_REGEX.search(numbered_blocks[0])
            )
            if not first_has_vehicle and len(numbered_blocks) >= 3:
                header = numbered_blocks[0]
                return [f"{header}\n{b}".strip() for b in numbered_blocks[1:]]
            if first_has_vehicle:
                return numbered_blocks

        # Trường hợp 4: Nhiều khối nhiều dòng liên tiếp không có dòng trống, mỗi khối bắt đầu bằng "Biển số:" / "BKS:" / "Số xe:"
        bks_split = re.split(
            r"(?m)(?=^(?:biển\s*số|bien\s*so|bks|số\s*xe|so\s*xe|đầu\s*kéo|dau\s*keo)\s*[:\-])",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        bks_blocks = [b.strip() for b in bks_split if b.strip()]
        if len(bks_blocks) >= 2:
            first_has_plate = bool(cls._PLATE_REGEX.search(bks_blocks[0]))
            if not first_has_plate and len(bks_blocks) >= 3:
                header = bks_blocks[0]
                return [f"{header}\n{b}".strip() for b in bks_blocks[1:]]
            if first_has_plate:
                return bks_blocks

        # Mặc định: Toàn bộ tin nhắn là 1 khối duy nhất (kèm ngữ cảnh trích dẫn nếu bản thân tin mới chỉ bổ sung thông tin)
        if quoted_text and len(cleaned_text.splitlines()) <= 2:
            return [f"{quoted_text}\n{cleaned_text}".strip()]
        return [cleaned_text]
