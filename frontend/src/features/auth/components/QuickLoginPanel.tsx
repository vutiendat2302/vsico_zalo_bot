"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Edit3, Loader2 } from "lucide-react";
import { QUICK_LOGIN_PRESETS } from "../presets";
import { QuickLoginPreset } from "../types";
import { login } from "../api";

interface QuickLoginPanelProps {
  onFillPreset: (username: string, password: string) => void;
  onSuccess?: () => void;
}

/**
 * Bảng Đăng nhập nhanh phục vụ kiểm thử phân quyền (Admin & ĐHVT).
 * Tối giản, ít chữ, chuẩn giao diện điều hành.
 */
export default function QuickLoginPanel({ onFillPreset, onSuccess }: QuickLoginPanelProps) {
  const router = useRouter();
  const [loadingPresetId, setLoadingPresetId] = useState<string | null>(null);

  const handleDirectLogin = async (preset: QuickLoginPreset) => {
    setLoadingPresetId(preset.id);
    try {
      const result = await login({
        username: preset.username,
        password: preset.password,
        remember: true,
      });

      if (result.ok) {
        if (onSuccess) {
          onSuccess();
        } else {
          router.push("/");
          router.refresh();
        }
      }
    } finally {
      setLoadingPresetId(null);
    }
  };

  return (
    <div className="border border-slate-200 rounded-sm bg-white p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 pb-2.5">
        <div className="flex items-center space-x-2">
          <span className="w-2 h-2 rounded-full bg-purple-600"></span>
          <span className="text-xs font-semibold text-slate-900 uppercase tracking-wide">
            Đăng nhập nhanh
          </span>
        </div>
        <span className="text-[10px] font-mono px-1.5 py-0.5 border border-purple-200 text-purple-700 bg-purple-50 rounded-sm">
          TEST
        </span>
      </div>

      {/* Danh sách Preset */}
      <div className="space-y-2">
        {QUICK_LOGIN_PRESETS.map((preset) => {
          const isLoading = loadingPresetId === preset.id;
          const isAdmin = preset.role === "admin";

          return (
            <div
              key={preset.id}
              className="border border-slate-200 hover:border-purple-300 rounded-sm p-2.5 bg-slate-50/50 hover:bg-white transition-colors duration-100 flex items-center justify-between"
            >
              <div>
                <div className="flex items-center space-x-2">
                  <span className="text-xs font-semibold text-slate-800">
                    {preset.label}
                  </span>
                  <span
                    className={`text-[10px] font-medium px-1.5 py-0.2 rounded-sm border ${
                      isAdmin
                        ? "border-amber-300 bg-amber-50 text-amber-800"
                        : "border-purple-200 bg-purple-50 text-purple-700"
                    }`}
                  >
                    {preset.badge}
                  </span>
                </div>
                <div className="text-[11px] text-slate-500 font-mono mt-0.5">
                  {preset.username}
                </div>
              </div>

              {/* Các nút thao tác */}
              <div className="flex items-center space-x-1.5">
                <button
                  type="button"
                  onClick={() => onFillPreset(preset.username, preset.password)}
                  className="h-7 px-2 border border-slate-200 hover:border-slate-300 bg-white text-slate-700 hover:text-slate-900 text-[11px] rounded-sm flex items-center space-x-1 transition-colors"
                >
                  <Edit3 className="w-3 h-3 text-slate-500" />
                  <span>Điền</span>
                </button>

                <button
                  type="button"
                  disabled={isLoading}
                  onClick={() => handleDirectLogin(preset)}
                  className="h-7 px-2.5 bg-purple-700 hover:bg-purple-800 disabled:bg-purple-400 text-white text-[11px] font-medium rounded-sm flex items-center space-x-1 transition-colors"
                >
                  {isLoading ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <>
                      <span>Vào ngay</span>
                      <ArrowRight className="w-3 h-3" />
                    </>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
