"""Module Phân Đoạn Tin Nhắn Đa Xe / Đa Container / Đa Lệnh (Multi-Vehicle & Multi-Order Segmenter).

Hỗ trợ phân tách toàn bộ các bố cục tin nhắn thực tế trong Bảng 1.6 và Bảng 2:
- F1: Mỗi dòng là 1 xe ngăn cách bằng dấu gạch chéo `/`, gạch ngang `-`, dấu sổ thẳng `|` hoặc tab `\t` (dạng bảng).
- F2: Khối nhiều dòng có nhãn (`Biển số:`, `Tài xế:`, `SĐT:`, `Số cont:`), cách nhau bởi dòng trống.
- F3: Danh sách đánh số thứ tự (`1.`, `2.`, `Xe 1:`, `Xe 2:`) hoặc ký hiệu đầu dòng (`*`, `-`, `#`, emoji).
- T09 / T24 / T25: Một tin nhắn chứa nhiều nhóm lệnh (Đóng + Trả) hoặc nhiều Kho / Khách hàng khác nhau.
- T31: Tin nhắn trích dẫn / chuyển tiếp (tách phần nội dung mới khỏi phần trích dẫn cũ).
"""

import json
import re
import unicodedata

from src.domain.patterns import CONT_REGEX, PLATE_REGEX, TRAILER_PLATE_REGEX


def normalize_segment_text(text: str) -> str:
    """Chuẩn hóa Unicode NFC, đồng nhất xuống dòng và tách tiền tố viết dính liền biển số (VD: 'Xe15h00814' -> 'Xe 15h00814')."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = cleaned.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(
        r"(?i)\b(xe|bks|bsx|bs|bien|biển|so|số|mooc|rm)\s*([0-9]{2}[A-Za-z])",
        r"\1 \2",
        cleaned,
    )
    return cleaned.strip()


def detect_header_info(full_text: str) -> dict[str, str | None]:
    """Trích xuất ngữ cảnh chung ở 1-2 dòng đầu tin nhắn (hướng đóng/trả, ngày, giờ) để kế thừa xuống các xe con."""
    lines = [ln.strip() for ln in normalize_segment_text(full_text).split("\n") if ln.strip()]
    header = " ".join(lines[:2]).lower()
    res: dict[str, str | None] = {"order_type": None, "date_str": None, "time_str": None}
    if not header:
        return res

    if ("nhập" in header or "nhap" in header or "trả" in header or "tra" in header) and (
        "đóng" in header or "dong" in header
    ):
        res["order_type"] = None
    elif "đóng" in header or "dong" in header:
        res["order_type"] = "LOAD"
    elif "trả" in header or "tra" in header or "nhập" in header or "nhap" in header:
        res["order_type"] = "RETURN"

    dm = re.search(r"\b(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b", header)
    if dm:
        res["date_str"] = dm.group(1)

    tm = re.search(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b(?!\d)|\b([01]?\d|2[0-3])h\b(?!\d)", header)
    if tm and tm.group(0) != res["date_str"]:
        res["time_str"] = tm.group(0)
    return res


class MessageSegmenter:
    """Bộ phân tách tin nhắn phức hợp 2 giai đoạn (Macro + Micro Inline) thành danh sách khối từng xe."""

    _PLATE_REGEX = PLATE_REGEX
    _TRAILER_PLATE_REGEX = TRAILER_PLATE_REGEX
    _SWAP_PLATE_REGEX = re.compile(
        r"(?:đổi|doi|thay)\s+(?:xe\s+|từ\s+|tu\s+)?\d{2}[A-Za-zĐđ]{1,2}[ \t\u00a0.\-/]*\d{3,6}(?:\.\d{2,3})?\s+(?:sang|qua|thành|thanh|bằng|bang)\s+(?:xe\s+)?\d{2}[A-Za-zĐđ]{1,2}[ \t\u00a0.\-/]*\d{3,6}(?:\.\d{2,3})?",
        re.IGNORECASE,
    )
    _CONT_REGEX = CONT_REGEX
    _TABLE_HEADER_REGEX = re.compile(
        r"^(?:\|\s*)?(?:stt|tt)\s*[|\t].*(?:biển\s*số|bien\s*so|\bxe\b|\bcont|container|tài\s*xế|tai\s*xe|sđt|sdt|điện\s*thoại)"
        r"|^(?:biển\s*số|bien\s*so)\s*[|\t]\s*(?:container|cont)\s*[|\t]\s*(?:tài\s*xế|tai\s*xe)",
        re.IGNORECASE,
    )

    @classmethod
    def _is_table_header_line(cls, line: str) -> bool:
        """Nhận diện dòng tiêu đề cột bảng để loại bỏ khỏi quá trình ghép tên tài xế/chuyến."""
        stripped = (line or "").strip()
        if not stripped or any(ch.isdigit() for ch in stripped):
            return False
        return bool(cls._TABLE_HEADER_REGEX.search(stripped))

    @classmethod
    def _try_segment_json(cls, text: str) -> list[str]:
        """Chuyển đổi payload JSON đơn hoặc mảng JSON nhiều chuyến thành các khối chuẩn hóa."""
        stripped = (text or "").strip()
        if not (stripped.startswith("{") or stripped.startswith("[")):
            return []
        try:
            payload = json.loads(stripped)
        except (ValueError, TypeError):
            return []

        items = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
        if not items or not all(isinstance(x, dict) for x in items):
            return []

        blocks: list[str] = []
        for obj in items:
            norm_map = {str(k).strip().lower(): v for k, v in obj.items() if v is not None and str(v).strip() not in ("", "—", "-", "null", "None")}
            lines: list[str] = []
            plate = norm_map.get("xe") or norm_map.get("plate") or norm_map.get("truck_plate") or norm_map.get("bks") or norm_map.get("bien_so")
            cont = norm_map.get("cont") or norm_map.get("container") or norm_map.get("container_no")
            driver = norm_map.get("tai") or norm_map.get("tx") or norm_map.get("driver") or norm_map.get("driver_name") or norm_map.get("tai_xe")
            phone = norm_map.get("sdt") or norm_map.get("dt") or norm_map.get("phone") or norm_map.get("driver_phone")
            if plate:
                lines.append(f"Xe: {plate}")
            if cont:
                lines.append(f"Cont: {cont}")
            if driver:
                lines.append(f"Tài xế: {driver}")
            if phone:
                lines.append(f"SĐT: {phone}")
            if lines:
                blocks.append("\n".join(lines))
        return blocks

    @classmethod
    def _try_segment_indexed_fragments(cls, text: str) -> list[str]:
        """Gom các dòng rời rạc hoặc phân tách theo phần (`--- XE ---`, `#k xe:`, `#k tài`) về đúng từng chuyến `#k`."""
        raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        idx_line_re = re.compile(r"^#(\d{1,3})\b\s*[:\-]?\s*(.+)$")
        section_re = re.compile(r"^-{2,}\s*(.+?)\s*-{2,}$")

        indexed_count = sum(1 for ln in raw_lines if idx_line_re.match(ln))
        has_sections = any(section_re.match(ln) for ln in raw_lines)
        if indexed_count < 2:
            return []
        # Cần ít nhất dấu hiệu đa phần/đa dòng theo cùng index #k hoặc tiêu đề section
        seen_indices: list[int] = []
        grouped: dict[int, list[str]] = {}
        current_section_label = ""
        duplicate_index = False

        for ln in raw_lines:
            sec_m = section_re.match(ln)
            if sec_m:
                sec_name = sec_m.group(1).strip().upper()
                if "XE" in sec_name:
                    current_section_label = "Xe"
                elif "CONT" in sec_name:
                    current_section_label = "Cont"
                elif "TÀI" in sec_name or "TAI" in sec_name:
                    current_section_label = "Tài xế"
                elif "SĐT" in sec_name or "SDT" in sec_name or "ĐIỆN THOẠI" in sec_name:
                    current_section_label = "SĐT"
                else:
                    current_section_label = ""
                continue

            m = idx_line_re.match(ln)
            if not m:
                continue
            trip_idx = int(m.group(1))
            body = m.group(2).strip()
            if not body:
                continue
            if trip_idx in grouped:
                duplicate_index = True
            else:
                grouped[trip_idx] = []
                seen_indices.append(trip_idx)

            if current_section_label and not re.match(r"^(?:xe|cont|container|tài|tai|tx|sđt|sdt|đt)\b", body, flags=re.IGNORECASE):
                if current_section_label == "Tài xế" and (cls._PLATE_REGEX.search(body) or cls._CONT_REGEX.search(body)):
                    grouped[trip_idx].append(body)
                else:
                    grouped[trip_idx].append(f"{current_section_label}: {body}")
            else:
                # Chuẩn hóa "#1 xe: 72H00704" hoặc "#1 tài LÂM ÚT ĐẠI, số 0396..." thành dòng sạch
                grouped[trip_idx].append(body)

        if not (duplicate_index or has_sections):
            return []
        return ["\n".join(grouped[idx]) for idx in seen_indices if grouped.get(idx)]

    @classmethod
    def _non_trailer_plates(cls, text: str) -> list[str]:
        """Lọc danh sách biển số đầu kéo (loại bỏ biển rơ-moóc có hậu tố R/RM)."""
        plates: list[str] = []
        for m in cls._PLATE_REGEX.finditer(text):
            val = m.group(0).strip()
            if cls._TRAILER_PLATE_REGEX.fullmatch(val):
                continue
            plates.append(val)
        return plates

    @classmethod
    def _split_inline_multi_trips(cls, text: str) -> list[str]:
        """Tách nhiều chuyến xe viết dồn trên cùng một hàng (`///`, `||`, `[CHUYẾN k]`, `;`, `...`, `,`, đánh số, hoặc lặp biển số)."""
        if "\n" in text.strip():
            return []
        non_trailer = cls._non_trailer_plates(text)
        if len(non_trailer) < 2:
            return []

        # 1. Ngăn cách rõ bằng dấu `///`, `||`, `;` hoặc dấu ba chấm `...` / `…`
        for delim_pat in (r"\s*///\s*", r"\s*\|\|\s*", r"\s*;\s*", r"\s*(?:\.{3,}|…+)\s*"):
            parts = [p.strip() for p in re.split(delim_pat, text) if p.strip()]
            valid_parts = [
                p for p in parts if cls._non_trailer_plates(p) or cls._CONT_REGEX.search(p)
            ]
            if (
                len(parts) >= 2
                and len(valid_parts) == len(parts)
                and len([p for p in valid_parts if cls._non_trailer_plates(p)]) >= 2
            ):
                return valid_parts

        # 2. Nhãn thẻ chuyến liên tiếp trên cùng hàng: `[CHUYẾN 1] ... [CHUYẾN 2] ...` hoặc `Chuyến 1: ... Chuyến 2: ...`
        tag_split = re.split(
            r"(?:(?<=^)|(?<=[\s,|/]))(?=(?:\[CHUYẾN\s*\d+\]|\[CHUYEN\s*\d+\]|chuyến\s*\d+\s*[:\-]|chuyen\s*\d+\s*[:\-]))",
            text,
            flags=re.IGNORECASE,
        )
        tag_parts = [p.strip(" ,;|/") for p in tag_split if p.strip(" ,;|/")]
        if len([p for p in tag_parts if cls._non_trailer_plates(p) or cls._CONT_REGEX.search(p)]) >= 2:
            return [p for p in tag_parts if cls._non_trailer_plates(p) or cls._CONT_REGEX.search(p)]

        # 3. Đánh số thứ tự hoặc nhãn xe trên cùng một hàng: `1) ... 2) ...`, `2)72C...`, `1. ... 2. ...`, `Xe 1: ... Xe 2: ...`
        inline_numbered = re.split(
            r"(?:(?<=^)|(?<=[\s,|/;]))(?=(?:xe\s*\d+\s*[:\-]|\d{1,2}[\.\)]\s*(?=[A-Za-z0-9À-ỹ])))",
            text,
            flags=re.IGNORECASE,
        )
        num_parts = [p.strip(" ,|/;") for p in inline_numbered if p.strip(" ,|/;")]
        if len([p for p in num_parts if cls._non_trailer_plates(p)]) >= 2:
            return [p for p in num_parts if cls._non_trailer_plates(p) or cls._CONT_REGEX.search(p)]

        # 3b. Ngăn cách nội dòng bằng `/` hoặc `;` ngay trước xe kế tiếp (VD: '/ Xe 15H00814', '/ 72C-64021') — không cắt trước rơ-moóc R/RM
        if not cls._SWAP_PLATE_REGEX.search(text):
            slash_parts = re.split(
                r"[/;]\s*(?=(?:xe|bks|bsx|bs|số\s*xe)\s*[0-9]{2}(?![A-Za-z]?R[M]?\b)[A-Za-z]"
                r"|\b[0-9]{2}(?![A-Za-z]?R[M]?(?:[\s.\-/]|\d))[A-Za-z]{1,2}[\s.\-/]*(?:\d{3}[\s.\-]\d{1,3}|\d{4,6})\b"
                r"|\d{1,2}[\.\)]\s*)",
                text,
                flags=re.IGNORECASE,
            )
            slash_valid = [p.strip(" ,|/;") for p in slash_parts if p.strip(" ,|/;")]
            if len([p for p in slash_valid if cls._non_trailer_plates(p)]) >= 2:
                return [p for p in slash_valid if cls._non_trailer_plates(p) or cls._CONT_REGEX.search(p)]

        # 4. Ngăn cách bằng dấu phẩy `,` hoặc dấu `|` khi mỗi đoạn đều có biển số đầu kéo riêng
        for delim_pat in (r"\s*\|\s*", r"\s*,\s*"):
            parts = [p.strip() for p in re.split(delim_pat, text) if p.strip()]
            if len([p for p in parts if cls._non_trailer_plates(p)]) >= 2 and all(
                cls._non_trailer_plates(p) for p in parts
            ):
                return parts

        # 5. Nhiều chuyến viết liền chỉ bằng khoảng trắng (tách trước từng biển số đầu kéo / tiền tố "xe ")
        tractor_matches = [
            m for m in cls._PLATE_REGEX.finditer(text) if not cls._TRAILER_PLATE_REGEX.fullmatch(m.group(0).strip())
        ]
        if len(tractor_matches) >= 2:
            split_indices: list[int] = [0]
            for m in tractor_matches[1:]:
                prefix_window = text[max(0, m.start() - 12) : m.start()]
                xe_m = re.search(r"(?:^|\s)(?:xe|bks|biển(?:\s*số)?)\s*[:\-]?\s*$", prefix_window, flags=re.IGNORECASE)
                if xe_m:
                    idx = max(0, m.start() - 12) + xe_m.start()
                    if text[idx].isspace():
                        idx += 1
                else:
                    idx = m.start()
                if idx > split_indices[-1]:
                    split_indices.append(idx)
            if len(split_indices) >= 2:
                chunks: list[str] = []
                for i, start in enumerate(split_indices):
                    end = split_indices[i + 1] if i + 1 < len(split_indices) else len(text)
                    chunk = text[start:end].strip(" ,;|\t")
                    if chunk:
                        chunks.append(chunk)
                if len([c for c in chunks if cls._non_trailer_plates(c)]) >= 2:
                    return chunks

        return []
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
        cleaned_text = normalize_segment_text(main_text)

        # Tiền xử lý JSON payload (1 object hoặc json_array nhiều chuyến)
        json_blocks = cls._try_segment_json(cleaned_text)
        if json_blocks:
            return json_blocks

        # Gom các dòng phân mảnh hoặc đan xen theo chỉ số `#1`, `#2`, ... + section header (`--- XE ---`)
        indexed_blocks = cls._try_segment_indexed_fragments(cleaned_text)
        if indexed_blocks:
            return indexed_blocks

        # Loại bỏ dòng tiêu đề bảng cột (STT | BIỂN SỐ | ...) để tránh nhiễu nhận diện nhãn/F1
        lines = [
            ln.strip()
            for ln in cleaned_text.split("\n")
            if ln.strip() and not cls._is_table_header_line(ln)
        ]
        if not lines:
            return []
        cleaned_no_header = "\n".join(lines)

        # Nếu toàn bộ tin nhắn chỉ có tối đa 1 biển số đầu kéo (không tính rơ-moóc) và 1 số container -> chắc chắn là 1 khối duy nhất (F2/F3 nhiều dòng)
        non_trailer_plates = cls._non_trailer_plates(cleaned_no_header)
        all_conts = cls._CONT_REGEX.findall(cleaned_no_header)
        if len(non_trailer_plates) <= 1 and len(all_conts) <= 1:
            return [cleaned_no_header]
        # Trường hợp câu đổi xe A sang B (2 biển số đều thuộc 1 chuyến duy nhất)
        if len(non_trailer_plates) == 2 and len(all_conts) <= 1 and cls._SWAP_PLATE_REGEX.search(cleaned_no_header):
            return [cleaned_no_header]

        # Trường hợp 0: Tin nhắn viết dồn nhiều chuyến trên cùng 1 hàng (hỗ trợ cả >10 chuyến/tin)
        inline_trips = cls._split_inline_multi_trips(cleaned_no_header)
        if len(inline_trips) >= 2:
            return inline_trips

        # Trường hợp 1: Phân đoạn theo ranh giới xe/chuyến rõ ràng (Chuyến k:, [CHUYẾN k], #k, 1., 2., 🚛, Biển số:, BKS:)
        # Lưu ý: Không tách theo nhãn "Cont:" đơn lẻ vì F2 nhiều dòng có "Xe: ..." ở trên và "Cont: ..." ở dưới thuộc cùng 1 xe.
        vehicle_split = re.split(
            r"(?m)(?=^[ \t]*(?:[🚛🚚🚗🏎️🚜]|\[?chuyến\s*\d+\]?\s*[:\-]?|\[?chuyen\s*\d+\]?\s*[:\-]?|#\d{1,3}\b|\d{1,2}[\.\)]\s+(?=[A-Za-z0-9À-ỹ])|(?:xe\s*\d+|biển\s*số|bien\s*so|bks|số\s*xe|so\s*xe|đầu\s*kéo|dau\s*keo)\s*[:\-])\s*)",
            cleaned_no_header,
            flags=re.IGNORECASE,
        )
        vehicle_parts = [p.strip() for p in vehicle_split if p.strip()]
        vehicle_candidates = [
            p for p in vehicle_parts if cls._non_trailer_plates(p) or cls._CONT_REGEX.search(p)
        ]
        if len(vehicle_candidates) >= 2:
            first_has_vehicle = bool(
                cls._non_trailer_plates(vehicle_parts[0]) or cls._CONT_REGEX.search(vehicle_parts[0])
            )
            if not first_has_vehicle and len(vehicle_parts) >= 3:
                header = vehicle_parts[0]
                return [
                    f"{header}\n{b}".strip()
                    for b in vehicle_parts[1:]
                    if cls._non_trailer_plates(b) or cls._CONT_REGEX.search(b)
                ]
            if first_has_vehicle:
                return vehicle_candidates

        # Trường hợp 2: Kiểm tra F1 / Bảng dòng - Mỗi dòng tự thân là 1 chuyến (`/` , `|`, `\t`, `—`, `,`)
        lines_with_plate = [ln for ln in lines if cls._non_trailer_plates(ln)]
        if len(lines_with_plate) >= 2:
            # Nhận diện dòng chỉ là nhãn trường F2 (không chứa đủ cặp bảng phân cột)
            labeled_field_lines = [
                ln for ln in lines
                if "|" not in ln
                and "\t" not in ln
                and re.match(
                    r"^(?:[👤👨🧑🪪📞📱☎️📦🏷️🧰🚛🚚🚗]|tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|sđt|sdt|đt|số\s*cont|so\s*cont|cont|seal|số\s*chì|bks|biển\s*số)\b|^[👤👨🧑🪪📞📱☎️📦🏷️🧰🚛🚚🚗]",
                    ln,
                    flags=re.IGNORECASE,
                )
            ]
            if not labeled_field_lines:
                results: list[str] = []
                active_headers: list[str] = []
                for ln in lines:
                    has_plate = bool(cls._non_trailer_plates(ln))
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
            if blk.strip() and not cls._is_table_header_line(blk)
        ]
        if len(raw_blocks) >= 2:
            vehicle_blocks: list[str] = []
            current_context_headers: list[str] = []
            for blk in raw_blocks:
                if cls._non_trailer_plates(blk) or cls._CONT_REGEX.search(blk):
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
                cls._non_trailer_plates(numbered_blocks[0])
                or cls._CONT_REGEX.search(numbered_blocks[0])
            )
            if not first_has_vehicle and len(numbered_blocks) >= 3:
                header = numbered_blocks[0]
                return [f"{header}\n{b}".strip() for b in numbered_blocks[1:]]
            if first_has_vehicle:
                return numbered_blocks

        # Trường hợp 5: Nhiều khối nhiều dòng liên tiếp không có dòng trống, mỗi khối bắt đầu bằng "Biển số:" / "BKS:" / "Số xe:"
        bks_split = re.split(
            r"(?m)(?=^(?:biển\s*số|bien\s*so|bks|số\s*xe|so\s*xe|đầu\s*kéo|dau\s*keo)\s*[:\-])",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        bks_blocks = [b.strip() for b in bks_split if b.strip()]
        if len(bks_blocks) >= 2:
            first_has_plate = bool(cls._non_trailer_plates(bks_blocks[0]))
            if not first_has_plate and len(bks_blocks) >= 3:
                header = bks_blocks[0]
                return [f"{header}\n{b}".strip() for b in bks_blocks[1:]]
            if first_has_plate:
                return bks_blocks

        # Mặc định: Toàn bộ tin nhắn là 1 khối duy nhất (kèm ngữ cảnh trích dẫn nếu bản thân tin mới chỉ bổ sung thông tin)
        if quoted_text and len(cleaned_text.splitlines()) <= 2:
            return [f"{quoted_text}\n{cleaned_text}".strip()]
        return [cleaned_text]
