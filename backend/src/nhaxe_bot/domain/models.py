"""Module Mô Hình Dữ Liệu Miền Nghiệp Vụ (Pure Domain Models).

Chứa các Data Class đại diện cho thực thể cốt lõi trong nghiệp vụ vận tải container
của VSICO. Tuyệt đối không phụ thuộc vào Database, Web framework, hoặc Zalo SDK.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from .enums import OrderType, TripStatus, SendStatus


@dataclass
class Vehicle:
    """Thực thể đại diện cho một xe chở container được bóc tách từ tin nhắn.

    Attributes:
        xe_index (int): Thứ tự của xe trong trường hợp 1 tin nhắn chứa nhiều xe (bắt đầu từ 1).
        cont (Optional[str]): Số container (11 ký tự chuẩn ISO 6346, ví dụ: 'VSIU7399796').
        seal (Optional[str]): Số niêm phong/chì do hải quan hoặc hãng tàu cấp.
        bien_so (Optional[str]): Biển kiểm soát xe đầu kéo hoặc rơ-moóc đã chuẩn hóa.
        tai_xe (Optional[str]): Họ tên người lái xe nhận chuyến.
        sdt (Optional[str]): Số điện thoại liên lạc của tài xế (10 chữ số chuẩn VN).
        gio_den (Optional[str]): Thời gian dự kiến xe có mặt tại kho khách hàng.
        loai_hint (str): Hướng vận chuyển ('tra' hoặc 'dong').
        warnings (List[str]): Danh sách các mã cảnh báo phát sinh trong quá trình validate.
        status (str): Trạng thái hợp lệ nội bộ ('ready', 'wait_supplement', 'need_admin').
        in_shipping (Optional[bool]): Cờ đánh dấu container có nằm trong kế hoạch Shipping hay không.
        shipping_id (Optional[str]): Mã định danh đơn hàng vận chuyển từ bảng Shipping (ví dụ: 'DH00000001').
        khach_hang_id (Optional[str]): Mã khách hàng nhận hàng (ví dụ: 'KH001').
        ten_khach_hang (Optional[str]): Tên đầy đủ của khách hàng (ví dụ: 'Dược Phẩm Á Châu').
        kho_tra (Optional[str]): Tên kho nhận container.
        dia_chi_kho_tra (Optional[str]): Địa chỉ chi tiết của kho nhận hàng.
        zalo_group_id_gui (Optional[str]): Mã nhóm Zalo GMF của khách hàng dùng để gửi tin outbound.
        send_status (Optional[str]): Trạng thái gửi tin ('SENT_DRY_RUN', 'HOLD_WAIT_SUPPLEMENT', ...).
        notification_text (Optional[str]): Nội dung tin nhắn hoàn chỉnh đã render qua template gửi khách.
        reply_to_carrier (Optional[str]): Nội dung tin nhắn phản hồi yêu cầu nhà xe bổ sung thông tin.
        admin_alert (bool): Cờ bật chuông cảnh báo cho Điều hành Vận tải (ĐHVT) khi có sự cố.
        admin_message (Optional[str]): Nội dung giải thích chi tiết lý do cần ĐHVT can thiệp.
        parser_source (str): Nguồn bóc tách dữ liệu ('rule' cho regex hoặc 'llm' cho AI fallback).
    """

    xe_index: int = 1
    cont: Optional[str] = None
    seal: Optional[str] = None
    bien_so: Optional[str] = None
    tai_xe: Optional[str] = None
    sdt: Optional[str] = None
    gio_den: Optional[str] = None
    loai_hint: str = "tra"
    warnings: List[str] = field(default_factory=list)
    status: str = "ready"
    in_shipping: Optional[bool] = None
    shipping_id: Optional[str] = None
    khach_hang_id: Optional[str] = None
    ten_khach_hang: Optional[str] = None
    kho_tra: Optional[str] = None
    dia_chi_kho_tra: Optional[str] = None
    zalo_group_id_gui: Optional[str] = None
    send_status: Optional[str] = None
    notification_text: Optional[str] = None
    reply_to_carrier: Optional[str] = None
    admin_alert: bool = False
    admin_message: Optional[str] = None
    parser_source: str = "rule"


@dataclass
class ShippingOrder:
    """Thực thể đại diện cho một dòng lệnh vận chuyển trong kế hoạch của VSICO.

    Attributes:
        shipping_id (str): Mã định danh duy nhất của đơn hàng điều phối.
        ngay_thuc_hien (str): Ngày kế hoạch thực hiện chuyến xe.
        trang_thai (str): Trạng thái lệnh trên phần mềm TMS.
        loai_lenh (str): Loại lệnh vận chuyển ('Trả hàng', 'Đóng hàng').
        so_container (str): Số hiệu container được phân bổ.
        kich_thuoc_cont (str): Loại kích thước vỏ container ('20DC', '40HC', ...).
        bien_so_xe (str): Biển số xe dự kiến trong kế hoạch ban đầu.
        tai_xe (str): Họ tên tài xế dự kiến ban đầu.
        nha_xe_id (str): Mã nhà xe được chỉ định chạy cuốc này (ví dụ: 'NX01').
        khach_hang_id (str): Mã khách hàng chủ hàng.
        ten_khach_hang (str): Tên doanh nghiệp khách hàng.
        kho_tra (str): Tên điểm giao/nhận container.
        dia_chi_kho_tra (str): Địa chỉ cụ thể của kho bãi.
        zalo_group_id_khach (str): Mã nhóm Zalo trao đổi thông tin với khách hàng.
    """

    shipping_id: str
    ngay_thuc_hien: str
    trang_thai: str
    loai_lenh: str
    so_container: str
    kich_thuoc_cont: str
    bien_so_xe: str
    tai_xe: str
    nha_xe_id: str
    khach_hang_id: str
    ten_khach_hang: str
    kho_tra: str
    dia_chi_kho_tra: str
    zalo_group_id_khach: str


@dataclass
class SentTrip:
    """Thực thể lưu vết một chuyến xe đã duyệt gửi thông báo khách hàng (Snapshot/Version).

    Attributes:
        carrier_id (str): Mã nhà xe thực hiện vận chuyển.
        cont (str): Số container của chuyến xe.
        shipping_id (Optional[str]): Mã lệnh vận chuyển tương ứng nếu khớp được bảng Shipping.
        xe_data (Dict[str, Any]): Bản sao dữ liệu chi tiết của xe tại thời điểm lưu.
        notification_text (Optional[str]): Nội dung thông báo đã gửi cho khách hàng.
        sent_at (str): Thời điểm ghi nhận gửi thông báo (định dạng ISO 8601).
        version (int): Số phiên bản chuyến xe (tự động tăng từ 1 lên 2, 3 khi có cập nhật).
    """

    carrier_id: str
    cont: str
    shipping_id: Optional[str]
    xe_data: Dict[str, Any]
    notification_text: Optional[str]
    sent_at: str
    version: int = 1


@dataclass
class Carrier:
    """Thực thể đại diện cho một đơn vị vận tải (nhà xe đối tác).

    Attributes:
        carrier_id (str): Mã định danh nhà xe (ví dụ: 'NX01', 'NX02').
        name (str): Tên thương mại đầy đủ của đơn vị vận tải.
        group_id (str): Mã nhóm Zalo GMF độc quyền của nhà xe đó.
        sender_ids (List[str]): Danh sách mã người dùng Zalo được ủy quyền gửi thông tin điều xe.
    """

    carrier_id: str
    name: str
    group_id: str
    sender_ids: List[str] = field(default_factory=list)
