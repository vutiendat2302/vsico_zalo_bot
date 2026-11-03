#!/usr/bin/env python3
"""Script Chạy Kiểm Thử An Toàn Dữ Liệu Test Case CSV (VSICO Safe CSV Test Runner).

Tính năng:
1. Đọc các ca kiểm thử từ file CSV (mặc định: `tests/data_test/test_case_20_phan_ket_hop.csv`).
2. Điều tiết tần suất gửi (Rate-limiting delay): tự động giãn cách giữa các tin nhắn
   (mặc định 2.0 giây/tin) để bảo vệ tài khoản và tránh bị Zalo giới hạn/phát hiện spam.
3. Cho phép chạy giới hạn số lượng tin (mặc định 5 tin đầu tiên) theo yêu cầu kiểm thử an toàn.
4. Gửi trực tiếp payload webhook đến cổng `POST http://localhost:8000/webhook`.
5. Tự động kiểm tra đối chiếu dữ liệu bóc tách được từ tin nhắn với bảng Kế hoạch Vận Chuyển (`transport_plans`):
   - Số cont -> Khách hàng, Loại lệnh (đóng/trả), Điểm nhận/giao, Nhóm Zalo đích.
6. Hiển thị báo cáo kết quả chi tiết, chuyên nghiệp.

Cách dùng:
  # Chạy thử nghiệm 5 tin đầu tiên với độ trễ 2 giây/tin:
  python scripts/run_csv_test_cases.py --count 5 --delay 2.0

  # Chạy 10 tin tiếp theo (bắt đầu từ tin thứ 6):
  python scripts/run_csv_test_cases.py --count 10 --offset 5 --delay 1.5

  # Dọn dẹp dữ liệu mock runtime trước khi chạy:
  python scripts/run_csv_test_cases.py --clean-first --count 5
"""

import argparse
import csv
from datetime import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# Thiết lập đường dẫn import backend
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = (
    os.path.dirname(CURRENT_DIR)
    if os.path.basename(CURRENT_DIR) == "scripts"
    else CURRENT_DIR
)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

DEFAULT_CSV_PATH = os.path.join(
    BACKEND_ROOT, "tests", "data_test", "test_case_20_phan_ket_hop.csv"
)
DEFAULT_WEBHOOK_URL = "http://localhost:8000/webhook"


def send_webhook_request(url: str, payload: dict) -> tuple[int, dict]:
    """Gửi HTTP POST request đến cổng Webhook backend.

    Args:
        url (str): Địa chỉ API webhook.
        payload (dict): Dữ liệu tin nhắn JSON.

    Returns:
        tuple[int, dict]: (Mã HTTP status, Dữ liệu phản hồi JSON).
    """
    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "VSICO-Safe-Test-Runner/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = resp.getcode()
            body = json.loads(resp.read().decode("utf-8"))
            return status_code, body
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return 500, {"error": str(e)}


def clean_runtime_database():
    """Dọn dẹp các bảng nghiệp vụ runtime trong MySQL trước khi test."""
    print("🧹 Đang thực hiện dọn dẹp dữ liệu nghiệp vụ runtime...")
    from scripts.manage_db import DatabaseManager, OPERATIONAL_TABLES
    DatabaseManager.truncate_table_list(OPERATIONAL_TABLES)
    print("✅ Đã dọn sạch các bảng tin nhắn, lượt xe, container, hàng đợi duyệt và log.")


def run_tests(
    csv_path: str,
    count: int = 5,
    offset: int = 0,
    delay_seconds: float = 2.0,
    webhook_url: str = DEFAULT_WEBHOOK_URL,
    clean_first: bool = False,
    verbose: Optional[bool] = None,
):
    """Đọc dữ liệu CSV và thực thi kiểm thử an toàn từng tin nhắn với cơ chế giãn cách.

    Args:
        csv_path (str): Đường dẫn file CSV.
        count (int): Số lượng tin nhắn cần test.
        offset (int): Vị trí bắt đầu trong file.
        delay_seconds (float): Thời gian giãn cách giữa các tin gửi (giây).
        webhook_url (str): Endpoint nhận tin.
        clean_first (bool): Có xóa dữ liệu cũ trước khi chạy không.
        verbose (bool): In chi tiết từng tin (mặc định True khi count <= 20, False khi chạy batch lớn).
    """
    if clean_first:
        clean_runtime_database()

    if not os.path.exists(csv_path):
        print(f"❌ Không tìm thấy tệp dữ liệu test: {csv_path}")
        sys.exit(1)

    is_verbose = verbose if verbose is not None else (count <= 20)

    print("\n" + "=" * 90)
    print("🚀 VSICO SAFE TEST RUNNER — KIỂM THỬ AN TOÀN TIN NHẮN ĐIỀU VẬN")
    print("=" * 90)
    print(f"📁 Tệp nguồn         : {os.path.basename(csv_path)}")
    print(f"🔢 Số lượng tin test : {count:,} tin (từ vị trí {offset + 1:,} đến {offset + count:,})")
    print(f"⏱️  Thời gian giãn cách: {delay_seconds} giây/tin")
    print(f"🎯 Webhook Gateway   : {webhook_url}")
    print(f"📊 Chế độ hiển thị   : {'Chi tiết từng tin (Verbose)' if is_verbose else 'Tối ưu hiệu năng & Tiến độ tổng hợp'}")
    print("=" * 90 + "\n")

    results_summary = []
    status_counts: Dict[str, int] = {}
    total_trucks = 0
    total_conts = 0
    matched_plan_conts = 0
    total_latency_ms = 0

    benchmark_start = time.perf_counter()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        current_idx = 0
        tested_count = 0

        for row in reader:
            if current_idx < offset:
                current_idx += 1
                continue

            if tested_count >= count:
                break

            test_case_idx = current_idx + 1
            tested_count += 1
            current_idx += 1

            bien_the = row.get("bien_the_ap_dung") or row.get("ten_cac_phan") or f"TC-{test_case_idx}"
            raw_json_str = row.get("tin_nhan_dau_vao_json")
            if not raw_json_str:
                continue

            try:
                payload = json.loads(raw_json_str)
            except Exception as e:
                if is_verbose:
                    print(f"⚠️ Ca #{test_case_idx}: Lỗi phân tích JSON đầu vào: {e}")
                continue

            # Đánh dấu cờ kiểm thử để Backend TUYỆT ĐỐI không gửi tin nhắn/nhắc lỗi ra Zalo
            payload["is_test"] = True
            payload["is_test_runner"] = True

            # Thêm timestamp và unique id nếu cần tránh bị deduplicate cũ
            msg_obj = payload.get("message") or {}
            raw_text = msg_obj.get("text") or ""
            unique_msg_id = f"test_{int(time.time()*1000)}_{test_case_idx}"
            msg_obj["msg_id"] = unique_msg_id
            payload["message"] = msg_obj

            if is_verbose:
                print(f"--------------------------------------------------------------------------------")
                print(f"📨 [TIN #{tested_count}/{count}] Ca kiểm thử #{test_case_idx}: {bien_the}")
                print(f"📝 Nội dung gửi:")
                for line in raw_text.strip().split("\n"):
                    print(f"    │ {line}")

            start_t = time.perf_counter()
            http_status, resp_data = send_webhook_request(webhook_url, payload)
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            total_latency_ms += elapsed_ms

            ok = resp_data.get("ok", False)
            proc_status = resp_data.get("processing_status", "unknown").lower()
            trucks = resp_data.get("trucks") or []
            containers = resp_data.get("containers") or []

            # Thống kê
            status_counts[proc_status] = status_counts.get(proc_status, 0) + 1
            total_trucks += len(trucks)
            total_conts += len(containers)
            for c in containers:
                if c.get("match_source") == "transport_plan":
                    matched_plan_conts += 1

            if is_verbose:
                print(f"⚡ Phản hồi Backend  : HTTP {http_status} ({elapsed_ms}ms) | Trạng thái: {proc_status.upper()}")
                for t in trucks:
                    print(f"    🚚 Xe: {t.get('truck_plate')} | Lái xe: {t.get('driver_name')} ({t.get('driver_phone')})")
                for c in containers:
                    c_no = c.get("container_no")
                    seal = c.get("seal_no")
                    ord_type = c.get("order_type")
                    m_src = c.get("match_source")
                    cust = c.get("customer_hint") or "N/A"
                    wh = c.get("warehouse_hint") or "N/A"
                    v_stat = c.get("validation_status") or "N/A"
                    warns = c.get("warnings") or []
                    ord_label = "ĐÓNG HÀNG" if ord_type == "dong" else "TRẢ HÀNG" if ord_type == "tra" else "CHƯA RÕ"
                    print(f"    📦 Cont: {c_no} (Chì: {seal})")
                    print(f"       ├─ Lệnh (từ bảng kế hoạch): {ord_label} (`{ord_type}`)")
                    print(f"       ├─ Khách hàng           : {cust}")
                    print(f"       ├─ Địa chỉ nhận/giao    : {wh}")
                    print(f"       ├─ Nguồn ghép (match)   : {m_src}")
                    print(f"       └─ Kiểm tra hợp lệ      : {v_stat.upper()} {('⚠️ ' + ', '.join(warns)) if warns else '✅'}")

                carrier_warn = resp_data.get("reply_to_carrier") or (resp_data.get("data") or {}).get("reply_to_carrier")
                if carrier_warn:
                    print(f"    📢 [THÔNG BÁO LỖI GỬI NHÀ XE]:")
                    for w_line in carrier_warn.strip().split("\n"):
                        print(f"       {w_line}")

            # Cập nhật tiến độ theo chu kỳ nếu không chạy verbose
            elif (tested_count % 500 == 0) or (tested_count == count):
                now_elapsed = max(0.001, time.perf_counter() - benchmark_start)
                rate = tested_count / now_elapsed
                pct = (tested_count / count) * 100
                print(
                    f"⏳ [TIẾN ĐỘ {tested_count:,}/{count:,} ({pct:.1f}%)] "
                    f"| Tốc độ: {rate:.1f} tin/s "
                    f"| Chờ duyệt: {status_counts.get('needs_review', 0):,} "
                    f"| Đã xử lý: {status_counts.get('processed', 0) + status_counts.get('parsed_ok', 0):,} "
                    f"| Conts: {total_conts:,} (Ghép KH: {matched_plan_conts:,})"
                )

            if is_verbose or count <= 100:
                results_summary.append({
                    "tc_index": test_case_idx,
                    "variant": bien_the,
                    "raw_text": raw_text.replace("\n", " "),
                    "http_status": http_status,
                    "processing_status": proc_status,
                    "trucks_count": len(trucks),
                    "containers_count": len(containers),
                    "containers": containers,
                    "elapsed_ms": elapsed_ms,
                })

            # GIÃN CÁCH THỜI GIAN GIỮA CÁC TIN
            if delay_seconds > 0 and tested_count < count:
                if is_verbose:
                    print(f"⏳ [SAFETY THROTTLE] Tạm hoãn {delay_seconds} giây trước khi gửi tin tiếp theo...")
                time.sleep(delay_seconds)

    total_time_sec = max(0.001, time.perf_counter() - benchmark_start)
    avg_latency = round(total_latency_ms / max(1, tested_count), 2)
    throughput = round(tested_count / total_time_sec, 2)

    # Hiển thị bảng tóm tắt nếu số lượng ít
    if results_summary and len(results_summary) <= 50:
        print("\n" + "=" * 90)
        print("📊 TỔNG HỢP KẾT QUẢ KIỂM THỬ TỪNG CA")
        print("=" * 90)
        print(f"{'CA #':<6} | {'TRẠNG THÁI':<15} | {'XE':<3} | {'CONT':<4} | {'GHÉP KẾ HOẠCH':<18} | {'BIẾN THỂ / MÔ TẢ'}")
        print("-" * 90)
        for res in results_summary:
            m_srcs = [c.get("match_source", "") for c in res["containers"]]
            m_str = ", ".join(m_srcs) if m_srcs else "none"
            print(
                f"#{res['tc_index']:<5} | "
                f"{res['processing_status']:<15} | "
                f"{res['trucks_count']:<3} | "
                f"{res['containers_count']:<4} | "
                f"{m_str:<18} | "
                f"{res['variant'][:35]}"
            )

    print("\n" + "=" * 90)
    print("🏁 BÁO CÁO TỔNG QUAN HIỆU NĂNG & ĐỘ CHÍNH XÁC BACKEND")
    print("=" * 90)
    print(f"Tổng số tin nhắn đã gửi    : {tested_count:,} tin")
    print(f"Tổng thời gian thực thi    : {total_time_sec:.2f} giây ({total_time_sec/60:.2f} phút)")
    print(f"Tốc độ xử lý (Throughput)  : {throughput:.2f} tin nhắn/giây")
    print(f"Độ trễ trung bình/tin (RTT): {avg_latency:.2f} ms/tin")
    print("-" * 90)
    print("Phân bố trạng thái xử lý:")
    for st, c_num in sorted(status_counts.items()):
        st_pct = (c_num / tested_count) * 100
        print(f"   • {st.upper():<20}: {c_num:,} tin ({st_pct:.1f}%)")
    print("-" * 90)
    print(f"Tổng số xe nhận diện được   : {total_trucks:,} xe")
    print(f"Tổng container nhận diện    : {total_conts:,} container")
    print(f"Container ghép đúng kế hoạch: {matched_plan_conts:,} container ({round((matched_plan_conts/max(1, total_conts))*100, 1)}%)")
    print("=" * 90)
    print("🌐 Truy cập giao diện Web để theo dõi và duyệt danh sách tin:")
    print("   👉 Quản lý Tin nhắn : http://localhost:3000/messages")
    print("   👉 Kết quả Outbound : http://localhost:3000/results")
    print("   👉 Hàng đợi Duyệt   : http://localhost:3000/reviews")
    print("=" * 90 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="VSICO Safe CSV Test Runner — Chạy thử nghiệm có giãn cách thời gian để bảo vệ tài khoản Zalo."
    )
    parser.add_argument(
        "--file",
        default=DEFAULT_CSV_PATH,
        help="Đường dẫn file CSV test cases (mặc định: tests/data_test/test_case_20_phan_ket_hop.csv)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Số lượng tin nhắn cần gửi thử nghiệm (mặc định: 5 tin)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Vị trí bắt đầu trong file CSV (mặc định: 0)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Số giây giãn cách giữa các tin gửi (mặc định: 2.0s để tránh bị Zalo giới hạn)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_WEBHOOK_URL,
        help=f"Endpoint Webhook nhận tin (mặc định: {DEFAULT_WEBHOOK_URL})",
    )
    parser.add_argument(
        "--clean-first",
        action="store_true",
        help="Dọn dẹp sạch dữ liệu mock runtime trước khi bắt đầu test",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=None,
        help="Bắt buộc in chi tiết từng tin nhắn (mặc định tự động bật nếu count <= 20)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Chạy toàn bộ 20.000 test cases với tốc độ cao (count=20000, delay=0)",
    )

    args = parser.parse_args()
    count_to_run = 20000 if args.full else args.count
    delay_to_use = 0.0 if args.full else args.delay

    run_tests(
        csv_path=args.file,
        count=count_to_run,
        offset=args.offset,
        delay_seconds=delay_to_use,
        webhook_url=args.url,
        clean_first=args.clean_first,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
