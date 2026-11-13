"""Module Định Nghĩa Schema Cơ Sở Dữ Liệu MySQL (SQLAlchemy 2.0 ORM Models).

Thiết kế theo 5 nguyên tắc cốt lõi của dự án Bot Zalo OA - VSICO:
1. Tin gốc không bị ghi đè: Lưu nguyên bản tại `zalo_messages` và lịch sử AI tại `extraction_runs`.
2. Tách biệt Tin nhắn -> Xe (`truck_records`) -> Container (`container_jobs`) vì 1 tin có nhiều xe, 1 xe nhiều cont.
3. Mỗi container có trạng thái kiểm tra, định tuyến và đồng bộ TMS độc lập.
4. Không chắc khách hoặc nhóm nhận thì đưa vào `review_cases` (chờ duyệt), tuyệt đối không gửi nhầm khách.
5. Dữ liệu danh mục (`customers`, `warehouses`) là bản đồng bộ từ PM TMS; mọi cập nhật đẩy qua API `be-tms`.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    """Trả về thời điểm hiện tại theo múi giờ máy chủ (GMT+7 Việt Nam) để đồng bộ với sent_at."""
    return datetime.now()


class ZaloGroup(Base):
    """Bảng 9: `zalo_groups` — Danh mục nhóm Zalo (Nhóm nhà xe, Nhóm khách, Nhóm nội bộ ĐHVT)."""

    __tablename__ = "zalo_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    zalo_group_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    group_role: Mapped[str] = mapped_column(String(32), nullable=False, default="SOURCE")
    carrier_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    carrier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    send_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="AUTO")
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class User(Base):
    """Bảng 3: `users` — Quản lý tài khoản nhân viên nội bộ (ĐHVT và Admin)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="DHVT", index=True)
    zalo_user_id: Mapped[Optional[str]] = mapped_column(String(128), unique=False, nullable=True, index=True)
    zalo_info_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("zalo_groups.id"), nullable=True, index=True)
    tms_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    forwarder_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=utc_now
    )


class Carrier(Base):
    """Bảng 4: `carriers` — Danh mục Nhà xe / Đội xe chuẩn đồng bộ từ phần mềm TMS."""

    __tablename__ = "carriers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tms_carrier_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tax_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Customer(Base):
    """Bảng 5: `customers` — Danh mục khách hàng chuẩn đồng bộ từ PM TMS."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tms_customer_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Warehouse(Base):
    """Bảng 6: `warehouses` — Danh mục kho đóng/trả hàng đồng bộ từ PM TMS."""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tms_warehouse_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("customers.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerAlias(Base):
    """Bảng 7: `customer_aliases` — Tên gọi tắt của khách hàng."""

    __tablename__ = "customer_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class WarehouseAlias(Base):
    """Bảng 8: `warehouse_aliases` — Tên gọi tắt của kho."""

    __tablename__ = "warehouse_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("warehouses.id"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TransportPlan(Base):
    """Bảng phụ trợ Mục 7.1: `transport_plans` — Kế hoạch vận chuyển hằng ngày (theo mẫu Kế hoạch điều vận)."""

    __tablename__ = "transport_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    carrier_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("carriers.id"), nullable=True, index=True)
    driver_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    driver_phone: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    tms_sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_STARTED", server_default="NOT_STARTED")
    plan_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    stt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    route_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cargo_io_type: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="Phân loại hàng: 'I' (Nhập) hoặc 'X' (Xuất)"
    )
    order_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, comment="'dong' (Đóng hàng/Xuất) hoặc 'tra' (Trả hàng/Nhập/Mở cont)"
    )
    container_no: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    seal_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    container_size: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, comment="'20' hoặc '40'")
    cargo_weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True, comment="Tải trọng cả vỏ (tấn)"
    )
    required_time: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="Yêu cầu thời gian có mặt: '7h', '9h'..."
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("customers.id"), nullable=True
    )
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("warehouses.id"), nullable=True
    )
    cargo_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Loại hàng hóa: Mỳ, Bột ngọt...")
    vessel_voyage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="Chuyến tàu/Số: Prosper 2633N...")
    empty_depot: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Bãi nâng/ hạ vỏ")
    full_depot: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Bãi nâng/hạ hàng: PTSC...")
    estimated_drop_time: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="Giờ dự kiến hạ hàng")
    fleet_partner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Đội xe: Tuấn Hưng, Phương Anh HP...")
    planned_truck_plate: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="Số xe kế hoạch: 29C-445.41...")
    delivery_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Địa chỉ đóng/ trả hàng")
    group_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, default="6469608867469758994", comment="Group ID Zalo nhận thông báo"
    )
    operator_staff: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="Cán bộ giao nhận")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Ghi chú / Chi chú")
    extra_fee_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Phát sinh")

    # Các trường tương thích ngược với code cũ:
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    carrier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    eta: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    combine_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=utc_now
    )


class ZaloMessage(Base):
    """Bảng 1: `zalo_messages` — Tin nhắn đầu vào nguyên bản nhận từ Webhook (zca-js / Zalo OA)."""

    __tablename__ = "zalo_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    zalo_message_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    group_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quote_msg_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="RECEIVED", index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    zalo_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(back_populates="message")
    truck_records: Mapped[list["TruckRecord"]] = relationship(back_populates="message")
    container_jobs: Mapped[list["ContainerJob"]] = relationship(back_populates="message")
    review_cases: Mapped[list["ReviewCase"]] = relationship(back_populates="message")
    bot_replies: Mapped[list["BotReply"]] = relationship(back_populates="message")


class ExtractionRun(Base):
    """Bảng 2: `extraction_runs` — Lịch sử các lần chạy bóc tách dữ liệu (AI hoặc Rule)."""

    __tablename__ = "extraction_runs"
    __table_args__ = (Index("ix_extraction_runs_msg_started", "message_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    message: Mapped["ZaloMessage"] = relationship(back_populates="extraction_runs")


class TruckRecord(Base):
    """Bảng 3: `truck_records` — Thông tin lượt xe (biển số đầu kéo, mooc, tài xế, SĐT)."""

    __tablename__ = "truck_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=False, index=True
    )
    extraction_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("extraction_runs.id"), nullable=True
    )
    truck_plate: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    trailer_plate: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    driver_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    driver_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    raw_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    message: Mapped["ZaloMessage"] = relationship(back_populates="truck_records")
    container_jobs: Mapped[list["ContainerJob"]] = relationship(back_populates="truck_record")


class ContainerJob(Base):
    """Bảng 4: `container_jobs` — Bảng nghiệp vụ trung tâm quản lý từng Container."""

    __tablename__ = "container_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=False, index=True
    )
    truck_record_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("truck_records.id"), nullable=True, index=True
    )
    parent_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("container_jobs.id"), nullable=True
    )
    is_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    line_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    line_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    container_no: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    container_size: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    seal_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    order_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    warehouse_hint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_hint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("customers.id"), nullable=True, index=True
    )
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("warehouses.id"), nullable=True, index=True
    )
    match_method: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ai_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3), nullable=True)
    estimated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    container_check_digit_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    routing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    tms_sync_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="NOT_STARTED"
    )

    raw_fields: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    message: Mapped["ZaloMessage"] = relationship(back_populates="container_jobs")
    truck_record: Mapped[Optional["TruckRecord"]] = relationship(back_populates="container_jobs")


class RouteMap(Base):
    """Bảng 10: `route_maps` — Bảng ánh xạ (Khách hàng + Kho + Loại lệnh -> Nhóm Zalo nhận)."""

    __tablename__ = "route_maps"
    __table_args__ = (
        Index("ix_route_maps_lookup", "customer_id", "warehouse_id", "order_type", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id"), nullable=False)
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("warehouses.id"), nullable=True
    )
    order_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    zalo_group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_groups.id"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ReviewCase(Base):
    """Bảng 11: `review_cases` — Hàng đợi duyệt thủ công dành cho Điều hành vận tải (ĐHVT)."""

    __tablename__ = "review_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=False, index=True
    )
    container_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("container_jobs.id"), nullable=True, index=True
    )
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", index=True
    )
    assigned_to: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolution: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    message: Mapped["ZaloMessage"] = relationship(back_populates="review_cases")


class BotReply(Base):
    """Bảng phụ trợ Mục 5 & 6: `bot_replies` — Theo dõi tin bot nhắc lỗi nhà xe và hạn sửa 30 phút."""

    __tablename__ = "bot_replies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(String(128), nullable=False)
    zalo_msg_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    reply_text: Mapped[Text] = mapped_column(Text, nullable=False)
    fix_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    message: Mapped["ZaloMessage"] = relationship(back_populates="bot_replies")


class OutboundMessage(Base):
    """Bảng 12: `outbound_messages` — Tin nhắn thông báo xe gửi tới nhóm Zalo của khách hàng."""

    __tablename__ = "outbound_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_groups.id"), nullable=False, index=True
    )
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    message_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="initial")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    review_zalo_msg_id: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, nullable=True
    )
    approved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING_APPROVAL", index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zalo_message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    target_group: Mapped[Optional["ZaloGroup"]] = relationship()
    items: Mapped[list["OutboundMessageItem"]] = relationship(
        back_populates="outbound_message", cascade="all, delete-orphan"
    )


class OutboundMessageItem(Base):
    """Bảng 13: `outbound_message_items` — Bảng trung gian gắn các Container vào một tin gửi."""

    __tablename__ = "outbound_message_items"

    outbound_message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("outbound_messages.id"), primary_key=True
    )
    container_job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("container_jobs.id"), primary_key=True
    )

    outbound_message: Mapped["OutboundMessage"] = relationship(back_populates="items")
    container_job: Mapped[Optional["ContainerJob"]] = relationship()


class TmsSyncLog(Base):
    """Bảng 14: `tms_sync_logs` — Nhật ký mọi lần gọi API tích hợp sang `be-tms`."""

    __tablename__ = "tms_sync_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    container_job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("container_jobs.id"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    response_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ActivityLog(Base):
    """Bảng 15: `activity_logs` — Nhật ký thao tác của người dùng và hệ thống."""

    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class FileRecord(Base):
    """Bảng 17: `files` — Lưu thông tin metadata file và đường dẫn đối tượng trong MinIO S3."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=True, index=True
    )
    storage_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageDraft(Base):
    """Bảng 18: `message_drafts` — Bản nháp gom các tin rời rạc của cùng một người gửi trong một nhóm."""

    __tablename__ = "message_drafts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    zalo_info_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_groups.id"), nullable=False, index=True
    )
    carrier_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("carriers.id"), nullable=True, index=True
    )
    group_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", index=True)
    entities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    first_message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=False
    )
    last_message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("zalo_messages.id"), nullable=False
    )
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    flushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
