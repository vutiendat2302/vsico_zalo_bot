/**
 * Định nghĩa kiểu dữ liệu cho phân hệ Xác thực & Phân quyền (Auth Domain).
 * Tuân thủ quy ước Snowflake ID 64-bit dạng chuỗi (Id = string).
 */

export type UserRole = "admin" | "dhvt";

export interface AuthUser {
  id: string;
  username: string;
  fullName: string;
  role: UserRole;
  zaloUserId?: string | null;
  zaloInfoId?: string | null;
  email?: string | null;
  department?: string | null;
}

export interface LoginCredentials {
  username: string;
  password: string;
  remember?: boolean;
}

export interface QuickLoginPreset {
  id: string;
  label: string;
  role: UserRole;
  username: string;
  password: string;
  department: string;
  badge: string;
  description: string;
}
