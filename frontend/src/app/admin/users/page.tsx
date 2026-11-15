"use client";

import React, { useEffect, useState, useCallback } from "react";
import { toast } from "@/components/shared/Toast";
import { UserItem } from "@/features/users/types";
import { getUsers, deleteUser } from "@/features/users/api";
import UserTable from "@/features/users/components/UserTable";
import CreateUserModal from "@/features/users/components/CreateUserModal";
import EditUserModal from "@/features/users/components/EditUserModal";
import {
  Users,
  UserPlus,
  RefreshCw,
  Search,
  Filter,
  AlertCircle,
} from "lucide-react";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Pagination
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 20;

  // Modals state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserItem | null>(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getUsers({
        page,
        pageSize,
        role: roleFilter !== "all" ? roleFilter : undefined,
        isActive:
          statusFilter === "active"
            ? true
            : statusFilter === "inactive"
            ? false
            : undefined,
        search: search.trim() || undefined,
      });
      setUsers(res.items);
      setTotal(res.total);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Không thể kết nối máy chủ để tải danh sách người dùng."
      );
    } finally {
      setLoading(false);
    }
  }, [page, roleFilter, statusFilter, search]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const handleDelete = async (user: UserItem) => {
    const confirmed = window.confirm(
      `Bạn có chắc chắn muốn xóa tài khoản "${user.username}" (ID: ${user.id}) không?`
    );
    if (!confirmed) return;

    try {
      await deleteUser(user.id);
      toast.success(`Đã xóa tài khoản "${user.username}" thành công.`);
      loadUsers();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Xóa tài khoản thất bại.");
    }
  };

  return (
    <div className="space-y-5">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <div className="flex items-center space-x-2">
            <div className="p-1.5 bg-purple-100 text-purple-700 rounded-sm">
              <Users className="w-5 h-5" />
            </div>
            <h1 className="text-lg font-bold text-slate-900 tracking-tight">
              Quản Lý Tài Khoản Người Dùng (Admin & ĐHVT)
            </h1>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Quản trị viên nội bộ, phân quyền vai trò (Admin / Điều hành vận tải) và quản lý liên kết nhóm Zalo.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => loadUsers()}
            disabled={loading}
            className="flex items-center space-x-1 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-sm transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-purple-700" : ""}`} />
            <span>Làm mới</span>
          </button>
          <button
            type="button"
            onClick={() => setIsCreateOpen(true)}
            className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium text-slate-900 bg-purple-700 hover:bg-purple-800 rounded-sm transition-colors "
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>Thêm tài khoản</span>
          </button>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="flex items-center space-x-2 p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Filter Bar */}
      <div className="bg-white border border-slate-200 rounded-sm p-3 flex flex-col md:flex-row md:items-center justify-between gap-3 ">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Tìm theo username, họ tên hoặc email..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-full pl-8 pr-3 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 font-mono"
          />
        </div>

        {/* Dropdowns */}
        <div className="flex items-center space-x-2">
          <div className="flex items-center space-x-1 text-xs text-slate-500">
            <Filter className="w-3.5 h-3.5" />
            <span>Vai trò:</span>
          </div>
          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPage(1);
            }}
            className="px-2 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 bg-white"
          >
            <option value="all">Tất cả vai trò</option>
            <option value="admin">Quản trị viên (Admin)</option>
            <option value="dhvt">Điều hành vận tải (ĐHVT)</option>
          </select>

          <div className="flex items-center space-x-1 text-xs text-slate-500 pl-2">
            <span>Trạng thái:</span>
          </div>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="px-2 py-1.5 text-xs border border-slate-300 rounded-sm focus:outline-none focus:border-purple-600 bg-white"
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="active">Đang hoạt động</option>
            <option value="inactive">Đã khóa</option>
          </select>
        </div>
      </div>

      {/* Users Table */}
      <UserTable
        users={users}
        loading={loading}
        onEdit={(user) => setEditingUser(user)}
        onDelete={handleDelete}
      />

      {/* Pagination Footer */}
      <div className="flex items-center justify-between text-xs text-slate-500 pt-1">
        <div>
          Tổng số: <span className="font-semibold text-slate-800">{total}</span> tài khoản
        </div>
        {total > pageSize && (
          <div className="flex items-center space-x-1">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="px-2.5 py-1 border border-slate-300 rounded-sm hover:bg-slate-50 disabled:opacity-40"
            >
              Trước
            </button>
            <span className="px-2 font-mono">
              Trang {page} / {Math.ceil(total / pageSize)}
            </span>
            <button
              type="button"
              disabled={page * pageSize >= total}
              onClick={() => setPage((p) => p + 1)}
              className="px-2.5 py-1 border border-slate-300 rounded-sm hover:bg-slate-50 disabled:opacity-40"
            >
              Sau
            </button>
          </div>
        )}
      </div>

      {/* Modals */}
      <CreateUserModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onSuccess={() => loadUsers()}
      />

      <EditUserModal
        user={editingUser}
        isOpen={editingUser !== null}
        onClose={() => setEditingUser(null)}
        onSuccess={() => loadUsers()}
      />
    </div>
  );
}
