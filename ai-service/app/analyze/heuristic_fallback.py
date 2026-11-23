"""Bộ phân tích heuristic nội bộ làm lớp dự phòng khi Cloud LLM ngoại tuyến hoặc thiếu API Key."""

import re

from app.schemas.extract import ExtractedEntity

_CONT_RE = re.compile(r"\b([A-Z]{4})[\s\-]?(\d{7})\b", re.IGNORECASE)
_PLATE_RE = re.compile(
    r"\b(\d{2}[A-Z]{1,2}(?:[\s.\-/]*\d{3}[\s.\-]*\d{1,3}|[\s.\-/]*\d{4,6}))\b",
    re.IGNORECASE,
)
_TRAILER_RE = re.compile(
    r"\b(\d{2}[A-Z]?R[M]?(?:[\s.\-/]*\d{3}[\s.\-]*\d{1,3}|[\s.\-/]*\d{4,6}))\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?:\+?84|0)(?:\d{2,3}xxxx\d{2}(?:_\d+)?|[\d\s.\-]{8,11}\d)", re.IGNORECASE)
_SEAL_RE = re.compile(r"(?:seal|chì|chi|số\s*seal|số\s*chì)\s*[:=\-]?\s*([A-Z0-9\-]{4,20})", re.IGNORECASE)
_ETA_RE = re.compile(r"\b(\d{1,2})[:hH](\d{2})?\b")
_SIZE_RE = re.compile(r"\b(20|40|45)\s*(?:ft|feet|hc|dc|rf|'|\")?\b", re.IGNORECASE)
_DRIVER_RE = re.compile(r"(?:tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|lx|tx|driver)\s*[:=\-]?\s*([^\n\-,;0-9]{2,40})", re.IGNORECASE)
_WAREHOUSE_RE = re.compile(r"(?:kho|điểm\s*(?:đóng|trả)|địa\s*chỉ|di\s*kho)\s*[:=\-]?\s*([^\n,;]{2,80})", re.IGNORECASE)
_STANDALONE_STOP_RE = re.compile(
    r"^(?:xe|bks|biển|bien|cont|số|so|chì|chi|seal|kho|nhà\s*máy|kcn|điểm|diem|đóng|dong|trả|tra|sđt|sdt|cccd|cmnd|ngày|ngay|giờ|gio|hẹn|hen)\b",
    re.IGNORECASE,
)


def _has_non_trailer_plate(text: str) -> bool:
    """Kiểm tra dòng văn bản có chứa biển số xe đầu kéo (không tính biển số rơ-moóc R/RM)."""
    for pm in _PLATE_RE.finditer(text):
        cand = pm.group(1).strip()
        if _TRAILER_RE.fullmatch(cand):
            continue
        return True
    return False

_CANCEL_KWS = ("hủy chuyến", "huy chuyen", "hủy cont", "huy cont", "bỏ xe", "bo xe", "không đóng nữa", "khong tra nua")
_UPDATE_KWS = ("đổi xe", "doi xe", "đổi tài", "doi tai", "thay xe", "thay tài", "sửa lại", "sua lai", "cập nhật", "cap nhat", "chuyển sang xe", "chuyen sang")
_CHAT_KWS = ("ok", "oke", "cảm ơn", "cam on", "thanks", "chào", "chao", "dạ", "vâng", "vang")


def infer_intent(text: str, quote_message: str | None = None, entity_count: int = 0) -> str:
    """Suy đoán ý định tin nhắn theo ngữ cảnh trích dẫn và từ khóa điều vận."""
    low = (text or "").strip().lower()
    if any(k in low for k in _CANCEL_KWS):
        return "CANCEL_REQUEST"
    if any(k in low for k in _UPDATE_KWS):
        return "UPDATE_REQUEST"
    if (
        quote_message
        and entity_count > 0
        and any(kw in quote_message.lower() for kw in ("thiếu", "bổ sung", "sai", "kiểm tra", "cont"))
    ):
        return "SUPPLEMENT"
    if any(k in low for k in ("bổ sung", "bo sung", "gửi thêm", "gui them", "cập nhật chì", "cap nhat seal")):
        return "SUPPLEMENT"
    if entity_count == 0 and (len(low) <= 25 or any(low == k or low.startswith(k + " ") for k in _CHAT_KWS)):
        return "IGNORE_CHAT"
    return "PARSE_TRUCK_INFO"


def _split_blocks(text: str) -> list[str]:
    """Tách văn bản tin nhắn thành các đoạn tương ứng từng xe hoặc từng container."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) <= 1:
        return [text.strip()] if text.strip() else []

    # Nếu mỗi dòng có riêng biển số đầu kéo (không tính rơ-moóc) -> tách từng dòng/nhóm dòng đánh số
    blocks: list[str] = []
    current: list[str] = []
    for ln in lines:
        starts_item = bool(re.match(r"^(?:\d+[\.\)]|[-*+•])\s+", ln)) or bool(
            _has_non_trailer_plate(ln) and current and any(_has_non_trailer_plate(c) for c in current)
        )
        if starts_item and current:
            blocks.append("\n".join(current))
            current = [ln]
        else:
            current.append(ln)
    if current:
        blocks.append("\n".join(current))
    return blocks


def heuristic_extract(
    masked_text: str,
    quote_message: str | None = None,
) -> tuple[str, list[ExtractedEntity]]:
    """Phân tích cấu trúc văn bản khi AI Provider không khả dụng."""
    blocks = _split_blocks(masked_text)
    items: list[ExtractedEntity] = []

    for blk in blocks:
        conts = [f"{m.group(1).upper()}{m.group(2)}" for m in _CONT_RE.finditer(blk)]
        trailer_m = _TRAILER_RE.search(blk)
        trailer_no = re.sub(r"\s+", "", trailer_m.group(1).upper()) if trailer_m else None

        plate_no = None
        for pm in _PLATE_RE.finditer(blk):
            raw_cand = pm.group(1).strip()
            if _TRAILER_RE.fullmatch(raw_cand):
                continue
            cand = re.sub(r"\s+", "", raw_cand.upper())
            if trailer_no and cand == trailer_no:
                continue
            plate_no = cand
            break

        phones_found: list[str] = []
        sanitized_for_phone = re.sub(
            r"\b(?:cccd|cmnd|seal|chì|chi|số\s*seal|số\s*chì)\s*[:=\-]?\s*[A-Z0-9\-]+",
            " ",
            blk,
            flags=re.IGNORECASE,
        )
        for pm_ph in _PHONE_RE.finditer(sanitized_for_phone):
            ph_val = re.sub(r"[\s.\-]", "", pm_ph.group(0))
            if ph_val and ph_val not in phones_found:
                phones_found.append(ph_val)
        driver_phone = " | ".join(phones_found) if phones_found else None

        seal_m = _SEAL_RE.search(blk)
        seal_cand = seal_m.group(1).upper() if seal_m else None
        if seal_cand and seal_cand in {"CHUA", "KHONG", "TRONG", "NONE", "NULL", "BAO", "SAU"}:
            seal_cand = None
        seal_no = seal_cand

        eta_m = _ETA_RE.search(blk)
        eta = None
        if eta_m:
            hh = int(eta_m.group(1))
            mm = int(eta_m.group(2) or "0")
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                eta = f"{hh:02d}:{mm:02d}"

        size_m = _SIZE_RE.search(blk)
        size_val = size_m.group(1) if size_m else None

        drv_m = _DRIVER_RE.search(blk)
        driver_name = drv_m.group(1).strip() if drv_m else None
        if not driver_name:
            for ln in blk.splitlines():
                ln_clean = ln.strip()
                if not ln_clean or any(ch.isdigit() for ch in ln_clean) or _STANDALONE_STOP_RE.search(ln_clean):
                    continue
                words = [w for w in ln_clean.split() if w.isalpha()]
                if 2 <= len(words) <= 5 and len(words) == len(ln_clean.split()) and any(w[0].isupper() for w in words):
                    driver_name = " ".join(words)
                    break

        wh_m = _WAREHOUSE_RE.search(blk)
        wh_name = wh_m.group(1).strip() if wh_m else None

        low_blk = blk.lower()
        order_type = None
        if any(k in low_blk for k in ("đóng hàng", "dong hang", "xuất", "xuat", "lấy rỗng", "lay rong")):
            order_type = "LOAD"
        elif any(k in low_blk for k in ("trả hàng", "tra hang", "nhập", "nhap", "hạ vỏ", "ha vo", "mở cont")):
            order_type = "RETURN"

        if not conts:
            if any([plate_no, trailer_no, driver_phone, driver_name, seal_no, wh_name, eta]):
                items.append(
                    ExtractedEntity(
                        plate_number=plate_no,
                        trailer_number=trailer_no,
                        driver_name=driver_name,
                        driver_phone=driver_phone,
                        container_size=size_val,
                        seal_no=seal_no,
                        order_type=order_type,
                        warehouse_name=wh_name,
                        eta=eta,
                        evidence=blk[:200],
                        confidence=0.68,
                    )
                )
        else:
            for c_no in conts:
                items.append(
                    ExtractedEntity(
                        plate_number=plate_no,
                        trailer_number=trailer_no,
                        driver_name=driver_name,
                        driver_phone=driver_phone,
                        container_no=c_no,
                        container_size=size_val,
                        seal_no=seal_no,
                        order_type=order_type,
                        warehouse_name=wh_name,
                        eta=eta,
                        evidence=blk[:200],
                        confidence=0.75 if plate_no else 0.7,
                    )
                )

    intent = infer_intent(masked_text, quote_message=quote_message, entity_count=len(items))
    return intent, items
