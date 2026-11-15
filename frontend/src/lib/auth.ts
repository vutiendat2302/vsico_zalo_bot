import { AuthUser } from "@/features/auth/types";

export const AUTH_COOKIE_NAME = "vsico_session";
export const TOKEN_COOKIE_NAME = "vsico_token";

/**
 * Đọc thông tin người dùng từ cookie phiên làm việc tại client.
 */
export function getClientSession(): AuthUser | null {
  if (typeof document === "undefined") {
    return null;
  }
  const cookies = document.cookie.split(";").map((c) => c.trim());
  const target = cookies.find((c) => c.startsWith(`${AUTH_COOKIE_NAME}=`));
  if (!target) {
    return null;
  }
  try {
    const rawVal = target.substring(`${AUTH_COOKIE_NAME}=`.length);
    const decoded = decodeURIComponent(rawVal);
    return JSON.parse(decoded) as AuthUser;
  } catch {
    return null;
  }
}

/**
 * Lấy mã JWT Token từ cookie phiên để đính kèm vào Header Authorization.
 */
export function getAuthToken(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const cookies = document.cookie.split(";").map((c) => c.trim());
  const target = cookies.find((c) => c.startsWith(`${TOKEN_COOKIE_NAME}=`));
  if (!target) {
    return null;
  }
  return decodeURIComponent(target.substring(`${TOKEN_COOKIE_NAME}=`.length));
}

/**
 * Lưu thông tin phiên làm việc và mã JWT vào cookie của trình duyệt.
 * @param user Thông tin người dùng đăng nhập
 * @param remember Có duy trì phiên dài ngày không
 * @param token Mã JWT Access Token tùy chọn
 */
export function setClientSession(
  user: AuthUser,
  remember = true,
  token?: string
): void {
  if (typeof document === "undefined") {
    return;
  }
  const serialized = encodeURIComponent(JSON.stringify(user));
  const maxAge = remember ? 60 * 60 * 24 * 7 : 60 * 60 * 12; // 7 ngày hoặc 12 giờ
  document.cookie = `${AUTH_COOKIE_NAME}=${serialized}; path=/; max-age=${maxAge}; SameSite=Lax`;
  if (token) {
    document.cookie = `${TOKEN_COOKIE_NAME}=${encodeURIComponent(token)}; path=/; max-age=${maxAge}; SameSite=Lax`;
  }
}

/**
 * Xóa cookie phiên làm việc và token khi đăng xuất.
 */
export function clearClientSession(): void {
  if (typeof document === "undefined") {
    return;
  }
  document.cookie = `${AUTH_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax`;
  document.cookie = `${TOKEN_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax`;
}

/**
 * Kiểm tra xem người dùng hiện tại có vai trò quản trị viên không.
 */
export function isAdmin(user: AuthUser | null): boolean {
  return user?.role === "admin";
}
