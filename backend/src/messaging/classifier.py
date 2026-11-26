"""Module Phân Loại Ý Định Tin Nhắn Zalo & Bộ Lọc Tín Hiệu Xe 2 Tầng (Fast 2-Tier Intent Classifier).

Tích hợp cơ chế thẩm định tín hiệu phương tiện (`extract_vehicle_signals`, `classify_junk`) và
phân cấp ưu tiên xử lý xung đột (Conflict Resolution Hierarchy):
- Tầng 1 (Junk / Social Chat Filter): Chặn tin rỗng, chỉ emoji, URL không chứa xe/cont,
  câu chào hỏi/xã giao (`COMMON_CHAT_PHRASES`), tin không có tín hiệu xe -> `IGNORE_CHAT`.
- Tầng 2 (Pattern & Keyword Classifier): Nhận diện chính xác lệnh duyệt/sửa của ĐHVT,
  yêu cầu hủy chuyến (`CANCEL_REQUEST`), đổi xe/đổi tài/sửa chì/lùi giờ (`UPDATE_REQUEST`),
  bổ sung thông tin (`SUPPLEMENT`), hoặc tin báo xe (`PARSE_TRUCK_INFO`).
"""

import re
from typing import Any
from src.domain.enums import Intent
from src.domain.patterns import ANY_PLATE_REGEX, CONT_REGEX, PHONE_PATTERN, deglue_transport_entities


# Danh sách cụm từ xã giao ngắn không liên quan đến điều xe
COMMON_CHAT_PHRASES: frozenset[str] = frozenset({
    "ok", "oke", "okay", "dạ", "da", "vâng", "vang", "dạ em nhận rồi ạ",
    "da em nhan roi a", "nhận rồi", "nhan roi", "đã nhận", "da nhan",
    "cảm ơn", "cam on", "cảm ơn anh", "cam on anh", "cảm ơn em", "cam on em",
    "xin chào", "xin chao", "xin chào cả nhà", "chào cả nhà", "chao ca nha",
    "chào anh", "chao anh", "ok a", "ok anh", "da vang", "dạ vâng",
    "dạ a", "da a", "done", "da gui", "dạ gửi", "thanks", "tks",
})


class IntentClassifier:
    """Bộ phân loại ý định tin nhắn tối ưu hiệu năng kết hợp bộ lọc tín hiệu xe."""

    # Mẫu nhận diện nhanh các câu chào hỏi, cảm ơn, xác nhận xã giao phổ biến trên Zalo
    _SOCIAL_CHAT_EXACT_REGEX = re.compile(
        r"^(?:hi+|hello+|alo+|chào\b.*|xin\s*chào.*|em\s*chào.*|dạ\b.*|vâng\b.*|"
        r"cảm\s*ơn.*|cám\s*ơn.*|tks\b.*|thanks\b.*|thank\s*you.*|"
        r"ok+\s*(?:anh|chị|em|bác|nhé|ạ|nha|shop|sếp|bạn)?.*|"
        r"đã\s*nhận(?:\s*thông\s*tin)?.*|nhận\s*thông\s*tin.*|"
        r"mọi\s*người\s*(?:ăn\s*cơm|nghỉ\s*trưa|ngủ).*|"
        r"chúc\s*(?:buổi\s*sáng|mọi\s*người|anh|chị|cuối\s*tuần).*|"
        r"haha+|hihi+|\:\)+|[\U0001F300-\U0001FAFF\u2600-\u27BF\s]+)$",
        re.IGNORECASE,
    )

    # Biểu thức nhận diện biển số xe (đầu kéo + rơ-moóc, chuẩn _PROVINCE/_SEP/_DIGITS/_TAIL)
    _PLATE_PATTERN = ANY_PLATE_REGEX
    # Biểu thức nhận diện số hiệu container (3 chữ + U/J/Z + đúng 7 chữ số)
    _CONTAINER_PATTERN = CONT_REGEX
    # Biểu thức nhận diện SĐT Việt Nam (đúng 10 ký tự số/che, hỗ trợ +84/0 và NBSP)
    _PHONE_PATTERN = PHONE_PATTERN
    # Từ khóa nghiệp vụ vận tải (có dấu + không dấu)
    _TRUCK_KEYWORDS = re.compile(
        r"(?:biển\s*số|bien\s*so|\bbks\b|\bbsx\b|số\s*xe|so\s*xe|đầu\s*kéo|dau\s*keo|mooc|moóc|rơ[\s.\-]?moóc|ro[\s.\-]?mooc|\brm\b|"
        r"tài\s*xế|tai\s*xe|taixe|tàixế|lái\s*xe|lai\s*xe|laixe|láixe|bác\s*tài|bac\s*tai|bactai|\btxe\b|\btx\b|\blx\b|\bsđt\b|\bsdt\b|\bsddt\b|\bđt\b|"
        r"số\s*cont|so\s*cont|container|\bcntr\b|\bcont\b|chưa\s*lấy\s*cont|chờ\s*cấp\s*cont|chưa\s*có\s*cont|"
        r"số\s*chì|so\s*chi|\bchì\b|\bchi\b|\bseal\b|niêm\s*chì|niem\s*chi|"
        r"đóng\s*hàng|dong\s*hang|lệnh\s*đóng|lenh\s*dong|đóng\s*cont|dong\s*cont|lấy\s*cont\s*rỗng|lay\s*cont\s*rong|"
        r"trả\s*hàng|tra\s*hang|lệnh\s*trả|lenh\s*tra|trả\s*cont|tra\s*cont|hạ\s*cont|ha\s*cont|hạ\s*bãi|ha\s*bai|"
        r"hàng\s*xuất|hang\s*xuat|hàng\s*nhập|hang\s*nhap|"
        r"điều\s*xe|dieu\s*xe|bố\s*trí\s*xe|bo\s*tri\s*xe|xe\s*chạy|xe\s*chay|xe\s*vào\s*kho|xe\s*vao\s*kho|"
        r"thông\s*báo\s*xe|thong\s*bao\s*xe|thông\s*tin\s*xe|thong\s*tin\s*xe|danh\s*sách\s*xe|danh\s*sach\s*xe|kế\s*hoạch\s*xe|ke\s*hoach\s*xe|"
        r"mã\s*lệnh|ma\s*lenh|số\s*lệnh|so\s*lenh|\b(?:ro|lo)\d{3,6}\b|booking|số\s*vận\s*đơn|so\s*van\s*don)",
        re.IGNORECASE,
    )

    @classmethod
    def extract_vehicle_signals(cls, text: str) -> dict[str, Any]:
        """Trích xuất danh mục các tín hiệu điều vận (container, biển số, SĐT, chì/seal, từ khóa vận tải)."""
        t_clean = deglue_transport_entities((text or "").strip())
        t_low = t_clean.lower()
        m_cont = cls._CONTAINER_PATTERN.findall(t_clean)
        m_plate = cls._PLATE_PATTERN.findall(t_clean)
        m_phone = cls._PHONE_PATTERN.findall(t_clean)
        has_seal = bool(re.search(r"\b(?:seal|chì|niêm\s*chì|chi)\b", t_low))
        has_truck_kw = bool(cls._TRUCK_KEYWORDS.search(t_clean))
        return {
            "has_cont": len(m_cont) > 0,
            "conts": m_cont,
            "has_plate": len(m_plate) > 0,
            "plates": m_plate,
            "has_phone": len(m_phone) > 0,
            "phones": m_phone,
            "has_seal": has_seal,
            "has_truck_kw": has_truck_kw,
        }

    @classmethod
    def classify_junk(cls, text: str) -> tuple[str, str, dict[str, Any]]:
        """Phân loại sơ bộ tin nhắn thành `JUNK` (bỏ qua), `SUSPECT` (1 tín hiệu yếu) hoặc `CANDIDATE`."""
        signals = cls.extract_vehicle_signals(text)
        t_clean = (text or "").strip()
        t_low = t_clean.lower()

        if not t_clean:
            return "JUNK", "Tin nhắn rỗng", signals

        if not re.search(r"[a-zA-Z0-9\u00C0-\u1EF9]", t_clean):
            return "JUNK", "Chỉ chứa biểu tượng hoặc ký tự đặc biệt", signals

        if re.search(r"https?://|www\.", t_low):
            if not signals["has_cont"] and not signals["has_plate"]:
                return "JUNK", "Liên kết trang web không có thông tin xe", signals

        t_words = re.sub(r"[\.,\!\?\:\;\-~]", "", t_low).strip()
        if t_words in COMMON_CHAT_PHRASES:
            return "JUNK", "Xác nhận xã giao hoặc chào hỏi thông thường", signals

        digit_count = sum(1 for ch in t_clean if ch.isdigit())
        if digit_count < 2 and cls._SOCIAL_CHAT_EXACT_REGEX.match(t_low):
            return "JUNK", "Câu chào hỏi/xã giao không chứa thực thể vận tải", signals

        if signals["has_cont"] or signals["has_plate"] or signals["has_truck_kw"]:
            return "CANDIDATE", "Có tín hiệu phương tiện hoặc container", signals

        if signals["has_phone"]:
            return "SUSPECT", "Chỉ có tín hiệu SĐT, cần kiểm tra ngữ cảnh", signals

        return "JUNK", "Không chứa tín hiệu điều vận", signals

    @classmethod
    def classify(cls, text: str) -> Intent:
        """Phân tích nội dung văn bản qua bộ lọc tín hiệu và thứ tự ưu tiên nghiệp vụ.

        Args:
            text (str): Nội dung tin nhắn văn bản thô từ Zalo.

        Returns:
            Intent: Giá trị Enum biểu diễn ý định của tin nhắn.
        """
        if not text or not text.strip():
            return Intent.IGNORE_CHAT

        normalized = text.strip()
        lower = normalized.lower()

        # 1. Kiểm tra lệnh duyệt gửi khách của Điều phối viên ("OK", "OK #12", "DUYET 12")
        if re.match(r"^(?:ok|duyệt|duyet)(?:\s*#?\d+)?$", lower):
            return Intent.APPROVE_OUTBOUND

        # 2. Kiểm tra lệnh sửa bản nháp của Điều phối viên
        if re.match(r"^(?:sửa|sua|edit)\s*#?\d+\b", lower):
            return Intent.EDIT_PENDING

        # 3. Kiểm tra yêu cầu hủy chuyến xe (loại trừ trường hợp "hủy thay xe / hủy đổi xe" vẫn chạy chuyến)
        if re.search(r"\b(?:hủy\s*xe|huy\s*xe|hủy\s*chuyến|huy\s*chuyen|hủy\s*cont|huy\s*cont|xin\s*hủy|xin\s*huy|báo\s*hủy|bao\s*huy)\b", lower):
            return Intent.CANCEL_REQUEST

        # 4. Yêu cầu đổi xe / đổi tài xế / đính chính / sửa cont / đổi giờ / hủy thay xe (T27, T28, T29)
        if not re.search(r"\bcập\s*nhật\s*số\s*cont\b|\bcap\s*nhat\s*so\s*cont\b", lower) and re.search(
            r"\b(?:đổi\s+(?:sang|qua|thành|lại|về|thông\s*tin)|doi\s+(?:sang|qua|thanh|lai|ve|thong\s*tin)|"
            r"thay\s+(?:bằng|sang|xe|đổi)|chuyển\s+sang\s+xe|chỉ\s*đổi\s*xe|chi\s*doi\s*xe|"
            r"hủy\s*(?:thay|đổi)\s*xe|huy\s*(?:thay|doi)\s*xe|không\s*đổi\s*nữa|khong\s*doi\s*nua|"
            r"đổi\s*xe|doi\s*xe|đổi\s*tài|doi\s*tai|đổi\s*lái\s*xe|doi\s*lai\s*xe|"
            r"đổi\s*rơ[\s.\-]?moóc|doi\s*ro[\s.\-]?mooc|đổi\s*mooc|doi\s*mooc|"
            r"sửa\s*thông\s*tin|sua\s*thong\s*tin|thay\s*doi|"
            r"đổi\s*số|doi\s*so|sửa\s*số|sua\s*so|đính\s*chính|dinh\s*chinh|sửa\s*cont|sua\s*cont|sửa\s*chì|sua\s*chi|sửa\s*seal|sua\s*seal|"
            r"cập\s*nhật(?:\s*lại|\s*thông\s*tin|\s*xe)?|cap\s*nhat(?:\s*lai|\s*thong\s*tin|\s*xe)?|"
            r"lùi\s*giờ|lui\s*gio|đổi\s*lịch|doi\s*lich|xe\s*đến\s*muộn)\b",
            lower,
        ):
            return Intent.UPDATE_REQUEST

        # 5. Tin nhắn trả lời bổ sung thông tin (T26: bổ sung cont, chì, giờ, seal cont)
        if re.search(
            r"\b(?:bổ\s*sung|bo\s*sung|gửi\s*thêm\s*số\s*cont|gui\s*them\s*so\s*cont|báo\s*thêm\s*chì|cập\s*nhật\s*số\s*cont)\b"
            r"|^(?:seal\s+cont|chì\s+cont|chi\s+cont)\b",
            lower,
        ):
            return Intent.SUPPLEMENT

        # 6. TẦNG 1 & 2: Thẩm định tín hiệu xe (JUNK -> IGNORE_CHAT, CANDIDATE/SUSPECT -> PARSE_TRUCK_INFO)
        verdict, _, signals = cls.classify_junk(normalized)
        if verdict == "JUNK":
            return Intent.IGNORE_CHAT

        if signals["has_plate"] or signals["has_cont"] or signals["has_truck_kw"]:
            return Intent.PARSE_TRUCK_INFO

        return Intent.IGNORE_CHAT
