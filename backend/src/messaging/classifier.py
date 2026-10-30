"""Module Phân Loại Ý Định Tin Nhắn Zalo & Bộ Lọc Hội Thoại Tối Ưu (Fast 2-Tier Intent Classifier).

Tích hợp cơ chế lọc 2 tầng (2-Tier Gatekeeper) siêu nhẹ giúp chặn ngay lập tức các tin nhắn
giao tiếp xã giao ('chào', 'hello', 'cảm ơn', 'dạ vâng', icon...) trong < 0.05ms mà không tốn
chi phí phân tích sâu hay gọi AI:
- Tầng 1 (Instant Social Chat Filter): Kiểm tra độ dài, số lượng chữ số và mẫu câu chào hỏi/xã giao.
- Tầng 2 (Pattern & Keyword Classifier): Nhận diện chính xác tin báo xe (F1, F2, F3, tự do),
  tin cập nhật/đổi xe/lùi giờ, tin bổ sung cont/chì, tin hủy chuyến, hoặc lệnh duyệt của ĐHVT.
"""

import re
from src.domain.enums import Intent


class IntentClassifier:
    """Bộ phân loại ý định tin nhắn tối ưu hiệu năng với cơ chế lọc sớm hội thoại xã giao."""

    # Mẫu nhận diện nhanh các câu chào hỏi, cảm ơn, xác nhận xã giao phổ biến trên Zalo
    _SOCIAL_CHAT_EXACT_REGEX = re.compile(
        r"^(?:hi+|hello+|alo+|chào\b.*|xin\s*chào.*|em\s*chào.*|dạ\b.*|vâng\b.*|"
        r"cảm\s*ơn.*|cám\s*ơn.*|tks\b.*|thanks\b.*|thank\s*you.*|"
        r"ok+\s*(?:anh|chị|em|bác|nhé|ạ|nha|shop|sếp).*|"
        r"đã\s*nhận(?:\s*thông\s*tin)?.*|nhận\s*thông\s*tin.*|"
        r"chúc\s*(?:buổi\s*sáng|mọi\s*người|anh|chị|cuối\s*tuần).*|"
        r"haha+|hihi+|\:\)+|\👍+|\🙏+|\❤️+)$",
        re.IGNORECASE,
    )

    # Biểu thức nhận diện biển số xe (có dấu gạch/chấm, khoảng trắng hoặc viết liền)
    _PLATE_PATTERN = re.compile(
        r"\b\d{2}[A-Za-z]{1,2}(?:[\s.\-]*\d{3}[\s.\-]*\d{1,2}|[\s.\-]*\d{4,5})\b"
    )
    # Biểu thức nhận diện số hiệu container (chuẩn 4 chữ + 6-7 số hoặc đi kèm từ khóa cont/cntr)
    _CONTAINER_PATTERN = re.compile(
        r"\b[A-Za-z]{3}[UJuZujz][\s.\-]*\d{5,8}\b|(?:số\s*cont|so\s*cont|container|cntr|cont)\s*[:\-]?\s*[A-Za-z0-9\-]{5,15}",
        re.IGNORECASE,
    )
    # Biểu thức nhận diện SĐT
    _PHONE_PATTERN = re.compile(
        r"(?:\+?84|0)\d[\d\s.\-*xX]{7,11}[\d*xX]"
    )
    # Từ khóa nghiệp vụ vận tải (có dấu + không dấu)
    _TRUCK_KEYWORDS = re.compile(
        r"(?:biển\s*số|bien\s*so|\bbks\b|số\s*xe|so\s*xe|đầu\s*kéo|dau\s*keo|mooc|rơ\s*moóc|ro\s*mooc|"
        r"tài\s*xế|tai\s*xe|lái\s*xe|lai\s*xe|bác\s*tài|bac\s*tai|\btx\b|\blx\b|"
        r"số\s*cont|so\s*cont|container|\bcntr\b|\bcont\b|chưa\s*lấy\s*cont|chờ\s*cấp\s*cont|chưa\s*có\s*cont|"
        r"số\s*chì|so\s*chi|\bseal\b|niêm\s*chì|niem\s*chi|"
        r"đóng\s*hàng|dong\s*hang|lệnh\s*đóng|lenh\s*dong|đóng\s*cont|dong\s*cont|lấy\s*cont\s*rỗng|lay\s*cont\s*rong|"
        r"trả\s*hàng|tra\s*hang|lệnh\s*trả|lenh\s*tra|trả\s*cont|tra\s*cont|hạ\s*cont|ha\s*cont|hạ\s*bãi|ha\s*bai|"
        r"hàng\s*xuất|hang\s*xuat|hàng\s*nhập|hang\s*nhap|"
        r"điều\s*xe|dieu\s*xe|bố\s*trí\s*xe|bo\s*tri\s*xe|xe\s*chạy|xe\s*chay|xe\s*vào\s*kho|xe\s*vao\s*kho|"
        r"thông\s*báo\s*xe|thong\s*bao\s*xe|thông\s*tin\s*xe|thong\s*tin\s*xe|danh\s*sách\s*xe|danh\s*sach\s*xe|kế\s*hoạch\s*xe|ke\s*hoach\s*xe|"
        r"mã\s*lệnh|ma\s*lenh|số\s*lệnh|so\s*lenh|booking|số\s*vận\s*đơn|so\s*van\s*don)",
        re.IGNORECASE,
    )

    @classmethod
    def classify(cls, text: str) -> Intent:
        """Phân tích nội dung văn bản qua bộ lọc 2 tầng để xác định ý định (Intent) nhanh và tiết kiệm nhất.

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

        # 3. Kiểm tra yêu cầu hủy chuyến xe
        if re.search(r"\b(?:hủy\s*xe|huy\s*xe|hủy\s*chuyến|huy\s*chuyen|báo\s*hủy|bao\s*huy)\b", lower):
            return Intent.CANCEL_REQUEST

        # 4. TẦNG 1 (Fast Gatekeeper): Nếu không có ít nhất 2 chữ số và khớp mẫu chào hỏi/xã giao -> Bỏ qua ngay lập tức
        digit_count = sum(1 for ch in normalized if ch.isdigit())
        if digit_count < 2 and cls._SOCIAL_CHAT_EXACT_REGEX.match(lower):
            return Intent.IGNORE_CHAT

        # 5. Kiểm tra yêu cầu đổi xe / đổi tài xế / đính chính / sửa cont / đổi giờ (T27, T28, T29)
        if re.search(
            r"\b(?:đổi\s*xe|doi\s*xe|đổi\s*tài|doi\s*tai|đổi\s*lái\s*xe|doi\s*lai\s*xe|thay\s*xe|"
            r"đổi\s*số\s*xe|đính\s*chính|dinh\s*chinh|sửa\s*cont|sua\s*cont|sửa\s*chì|sua\s*chi|"
            r"cập\s*nhật\s*lại|cap\s*nhat\s*lai|lùi\s*giờ|lui\s*gio|đổi\s*lịch|doi\s*lich|xe\s*đến\s*muộn)\b",
            lower,
        ):
            return Intent.UPDATE_REQUEST

        # 6. Kiểm tra tin nhắn trả lời bổ sung thông tin (T26: bổ sung cont, chì, giờ)
        if re.search(
            r"\b(?:bổ\s*sung|bo\s*sung|gửi\s*thêm\s*số\s*cont|gui\s*them\s*so\s*cont|báo\s*thêm\s*chì|cập\s*nhật\s*số\s*cont)\b",
            lower,
        ):
            return Intent.SUPPLEMENT

        # 7. TẦNG 2: Kiểm tra dấu hiệu báo thông tin xe / container (biển số, số cont, SĐT, từ khóa vận tải)
        has_plate = bool(cls._PLATE_PATTERN.search(normalized))
        has_cont = bool(cls._CONTAINER_PATTERN.search(normalized))
        has_phone = bool(cls._PHONE_PATTERN.search(normalized))
        has_keywords = bool(cls._TRUCK_KEYWORDS.search(normalized))

        if has_plate or has_cont or (has_phone and has_keywords) or has_keywords:
            return Intent.PARSE_TRUCK_INFO

        return Intent.IGNORE_CHAT
