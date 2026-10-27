"""Module Nạp Kế Hoạch Vận Chuyển (Shipping Repository).

Chịu trách nhiệm nạp, chuẩn hóa và cung cấp giao diện tra cứu danh mục lệnh vận chuyển
từ file CSV kế hoạch của VSICO (`nhaxe_shipping_demo.csv`), đồng thời hỗ trợ cơ chế
tự động sinh đơn giả lập (Auto-Mock Shipping) phục vụ kiểm thử chủ động.
"""

import os
import csv
from datetime import datetime
from typing import Dict, Optional
from ...domain.models import ShippingOrder
from ...domain.rules import clean_container
from ...config.settings import TZ_VN


class ShippingRepository:
    """Kho dữ liệu nạp và truy vấn kế hoạch vận chuyển từ file CSV và bộ nhớ."""

    def __init__(self, csv_path: str):
        """Khởi tạo Shipping Repository và nạp dữ liệu từ tệp CSV.

        Args:
            csv_path (str): Đường dẫn tuyệt đối hoặc tương đối tới tệp CSV kế hoạch vận chuyển.
        """
        self.csv_path = csv_path
        self._shipping_map: Dict[str, ShippingOrder] = {}
        self._auto_mock: bool = False
        self.reload()

    def enable_auto_mock(self, enabled: bool = True) -> None:
        """Bật hoặc tắt chế độ tự động tạo kế hoạch shipping giả lập (Auto-Mock Shipping).

        Khi bật, bất kỳ số container hợp lệ nào chưa có trong file kế hoạch
        sẽ tự động được cấp một đơn vận chuyển mẫu tương ứng, giúp kiểm thử chủ động linh hoạt.

        Args:
            enabled (bool, optional): Trạng thái bật (True) hoặc tắt (False). Mặc định là True.
        """
        self._auto_mock = enabled

    def is_auto_mock_enabled(self) -> bool:
        """Kiểm tra xem chế độ tự động tạo shipping giả lập có đang được bật hay không.

        Returns:
            bool: True nếu đang bật auto-mock, ngược lại False.
        """
        return self._auto_mock

    def reload(self) -> None:
        """Đọc và nạp lại toàn bộ dữ liệu từ tệp CSV vào từ điển bộ nhớ `_shipping_map`.

        Mỗi dòng lệnh vận chuyển được chuẩn hóa số container và ánh xạ theo key là số container.
        """
        self._shipping_map.clear()
        if not os.path.exists(self.csv_path):
            return

        with open(self.csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_cont = row.get("so_container", "")
                cont = clean_container(raw_cont)
                if not cont:
                    continue

                order = ShippingOrder(
                    shipping_id=row.get("shipping_id", "").strip(),
                    ngay_thuc_hien=row.get("ngay_thuc_hien", "").strip(),
                    trang_thai=row.get("trang_thai", "").strip(),
                    loai_lenh=row.get("loai_lenh", "").strip(),
                    so_container=cont,
                    kich_thuoc_cont=row.get("kich_thuoc_cont", "").strip(),
                    bien_so_xe=row.get("bien_so_xe", "").strip(),
                    tai_xe=row.get("tai_xe", "").strip(),
                    nha_xe_id=row.get("nha_xe_id", "").strip(),
                    khach_hang_id=row.get("khach_hang_id", "").strip(),
                    ten_khach_hang=row.get("ten_khach_hang", "").strip(),
                    kho_tra=row.get("kho_tra", "").strip(),
                    dia_chi_kho_tra=row.get("dia_chi_kho_tra", "").strip(),
                    zalo_group_id_khach=row.get("zalo_group_id_khach", "").strip(),
                )
                self._shipping_map[cont] = order

    def add_order(self, order: ShippingOrder) -> None:
        """Thêm hoặc cập nhật một đơn vận chuyển trực tiếp vào bộ nhớ tạm.

        Args:
            order (ShippingOrder): Thực thể lệnh vận chuyển cần lưu trữ.
        """
        cont = clean_container(order.so_container)
        if cont:
            self._shipping_map[cont] = order

    def create_mock_order(
        self,
        cont: str,
        carrier_id: str = "NX01",
        khach_hang_id: str = "KH_MOCK",
        ten_khach_hang: str = "Công ty TNHH Khách Hàng Thử Nghiệm (MOCK)",
        kho_tra: str = "Kho Thử Nghiệm VSICO",
        dia_chi_kho_tra: str = "KCN Thử Nghiệm, Hà Nội",
        kich_thuoc_cont: str = "40DC",
        zalo_group_id_khach: str = "3001000000000000001",
    ) -> ShippingOrder:
        """Tự động tạo và lưu trữ một đơn vận chuyển mẫu cho container chưa có kế hoạch.

        Args:
            cont (str): Số hiệu container cần tạo đơn giả lập.
            carrier_id (str, optional): Mã định danh nhà xe. Mặc định là 'NX01'.
            khach_hang_id (str, optional): Mã khách hàng. Mặc định là 'KH_MOCK'.
            ten_khach_hang (str, optional): Tên công ty khách hàng. Mặc định là 'Công ty TNHH Khách Hàng Thử Nghiệm (MOCK)'.
            kho_tra (str, optional): Tên kho trả hàng. Mặc định là 'Kho Thử Nghiệm VSICO'.
            dia_chi_kho_tra (str, optional): Địa chỉ kho trả. Mặc định là 'KCN Thử Nghiệm, Hà Nội'.
            kich_thuoc_cont (str, optional): Kích thước vỏ cont. Mặc định là '40DC'.
            zalo_group_id_khach (str, optional): Mã nhóm chat Zalo nhận thông báo. Mặc định là '3001000000000000001'.

        Returns:
            ShippingOrder: Thực thể lệnh vận chuyển mẫu vừa được sinh và lưu vào danh mục.
        """
        clean = clean_container(cont) or cont.strip().upper()
        mock_id = f"SHIP_MOCK_{clean}"
        order = ShippingOrder(
            shipping_id=mock_id,
            ngay_thuc_hien=datetime.now(TZ_VN).strftime("%d/%m/%Y"),
            trang_thai="Chờ thực hiện",
            loai_lenh="Trả",
            so_container=clean,
            kich_thuoc_cont=kich_thuoc_cont,
            bien_so_xe="",
            tai_xe="",
            nha_xe_id=carrier_id,
            khach_hang_id=khach_hang_id,
            ten_khach_hang=ten_khach_hang,
            kho_tra=kho_tra,
            dia_chi_kho_tra=dia_chi_kho_tra,
            zalo_group_id_khach=zalo_group_id_khach,
        )
        self._shipping_map[clean] = order
        return order

    def get_by_container(self, cont: str, carrier_id: Optional[str] = None) -> Optional[ShippingOrder]:
        """Tra cứu lệnh vận chuyển dựa theo số hiệu container.

        Nếu chế độ Auto-Mock đang bật và container chưa có trong hệ thống,
        tự động sinh một đơn mẫu mới và trả về kết quả.

        Args:
            cont (str): Số container cần tra cứu.
            carrier_id (Optional[str], optional): Mã nhà xe gửi tin (dùng để gán khi sinh mock). Mặc định là None.

        Returns:
            Optional[ShippingOrder]: Lệnh vận chuyển nếu tìm thấy hoặc tự sinh, ngược lại None.
        """
        if not cont:
            return None
        clean = clean_container(cont)
        if not clean:
            return None

        if clean not in self._shipping_map and self._auto_mock:
            return self.create_mock_order(clean, carrier_id=carrier_id or "NX01")

        return self._shipping_map.get(clean)

    def get_all(self) -> Dict[str, ShippingOrder]:
        """Lấy toàn bộ danh bạ các lệnh vận chuyển đang có trong hệ thống.

        Returns:
            Dict[str, ShippingOrder]: Từ điển ánh xạ từ số container sang đối tượng ShippingOrder.
        """
        return self._shipping_map
