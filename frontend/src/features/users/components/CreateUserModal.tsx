"use client";

import React, { useState } from "react";
import { CreateUserInput, UserRole } from "../types";
import { createUser } from "../api";
import { X, Loader2 } from "lucide-react";

interface CreateUserModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function CreateUserModal({
  isOpen,
  onClose,
  onSuccess,
}: CreateUserModalProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("123456");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("dhvt");
  const [email, setEmail] = useState("");
  const [zaloUserId, setZaloUserId] = useState("6691387223255581446");
  const [zaloInfoId, setZaloInfoId] = useState("3073804738540831090");
  const [isActive, setIsActive] = useState(true);

  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim()) {
      setErrorMsg("Vui lòng nhập tên đăng nhập.");
      return;
    }

    setLoading(true);
    setErrorMsg(null);

    try {
      const payload: CreateUserInput = {
        username: username.trim(),
        password: password.trim() || "123456",
        fullName: fullName.trim() || username.trim(),
        role,
        email: email.trim() || undefined,
        zaloUserId: zaloUserId.trim() || "6691387223255581446",
        zaloInfoId: zaloInfoId.trim() ? Number(zaloInfoId.trim()) : 3073804738540831090,
        isActive,
      };

      await createUser(payload);
      // Reset form
      setUsername("");
      setPassword("123456");
      setFullName("");
      setEmail("");
      setRole("dhvt");
      setZaloUserId("6691387223255581446");
      setZaloInfoId("3073804738540831090");
      setIsActive(true);

      onSuccess();
      onClose();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Tạo tài khoản thất bại.");
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
              Thêm Mới Tài Khoản Người Dùng
            </h3>
            <p className="text-xs text-slate-500">
              Chỉ cần nhập tên đăng nhập, các trường còn lại đã có cấu hình mặc định.
            </p>
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

          {/* Tên đăng nhập (Bắt buộc) */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Tên đăng nhập (Username) <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              placeholder="VD: dhvt_hanoi, le_van_b..."
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 font-mono"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            {/* Mật khẩu */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Mật khẩu (Mặc định: 123456)
              </label>
              <input
                type="text"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 font-mono"
              />
            </div>

            {/* Phân quyền */}
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

          {/* Họ và tên & Email */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Họ và tên (Tùy chọn)
              </label>
              <input
                type="text"
                placeholder="Mặc định lấy theo username"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Email công ty (Tùy chọn)
              </label>
              <input
                type="email"
                placeholder="VD: user@vsico.com.vn"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600"
              />
            </div>
          </div>

          {/* Zalo User ID & Nhóm Zalo ID */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Zalo User ID (Mặc định)
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
                Nhóm Zalo ĐHVT ID (Mặc định)
              </label>
              <input
                type="text"
                value={zaloInfoId}
                onChange={(e) => setZaloInfoId(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 font-mono"
              />
            </div>
          </div>

          {/* Trạng thái hoạt động */}
          <div className="flex items-center space-x-2 pt-1">
            <input
              type="checkbox"
              id="isActiveCheck"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="rounded-sm border-slate-300 text-purple-700 focus:ring-purple-600"
            />
            <label htmlFor="isActiveCheck" className="text-xs text-slate-700 select-none">
              Kích hoạt tài khoản ngay sau khi tạo
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
              <span>Tạo tài khoản</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
