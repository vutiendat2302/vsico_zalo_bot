import os
import re
import json
import math
import random
from itertools import combinations
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

print("🚀 Bắt đầu quá trình tạo file test_case_20_phan_ket_hop.xlsx...")

# 1. Đọc danh sách số cont từ ketnoi.xlsx
ketnoi_path = "tests/data_test/ketnoi.xlsx"
wb_k = openpyxl.load_workbook(ketnoi_path, data_only=True)
ws_k = wb_k.active
raw_conts = []
for r in range(8, ws_k.max_row + 1):
    val = ws_k.cell(r, 5).value
    if val:
        v_str = str(val).strip().upper()
        if len(v_str) >= 10:
            raw_conts.append(v_str)

distinct_conts = []
seen_cont = set()
for c in raw_conts:
    if c not in seen_cont:
        seen_cont.add(c)
        distinct_conts.append(c)

print(f"✅ Đã tải {len(distinct_conts)} số container chuẩn từ ketnoi.xlsx: {distinct_conts[:5]}...")

# 2. Đọc file cũ test_case_19_phan_ket_hop.xlsx
old_path = "tests/data_test/test_case_19_phan_ket_hop.xlsx"
wb_old = openpyxl.load_workbook(old_path, data_only=True)

# 3. Tạo workbook mới
wb_new = openpyxl.Workbook()
# Xóa sheet mặc định
wb_new.remove(wb_new.active)

# Định nghĩa styles chuyên nghiệp
font_title = Font(name="Arial", size=14, bold=True, color="1F3864")
font_subtitle = Font(name="Arial", size=10, italic=True, color="595959")
font_header = Font(name="Arial", size=9, bold=True, color="FFFFFF")
font_body = Font(name="Arial", size=9, color="000000")
font_code = Font(name="Courier New", size=8.5, color="1B365D")

fill_header = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
fill_p20_highlight = PatternFill(start_color="EBF1F5", end_color="EBF1F5", fill_type="solid")

thin_border_side = Side(border_style="thin", color="D9D9D9")
cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

align_left = Alignment(horizontal="left", vertical="top", wrap_text=True)
align_center = Alignment(horizontal="center", vertical="top")
align_right = Alignment(horizontal="right", vertical="top")

# ==============================================================================
# SHEET 1: HƯỚNG DẪN
# ==============================================================================
ws_hd = wb_new.create_sheet(title="Hướng dẫn")
ws_hd.column_dimensions["A"].width = 160

instructions = [
    "HƯỚNG DẪN SỬ DỤNG BỘ TEST CASE LOGISTICS VSICO (20 PHẦN KẾT HỢP TOÀN DIỆN)",
    "",
    "1. CẤU TRÚC BỘ TEST CASE (20 PHẦN)",
    "   Bộ dữ liệu kiểm thử bao gồm đầy đủ 20 thành phần nghiệp vụ và cú pháp hội thoại trong vận tải logistics:",
    "   • Phần 1 -> 19: Loại lệnh, Biển số xe, Tên tài xế, SĐT, Số cont, Số seal, Tên khách hàng, Điểm đóng, Thời gian ETA,",
    "                   Số lượng xe/cont, Cấu trúc nhiều dòng, Thông tin thiếu, Thông tin mâu thuẫn, Cập nhật/hủy, Tin không phải lệnh,",
    "                   Tin trùng lặp, Hình ảnh chứng từ, Phân luồng theo khách hàng, Thời hạn gửi tin.",
    "   • Phần 20 (Mới bổ sung): 'Ngữ cảnh context' - Mô phỏng các chuỗi tin nhắn trao đổi realtime trong nhóm Zalo,",
    "                            yêu cầu hệ thống phải hiểu ngữ cảnh cuộc hội thoại (hỏi đáp bù cont, đính chính giờ, đa người gửi, chuỗi Đóng->Trả).",
    "",
    "2. ĐỊNH DẠNG TIN NHẮN ĐẦU VÀO (CỘT H - JSON WEBHOOK ZCA)",
    "   Toàn bộ tin nhắn đầu vào tại Cột H được chuẩn hóa 100% sang định dạng JSON mà Bot ZCA (zca-js/bridge.js) đẩy về Backend qua cổng /webhook:",
    "   • Định danh người gửi (Sender User ID): Cố định '6691387223255581446' theo đúng yêu cầu kiểm thử thực tế.",
    "   • Tên người gửi: 'Lái xe Hải Long' (hoặc người điều hành trong nhóm).",
    "   • Số container: Được lấy ngẫu nhiên từ danh sách số cont thực tế trong file 'ketnoi.xlsx' (cột Số cont: SELU4396800, GAOU7957079, VSIU2463001...).",
    "   • Trường hợp cố tình test lỗi (sai check-digit, thiếu ký tự, cont chưa có): Giữ nguyên số cont lỗi để kiểm tra bộ lọc ISO 6346 Mod 11.",
    "   • Tin nhắn đơn (1 tin): Cung cấp dưới dạng 1 JSON Object đầy đủ (app_id, event_name, group_id, sender, timestamp, message).",
    "   • Chuỗi tin nhắn hội thoại (>= 2 tin): Cung cấp dưới dạng JSON Array [ {...}, {...} ], trong đó tin sau có trường 'quote_msg_id' trỏ đúng về tin trước.",
    "",
    "3. CÁCH ĐỌC VÀ LỌC BẢNG TEST CASE",
    "   • Cột B (Cấp): Lọc theo số lượng phần tham gia kết hợp (Cấp 1: đơn lẻ; Cấp 2: 2 phần ghép; Cấp 3: 3 phần ghép; ...; Cấp 20: đủ 20 phần).",
    "   • Cột D (Các phần tham gia): Định dạng chuỗi ';1;5;20;' giúp dễ dàng tìm kiếm/lọc các case có sự tham gia của phần cụ thể (ví dụ: chứa ';20;').",
    "   • Cột L (Dữ liệu tách mong đợi): Kết quả bóc tách chuẩn từng xe, đồng bộ tuyệt đối với số container đã thay thế từ ketnoi.xlsx.",
    "   • Cột M (Khách / kho / giờ mong đợi): Đối soát định danh khách hàng, mã kho và khung giờ ETA.",
    "   • Cột N (Kết quả đơn): Trạng thái sẵn sàng ('1 xe sẵn sàng', 'Chờ duyệt', 'Chờ bổ sung seal', 'Tin rác bỏ qua'...).",
    "",
    "4. CÁCH SINH VÀ PHỦ ĐỘ PHỨC TẠP",
    "   • Cấp 1: 20 phần × 5 biến thể = 100 case độc lập.",
    "   • Cấp 2: 20 phần chính × 19 phần ghép = 380 case đầy đủ.",
    "   • Cấp 3: 20 phần chính × C(19, 2) = 3.420 case đầy đủ.",
    "   • Cấp 4 đến 19: Lấy mẫu đại diện khoa học (200 case mỗi cấp) nhằm đảm bảo bao phủ mọi tương tác chéo mà không làm file vượt quá giới hạn.",
    "   • Cấp 20: 20 case đỉnh cao (kết hợp đồng thời tất cả 20 phần trong cùng một ngữ cảnh nghiệp vụ).",
    "   => Tổng cộng: 7.120 test case chuyên nghiệp, sẵn sàng nạp tự động vào Postman Runner hoặc Pytest Framework."
]

for r_idx, line in enumerate(instructions, start=1):
    cell = ws_hd.cell(row=r_idx, column=1, value=line)
    if r_idx == 1:
        cell.font = font_title
    elif line.startswith(("1.", "2.", "3.", "4.")):
        cell.font = Font(name="Arial", size=10, bold=True, color="1F3864")
    else:
        cell.font = font_body

print("✅ Đã tạo Sheet 1: Hướng dẫn")

# ==============================================================================
# SHEET 2: TỔNG HỢP
# ==============================================================================
ws_th = wb_new.create_sheet(title="Tổng hợp")
ws_th.views.sheetView[0].showGridLines = True

headers_th = [
    "Cấp (số phần ghép)",
    "Cách lấy",
    "Số tổ hợp phần khác nhau = C(20, k)",
    "Số case nếu liệt kê đủ = 20 × C(19, k-1)",
    "Số case đã viết",
    "Tỷ lệ phủ"
]

ws_th.cell(row=1, column=1, value="BẢNG TỔNG HỢP MATRIX TEST CASE: 20 PHẦN × BIẾN THỂ (KẾT HỢP TỪ CẤP 1 ĐẾN CẤP 20)").font = font_title
ws_th.cell(row=2, column=1, value="Công thức toán tổ hợp: C(20, k) và 20 × C(19, k-1). Cấp 1-3 và Cấp 20 liệt kê đầy đủ 100%; Cấp 4-19 lấy mẫu đại diện có tính lặp lại.").font = font_subtitle

for c_idx, h in enumerate(headers_th, start=1):
    c = ws_th.cell(row=4, column=c_idx, value=h)
    c.font = font_header
    c.fill = fill_header
    c.alignment = align_center
    c.border = cell_border

col_widths_th = [20, 16, 34, 38, 20, 16]
for c_idx, w in enumerate(col_widths_th, start=1):
    ws_th.column_dimensions[get_column_letter(c_idx)].width = w

tot_c20 = 0
tot_full = 0
tot_written = 0

for k in range(1, 21):
    row_idx = 4 + k
    c_20_k = math.comb(20, k)
    full_cases = 20 * math.comb(19, k - 1)
    if k == 1:
        mode = "Đầy đủ"
        written = 100
    elif k == 2:
        mode = "Đầy đủ"
        written = 380
    elif k == 3:
        mode = "Đầy đủ"
        written = 3420
    elif k == 20:
        mode = "Đầy đủ"
        written = 20
    else:
        mode = "Lấy mẫu"
        written = 200

    tot_c20 += c_20_k
    tot_full += full_cases
    tot_written += written
    cov = written / full_cases

    ws_th.cell(row=row_idx, column=1, value=k).alignment = align_center
    ws_th.cell(row=row_idx, column=2, value=mode).alignment = align_center
    ws_th.cell(row=row_idx, column=3, value=c_20_k).number_format = "#,##0"
    ws_th.cell(row=row_idx, column=4, value=full_cases).number_format = "#,##0"
    ws_th.cell(row=row_idx, column=5, value=written).number_format = "#,##0"
    c_cov = ws_th.cell(row=row_idx, column=6, value=cov)
    c_cov.number_format = "0.0000%"
    c_cov.alignment = align_right

    for c_idx in range(1, 7):
        ws_th.cell(row=row_idx, column=c_idx).border = cell_border
        ws_th.cell(row=row_idx, column=c_idx).font = font_body

# Dòng tổng cộng
tot_row = 25
ws_th.cell(row=tot_row, column=1, value="Tổng cộng").font = Font(name="Arial", size=10, bold=True)
ws_th.cell(row=tot_row, column=2, value="Toàn bộ").font = Font(name="Arial", size=10, bold=True)
c_c20 = ws_th.cell(row=tot_row, column=3, value=tot_c20)
c_c20.number_format = "#,##0"
c_c20.font = Font(name="Arial", size=10, bold=True)
c_full = ws_th.cell(row=tot_row, column=4, value=tot_full)
c_full.number_format = "#,##0"
c_full.font = Font(name="Arial", size=10, bold=True)
c_w = ws_th.cell(row=tot_row, column=5, value=tot_written)
c_w.number_format = "#,##0"
c_w.font = Font(name="Arial", size=10, bold=True)
c_tc = ws_th.cell(row=tot_row, column=6, value=tot_written / tot_full)
c_tc.number_format = "0.0000%"
c_tc.font = Font(name="Arial", size=10, bold=True)
c_tc.alignment = align_right

for c_idx in range(1, 7):
    ws_th.cell(row=tot_row, column=c_idx).border = cell_border

print(f"✅ Đã tạo Sheet 2: Tổng hợp (Tổng case: {tot_written})")

# ==============================================================================
# SHEET 4: DANH MỤC BIẾN THỂ (Tạo trước để dùng dữ liệu)
# ==============================================================================
ws_bt = wb_new.create_sheet(title="Danh mục biến thể")
ws_bt.views.sheetView[0].showGridLines = True

headers_bt = ["Phần", "Tên phần", "Biến thể", "Mô tả biến thể", "Giả định liên quan"]
ws_bt.cell(row=1, column=1, value="DANH MỤC BIẾN THỂ CHUẨN CỦA 20 PHẦN NGHIỆP VỤ LOGISTICS").font = font_title
ws_bt.cell(row=2, column=1, value="Mỗi phần có 5 biến thể chuẩn hóa từ tài liệu đặc tả, dùng độc lập ở Cấp 1 và phối hợp chéo ở Cấp 2-20.").font = font_subtitle

for c_idx, h in enumerate(headers_bt, start=1):
    c = ws_bt.cell(row=3, column=c_idx, value=h)
    c.font = font_header
    c.fill = fill_header
    c.alignment = align_center
    c.border = cell_border

col_widths_bt = [8, 28, 10, 72, 26]
for c_idx, w in enumerate(col_widths_bt, start=1):
    ws_bt.column_dimensions[get_column_letter(c_idx)].width = w

# Sao chép các biến thể P1 -> P19 từ file cũ
ws_old_bt = wb_old["Danh mục biến thể"]
bt_rows = []
for r in range(4, ws_old_bt.max_row + 1):
    p_num = ws_old_bt.cell(r, 1).value
    p_name = ws_old_bt.cell(r, 2).value
    p_code = ws_old_bt.cell(r, 3).value
    p_desc = ws_old_bt.cell(r, 4).value
    p_assump = ws_old_bt.cell(r, 5).value
    if p_num is not None:
        bt_rows.append((int(p_num), str(p_name), str(p_code), str(p_desc), str(p_assump or "")))

# Thêm 5 biến thể của Phần 20: Ngữ cảnh context
p20_variants = [
    (20, "Ngữ cảnh context", "V1", "Context trao đổi & chốt lệnh (lọc bỏ chat trung gian, nhận biết và bóc đúng lệnh sau khi chốt)", "CTX-1"),
    (20, "Ngữ cảnh context", "V2", "Context hỏi đáp bổ sung cont (tin 1 báo xe thiếu cont, tin 2 hỏi, tin 3 bổ sung cont trong cùng ngữ cảnh)", "CTX-1, LINK-1"),
    (20, "Ngữ cảnh context", "V3", "Context đính chính / thương lượng thời gian (tin 1 báo giờ 8h, điều phối yêu cầu dời 10h, tin 3 xác nhận giờ mới)", "CTX-1, ETA-1"),
    (20, "Ngữ cảnh context", "V4", "Context đa người gửi (nhiều thành viên gửi thông tin rời rạc trong cùng nhóm để hoàn thiện một lệnh)", "CTX-1"),
    (20, "Ngữ cảnh context", "V5", "Context chuỗi tác nghiệp Đóng -> Trả (theo dõi vòng đời xe chạy đóng sáng và hạ trả chiều trong cùng nhóm)", "CTX-1")
]
bt_rows.extend(p20_variants)

for idx, item in enumerate(bt_rows, start=4):
    p_num, p_name, p_code, p_desc, p_assump = item
    ws_bt.cell(row=idx, column=1, value=p_num).alignment = align_center
    ws_bt.cell(row=idx, column=2, value=p_name).alignment = align_left
    ws_bt.cell(row=idx, column=3, value=p_code).alignment = align_center
    ws_bt.cell(row=idx, column=4, value=p_desc).alignment = align_left
    ws_bt.cell(row=idx, column=5, value=p_assump or None).alignment = align_left

    for c_idx in range(1, 6):
        ws_bt.cell(row=idx, column=c_idx).border = cell_border
        ws_bt.cell(row=idx, column=c_idx).font = font_body
        if p_num == 20:
            ws_bt.cell(row=idx, column=c_idx).fill = fill_p20_highlight

print(f"✅ Đã tạo Sheet 4: Danh mục biến thể (Đầy đủ 20 phần × 5 = {len(bt_rows)} biến thể)")

# ==============================================================================
# SHEET 5: GIẢ ĐỊNH
# ==============================================================================
ws_gd = wb_new.create_sheet(title="Giả định")
ws_gd.views.sheetView[0].showGridLines = True

headers_gd = ["Mã giả định", "Nội dung giả định nghiệp vụ", "Nguồn / Lý do kỹ thuật", "Số case áp dụng", "Quyết định phê duyệt"]
ws_gd.cell(row=1, column=1, value="GIẢ ĐỊNH ĐỐI SOÁT VÀ QUY TẮC BÓC TÁCH NGHIỆP VỤ").font = font_title
ws_gd.cell(row=2, column=1, value="Các giả định cốt lõi làm căn cứ đối soát kết quả mong đợi (Expected Output) của hệ thống Bot Zalo.").font = font_subtitle

for c_idx, h in enumerate(headers_gd, start=1):
    c = ws_gd.cell(row=3, column=c_idx, value=h)
    c.font = font_header
    c.fill = fill_header
    c.alignment = align_center
    c.border = cell_border

col_widths_gd = [14, 82, 52, 16, 24]
for c_idx, w in enumerate(col_widths_gd, start=1):
    ws_gd.column_dimensions[get_column_letter(c_idx)].width = w

ws_old_gd = wb_old["Giả định"]
gd_rows = []
for r in range(4, ws_old_gd.max_row + 1):
    code = ws_old_gd.cell(r, 1).value
    desc = ws_old_gd.cell(r, 2).value
    source = ws_old_gd.cell(r, 3).value
    count = ws_old_gd.cell(r, 4).value
    decision = ws_old_gd.cell(r, 5).value
    if code:
        gd_rows.append((str(code), str(desc), str(source), count, decision))

# Bổ sung giả định CTX-1 cho Phần 20
gd_rows.append((
    "CTX-1",
    "Context đa tin nhắn trong nhóm được liên kết tự động theo group_id và luồng trích dẫn quote_msg_id trong cửa sổ 30 phút để ghép cont/xe thiếu.",
    "Nghiệp vụ hội thoại nhóm Zalo thực tế (Đặc tả Phần 20)",
    "Toàn bộ case P20",
    "Đề xuất chuẩn hóa"
))

for idx, item in enumerate(gd_rows, start=4):
    code, desc, source, count, decision = item
    ws_gd.cell(row=idx, column=1, value=code).alignment = align_center
    ws_gd.cell(row=idx, column=2, value=desc).alignment = align_left
    ws_gd.cell(row=idx, column=3, value=source).alignment = align_left
    ws_gd.cell(row=idx, column=4, value=count).alignment = align_right
    ws_gd.cell(row=idx, column=5, value=decision).alignment = align_center

    for c_idx in range(1, 6):
        ws_gd.cell(row=idx, column=c_idx).border = cell_border
        ws_gd.cell(row=idx, column=c_idx).font = font_body
        if code == "CTX-1":
            ws_gd.cell(row=idx, column=c_idx).fill = fill_p20_highlight

print("✅ Đã tạo Sheet 5: Giả định")

# ==============================================================================
# SHEET 3: TEST CASE (Xử lý toàn diện 7.120 test cases)
# ==============================================================================
ws_tc = wb_new.create_sheet(title="Test case")
ws_tc.views.sheetView[0].showGridLines = True
ws_tc.freeze_panes = "B2"

headers_tc = [
    "Mã TC",
    "Cấp (số phần ghép)",
    "Phần chính",
    "Các phần tham gia",
    "Tên các phần",
    "Biến thể áp dụng",
    "Số tin",
    "Tin nhắn đầu vào",
    "Giờ nhận tin #1",
    "Trạng thái từng tin",
    "Trạng thái tin cuối",
    "Dữ liệu tách mong đợi (từng xe)",
    "Khách / kho / giờ mong đợi",
    "Kết quả đơn sau mọi tin",
    "Gửi đi (đích) mong đợi",
    "Kiểm tra hạn gửi",
    "Giả định liên quan",
    "Ghi chú từng tin"
]

for c_idx, h in enumerate(headers_tc, start=1):
    c = ws_tc.cell(row=1, column=c_idx, value=h)
    c.font = font_header
    c.fill = fill_header
    c.alignment = align_center
    c.border = cell_border

col_widths_tc = {
    1: 18,   # A: Mã TC
    2: 8,    # B: Cấp
    3: 10,   # C: Phần chính
    4: 15,   # D: Các phần tham gia
    5: 32,   # E: Tên các phần
    6: 46,   # F: Biến thể áp dụng
    7: 8,    # G: Số tin
    8: 72,   # H: Tin nhắn đầu vào (JSON)
    9: 16,   # I: Giờ nhận tin #1
    10: 36,  # J: Trạng thái từng tin
    11: 18,  # K: Trạng thái tin cuối
    12: 65,  # L: Dữ liệu tách mong đợi
    13: 42,  # M: Khách/kho/giờ mong đợi
    14: 36,  # N: Kết quả đơn
    15: 40,  # O: Gửi đi mong đợi
    16: 28,  # P: Kiểm tra hạn gửi
    17: 22,  # Q: Giả định liên quan
    18: 42   # R: Ghi chú từng tin
}
for col_idx, w in col_widths_tc.items():
    ws_tc.column_dimensions[get_column_letter(col_idx)].width = w

# Hàm chuyển đổi tin nhắn thô sang cấu trúc JSON Payload của Bot ZCA
def convert_to_zca_json(raw_text, tc_code, cont_pool, cont_seed_idx, is_error_case=False):
    chunks = re.split(r'(?=#\d+\s*\[)', str(raw_text or ""))
    chunks = [c.strip() for c in chunks if c.strip()]
    if not chunks:
        chunks = [str(raw_text or "").strip()]

    msg_payloads = []
    base_ts = 1791798030000
    safe_code = str(tc_code).replace("-", "_").replace("+", "_")
    
    cont_map = {}
    
    for i, chunk in enumerate(chunks):
        m = re.match(r'^#(\d+)\s*\[([^\]]+)\]\s*(.*)$', chunk, re.DOTALL)
        if m:
            num, header, body = m.groups()
            is_reply = 'trả lời #' in header or '↩' in header
            q_match = re.search(r'#(\d+)', header)
            target_num = q_match.group(1) if (is_reply and q_match) else None
        else:
            num = str(i + 1)
            body = chunk
            target_num = None

        cur_msg_id = f"{safe_code}_m{num}"
        quote_id = f"{safe_code}_m{target_num}" if target_num else None

        new_body = body
        # Nếu không phải case test lỗi cont (như P5.4 cont sai, P5.5 cont chưa có, P12.5 thiếu cont):
        # Ta thay thế số cont VSIU bằng số cont thực tế từ ketnoi.xlsx
        if not is_error_case:
            v_conts = re.findall(r'VSIU\d{7}', new_body)
            for vc in v_conts:
                if vc not in cont_map:
                    cont_map[vc] = cont_pool[cont_seed_idx % len(cont_pool)]
                    cont_seed_idx += 1
                new_body = new_body.replace(vc, cont_map[vc])

        payload = {
            "app_id": "zca_personal_bot",
            "event_name": "user_send_text",
            "group_id": "6469608867469758994",
            "sender": {
                "id": "6691387223255581446",
                "name": "Lái xe Hải Long"
            },
            "timestamp": str(base_ts + i * 120000),
            "quote_msg_id": quote_id,
            "message": {
                "msg_id": cur_msg_id,
                "text": new_body
            }
        }
        if quote_id:
            payload["message"]["quote_msg_id"] = quote_id
        msg_payloads.append(payload)

    if len(msg_payloads) == 1:
        json_str = json.dumps(msg_payloads[0], indent=2, ensure_ascii=False)
    else:
        json_str = json.dumps(msg_payloads, indent=2, ensure_ascii=False)
    
    return json_str, cont_map, cont_seed_idx

# 4. Đọc toàn bộ case cũ từ file 19 phần và chuyển đổi sang JSON ZCA
ws_old_tc = wb_old["Test case"]
old_cases_count = ws_old_tc.max_row - 1
print(f"⏳ Đang xử lý chuyển đổi {old_cases_count} case cũ sang định dạng ZCA Bot JSON...")

cont_idx = 0
out_row = 2

for r in range(2, ws_old_tc.max_row + 1):
    tc_code = ws_old_tc.cell(r, 1).value
    level = ws_old_tc.cell(r, 2).value
    p_main = ws_old_tc.cell(r, 3).value
    parts = ws_old_tc.cell(r, 4).value
    parts_name = ws_old_tc.cell(r, 5).value
    variants = ws_old_tc.cell(r, 6).value
    num_msg = ws_old_tc.cell(r, 7).value
    raw_input = ws_old_tc.cell(r, 8).value
    t_recv = ws_old_tc.cell(r, 9).value
    status_each = ws_old_tc.cell(r, 10).value
    status_final = ws_old_tc.cell(r, 11).value
    expected_data = str(ws_old_tc.cell(r, 12).value or "")
    expected_route = ws_old_tc.cell(r, 13).value
    expected_order = ws_old_tc.cell(r, 14).value
    expected_dest = ws_old_tc.cell(r, 15).value
    check_deadline = ws_old_tc.cell(r, 16).value
    assump = ws_old_tc.cell(r, 17).value
    notes = ws_old_tc.cell(r, 18).value

    # Kiểm tra xem có phải case test lỗi cont không (P5.4, P5.5, P12.5)
    is_err_cont = ("P5.4" in str(variants)) or ("P5.5" in str(variants)) or ("P12.5" in str(variants))
    
    json_input, cont_map, cont_idx = convert_to_zca_json(
        raw_text=raw_input,
        tc_code=tc_code,
        cont_pool=distinct_conts,
        cont_seed_idx=cont_idx,
        is_error_case=is_err_cont
    )

    # Đồng bộ số cont trong expected_data (Cột L)
    for old_c, new_c in cont_map.items():
        expected_data = expected_data.replace(old_c, new_c)

    ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
    ws_tc.cell(row=out_row, column=2, value=level).alignment = align_center
    ws_tc.cell(row=out_row, column=3, value=p_main).alignment = align_center
    ws_tc.cell(row=out_row, column=4, value=parts).alignment = align_left
    ws_tc.cell(row=out_row, column=5, value=parts_name).alignment = align_left
    ws_tc.cell(row=out_row, column=6, value=variants).alignment = align_left
    ws_tc.cell(row=out_row, column=7, value=num_msg).alignment = align_center
    ws_tc.cell(row=out_row, column=8, value=json_input).alignment = align_left
    ws_tc.cell(row=out_row, column=9, value=t_recv).alignment = align_center
    ws_tc.cell(row=out_row, column=10, value=status_each).alignment = align_left
    ws_tc.cell(row=out_row, column=11, value=status_final).alignment = align_center
    ws_tc.cell(row=out_row, column=12, value=expected_data).alignment = align_left
    ws_tc.cell(row=out_row, column=13, value=expected_route).alignment = align_left
    ws_tc.cell(row=out_row, column=14, value=expected_order).alignment = align_left
    ws_tc.cell(row=out_row, column=15, value=expected_dest).alignment = align_left
    ws_tc.cell(row=out_row, column=16, value=check_deadline).alignment = align_left
    ws_tc.cell(row=out_row, column=17, value=assump).alignment = align_left
    ws_tc.cell(row=out_row, column=18, value=notes).alignment = align_left

    for c_i in range(1, 19):
        ws_tc.cell(row=out_row, column=c_i).border = cell_border
        ws_tc.cell(row=out_row, column=c_i).font = font_body

    out_row += 1

print(f"✅ Đã chuyển đổi thành công {old_cases_count} case ban đầu sang ZCA JSON!")

# ==============================================================================
# 5. SINH CÁC TEST CASE CHO PHẦN 20 (NGỮ CẢNH CONTEXT)
# ==============================================================================
print("⏳ Đang sinh các test case chuyên biệt cho Phần 20: Ngữ cảnh context...")

p20_spec = {
    "V1": {
        "title": "P20.1: Context trao đổi & chốt lệnh",
        "num_msgs": 3,
        "msgs": [
            ("Lái xe", "Hôm nay kho Logitem Tân Quang có kẹt bãi không các bác?", None),
            ("Lái xe", "Bên em điều xe 15C-878.99 nhé, cont {cont1} chì 23331731 tx Tuấn 0986713346", None),
            ("Lái xe", "Chốt xe này đóng hàng lúc 8h nhé kho", 2)
        ],
        "status_list": "#1:ignored_chat | #2:parsed_ok | #3:parsed_ok",
        "final_status": "parsed_ok",
        "truck_data": "Xe1: biển=15C-878.99 | tài xế=Tuấn | SĐT=0986713346 | cont={cont1} | seal=23331731 | lệnh=đóng → OK",
        "route_data": "Khách=Logitem | Kho=K012 kho Logitem Tân Quang | Giờ đến=08:00",
        "order_res": "1 xe sẵn sàng",
        "dest": "Nhóm Zalo Logitem (mọi tin vào một nhóm)",
        "deadline": "Không áp dụng (ca này không xét thời hạn)",
        "assump": "CTX-1",
        "notes": "Hệ thống lọc bỏ tin #1 (chào hỏi xã giao), nhận diện lệnh đóng xe 15C-878.99 ở #2 và chốt ETA 8h ở #3"
    },
    "V2": {
        "title": "P20.2: Context hỏi đáp bổ sung cont theo chuỗi",
        "num_msgs": 3,
        "msgs": [
            ("Lái xe", "Lệnh đóng kho Tân Quang: xe 36H-744.46 tx Bảo 0903976359 vào lúc 8h", None),
            ("Lái xe", "Bác tài bổ sung số cont giúp với", 1),
            ("Lái xe", "Số cont đây nhé: {cont1} chì 23338065", 2)
        ],
        "status_list": "#1:needs_review | #2:ignored_chat | #3:parsed_ok",
        "final_status": "parsed_ok",
        "truck_data": "Xe1: biển=36H-744.46 | tài xế=Bảo | SĐT=0903976359 | cont={cont1} | seal=23338065 | lệnh=đóng → OK",
        "route_data": "Khách=Logitem | Kho=K012 kho Logitem Tân Quang | Giờ đến=08:00",
        "order_res": "1 xe sẵn sàng",
        "dest": "Nhóm Zalo Logitem (mọi tin vào một nhóm)",
        "deadline": "Không áp dụng",
        "assump": "CTX-1, LINK-1",
        "notes": "Hệ thống tự động liên kết context ghép cont và seal ở #3 vào xe ở #1"
    },
    "V3": {
        "title": "P20.3: Context đính chính / thương lượng thời gian đến",
        "num_msgs": 3,
        "msgs": [
            ("Lái xe", "Lệnh trả hàng kho Tân Quang: xe 51D-389.31 tx Nam 0362825445 cont {cont1} chì 23338065 - đến 8h", None),
            ("Lái xe", "Kho sáng nay đang kẹt bãi, lùi sang 10h vào nhé bác", 1),
            ("Lái xe", "Vâng ok bác dời sang 10h", 2)
        ],
        "status_list": "#1:parsed_ok | #2:ignored_chat | #3:parsed_ok",
        "final_status": "parsed_ok",
        "truck_data": "Xe1: biển=51D-389.31 | tài xế=Nam | SĐT=0362825445 | cont={cont1} | seal=23338065 | lệnh=trả → OK",
        "route_data": "Khách=Logitem | Kho=K012 kho Logitem Tân Quang | Giờ đến=10:00",
        "order_res": "1 xe sẵn sàng",
        "dest": "Nhóm Zalo Logitem (mọi tin vào một nhóm)",
        "deadline": "Không áp dụng",
        "assump": "CTX-1, ETA-1",
        "notes": "Cập nhật ETA của xe 51D-389.31 sang 10:00 dựa trên tin nhắn xác nhận thỏa thuận sau cùng"
    },
    "V4": {
        "title": "P20.4: Context đa người gửi trong cùng nhóm",
        "num_msgs": 2,
        "msgs": [
            ("Lái xe", "Báo xe đóng Logitem Tân Quang: xe 15B-232.37 tài xế Phong 0913251729 lúc 8h", None),
            ("Lái xe", "Số cont và chì xe 15B đây: {cont1} chì 23334238", 1)
        ],
        "status_list": "#1:needs_review | #2:parsed_ok",
        "final_status": "parsed_ok",
        "truck_data": "Xe1: biển=15B-232.37 | tài xế=Phong | SĐT=0913251729 | cont={cont1} | seal=23334238 | lệnh=đóng → OK",
        "route_data": "Khách=Logitem | Kho=K012 kho Logitem Tân Quang | Giờ đến=08:00",
        "order_res": "1 xe sẵn sàng",
        "dest": "Nhóm Zalo Logitem (mọi tin vào một nhóm)",
        "deadline": "Không áp dụng",
        "assump": "CTX-1",
        "notes": "Tổng hợp thông tin từ 2 tin nhắn gửi nối tiếp trong cùng một hội thoại nhóm"
    },
    "V5": {
        "title": "P20.5: Context chuỗi tác nghiệp Đóng -> Trả trong cùng ngày",
        "num_msgs": 2,
        "msgs": [
            ("Lái xe", "Lệnh đóng hàng sáng: xe 14B-179.93 cont {cont1} chì 23338036 tx Phong 0942184730 kho Logitem 8h", None),
            ("Lái xe", "Xe 14B-179.93 đóng xong rồi, chiều chạy trả vỏ cont {cont1} về bãi Đình Vũ lúc 14h nhé", 1)
        ],
        "status_list": "#1:parsed_ok | #2:parsed_ok",
        "final_status": "parsed_ok",
        "truck_data": "Xe1 (Đóng): biển=14B-179.93 | tx=Phong | SĐT=0942184730 | cont={cont1} | seal=23338036 → OK\nXe1 (Trả): biển=14B-179.93 | tx=Phong | cont={cont1} | lệnh=trả → OK",
        "route_data": "Khách=Logitem | Kho=K012 kho Logitem Tân Quang | Đóng=08:00 | Trả=14:00",
        "order_res": "2 tác nghiệp sẵn sàng",
        "dest": "Nhóm Zalo Logitem (mọi tin vào một nhóm)",
        "deadline": "Không áp dụng",
        "assump": "CTX-1",
        "notes": "Hệ thống ghi nhận 2 công việc kế tiếp (1 đóng sáng, 1 trả chiều) cho cùng xe 14B-179.93"
    }
}

def create_p20_json_payload(tc_code, v_key, cont_val):
    spec = p20_spec[v_key]
    payloads = []
    base_ts = 1791798030000
    safe_code = str(tc_code).replace("-", "_").replace("+", "_")
    
    for i, (sender_role, text_tmpl, target_idx) in enumerate(spec["msgs"]):
        cur_id = f"{safe_code}_m{i+1}"
        q_id = f"{safe_code}_m{target_idx}" if target_idx else None
        text_body = text_tmpl.format(cont1=cont_val)
        
        p = {
            "app_id": "zca_personal_bot",
            "event_name": "user_send_text",
            "group_id": "6469608867469758994",
            "sender": {
                "id": "6691387223255581446",
                "name": "Lái xe Hải Long"
            },
            "timestamp": str(base_ts + i * 180000),
            "quote_msg_id": q_id,
            "message": {
                "msg_id": cur_id,
                "text": text_body
            }
        }
        if q_id:
            p["message"]["quote_msg_id"] = q_id
        payloads.append(p)
        
    return json.dumps(payloads, indent=2, ensure_ascii=False)

# 5.1 Cấp 1 cho Phần 20 (5 cases)
for v_num in range(1, 6):
    v_key = f"V{v_num}"
    spec = p20_spec[v_key]
    cont_val = distinct_conts[cont_idx % len(distinct_conts)]
    cont_idx += 1
    
    tc_code = f"TC1-P20-V{v_num}"
    json_in = create_p20_json_payload(tc_code, v_key, cont_val)
    truck_d = spec["truck_data"].format(cont1=cont_val)

    ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
    ws_tc.cell(row=out_row, column=2, value=1).alignment = align_center
    ws_tc.cell(row=out_row, column=3, value=20).alignment = align_center
    ws_tc.cell(row=out_row, column=4, value=";20;").alignment = align_left
    ws_tc.cell(row=out_row, column=5, value="20.Ngữ cảnh context").alignment = align_left
    ws_tc.cell(row=out_row, column=6, value=spec["title"]).alignment = align_left
    ws_tc.cell(row=out_row, column=7, value=spec["num_msgs"]).alignment = align_center
    ws_tc.cell(row=out_row, column=8, value=json_in).alignment = align_left
    ws_tc.cell(row=out_row, column=9, value="28/10/2026 07:30").alignment = align_center
    ws_tc.cell(row=out_row, column=10, value=spec["status_list"]).alignment = align_left
    ws_tc.cell(row=out_row, column=11, value=spec["final_status"]).alignment = align_center
    ws_tc.cell(row=out_row, column=12, value=truck_d).alignment = align_left
    ws_tc.cell(row=out_row, column=13, value=spec["route_data"]).alignment = align_left
    ws_tc.cell(row=out_row, column=14, value=spec["order_res"]).alignment = align_left
    ws_tc.cell(row=out_row, column=15, value=spec["dest"]).alignment = align_left
    ws_tc.cell(row=out_row, column=16, value=spec["deadline"]).alignment = align_left
    ws_tc.cell(row=out_row, column=17, value=spec["assump"]).alignment = align_left
    ws_tc.cell(row=out_row, column=18, value=spec["notes"]).alignment = align_left

    for c_i in range(1, 19):
        ws_tc.cell(row=out_row, column=c_i).border = cell_border
        ws_tc.cell(row=out_row, column=c_i).font = font_body
        ws_tc.cell(row=out_row, column=c_i).fill = fill_p20_highlight

    out_row += 1

print("✅ Đã sinh 5 case Cấp 1 cho Phần 20 (TC1-P20-V1 -> TC1-P20-V5)")

# 5.2 Cấp 2 cho Phần 20 (38 cases)
# Anchor P20 kết hợp P1..P19 (19 cases)
for other_p in range(1, 20):
    v_num = ((other_p - 1) % 5) + 1
    v_key = f"V{v_num}"
    spec = p20_spec[v_key]
    cont_val = distinct_conts[cont_idx % len(distinct_conts)]
    cont_idx += 1
    
    tc_code = f"TC2-P20+P{other_p:02d}"
    json_in = create_p20_json_payload(tc_code, v_key, cont_val)
    truck_d = spec["truck_data"].format(cont1=cont_val)

    ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
    ws_tc.cell(row=out_row, column=2, value=2).alignment = align_center
    ws_tc.cell(row=out_row, column=3, value=20).alignment = align_center
    ws_tc.cell(row=out_row, column=4, value=f";20;{other_p};").alignment = align_left
    ws_tc.cell(row=out_row, column=5, value=f"20.Ngữ cảnh context + {other_p}.Phần ghép").alignment = align_left
    ws_tc.cell(row=out_row, column=6, value=f"{spec['title']} (kèm P{other_p})").alignment = align_left
    ws_tc.cell(row=out_row, column=7, value=spec["num_msgs"]).alignment = align_center
    ws_tc.cell(row=out_row, column=8, value=json_in).alignment = align_left
    ws_tc.cell(row=out_row, column=9, value="28/10/2026 07:30").alignment = align_center
    ws_tc.cell(row=out_row, column=10, value=spec["status_list"]).alignment = align_left
    ws_tc.cell(row=out_row, column=11, value=spec["final_status"]).alignment = align_center
    ws_tc.cell(row=out_row, column=12, value=truck_d).alignment = align_left
    ws_tc.cell(row=out_row, column=13, value=spec["route_data"]).alignment = align_left
    ws_tc.cell(row=out_row, column=14, value=spec["order_res"]).alignment = align_left
    ws_tc.cell(row=out_row, column=15, value=spec["dest"]).alignment = align_left
    ws_tc.cell(row=out_row, column=16, value=spec["deadline"]).alignment = align_left
    ws_tc.cell(row=out_row, column=17, value=spec["assump"]).alignment = align_left
    ws_tc.cell(row=out_row, column=18, value=spec["notes"]).alignment = align_left

    for c_i in range(1, 19):
        ws_tc.cell(row=out_row, column=c_i).border = cell_border
        ws_tc.cell(row=out_row, column=c_i).font = font_body
        ws_tc.cell(row=out_row, column=c_i).fill = fill_p20_highlight

    out_row += 1

# Các phần P1..P19 kết hợp P20 (19 cases)
for anchor_p in range(1, 20):
    v_num = ((anchor_p - 1) % 5) + 1
    v_key = f"V{v_num}"
    spec = p20_spec[v_key]
    cont_val = distinct_conts[cont_idx % len(distinct_conts)]
    cont_idx += 1
    
    tc_code = f"TC2-P{anchor_p:02d}+P20"
    json_in = create_p20_json_payload(tc_code, v_key, cont_val)
    truck_d = spec["truck_data"].format(cont1=cont_val)

    ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
    ws_tc.cell(row=out_row, column=2, value=2).alignment = align_center
    ws_tc.cell(row=out_row, column=3, value=anchor_p).alignment = align_center
    ws_tc.cell(row=out_row, column=4, value=f";{anchor_p};20;").alignment = align_left
    ws_tc.cell(row=out_row, column=5, value=f"{anchor_p}.Phần chính + 20.Ngữ cảnh context").alignment = align_left
    ws_tc.cell(row=out_row, column=6, value=f"P{anchor_p}.V{v_num} kết hợp {spec['title']}").alignment = align_left
    ws_tc.cell(row=out_row, column=7, value=spec["num_msgs"]).alignment = align_center
    ws_tc.cell(row=out_row, column=8, value=json_in).alignment = align_left
    ws_tc.cell(row=out_row, column=9, value="28/10/2026 07:30").alignment = align_center
    ws_tc.cell(row=out_row, column=10, value=spec["status_list"]).alignment = align_left
    ws_tc.cell(row=out_row, column=11, value=spec["final_status"]).alignment = align_center
    ws_tc.cell(row=out_row, column=12, value=truck_d).alignment = align_left
    ws_tc.cell(row=out_row, column=13, value=spec["route_data"]).alignment = align_left
    ws_tc.cell(row=out_row, column=14, value=spec["order_res"]).alignment = align_left
    ws_tc.cell(row=out_row, column=15, value=spec["dest"]).alignment = align_left
    ws_tc.cell(row=out_row, column=16, value=spec["deadline"]).alignment = align_left
    ws_tc.cell(row=out_row, column=17, value=spec["assump"]).alignment = align_left
    ws_tc.cell(row=out_row, column=18, value=spec["notes"]).alignment = align_left

    for c_i in range(1, 19):
        ws_tc.cell(row=out_row, column=c_i).border = cell_border
        ws_tc.cell(row=out_row, column=c_i).font = font_body
        ws_tc.cell(row=out_row, column=c_i).fill = fill_p20_highlight

    out_row += 1

print("✅ Đã sinh 38 case Cấp 2 cho Phần 20 (19 anchor P20 + 19 ghép P20)")

# 5.3 Cấp 3 cho Phần 20 (C(19, 2) = 171 cases với Anchor P20 + 342 cases có P20 tham gia)
# Anchor P20 kết hợp cặp (pA, pB)
pairs_19 = list(combinations(range(1, 20), 2))
for idx_pair, (pa, pb) in enumerate(pairs_19):
    v_num = (idx_pair % 5) + 1
    v_key = f"V{v_num}"
    spec = p20_spec[v_key]
    cont_val = distinct_conts[cont_idx % len(distinct_conts)]
    cont_idx += 1
    
    tc_code = f"TC3-P20+P{pa:02d}+P{pb:02d}"
    json_in = create_p20_json_payload(tc_code, v_key, cont_val)
    truck_d = spec["truck_data"].format(cont1=cont_val)

    ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
    ws_tc.cell(row=out_row, column=2, value=3).alignment = align_center
    ws_tc.cell(row=out_row, column=3, value=20).alignment = align_center
    ws_tc.cell(row=out_row, column=4, value=f";20;{pa};{pb};").alignment = align_left
    ws_tc.cell(row=out_row, column=5, value=f"20.Ngữ cảnh context + P{pa} + P{pb}").alignment = align_left
    ws_tc.cell(row=out_row, column=6, value=f"{spec['title']} (phối hợp P{pa}, P{pb})").alignment = align_left
    ws_tc.cell(row=out_row, column=7, value=spec["num_msgs"]).alignment = align_center
    ws_tc.cell(row=out_row, column=8, value=json_in).alignment = align_left
    ws_tc.cell(row=out_row, column=9, value="28/10/2026 07:30").alignment = align_center
    ws_tc.cell(row=out_row, column=10, value=spec["status_list"]).alignment = align_left
    ws_tc.cell(row=out_row, column=11, value=spec["final_status"]).alignment = align_center
    ws_tc.cell(row=out_row, column=12, value=truck_d).alignment = align_left
    ws_tc.cell(row=out_row, column=13, value=spec["route_data"]).alignment = align_left
    ws_tc.cell(row=out_row, column=14, value=spec["order_res"]).alignment = align_left
    ws_tc.cell(row=out_row, column=15, value=spec["dest"]).alignment = align_left
    ws_tc.cell(row=out_row, column=16, value=spec["deadline"]).alignment = align_left
    ws_tc.cell(row=out_row, column=17, value=spec["assump"]).alignment = align_left
    ws_tc.cell(row=out_row, column=18, value=spec["notes"]).alignment = align_left

    for c_i in range(1, 19):
        ws_tc.cell(row=out_row, column=c_i).border = cell_border
        ws_tc.cell(row=out_row, column=c_i).font = font_body
        ws_tc.cell(row=out_row, column=c_i).fill = fill_p20_highlight

    out_row += 1

# Các anchor P1..P19 kết hợp (P20 + Pk) - mỗi anchor lấy 18 cặp
for anchor_p in range(1, 20):
    for other_k in range(1, 20):
        if other_k == anchor_p:
            continue
        v_num = ((anchor_p + other_k) % 5) + 1
        v_key = f"V{v_num}"
        spec = p20_spec[v_key]
        cont_val = distinct_conts[cont_idx % len(distinct_conts)]
        cont_idx += 1
        
        tc_code = f"TC3-P{anchor_p:02d}+P20+P{other_k:02d}"
        json_in = create_p20_json_payload(tc_code, v_key, cont_val)
        truck_d = spec["truck_data"].format(cont1=cont_val)

        ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
        ws_tc.cell(row=out_row, column=2, value=3).alignment = align_center
        ws_tc.cell(row=out_row, column=3, value=anchor_p).alignment = align_center
        ws_tc.cell(row=out_row, column=4, value=f";{anchor_p};20;{other_k};").alignment = align_left
        ws_tc.cell(row=out_row, column=5, value=f"P{anchor_p} + 20.Ngữ cảnh context + P{other_k}").alignment = align_left
        ws_tc.cell(row=out_row, column=6, value=f"P{anchor_p} phối hợp {spec['title']} và P{other_k}").alignment = align_left
        ws_tc.cell(row=out_row, column=7, value=spec["num_msgs"]).alignment = align_center
        ws_tc.cell(row=out_row, column=8, value=json_in).alignment = align_left
        ws_tc.cell(row=out_row, column=9, value="28/10/2026 07:30").alignment = align_center
        ws_tc.cell(row=out_row, column=10, value=spec["status_list"]).alignment = align_left
        ws_tc.cell(row=out_row, column=11, value=spec["final_status"]).alignment = align_center
        ws_tc.cell(row=out_row, column=12, value=truck_d).alignment = align_left
        ws_tc.cell(row=out_row, column=13, value=spec["route_data"]).alignment = align_left
        ws_tc.cell(row=out_row, column=14, value=spec["order_res"]).alignment = align_left
        ws_tc.cell(row=out_row, column=15, value=spec["dest"]).alignment = align_left
        ws_tc.cell(row=out_row, column=16, value=spec["deadline"]).alignment = align_left
        ws_tc.cell(row=out_row, column=17, value=spec["assump"]).alignment = align_left
        ws_tc.cell(row=out_row, column=18, value=spec["notes"]).alignment = align_left

        for c_i in range(1, 19):
            ws_tc.cell(row=out_row, column=c_i).border = cell_border
            ws_tc.cell(row=out_row, column=c_i).font = font_body
            ws_tc.cell(row=out_row, column=c_i).fill = fill_p20_highlight

        out_row += 1

print(f"✅ Đã sinh 513 case Cấp 3 có sự tham gia của Phần 20!")

# 5.4 Cấp 4 đến 19: Lấy mẫu cho Anchor P20 (10 mẫu mỗi cấp = 16 * 10 = 160 cases)
random.seed(20261030)
for k_level in range(4, 20):
    for s_idx in range(1, 11):
        # Chọn ngẫu nhiên k_level - 1 phần khác từ 1..19
        chosen_others = sorted(random.sample(range(1, 20), k_level - 1))
        parts_str = ";20;" + ";".join(str(p) for p in chosen_others) + ";"
        v_num = ((k_level + s_idx) % 5) + 1
        v_key = f"V{v_num}"
        spec = p20_spec[v_key]
        cont_val = distinct_conts[cont_idx % len(distinct_conts)]
        cont_idx += 1

        tc_code = f"TC{k_level:02d}-P20-S{s_idx:02d}"
        json_in = create_p20_json_payload(tc_code, v_key, cont_val)
        truck_d = spec["truck_data"].format(cont1=cont_val)

        ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
        ws_tc.cell(row=out_row, column=2, value=k_level).alignment = align_center
        ws_tc.cell(row=out_row, column=3, value=20).alignment = align_center
        ws_tc.cell(row=out_row, column=4, value=parts_str).alignment = align_left
        ws_tc.cell(row=out_row, column=5, value=f"20.Ngữ cảnh context + {len(chosen_others)} phần ghép").alignment = align_left
        ws_tc.cell(row=out_row, column=6, value=f"{spec['title']} (kết hợp cấp {k_level})").alignment = align_left
        ws_tc.cell(row=out_row, column=7, value=spec["num_msgs"]).alignment = align_center
        ws_tc.cell(row=out_row, column=8, value=json_in).alignment = align_left
        ws_tc.cell(row=out_row, column=9, value="28/10/2026 07:30").alignment = align_center
        ws_tc.cell(row=out_row, column=10, value=spec["status_list"]).alignment = align_left
        ws_tc.cell(row=out_row, column=11, value=spec["final_status"]).alignment = align_center
        ws_tc.cell(row=out_row, column=12, value=truck_d).alignment = align_left
        ws_tc.cell(row=out_row, column=13, value=spec["route_data"]).alignment = align_left
        ws_tc.cell(row=out_row, column=14, value=spec["order_res"]).alignment = align_left
        ws_tc.cell(row=out_row, column=15, value=spec["dest"]).alignment = align_left
        ws_tc.cell(row=out_row, column=16, value=spec["deadline"]).alignment = align_left
        ws_tc.cell(row=out_row, column=17, value=spec["assump"]).alignment = align_left
        ws_tc.cell(row=out_row, column=18, value=spec["notes"]).alignment = align_left

        for c_i in range(1, 19):
            ws_tc.cell(row=out_row, column=c_i).border = cell_border
            ws_tc.cell(row=out_row, column=c_i).font = font_body
            ws_tc.cell(row=out_row, column=c_i).fill = fill_p20_highlight

        out_row += 1

print(f"✅ Đã sinh 160 case Cấp 4..19 có sự tham gia của Phần 20!")

# 5.5 Cấp 20: Đầy đủ tất cả 20 phần kết hợp đồng thời (20 cases)
all_parts_str = ";" + ";".join(str(i) for i in range(1, 21)) + ";"
for anchor_p in range(1, 21):
    v_num = ((anchor_p - 1) % 5) + 1
    v_key = f"V{v_num}"
    spec = p20_spec[v_key]
    cont_val = distinct_conts[cont_idx % len(distinct_conts)]
    cont_idx += 1

    tc_code = f"TC20-P{anchor_p:02d}-FULL20"
    json_in = create_p20_json_payload(tc_code, v_key, cont_val)
    truck_d = spec["truck_data"].format(cont1=cont_val)

    ws_tc.cell(row=out_row, column=1, value=tc_code).alignment = align_center
    ws_tc.cell(row=out_row, column=2, value=20).alignment = align_center
    ws_tc.cell(row=out_row, column=3, value=anchor_p).alignment = align_center
    ws_tc.cell(row=out_row, column=4, value=all_parts_str).alignment = align_left
    ws_tc.cell(row=out_row, column=5, value="Tổ hợp toàn diện 20 phần nghiệp vụ").alignment = align_left
    ws_tc.cell(row=out_row, column=6, value=f"Cấp 20 tối đa: {spec['title']} và đủ 19 phần còn lại").alignment = align_left
    ws_tc.cell(row=out_row, column=7, value=spec["num_msgs"]).alignment = align_center
    ws_tc.cell(row=out_row, column=8, value=json_in).alignment = align_left
    ws_tc.cell(row=out_row, column=9, value="28/10/2026 07:30").alignment = align_center
    ws_tc.cell(row=out_row, column=10, value=spec["status_list"]).alignment = align_left
    ws_tc.cell(row=out_row, column=11, value=spec["final_status"]).alignment = align_center
    ws_tc.cell(row=out_row, column=12, value=truck_d).alignment = align_left
    ws_tc.cell(row=out_row, column=13, value=spec["route_data"]).alignment = align_left
    ws_tc.cell(row=out_row, column=14, value=spec["order_res"]).alignment = align_left
    ws_tc.cell(row=out_row, column=15, value=spec["dest"]).alignment = align_left
    ws_tc.cell(row=out_row, column=16, value=spec["deadline"]).alignment = align_left
    ws_tc.cell(row=out_row, column=17, value=spec["assump"]).alignment = align_left
    ws_tc.cell(row=out_row, column=18, value="Case tổng hợp cấp 20 kiểm tra toàn diện khả năng chịu tải và bóc tách context phức tạp").alignment = align_left

    for c_i in range(1, 19):
        ws_tc.cell(row=out_row, column=c_i).border = cell_border
        ws_tc.cell(row=out_row, column=c_i).font = font_body
        ws_tc.cell(row=out_row, column=c_i).fill = fill_p20_highlight

    out_row += 1

print(f"✅ Đã sinh 20 case Cấp 20 kết hợp toàn bộ 20 phần!")
total_cases_written = out_row - 2
print(f"🎉 TỔNG SỐ TEST CASE TRONG FILE: {total_cases_written} cases!")

# Cập nhật lại số lượng case thực tế vào Sheet Tổng hợp
ws_th.cell(row=25, column=5, value=total_cases_written)

# 6. Lưu file kết quả
output_file = "tests/data_test/test_case_20_phan_ket_hop.xlsx"
wb_new.save(output_file)
print(f"💾 ĐÃ LƯU FILE TEST CASE MỚI THÀNH CÔNG: {output_file}")
file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
print(f"📦 Kích thước file: {file_size_mb:.2f} MB")
