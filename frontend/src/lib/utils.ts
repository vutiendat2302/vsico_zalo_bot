/**
 * Hàm tiện ích kết hợp class name Tailwind CSS.
 * Không thêm thư viện ngoài, tối ưu hiệu năng và giữ kích thước bundle tối thiểu.
 */
export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(" ");
}
