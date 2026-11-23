/**
 * Hàm tiện ích kết hợp class name Tailwind CSS.
 * Không thêm thư viện ngoài, tối ưu hiệu năng và giữ kích thước bundle tối thiểu.
 */
export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(" ");
}

/**
 * Lấy ngày hôm nay theo múi giờ Việt Nam (`Asia/Ho_Chi_Minh`) định dạng `YYYY-MM-DD`.
 */
export function todayVnIso(): string {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Ho_Chi_Minh",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

/**
 * Định dạng thời điểm đồng bộ TMS gần nhất sang giờ:phút (`HH:mm`).
 */
export function formatSyncTime(iso?: string | null): string {
  if (!iso) return "Chưa chạy";
  try {
    return new Date(iso).toLocaleTimeString("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

/**
 * Định dạng mốc thời gian ISO sang chuẩn 24 giờ (`DD/MM/YYYY HH:mm`) theo múi giờ Việt Nam.
 */
export function formatDateTime24h(iso?: string | null): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) {
    return iso.slice(0, 16).replace("T", " ");
  }
  const parts = new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(dt);
  const get = (t: string) => parts.find((p) => p.type === t)?.value || "00";
  return `${get("day")}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")}`;
}

export interface FriendlyStatusMeta {
  label: string;
  dotClass: string;
  textClass: string;
}

/**
 * Chuyển mã trạng thái xử lý tin nhắn sang nhãn tiếng Việt thân thiện và màu chấm trạng thái.
 */
export function getMessageStatusMeta(status?: string | null): FriendlyStatusMeta {
  switch ((status || "").toLowerCase()) {
    case "processed":
      return {
        label: "Thành công",
        dotClass: "bg-emerald-500",
        textClass: "text-emerald-700",
      };
    case "needs_review":
      return {
        label: "Chờ duyệt",
        dotClass: "bg-purple-600",
        textClass: "text-purple-700",
      };
    case "cancelled":
      return {
        label: "Đã hủy",
        dotClass: "bg-rose-500",
        textClass: "text-rose-700",
      };
    case "failed":
      return {
        label: "Thất bại",
        dotClass: "bg-rose-500",
        textClass: "text-rose-700",
      };
    case "ignored_chat":
      return {
        label: "Tin xã giao",
        dotClass: "bg-slate-400",
        textClass: "text-slate-600",
      };
    case "ignored_non_text":
      return {
        label: "Bỏ qua",
        dotClass: "bg-slate-400",
        textClass: "text-slate-600",
      };
    case "received":
      return {
        label: "Mới nhận",
        dotClass: "bg-slate-500",
        textClass: "text-slate-700",
      };
    case "queued":
      return {
        label: "Đang chờ",
        dotClass: "bg-amber-500",
        textClass: "text-amber-700",
      };
    case "processing":
      return {
        label: "Đang xử lý",
        dotClass: "bg-amber-500",
        textClass: "text-amber-700",
      };
    default:
      return {
        label: "Chưa rõ",
        dotClass: "bg-slate-400",
        textClass: "text-slate-600",
      };
  }
}

/**
 * Chuyển mã phân loại ca duyệt nội bộ sang mô tả tiếng Việt thân thiện cho người điều hành.
 */
export function getReviewCaseTypeLabel(caseType?: string | null): string {
  switch ((caseType || "").trim()) {
    case "missing_fields":
      return "Thiếu thông tin bắt buộc";
    case "invalid_check_digit":
      return "Số container chưa đúng chuẩn";
    case "SHIPPING_NOT_FOUND":
      return "Chưa khớp kế hoạch vận chuyển";
    case "CARRIER_MISMATCH":
      return "Lệch nhà xe phụ trách";
    case "PLAN_SYNC_REQUIRED":
      return "Cần chọn kế hoạch phù hợp";
    case "PLAN_FIELD_CONFLICT":
      return "Thông tin lệch so với kế hoạch";
    case "CUSTOMER_CHANGE_REQUEST":
      return "Khách hàng yêu cầu thay đổi";
    case "CUSTOMER_REPEATED_INQUIRY":
      return "Khách hàng hỏi lại nhiều lần";
    case "ROUTING_NOT_FOUND":
      return "Chưa có nhóm nhận thông báo";
    case "OUTBOUND_PENDING_APPROVAL":
      return "Chờ duyệt gửi khách hàng";
    case "OUTBOUND_SEND_FAILED":
      return "Gửi thông báo thất bại";
    case "DUPLICATE_CONTAINER_WARNING":
      return "Cảnh báo trùng số container";
    case "CARRIER_ISSUE_OR_CANCEL":
      return "Nhà xe báo sự cố hoặc hủy chuyến";
    default:
      return "Cần điều hành kiểm tra";
  }
}

/**
 * Chuyển trạng thái ca duyệt sang nhãn tiếng Việt.
 */
export function getReviewStatusLabel(status?: string | null): string {
  switch ((status || "").toLowerCase()) {
    case "pending":
      return "Chờ xử lý";
    case "in_progress":
      return "Đang xử lý";
    case "approved":
      return "Đã duyệt";
    case "rejected":
      return "Đã từ chối";
    case "resolved":
      return "Đã xử lý";
    default:
      return "Chờ xử lý";
  }
}

/**
 * Chuyển trạng thái bản tin gửi khách hàng sang nhãn tiếng Việt và màu chấm trạng thái.
 */
export function getOutboundStatusMeta(status?: string | null): FriendlyStatusMeta {
  switch ((status || "").toLowerCase()) {
    case "da_gui":
    case "sent":
      return {
        label: "Đã gửi",
        dotClass: "bg-emerald-500",
        textClass: "text-emerald-700",
      };
    case "cho_duyet":
    case "pending_approval":
      return {
        label: "Chờ duyệt",
        dotClass: "bg-purple-600",
        textClass: "text-purple-700",
      };
    case "pending_send":
      return {
        label: "Đang chờ gửi",
        dotClass: "bg-amber-500",
        textClass: "text-amber-700",
      };
    case "bo_qua_trung_lap":
    case "skipped_duplicate":
      return {
        label: "Bỏ qua gửi trùng",
        dotClass: "bg-slate-400",
        textClass: "text-slate-600",
      };
    case "failed":
    case "that_bai":
      return {
        label: "Gửi thất bại",
        dotClass: "bg-rose-500",
        textClass: "text-rose-700",
      };
    default:
      return {
        label: "Đang xử lý",
        dotClass: "bg-slate-400",
        textClass: "text-slate-600",
      };
  }
}

/**
 * Chuyển trạng thái đối chiếu nguồn dữ liệu sang nhãn tiếng Việt cho người dùng cuối.
 */
export function getMatchStatusLabel(matchSource?: string | null): string {
  switch ((matchSource || "").toLowerCase()) {
    case "transport_plan":
    case "matched":
    case "direct_match":
    case "exact":
      return "Đã khớp kế hoạch";
    case "habit":
    case "fuzzy":
    case "vector":
    case "ai_llm":
      return "Đã nhận diện danh mục";
    case "unmatched":
    case "":
      return "Chưa khớp kế hoạch";
    default:
      return "Đã đối chiếu";
  }
}
