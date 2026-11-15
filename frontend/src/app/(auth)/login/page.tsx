"use client";

import React, { useState } from "react";
import LoginForm from "@/features/auth/components/LoginForm";
import QuickLoginPanel from "@/features/auth/components/QuickLoginPanel";
import { LoginCredentials } from "@/features/auth/types";
import { QUICK_LOGIN_PRESETS } from "@/features/auth/presets";
import { Truck } from "lucide-react";

/**
 * Trang Đăng nhập Hệ thống Điều hành VSICO.
 * Tối giản, ít chữ, chuẩn phong cách điều hành.
 */
export default function LoginPage() {
  const [credentials, setCredentials] = useState<LoginCredentials>({
    username: QUICK_LOGIN_PRESETS[0].username,
    password: QUICK_LOGIN_PRESETS[0].password,
    remember: true,
  });

  const handleFieldChange = (
    field: keyof LoginCredentials,
    value: string | boolean
  ) => {
    setCredentials((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const handleFillPreset = (username: string, password: string) => {
    setCredentials({
      username,
      password,
      remember: true,
    });
  };

  return (
    <div className="min-h-[85vh] flex items-center justify-center py-6 px-4">
      <div className="w-full max-w-3xl bg-white border border-slate-200 rounded-sm">
        {/* Header */}
        <div className="border-b border-slate-200 px-5 py-3.5 flex items-center justify-between bg-slate-50">
          <div className="flex items-center space-x-2.5">
            <div className="w-7 h-7 rounded-sm bg-purple-700 flex items-center justify-center text-white">
              <Truck className="w-4 h-4" />
            </div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-sm tracking-wide text-slate-900">
                VSICO LOGISTICS
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 border border-purple-200 text-purple-700 bg-purple-50 rounded-sm">
                BOT ZALO
              </span>
            </div>
          </div>
        </div>

        {/* Nội dung chính chia 2 cột */}
        <div className="p-5 grid grid-cols-1 md:grid-cols-12 gap-5">
          {/* Cột trái: Form đăng nhập */}
          <div className="md:col-span-6 space-y-3">
            <h1 className="text-xs font-semibold text-slate-900 uppercase tracking-wide">
              Đăng nhập
            </h1>

            <LoginForm
              credentials={credentials}
              onChange={handleFieldChange}
            />
          </div>

          {/* Cột phải: Đăng nhập nhanh */}
          <div className="md:col-span-6">
            <QuickLoginPanel onFillPreset={handleFillPreset} />
          </div>
        </div>
      </div>
    </div>
  );
}
