"""Module Phân Loại & Thống Kê Taxonomy Tin Nhắn Theo Bảng 1 & Bảng 2 (T01 -> T40).

Thực hiện phân tích toàn diện từng tin nhắn Zalo theo đúng bộ tiêu chí khảo sát nghiệp vụ:
1. **Bảng 1 (Hạng mục dữ liệu 1.1 -> 1.6)**:
   - 1.1. Nhận diện loại lệnh và cấu trúc tin
   - 1.2. Thông tin xe và tài xế
   - 1.3. Container và số chì
   - 1.4. Kho, khách hàng và địa điểm
   - 1.5. Thời gian và tiến độ
   - 1.6. Định dạng, bố cục và ngoại lệ
   *Quy tắc đếm*: Đếm theo số ID tin nhắn riêng biệt chứa hạng mục (một tin có nhiều xe
   vẫn chỉ tính 1 lần cho hạng mục đó).

2. **Bảng 2 (40 Dạng tin T01 -> T40)**:
   - Xác định một `primary_type` (dạng chính duy nhất) cho mỗi tin nhắn để tránh đếm trùng.
   - Đánh dấu riêng toàn bộ các đặc điểm phụ (`secondary_types` / `matched_types`).
"""

import re
from typing import Any, Optional

from src.domain.enums import Intent
from src.domain.models import ExtractedContainerLine


# Định nghĩa danh mục chuẩn Bảng 1 (1.1 -> 1.6)
TABLE1_DEFINITIONS: dict[str, list[dict[str, str]]] = {
    "1.1_nhan_dien_lenh_va_cau_truc": [
        {"code": "1.1.1", "name": "Lệnh đóng", "variants": "Đóng, đóng hàng, lệnh đóng, đóng cont, lấy cont rỗng"},
        {"code": "1.1.2", "name": "Lệnh trả", "variants": "Trả, trả hàng, lệnh trả, trả cont, hạ cont"},
        {"code": "1.1.3", "name": "Từ khóa xuất/nhập", "variants": "Xuất, nhập, hàng xuất, hàng nhập"},
        {"code": "1.1.4", "name": "Từ khóa điều phối", "variants": "Điều xe, bố trí xe, xe chạy, xe vào kho"},
        {"code": "1.1.5", "name": "Tiêu đề thông báo", "variants": "Thông báo xe, thông tin xe, danh sách xe, kế hoạch xe"},
        {"code": "1.1.6", "name": "Mã lệnh/mã vận đơn", "variants": "Mã lệnh, số lệnh, booking, mã booking, số vận đơn"},
        {"code": "1.1.7", "name": "Nội dung tự do", "variants": "Có tiêu đề, không tiêu đề, chỉ có danh sách xe"},
        {"code": "1.1.8", "name": "Nhiều lệnh trong một tin", "variants": "Nhiều nhóm thông tin đóng/trả trong cùng nội dung"},
    ],
    "1.2_thong_tin_xe_va_tai_xe": [
        {"code": "1.2.1", "name": "Biển số đầu kéo", "variants": "Biển số, BKS, xe, đầu kéo, số xe (30H-123.45)"},
        {"code": "1.2.2", "name": "Biển số không dấu phân cách", "variants": "Viết liền, có khoảng trắng (30H12345)"},
        {"code": "1.2.3", "name": "Biển số rơ-moóc", "variants": "Mooc, rơ-moóc, số mooc, biển mooc"},
        {"code": "1.2.4", "name": "Tên tài xế", "variants": "Tài xế, TX, lái xe, tên lái xe, bác tài"},
        {"code": "1.2.5", "name": "Số điện thoại tài xế", "variants": "SĐT, ĐT, điện thoại, liên hệ, số tài xế"},
        {"code": "1.2.6", "name": "Nhiều tài xế/xe", "variants": "Mỗi xe một dòng, nhiều xe đánh số, nhiều khối dữ liệu"},
        {"code": "1.2.7", "name": "Thiếu thông tin tài xế", "variants": "Có xe nhưng không tên hoặc số điện thoại"},
        {"code": "1.2.8", "name": "Thay đổi xe/tài xế", "variants": "Tin cập nhật xe khác, đổi lái xe"},
    ],
    "1.3_container_va_so_chi": [
        {"code": "1.3.1", "name": "Số container", "variants": "Cont, container, số cont, số container, CNTR"},
        {"code": "1.3.2", "name": "Số container viết sai định dạng", "variants": "Thiếu ký tự, thừa ký tự, sai checksum, dấu cách"},
        {"code": "1.3.3", "name": "Container chưa có số", "variants": "Chưa lấy cont, chờ cấp cont, chưa biết số"},
        {"code": "1.3.4", "name": "Nhiều container", "variants": "Một xe nhiều cont, một tin nhiều cont"},
        {"code": "1.3.5", "name": "Kích thước/loại container", "variants": "20, 40, 45, 20DC, 40HC, 40RF..."},
        {"code": "1.3.6", "name": "Số chì", "variants": "Chì, số chì, seal, seal no, niêm chì"},
        {"code": "1.3.7", "name": "Thiếu số chì", "variants": "Để trống, chưa có chì, bổ sung sau"},
        {"code": "1.3.8", "name": "Sửa số container/số chì", "variants": "Đính chính, sửa cont, sửa chì, cập nhật lại"},
        {"code": "1.3.9", "name": "Container gắn nhầm xe", "variants": "Nhiều xe và container nhưng không rõ quan hệ"},
    ],
    "1.4_kho_khach_hang_va_dia_diem": [
        {"code": "1.4.1", "name": "Tên kho", "variants": "Tên đầy đủ, tên tắt, biệt danh, mã kho"},
        {"code": "1.4.2", "name": "Kho viết tắt", "variants": "Chữ cái đầu, tên địa phương, mã nội bộ"},
        {"code": "1.4.3", "name": "Kho viết sai chính tả", "variants": "Thiếu dấu, sai dấu, gõ nhầm"},
        {"code": "1.4.4", "name": "Tên khách hàng", "variants": "Tên pháp lý, tên thương mại, tên rút gọn"},
        {"code": "1.4.5", "name": "Khách hàng viết tắt", "variants": "Tên viết tắt, tên tiếng Anh, biệt danh"},
        {"code": "1.4.6", "name": "Địa chỉ kho", "variants": "Địa chỉ đầy đủ, số đường, khu công nghiệp"},
        {"code": "1.4.7", "name": "Khu công nghiệp", "variants": "Tên đầy đủ, tên viết tắt (KCN, VSIP...)"},
        {"code": "1.4.8", "name": "Cảng/điểm lấy-trả", "variants": "Tên cảng, mã cảng, tên terminal"},
        {"code": "1.4.9", "name": "Điểm đóng hàng", "variants": "Kho đóng, điểm đóng, nơi đóng"},
        {"code": "1.4.10", "name": "Điểm trả hàng", "variants": "Kho trả, nơi hạ, điểm hạ"},
        {"code": "1.4.11", "name": "Thiếu kho", "variants": "Không nêu kho, chỉ nêu khách hàng"},
        {"code": "1.4.12", "name": "Thiếu khách hàng", "variants": "Chỉ có kho hoặc địa điểm"},
        {"code": "1.4.13", "name": "Tên kho/khách trùng nhau", "variants": "Một tên gọi có thể chỉ nhiều đối tượng"},
    ],
    "1.5_thoi_gian_va_tien_do": [
        {"code": "1.5.1", "name": "Ngày chạy", "variants": "Ngày/tháng, ngày-tháng, ngày đầy đủ (27/10)"},
        {"code": "1.5.2", "name": "Giờ dự kiến", "variants": "8h, 08:00, 8 giờ sáng"},
        {"code": "1.5.3", "name": "Thời gian dự kiến đến kho", "variants": "ETA, giờ đến, dự kiến vào kho"},
        {"code": "1.5.4", "name": "Thời gian tương đối", "variants": "Sáng nay, chiều nay, tối, mai"},
        {"code": "1.5.5", "name": "Thời gian chưa xác định", "variants": "Chưa có giờ, báo sau, chờ điều phối"},
        {"code": "1.5.6", "name": "Trễ/đổi lịch", "variants": "Lùi giờ, đổi lịch, xe đến muộn"},
    ],
    "1.6_dinh_dang_bo_cuc_va_ngoai_le": [
        {"code": "1.6.1", "name": "Tin theo mẫu cố định", "variants": "Có nhãn trường và giá trị theo từng dòng"},
        {"code": "1.6.2", "name": "Tin dạng danh sách", "variants": "Đánh số 1, 2, 3; mỗi xe một dòng"},
        {"code": "1.6.3", "name": "Tin dạng bảng", "variants": "Dữ liệu phân tách bằng tab, dấu |"},
        {"code": "1.6.4", "name": "Tin một dòng", "variants": "Các trường nối nhau trên 1 dòng duy nhất"},
        {"code": "1.6.5", "name": "Tin nhiều dòng", "variants": "Mỗi trường một dòng hoặc nhiều khối xe"},
        {"code": "1.6.6", "name": "Tin có emoji/ký hiệu", "variants": "Icon, dấu *, -, #, :"},
        {"code": "1.6.7", "name": "Tin viết hoa toàn bộ", "variants": "Viết hoa toàn bộ nội dung"},
        {"code": "1.6.8", "name": "Tin không dấu", "variants": "Tiếng Việt bỏ dấu"},
        {"code": "1.6.9", "name": "Tin có lỗi chính tả", "variants": "Sai dấu, viết nhầm, gõ thiếu"},
        {"code": "1.6.10", "name": "Tin trích dẫn/chuyển tiếp", "variants": "Có nội dung cũ và nội dung mới"},
        {"code": "1.6.11", "name": "Tin trả lời bổ sung", "variants": "Chỉ bổ sung số cont, số chì hoặc giờ"},
        {"code": "1.6.12", "name": "Tin trùng lặp", "variants": "Gửi lại cùng nội dung"},
        {"code": "1.6.13", "name": "Tin không liên quan", "variants": "Trao đổi ngoài nghiệp vụ"},
    ],
}

# Định nghĩa chuẩn 40 dạng tin Bảng 2 (T01 -> T40)
TABLE2_DEFINITIONS: dict[str, dict[str, str]] = {
    "T01": {"name": "Lệnh đóng chuẩn", "rule": "Có thể nhận diện rõ là lệnh đóng"},
    "T02": {"name": "Lệnh trả chuẩn", "rule": "Có thể nhận diện rõ là lệnh trả"},
    "T03": {"name": "Lệnh đóng không ghi rõ từ khóa đóng", "rule": "Phải suy ra từ ngữ cảnh hoặc trường dữ liệu"},
    "T04": {"name": "Lệnh trả không ghi rõ từ khóa trả", "rule": "Phải suy ra từ ngữ cảnh hoặc trường dữ liệu"},
    "T05": {"name": "Một xe, một container", "rule": "Một bộ thông tin xe-container"},
    "T06": {"name": "Một xe, nhiều container", "rule": "Một xe gắn nhiều container"},
    "T07": {"name": "Nhiều xe, mỗi xe một container", "rule": "Nhiều bộ xe-container"},
    "T08": {"name": "Nhiều xe, nhiều container", "rule": "Phải xác định đúng quan hệ xe-container"},
    "T09": {"name": "Một tin chứa nhiều lệnh", "rule": "Có nhiều nhóm nghiệp vụ trong cùng tin"},
    "T10": {"name": "Lệnh đóng chưa có số container", "rule": "Container sẽ được bổ sung sau"},
    "T11": {"name": "Thiếu biển số xe", "rule": "Không đủ thông tin xe"},
    "T12": {"name": "Thiếu số chì", "rule": "Không có số chì trong tin"},
    "T13": {"name": "Thiếu tên tài xế", "rule": "Không có tên tài xế"},
    "T14": {"name": "Thiếu số điện thoại", "rule": "Không có số điện thoại"},
    "T15": {"name": "Thiếu kho", "rule": "Không xác định được kho"},
    "T16": {"name": "Thiếu khách hàng", "rule": "Không xác định được khách hàng"},
    "T17": {"name": "Thiếu nhiều trường", "rule": "Thiếu từ hai trường trở lên"},
    "T18": {"name": "Số container sai định dạng", "rule": "Không đúng cấu trúc số container"},
    "T19": {"name": "Số container sai check digit", "rule": "Không vượt qua kiểm tra ISO 6346"},
    "T20": {"name": "Không xác định được loại lệnh", "rule": "Không đủ căn cứ phân loại"},
    "T21": {"name": "Không khớp tên kho", "rule": "Không ánh xạ được về kho chuẩn"},
    "T22": {"name": "Không khớp tên khách hàng", "rule": "Không ánh xạ được về khách hàng chuẩn"},
    "T23": {"name": "Kho/khách hàng có nhiều kết quả khớp", "rule": "Alias không duy nhất"},
    "T24": {"name": "Một tin có nhiều kho", "rule": "Cần gắn đúng kho cho từng container"},
    "T25": {"name": "Một tin có nhiều khách hàng", "rule": "Cần gắn đúng khách hàng cho từng container"},
    "T26": {"name": "Tin cập nhật/bổ sung thông tin", "rule": "Thêm trường cho lệnh đã gửi trước"},
    "T27": {"name": "Tin đính chính/thay thế dữ liệu", "rule": "Sửa thông tin cũ"},
    "T28": {"name": "Tin đổi xe/đổi tài xế", "rule": "Thay đổi phương tiện hoặc tài xế"},
    "T29": {"name": "Tin đổi giờ/đổi lịch", "rule": "Cập nhật thời gian vận chuyển"},
    "T30": {"name": "Tin trùng lặp", "rule": "Nội dung được gửi lại"},
    "T31": {"name": "Tin chuyển tiếp/trích dẫn", "rule": "Có nội dung cũ được dẫn lại"},
    "T32": {"name": "Tin sai định dạng", "rule": "Không thể phân tích theo các cấu trúc hỗ trợ"},
    "T33": {"name": "Tin không phải lệnh vận tải", "rule": "Trao đổi thông thường"},
    "T34": {"name": "Tin có dữ liệu mâu thuẫn", "rule": "Ví dụ nhiều biển số hoặc nhiều số cont không rõ quan hệ"},
    "T35": {"name": "Tin chỉ có thông tin xe", "rule": "Có xe nhưng chưa đủ thông tin lệnh"},
    "T36": {"name": "Tin chỉ có thông tin container", "rule": "Có container nhưng không đủ dữ liệu xe/lệnh"},
    "T37": {"name": "Tin không có nhãn trường", "rule": "Phải dựa vào cấu trúc và ngữ cảnh"},
    "T38": {"name": "Tin chứa nhiều định dạng hỗn hợp", "rule": "Văn xuôi kết hợp danh sách hoặc bảng"},
    "T39": {"name": "Tin có dữ liệu thời gian mơ hồ", "rule": "Không xác định được ngày/giờ chính xác"},
    "T40": {"name": "Dạng khác chưa phân loại", "rule": "Giữ lại để cập nhật taxonomy"},
}


class MessageTaxonomyAnalyzer:
    """Bộ phân tích và phân loại một tin nhắn theo chuẩn Bảng 1 (1.1->1.6) và Bảng 2 (T01->T40)."""

    _VIETNAMESE_DIACRITICS = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
        re.IGNORECASE,
    )

    @classmethod
    def analyze(
        cls,
        raw_text: str,
        intent: Intent,
        lines: list[ExtractedContainerLine],
        quote_msg_id: Optional[str] = None,
        is_duplicate_content: bool = False,
        unmatched_warehouse: bool = False,
        unmatched_customer: bool = False,
        ambiguous_route_match: bool = False,
    ) -> dict[str, Any]:
        """Phân tích một tin nhắn và trả về kết quả khớp Bảng 1 & Bảng 2 (T01 -> T40).

        Args:
            raw_text (str): Nội dung văn bản gốc của tin nhắn.
            intent (Intent): Ý định đã phân loại của tin nhắn.
            lines (list[ExtractedContainerLine]): Danh sách dòng xe/container đã bóc tách và thẩm định.
            quote_msg_id (Optional[str]): Mã tin nhắn được trích dẫn (nếu có).
            is_duplicate_content (bool): Cờ báo nội dung trùng lặp với tin đã gửi trước đó.
            unmatched_warehouse (bool): Cờ báo tên kho không khớp danh mục chuẩn.
            unmatched_customer (bool): Cờ báo tên khách không khớp danh mục chuẩn.
            ambiguous_route_match (bool): Cờ báo kho/khách khớp nhiều kết quả (mơ hồ).

        Returns:
            dict[str, Any]: Từ điển chứa `primary_type`, `matched_types`, `table1_codes`.
        """
        text = (raw_text or "").strip()
        lower = text.lower()
        table1_codes: set[str] = set()
        t_codes: list[str] = []

        def add_t(code: str) -> None:
            if code not in t_codes:
                t_codes.append(code)

        # Kiểm tra tin không liên quan (T33 / 1.6.13)
        if intent == Intent.IGNORE_CHAT or not text:
            table1_codes.add("1.6.13")
            add_t("T33")
            return {
                "primary_type": "T33",
                "primary_type_name": TABLE2_DEFINITIONS["T33"]["name"],
                "matched_types": t_codes,
                "table1_codes": sorted(table1_codes),
            }

        # --- PHÂN TÍCH NHÓM 1.1: NHẬN DIỆN LỆNH & CẤU TRÚC ---
        order_types = {ln.order_type for ln in lines if ln.order_type}
        any_inferred = any(ln.inferred_order_type for ln in lines)

        if "dong" in order_types:
            table1_codes.add("1.1.1")
            if any(ln.order_type == "dong" and ln.inferred_order_type for ln in lines):
                add_t("T03")
            else:
                add_t("T01")
        if "tra" in order_types:
            table1_codes.add("1.1.2")
            if any(ln.order_type == "tra" and ln.inferred_order_type for ln in lines):
                add_t("T04")
            else:
                add_t("T02")
        if not order_types:
            add_t("T20")

        if len(order_types) >= 2:
            table1_codes.add("1.1.8")
            add_t("T09")

        if re.search(r"\b(?:xuất|xuat|nhập|nhap|hàng\s*xuất|hang\s*xuat|hàng\s*nhập|hang\s*nhap)\b", lower):
            table1_codes.add("1.1.3")
        if re.search(r"\b(?:điều\s*xe|dieu\s*xe|bố\s*trí\s*xe|bo\s*tri\s*xe|xe\s*chạy|xe\s*chay|xe\s*vào\s*kho|xe\s*vao\s*kho)\b", lower):
            table1_codes.add("1.1.4")
        if re.search(r"\b(?:thông\s*báo\s*xe|thong\s*bao\s*xe|thông\s*tin\s*xe|thong\s*tin\s*xe|danh\s*sách\s*xe|danh\s*sach\s*xe|kế\s*hoạch\s*xe|ke\s*hoach\s*xe)\b", lower):
            table1_codes.add("1.1.5")
        if any(ln.booking_no for ln in lines):
            table1_codes.add("1.1.6")
        table1_codes.add("1.1.7")

        # --- PHÂN TÍCH NHÓM 1.2: XE & TÀI XẾ ---
        distinct_trucks = {ln.truck_plate for ln in lines if ln.truck_plate}
        if distinct_trucks:
            table1_codes.add("1.2.1")
        if any(
            ln.raw_truck_plate and not re.search(r"[\-.]", ln.raw_truck_plate)
            for ln in lines
        ):
            table1_codes.add("1.2.2")
        if any(ln.trailer_plate for ln in lines):
            table1_codes.add("1.2.3")
        if any(ln.driver_name for ln in lines):
            table1_codes.add("1.2.4")
        if any(ln.driver_phone for ln in lines):
            table1_codes.add("1.2.5")
        if len(distinct_trucks) >= 2:
            table1_codes.add("1.2.6")
        if any(not ln.driver_name or not ln.driver_phone for ln in lines):
            table1_codes.add("1.2.7")
        if any(not ln.truck_plate for ln in lines):
            add_t("T11")
        if any(not ln.driver_name for ln in lines):
            add_t("T13")
        if any(not ln.driver_phone for ln in lines):
            add_t("T14")

        # --- PHÂN TÍCH NHÓM 1.3: CONTAINER & SỐ CHÌ ---
        distinct_conts = [ln.container_no for ln in lines if ln.container_no]
        if distinct_conts:
            table1_codes.add("1.3.1")
        if any("INVALID_CONTAINER_FORMAT" in ln.warnings for ln in lines):
            table1_codes.add("1.3.2")
            add_t("T18")
        if any(any(w.startswith("ISO6346_CHECK_DIGIT_MISMATCH") for w in ln.warnings) for ln in lines):
            table1_codes.add("1.3.2")
            add_t("T19")
        if any(ln.is_container_pending or not ln.container_no for ln in lines):
            if any(ln.is_container_pending or ln.order_type == "dong" for ln in lines if not ln.container_no):
                table1_codes.add("1.3.3")
                add_t("T10")
        if len(distinct_conts) >= 2:
            table1_codes.add("1.3.4")
        if any(ln.container_size for ln in lines):
            table1_codes.add("1.3.5")
        if any(ln.seal_no for ln in lines):
            table1_codes.add("1.3.6")
        if any(not ln.seal_no for ln in lines):
            table1_codes.add("1.3.7")
            add_t("T12")
        if any(ln.has_conflicting_mapping for ln in lines):
            table1_codes.add("1.3.9")
            add_t("T34")

        # Quan hệ Số lượng Xe - Số lượng Container (T05, T06, T07, T08, T35, T36)
        num_trucks = len(distinct_trucks)
        num_conts = len(distinct_conts)
        if num_trucks == 1 and num_conts == 1:
            add_t("T05")
        elif num_trucks == 1 and num_conts >= 2:
            add_t("T06")
        elif num_trucks >= 2 and num_conts == num_trucks:
            add_t("T07")
        elif num_trucks >= 2 and num_conts >= 2 and num_conts != num_trucks:
            add_t("T08")
        elif num_trucks >= 1 and num_conts == 0 and not order_types:
            add_t("T35")
        elif num_trucks == 0 and num_conts >= 1 and not order_types:
            add_t("T36")

        # --- PHÂN TÍCH NHÓM 1.4: KHO, KHÁCH HÀNG & ĐỊA ĐIỂM ---
        warehouses = {ln.warehouse_hint for ln in lines if ln.warehouse_hint}
        customers = {ln.customer_hint for ln in lines if ln.customer_hint}

        if warehouses:
            table1_codes.add("1.4.1")
            if any(len(w.split()) <= 2 or w.isupper() for w in warehouses):
                table1_codes.add("1.4.2")
            if re.search(r"\b(?:kcn|khu\s*công\s*nghiệp|khu\s*cong\s*nghiep|vsip)\b", lower):
                table1_codes.add("1.4.7")
            if re.search(r"\b(?:cảng|cang|terminal|tân\s*vũ|đình\s*vũ|lạch\s*huyện|cát\s*lái|icd)\b", lower):
                table1_codes.add("1.4.8")
            if re.search(r"\b(?:kho\s*đóng|điểm\s*đóng|nơi\s*đóng|diem\s*dong|noi\s*dong)\b", lower):
                table1_codes.add("1.4.9")
            if re.search(r"\b(?:kho\s*trả|điểm\s*trả|nơi\s*hạ|điểm\s*hạ|noi\s*ha|diem\s*ha)\b", lower):
                table1_codes.add("1.4.10")
            if re.search(r"\b(?:đường|duong|phường|phuong|huyện|huyen|tỉnh|tinh|địa\s*chỉ|dia\s*chi)\b", lower):
                table1_codes.add("1.4.6")
        else:
            table1_codes.add("1.4.11")
            add_t("T15")

        if customers:
            table1_codes.add("1.4.4")
            if any(len(c.split()) <= 2 or c.isupper() for c in customers):
                table1_codes.add("1.4.5")
        else:
            table1_codes.add("1.4.12")
            add_t("T16")

        if len(warehouses) >= 2:
            add_t("T24")
        if len(customers) >= 2:
            add_t("T25")
        if unmatched_warehouse:
            add_t("T21")
        if unmatched_customer:
            add_t("T22")
        if ambiguous_route_match or (warehouses and customers and warehouses.intersection(customers)):
            table1_codes.add("1.4.13")
            add_t("T23")

        # Kiểm tra thiếu từ 2 trường trở lên (T17)
        missing_types = {"T10", "T11", "T12", "T13", "T14", "T15", "T16"}.intersection(t_codes)
        if len(missing_types) >= 2:
            add_t("T17")

        # --- PHÂN TÍCH NHÓM 1.5: THỜI GIAN & TIẾN ĐỘ ---
        if re.search(r"\b\d{1,2}[\/\-]\d{1,2}(?:[\/\-]\d{2,4})?\b", text):
            table1_codes.add("1.5.1")
        if re.search(r"\b\d{1,2}(?:[:hH]\d{2}|\s*giờ|[hH]\b)", text):
            table1_codes.add("1.5.2")
        if re.search(r"\b(?:eta|giờ\s*đến|gio\s*den|dự\s*kiến\s*vào\s*kho|du\s*kien)\b", lower):
            table1_codes.add("1.5.3")
        if re.search(r"\b(?:sáng\s*nay|chiều\s*nay|tối\s*nay|sáng\s*mai|chiều\s*mai|ngày\s*mai|sang\s*nay|chieu\s*nay)\b", lower):
            table1_codes.add("1.5.4")
        if re.search(r"\b(?:chưa\s*có\s*giờ|báo\s*sau|chờ\s*điều\s*phối|chua\s*co\s*gio|bao\s*sau)\b", lower):
            table1_codes.add("1.5.5")
        if any(ln.is_time_vague for ln in lines):
            add_t("T39")

        # --- PHÂN TÍCH CẬP NHẬT / ĐỔI XE / ĐỔI GIỜ / TRÍCH DẪN / TRÙNG LẶP ---
        if re.search(r"\b(?:đổi\s*xe|doi\s*xe|đổi\s*tài|doi\s*tai|đổi\s*lái\s*xe|thay\s*xe)\b", lower):
            table1_codes.add("1.2.8")
            add_t("T28")
        if re.search(r"\b(?:đính\s*chính|dinh\s*chinh|sửa\s*cont|sua\s*cont|sửa\s*chì|sua\s*chi|cập\s*nhật\s*lại)\b", lower):
            table1_codes.add("1.3.8")
            add_t("T27")
        if re.search(r"\b(?:lùi\s*giờ|lui\s*gio|đổi\s*lịch|doi\s*lich|xe\s*đến\s*muộn|trễ\s*giờ|dời\s*giờ)\b", lower):
            table1_codes.add("1.5.6")
            add_t("T29")
        if intent == Intent.SUPPLEMENT or re.search(r"\b(?:bổ\s*sung|bo\s*sung)\b", lower):
            table1_codes.add("1.6.11")
            add_t("T26")
        if quote_msg_id or re.search(r"(?:>{1,3}|❝|tin\s*nhắn\s*chuyển\s*tiếp|trích\s*dẫn)", lower):
            table1_codes.add("1.6.10")
            add_t("T31")
        if is_duplicate_content:
            table1_codes.add("1.6.12")
            add_t("T30")

        # --- PHÂN TÍCH NHÓM 1.6: ĐỊNH DẠNG & BỐ CỤC ---
        has_labels = bool(
            re.search(
                r"(?:biển\s*số|bien\s*so|bks|tài\s*xế|tai\s*xe|lái\s*xe|sđt|sdt|số\s*cont|so\s*cont|số\s*chì|seal)\s*[:\-]",
                lower,
            )
        )
        has_numbered_list = bool(re.search(r"(?m)^(?:xe\s*\d+|\d+[\.)])\s*", lower))
        has_table_sep = bool("\t" in text or "|" in text)
        non_empty_lines = [ln for ln in text.splitlines() if ln.strip()]

        if has_labels:
            table1_codes.add("1.6.1")
        else:
            add_t("T37")

        if has_numbered_list or len(lines) >= 2:
            table1_codes.add("1.6.2")
        if has_table_sep:
            table1_codes.add("1.6.3")
        if len(non_empty_lines) == 1:
            table1_codes.add("1.6.4")
        else:
            table1_codes.add("1.6.5")

        if (has_labels and has_table_sep) or (has_numbered_list and has_table_sep):
            add_t("T38")

        if re.search(r"[*#👉🚛📦✅⚠️🔴🟢]|^\s*-\s+", text, flags=re.MULTILINE):
            table1_codes.add("1.6.6")

        alpha_chars = [ch for ch in text if ch.isalpha()]
        if alpha_chars and all(ch.isupper() for ch in alpha_chars):
            table1_codes.add("1.6.7")

        if alpha_chars and not cls._VIETNAMESE_DIACRITICS.search(text):
            table1_codes.add("1.6.8")

        if num_trucks == 0 and num_conts == 0:
            add_t("T32")

        if not t_codes:
            add_t("T40")

        # Quyết định `primary_type` (1 dạng chính duy nhất cho mỗi tin theo thứ tự ưu tiên nghiệp vụ)
        priority_order = [
            "T30", "T28", "T27", "T29", "T26", "T31",
            "T34", "T18", "T19", "T32",
            "T09", "T24", "T25", "T23", "T21", "T22",
            "T06", "T08", "T07",
            "T10", "T11", "T13", "T14",
            "T03", "T04", "T01", "T02",
            "T35", "T36", "T05", "T37", "T38", "T39", "T20", "T17", "T15", "T16", "T12", "T40",
        ]
        primary_type = next((code for code in priority_order if code in t_codes), t_codes[0])

        return {
            "primary_type": primary_type,
            "primary_type_name": TABLE2_DEFINITIONS[primary_type]["name"],
            "matched_types": t_codes,
            "secondary_types": [c for c in t_codes if c != primary_type],
            "table1_codes": sorted(table1_codes),
        }

    @classmethod
    def build_statistics_report(cls, messages_data: list[dict[str, Any]]) -> dict[str, Any]:
        """Tổng hợp báo cáo thống kê Bảng 1 (1.1 -> 1.6) và Bảng 2 (T01 -> T40) trên tập tin nhắn.

        Cách tính cột "Số tin có": Đếm số ID tin nhắn riêng biệt chứa hạng mục (không đếm trùng
        nếu 1 tin có nhiều xe).

        Args:
            messages_data (list[dict[str, Any]]): Danh sách từ điển chứa `id`, `raw_text`, `taxonomy`.

        Returns:
            dict[str, Any]: Báo cáo thống kê đầy đủ cho Bảng 1 và Bảng 2.
        """
        # 1. Thống kê Bảng 1 (theo từng nhóm 1.1 -> 1.6)
        table1_stats: dict[str, list[dict[str, Any]]] = {}
        for group_key, items in TABLE1_DEFINITIONS.items():
            group_rows: list[dict[str, Any]] = []
            for item_def in items:
                code = item_def["code"]
                matched_msgs = [
                    m for m in messages_data
                    if code in (m.get("taxonomy", {}).get("table1_codes") or [])
                ]
                example_text = matched_msgs[0]["raw_text"][:100] if matched_msgs else None
                group_rows.append(
                    {
                        "code": code,
                        "hang_muc": item_def["name"],
                        "so_tin_co": len(matched_msgs),
                        "message_ids": [m["id"] for m in matched_msgs],
                        "cac_kieu_viet": item_def["variants"],
                        "vi_du_thuc_te": example_text,
                    }
                )
            table1_stats[group_key] = group_rows

        # 2. Thống kê Bảng 2 (T01 -> T40: cả theo primary_type không trùng lặp và theo tổng số tin có đặc điểm đó)
        table2_stats: list[dict[str, Any]] = []
        for t_code, t_def in TABLE2_DEFINITIONS.items():
            primary_msgs = [
                m for m in messages_data
                if m.get("taxonomy", {}).get("primary_type") == t_code
            ]
            all_matched_msgs = [
                m for m in messages_data
                if t_code in (m.get("taxonomy", {}).get("matched_types") or [])
            ]
            table2_stats.append(
                {
                    "ma": t_code,
                    "dang_tin": t_def["name"],
                    "so_tin_primary": len(primary_msgs),
                    "so_tin_co_dac_diem": len(all_matched_msgs),
                    "primary_message_ids": [m["id"] for m in primary_msgs],
                    "all_message_ids": [m["id"] for m in all_matched_msgs],
                    "quy_tac_nhan_dien": t_def["rule"],
                }
            )

        return {
            "total_messages_analyzed": len(messages_data),
            "bang_1_hang_muc_du_lieu": table1_stats,
            "bang_2_phan_loai_dang_tin_T01_T40": table2_stats,
        }
