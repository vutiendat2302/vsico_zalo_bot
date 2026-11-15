"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, LogIn, Loader2 } from "lucide-react";
import { login } from "../api";
import { LoginCredentials } from "../types";

interface LoginFormProps {
  credentials: LoginCredentials;
  onChange: (field: keyof LoginCredentials, value: string | boolean) => void;
  onSuccess?: () => void;
}

/**
 * Biểu mẫu đăng nhập chuẩn hóa cho nhân viên ĐHVT & Quản trị viên.
 * Thiết kế tối giản, sắc nét, không đổ bóng, bo góc tối đa rounded-sm.
 */
export default function LoginForm({ credentials, onChange, onSuccess }: LoginFormProps) {
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setLoading(true);

    try {
      const result = await login(credentials);
      if (result.ok) {
        if (onSuccess) {
          onSuccess();
        } else {
          router.push("/");
          router.refresh();
        }
      } else {
        setErrorMessage(result.message || "Đăng nhập không thành công.");
      }
    } catch {
      setErrorMessage("Lỗi kết nối máy chủ xác thực. Vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {errorMessage && (
        <div className="border border-red-200 bg-red-50 text-red-700 text-xs rounded-sm p-2.5 flex items-center justify-between">
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-red-500 hover:text-red-700 font-semibold ml-2 text-xs"
          >
            Đóng
          </button>
        </div>
      )}

      {/* Trường Tài khoản */}
      <div className="space-y-1.5">
        <label
          htmlFor="username"
          className="block text-xs font-medium text-slate-700 tracking-wide"
        >
          Tài khoản
        </label>
        <input
          id="username"
          type="text"
          value={credentials.username}
          onChange={(e) => onChange("username", e.target.value)}
          placeholder="Tên tài khoản hoặc email nội bộ"
          required
          autoComplete="username"
          className="w-full h-9 px-3 text-xs bg-white text-slate-900 border border-slate-300 rounded-sm focus:border-purple-600 focus:ring-1 focus:ring-purple-600 outline-none transition-colors"
        />
      </div>

      {/* Trường Mật khẩu */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label
            htmlFor="password"
            className="block text-xs font-medium text-slate-700 tracking-wide"
          >
            Mật khẩu
          </label>
        </div>
        <div className="relative">
          <input
            id="password"
            type={showPassword ? "text" : "password"}
            value={credentials.password}
            onChange={(e) => onChange("password", e.target.value)}
            placeholder="Mật khẩu truy cập hệ thống"
            required
            autoComplete="current-password"
            className="w-full h-9 pl-3 pr-9 text-xs bg-white text-slate-900 border border-slate-300 rounded-sm focus:border-purple-600 focus:ring-1 focus:ring-purple-600 outline-none transition-colors"
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            tabIndex={-1}
            className="absolute inset-y-0 right-0 px-2.5 flex items-center text-slate-400 hover:text-slate-600"
            title={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
          >
            {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Tùy chọn Ghi nhớ phiên */}
      <div className="flex items-center justify-between pt-1">
        <label className="flex items-center space-x-2 text-xs text-slate-600 cursor-pointer">
          <input
            type="checkbox"
            checked={credentials.remember ?? true}
            onChange={(e) => onChange("remember", e.target.checked)}
            className="w-3.5 h-3.5 rounded-sm border-slate-300 text-purple-700 focus:ring-purple-600"
          />
          <span>Duy trì đăng nhập phiên làm việc</span>
        </label>
      </div>

      {/* Nút gửi Đăng nhập */}
      <button
        type="submit"
        disabled={loading}
        className="w-full h-9 px-4 bg-purple-700 hover:bg-purple-800 disabled:bg-purple-400 text-white text-xs font-medium rounded-sm flex items-center justify-center space-x-2 transition-colors duration-100"
      >
        {loading ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span>Đang xác thực...</span>
          </>
        ) : (
          <>
            <LogIn className="w-3.5 h-3.5" />
            <span>Đăng nhập</span>
          </>
        )}
      </button>
    </form>
  );
}
