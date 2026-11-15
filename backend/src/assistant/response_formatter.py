"""Định dạng phản hồi hữu hạn cho điện thoại, không suy diễn tiến độ thực tế."""

from src.infrastructure.models import ContainerJob, TransportPlan

from .schemas import AssistantReply

NOT_FOUND = (
    "Hiện tại VSICO chưa ghi nhận thông tin điều xe cho mã tra cứu Quý khách cung cấp "
    "trong phạm vi tuyến phụ trách của nhóm. Quý khách vui lòng kiểm tra lại mã container/biển số "
    "hoặc liên hệ bộ phận Điều hành vận tải để được hỗ trợ."
)
LIMIT = 20


def plan_line(p: TransportPlan) -> str:
    """Hiển thị giá trị kế hoạch, chưa coi giờ hẹn là thời điểm xe thực đến."""
    kind = (
        "Đóng"
        if p.order_type.lower() in ("dong", "load", "lo")
        else "Trả"
        if p.order_type.lower() in ("tra", "return", "ro")
        else p.order_type
    )
    return (
        f"{p.order_code or p.container_no or p.booking_no or '#' + str(p.id)} | {kind} | "
        f"{p.warehouse_name or p.delivery_address or 'Chưa có kho'} | "
        f"{p.required_time or p.eta or 'Chưa có giờ'} | "
        f"{p.planned_truck_plate or 'Chưa có xe'} | {p.driver_name or 'Chưa có tài xế'}"
    )


def format_plans(plans: list[TransportPlan], title: str, detail: bool = False) -> AssistantReply:
    """Liệt kê tối đa 20 dòng và nêu rõ khi kết quả còn tiếp."""
    if not plans:
        return AssistantReply(text=NOT_FOUND)
    rows = [f"{i}. {plan_line(p)}" for i, p in enumerate(plans[:LIMIT], 1)]
    if detail:
        for p in plans[:3]:
            rows.append(
                f"{p.order_code or p.container_no or p.id}: Cont {p.container_no or 'Chưa có'}; "
                f"Seal {p.seal_no or 'Chưa có'}; SĐT {p.driver_phone or 'Chưa có'}; "
                f"Booking {p.booking_no or '—'}; B/L {p.bill_of_lading_no or '—'}"
            )
    if len(plans) > LIMIT:
        rows.append("Còn kết quả khác; vui lòng lọc thêm mã lệnh/kho hoặc xem trên Web.")
    rows.append("Giờ hiển thị là giờ dự kiến theo kế hoạch, chưa xác nhận xe thực đến.")
    return AssistantReply(
        text=title + "\n" + "\n".join(rows), plan_ids=[str(p.id) for p in plans[:LIMIT]]
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
