import { getAuthToken } from "@/lib/auth";
import {
  CreateUserInput,
  UpdateUserInput,
  UserItem,
  UserListParams,
  UserListResult,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface BackendUserOut {
  id: string;
  username: string;
  full_name: string;
  role: string;
  email?: string | null;
  zalo_user_id?: string | null;
  zalo_info_id?: string | null;
  tms_user_id?: string | null;
  forwarder_id?: string | null;
  is_active: boolean;
  last_login_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

function mapUserOut(u: BackendUserOut): UserItem {
  return {
    id: String(u.id),
    username: u.username,
    fullName: u.full_name,
    role: (u.role?.toUpperCase() === "ADMIN") ? "admin" : "dhvt",
    email: u.email,
    zaloUserId: u.zalo_user_id,
    zaloInfoId: u.zalo_info_id ? String(u.zalo_info_id) : null,
    tmsUserId: u.tms_user_id,
    forwarderId: u.forwarder_id,
    isActive: Boolean(u.is_active),
    lastLoginAt: u.last_login_at,
    createdAt: u.created_at,
    updatedAt: u.updated_at,
  };
}

function getHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Lấy danh sách tài khoản người dùng từ Backend CSDL thực tế.
 */
export async function getUsers(params?: UserListParams): Promise<UserListResult> {
  const query = new URLSearchParams();
  if (params?.page) query.set("page", String(params.page));
  if (params?.pageSize) query.set("page_size", String(params.pageSize));
  if (params?.role && params.role !== "all") query.set("role", params.role);
  if (params?.isActive !== undefined) query.set("is_active", String(params.isActive));
  if (params?.search && params.search.trim()) query.set("search", params.search.trim());

  const res = await fetch(`${API_BASE_URL}/api/users?${query.toString()}`, {
    method: "GET",
    headers: getHeaders(),
    cache: "no-store",
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || err.detail || "Không thể tải danh sách tài khoản từ máy chủ.");
  }

  const data = await res.json();
  const rawItems = Array.isArray(data.data) ? data.data : (data.items || []);
  return {
    ok: true,
    total: data.meta?.total ?? data.total ?? 0,
    page: data.meta?.page ?? data.page ?? 1,
    pageSize: data.meta?.page_size ?? data.page_size ?? 20,
    items: rawItems.map(mapUserOut),
  };
}

/**
 * Lấy chi tiết thông tin một tài khoản.
 */
export async function getUserById(id: string): Promise<UserItem> {
  const res = await fetch(`${API_BASE_URL}/api/users/${id}`, {
    method: "GET",
    headers: getHeaders(),
    cache: "no-store",
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || err.detail || `Không tìm thấy tài khoản ID: ${id}`);
  }

  const json = await res.json();
  return mapUserOut(json.data);
}

/**
 * Tạo mới tài khoản người dùng với các giá trị mặc định.
 * - password: mặc định 123456
 * - zalo_user_id: mặc định 6691387223255581446
 * - zalo_info_id: mặc định 3073804738540831090
 */
export async function createUser(input: CreateUserInput): Promise<UserItem> {
  const payload = {
    username: input.username.trim(),
    password: input.password || "123456",
    full_name: input.fullName?.trim() || input.username.trim(),
    role: (input.role || "dhvt").toUpperCase(),
    email: input.email?.trim() || null,
    zalo_user_id: input.zaloUserId || "6691387223255581446",
    zalo_info_id: input.zaloInfoId || 3073804738540831090,
    is_active: input.isActive !== undefined ? input.isActive : true,
  };

  const res = await fetch(`${API_BASE_URL}/api/users`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || err.detail || "Tạo tài khoản thất bại.");
  }

  const json = await res.json();
  return mapUserOut(json.data);
}

/**
 * Cập nhật thông tin tài khoản hoặc đổi mật khẩu.
 */
export async function updateUser(
  id: string,
  input: UpdateUserInput
): Promise<UserItem> {
  const payload: Record<string, unknown> = {};
  if (input.fullName !== undefined) payload.full_name = input.fullName;
  if (input.role !== undefined) payload.role = input.role.toUpperCase();
  if (input.email !== undefined) payload.email = input.email || null;
  if (input.zaloUserId !== undefined) payload.zalo_user_id = input.zaloUserId || null;
  if (input.zaloInfoId !== undefined) payload.zalo_info_id = input.zaloInfoId;
  if (input.isActive !== undefined) payload.is_active = input.isActive;
  if (input.password && input.password.trim().length >= 6) {
    payload.password = input.password.trim();
  }

  const res = await fetch(`${API_BASE_URL}/api/users/${id}`, {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || err.detail || "Cập nhật tài khoản thất bại.");
  }

  const json = await res.json();
  return mapUserOut(json.data);
}

/**
 * Xóa tài khoản khỏi hệ thống.
 */
export async function deleteUser(id: string): Promise<boolean> {
  const res = await fetch(`${API_BASE_URL}/api/users/${id}`, {
    method: "DELETE",
    headers: getHeaders(),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || err.detail || "Xóa tài khoản thất bại.");
  }

  return true;
}
