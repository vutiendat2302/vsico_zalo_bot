"""Module Bóc Tách Thông Tin Xe Đầu Kéo & Container Chuẩn Hóa F1 / F2 / F3 / Tự Do.

Xử lý chính xác 3 định dạng đầu vào chuẩn của VSICO (F1, F2, F3) cùng mọi biến thể tự do
theo Bảng 1 (1.1 -> 1.6) và Bảng 2 (T01 -> T40), chuyển đổi mọi tin nhắn về cùng một
**Bản ghi chuẩn (Canonical Record)** — mỗi container một bản ghi.
"""

from datetime import datetime, timedelta
import re
from typing import Optional

from src.domain.enums import OrderType
from src.domain.models import ExtractedContainerLine
from src.domain.patterns import (
    CONT_REGEX,
    PHONE_MALFORMED_REGEX,
    PHONE_PATTERN,
    PLATE_REGEX,
    TRAILER_PLATE_REGEX,
)
from src.domain.rules import (
    clean_container,
    clean_driver_name,
    clean_phone,
    clean_plate,
)
from src.messaging.segmenter import MessageSegmenter, detect_header_info, normalize_segment_text


class TripParser:
    """Bộ bóc tách dữ liệu chuyến xe và container chuẩn hóa F1, F2, F3 và Tự do."""

    _PLATE_REGEX = PLATE_REGEX
    _TRAILER_PLATE_REGEX = TRAILER_PLATE_REGEX
    _CONTAINER_STD_REGEX = CONT_REGEX
    _CONTAINER_MALFORMED_REGEX = re.compile(
        r"(?<![A-Za-z0-9])([A-Za-z]{3}[UJZujz](?:[ \t\u00a0.\-]*\d){3,9})(?![A-Za-z0-9])"
    )
    _PHONE_REGEX = PHONE_PATTERN
    _PHONE_MALFORMED_REGEX = PHONE_MALFORMED_REGEX
    _SIZE_REGEX = re.compile(
        r"\b(?:\d+\s*[xX]\s*(20|40|45)(?:DC|GP|RF|OT|FR|HC|HQ)?|(20\s*(?:DC|GP|RF|OT|FR|HC|HQ|FT|')|40\s*(?:HC|HQ|DC|GP|RF|OT|FR|FT|')|45\s*(?:HC|HQ|DC|FT|'))|(?:cont|loại|loai|size|cỡ|co)\s*(20|40|45)|\b(20DC|40HC|40HQ|40RF|20RF|20GP|40GP)\b)",
        re.IGNORECASE,
    )

    @classmethod
    def detect_source_format(cls, text: str) -> str:
        """Nhận diện định dạng nguồn của tin nhắn: `'F1'`, `'F2'`, `'F3'` hoặc `'tu_do'`.

        - **F1**: Định dạng nhà xe miền Bắc, mỗi xe 1 dòng ngăn cách bằng dấu `/`.
        - **F2**: Định dạng ĐHVT HCM có dòng `Ngày: ... Đóng , Trả hàng:` hoặc các dòng gạch đầu dòng `- Tên lái xe:`, `- Số xe:`, `- Số seal:`.
        - **F3**: Định dạng mẫu chuẩn VSICO (`Khách hàng:`, `Lệnh:`, `Biển số xe:`, `Điểm đóng/trả:`).
        - **tu_do**: Các định dạng tự do khác (bảng `|`, 1 dòng không dấu phân cách, văn xuôi...).

        Args:
            text (str): Đoạn văn bản cần nhận diện.

        Returns:
            str: `'F1'`, `'F2'`, `'F3'` hoặc `'tu_do'`.
        """
        lower = text.lower()
        # Kiểm tra F3 (Mẫu chuẩn VSICO: có Điểm đóng/trả hoặc tổ hợp Khách hàng + Lệnh + Biển số xe)
        if re.search(r"điểm\s*đóng\s*/\s*trả|diem\s*dong\s*/\s*tra", lower) or (
            re.search(r"khách\s*hàng\s*:", lower)
            and re.search(r"lệnh\s*:", lower)
            and re.search(r"biển\s*số\s*xe\s*:", lower)
        ):
            return "F3"

        # Kiểm tra F2 (Mẫu ĐHVT HCM: Đóng , Trả hàng / Số seal / Thời gian xe đến kho / - Tên lái xe)
        if (
            re.search(r"đóng\s*[,/]\s*trả\s*hàng", lower)
            or re.search(r"số\s*seal\s*:", lower)
            or re.search(r"thời\s*gian\s*xe\s*đến\s*kho", lower)
            or (re.search(r"-\s*tên\s*lái\s*xe\s*:", lower) and re.search(r"-\s*số\s*xe\s*:", lower))
        ):
            return "F2"

        # Kiểm tra F1 (Mỗi xe 1 dòng ngăn bằng dấu '/' và có biển số + cont/SĐT)
        for ln in text.splitlines():
            if ln.count("/") >= 2 and cls._PLATE_REGEX.search(ln):
                return "F1"

        return "tu_do"

    @classmethod
    def parse_message(
        cls,
        raw_text: str,
        reference_time: Optional[datetime] = None,
    ) -> list[ExtractedContainerLine]:
        """Phân đoạn và bóc tách toàn bộ danh sách dòng xe/container từ một tin nhắn Zalo.

        Args:
            raw_text (str): Nội dung tin nhắn gốc của nhà xe.
            reference_time (Optional[datetime]): Mốc thời gian nhận tin nhắn.

        Returns:
            list[ExtractedContainerLine]: Danh sách các dòng container (mỗi container 1 bản ghi chuẩn).
        """
        overall_format = cls.detect_source_format(raw_text)
        header_info = detect_header_info(raw_text)
        blocks = MessageSegmenter.segment(raw_text)
        results: list[ExtractedContainerLine] = []
        line_counter = 1

        for block in blocks:
            extracted_list = cls.parse_block(
                block_text=block,
                start_line_no=line_counter,
                reference_time=reference_time,
                default_format=overall_format,
                header_info=header_info,
            )
            results.extend(extracted_list)
            line_counter += len(extracted_list)

        return results

    @classmethod
    def parse_block(
        cls,
        block_text: str,
        start_line_no: int = 1,
        reference_time: Optional[datetime] = None,
        default_format: Optional[str] = None,
        header_info: Optional[dict[str, Optional[str]]] = None,
    ) -> list[ExtractedContainerLine]:
        """Bóc tách thông tin từ một khối văn bản đơn lẻ sang danh sách `ExtractedContainerLine`.

        Args:
            block_text (str): Đoạn văn bản của khối xe cần bóc tách.
            start_line_no (int): Số thứ tự dòng bắt đầu.
            reference_time (Optional[datetime]): Thời gian gửi tin nhắn để suy luận `plan_date` và `estimated_at`.
            default_format (Optional[str]): Định dạng tổng thể của tin nhắn (`F1`, `F2`, `F3`, `tu_do`).
            header_info (Optional[dict]): Ngữ cảnh chung trích từ 1-2 dòng đầu tin nhắn gốc.

        Returns:
            list[ExtractedContainerLine]: Danh sách đối tượng `ExtractedContainerLine`.
        """
        block_text = normalize_segment_text(block_text)
        source_format = default_format or cls.detect_source_format(block_text)
        if source_format == "tu_do":
            source_format = cls.detect_source_format(block_text)

        plan_date, parsed_plan_dt = cls._extract_plan_date(block_text, reference_time)
        if header_info and header_info.get("date_str") and not re.search(
            r"(?:ngày\s*chạy|ngay\s*chay|ngày|ngay)\s*[:\-]?\s*[\.,\s]*\d{1,2}[\/\-]\d{1,2}",
            block_text,
            flags=re.IGNORECASE,
        ):
            h_date, h_dt = cls._extract_plan_date(f"ngày {header_info['date_str']}", reference_time)
            if h_dt is not None:
                plan_date, parsed_plan_dt = h_date, h_dt
        effective_ref_time = parsed_plan_dt or reference_time or datetime.now()

        truck_plate, raw_truck_plate, trailer_plate, multiple_tractors = cls._extract_plates(block_text)
        driver_phone = cls._extract_phone(block_text)
        containers = cls._extract_containers(block_text)
        container_size = cls._extract_container_size(block_text)
        seal_no, is_seal_pending = cls._extract_seal(block_text, containers)
        booking_no = cls._extract_booking_no(block_text)
        order_type, inferred_order = cls._extract_order_type(block_text)
        if not order_type and header_info and header_info.get("order_type"):
            order_type = header_info["order_type"]
            inferred_order = True
        warehouse_hint = cls._extract_warehouse_hint(block_text)
        customer_hint = cls._extract_customer_hint(block_text)
        eta_text, eta_time, estimated_at, is_time_vague = cls._extract_eta(block_text, effective_ref_time)
        if not eta_time and header_info and header_info.get("time_str"):
            h_eta_text, h_eta_time, h_est, h_vague = cls._extract_eta(
                f"lúc {header_info['time_str']}", effective_ref_time
            )
            if h_eta_time:
                eta_text, eta_time, estimated_at, is_time_vague = h_eta_text, h_eta_time, h_est, h_vague
        is_container_pending = cls._check_container_pending(block_text)
        driver_name, driver_name_certain = cls._extract_driver_name_with_certainty(
            block_text,
            raw_truck_plate=raw_truck_plate,
            driver_phone=driver_phone,
            containers=containers,
            seal_no=seal_no,
        )

        # Khối có nhãn tường minh, bảng/dấu phân cách rõ hoặc mã lệnh kèm thực thể chính -> tin cậy cao (tránh gọi AI thừa)
        has_structured_cues = source_format in ("F1", "F2", "F3") or bool(
            re.search(
                r"[|｜\t;·•→—:/\\]|(?:^|[\s(\[])(?:xe|bks|biển(?:\s*số)?|bien(?:\s*so)?|cont|container|số\s*công|so\s*cong|tài\s*xế|tai\s*xe|tài|tx|lx|sđt|sdt|đt|seal|chì|booking|\bbk\b|lệnh|lenh|\b(?:ro|lo)\d{3,6})\b",
                block_text,
                flags=re.IGNORECASE,
            )
        )
        has_any_primary = bool(truck_plate or containers or driver_phone or booking_no or seal_no or eta_time)
        line_confidence = (
            0.92
            if (has_structured_cues and has_any_primary and (driver_name_certain or not driver_name))
            else (
                0.55
                if (source_format == "tu_do" and (not driver_name or not driver_name_certain))
                else 0.95
            )
        )
        has_conflict = len(multiple_tractors) >= 2 and len(containers) >= 2

        if containers:
            lines: list[ExtractedContainerLine] = []
            for idx, cont_no in enumerate(containers):
                lines.append(
                    ExtractedContainerLine(
                        line_no=start_line_no + idx,
                        line_text=block_text,
                        source_format=source_format,
                        plan_date=plan_date,
                        truck_plate=truck_plate,
                        raw_truck_plate=raw_truck_plate,
                        trailer_plate=trailer_plate,
                        driver_name=driver_name,
                        driver_phone=driver_phone,
                        container_no=cont_no,
                        container_size=container_size,
                        seal_no=seal_no,
                        booking_no=booking_no,
                        order_type=order_type,
                        inferred_order_type=inferred_order,
                        warehouse_hint=warehouse_hint,
                        customer_hint=customer_hint,
                        eta_text=eta_text,
                        eta_time=eta_time,
                        estimated_at=estimated_at,
                        is_time_vague=is_time_vague,
                        is_container_pending=is_container_pending,
                        is_seal_pending=is_seal_pending,
                        container_status="DEFERRED" if is_container_pending else "UNKNOWN",
                        seal_status="DEFERRED" if is_seal_pending else "UNKNOWN",
                        has_conflicting_mapping=has_conflict,
                        confidence=line_confidence,
                    )
                )
            return lines

        return [
            ExtractedContainerLine(
                line_no=start_line_no,
                line_text=block_text,
                source_format=source_format,
                plan_date=plan_date,
                truck_plate=truck_plate,
                raw_truck_plate=raw_truck_plate,
                trailer_plate=trailer_plate,
                driver_name=driver_name,
                driver_phone=driver_phone,
                container_no=None,
                container_size=container_size,
                seal_no=seal_no,
                booking_no=booking_no,
                order_type=order_type,
                inferred_order_type=inferred_order,
                warehouse_hint=warehouse_hint,
                customer_hint=customer_hint,
                eta_text=eta_text,
                eta_time=eta_time,
                estimated_at=estimated_at,
                is_time_vague=is_time_vague,
                is_container_pending=is_container_pending,
                is_seal_pending=is_seal_pending,
                container_status="DEFERRED" if is_container_pending else "UNKNOWN",
                seal_status="DEFERRED" if is_seal_pending else "UNKNOWN",
                has_conflicting_mapping=has_conflict,
                confidence=line_confidence,
            )
        ]

    @classmethod
    def _extract_plan_date(
        cls,
        text: str,
        reference_time: Optional[datetime] = None,
    ) -> tuple[str, Optional[datetime]]:
        """Trích xuất ngày kế hoạch đóng/trả (`plan_date` chuẩn `YYYY-MM-DD`).

        - Nếu có dòng `Ngày: .9/10/2026` (như trong F2, kể cả có dấu chấm thừa trước ngày): lấy ngày đó.
        - Nếu không có dòng Ngày (như trong F1, F3): mặc định lấy ngày gửi tin (`reference_time`).

        Args:
            text (str): Đoạn văn bản cần tìm ngày.
            reference_time (Optional[datetime]): Thời điểm gửi/nhận tin nhắn.

        Returns:
            tuple[str, Optional[datetime]]: Cặp `(plan_date_str, datetime_obj)`.
        """
        ref = reference_time or datetime.now()
        # Bắt dòng "Ngày: .9/10/2026" hoặc "Ngày chạy: 27/10" (bỏ qua dấu chấm/khoảng trắng thừa trước số ngày)
        date_match = re.search(
            r"(?:ngày\s*chạy|ngay\s*chay|ngày|ngay)\s*[:\-]?\s*[\.,\s]*(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\b",
            text,
            flags=re.IGNORECASE,
        )
        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year_raw = date_match.group(3)
            year = int(year_raw) if year_raw else ref.year
            if year < 100:
                year += 2000
            try:
                dt = datetime(year, month, day, ref.hour, ref.minute)
                return dt.strftime("%Y-%m-%d"), dt
            except ValueError:
                pass

        return ref.strftime("%Y-%m-%d"), ref

    @classmethod
    def _extract_plates(
        cls, text: str
    ) -> tuple[Optional[str], Optional[str], Optional[str], list[str]]:
        """Trích xuất biển số xe đầu kéo, chuỗi biển số thô, biển số rơ-moóc và danh sách đầu kéo."""
        truck_plate: Optional[str] = None
        raw_truck_plate: Optional[str] = None
        trailer_plate: Optional[str] = None
        tractor_list: list[str] = []

        explicit_mooc = re.search(
            r"(?:rơ\s*[\-\s]*moóc|ro\s*[\-\s]*mooc|biển\s*mooc|bien\s*mooc|số\s*mooc|so\s*mooc|\bmooc\b|\brm\b)[ \t]*[:\-]?[ \t]*([0-9A-Za-z.\-]{5,12})",
            text,
            flags=re.IGNORECASE,
        )
        if explicit_mooc:
            trailer_plate = clean_plate(explicit_mooc.group(1))

        # 1. Quét riêng biển số rơ-moóc (seri R/RM) bằng _TRAILER_PLATE_REGEX
        for tr_match in cls._TRAILER_PLATE_REGEX.finditer(text):
            norm_tr = clean_plate(tr_match.group(0).strip())
            if norm_tr and trailer_plate is None:
                trailer_plate = norm_tr

        # 2. Quét biển số đầu kéo bằng _PLATE_REGEX (đã loại trừ trực tiếp seri R/RM)
        for match in cls._PLATE_REGEX.finditer(text):
            raw_candidate = match.group(0).strip()
            normalized = clean_plate(raw_candidate)
            if not normalized:
                continue

            prefix_part = normalized.split("-")[0]
            if re.search(r"R[M]?$", prefix_part, flags=re.IGNORECASE):
                if trailer_plate is None:
                    trailer_plate = normalized
            elif trailer_plate and normalized == trailer_plate:
                continue
            else:
                if normalized not in tractor_list:
                    tractor_list.append(normalized)
                if truck_plate is None:
                    truck_plate = normalized
                    raw_truck_plate = raw_candidate

        # Xử lý câu đổi xe từ <cũ> sang <mới> khi chỉ có tối đa 1 chuyến để lấy biển số xe mới làm chuẩn
        swap_match = re.search(
            r"(?:đổi|doi|thay)\s+(?:xe\s+|từ\s+|tu\s+)?(\d{2}[A-Za-z]{1,2}[\s.\-/]*\d{3,6}(?:\.\d{2,3})?)\s+(?:sang|qua|thành|thanh|bằng|bang)\s+(?:xe\s+)?(\d{2}[A-Za-z]{1,2}[\s.\-/]*\d{3,6}(?:\.\d{2,3})?)",
            text,
            flags=re.IGNORECASE,
        )
        if swap_match:
            new_norm = clean_plate(swap_match.group(2))
            if new_norm and not re.search(r"R[M]?$", new_norm.split("-")[0], flags=re.IGNORECASE):
                truck_plate = new_norm
                raw_truck_plate = swap_match.group(2).strip()
                tractor_list = [new_norm]

        return truck_plate, raw_truck_plate, trailer_plate, tractor_list

    @classmethod
    def _extract_phone(cls, text: str) -> Optional[str]:
        """Trích xuất toàn bộ SĐT tài xế trong khối xe (hỗ trợ 2+ SĐT ngăn cách bởi `' | '`, VD: `'0394251493 | 0984131254'`).

        Loại trừ các dãy số nằm ngay sau nhãn CCCD/CMND, Số chì/Seal hoặc dính trong số Container.
        Vẫn giữ lại SĐT thiếu/thừa số (8-12 ký tự) để `ContainerValidator` phát hiện và nhắc nhà xe.
        """
        # Loại bỏ các dòng/cụm CCCD, CMND, số seal/chì có nhãn để tránh nhận nhầm làm SĐT
        sanitized = re.sub(
            r"\b(?:cccd|cmnd|căn\s*cước|can\s*cuoc|chứng\s*minh|chung\s*minh|số\s*chì|so\s*chi|số\s*seal|so\s*seal|seal|chì|chi)\s*[:\-]?\s*[A-Za-z0-9\-]+",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        # Tách ranh giới nhãn điện thoại bị gõ dính hoặc lặp chữ (VD: SDDT0345032001, SDT09..., SĐT03..., DT09..., LH08...)
        sanitized = re.sub(
            r"(?<![A-Za-z0-9])(s+d+đ*t+|s+đ+t+|d+t+|đ+t+|tel|lh|hl|zalo|phone|call)\s*[:.\-]?(?=(?:\+?84|0)[35789](?:[ \t\u00a0.\-]?\d){6,9}(?![\dxX*]))",
            r"\1 ",
            sanitized,
            flags=re.IGNORECASE,
        )
        phones: list[str] = []
        matched_spans: list[tuple[int, int]] = []
        for match in cls._PHONE_REGEX.finditer(sanitized):
            raw_tok = match.group(0)
            cleaned = clean_phone(raw_tok)
            if cleaned and 8 <= len(cleaned) <= 12 and cleaned not in phones:
                phones.append(cleaned)
                matched_spans.append(match.span())

        # Bổ sung bắt SĐT di động bị thiếu/thừa 1 chữ số (VD: 098736941) để Validator báo lỗi nhắc nhà xe
        for match in cls._PHONE_MALFORMED_REGEX.finditer(sanitized):
            s_idx, e_idx = match.span()
            if any(not (e_idx <= ms or s_idx >= me) for ms, me in matched_spans):
                continue
            cleaned = clean_phone(match.group(0))
            if cleaned and 8 <= len(cleaned) <= 12 and cleaned not in phones:
                phones.append(cleaned)
                matched_spans.append((s_idx, e_idx))

        if not phones:
            return None
        return " | ".join(phones)

    @classmethod
    def _extract_containers(cls, text: str) -> list[str]:
        """Trích xuất danh sách tất cả các số hiệu container (chuẩn ISO 6346 hoặc viết sai định dạng T18)."""
        containers: list[str] = []

        for match in cls._CONTAINER_STD_REGEX.finditer(text):
            cleaned = clean_container(match.group(0))
            if cleaned and cleaned not in containers:
                containers.append(cleaned)

        sanitized_for_cont = re.sub(
            r"\b(?:cccd|cmnd|căn\s*cước|can\s*cuoc|số\s*chì|so\s*chi|số\s*seal|so\s*seal|seal|chì|chi|booking|\bbk\b|\bbl\b)\s*[:\-]?\s*[A-Za-z0-9\-]+",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        label_matches = re.finditer(
            r"(?:số\s*container|so\s*container|số\s*cont|so\s*cont|container|\bcntr\b|\bcont\b)[ \t]*[:\-]?[ \t]*([A-Za-z]{2,5}(?:[ \t.\-]?\d){3,9})\b",
            sanitized_for_cont,
            flags=re.IGNORECASE,
        )
        for lm in label_matches:
            token = lm.group(1).strip()
            if re.match(r"^(?:20|40|45)", token):
                continue
            cleaned = clean_container(token)
            if not cleaned:
                continue
            letter_count = sum(1 for ch in cleaned if ch.isalpha())
            if letter_count < 3 or re.match(r"^(?:RO|LO|BK|BL|DR|VS|HL|CCCD|CMND|SEAL)\d", cleaned):
                continue
            if (
                cleaned not in containers
                and not any(ex.startswith(cleaned) or cleaned.startswith(ex) for ex in containers)
            ):
                containers.append(cleaned)

        if not containers:
            for mm in cls._CONTAINER_MALFORMED_REGEX.finditer(sanitized_for_cont):
                cleaned = clean_container(mm.group(1))
                if cleaned and cleaned not in containers:
                    containers.append(cleaned)

        return containers

    @classmethod
    def _check_container_pending(cls, text: str) -> bool:
        """Kiểm tra xem tin nhắn có ghi nhận trạng thái chưa có số container hay không (T10)."""
        return bool(
            re.search(
                r"(?:chưa\s*lấy\s*cont|chua\s*lay\s*cont|chờ\s*cấp\s*cont|cho\s*cap\s*cont|"
                r"chưa\s*biết\s*số|chua\s*biet\s*so|chưa\s*có\s*(?:số\s*)?cont|chua\s*co\s*(?:so\s*)?cont|"
                r"cont\s*báo\s*sau|cont\s*bao\s*sau|bổ\s*sung\s*cont\s*sau)",
                text,
                flags=re.IGNORECASE,
            )
        )

    @classmethod
    def _extract_driver_name(
        cls,
        text: str,
        raw_truck_plate: Optional[str],
        driver_phone: Optional[str],
        containers: list[str],
        seal_no: Optional[str],
    ) -> Optional[str]:
        """Trích xuất họ tên tài xế trên cả F1, F2, F3 và Tự do."""
        name, _ = cls._extract_driver_name_with_certainty(
            text=text,
            raw_truck_plate=raw_truck_plate,
            driver_phone=driver_phone,
            containers=containers,
            seal_no=seal_no,
        )
        return name

    @classmethod
    def _extract_driver_name_with_certainty(
        cls,
        text: str,
        raw_truck_plate: Optional[str],
        driver_phone: Optional[str],
        containers: list[str],
        seal_no: Optional[str],
    ) -> tuple[Optional[str], bool]:
        """Trích xuất họ tên tài xế kèm mức độ chắc chắn (`certain=True` với nhãn/F1/bảng, `False` với đoán từ văn xuôi tự do)."""
        stop_words_regex = re.compile(
            r"\b(?:đóng|dong|trả|tra|hạ|ha|kho|nhà\s*máy|nha\s*may|khách|khach|cont|container|cntr|"
            r"seal|chì|chi|booking|lệnh|lenh|hàng|hang|xuất|xuat|nhập|nhap|cảng|cang|kcn|bãi|bai|"
            r"biển\s*số|bien\s*so|bks|mooc|dự\s*kiến|du\s*kien|eta|thông\s*báo|thong\s*bao|"
            r"danh\s*sách|danh\s*sach|kế\s*hoạch|ke\s*hoach|điều\s*xe|dieu\s*xe|chưa|chua|chờ|cho|kính\s*gửi|"
            r"stt|điện\s*thoại|dien\s*thoai|thông\s*tin\s*chuyến|chuyến|chuyen|báo\s*chuyến|bao\s*chuyen|"
            r"hôm\s*nay|hom\s*nay|cảm\s*ơn|cam\s*on|xác\s*nhận|xac\s*nhan|nhờ|nho|"
            r"bổ\s*sung|bo\s*sung|cập\s*nhật|cap\s*nhat|đính\s*chính|dinh\s*chinh|thay\s*đổi|thay\s*doi|"
            r"nhé|nhe|nha|ơi|oi|ạ|giúp|giup|xong|rồi|roi|đã|sắp|sap|xếp|xep|đổi|doi|vẫn|van|"
            r"nữa|nua|bận|ban|kẹt|ket|chạy|chay|thấy|thay|giữ|giu|vâng|vang|dạ|ok|không|khong|"
            r"nx|báo|bao|xe|tại|lúc|hẹn|mới|cũ|bên|liệu|kiểm|check)\b",
            re.IGNORECASE,
        )
        table_header_re = re.compile(
            r"^(?:\|\s*)?(?:stt|tt)\s*[|\t]|^(?:biển\s*số|bien\s*so)\s*[|\t]\s*(?:container|cont)",
            re.IGNORECASE,
        )

        # Tiền làm sạch ký tự định dạng markdown / JSON nhẹ và chuẩn hóa dấu gạch nối đặc biệt
        sanitized_text = re.sub(r"[`*_~]+", "", text)
        sanitized_text = re.sub(r"[🚛🚚🚗🏎️🚜📞📱☎️]", " | ", sanitized_text)

        # Hàm cắt phần đuôi trường khác đi liền sau tên tài xế trên cùng một dòng (SĐT, cont, biển số, đóng/trả, hẹn giờ...)
        def _clip_inline_driver_tail(raw_cand: str) -> str:
            if not raw_cand:
                return ""
            m_tail = re.search(
                r"(?:\(\s*)?(?:(?:\+?84[\s.\-]?|0)\d[\d\s.\-*xX]{5,12}|"
                r"\b[A-Za-z]{4}[\s.\-]?\d{7}\b|"
                r"\b\d{2}[A-Za-z]{1,2}[\s.\-]?\d{3,6}(?:\.\d{1,3})?\b|"
                r"\b(?:sđt|sdt|đt|dt|tel|chưa\s*có\s*số|chua\s*co\s*so|chưa\s*có\s*sđt|chua\s*co\s*sdt|"
                r"nhận\s*chuyến|làm\s*hàng|giao\s*hàng|giao\s*cont|giữ\s*nguyên|rơ\s*moóc|"
                r"trả\s*hàng|tra\s*hang|trả\s*cont|tra\s*cont|trả\s*rỗng|tra\s*rong|hạ\s*cont|ha\s*cont|hạ\s*bãi|ha\s*bai|"
                r"tới\s*\d|đến\s*\d|sang\s*xe|đổi\s*sang|vào\s*kho|ra\s*cảng|"
                r"đóng|dong|trả|tra|cont|container|cntr|seal|chì|chi|booking|lệnh|lenh|"
                r"mooc|kcn|bks|eta|size|hẹn|hen|lúc|luc|tại|tai|kho|cảng|cang|bãi|bai|xe|"
                r"(?:20|40|45)\s*(?:dc|hc|gp|rf|hq))\b)",
                raw_cand,
                flags=re.IGNORECASE,
            )
            if m_tail and m_tail.start() > 0:
                prefix = raw_cand[:m_tail.start()].strip(" -:/,.;*|\t[]()\"'{}—–·•→#")
                if prefix:
                    return prefix
            return raw_cand

        # Hàm dọn ứng viên tên tài xế: bỏ SĐT, ngoặc, cụm hậu tố nghiệp vụ, giữ tối đa hậu tố 2 chữ số (VD "Lê Văn Duy 88")
        def _finalize_name(raw_cand: str) -> Optional[str]:
            if not raw_cand:
                return None
            # Cắt cụm hậu tố nghiệp vụ/báo thiếu đứng sau tên
            s = re.split(
                r"\b(?:sđt|sdt|đt|dt|chưa\s*có\s*số|chua\s*co\s*so|chưa\s*có\s*sđt|chua\s*co\s*sdt|nhận\s*chuyến|làm\s*hàng|giao\s*hàng|giữ\s*nguyên)\b",
                raw_cand,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            # Xóa SĐT lồng trong ngoặc hoặc cuối chuỗi
            s = re.sub(
                r"\(?\s*(?:sđt|sdt|đt|dt|tel|số)?\s*[:\-]?\s*(?:\+?84[\s.\-]?|0)\d[\d\s.\-*xX]{5,12}\)?",
                " ",
                s,
                flags=re.IGNORECASE,
            )
            s = re.sub(r"\s+(?:số|so)\s*$", "", s, flags=re.IGNORECASE)
            s = s.strip(" -:/,.;*|\t[]()\"'{}—–·•→#")
            if not s or len(s) < 2 or re.search(r"[:;|]", s):
                return None
            if cls._PLATE_REGEX.search(s) or cls._CONTAINER_STD_REGEX.search(s):
                return None
            if re.search(r"\b(?:LO|RO)\d+\b", s, re.IGNORECASE):
                return None
            if stop_words_regex.search(s):
                return None
            # Chấp nhận tên chuẩn không chứa số, hoặc họ tên 2+ từ có biệt danh 1-2 số ở cuối (VD: "Lê Văn Duy 88")
            if re.search(r"\d|\*", s) and not re.match(r"^[A-Za-zÀ-ỹ]+(?:\s+[A-Za-zÀ-ỹ]+){1,4}\s+\d{1,2}$", s):
                return None
            cand = clean_driver_name(s)
            if cand and 1 <= len(cand.split()) <= 6 and len(cand) >= 2:
                return cand
            return None

        # Kiểu 1: Có nhãn rõ ràng trên dòng ("Tên lái xe:", "Tài xế:", "Tài ...", "TX ...", "👤 ...")
        # Ưu tiên cụm cập nhật tường minh ("tài ... đổi thành <Tên>", "tài xế mới: <Tên>") trước khi quét nhãn chung
        update_drv_m = re.search(
            r"(?:tài(?:\s*xế)?|lái\s*xe)\b[^\n/\\|｜;]{0,45}?\b(?:đổi\s*(?:thành|sang|qua)|doi\s*(?:thanh|sang|qua)|mới\s*[:\-]?)\s+([^\n/\\|｜;\t,\[\]()\"'*#—–·•→]+)",
            sanitized_text,
            flags=re.IGNORECASE,
        )
        if update_drv_m:
            candidate = _finalize_name(_clip_inline_driver_tail(update_drv_m.group(1)))
            if candidate and 2 <= len(candidate.split()) <= 6:
                return candidate, True

        # Duyệt tuần tự tất cả các nhãn để tránh cụm sai như "tài liệu" che khuất nhãn "tài xế ..." đứng sau
        labeled_re = re.compile(
            r"(?:^|[\s/\\|｜;\t,\[\(—–·•→#])(?:[👤👨🧑🪪]|tên\s*lái\s*xe|ten\s*lai\s*xe|tên\s*tài\s*xế|ten\s*tai\s*xe|bác\s*tài|bac\s*tai|bactai|"
            r"tài\s*xế|tai\s*xe|taixe|tàixế|lái\s*xe|lai\s*xe|laixe|láixe|\btxe\b|\btx\b|\blx\b|\btài\b|\btai\b)(?:\s*[:\-]\s*|\s+)([^\n/\\|｜;\t,\]\)\"*#—–·•→]+)",
            flags=re.IGNORECASE,
        )
        for labeled in labeled_re.finditer(sanitized_text):
            candidate = _finalize_name(_clip_inline_driver_tail(labeled.group(1)))
            if candidate and not stop_words_regex.search(candidate):
                raw_matched_all = labeled.group(0).lower()
                if re.search(r"\btài\b|\btai\b", raw_matched_all) and "tài xế" not in raw_matched_all and "tai xe" not in raw_matched_all and ":" not in raw_matched_all:
                    if len(candidate.split()) >= 2:
                        return candidate, True
                else:
                    return candidate, True

        stop_prefix = re.compile(
            r"^(?:kh|khách\s*hàng|khach\s*hang|khách|khach|kho|cảng|cang|điểm\s*đóng|diem\s*dong|đóng\s*tại|lệnh|lenh|trả\s*về|tra\s*ve|xe|bks|cont|container|sđt|sdt|đt|stt)\s*[:\-]?",
            re.IGNORECASE,
        )

        # Kiểu 2: Định dạng F1 / Bảng / Đa phân cách ('/', '|', '｜', '\t', '—', '–', '·', '•', '→', '#', ';', ',', ' - ')
        all_lines = [ln for ln in sanitized_text.split("\n") if ln.strip() and not table_header_re.search(ln.strip())]
        ordered_lines = sorted(all_lines, key=lambda ln: 0 if (raw_truck_plate and raw_truck_plate.lower() in ln.lower()) else 1)

        for line in ordered_lines:
            if re.search(r"[/\\|｜\t;·•→—–#]|(?:\s+-\s+)|,", line):
                parts = [
                    p.strip()
                    for p in re.split(r"\s*[/\\|｜\t;·•→—–#]+\s*|\s+-\s+|\s*,\s*", line)
                    if p.strip()
                ]
                for part in parts:
                    # Bóc bỏ nhãn nếu part còn tiền tố "tài ...", "tx ..."
                    part_clean = re.sub(r"^(?:tên\s*lái\s*xe|tài\s*xế|tai\s*xe|lái\s*xe|tx|lx|tài|tai)\s*[:\-]?\s+", "", part, flags=re.IGNORECASE).strip()
                    if re.match(r"^\d{1,3}$", part_clean):
                        continue
                    if stop_prefix.search(part):
                        continue
                    if raw_truck_plate and raw_truck_plate.lower() in part.lower():
                        continue
                    if any(c.lower() in re.sub(r"[^a-zA-Z0-9]", "", part).lower() for c in containers):
                        continue
                    candidate = _finalize_name(part_clean)
                    if candidate and 2 <= len(candidate.split()) <= 6:
                        return candidate, True

        # Kiểu 2b: Mẫu vị trí từ nhaxe_bot (tên tài xế kẹp giữa biển số xe và SĐT hoặc container, hoặc đứng trước SĐT)
        positional_patterns = [
            r"(?:[0-9]{2}[A-Za-z]{1,2}[\s.\-/]*[0-9.\-]{4,7})\s*(?:-|/|\\)?\s*([A-Za-zÀ-ỹ ]{3,35}?)\s*(?:-|/|\\)?\s*(?:sdt|sđt|đt|dt)?\s*[:\s'\"]*(?:\+84|0\d)",
            r"(?:[0-9]{2}[A-Za-z]{1,2}[\s.\-/]*[0-9.\-]{4,7})\s*(?:-|/|\\)?\s*([A-Za-zÀ-ỹ ]{3,35}?)\s*(?:-|/|\\)?\s*(?:cont|\b[A-Za-z]{4}\d{7}\b)",
            r"(?:^|[/\\,\n])\s*([A-Za-zÀ-ỹ ]{3,35}?)\s*(?:/|\\|-)?\s*(?:sdt|sđt|đt|dt)?\s*[:\s'\"]*(?:\+84|0\d)",
        ]
        for pos_pat in positional_patterns:
            m_pos = re.search(pos_pat, sanitized_text, flags=re.IGNORECASE)
            if m_pos:
                raw_pos = re.sub(r"^(?:xe|tx|lx|anh|chị|bác)\s+", "", m_pos.group(1).strip(), flags=re.IGNORECASE).strip()
                candidate = _finalize_name(raw_pos)
                if candidate and 2 <= len(candidate.split()) <= 5:
                    return candidate, True

        # Kiểu 3: Tin một dòng tự do không có dấu phân cách / nhãn (heuristic, không chắc chắn -> để AI tinh chỉnh nếu cần)
        for line in all_lines:
            if not (raw_truck_plate and raw_truck_plate in line):
                continue
            rem = line
            if raw_truck_plate:
                rem = rem.replace(raw_truck_plate, " | ")
            rem = re.sub(r"\b(?:LO|RO)\d{3,8}\b", " | ", rem, flags=re.IGNORECASE)
            rem = re.sub(r"(?:rơ\s*moóc|mooc|rm)\s*[:\-]?\s*[0-9A-Za-z.\-]+", " | ", rem, flags=re.IGNORECASE)
            rem = re.sub(
                r"(?:\b(?:s+d+đ*t+|s+đ+t+|d+t+|đ+t+|tel|lh|hl|zalo|phone|call)\b)?\s*[:\-]?\s*(?:\+?84[\s.\-]?|0)\d[\d\s.\-*xX]{5,11}[\d*xX]",
                " | ",
                rem,
                flags=re.IGNORECASE,
            )
            for c in containers:
                rem = re.sub(re.escape(c), " | ", rem, flags=re.IGNORECASE)
            if seal_no:
                rem = re.sub(rf"(?:chì|seal)?\s*[:\-]?\s*{re.escape(seal_no)}", " | ", rem, flags=re.IGNORECASE)
            rem = cls._SIZE_REGEX.sub(" | ", rem)
            rem = re.sub(r"^(?:\d+[\.\)]?\s*)?(?:xe\s*\d*\s*[:\-]?\s*)?", "", rem, flags=re.IGNORECASE)

            for chunk in rem.split("|"):
                candidate = _finalize_name(chunk)
                if candidate and 2 <= len(candidate.split()) <= 5:
                    return candidate, False

        # Kiểu 4: Dòng độc lập không có nhãn/dấu phân cách (chỉ nhận khi trong khối có thực thể chuyến khác hoặc dòng viết hoa đầu từ đúng quy cách họ tên)
        has_other_entity = bool(raw_truck_plate or containers or driver_phone or seal_no)
        for line in all_lines:
            line_clean = line.strip()
            if stop_prefix.search(line_clean):
                continue
            words_raw = [w for w in line_clean.split() if w.isalpha()]
            if not words_raw or not any(w[0].isupper() for w in words_raw):
                continue
            if not has_other_entity and not all(w[0].isupper() for w in words_raw):
                continue
            candidate = _finalize_name(line_clean)
            if candidate and 2 <= len(candidate.split()) <= 5 and len(candidate) >= 3:
                is_pure_name_line = bool(
                    has_other_entity
                    and not any(ch.isdigit() for ch in line_clean)
                    and len(words_raw) == len(line_clean.split())
                )
                return candidate, is_pure_name_line

        return None, False

    @classmethod
    def _extract_container_size(cls, text: str) -> Optional[str]:
        """Trích xuất kích cỡ/loại container (hỗ trợ cả `1x20` của F2 -> `'20'`, `'40HC'`, `'20DC'`)."""
        # 1. Mẫu F2 "1x20", "2x20", "1x40HC"
        nx_match = re.search(
            r"\b\d+\s*[xX]\s*(20\s*(?:DC|GP|RF|HC|HQ)?|40\s*(?:HC|HQ|DC|GP|RF)?|45\s*(?:HC|HQ|DC)?)\b",
            text,
            flags=re.IGNORECASE,
        )
        if nx_match:
            return nx_match.group(1).upper().replace(" ", "")

        # 2. Mẫu có nhãn "Loại cont:", "Kích cỡ:", "Size:"
        labeled = re.search(
            r"(?:loại\s*cont|loai\s*cont|kích\s*cỡ|kich\s*co|kích\s*thước|kich\s*thuoc|size|cỡ|co)[ \t]*[:\-]?[ \t]*(20[ \t]*[A-Za-z']*|40[ \t]*[A-Za-z']*|45[ \t]*[A-Za-z']*)",
            text,
            flags=re.IGNORECASE,
        )
        if labeled:
            return labeled.group(1).upper().replace("'", "").replace(" ", "")

        # 3. Mẫu trực tiếp 20DC, 40HC, 40RF, Cont 20...
        match = cls._SIZE_REGEX.search(text)
        if match:
            raw_sz = match.group(0).upper().replace("'", "")
            raw_sz = re.sub(r"^(?:\d+\s*X\s*|CONT|LOẠI|LOAI|SIZE|CỠ|CO)\s*", "", raw_sz).replace(" ", "")
            return raw_sz

        # 4. Mẫu số kích thước đứng độc lập (20, 40, 45) cạnh mã cont hoặc từ khóa chì/seal/xe
        bare_sz = re.search(
            r"(?:\b[A-Za-z]{4}[\s.\-]*\d{7}\s+(20|40|45)\b|\b(20|40|45)\b(?=\s*(?:chì|chi|seal|xe|cont|dc|hc|gp|rf)\b))",
            text,
            flags=re.IGNORECASE,
        )
        if bare_sz:
            return bare_sz.group(1) or bare_sz.group(2)
        return None

    @classmethod
    def _extract_seal(
        cls, text: str, containers: list[str]
    ) -> tuple[Optional[str], bool]:
        """Trích xuất số chì niêm phong (Seal) trên cùng một dòng (tránh ăn sang dòng tiếp theo khi `Số seal:` để trống)."""
        is_pending = bool(
            re.search(
                r"(?:chưa\s*(?:có|cấp|lấy|bấm|kẹp)\s*(?:số\s*)?(?:chì|seal)|"
                r"chua\s*(?:co|cap|lay|bam|kep)\s*(?:so\s*)?(?:chi|seal)|"
                r"(?:số\s*)?(?:chì|chi|seal)\s*(?:chưa|chua|không|khong)\s*(?:có|co|cấp|cap|lấy|lay|bấm|bam|kẹp|kep)|"
                r"(?:không|khong)\s*có\s*(?:số\s*)?(?:chì|chi|seal)|"
                r"(?:chì|chi|seal)\s*(?:báo|bao|bổ\s*sung|bo\s*sung)\s*sau|"
                r"(?:bổ\s*sung|bo\s*sung|báo|bao)\s*(?:chì|chi|seal)\s*sau|"
                r"(?:nợ|no)\s*(?:chì|chi|seal))",
                text,
                flags=re.IGNORECASE,
            )
        )
        if is_pending:
            return None, True

        # Chỉ dùng [ \t]* (khoảng trắng ngang trên cùng dòng) để khi "Số seal:" hoặc "Số chì:" để trống sẽ trả về None
        match = re.search(
            r"(?:số\s*chì|so\s*chi|số\s*seal|so\s*seal|niêm\s*chì|niem\s*chi|seal\s*no|seal|chì|chi)[ \t]*[:\-]?[ \t]*([A-Za-z0-9\-]{4,20})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            candidate = match.group(1).strip().upper()
            if candidate.lower() not in ("bổ", "bo", "chưa", "chua", "không", "khong", "thời", "thoi", "điểm", "diem"):
                return candidate, False

        for cont in containers:
            shorthand = re.search(
                rf"{re.escape(cont)}[ \t]*/[ \t]*([A-Za-z0-9\-]{{5,15}})\b",
                text,
                flags=re.IGNORECASE,
            )
            if shorthand:
                cand = shorthand.group(1).strip().upper()
                if not re.match(r"^(?:20|40|45|0\d{8,10})", cand):
                    return cand, False

        # Tin nhắn ngắn chỉ chứa 1 mã chì độc lập (VD: "VS998877", "HL778899")
        stripped = (text or "").strip()
        if (
            not containers
            and stripped
            and " " not in stripped
            and "\n" not in stripped
            and re.fullmatch(
                r"(?!(?:BK|LO|RO)\d)(?![A-Z]{4}\d{7}$)(?!0\d{8,10}$)(?!\d{2}[A-Z]{1,2}\d{4,5}$)[A-Za-z0-9\-]{5,15}",
                stripped,
                flags=re.IGNORECASE,
            )
            and len(re.findall(r"\d", stripped)) >= 4
            and not re.search(r"^\d{2}[A-Z]{1,2}[\.\-]?\d{3,5}(?:\.\d{2})?$", stripped, flags=re.IGNORECASE)
        ):
            return stripped.upper(), False

        return None, False

    @classmethod
    def _extract_booking_no(cls, text: str) -> Optional[str]:
        """Trích xuất mã lệnh / số lệnh / mã booking / số vận đơn."""
        compact_bk = re.search(r"\b(BK\d{4,20})\b", text, flags=re.IGNORECASE)
        if compact_bk:
            return compact_bk.group(1).strip().upper()
        match = re.search(
            r"(?:mã\s*booking|ma\s*booking|số\s*booking|so\s*booking|booking|\bbk\b|"
            r"mã\s*lệnh|ma\s*lenh|số\s*lệnh|so\s*lenh|số\s*vận\s*đơn|so\s*van\s*don|vận\s*đơn|van\s*don|\bbill\b|\bb/l\b)"
            r"(?:\s+(?:mới|moi|cũ|cu))?[ \t]*[:\-]?[ \t]*([A-Za-z0-9\-_/]{4,25})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().upper()
        return None

    @classmethod
    def _extract_order_type(cls, text: str) -> tuple[Optional[str], bool]:
        """Xác định loại lệnh Đóng (`dong`) hay Trả (`tra`), xử lý chuẩn xác cả nhãn kép `Đóng , Trả hàng: Tra` của F2."""
        # 0. Ưu tiên tiền tố chỉ định theo dòng (VD: "Đóng: 1 Xe...", "Trả: 2 xe...") khi một tin có cả đóng và trả
        line_prefix_match = re.search(
            r"(?:^|\n)\s*(đóng|dong|trả|tra)\s*[:\-]\s*(?:\d+\s*xe|\bxe\b)",
            text,
            flags=re.IGNORECASE,
        )
        if line_prefix_match:
            prefix_choice = line_prefix_match.group(1).lower()
            if prefix_choice in ("đóng", "dong"):
                return OrderType.LOAD.value, False
            return OrderType.RETURN.value, False

        # 1. Xử lý ưu tiên nhãn lựa chọn của F2 ("Đóng , Trả hàng: Tra 1x20...") và F3 ("Lệnh: Trả")
        explicit_choice = re.search(
            r"(?:đóng\s*[,/]\s*trả(?:\s*hàng)?|dong\s*[,/]\s*tra(?:\s*hang)?|\blệnh\b|\blenh\b)[ \t]*[:\-][ \t]*(đóng|dong|trả|tra)\b",
            text,
            flags=re.IGNORECASE,
        )
        if explicit_choice:
            choice = explicit_choice.group(1).lower()
            if choice in ("đóng", "dong"):
                return OrderType.LOAD.value, False
            return OrderType.RETURN.value, False

        # Loại bỏ cụm nhãn "Đóng , Trả hàng:" hoặc "Điểm đóng/trả:" trước khi quét từ khóa tự do để không bị nhiễu
        cleaned_for_order = re.sub(
            r"(?:đóng\s*[,/]\s*trả(?:\s*hàng)?|điểm\s*đóng\s*/\s*trả|diem\s*dong\s*/\s*tra)",
            "",
            text,
            flags=re.IGNORECASE,
        )
        lower = cleaned_for_order.lower()

        # 2. Từ khóa nhận diện trực tiếp Lệnh Đóng (T01)
        if re.search(
            r"\b(?:đóng\s*hàng|dong\s*hang|lệnh\s*đóng|lenh\s*dong|đóng\s*cont|dong\s*cont|"
            r"lấy\s*cont\s*rỗng|lay\s*cont\s*rong|lấy\s*rỗng|lay\s*rong|kéo\s*rỗng|keo\s*rong|đóng|dong)\b",
            lower,
        ):
            return OrderType.LOAD.value, False

        # 3. Từ khóa nhận diện trực tiếp Lệnh Trả (T02)
        if re.search(
            r"\b(?:trả\s*hàng|tra\s*hang|lệnh\s*trả|lenh\s*tra|trả\s*cont|tra\s*cont|"
            r"hạ\s*cont|ha\s*cont|hạ\s*bãi|ha\s*bai|trả\s*rỗng|tra\s*rong|trả|tra(?!\s*(?:cuu|cứu)))\b",
            lower,
        ):
            return OrderType.RETURN.value, False

        # 4. Suy luận Lệnh Đóng từ ngữ cảnh xuất hàng / điểm đóng (T03)
        if re.search(
            r"\b(?:hàng\s*xuất|hang\s*xuat|xuất\s*hàng|xuat\s*hang|điểm\s*đóng|diem\s*dong|"
            r"nơi\s*đóng|noi\s*dong|kho\s*đóng|kho\s*dong|booking\s*xuất)\b",
            lower,
        ):
            return OrderType.LOAD.value, True

        # 5. Suy luận Lệnh Trả từ ngữ cảnh nhập hàng / dỡ hàng / nơi hạ (T04)
        if re.search(
            r"\b(?:hàng\s*nhập|hang\s*nhap|nhập\s*hàng|nhap\s*hang|dỡ\s*hàng|do\s*hang|"
            r"giao\s*hàng|giao\s*hang|điểm\s*trả|diem\s*tra|kho\s*trả|kho\s*tra|nơi\s*hạ|noi\s*ha|điểm\s*hạ|diem\s*ha)\b",
            lower,
        ):
            return OrderType.RETURN.value, True

        # 6. Suy luận từ mã lệnh tường minh ROxxxx (Trả) / LOxxxx (Đóng) nếu chỉ có 1 loại lệnh
        has_ro_code = bool(re.search(r"\bro\d{3,6}\b", lower))
        has_lo_code = bool(re.search(r"\blo\d{3,6}\b", lower))
        if has_ro_code and not has_lo_code:
            return OrderType.RETURN.value, True
        if has_lo_code and not has_ro_code:
            return OrderType.LOAD.value, True

        return None, False

    @classmethod
    def _extract_warehouse_hint(cls, text: str) -> Optional[str]:
        """Trích xuất điểm đóng/trả (`location_raw` / `warehouse_hint`)."""
        # 1. Mẫu F3: "Điểm đóng/trả: Kho Nhựa Á Đông – Long An"
        f3_loc = re.search(
            r"(?:điểm\s*đóng\s*/\s*trả|diem\s*dong\s*/\s*tra|điểm\s*đóng|diem\s*dong|nơi\s*đóng|noi\s*dong|"
            r"điểm\s*trả|diem\s*tra|nơi\s*hạ|noi\s*ha|điểm\s*hạ|diem\s*ha|địa\s*chỉ\s*kho|dia\s*chi\s*kho)[ \t]*[:\-][ \t]*([^\n,;|]+)",
            text,
            flags=re.IGNORECASE,
        )
        if f3_loc:
            val = f3_loc.group(1).strip(" -:;,.|/\t")
            if val:
                # Loại bỏ phần thời gian bị dính ở cuối (ví dụ "kho Logitem Tân Quang - 8h" -> "kho Logitem Tân Quang")
                val = re.sub(
                    r"\s+[-–—]\s*(?:\d{1,2}(?:[:hH]\d{0,2})?|\b\d{1,2}\s*giờ\b).*$",
                    "",
                    val,
                    flags=re.IGNORECASE,
                ).strip(" -:;,.|/\t")
                return val[:255]

        # 2. Mẫu chung: Kho / Nhà máy / Cảng / KCN / Bãi
        # Loại trừ cụm "đến kho:" hoặc "vào kho:" của dòng Thời gian
        cleaned_lines = [
            ln for ln in text.splitlines()
            if not re.search(r"(?:thời\s*gian|dự\s*kiến|giờ)\s*(?:dự\s*kiến\s*)?(?:xe\s*)?(?:đến|vào)\s*kho", ln, flags=re.IGNORECASE)
        ]
        cleaned_text = "\n".join(cleaned_lines)

        match = re.search(
            r"(?:khu\s*công\s*nghiệp|khu\s*cong\s*nghiep|\bkcn\b|vsip|cảng|cang|bãi|bai|nhà\s*máy|nha\s*may|kho)[ \t]*[:\-]?[ \t]*([^\n,;/|\t]+)",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        if match:
            hint = match.group(0).strip(" -:;,.|/\t")
            if len(hint) >= 3:
                return hint[:255]
        return None

    @classmethod
    def _extract_customer_hint(cls, text: str) -> Optional[str]:
        """Trích xuất tên khách hàng nguyên bản (`customer_raw` / `customer_hint`) cho cả F1, F2, F3."""
        # 1. Mẫu F3 hoặc chung: "Khách hàng: Nhựa Á Đông", "KH: Logitem", "Kính gửi: ..."
        labeled = re.search(
            r"(?:\bkh\b|khách\s*hàng|khach\s*hang|khách|khach|chủ\s*hàng|chu\s*hang|cty|công\s*ty|cong\s*ty|hàng\s*của|hang\s*cua|kính\s*gửi|kinh\s*gui)[ \t]*[:\-]?[ \t]*([^\n,;/|\t]+)",
            text,
            flags=re.IGNORECASE,
        )
        if labeled:
            hint = labeled.group(1).strip(" -:;,.|/\t")
            hint = re.split(
                r"\s+-\s+|\s+(?:tại|tai|ở|o)\s+(?:kho|cảng|cang|nhà\s*máy|kcn)\b",
                hint,
                flags=re.IGNORECASE,
            )[0].strip()
            if hint:
                return hint[:255]

        # 2. Mẫu F2: "1. Ngày: .9/10/2026 : Đóng , Trả hàng: Tra 1x20 Nhựa Long An"
        f2_header = re.search(
            r"đóng\s*[,/]\s*trả(?:\s*hàng)?[ \t]*:[ \t]*(?:đóng|dong|trả|tra)[ \t]+(?:\d+[ \t]*[xX][ \t]*\d+\w*[ \t]+)?([^\n,;]+)",
            text,
            flags=re.IGNORECASE,
        )
        if f2_header:
            hint = f2_header.group(1).strip(" -:;,.|/\t")
            if hint:
                return hint[:255]

        return None

    @classmethod
    def _extract_eta(
        cls,
        text: str,
        reference_time: Optional[datetime] = None,
    ) -> tuple[Optional[str], Optional[str], Optional[datetime], bool]:
        """Trích xuất thời gian dự kiến đến kho (`eta_text`, `eta_time` chuẩn `'HH:MM'`, `estimated_at`, `is_time_vague`)."""
        ref = reference_time or datetime.now()

        # 1. Kiểm tra thời gian chưa xác định ("chưa có giờ", "báo sau", "chờ điều phối")
        undetermined = re.search(
            r"(?:chưa\s*có\s*giờ|chua\s*co\s*gio|giờ\s*báo\s*sau|gio\s*bao\s*sau|báo\s*giờ\s*sau|chờ\s*điều\s*phối|cho\s*dieu\s*phoi)",
            text,
            flags=re.IGNORECASE,
        )
        if undetermined:
            return undetermined.group(0).strip(), None, None, True

        # 2. Mẫu có nhãn rõ của F2 & F3: "Thời gian xe đến kho: 8h", "Thời gian dự kiến đến kho: 08:00", "ETA: 08:00"
        labeled_eta = re.search(
            r"(?:thời\s*gian\s*(?:dự\s*kiến\s*)?(?:xe\s*)?(?:đến|vào)\s*kho|dự\s*kiến|du\s*kien|eta|giờ\s*đến|gio\s*den|giờ\s*vào|gio\s*vao)[ \t]*[:\-]?[ \t]*(\d{1,2})(?:[:hH](\d{2})?|\s*giờ(?:\s*(\d{1,2}))?)?[ \t]*(sáng|chiều|tối|đêm)?(?:[ \t]*(?:ngày\s*)?(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?)?",
            text,
            flags=re.IGNORECASE,
        )
        if labeled_eta:
            eta_raw = labeled_eta.group(0).strip()
            hour = int(labeled_eta.group(1))
            minute = int(labeled_eta.group(2) or labeled_eta.group(3) or 0)
            period = (labeled_eta.group(4) or "").lower()
            if period in ("chiều", "tối") and hour < 12:
                hour += 12
            day = int(labeled_eta.group(5)) if labeled_eta.group(5) else ref.day
            month = int(labeled_eta.group(6)) if labeled_eta.group(6) else ref.month
            year_raw = labeled_eta.group(7)
            year = int(year_raw) if year_raw else ref.year
            if year < 100:
                year += 2000
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                eta_hhmm = f"{hour:02d}:{minute:02d}"
                try:
                    return eta_raw, eta_hhmm, datetime(year, month, day, hour, minute), False
                except ValueError:
                    return eta_raw, eta_hhmm, None, False

        # 3. Mẫu đầy đủ giờ + ngày/tháng(/năm) tự do: "14h30 27/10/2026"
        full_match = re.search(
            r"\b(\d{1,2})(?:[:hH](\d{2})?|\s*giờ\s*(\d{1,2})?)\s*(?:sáng|chiều|tối|đêm)?\s*(?:ngày\s*)?(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\b",
            text,
            flags=re.IGNORECASE,
        )
        if full_match:
            eta_raw = full_match.group(0).strip()
            hour = int(full_match.group(1))
            minute = int(full_match.group(2) or full_match.group(3) or 0)
            if re.search(r"chiều|tối", eta_raw, flags=re.IGNORECASE) and hour < 12:
                hour += 12
            day = int(full_match.group(4))
            month = int(full_match.group(5))
            year_raw = full_match.group(6)
            year = int(year_raw) if year_raw else ref.year
            if year < 100:
                year += 2000
            eta_hhmm = f"{hour:02d}:{minute:02d}"
            try:
                return eta_raw, eta_hhmm, datetime(year, month, day, hour, minute), False
            except ValueError:
                return eta_raw, eta_hhmm, None, True

        # 3b. Mẫu giờ rút gọn có tiền tố liên kết: "- 8h", "đến 8h", "tới 19:40", "vào 8h30", "lúc 14h", "tam 8h30"
        short_eta = re.search(
            r"(?:(?:đến|den|tới|toi|vào|vao|lúc|luc|tầm|tam|khoảng|khoang|hẹn|hen)\s*|[-–—]\s*)(\d{1,2})(?:[:hH](\d{2})?|\s*giờ(?:\s*(\d{1,2}))?)\s*(sáng|sang|chiều|chieu|tối(?:\s*nay)?|toi\s*nay|đêm|dem)?\b",
            text,
            flags=re.IGNORECASE,
        )
        if short_eta:
            eta_raw = short_eta.group(0).strip()
            hour = int(short_eta.group(1))
            minute = int(short_eta.group(2) or short_eta.group(3) or 0)
            period = (short_eta.group(4) or "").lower()
            if period and any(p in period for p in ("chiều", "chieu", "tối", "toi", "đêm", "dem")) and hour < 12:
                hour += 12
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                eta_hhmm = f"{hour:02d}:{minute:02d}"
                try:
                    return eta_raw, eta_hhmm, datetime(ref.year, ref.month, ref.day, hour, minute), False
                except ValueError:
                    return eta_raw, eta_hhmm, None, False

        # 3c. Mẫu giờ HH:MM tường minh đứng độc lập (VD: "08:00", "(11:00)", "19:40")
        colon_eta = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?![\-.\d])", text)
        if colon_eta:
            hour = int(colon_eta.group(1))
            minute = int(colon_eta.group(2))
            eta_hhmm = f"{hour:02d}:{minute:02d}"
            try:
                return colon_eta.group(0), eta_hhmm, datetime(ref.year, ref.month, ref.day, hour, minute), False
            except ValueError:
                return colon_eta.group(0), eta_hhmm, None, False

        # 4. Mẫu thời gian tương đối ("Sáng nay", "Chiều nay", "Tối nay", "Ngày mai") -> T39
        relative_match = re.search(
            r"\b(?:sáng\s*nay|sang\s*nay|trưa\s*nay|chiều\s*nay|chieu\s*nay|tối\s*nay|toi\s*nay|"
            r"đêm\s*nay|sáng\s*mai|sang\s*mai|chiều\s*mai|chieu\s*mai|ngày\s*mai|ngay\s*mai)\b",
            text,
            flags=re.IGNORECASE,
        )
        if relative_match:
            eta_raw = relative_match.group(0).strip()
            lower_rel = eta_raw.lower()
            base_dt = ref + timedelta(days=1) if "mai" in lower_rel else ref
            hour = 8 if ("sáng" in lower_rel or "sang" in lower_rel) else (14 if ("chiều" in lower_rel or "chieu" in lower_rel) else 19)
            try:
                est_dt = base_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
            except ValueError:
                est_dt = None
            return eta_raw, None, est_dt, True

        return None, None, None, False
