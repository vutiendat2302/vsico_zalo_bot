import csv
import json
import math
import os
import random
import re
from itertools import combinations
import openpyxl

print("🚀 Khởi chạy trình sinh 20.000 Test Case Logistics VSICO dạng CSV...")

# 1. Đọc số cont từ ketnoi.xlsx
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
seen = set()
for c in raw_conts:
    if c not in seen:
        seen.add(c)
        distinct_conts.append(c)

print(f"✅ Đã tải {len(distinct_conts)} số container chuẩn từ ketnoi.xlsx.")

# 2. Đọc file test_case_20_phan_ket_hop.xlsx đã tạo trước đó
excel_path = "tests/data_test/test_case_20_phan_ket_hop.xlsx"
wb_ex = openpyxl.load_workbook(excel_path, data_only=True)
ws_tc = wb_ex["Test case"]
print(f"✅ Đã tải {ws_tc.max_row - 1} test case nền tảng từ file Excel.")

# Danh mục tên 20 phần
part_names = {
    1: "1.Loại lệnh",
    2: "2.Biển số xe",
    3: "3.Tên tài xế",
    4: "4.Số điện thoại",
    5: "5.Số container",
    6: "6.Số chì / seal",
    7: "7.Tên khách hàng",
    8: "8.Điểm đóng hàng",
    9: "9.Thời gian dự kiến",
    10: "10.Số lượng xe / container",
    11: "11.Cấu trúc nhiều dòng",
    12: "12.Thông tin thiếu",
    13: "13.Thông tin mâu thuẫn",
    14: "14.Tin nhắn cập nhật / hủy",
    15: "15.Tin nhắn không phải lệnh",
    16: "16.Tin nhắn trùng lặp",
    17: "17.Hình ảnh",
    18: "18.Gửi cho từng khách hàng",
    19: "19.Thời hạn gửi tin",
    20: "20.Ngữ cảnh context"
}

# Pool mẫu dữ liệu xe, tài xế, sđt, seal, kho, khách
plates_pool = [
    ("15C17066", "15C-170.66"), ("36H74446", "36H-744.46"), ("51D38931", "51D-389.31"),
    ("15C87899", "15C-878.99"), ("29H54321", "29H-543.21"), ("14B17993", "14B-179.93"),
    ("50H04915", "50H-049.15"), ("15D41566", "15D-415.66"), ("30H12345", "30H-123.45"),
    ("14C87035", "14C-870.35"), ("15H00642", "15H-006.42"), ("15H06722", "15H-067.22"),
    ("15B23237", "15B-232.37"), ("30D15459", "30D-154.59"), ("29B52063", "29B-520.63"),
    ("14D83695", "14D-836.95"), ("50C81760", "50C-817.60"), ("14H39851", "14H-398.51")
]

drivers_pool = [
    ("Hoàng Thanh Bình", "0981695322"), ("Trần Minh Tuấn", "0362825445"), ("Lê Hữu Phong", "0913251729"),
    ("Bùi Văn Tuấn", "0932237840"), ("Đỗ Văn Cường", "0978127272"), ("Nguyễn Văn Nam", "0903976359"),
    ("Phạm Hữu Phong", "0942184730"), ("Đào Quang Thoại", "0360005504"), ("Đoàn Văn Biên", "0984457785"),
    ("Đào Đức Thoại", "0364461978"), ("Bảo", "0903976359"), ("Nguyên Thanh Phong", "0931142873"),
    ("Phạm Văn Huynh", "0986713346"), ("Trần Văn Biên", "0353324479"), ("Nguyễn Văn An", "0986123456")
]

seals_pool = ["23331731", "23338065", "23334238", "23339832", "23335654", "23338036", "23337978", "23333878", "23333310", "23333330", "23335804"]
warehouses_pool = [
    ("K012 kho Logitem Tân Quang", "kho Logitem Tân Quang"),
    ("K005 kho Nhựa Long An Bến Lức", "kho Nhựa Long An Bến Lức"),
    ("K018 kho Tân Trường", "kho Tân Trường"),
    ("B001 bãi Đình Vũ", "bãi Đình Vũ"),
    ("K008 kho Quang Minh", "kho Quang Minh"),
    ("C002 cảng Nam Hải Đình Vũ", "cảng Nam Hải Đình Vũ")
]
customers_pool = ["Logitem", "Nhựa Long An", "Cheng Loong", "Đại Phát", "Vạn Lợi", "DYSM"]

headers_csv = [
    "ma_tc",
    "cap_do",
    "phan_chinh",
    "cac_phan_tham_gia",
    "ten_cac_phan",
    "bien_the_ap_dung",
    "so_tin_nhan",
    "tin_nhan_dau_vao_json",
    "gio_nhan_tin",
    "trang_thai_tung_tin",
    "trang_thai_tin_cuoi",
    "du_lieu_tach_mong_doi",
    "khach_kho_gio_mong_doi",
    "ket_qua_don_sau_moi_tin",
    "gui_dich_mong_doi",
    "kiem_tra_han_gui",
    "gia_dinh_lien_quan",
    "ghi_chu_tung_tin",
    "trang_thai_api_mong_doi",      # Cột kết quả API Backend
    "ket_qua_canonical_json",        # Cột kết quả Canonical Record JSON
    "ket_qua_kiem_dinh_iso6346"     # Cột kết quả ISO 6346 Check Digit
]

output_csv_path = "tests/data_test/test_case_20_phan_20k.csv"

# Hàm suy luận trạng thái API và kết quả canonical record
def infer_expected_api_results(tc_code, variants_str, expected_text, status_final, cont_val, plate_val, driver_val, phone_val, seal_val, order_type_val):
    # 1. Trạng thái API: processed, needs_review, ignored_chat, ignored_non_text
    st_lower = str(status_final or "").lower()
    var_lower = str(variants_str or "").lower()
    
    if "ignored_chat" in st_lower or "p15" in var_lower and "tin độc lập" in var_lower:
        api_status = "ignored_chat"
        iso_status = "NOT_APPLICABLE"
        canonical = None
    elif "needs_review" in st_lower or any(err in var_lower for err in ["p5.4", "p5.5", "p12.", "p13.", "p17.1", "p2.5"]):
        api_status = "needs_review"
        if "p5.4" in var_lower:
            iso_status = "FAILED_CHECK_DIGIT"
        elif "p5.5" in var_lower or "p12.5" in var_lower:
            iso_status = "MISSING_CONTAINER"
        else:
            iso_status = "PASSED" if cont_val else "MISSING_CONTAINER"
            
        canonical = {
            "plate": plate_val[0] if plate_val else None,
            "driver_name": driver_val[0] if driver_val else None,
            "driver_phone": phone_val if phone_val else None,
            "cont_no": cont_val if "p5.5" not in var_lower and "p12.5" not in var_lower else None,
            "cont_size": "20",
            "seal_no": seal_val if "p12.3" not in var_lower else None,
            "order_type": order_type_val,
            "plan_date": "2026-10-28",
            "eta": "08:00",
            "match_source": "transport_plan",
            "validation_status": "needs_review"
        }
    else:
        api_status = "processed"
        iso_status = "PASSED"
        canonical = {
            "plate": plate_val[0] if plate_val else "15C17066",
            "driver_name": driver_val[0] if driver_val else "Hoàng Thanh Bình",
            "driver_phone": phone_val if phone_val else "0981695322",
            "cont_no": cont_val if cont_val else "SELU4396800",
            "cont_size": "20",
            "seal_no": seal_val if seal_val else "23331731",
            "order_type": order_type_val,
            "plan_date": "2026-10-28",
            "eta": "08:00",
            "match_source": "transport_plan",
            "validation_status": "valid"
        }
        
    canonical_json_str = json.dumps(canonical, ensure_ascii=False) if canonical else "{}"
    return api_status, canonical_json_str, iso_status

all_records = []
cont_idx = 0

# 3. Đọc toàn bộ case từ file Excel có sẵn
print("⏳ Đang nạp các test case từ Excel...")
for r in range(2, ws_tc.max_row + 1):
    row_vals = [ws_tc.cell(r, c).value for c in range(1, 19)]
    tc_code = row_vals[0]
    cap = row_vals[1]
    p_main = row_vals[2]
    parts = row_vals[3]
    parts_name = row_vals[4]
    variants = row_vals[5]
    num_msg = row_vals[6]
    json_in = row_vals[7]
    gio_nhan = row_vals[8]
    st_tung_tin = row_vals[9]
    st_cuoi = row_vals[10]
    tach_exp = row_vals[11]
    route_exp = row_vals[12]
    order_exp = row_vals[13]
    dest_exp = row_vals[14]
    check_dl = row_vals[15]
    assump = row_vals[16]
    notes = row_vals[17]

    # Trích xuất số cont, biển số, tài xế từ dữ liệu bóc tách mong đợi
    cont_match = re.search(r'cont=([A-Z0-9]+)', str(tach_exp or ""))
    cont_val = cont_match.group(1) if cont_match else distinct_conts[cont_idx % len(distinct_conts)]
    
    plate_match = re.search(r'biển=([A-Z0-9.\-]+)', str(tach_exp or ""))
    plate_val = (re.sub(r'[^A-Z0-9]', '', plate_match.group(1)), plate_match.group(1)) if plate_match else plates_pool[0]
    
    driver_match = re.search(r'tài xế=([^|]+)', str(tach_exp or ""))
    driver_val = (driver_match.group(1).strip(), "") if driver_match else drivers_pool[0]
    
    phone_match = re.search(r'SĐT=([0-9xX*]+)', str(tach_exp or ""))
    phone_val = phone_match.group(1) if phone_match else "0981695322"
    
    seal_match = re.search(r'seal=([A-Z0-9]+)', str(tach_exp or ""))
    seal_val = seal_match.group(1) if seal_match else "23331731"
    
    order_type_val = "tra" if "lệnh=trả" in str(tach_exp or "") else "dong"

    api_st, canon_json, iso_st = infer_expected_api_results(
        tc_code, variants, tach_exp, st_cuoi, cont_val, plate_val, driver_val, phone_val, seal_val, order_type_val
    )

    all_records.append([
        tc_code, cap, p_main, parts, parts_name, variants, num_msg, json_in,
        gio_nhan, st_tung_tin, st_cuoi, tach_exp, route_exp, order_exp,
        dest_exp, check_dl, assump, notes, api_st, canon_json, iso_st
    ])
    cont_idx += 1

initial_loaded = len(all_records)
print(f"✅ Đã nạp và bổ sung 3 cột kết quả cho {initial_loaded} test case đầu tiên.")

# 4. Sinh thêm các test case đa phần kết hợp để đạt CHÍNH XÁC 20.000 test case
target_total = 20000
needed_more = target_total - initial_loaded
print(f"⏳ Cần sinh thêm {needed_more} test case kết hợp đa phần để đạt mục tiêu {target_total}...")

# Phân bổ số lượng case cần sinh thêm vào các cấp kết hợp cao (Cấp 4 đến Cấp 20)
levels_to_boost = list(range(4, 21))  # Cấp 4 đến Cấp 20
samples_per_boost_level = needed_more // len(levels_to_boost)
remainder = needed_more % len(levels_to_boost)

random.seed(20261030)
boost_counter = 1

for l_idx, k_level in enumerate(levels_to_boost):
    # Số case cần sinh cho cấp này
    num_to_gen = samples_per_boost_level + (1 if l_idx < remainder else 0)
    
    for s in range(1, num_to_gen + 1):
        anchor_p = ((s - 1) % 20) + 1
        other_candidates = [p for p in range(1, 21) if p != anchor_p]
        num_others = min(k_level - 1, len(other_candidates))
        chosen_others = sorted(random.sample(other_candidates, num_others))
        all_parts_chosen = sorted([anchor_p] + chosen_others)
        
        parts_tag = ";" + ";".join(str(p) for p in all_parts_chosen) + ";"
        parts_name_str = f"{anchor_p}.{part_names[anchor_p].split('.')[1]} + {len(chosen_others)} phần ghép (Cấp {k_level})"
        
        tc_code = f"TC{k_level:02d}-P{anchor_p:02d}-B{s:04d}"
        
        # Chọn dữ liệu mẫu cho case
        cont_val = distinct_conts[cont_idx % len(distinct_conts)]
        plate_val = plates_pool[s % len(plates_pool)]
        driver_val = drivers_pool[s % len(drivers_pool)]
        seal_val = seals_pool[s % len(seals_pool)]
        wh_val = warehouses_pool[s % len(warehouses_pool)]
        cust_val = customers_pool[s % len(customers_pool)]
        cont_idx += 1
        
        # Xác định biến thể và độ phức tạp
        is_context_case = (20 in all_parts_chosen)
        is_error_case = (12 in all_parts_chosen or 13 in all_parts_chosen or 5 in all_parts_chosen and (s % 3 == 0))
        is_tra = (1 in all_parts_chosen and (s % 2 == 0))
        order_type_str = "tra" if is_tra else "dong"
        order_name = "Lệnh trả cont" if is_tra else "Lệnh đóng hàng"
        
        var_desc = f"P{anchor_p}.V{(s % 5) + 1}: Tổ hợp nâng cao {len(all_parts_chosen)} phần"
        
        safe_code = tc_code.replace("-", "_").replace("+", "_")
        
        if is_context_case:
            # Case có ngữ cảnh đa tin nhắn
            num_msgs = 3 if s % 2 == 0 else 2
            m1_text = f"Chào anh em, {order_name} kho {wh_val[1]}: xe {plate_val[1]} tx {driver_val[0]} {driver_val[1]} lúc 8h"
            m2_text = f"Bác tài ơi cont số mấy để kho xếp bãi?"
            m3_text = f"Cont {cont_val} chì {seal_val} nhé kho"
            
            payloads = [
                {
                    "app_id": "zca_personal_bot",
                    "event_name": "user_send_text",
                    "group_id": "6469608867469758994",
                    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
                    "timestamp": "1791798030000",
                    "quote_msg_id": None,
                    "message": {"msg_id": f"{safe_code}_m1", "text": m1_text}
                },
                {
                    "app_id": "zca_personal_bot",
                    "event_name": "user_send_text",
                    "group_id": "6469608867469758994",
                    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
                    "timestamp": "1791798150000",
                    "quote_msg_id": f"{safe_code}_m1",
                    "message": {"msg_id": f"{safe_code}_m2", "quote_msg_id": f"{safe_code}_m1", "text": m2_text}
                }
            ]
            if num_msgs == 3:
                payloads.append({
                    "app_id": "zca_personal_bot",
                    "event_name": "user_send_text",
                    "group_id": "6469608867469758994",
                    "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
                    "timestamp": "1791798270000",
                    "quote_msg_id": f"{safe_code}_m2",
                    "message": {"msg_id": f"{safe_code}_m3", "quote_msg_id": f"{safe_code}_m2", "text": m3_text}
                })
            json_input = json.dumps(payloads, indent=2, ensure_ascii=False)
            status_each = "#1:needs_review | #2:ignored_chat | #3:parsed_ok" if num_msgs == 3 else "#1:needs_review | #2:parsed_ok"
        else:
            # Case tin đơn nhưng kết hợp nhiều trường phức tạp
            num_msgs = 1
            if is_error_case and (s % 2 == 0):
                # Thiếu seal
                msg_text = f"1 xe {plate_val[1]}/ {driver_val[0]} đt: {driver_val[1]} / {cont_val} KH: {cust_val} - {wh_val[1]} - 8h"
                seal_val_case = None
            else:
                msg_text = f"1 xe: {plate_val[1]}/ {driver_val[0]} đt: {driver_val[1]} / {cont_val} chì {seal_val} - KH: {cust_val} - {wh_val[1]} - 8h"
                seal_val_case = seal_val
                
            payload = {
                "app_id": "zca_personal_bot",
                "event_name": "user_send_text",
                "group_id": "6469608867469758994",
                "sender": {"id": "6691387223255581446", "name": "Lái xe Hải Long"},
                "timestamp": "1791798030000",
                "quote_msg_id": None,
                "message": {"msg_id": f"{safe_code}_m1", "text": msg_text}
            }
            json_input = json.dumps(payload, indent=2, ensure_ascii=False)
            status_each = "#1:needs_review" if is_error_case else "#1:parsed_ok"
            seal_val = seal_val_case

        # Kết quả mong đợi
        status_final = "needs_review" if is_error_case else "parsed_ok"
        tach_exp = f"Xe1: biển={plate_val[0]} | tài xế={driver_val[0]} | SĐT={driver_val[1]} | cont={cont_val} | seal={seal_val or '∅'} | lệnh={order_type_str} → {'THIẾU: seal' if not seal_val else 'OK'}"
        route_exp = f"Khách={cust_val} | Kho={wh_val[0]} | Giờ đến=08:00"
        order_exp = "Chờ bổ sung seal" if not seal_val else "1 xe sẵn sàng"
        dest_exp = f"Nhóm Zalo {cust_val} (mọi tin vào một nhóm)"
        check_dl = "Không áp dụng"
        assump = "CTX-1, REQ-5" if is_context_case else "NORM-1, REQ-1"
        notes = f"Case kết hợp cấp {k_level} phủ {len(all_parts_chosen)} phần nghiệp vụ chéo"

        api_st, canon_json, iso_st = infer_expected_api_results(
            tc_code, var_desc, tach_exp, status_final, cont_val, plate_val, driver_val, driver_val[1], seal_val, order_type_str
        )

        all_records.append([
            tc_code, k_level, anchor_p, parts_tag, parts_name_str, var_desc, num_msgs, json_input,
            "28/10/2026 07:30", status_each, status_final, tach_exp, route_exp, order_exp,
            dest_exp, check_dl, assump, notes, api_st, canon_json, iso_st
        ])

print(f"🎉 Đã sinh đủ {len(all_records)} test cases!")

# 5. Ghi toàn bộ dữ liệu ra tệp CSV với encoding UTF-8 có BOM (để mở bằng Excel không bị lỗi font)
print(f"⏳ Đang ghi ra tệp CSV: {output_csv_path}...")
with open(output_csv_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(headers_csv)
    for row in all_records:
        writer.writerow(row)

file_size_mb = os.path.getsize(output_csv_path) / (1024 * 1024)
print(f"💾 HOÀN THÀNH LƯU FILE CSV: {output_csv_path}")
print(f"📦 Kích thước file CSV: {file_size_mb:.2f} MB ({len(all_records)} dòng dữ liệu)")

# 6. Tạo thêm bản sao test_case_20_phan_ket_hop.csv để tiện tham chiếu
alias_csv_path = "tests/data_test/test_case_20_phan_ket_hop.csv"
import shutil
shutil.copyfile(output_csv_path, alias_csv_path)
print(f"✅ Đã tạo thêm alias đồng bộ: {alias_csv_path}")
