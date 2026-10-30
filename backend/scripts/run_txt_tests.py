#!/usr/bin/env python3
"""Script Chạy Kiểm Thử Tự Động Toàn Bộ Các Tệp Tin Nhắn Input Text (VSICO Test Runner).

Tính năng:
1. Đọc tất cả các tệp `*_input.txt` trong thư mục fixtures (hoặc 1 tệp chỉ định).
2. Tự động bóc tách khối nội dung `INPUT:` để gửi vào bộ xử lý Webhook / FIFO Extractor.
3. Xuất kết quả bóc tách chi tiết ra từng tệp `_output.txt` trong thư mục `output/`.
4. Tự động so sánh với tệp `_expected.txt` (nếu có) để đối soát kết quả.
5. Hỗ trợ mở rộng: Khi người dùng thêm bất kỳ tệp mới nào (VD: `TC-21_input.txt`),
   script tự động nhận diện và xuất ra `TC-21_output.txt`.

Cách dùng:
  # Chạy kiểm thử tất cả các tệp:
  python scripts/run_txt_tests.py --all

  # Chạy kiểm thử 1 tệp duy nhất:
  python scripts/run_txt_tests.py --file TC-01_input.txt
  python scripts/run_txt_tests.py --file tests/vsico_test_txt_files/tests/fixtures/messages/TC-04_input.txt

  # Chỉ định thư mục output khác:
  python scripts/run_txt_tests.py --all --output-dir my_custom_output/
"""

import argparse
from datetime import datetime, timezone
import glob
import json
import os
import sys
import uuid

# Đảm bảo import được module backend
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(CURRENT_DIR) if os.path.basename(CURRENT_DIR) == "scripts" else CURRENT_DIR
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

DEFAULT_FIXTURE_DIR = os.path.join(
    BACKEND_ROOT, "tests", "vsico_test_txt_files", "tests", "fixtures", "messages"
)
DEFAULT_OUTPUT_DIR = os.path.join(
    BACKEND_ROOT, "tests", "vsico_test_txt_files", "output"
)


def extract_input_text_from_file(file_path: str) -> tuple[str, str, str]:
    """Đọc tệp input và trích xuất `test_id`, `format_label`, và `raw_text`.

    Args:
        file_path (str): Đường dẫn tệp txt.

    Returns:
        tuple[str, str, str]: (test_id, format_label, raw_text).
    """
    with open(file_path, "r", encoding="utf-8") as fp:
        lines = fp.readlines()

    test_id = os.path.basename(file_path).replace("_input.txt", "").replace(".txt", "")
    format_label = "TU_DO"
    raw_text_lines = []
    is_capturing = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("TEST_ID:"):
            test_id = stripped.replace("TEST_ID:", "").strip()
        elif stripped.startswith("FORMAT:"):
            format_label = stripped.replace("FORMAT:", "").strip()
        elif stripped.startswith("INPUT:"):
            is_capturing = True
            continue

        if is_capturing:
            raw_text_lines.append(line)

    if is_capturing and raw_text_lines:
        raw_text = "".join(raw_text_lines).strip()
    else:
        # Nếu tệp không có cấu trúc nhãn, lấy toàn bộ nội dung tệp
        raw_text = "".join(lines).strip()

    return test_id, format_label, raw_text


def load_expected_text_if_exists(input_file_path: str) -> str:
    """Tìm và đọc tệp `_expected.txt` tương ứng nếu có."""
    expected_path = input_file_path.replace("_input.txt", "_expected.txt")
    if os.path.exists(expected_path):
        with open(expected_path, "r", encoding="utf-8") as fp:
            return fp.read().strip()
    return "Không có tệp expected tương ứng."


def process_message_through_pipeline(
    raw_text: str,
    test_id: str,
    group_id: str = "2001000000000000001",
    sender_id: str = "1001000000000000001",
) -> dict:
    """Đẩy tin nhắn vào pipeline FastAPI TestClient để chạy bóc tách FIFO đầy đủ."""
    from fastapi.testclient import TestClient
    from src.main import app

    client = TestClient(app)
    unique_msg_id = f"txt_run_{test_id}_{uuid.uuid4().hex[:8]}"

    payload = {
        "app_id": "txt_test_runner",
        "event_name": "user_send_text",
        "group_id": group_id,
        "sender": {
            "id": sender_id,
            "name": f"Tester {test_id}",
        },
        "timestamp": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        "message": {
            "msg_id": unique_msg_id,
            "text": raw_text,
        },
    }

    response = client.post("/webhook", json=payload)
    if response.status_code == 200:
        return response.json()
    return {
        "ok": False,
        "status_code": response.status_code,
        "error": response.text,
    }


def format_output_report(
    test_id: str,
    format_label: str,
    input_file_path: str,
    raw_text: str,
    expected_text: str,
    result_data: dict,
) -> str:
    """Tạo nội dung báo cáo chi tiết cho tệp `_output.txt`."""
    data = result_data.get("data", {})
    action = data.get("action", result_data.get("status", "UNKNOWN"))
    processing_status = data.get("processing_status", "UNKNOWN")
    trucks = data.get("trucks", [])
    containers = data.get("containers", [])
    reply_to_carrier = data.get("reply_to_carrier")

    out_lines = [
        "=" * 76,
        f"TEST_ID: {test_id}",
        f"FORMAT_DECLARED: {format_label}",
        f"SOURCE_INPUT_FILE: {os.path.basename(input_file_path)}",
        f"TESTED_AT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 76,
        "",
        "--- [1. NỘI DUNG ĐẦU VÀO (INPUT TEXT)] ---",
        raw_text,
        "",
        "--- [2. KẾT QUẢ XỬ LÝ (PROCESSING RESULT)] ---",
        f"HÀNH ĐỘNG (ACTION)       : {action}",
        f"TRẠNG THÁI (STATUS)      : {processing_status}",
        f"SỐ XE BÓC TÁCH ĐƯỢC      : {len(trucks)}",
        f"SỐ CONTAINER BÓC TÁCH    : {len(containers)}",
    ]

    if reply_to_carrier:
        out_lines.append(f"PHẢN HỒI NHÀ XE          : {reply_to_carrier}")

    out_lines.append("")
    out_lines.append("--- [3. CHI TIẾT CÁC XE ĐẦU KÉO (TRUCKS)] ---")
    if not trucks:
        out_lines.append("(Không có xe nào được bóc tách)")
    else:
        for idx, t in enumerate(trucks, 1):
            out_lines.extend([
                f"  Xe #{idx}:",
                f"    - Biển số xe   : {t.get('truck_plate') or '(trống)'}",
                f"    - Biển rơ-moóc : {t.get('trailer_plate') or '(trống)'}",
                f"    - Tên tài xế   : {t.get('driver_name') or '(trống)'}",
                f"    - SĐT tài xế   : {t.get('driver_phone') or '(trống)'}",
            ])

    out_lines.append("")
    out_lines.append("--- [4. CHI TIẾT CÁC CONTAINER (CONTAINERS)] ---")
    if not containers:
        out_lines.append("(Không có container nào được bóc tách)")
    else:
        for idx, c in enumerate(containers, 1):
            warnings = c.get("warnings", [])
            warn_str = ", ".join(warnings) if warnings else "Không có"
            out_lines.extend([
                f"  Container #{idx} (Dòng {c.get('line_no', idx)}):",
                f"    - Số Container    : {c.get('container_no') or '(trống)'}",
                f"    - Kích cỡ cont    : {c.get('container_size') or '(trống)'}",
                f"    - Số seal / chì   : {c.get('seal_no') or '(trống)'}",
                f"    - Loại lệnh       : {c.get('order_type') or '(chưa rõ)'}",
                f"    - Gợi ý kho       : {c.get('warehouse_hint') or '(trống)'}",
                f"    - Gợi ý khách     : {c.get('customer_hint') or '(trống)'}",
                f"    - Chuẩn ISO 6346  : {'HỢP LỆ (TRUE)' if c.get('check_digit_valid') else 'SAI SỐ KIỂM TRA (FALSE)'}",
                f"    - Trạng thái kiểm : {c.get('validation_status')}",
                f"    - Cảnh báo        : {warn_str}",
            ])

    out_lines.append("")
    out_lines.append("--- [5. KỲ VỌNG BAN ĐẦU (EXPECTED FROM FIXTURE)] ---")
    out_lines.append(expected_text)

    out_lines.append("")
    out_lines.append("--- [6. DỮ LIỆU JSON CHI TIẾT TRẢ VỀ (RAW JSON RESPONSE)] ---")
    out_lines.append(json.dumps(result_data, ensure_ascii=False, indent=2))
    out_lines.append("")

    return "\n".join(out_lines)


def run_tests(
    input_files: list[str],
    output_dir: str,
) -> None:
    """Thực thi kiểm thử danh sách tệp và xuất ra thư mục output."""
    os.makedirs(output_dir, exist_ok=True)
    total = len(input_files)
    print(f"\n🚀 BẮT ĐẦU CHẠY KIỂM THỬ {total} TỆP INPUT...")
    print(f"📂 Thư mục xuất kết quả: {output_dir}\n")
    print(f"{'STT':<4} | {'MÃ TEST':<8} | {'HÀNH ĐỘNG':<16} | {'TRẠNG THÁI':<14} | {'XE':<3} | {'CONT':<4} | {'TỆP OUTPUT'}")
    print("-" * 88)

    processed_count = 0
    needs_review_count = 0
    ignored_count = 0

    for idx, fpath in enumerate(input_files, 1):
        test_id, format_label, raw_text = extract_input_text_from_file(fpath)
        expected_text = load_expected_text_if_exists(fpath)

        res = process_message_through_pipeline(raw_text=raw_text, test_id=test_id)

        # Tạo báo cáo và lưu tệp output
        out_content = format_output_report(
            test_id=test_id,
            format_label=format_label,
            input_file_path=fpath,
            raw_text=raw_text,
            expected_text=expected_text,
            result_data=res,
        )

        base_name = os.path.basename(fpath)
        out_filename = base_name.replace("_input.txt", "_output.txt")
        if not out_filename.endswith("_output.txt"):
            out_filename = f"{test_id}_output.txt"

        out_path = os.path.join(output_dir, out_filename)
        with open(out_path, "w", encoding="utf-8") as out_fp:
            out_fp.write(out_content)

        data = res.get("data", {})
        action = data.get("action", "UNKNOWN")
        status = data.get("processing_status", "UNKNOWN")
        truck_cnt = len(data.get("trucks", []))
        cont_cnt = len(data.get("containers", []))

        if status == "processed":
            processed_count += 1
        elif status == "needs_review":
            needs_review_count += 1
        elif status == "ignored_chat":
            ignored_count += 1

        print(
            f"{idx:<4} | {test_id:<8} | {action:<16} | {status:<14} | {truck_cnt:<3} | {cont_cnt:<4} | {out_filename}"
        )

    print("-" * 88)
    print(f"✅ HOÀN THÀNH: {total} Tệp | Đã xử lý (processed): {processed_count} | Cần duyệt (needs_review): {needs_review_count} | Tin rác (ignored): {ignored_count}")
    print(f"👉 Tất cả các tệp output chi tiết đã được lưu tại: {output_dir}\n")


def main():
    parser = argparse.ArgumentParser(description="Chạy kiểm thử các tệp input text cho Bot Zalo.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Chạy kiểm thử toàn bộ các tệp `*_input.txt` trong thư mục fixtures.",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Chạy kiểm thử một tệp cụ thể (VD: TC-01_input.txt hoặc đường dẫn đầy đủ).",
    )
    parser.add_argument(
        "--fixture-dir",
        type=str,
        default=DEFAULT_FIXTURE_DIR,
        help=f"Thư mục chứa fixtures (mặc định: {DEFAULT_FIXTURE_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Thư mục lưu tệp output (mặc định: {DEFAULT_OUTPUT_DIR})",
    )

    args = parser.parse_args()

    # Xác định danh sách tệp cần test
    if args.file:
        target_file = args.file
        if not os.path.isabs(target_file) and not os.path.exists(target_file):
            target_file = os.path.join(args.fixture_dir, target_file)

        if not os.path.exists(target_file):
            print(f"❌ Không tìm thấy tệp: {target_file}")
            sys.exit(1)
        input_files = [target_file]
    elif args.all or len(sys.argv) == 1:
        pattern = os.path.join(args.fixture_dir, "*_input.txt")
        input_files = sorted(glob.glob(pattern))
        if not input_files:
            # Tìm tất cả các file .txt không phải expected
            all_txt = sorted(glob.glob(os.path.join(args.fixture_dir, "*.txt")))
            input_files = [f for f in all_txt if not f.endswith("_expected.txt")]
    else:
        parser.print_help()
        sys.exit(0)

    if not input_files:
        print(f"⚠️ Không tìm thấy tệp input nào trong {args.fixture_dir}")
        sys.exit(1)

    run_tests(input_files=input_files, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
