import { QuickLoginPreset } from "./types";

/**
 * Danh sách tài khoản kiểm thử cho tính năng Đăng nhập nhanh.
 */
export const QUICK_LOGIN_PRESETS: QuickLoginPreset[] = [
  {
    id: "admin-system",
    label: "Admin",
    role: "admin",
    username: "admin",
    password: "123456",
    department: "",
    badge: "Admin",
    description: "",
  },
];
