import { AuthUser, LoginCredentials } from "./types";
import { setClientSession } from "@/lib/auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface LoginResult {
  ok: boolean;
  message?: string;
  user?: AuthUser;
}

/**
 * Xử lý đăng nhập tài khoản ĐHVT hoặc Admin thông qua API Backend thực tế.
 * Không sử dụng mock data.
 */
export async function login(credentials: LoginCredentials): Promise<LoginResult> {
  const { username, password, remember = true } = credentials;

  if (!username.trim() || !password.trim()) {
    return {
      ok: false,
      message: "Vui lòng nhập đầy đủ tên tài khoản và mật khẩu.",
    };
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username: username.trim(),
        password: password.trim(),
      }),
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      return {
        ok: false,
        message: data.detail || "Đăng nhập thất bại. Tài khoản hoặc mật khẩu không chính xác.",
      };
    }

    const user: AuthUser = {
      id: String(data.user?.id || ""),
      username: data.user?.username || username.trim(),
      fullName: data.user?.full_name || username.trim(),
      role: (data.user?.role as "admin" | "dhvt") || "dhvt",
      email: data.user?.email || null,
      zaloUserId: data.user?.zalo_user_id || null,
      zaloInfoId: data.user?.zalo_info_id ? String(data.user.zalo_info_id) : null,
      department: data.user?.role === "admin" ? "Ban Quản Trị Hệ Thống" : "Ban Điều Hành Vận Tải",
    };

    // Lưu session và Bearer token vào cookie
    setClientSession(user, remember, data.access_token);

    return { ok: true, user };
  } catch (err: unknown) {
    const errorMsg =
      err instanceof Error ? err.message : "Lỗi kết nối máy chủ";
    return {
      ok: false,
      message: `Không thể kết nối tới máy chủ Backend (${API_BASE_URL}): ${errorMsg}`,
    };
  }
}
