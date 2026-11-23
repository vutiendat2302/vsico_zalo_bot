import { AuthUser } from "@/features/auth/types";

export const AUTH_COOKIE_NAME = "vsico_session";
export const TOKEN_COOKIE_NAME = "vsico_token";

/**
 * Trích xuất thời điểm hết hạn `exp` (Unix timestamp giây) từ phần payload của JWT.
 */
export function getJwtExpirationEpoch(token?: string | null): number | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length < 2) return null;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const jsonStr = atob(padded);
    const payload = JSON.parse(jsonStr) as { exp?: unknown };
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

/**
 * Kiểm tra JWT đã hết hạn (hoặc sắp hết hạn trong `skewSeconds` giây) hay chưa.
 */
export function isJwtExpired(token?: string | null, skewSeconds = 0): boolean {
  const exp = getJwtExpirationEpoch(token);
  if (exp === null) return true;
  return Date.now() / 1000 >= exp - skewSeconds;
}

/**
 * Lấy số giây hiệu lực còn lại của JWT hiện tại (trả về 0 nếu hết hạn/không hợp lệ).
 */
export function getJwtRemainingSeconds(token?: string | null): number {
  const exp = getJwtExpirationEpoch(token);
  if (exp === null) return 0;
  return Math.max(0, Math.floor(exp - Date.now() / 1000));
}

/**
 * Dọn cookie phiên lỗi thời và chuyển hướng người dùng về trang đăng nhập khi API trả 401.
 */
export function redirectToLoginOnUnauthorized(): void {
  clearClientSession();
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  const from = `${window.location.pathname}${window.location.search}`;
  window.location.replace(`/login?from=${encodeURIComponent(from)}`);
}

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
