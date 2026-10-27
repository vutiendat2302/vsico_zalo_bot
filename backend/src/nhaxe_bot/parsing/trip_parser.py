"""Module Bóc Tách Thông Tin Chuyến Xe (Trip & Vehicle Parser).

Thực hiện toàn bộ pipeline trích xuất dữ liệu xe từ một khối văn bản tin nhắn:
1. Số hiệu container (thẩm định sơ bộ).
2. Số niêm phong / seal hải quan.
3. Biển số xe cơ giới (đầu kéo, rơ-moóc).
4. Số điện thoại di động tài xế.
5. Họ tên người lái xe (loại bỏ danh xưng anh, bác, tx).
6. Thời gian xe đến kho (kết hợp tiêu đề chung nếu trong dòng không ghi).
7. Hướng vận chuyển (trả hàng, nhập hàng, đóng hàng).
"""

import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from ..domain.models import Vehicle
from ..domain.rules import clean_container, clean_plate, clean_phone, clean_seal, validate_iso6346, clean_driver_name
from ..messaging.preprocess import normalize_text, detect_header_info
from .fields.datetime_parser import parse_vietnamese_datetime


class TripParser:
    """Bộ bóc tách thông tin phương tiện từ một khối văn bản tin nhắn của nhà xe."""

    @staticmethod
    def parse_vehicle(block: str, full_text: str, msg_dt: datetime, xe_index: int = 1) -> Vehicle:
        """Trích xuất toàn bộ các trường thông tin xe từ một khối văn bản (block).

        Args:
            block (str): Đoạn văn bản đại diện cho 1 xe (sau khi qua phân đoạn segmenter).
            full_text (str): Toàn bộ nội dung tin nhắn gốc (dùng để kế thừa ngày giờ ở tiêu đề).
            msg_dt (datetime): Thời điểm nhận tin nhắn (chuẩn timezone GMT+7) làm mốc quy chiếu.
            xe_index (int, optional): Thứ tự của xe trong tin nhắn (mặc định là 1).

        Returns:
            Vehicle: Thực thể phương tiện chứa đầy đủ các trường dữ liệu và cảnh báo ban đầu.
        """
        # Trích xuất thông tin chung ở đầu tin nhắn (ngày, giờ, loại hàng)
        header_info = detect_header_info(full_text)
        block_norm = normalize_text(block)
        full_norm = normalize_text(full_text)

        # ---------------------------------------------------------
        # 1. BÓC TÁCH SỐ CONTAINER
        # ---------------------------------------------------------
        raw_cont = None
        # Ưu tiên tìm theo nhãn "cont:", "số cont:"
        m_cont_label = re.search(
            r'(?:số\s+cont|cont)\s*[:\s]\s*([A-Za-z0-9\s\-]+?)(?=(?:\s+chì|\s+chi|\s+seal|\s*\(|\n|$|/|,|-))',
            block_norm,
            re.I,
        )
        if m_cont_label and re.search(r'\d', m_cont_label.group(1)):
            raw_cont = m_cont_label.group(1).strip()
        else:
            # Tìm theo mẫu regex 4 chữ cái + 7 chữ số tự do trong khối
            m_cont_regex = re.search(r'\b([A-Za-z]{3,5}\s*-?\s*\d{6,7})\b', block_norm)
            if m_cont_regex:
                raw_cont = m_cont_regex.group(1).strip()

        cont = clean_container(raw_cont) if raw_cont else None

        # ---------------------------------------------------------
        # 2. BÓC TÁCH SỐ CHÌ / SEAL
        # ---------------------------------------------------------
        seal = None
        # Đảm bảo nhãn chì/seal không bị bỏ trống
        if not re.search(r'(?:số\s+seal|số\s+chì|seal|chì)\s*:\s*(?:\n|$)', block_norm, re.I):
            m_seal_label = re.search(
                r'(?:số\s+seal|số\s+chì|seal|chì)\s*[:\s]\s*(\d{6,8})\b', block_norm, re.I
            )
            if m_seal_label:
                seal = m_seal_label.group(1).strip()
            else:
                # Tìm chuỗi 6-8 chữ số không phải số điện thoại
                tokens = re.findall(r'\b\d{6,8}\b', block_norm)
                for t in tokens:
                    if t.startswith(('09', '08', '07', '03', '05')):
                        if re.search(r'(?:sdt|sđt|đt|dt)', block_norm, re.I):
                            continue
                    seal = t
                    break

        # ---------------------------------------------------------
        # 3. BÓC TÁCH BIỂN SỐ XE
        # ---------------------------------------------------------
        raw_plate = None
        # Ưu tiên tìm theo nhãn "biển số:", "số xe:", "xe:" (hỗ trợ cả dính liền như 'Xe15h00814')
        m_plate_label = re.search(
            r'(?:biển\s+số|số\s+xe|xe)\s*[:\s]*([0-9]{2}[A-Za-z][A-Za-z0-9\.\-\s]{3,10}?)(?=(?:/|-|\s+tx|\s+tài\s+xế|\s+đt|\s+sđt|\s+cont|\s+chì|\s+seal|\n|$))',
            block_norm,
            re.I,
        )
        if m_plate_label:
            val = m_plate_label.group(1).strip()
            c = clean_plate(val)
            if c:
                raw_plate = c
        if not raw_plate:
            m_plate_reg = re.search(
                r'(?:(?<=\b)|(?<=[A-Za-z]))(?<!\d)(\d{2}[A-Za-z][\dA-Za-z]?[\s\.\-]?(?:\d{4,5}|\d{3}\.\d{2}))\b',
                block_norm,
            )
            if m_plate_reg:
                raw_plate = clean_plate(m_plate_reg.group(1))
        if not raw_plate:
            m_plate_bad = re.search(
                r'\b([0-9][A-Za-z]{2}[\s\.\-]?(?:\d{4,5}|\d{3}\.\d{2}))\b', block_norm
            )
            if m_plate_bad:
                raw_plate = re.sub(r'[^A-Za-z0-9]', '', m_plate_bad.group(1)).upper()
        bien_so = raw_plate

        # ---------------------------------------------------------
        # 4. BÓC TÁCH SỐ ĐIỆN THOẠI
        # ---------------------------------------------------------
        raw_phone = None
        # Ưu tiên tìm theo nhãn "sđt:", "đt:"
        m_phone_label = re.search(
            r'(?:sđt|sdt|đt|dt)\s*[:\s]\s*(\+?[0-9][0-9\.\s]{7,12}\d)\b', block_norm, re.I
        )
        if m_phone_label:
            raw_phone = m_phone_label.group(1).strip()
        else:
            # Nhận diện số điện thoại có dấu cách phân đoạn (ví dụ: 0903 976 359)
            m_split = re.search(r'\b0\d{2,3}\s+\d{3}\s+\d{3,4}\b', block_norm)
            if m_split:
                raw_phone = m_split.group(0)
            else:
                tokens = re.split(r'[\s/,\-]+', block_norm)
                for t in tokens:
                    clean_t = re.sub(r'[^0-9+]', '', t)
                    if clean_t.startswith('+84') and len(clean_t) in [11, 12]:
                        raw_phone = clean_t
                        break
                    if clean_t.startswith('0') and len(clean_t) in [9, 10, 11] and ':' not in t:
                        raw_phone = clean_t
                        break
        sdt = clean_phone(raw_phone) if raw_phone else None

        # ---------------------------------------------------------
        # 5. BÓC TÁCH HỌ TÊN TÀI XẾ
        # ---------------------------------------------------------
        tai_xe = None
        # Ưu tiên tìm theo nhãn "tài xế:", "tx:"
        m_driver_label = re.search(
            r'(?:tài\s+xế|tên\s+lái\s+xe|tx)\s*[:\s]\s*([^\n\r,/]+?)(?=(?:\s+sđt|\s+sdt|\s+đt|\s+dt|\s+cont|\s+chì|\s+seal|\s*0\d|\s*\+84|\n|$|/|,|-))',
            block_norm,
            re.I,
        )
        if m_driver_label:
            name = m_driver_label.group(1).strip()
            # Bỏ danh xưng lịch sự 'anh', 'chị', 'bác'
            name = re.sub(r'^(?:anh|chị|bác)\s+', '', name, flags=re.I)
            if len(name) >= 2 and not any(
                k in name.lower() for k in ['cont', 'seal', 'biển số', 'xe', 'sdt', 'sđt', 'đt']
            ):
                tai_xe = clean_driver_name(name)
        if not tai_xe:
            # Nhận diện tên tài xế nằm kẹp giữa biển số xe và số điện thoại
            m_driver_mid = re.search(
                r'(?:[0-9][A-Za-z0-9\.\-]{5,10})\s*(?:-|/)?\s*([A-Za-zÀ-ỹ ]{3,30}?)\s*(?:-|/)?\s*(?:sdt|sđt|đt|dt)?\s*[:\s]*\s*(?:\+84|0\d)',
                block_norm,
                re.I,
            )
            if m_driver_mid:
                name = m_driver_mid.group(1).strip()
                name = re.sub(r'^(?:xe|tx)\s+', '', name, flags=re.I).strip()
                if len(name) >= 2 and not re.search(r'\b(?:sdt|sđt|đt|dt)\b', name, re.I):
                    tai_xe = clean_driver_name(name)
        if not tai_xe:
            # Nhận diện tên tài xế nằm trước số container
            m_driver_before_cont = re.search(
                r'(?:[0-9][A-Za-z0-9\.\-]{5,10})\s*(?:-|/)?\s*([A-Za-zÀ-ỹ ]{3,30}?)\s*(?:-|/)?\s*(?:cont|\b[A-Za-z]{4}\d{7}\b)',
                block_norm,
                re.I,
            )
            if m_driver_before_cont:
                name = m_driver_before_cont.group(1).strip()
                name = re.sub(r'^(?:xe|tx)\s+', '', name, flags=re.I).strip()
                if len(name) >= 2 and not re.search(r'\b(?:sdt|sđt|đt|dt)\b', name, re.I):
                    tai_xe = clean_driver_name(name)
        if not tai_xe:
            # Nhận diện tên tài xế đứng trước số điện thoại di động
            m_driver_before_phone = re.search(
                r'(?:^|[/,\n])\s*([A-Za-zÀ-ỹ\s]{3,30}?)\s*(?:/|-)?\s*(?:sdt|sđt|đt|dt)?\s*[:\s]*\s*(?:\+84|0\d)',
                block_norm,
                re.I,
            )
            if m_driver_before_phone:
                name = m_driver_before_phone.group(1).strip()
                name = re.sub(r'^(?:xe|tx)\s+', '', name, flags=re.I).strip()
                if len(name) >= 2 and not re.search(r'\b(?:sdt|sđt|đt|dt|cont|seal)\b', name, re.I):
                    tai_xe = clean_driver_name(name)

        if tai_xe:
            tai_xe = clean_driver_name(tai_xe)

        # ---------------------------------------------------------
        # 6. BÓC TÁCH GIỜ ĐẾN KHO
        # ---------------------------------------------------------
        raw_time_str = None
        # Ưu tiên tìm theo nhãn "giờ đến:", "thời gian xe đến kho:"
        m_time_label = re.search(
            r'(?:giờ\s+đến|thời\s+gian\s+xe\s+đến\s+kho|đến\s+kho|đến|den\s+kho|den)\s*[:\s]\s*([^\n\r]+)',
            block_norm,
            re.I,
        )
        if m_time_label:
            raw_time_str = re.sub(r'[\(\)]', '', m_time_label.group(1)).strip()
        else:
            m_time_in_line = re.search(
                r'\b((?:[01]?\d|2[0-3])[:h][0-5]\d(?:\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?|\s+\d{4}-\d{1,2}-\d{1,2})?|(?:[01]?\d|2[0-3])h(?:\s+\d{1,2}/\d{1,2})?)\b(?!\d)',
                block_norm,
            )
            if m_time_in_line:
                raw_time_str = m_time_in_line.group(1).strip()
            elif header_info['time_str']:
                # Kế thừa giờ và ngày từ tiêu đề đầu tin nhắn
                time_part = header_info['time_str']
                date_part = header_info['date_str'] or ""
                raw_time_str = f"{time_part} {date_part}".strip()

        # Bổ sung ngày từ header nếu trong dòng chỉ ghi giờ
        if raw_time_str and not re.search(r'\d{1,2}/\d{1,2}', raw_time_str) and header_info['date_str']:
            raw_time_str = f"{raw_time_str} {header_info['date_str']}"

        gio_den, time_warns = parse_vietnamese_datetime(raw_time_str, msg_dt)

        # ---------------------------------------------------------
        # 7. PHÂN LOẠI HƯỚNG VẬN CHUYỂN (NHẬP / TRẢ / ĐÓNG)
        # ---------------------------------------------------------
        header_loai = header_info.get('loai')
        b_low = block_norm.lower()
        has_tra = 'trả hàng' in b_low or 'tra hang' in b_low or 'trả' in b_low
        has_nhap = 'nhập hàng' in b_low or 'nhap hang' in b_low or 'nhập' in b_low
        has_dong = 'đóng hàng' in b_low or 'dong hang' in b_low or 'đóng' in b_low

        if (has_tra or header_loai == 'tra') and (has_dong or header_loai == 'dong'):
            loai_hint = 'tra'
        elif has_dong or header_loai == 'dong':
            loai_hint = 'dong'
        elif has_nhap or header_loai == 'nhap':
            loai_hint = 'nhap'
        elif has_tra or header_loai == 'tra':
            loai_hint = 'tra'
        else:
            loai_hint = 'tra'

        # Đóng gói thành đối tượng Vehicle hoàn chỉnh
        return Vehicle(
            xe_index=xe_index,
            cont=cont,
            seal=seal,
            bien_so=bien_so,
            tai_xe=tai_xe,
            sdt=sdt,
            gio_den=gio_den,
            loai_hint=loai_hint,
            warnings=list(time_warns),
        )
