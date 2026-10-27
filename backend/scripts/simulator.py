#!/usr/bin/env python3
"""Công Cụ Giả Lập & Thử Nghiệm Tương Tác Trực Tiếp (Interactive CLI Simulator).

Cho phép nhà phát triển và BA chủ động kiểm thử bất kỳ tin nhắn điều xe nào,
quan sát toàn bộ quy trình bóc tách từng bước của hệ thống theo thời gian thực,
và tự động sinh đơn hàng vận chuyển giả lập (Auto-Mock Shipping) cho mọi số container
mà không phụ thuộc vào tệp dữ liệu tĩnh.

Cách sử dụng:
    # 1. Chế độ tương tác nhập tin nhắn trực tiếp qua Terminal:
    python3 scripts/simulator.py

    # 2. Chế độ tương tác có bật sẵn tính năng Auto-Mock Shipping:
    python3 scripts/simulator.py --mock

    # 3. Chạy kiểm thử nhanh một tin nhắn qua dòng lệnh:
    python3 scripts/simulator.py --text "TRẢ HÀNG Cont: VSIU7399796 Seal: 73957169 Xe: 15C-878.99 TX: Trần Quốc Bảo 0903976359"
"""

import os
import sys
import json
import argparse
from typing import Dict, Any, List

# Ráp đường dẫn thư mục mã nguồn vào sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from nhaxe_bot.main import build_application
from nhaxe_bot.domain.rules import validate_iso6346


class SimulatorRunner:
    """Bộ thực thi giả lập mô phỏng tin nhắn và hiển thị luồng Clean Architecture."""

    def __init__(self, shipping_file: str, auto_mock: bool = True):
        """Khởi tạo môi trường ứng dụng và cấu hình chế độ auto-mock.

        Args:
            shipping_file (str): Đường dẫn tệp CSV kế hoạch vận chuyển.
            auto_mock (bool, optional): Bật tính năng tự sinh shipping giả lập. Mặc định là True.
        """
        self.app = build_application(shipping_file)
        self.webhook = self.app["webhook_controller"]
        self.worker = self.app["worker"]
        self.shipping_repo = self.app["shipping_repo"]
        self.trip_repo = self.app["trip_repo"]
        self.auto_mock = auto_mock
        self.shipping_repo.enable_auto_mock(auto_mock)
        self.current_carrier = "NX01"
        self.seq = 0

    def set_carrier(self, carrier_id: str) -> None:
        """Thay đổi nhà xe đang đóng vai gửi tin nhắn.

        Args:
            carrier_id (str): Mã định danh nhà xe (ví dụ: 'NX01', 'NX02', 'NX03', 'NX04').
        """
        self.current_carrier = carrier_id.upper()

    def set_mock_mode(self, enabled: bool) -> None:
        """Bật/tắt chế độ tự sinh đơn hàng giả lập.

        Args:
            enabled (bool): Trạng thái bật hoặc tắt.
        """
        self.auto_mock = enabled
        self.shipping_repo.enable_auto_mock(enabled)

    def process_text(self, text: str) -> List[Dict[str, Any]]:
        """Mô phỏng gửi tin nhắn văn bản vào cổng Webhook và tiêu thụ qua Queue Worker.

        Args:
            text (str): Nội dung tin nhắn người dùng gõ.

        Returns:
            List[Dict[str, Any]]: Danh sách các kết quả phương tiện hoặc hành động xử lý.
        """
        self.seq += 1
        group_id_map = {
            "NX01": "2001000000000000001",
            "NX02": "2002000000000000001",
            "NX03": "2003000000000000001",
            "NX04": "2004000000000000001",
        }
        sender_id_map = {
            "NX01": "1001000000000000001",
            "NX02": "1002000000000000001",
            "NX03": "1003000000000000001",
            "NX04": "1004000000000000001",
        }

        group_id = group_id_map.get(self.current_carrier, "2001000000000000001")
        sender_id = sender_id_map.get(self.current_carrier, "1001000000000000001")

        # Tự động chuyển đổi các ký tự thoát literal \n, \r\n thành xuống dòng thực tế khi dán từ terminal
        text_clean = text.replace("\\r\\n", "\n").replace("\\n", "\n")

        payload = {
            "event_name": "user_send_text",
            "group_id": group_id,
            "sender": {"id": sender_id, "name": f"Điều hành {self.current_carrier}"},
            "timestamp": "1791798000000",
            "message": {
                "msg_id": f"sim_{self.seq:04d}",
                "text": text_clean
            }
        }

        # 1. Tiếp nhận Webhook
        status, ack = self.webhook.handle_webhook_event(self.seq, payload)
        if status != 200:
            print(f"[REJECT] Webhook status {status}: {ack}")
            return []

        # 2. Worker xử lý từ Hàng đợi
        results = self.worker.process_all_queued()
        return results

    def print_pipeline_trace(self, text: str, results: List[Dict[str, Any]]) -> None:
        """In bảng phân tích chi tiết từng bước xử lý dữ liệu ra màn hình console.

        Args:
            text (str): Nội dung văn bản tin nhắn gốc.
            results (List[Dict[str, Any]]): Kết quả xử lý thu được từ Worker.
        """
        print("\n+-----------------------------------------------------------------------------+")
        print("| PIPELINE INSPECTOR TRACE (THEO DÕI LUỒNG BÓC TÁCH CHI TIẾT)                 |")
        print("+-----------------------------------------------------------------------------+")
        print(f"  [INPUT ] Tin nhắn gốc : {repr(text)}")
        print(f"  [CONFIG] Đội xe gửi   : {self.current_carrier}")
        print(f"  [CONFIG] Auto-Mock    : {'BẬT (Tự tạo shipping nếu cont chưa có)' if self.auto_mock else 'TẮT (Chỉ nhận cont trong CSV)'}")
        print("+-----------------------------------------------------------------------------+")

        if not results:
            print("  [WARN] Không có kết quả nào được tạo ra.")
            print("+-----------------------------------------------------------------------------+\n")
            return

        for idx, res in enumerate(results, start=1):
            action = res.get("action", "UNKNOWN")
            print(f"\n  [KẾT QUẢ {idx}] Phân loại hành động: {action}")

            if action == "PARSE":
                cont = res.get("cont") or "Chưa rõ"
                is_iso = validate_iso6346(cont) if cont != "Chưa rõ" else False
                status_str = "HỢP LỆ ISO 6346" if is_iso else "SAI CHECK DIGIT HOẶC ĐỊNH DẠNG"
                print(f"    - Container       : {cont} [{status_str}]")
                print(f"    - Số Seal/Chì     : {res.get('seal') or 'Trống'}")
                print(f"    - Biển số xe      : {res.get('bien_so') or 'Trống'}")
                print(f"    - Tài xế          : {res.get('tai_xe') or 'Trống'}")
                print(f"    - Số điện thoại   : {res.get('sdt') or 'Trống'}")
                print(f"    - Giờ đến dự kiến : {res.get('gio_den') or 'Trống'}")
                print(f"    - Trạng thái gửi  : {res.get('send_status')}")
                if res.get("warnings"):
                    print(f"    - Cảnh báo        : {', '.join(res['warnings'])}")
                if res.get("reply_to_carrier"):
                    print(f"    - Phản hồi nhà xe : {res['reply_to_carrier']}")
                if res.get("notification_text"):
                    print("    - Nội dung thông báo gửi khách hàng:")
                    print("      +-------------------------------------------------------+")
                    for line in res["notification_text"].split("\n"):
                        print(f"      | {line}")
                    print("      +-------------------------------------------------------+")
            elif action == "UPDATE_REQUEST":
                print(f"    - Container đích  : {res.get('cont') or 'Tra theo biển số'}")
                print(f"    - Trạng thái       : {res.get('status')}")
                print(f"    - Phản hồi        : {res.get('reply_to_carrier') or 'Đã cập nhật'}")
            elif action == "CANCEL_REQUEST":
                print(f"    - Container       : {res.get('cont') or 'Chưa rõ'}")
                print(f"    - Lý do hủy       : {res.get('reason') or 'Không nêu lý do'}")
                print(f"    - Cảnh báo Admin  : {res.get('admin_message')}")
            else:
                print(f"    - Chi tiết        : {res.get('reason') or res.get('raw_text', '')}")

        print("+-----------------------------------------------------------------------------+\n")


def start_interactive_cli(simulator: SimulatorRunner) -> None:
    """Bắt đầu vòng lặp dòng lệnh tương tác trực tiếp (Interactive REPL).

    Args:
        simulator (SimulatorRunner): Đối tượng thực thi giả lập.
    """
    print("+-----------------------------------------------------------------------------+")
    print("| CHƯƠNG TRÌNH GIẢ LẬP ĐIỀU VẬN NHAXE-BOT (INTERACTIVE SIMULATOR)              |")
    print("+-----------------------------------------------------------------------------+")
    print("  Các lệnh hỗ trợ nhanh:")
    print("    - 'carrier NX01' / 'carrier NX02': Đổi nhà xe gửi tin.")
    print("    - 'mock on' / 'mock off'         : Bật/tắt chế độ tự tạo shipping.")
    print("    - 'trips'                        : Xem danh sách các chuyến xe đã tạo.")
    print("    - 'clear'                        : Xóa màn hình terminal.")
    print("    - 'exit' hoặc 'quit'             : Thoát chương trình.")
    print("+-----------------------------------------------------------------------------+")

    while True:
        try:
            prompt = f"[{simulator.current_carrier}|Mock:{'ON' if simulator.auto_mock else 'OFF'}] Nhập tin nhắn > "
            user_input = input(prompt).strip()
            if not user_input:
                continue

            low = user_input.lower()
            if low in ("exit", "quit", "q"):
                print("[INFO] Đã thoát chương trình giả lập.")
                break
            elif low.startswith("carrier "):
                parts = user_input.split()
                if len(parts) >= 2:
                    simulator.set_carrier(parts[1])
                    print(f"[OK] Đã chuyển sang nhà xe: {simulator.current_carrier}")
                continue
            elif low in ("mock on", "mock 1", "mock true"):
                simulator.set_mock_mode(True)
                print("[OK] Đã BẬT Auto-Mock Shipping: Mọi số cont đều sẽ tự có đơn kế hoạch.")
                continue
            elif low in ("mock off", "mock 0", "mock false"):
                simulator.set_mock_mode(False)
                print("[WARN] Đã TẮT Auto-Mock Shipping: Chỉ nhận cont có trong CSV.")
                continue
            elif low == "trips":
                trips = simulator.trip_repo.list_all()
                print(f"\n[INFO] Tổng cộng {len(trips)} chuyến xe đã ghi nhận:")
                for t in trips:
                    print(f"    - Cont: {t.cont:<12} | NX: {t.carrier_id} | Ver: {t.version} | Xe: {t.xe_data.get('bien_so'):<10} | TX: {t.xe_data.get('tai_xe')}")
                print()
                continue
            elif low == "clear":
                os.system("clear")
                continue

            # Xử lý tin nhắn người dùng gõ
            results = simulator.process_text(user_input)
            simulator.print_pipeline_trace(user_input, results)

        except (KeyboardInterrupt, EOFError):
            print("\n[INFO] Đã thoát chương trình giả lập.")
            break


def main() -> None:
    """Hàm phân tích tham số dòng lệnh và khởi chạy kịch bản thử nghiệm."""
    parser = argparse.ArgumentParser(description="Zalo TMS nhaxe-bot Interactive Simulator")
    parser.add_argument("--mock", action="store_true", default=True, help="Bật chế độ Auto-Mock Shipping (mặc định bật)")
    parser.add_argument("--no-mock", action="store_false", dest="mock", help="Tắt chế độ Auto-Mock Shipping")
    parser.add_argument("--carrier", type=str, default="NX01", help="Mã nhà xe gửi tin (NX01, NX02, NX03, NX04)")
    parser.add_argument("--text", type=str, default="", help="Tin nhắn cần test ngay lập tức (không vào interactive mode)")
    parser.add_argument("--shipping", type=str, default=os.path.join(PROJECT_ROOT, "tests", "fixtures", "shipping", "nhaxe_shipping_demo.csv"), help="File shipping CSV")
    args = parser.parse_args()

    simulator = SimulatorRunner(args.shipping, auto_mock=args.mock)
    simulator.set_carrier(args.carrier)

    if args.text:
        results = simulator.process_text(args.text)
        simulator.print_pipeline_trace(args.text, results)
    else:
        start_interactive_cli(simulator)


if __name__ == "__main__":
    main()
