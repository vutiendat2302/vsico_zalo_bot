"""Định dạng phản hồi hữu hạn cho điện thoại, không suy diễn tiến độ thực tế."""

from src.infrastructure.models import ContainerJob, TransportPlan

from .schemas import AssistantReply

NOT_FOUND = (
    "[VSICO] - 🔍 Hiện chưa tìm thấy thông tin điều xe phù hợp với mã tra cứu trong phạm vi tuyến phụ trách.\n\n"
    "Anh/chị vui lòng kiểm tra lại mã lệnh, số container hoặc ngày cần xem nhé."
)
LIMIT = 200
MAX_ZALO_TEXT_CHARS = 1900


def paginate_zalo_text(
    *,
    header_text: str,
    item_lines: list[str],
    continuation_title: str,
    footer_text: str = "",
    max_chars: int = MAX_ZALO_TEXT_CHARS,
) -> list[str]:
    """Chia nội dung dài thành nhiều tin nhắn Zalo hợp lệ (<= max_chars/tin) theo ranh giới dòng, không cắt sót lệnh."""
    clean_header = (header_text or "").rstrip("\n")
    clean_footer = (footer_text or "").strip("\n")
    if not item_lines:
        body = f"{clean_header}\n\n{clean_footer}".strip() if clean_footer else clean_header
        return [body[:max_chars]] if body else [""]

    single_parts = [clean_header, "\n".join(item_lines)]
    if clean_footer:
        single_parts.append(clean_footer)
    single_candidate = "\n".join(p for p in single_parts if p)
    if len(single_candidate) <= max_chars:
        return [single_candidate]

    # Chia theo nhóm dòng sao cho mỗi tin nhắn nằm gọn trong ngưỡng Zalo OA (trừa chỗ cho nhãn Phần k/N)
    cont_overhead = len(continuation_title) + 28
    footer_overhead = (len(clean_footer) + 2) if clean_footer else 0
    chunks_lines: list[list[str]] = []

    current_lines: list[str] = []
    first_budget = max(250, max_chars - len(clean_header) - 24)
    next_budget = max(250, max_chars - cont_overhead)
    current_budget = first_budget
    current_len = 0

    for line in item_lines:
        safe_line = line[: max(200, next_budget - 10)]
        add_len = len(safe_line) + (1 if current_lines else 0)
        if current_lines and current_len + add_len > current_budget:
            chunks_lines.append(current_lines)
            current_lines = [safe_line]
            current_budget = next_budget
            current_len = len(safe_line)
        else:
            current_lines.append(safe_line)
            current_len += add_len

    if current_lines:
        chunks_lines.append(current_lines)

    # Nếu tin cuối cộng footer bị vượt giới hạn, tách các dòng cuối sang 1 phần mới để giữ footer trọn vẹn
    if clean_footer and chunks_lines:
        last_body = "\n".join(chunks_lines[-1])
        last_prefix_len = (len(clean_header) + 20) if len(chunks_lines) == 1 else cont_overhead
        if last_prefix_len + len(last_body) + footer_overhead > max_chars and len(chunks_lines[-1]) > 1:
            overflow: list[str] = []
            while len(chunks_lines[-1]) > 1:
                overflow.insert(0, chunks_lines[-1].pop())
                if last_prefix_len + len("\n".join(chunks_lines[-1])) <= max_chars - 10:
                    break
            if overflow:
                chunks_lines.append(overflow)

    total_parts = len(chunks_lines)
    messages: list[str] = []
    for idx, lines_batch in enumerate(chunks_lines, start=1):
        is_first = idx == 1
        is_last = idx == total_parts
        if is_first:
            first_head = clean_header
            if total_parts > 1:
                first_lines = first_head.split("\n", 1)
                if len(first_lines) == 2:
                    first_head = f"{first_lines[0]} (Phần 1/{total_parts})\n{first_lines[1]}"
                else:
                    first_head = f"{first_head} (Phần 1/{total_parts})"
            msg = f"{first_head}\n" + "\n".join(lines_batch)
        else:
            msg = f"{continuation_title} (Phần {idx}/{total_parts})\n\n" + "\n".join(lines_batch)
        if is_last and clean_footer:
            if len(msg) + len(clean_footer) + 2 <= max_chars:
                msg = f"{msg}\n\n{clean_footer}"
            else:
                messages.append(msg[:max_chars])
                messages.append(clean_footer[:max_chars])
                continue
        messages.append(msg[:max_chars])
    return messages


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
    """Liệt kê đầy đủ danh sách kế hoạch (tự động tách nhiều tin Zalo nếu vượt ngưỡng 1900 ký tự)."""
    if not plans:
        return AssistantReply(text=NOT_FOUND)
    capped_plans = plans[:LIMIT]
    rows: list[str] = [f"{i}. {plan_line(p)}" for i, p in enumerate(capped_plans, 1)]

    if detail:
        for p in capped_plans[:3]:
            rows.append(
                f"{p.order_code or p.container_no or p.booking_no or p.warehouse_name or 'Chuyến'}: Cont {p.container_no or 'Chưa có'}; "
                f"Seal {p.seal_no or 'Chưa có'}; SĐT {p.driver_phone or 'Chưa có'}; "
                f"Booking {p.booking_no or '—'}; B/L {p.bill_of_lading_no or '—'}"
            )

    footer = (
        f"Hiển thị {LIMIT}/{len(plans)} lệnh đầu tiên; vui lòng lọc thêm theo tỉnh/kho để xem tiếp."
        if len(plans) > LIMIT
        else ""
    )
    parts = paginate_zalo_text(
        header_text=title,
        item_lines=rows,
        continuation_title=title,
        footer_text=footer,
        max_chars=MAX_ZALO_TEXT_CHARS,
    )
    return AssistantReply(
        text=parts[0],
        extra_texts=parts[1:],
        plan_ids=[str(p.id) for p in capped_plans[:20]],
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
