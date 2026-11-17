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
