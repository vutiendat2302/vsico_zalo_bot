"""Bộ phân tích heuristic nội bộ làm lớp dự phòng khi Cloud LLM ngoại tuyến hoặc thiếu API Key."""

import re

from app.schemas.extract import ExtractedEntity

_CONT_RE = re.compile(r"\b([A-Z]{4})[\s\-]?(\d{7})\b", re.IGNORECASE)
_PLATE_RE = re.compile(r"\b(\d{2}[A-Z]{1,2}[\s\-]?\d{3,5}(?:\.\d{2})?)\b", re.IGNORECASE)
_TRAILER_RE = re.compile(r"\b(\d{2}R[\s\-]?\d{3,5}(?:\.\d{2})?)\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?84|0)(?:\d{2,3}xxxx\d{2}(?:_\d+)?|[\d\s.\-]{8,11}\d)", re.IGNORECASE)
_SEAL_RE = re.compile(r"(?:seal|chì|chi|số\s*seal|số\s*chì)\s*[:=\-]?\s*([A-Z0-9\-]{4,20})", re.IGNORECASE)
_ETA_RE = re.compile(r"\b(\d{1,2})[:hH](\d{2})?\b")
_SIZE_RE = re.compile(r"\b(20|40|45)\s*(?:ft|feet|hc|dc|rf|'|\")?\b", re.IGNORECASE)
_DRIVER_RE = re.compile(r"(?:tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|lx|tx|driver)\s*[:=\-]?\s*([^\n\-,;0-9]{2,40})", re.IGNORECASE)
_WAREHOUSE_RE = re.compile(r"(?:kho|điểm\s*(?:đóng|trả)|địa\s*chỉ|di\s*kho)\s*[:=\-]?\s*([^\n,;]{2,80})", re.IGNORECASE)

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

    # Nếu mỗi dòng có riêng số cont hoặc biển số -> tách từng dòng/nhóm dòng đánh số
    blocks: list[str] = []
    current: list[str] = []
    for ln in lines:
        starts_item = bool(re.match(r"^(?:\d+[\.\)]|[-*+•])\s+", ln)) or bool(_PLATE_RE.search(ln) and current and any(_PLATE_RE.search(c) for c in current))
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
            cand = re.sub(r"\s+", "", pm.group(1).upper())
            if trailer_no and cand == trailer_no:
                continue
            if "R" in cand[:4]:
                continue
            plate_no = cand
            break

        phone_m = _PHONE_RE.search(blk)
        driver_phone = re.sub(r"[\s.\-]", "", phone_m.group(0)) if phone_m else None

        seal_m = _SEAL_RE.search(blk)
        seal_no = seal_m.group(1).upper() if seal_m else None

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
