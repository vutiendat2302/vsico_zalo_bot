#!/usr/bin/env python3
"""Script Quản Lý & Dọn Dẹp Cơ Sở Dữ Liệu MySQL (VSICO Database Management Utility).

Cung cấp các công cụ dòng lệnh chuyên nghiệp để:
1. `status` / `stats`: Thống kê chi tiết số lượng bản ghi trong toàn bộ 17 bảng của hệ thống.
2. `check`: Kiểm tra trạng thái kết nối tới MySQL, phiên bản máy chủ và revision Alembic hiện tại.
3. `clean`: Dọn dẹp dữ liệu an toàn theo các chế độ:
   - `--runtime` / `--operational`: Dọn dẹp toàn bộ dữ liệu tin nhắn, bóc tách xe/container, lịch sử AI,
     hàng đợi duyệt và log gửi tin (bảo toàn danh mục Khách hàng, Kho, Nhóm Zalo và Kế hoạch vận chuyển).
   - `--plans`: Dọn dẹp bảng kế hoạch vận chuyển `transport_plans`.
   - `--tests`: Dọn dẹp các bản ghi sinh ra trong quá trình chạy kiểm thử tự động (tiền tố `pytest_`, `test_`, `mock_`).
   - `--all`: Dọn dẹp trắng toàn bộ 17 bảng trong database (an toàn với Foreign Key).
4. `reset`: Đặt lại toàn bộ cơ sở dữ liệu về trạng thái ban đầu và áp dụng migration mới nhất của Alembic.

Cách dùng:
  # 1. Xem thống kê số lượng bản ghi của 17 bảng:
  python scripts/manage_db.py status

  # 2. Kiểm tra kết nối và phiên bản Alembic hiện tại:
  python scripts/manage_db.py check

  # 3. Dọn dẹp dữ liệu nghiệp vụ (tin nhắn, xe, cont, review, log) - GIỮ danh mục & kế hoạch:
  python scripts/manage_db.py clean --runtime -y

  # 4. Dọn dẹp bảng kế hoạch vận chuyển:
  python scripts/manage_db.py clean --plans -y

  # 5. Dọn dẹp chỉ các bản ghi kiểm thử tự động (pytest_*, test_*):
  python scripts/manage_db.py clean --tests

  # 6. Dọn dẹp toàn bộ dữ liệu (trắng DB, giữ nguyên cấu trúc bảng):
  python scripts/manage_db.py clean --all -y

  # 7. Reset toàn bộ schema (xóa sạch và chạy lại alembic upgrade head):
  python scripts/manage_db.py reset -y
"""

import argparse
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

# Đảm bảo import được module backend
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = (
    os.path.dirname(CURRENT_DIR)
    if os.path.basename(CURRENT_DIR) == "scripts"
    else CURRENT_DIR
)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.infrastructure.database import SessionLocal, engine
from src.infrastructure.models import (
    ActivityLog,
    Base,
    BotReply,
    ContainerJob,
    Customer,
    CustomerAlias,
    ExtractionRun,
    OutboundMessage,
    OutboundMessageItem,
    ReviewCase,
    RouteMap,
    TmsSyncLog,
    TransportPlan,
    TruckRecord,
    User,
    Warehouse,
    WarehouseAlias,
    ZaloGroup,
    ZaloMessage,
)

# Phân nhóm bảng để dọn dẹp có định hướng rõ ràng
OPERATIONAL_TABLES = [
    "message_drafts",
    "files",
    "outbound_message_items",
    "outbound_messages",
    "bot_replies",
    "review_cases",
    "tms_sync_logs",
    "activity_logs",
    "container_jobs",
    "truck_records",
    "extraction_runs",
    "zalo_messages",
]

PLAN_TABLES = [
    "transport_plans",
]

CATALOG_TABLES = [
    "users",
    "carriers",
    "route_maps",
    "warehouse_aliases",
    "customer_aliases",
    "warehouses",
    "customers",
    "zalo_groups",
]

ALL_SYSTEM_TABLES = OPERATIONAL_TABLES + PLAN_TABLES + CATALOG_TABLES

TABLE_DESCRIPTIONS: Dict[str, str] = {
    # Dữ liệu nghiệp vụ / runtime
    "zalo_messages": "Tin nhắn thô nhận từ Zalo OA",
    "extraction_runs": "Lịch sử các phiên bóc tách AI/Rule",
    "truck_records": "Lượt xe (Biển số, Mooc, Lái xe, SĐT)",
    "container_jobs": "Bản ghi quản lý từng Container (Trung tâm)",
    "review_cases": "Hàng đợi duyệt thủ công ĐHVT",
    "bot_replies": "Tin bot nhắc lỗi nhà xe (hạn sửa 30p)",
    "outbound_messages": "Tin thông báo gửi tới nhóm khách hàng",
    "outbound_message_items": "Bảng trung gian gắn cont vào tin outbound",
    "tms_sync_logs": "Nhật ký đồng bộ dữ liệu sang be-tms",
    "activity_logs": "Nhật ký thao tác người dùng & hệ thống",
    "files": "Lưu trữ thông tin metadata file tải lên MinIO S3",
    "message_drafts": "Bản nháp gom các tin nhắn rời rạc từ nhà xe",
    # Kế hoạch vận chuyển
    "transport_plans": "Kế hoạch điều vận hằng ngày (Import Excel/CSV)",
    # Danh mục / Master data
    "users": "Tài khoản nhân viên nội bộ (ĐHVT, Admin)",
    "carriers": "Danh mục nhà xe / đội xe chuẩn từ TMS",
    "customers": "Danh mục khách hàng chuẩn từ TMS",
    "warehouses": "Danh mục kho đóng/trả hàng chuẩn",
    "customer_aliases": "Tên viết tắt/bí danh của khách hàng",
    "warehouse_aliases": "Tên viết tắt/bí danh của kho hàng",
    "route_maps": "Bảng ánh xạ Khách + Kho -> Nhóm Zalo",
    "zalo_groups": "Danh mục nhóm Zalo (Nhà xe, Khách, ĐHVT)",
}


class DatabaseManager:
    """Lớp tiện ích thực thi các tác vụ quản trị và dọn dẹp cơ sở dữ liệu MySQL."""

    @staticmethod
    def get_alembic_current_revision() -> Optional[str]:
        """Truy vấn revision hiện tại từ bảng `alembic_version` trong MySQL.

        Returns:
            Optional[str]: Mã revision migration hiện tại (VD: '8b530e8da3ec') hoặc None.
        """
        try:
            with engine.connect() as conn:
                res = conn.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1;")
                ).scalar()
                return str(res) if res else None
        except Exception:
            return None

    @classmethod
    def check_connection(cls) -> Dict[str, Any]:
        """Kiểm tra tình trạng kết nối tới máy chủ MySQL và thu thập thông số môi trường.

        Returns:
            Dict[str, Any]: Thông tin chi tiết về trạng thái DB, phiên bản và URL.
        """
        print(f"\n[INFO] Đang kiểm tra kết nối tới cơ sở dữ liệu...")
        print(f"  - Database URL: {settings.DATABASE_URL.split('@')[-1]}")
        print(f"  - Host: {settings.DB_HOST}:{settings.DB_PORT}")
        print(f"  - Database: {settings.DB_NAME}")

        try:
            with engine.connect() as conn:
                version = conn.execute(text("SELECT VERSION();")).scalar()
                current_db = conn.execute(text("SELECT DATABASE();")).scalar()
                alembic_rev = cls.get_alembic_current_revision()

                print(f"[SUCCESS] Kết nối MySQL thành công!")
                print(f"  - MySQL Server Version: {version}")
                print(f"  - Current Schema: {current_db}")
                print(f"  - Alembic Current Revision: {alembic_rev or 'Chưa khởi tạo'}")
                return {
                    "ok": True,
                    "version": version,
                    "database": current_db,
                    "alembic_revision": alembic_rev,
                }
        except Exception as exc:
            print(f"[ERROR] Không thể kết nối tới MySQL: {exc}")
            return {"ok": False, "error": str(exc)}

    @classmethod
    def show_statistics(cls) -> Dict[str, int]:
        """Đếm và hiển thị bảng biểu số lượng bản ghi của toàn bộ 17 bảng trong database.

        Returns:
            Dict[str, int]: Bản đồ tên bảng -> số lượng bản ghi hiện có.
        """
        stats: Dict[str, int] = {}
        total_records = 0

        print("\n" + "=" * 80)
        print(" THỐNG KÊ SỐ LƯỢNG BẢN GHI TRONG CƠ SỞ DỮ LIỆU (TOÀN BỘ CÁC BẢNG)")
        print("=" * 80)
        print(f"{'NHÓM / TÊN BẢNG':<26} | {'SỐ DÒNG':>9} | {'MÔ TẢ NGHIỆP VỤ'}")
        print("-" * 80)

        def print_group(group_name: str, tables: List[str]) -> int:
            group_subtotal = 0
            print(f"--- [ {group_name} ] ---")
            with engine.connect() as conn:
                for tbl in tables:
                    try:
                        cnt = conn.execute(
                            text(f"SELECT COUNT(*) FROM `{tbl}`;")
                        ).scalar()
                        count_val = int(cnt) if cnt is not None else 0
                    except Exception:
                        count_val = -1  # Bảng chưa được tạo
                    stats[tbl] = count_val
                    group_subtotal += max(0, count_val)
                    desc = TABLE_DESCRIPTIONS.get(tbl, "")
                    cnt_str = f"{count_val:,}" if count_val >= 0 else "CHƯA TẠO"
                    print(f"  {tbl:<24} | {cnt_str:>9} | {desc}")
            return group_subtotal

        total_op = print_group("1. DỮ LIỆU NGHIỆP VỤ & TIN NHẮN (RUNTIME)", OPERATIONAL_TABLES)
        total_plan = print_group("2. KẾ HOẠCH VẬN CHUYỂN (PLANS)", PLAN_TABLES)
        total_cat = print_group("3. DANH MỤC & CẤU HÌNH (MASTER DATA)", CATALOG_TABLES)

        total_records = total_op + total_plan + total_cat

        print("-" * 80)
        print(
            f"  TỔNG CỘNG TOÀN BỘ HỆ THỐNG: {total_records:,} bản ghi "
            f"(Runtime: {total_op:,} | Plans: {total_plan:,} | Master: {total_cat:,})"
        )
        print("=" * 80)

        alembic_rev = cls.get_alembic_current_revision()
        print(f"  Trạng thái Alembic Head: {alembic_rev or 'N/A'}\n")
        return stats

    @classmethod
    def truncate_table_list(cls, table_names: List[str]) -> Dict[str, int]:
        """Xóa trắng an toàn danh sách bảng được chỉ định với foreign key checks tắt tạm thời.

        Args:
            table_names (List[str]): Danh sách tên các bảng cần dọn dẹp.

        Returns:
            Dict[str, int]: Thống kê số lượng dòng đã xóa theo từng bảng.
        """
        deleted_counts: Dict[str, int] = {}
        with engine.begin() as conn:
            # Tạm thời tắt kiểm tra khóa ngoại để TRUNCATE không bị lỗi phụ thuộc
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            try:
                for tbl in table_names:
                    try:
                        cnt = conn.execute(
                            text(f"SELECT COUNT(*) FROM `{tbl}`;")
                        ).scalar()
                        initial_count = int(cnt) if cnt is not None else 0
                    except Exception:
                        initial_count = 0

                    conn.execute(text(f"TRUNCATE TABLE `{tbl}`;"))
                    deleted_counts[tbl] = initial_count
            finally:
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

        return deleted_counts

    @classmethod
    def clean_runtime_data(cls) -> None:
        """Dọn dẹp toàn bộ dữ liệu nghiệp vụ / runtime (tin nhắn, lượt xe, container jobs, logs).

        Giữ nguyên: Kế hoạch vận chuyển (`transport_plans`) và Master data (khách, kho, nhóm zalo).
        """
        print("\n[BẮT ĐẦU] Đang dọn dẹp dữ liệu nghiệp vụ & tin nhắn runtime...")
        deleted = cls.truncate_table_list(OPERATIONAL_TABLES)
        total_deleted = sum(deleted.values())
        for tbl, cnt in deleted.items():
            print(f"  - Đã xóa {cnt:,} dòng tại bảng `{tbl}`")
        print(f"[HOÀN TẤT] Tổng cộng đã dọn {total_deleted:,} bản ghi nghiệp vụ. Giữ nguyên Master Data & Plans!\n")

    @classmethod
    def clean_plans_data(cls) -> None:
        """Dọn dẹp bảng kế hoạch vận chuyển `transport_plans`."""
        print("\n[BẮT ĐẦU] Đang dọn dẹp bảng kế hoạch vận chuyển `transport_plans`...")
        deleted = cls.truncate_table_list(PLAN_TABLES)
        print(f"[HOÀN TẤT] Đã xóa {deleted.get('transport_plans', 0):,} dòng trong bảng `transport_plans`.\n")

    @classmethod
    def clean_test_records_only(cls) -> None:
        """Dọn dẹp có chọn lọc chỉ các bản ghi kiểm thử (chứa tiền tố test_, pytest_, mock_).

        Bảo toàn toàn bộ dữ liệu thật đang vận hành trên môi trường thực tế.
        """
        print("\n[BẮT ĐẦU] Đang quét và dọn dẹp các bản ghi kiểm thử (pytest_*, test_*, mock_*)...")
        test_patterns = ["pytest_%", "test_%", "mock_%"]

        with SessionLocal() as session:
            total_cleaned_msgs = 0
            for pattern in test_patterns:
                # Tìm ID tin nhắn test
                msg_ids = list(
                    session.scalars(
                        select(ZaloMessage.id).where(
                            ZaloMessage.zalo_message_id.like(pattern)
                        )
                    ).all()
                )
                if msg_ids:
                    session.execute(
                        delete(OutboundMessageItem).where(
                            OutboundMessageItem.container_job_id.in_(
                                select(ContainerJob.id).where(
                                    ContainerJob.message_id.in_(msg_ids)
                                )
                            )
                        )
                    )
                    session.execute(
                        delete(TmsSyncLog).where(
                            TmsSyncLog.container_job_id.in_(
                                select(ContainerJob.id).where(
                                    ContainerJob.message_id.in_(msg_ids)
                                )
                            )
                        )
                    )
                    session.execute(
                        delete(ReviewCase).where(ReviewCase.message_id.in_(msg_ids))
                    )
                    session.execute(
                        delete(BotReply).where(BotReply.message_id.in_(msg_ids))
                    )
                    session.execute(
                        delete(ContainerJob).where(
                            ContainerJob.message_id.in_(msg_ids)
                        )
                    )
                    session.execute(
                        delete(TruckRecord).where(TruckRecord.message_id.in_(msg_ids))
                    )
                    session.execute(
                        delete(ExtractionRun).where(
                            ExtractionRun.message_id.in_(msg_ids)
                        )
                    )
                    session.execute(
                        delete(ZaloMessage).where(ZaloMessage.id.in_(msg_ids))
                    )
                    total_cleaned_msgs += len(msg_ids)

                # Dọn nhóm test
                session.execute(
                    delete(ZaloGroup).where(ZaloGroup.zalo_group_id.like(pattern))
                )

            session.commit()
            print(f"[HOÀN TẤT] Đã dọn dẹp các bản ghi liên quan đến {total_cleaned_msgs:,} tin nhắn kiểm thử!\n")

    @classmethod
    def clean_all_data(cls) -> None:
        """Dọn dẹp trắng toàn bộ 17 bảng trong cơ sở dữ liệu (Schema và Alembic Version được giữ nguyên)."""
        print("\n[CẢNH BÁO] Đang dọn dẹp TRẮNG TOÀN BỘ 17 BẢNG trong database...")
        deleted = cls.truncate_table_list(ALL_SYSTEM_TABLES)
        total_deleted = sum(deleted.values())
        for tbl, cnt in deleted.items():
            print(f"  - Truncated `{tbl}`: {cnt:,} dòng")
        print(f"[HOÀN TẤT] Đã xóa toàn bộ {total_deleted:,} bản ghi. Cơ sở dữ liệu hiện ở trạng thái sạch 100%!\n")

    @classmethod
    def reset_database(cls) -> None:
        """Reset toàn bộ database: Drop tables và chạy lại migrations Alembic lên HEAD."""
        print("\n[CẢNH BÁO CAO] Bắt đầu quy trình RESET TOÀN BỘ CƠ SỞ DỮ LIỆU...")
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            try:
                # Lấy danh sách toàn bộ bảng hiện có
                tables = conn.execute(text("SHOW TABLES;")).fetchall()
                for t in tables:
                    table_name = t[0]
                    print(f"  - Dropping table `{table_name}`...")
                    conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`;"))
            finally:
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

        print("[INFO] Đang chạy Alembic Migrations để tái tạo lại toàn bộ 17 bảng...")
        alembic_bin = (
            os.path.join(BACKEND_ROOT, ".venv", "bin", "alembic")
            if os.path.exists(os.path.join(BACKEND_ROOT, ".venv", "bin", "alembic"))
            else "alembic"
        )
        cmd = [alembic_bin, "upgrade", "head"]
        result = subprocess.run(cmd, cwd=BACKEND_ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            print("[SUCCESS] Alembic upgrade head hoàn tất thành công!")
            print(result.stdout)
            cls.show_statistics()
        else:
            print(f"[ERROR] Chạy Alembic thất bại: {result.stderr}")

    @classmethod
    def seed_data(cls) -> None:
        """Tự động kiểm tra và khởi tạo tài khoản quản trị mặc định (admin) nếu chưa có."""
        print("\n[BẮT ĐẦU] Đang kiểm tra và khởi tạo dữ liệu quản trị viên...")
        from src.api.app import seed_initial_users
        seed_initial_users()
        print("[HOÀN TẤT] Quá trình kiểm tra và khởi tạo tài khoản admin hoàn tất!\n")


def confirm_prompt(prompt_message: str) -> bool:
    """Yêu cầu xác nhận từ người dùng qua dòng lệnh trước các tác vụ nhạy cảm.

    Args:
        prompt_message (str): Câu hỏi xác nhận.

    Returns:
        bool: True nếu người dùng đồng ý (y/yes), False nếu hủy.
    """
    try:
        reply = input(f"{prompt_message} [y/N]: ").strip().lower()
        return reply in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print("\nĐã hủy tác vụ.")
        return False


def main() -> None:
    """Điểm nhập lệnh chính (CLI Entrypoint) của tiện ích quản lý database."""
    parser = argparse.ArgumentParser(
        description="VSICO MySQL Database Management & Cleanup Utility (Task 2 - PM TMS VSICO)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Lệnh thao tác cơ sở dữ liệu")

    # 1. Lệnh status
    parser_status = subparsers.add_parser("status", help="Xem thống kê số lượng bản ghi của 17 bảng")
    parser_status.add_argument("--json", action="store_true", help="Xuất kết quả dạng JSON")

    # 2. Lệnh check
    subparsers.add_parser("check", help="Kiểm tra kết nối MySQL và phiên bản Alembic hiện tại")

    # 3. Lệnh clean
    parser_clean = subparsers.add_parser("clean", help="Dọn dẹp dữ liệu trong cơ sở dữ liệu")
    parser_clean.add_argument(
        "--runtime",
        action="store_true",
        help="Dọn dữ liệu tin nhắn, bóc tách xe/cont (Giữ nguyên Master Data & Plans)",
    )
    parser_clean.add_argument(
        "--plans",
        action="store_true",
        help="Dọn dữ liệu bảng kế hoạch vận chuyển `transport_plans`",
    )
    parser_clean.add_argument(
        "--tests",
        action="store_true",
        help="Dọn chỉ các bản ghi kiểm thử tự động (tiền tố pytest_*, test_*, mock_*)",
    )
    parser_clean.add_argument(
        "--all",
        action="store_true",
        help="Dọn TRẮNG toàn bộ 17 bảng trong DB (giữ nguyên cấu trúc bảng)",
    )
    parser_clean.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Tự động đồng ý xác nhận không cần hỏi lại",
    )

    # 4. Lệnh reset
    parser_reset = subparsers.add_parser("reset", help="Xóa sạch toàn bộ bảng và chạy lại Alembic upgrade head")
    parser_reset.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Tự động đồng ý xác nhận không cần hỏi lại",
    )

    # 5. Lệnh seed
    subparsers.add_parser("seed", help="Tự động kiểm tra và khởi tạo tài khoản admin nếu chưa có")

    args = parser.parse_args()

    if not args.command:
        # Nếu không truyền lệnh, hiển thị check và status mặc định
        DatabaseManager.check_connection()
        DatabaseManager.show_statistics()
        return

    if args.command == "check":
        DatabaseManager.check_connection()

    elif args.command == "status":
        stats = DatabaseManager.show_statistics()
        if getattr(args, "json", False):
            import json
            print(json.dumps(stats, indent=2))

    elif args.command == "clean":
        if args.tests:
            DatabaseManager.clean_test_records_only()
        elif args.plans:
            if args.yes or confirm_prompt("Bạn có chắc chắn muốn xóa toàn bộ bảng KẾ HOẠCH VẬN CHUYỂN?"):
                DatabaseManager.clean_plans_data()
        elif args.runtime:
            if args.yes or confirm_prompt("Bạn có chắc chắn muốn xóa toàn bộ dữ liệu TIN NHẮN & NGHIỆP VỤ RUNTIME?"):
                DatabaseManager.clean_runtime_data()
        elif args.all:
            if args.yes or confirm_prompt("CẢNH BÁO: Bạn có chắc chắn muốn XÓA TRẮNG TOÀN BỘ 17 BẢNG trong database?"):
                DatabaseManager.clean_all_data()
        else:
            print("[LƯU Ý] Vui lòng chỉ định loại dữ liệu cần dọn: --runtime, --plans, --tests, hoặc --all.")
            print("Ví dụ: python scripts/manage_db.py clean --runtime -y")

    elif args.command == "reset":
        if args.yes or confirm_prompt("CẢNH BÁO NGUY HIỂM: Bạn có chắc chắn muốn RESET TOÀN BỘ CƠ SỞ DỮ LIỆU VÀ CHẠY LẠI MIGRATIONS?"):
            DatabaseManager.reset_database()

    elif args.command == "seed":
        DatabaseManager.seed_data()


if __name__ == "__main__":
    main()
