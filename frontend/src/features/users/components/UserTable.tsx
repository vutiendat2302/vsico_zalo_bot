"use client";

import React from "react";
import { UserItem } from "../types";
import { Edit2, Trash2, Shield, User, Loader2 } from "lucide-react";

interface UserTableProps {
  users: UserItem[];
  loading: boolean;
  onEdit: (user: UserItem) => void;
  onDelete: (user: UserItem) => void;
}

export default function UserTable({
  users,
  loading,
  onEdit,
  onDelete,
}: UserTableProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 bg-white border border-slate-200 rounded-sm">
        <div className="flex items-center space-x-2 text-xs text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin text-purple-700" />
          <span>Đang tải danh sách tài khoản từ máy chủ...</span>
        </div>
      </div>
    );
  }

  if (users.length === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-sm p-8 text-center">
        <p className="text-xs text-slate-500 font-medium">
          Chưa có tài khoản nào trong hệ thống hoặc không khớp với bộ lọc.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-sm overflow-hidden shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold uppercase tracking-wider">
              <th className="px-3 py-2.5">ID (Snowflake)</th>
              <th className="px-3 py-2.5">Tên đăng nhập</th>
              <th className="px-3 py-2.5">Họ và tên</th>
              <th className="px-3 py-2.5">Vai trò</th>
              <th className="px-3 py-2.5">Zalo User ID</th>
              <th className="px-3 py-2.5">Nhóm Zalo ĐHVT</th>
              <th className="px-3 py-2.5">Trạng thái</th>
              <th className="px-3 py-2.5">Ngày tạo</th>
              <th className="px-3 py-2.5 text-right">Thao tác</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map((u) => {
              const isAdmin = u.role === "admin";
              return (
                <tr
                  key={u.id}
                  className="hover:bg-slate-50/70 transition-colors"
                >
                  {/* Snowflake ID */}
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-500 select-all">
                    {u.id}
                  </td>

                  {/* Username */}
                  <td className="px-3 py-2 font-semibold text-slate-900 font-mono">
                    {u.username}
                  </td>

                  {/* Họ và tên */}
                  <td className="px-3 py-2 text-slate-800">
                    <div>{u.fullName}</div>
                    {u.email && (
                      <div className="text-[10px] text-slate-400 font-mono">
                        {u.email}
                      </div>
                    )}
                  </td>

                  {/* Role Badge */}
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center space-x-1 px-1.5 py-0.5 rounded-sm text-[10px] font-semibold border ${
                        isAdmin
                          ? "bg-purple-50 text-purple-700 border-purple-200"
                          : "bg-blue-50 text-blue-700 border-blue-200"
                      }`}
                    >
                      {isAdmin ? (
                        <Shield className="w-2.5 h-2.5" />
                      ) : (
                        <User className="w-2.5 h-2.5" />
                      )}
                      <span>{isAdmin ? "Admin" : "ĐHVT"}</span>
                    </span>
                  </td>

                  {/* Zalo User ID */}
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-600 select-all">
                    {u.zaloUserId || <span className="text-slate-300">-</span>}
                  </td>

                  {/* Zalo Info ID */}
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-600 select-all">
                    {u.zaloInfoId || <span className="text-slate-300">-</span>}
                  </td>

                  {/* Trạng thái */}
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-medium border ${
                        u.isActive
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : "bg-red-50 text-red-700 border-red-200"
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full mr-1 ${
                          u.isActive ? "bg-emerald-500" : "bg-red-500"
                        }`}
                      ></span>
                      <span>{u.isActive ? "Hoạt động" : "Đã khóa"}</span>
                    </span>
                  </td>

                  {/* Ngày tạo */}
                  <td className="px-3 py-2 text-[11px] text-slate-500 font-mono whitespace-nowrap">
                    {u.createdAt ? u.createdAt.replace("T", " ").substring(0, 19) : "-"}
                  </td>

                  {/* Thao tác */}
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => onEdit(u)}
                      className="inline-flex items-center space-x-1 px-2 py-1 text-slate-600 hover:text-purple-700 hover:bg-purple-50 rounded-sm border border-transparent hover:border-purple-200 transition-colors mr-1"
                      title="Sửa thông tin tài khoản"
                    >
                      <Edit2 className="w-3 h-3" />
                      <span className="text-[11px]">Sửa</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(u)}
                      className="inline-flex items-center space-x-1 px-2 py-1 text-slate-600 hover:text-red-700 hover:bg-red-50 rounded-sm border border-transparent hover:border-red-200 transition-colors"
                      title="Xóa tài khoản"
                    >
                      <Trash2 className="w-3 h-3" />
                      <span className="text-[11px]">Xóa</span>
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
