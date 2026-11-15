/**
 * Định nghĩa kiểu dữ liệu cho phân hệ Quản lý Người dùng (Users Domain).
 * Tuân thủ quy chuẩn Snowflake ID 64-bit dạng chuỗi (Id = string).
 */

export type UserRole = "admin" | "dhvt";

export interface UserItem {
  id: string;
  username: string;
  fullName: string;
  role: UserRole;
  email?: string | null;
  zaloUserId?: string | null;
  zaloInfoId?: string | null;
  tmsUserId?: string | null;
  forwarderId?: string | null;
  isActive: boolean;
  lastLoginAt?: string | null;
  createdAt: string;
  updatedAt?: string | null;
}

export interface CreateUserInput {
  username: string;
  password?: string;
  fullName?: string;
  role?: UserRole;
  email?: string;
  zaloUserId?: string;
  zaloInfoId?: number;
  isActive?: boolean;
}

export interface UpdateUserInput {
  fullName?: string;
  role?: UserRole;
  email?: string;
  zaloUserId?: string;
  zaloInfoId?: number;
  isActive?: boolean;
  password?: string;
}

export interface UserListParams {
  page?: number;
  pageSize?: number;
  role?: string;
  isActive?: boolean;
  search?: string;
}

export interface UserListResult {
  ok: boolean;
  total: number;
  page: number;
  pageSize: number;
  items: UserItem[];
  message?: string;
}
