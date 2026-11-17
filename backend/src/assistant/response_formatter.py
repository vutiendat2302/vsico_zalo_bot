"""Định dạng phản hồi hữu hạn cho điện thoại, không suy diễn tiến độ thực tế."""

from src.infrastructure.models import ContainerJob, TransportPlan

from .schemas import AssistantReply

NOT_FOUND = (
    "Hiện tại VSICO chưa ghi nhận thông tin điều xe cho mã tra cứu Quý khách cung cấp "
    "trong phạm vi tuyến phụ trách của nhóm. Quý khách vui lòng kiểm tra lại mã container/biển số "
    "hoặc liên hệ bộ phận Điều hành vận tải để được hỗ trợ."
)
LIMIT = 20
MAX_ZALO_TEXT_CHARS = 1900


def plan_line(p: TransportPlan) -> str:
    """Hiển thị giá trị kế hoạch, chưa coi giờ hẹn là thời điểm xe thực đến."""
    kind = (
        "Đóng"
        if p.order_type.lower() in ("dong", "load", "lo")
        else "Trả"
        if p.order_type.lower() in ("tra", "return", "ro")
        else p.order_type
    )
    vehicle_str = p.planned_truck_plate or "Chưa có xe"
    if p.planned_trailer_plate:
        vehicle_str = f"{vehicle_str} / Mooc {p.planned_trailer_plate}"
    return (
        f"{p.order_code or p.container_no or p.booking_no or p.warehouse_name or p.customer_name or 'Chuyến'} | {kind} | "
        f"{p.warehouse_name or p.delivery_address or 'Chưa có kho'} | "
        f"{p.required_time or p.eta or 'Chưa có giờ'} | "
        f"{vehicle_str} | {p.driver_name or 'Chưa có tài xế'}"
    )


def format_plans(plans: list[TransportPlan], title: str, detail: bool = False) -> AssistantReply:
    """Liệt kê tối đa 20 dòng và giữ tổng độ dài dưới ngưỡng 2000 ký tự của Zalo OA."""
    if not plans:
        return AssistantReply(text=NOT_FOUND)
    note_more = "Còn kết quả khác; vui lòng lọc thêm mã lệnh/kho hoặc xem trên Web."
    # Dự phòng chỗ cho phần ghi chú khi vượt ngưỡng để tổng nội dung không vượt 1900 ký tự.
    reserved = len(title) + len(note_more) + 4
    rows: list[str] = []
    used = reserved
    included_plans: list[TransportPlan] = []
    truncated = len(plans) > LIMIT

    for i, p in enumerate(plans[:LIMIT], 1):
        line = f"{i}. {plan_line(p)}"
        if rows and used + len(line) + 1 > MAX_ZALO_TEXT_CHARS:
            truncated = True
            break
        rows.append(line)
        included_plans.append(p)
        used += len(line) + 1

    if detail:
        for p in included_plans[:3]:
            dline = (
                f"{p.order_code or p.container_no or p.booking_no or p.warehouse_name or 'Chuyến'}: Cont {p.container_no or 'Chưa có'}; "
                f"Seal {p.seal_no or 'Chưa có'}; SĐT {p.driver_phone or 'Chưa có'}; "
                f"Booking {p.booking_no or '—'}; B/L {p.bill_of_lading_no or '—'}"
            )
            if used + len(dline) + 1 > MAX_ZALO_TEXT_CHARS:
                break
            rows.append(dline)
            used += len(dline) + 1

    if truncated:
        rows.append(note_more)
    return AssistantReply(
        text=title + "\n" + "\n".join(rows),
        plan_ids=[str(p.id) for p in included_plans],
    )


def customer_job_line(job: ContainerJob) -> str:
    """Định dạng ngắn gọn thông tin xe/cont từ lượt báo xe cho nhóm khách hàng (ẩn trạng thái kỹ thuật nội bộ)."""
    truck = job.truck_record
    phone = (truck.driver_phone if truck else None) or "Chưa có"
    seal = job.seal_no or "Chưa có"
    return (
        f"Cont {job.container_no or 'Chưa có'} | "
        f"Xe {truck.truck_plate if truck else 'Chưa có'} | "
        f"Tài xế {truck.driver_name if truck else 'Chưa có'} | "
        f"SĐT {phone} | Seal {seal}"
    )


def job_line(job: ContainerJob, mask_phone: bool = False) -> str:
    """Tách dữ liệu nhà xe báo khỏi dữ liệu kế hoạch, giữ trạng thái kiểm tra thật."""
    truck = job.truck_record
    phone = (truck.driver_phone if truck else None) or "Chưa có"
    if mask_phone and len(phone) == 10 and phone.isdigit():
        phone = phone[:4] + "xxxx" + phone[-2:]
    return (
        f"Nhà xe báo {job.container_no or 'Chưa có cont'}: "
        f"{truck.truck_plate if truck else 'Chưa có xe'}; "
        f"{truck.driver_name if truck else 'Chưa có tài xế'}; SĐT {phone}; "
        f"kiểm tra {job.validation_status}; định tuyến {job.routing_status}."
    )
