"use client";

import React, { useEffect, useState } from "react";
import { UpdateUserInput, UserItem, UserRole } from "../types";
import { updateUser } from "../api";
import { X, Loader2 } from "lucide-react";

interface EditUserModalProps {
  user: UserItem | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function EditUserModal({
  user,
  isOpen,
  onClose,
  onSuccess,
}: EditUserModalProps) {
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("dhvt");
  const [email, setEmail] = useState("");
  const [zaloUserId, setZaloUserId] = useState("");
  const [zaloInfoId, setZaloInfoId] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [newPassword, setNewPassword] = useState("");

  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setFullName(user.fullName || "");
      setRole(user.role || "dhvt");
      setEmail(user.email || "");
      setZaloUserId(user.zaloUserId || "");
      setZaloInfoId(user.zaloInfoId ? String(user.zaloInfoId) : "");
      setIsActive(user.isActive);
      setNewPassword("");
      setErrorMsg(null);
    }
  }, [user]);

  if (!isOpen || !user) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg(null);

    try {
      const payload: UpdateUserInput = {
        fullName: fullName.trim() || undefined,
        role,
        email: email.trim() || undefined,
        zaloUserId: zaloUserId.trim() || undefined,
        zaloInfoId: zaloInfoId.trim() ? Number(zaloInfoId.trim()) : undefined,
        isActive,
        password: newPassword.trim() ? newPassword.trim() : undefined,
      };

      await updateUser(user.id, payload);
      onSuccess();
      onClose();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Cập nhật tài khoản thất bại.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white border border-slate-200 rounded-sm shadow-md w-full max-w-lg overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50">
          <div>
            <h3 className="text-sm font-bold text-slate-900">
              Cập Nhật Tài Khoản: <span className="font-mono text-purple-700">{user.username}</span>
            </h3>
            <p className="text-xs text-slate-500">ID: {user.id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded-sm"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body / Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-3.5">
          {errorMsg && (
            <div className="p-2.5 bg-red-50 border border-red-200 text-red-700 text-xs rounded-sm">
              {errorMsg}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Họ và tên
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Vai trò (Role)
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 bg-white"
              >
                <option value="dhvt">ĐHVT (Điều hành vận tải)</option>
                <option value="admin">Admin (Quản trị viên)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Email công ty
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Zalo User ID
              </label>
              <input
                type="text"
                value={zaloUserId}
                onChange={(e) => setZaloUserId(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Nhóm Zalo ĐHVT ID
              </label>
              <input
                type="text"
                value={zaloInfoId}
                onChange={(e) => setZaloInfoId(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 font-mono"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Đặt lại mật khẩu mới (Bỏ trống nếu giữ nguyên)
            </label>
            <input
              type="password"
              placeholder="Tối thiểu 6 ký tự"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 font-mono"
            />
          </div>

          {/* Trạng thái hoạt động */}
          <div className="flex items-center space-x-2 pt-1">
            <input
              type="checkbox"
              id="isActiveEditCheck"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="rounded-sm border-slate-300 text-purple-700 focus:ring-purple-600"
            />
            <label htmlFor="isActiveEditCheck" className="text-xs text-slate-700 select-none">
              Tài khoản đang hoạt động (Bỏ chọn để khóa tài khoản)
            </label>
          </div>

          {/* Modal Footer */}
          <div className="flex items-center justify-end space-x-2 pt-3 border-t border-slate-200">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-800 border border-slate-200 rounded-sm"
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium text-white bg-purple-700 hover:bg-purple-800 rounded-sm transition-colors disabled:opacity-50"
            >
              {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              <span>Lưu thay đổi</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
