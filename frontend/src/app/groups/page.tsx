"use client";

import React, { useEffect, useState } from "react";
import { X, RefreshCw } from "lucide-react";
import { toast } from "@/components/shared/Toast";
import {
  ZaloGroupItem,
  getGroups,
  updateGroupSendMode,
  updateRealGroupStatus,
  createGroup,
  deleteGroup,
  getGroupDetail,
} from "@/lib/api";

export default function GroupsManagementPage() {
  const [groups, setGroups] = useState<ZaloGroupItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState("");
  const [sendModeFilter, setSendModeFilter] = useState<string>("");
  const [roleFilter, setRoleFilter] = useState<string>("");

  // Action states
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null);

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newZaloId, setNewZaloId] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("DESTINATION");
  const [newSendMode, setNewSendMode] = useState<"AUTO" | "MANUAL">("AUTO");
  const [submittingCreate, setSubmittingCreate] = useState(false);

  // Edit Modal
  const [editingGroup, setEditingGroup] = useState<ZaloGroupItem | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState("DESTINATION");
  const [editSendMode, setEditSendMode] = useState<"AUTO" | "MANUAL">("AUTO");
  const [editIsActive, setEditIsActive] = useState(true);
  const [submittingEdit, setSubmittingEdit] = useState(false);

  // Delete Confirm Modal
  const [deletingGroup, setDeletingGroup] = useState<ZaloGroupItem | null>(null);
  const [submittingDelete, setSubmittingDelete] = useState(false);

  // Detail Modal
  const [detailGroup, setDetailGroup] = useState<(ZaloGroupItem & { zalo_live_info?: any }) | null>(null);

  const loadGroupsList = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await getGroups({
        search: searchTerm || undefined,
        send_mode: sendModeFilter || undefined,
        role: roleFilter || undefined,
        limit: 100,
      });

      // Chỉ hiển thị nhóm thật
      const list = (res.groups || []).filter((g) => !g.is_test);
      setGroups(list);
    } catch (err: unknown) {
      const e = err as Error;
      const msg = e.message || "Lỗi khi tải danh sách nhóm Zalo";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGroupsList();
  }, [sendModeFilter, roleFilter]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadGroupsList();
  };

  const handleToggleSendMode = async (group: ZaloGroupItem) => {
    const isAuto = (group.send_mode || "").toUpperCase() === "AUTO";
    const newMode = isAuto ? "MANUAL" : "AUTO";
    try {
      setTogglingId(group.id);
      const res = await updateGroupSendMode(group.id, newMode);
      setGroups((prev) =>
        prev.map((g) =>
          g.id === group.id
            ? {
                ...g,
                send_mode: newMode,
                send_mode_label: newMode === "AUTO" ? "Tự động" : "Chờ duyệt",
              }
            : g
        )
      );
      toast.success(res.message || `Đã chuyển sang ${newMode === "AUTO" ? "Tự động gửi" : "Chờ duyệt"}`);
    } catch (err: unknown) {
      const e = err as Error;
      toast.error(e.message || "Lỗi khi đổi chế độ gửi");
    } finally {
      setTogglingId(null);
    }
  };

  const handleOpenDetail = async (groupId: string) => {
    try {
      setLoadingDetailId(groupId);
      const res = await getGroupDetail(groupId);
      setDetailGroup(res.group);
    } catch (err: unknown) {
      const e = err as Error;
      toast.error(e.message || "Lỗi khi tải chi tiết nhóm");
    } finally {
      setLoadingDetailId(null);
    }
  };

  const handleOpenEdit = (group: ZaloGroupItem) => {
    setEditingGroup(group);
    setEditName(group.name || "");
    setEditRole((group.group_role || "DESTINATION").toUpperCase());
    setEditSendMode((group.send_mode || "").toUpperCase() === "AUTO" ? "AUTO" : "MANUAL");
    setEditIsActive(group.is_active);
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingGroup) return;

    try {
      setSubmittingEdit(true);
      const res = await updateRealGroupStatus(editingGroup.id, {
        name: editName.trim(),
        group_role: editRole,
        send_mode: editSendMode,
        is_active: editIsActive,
      });
      setEditingGroup(null);
      toast.success(res.message || "Cập nhật thông tin nhóm thành công");
      loadGroupsList();
    } catch (err: unknown) {
      const e = err as Error;
      toast.error(e.message || "Lỗi khi lưu thông tin nhóm");
    } finally {
      setSubmittingEdit(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deletingGroup) return;
    try {
      setSubmittingDelete(true);
      const res = await deleteGroup(deletingGroup.id);
      setDeletingGroup(null);
      toast.success(res.message || "Đã xóa nhóm Zalo thành công");
      loadGroupsList();
    } catch (err: unknown) {
      const e = err as Error;
      toast.error(e.message || "Lỗi khi xóa nhóm");
    } finally {
      setSubmittingDelete(false);
    }
  };

  const handleCreateGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newZaloId.trim()) {
      toast.error("Vui lòng nhập Zalo Group ID");
      return;
    }
    try {
      setSubmittingCreate(true);
      const res = await createGroup({
        zalo_group_id: newZaloId.trim(),
        name: newName.trim() || undefined,
        group_role: newRole,
        send_mode: newSendMode,
        is_active: true,
        is_test: false,
      });
      setIsCreateModalOpen(false);
      setNewZaloId("");
      setNewName("");
      toast.success(res.message || "Đã thêm nhóm Zalo mới thành công");
      loadGroupsList();
    } catch (err: unknown) {
      const e = err as Error;
      toast.error(e.message || "Lỗi khi tạo nhóm mới");
    } finally {
      setSubmittingCreate(false);
    }
  };

  const getRoleBadge = (role: string) => {
    const r = (role || "").toUpperCase();
    if (r === "DESTINATION" || r === "CUSTOMER" || r === "KHÁCH HÀNG") {
      return <span className="text-slate-800 font-medium">Khách hàng</span>;
    }
    if (r === "SOURCE" || r === "CARRIER" || r === "NHÀ XE") {
      return <span className="text-slate-800 font-medium">Nhà xe</span>;
    }
    if (r === "DHVT" || r === "INTERNAL" || r === "NỘI BỘ") {
      return <span className="text-slate-800 font-medium">Nội bộ ĐHVT</span>;
    }
    return <span className="text-slate-700">{role}</span>;
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <div>
          <h1 className="text-base font-bold text-slate-900 uppercase">Quản Lý Nhóm Zalo</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Cấu hình chế độ phát hành tin và trạng thái hoạt động của các nhóm
          </p>
        </div>
        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => setIsCreateModalOpen(true)}
            className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-sm text-xs font-medium transition"
          >
            Thêm nhóm Zalo
          </button>
          <button
            type="button"
            onClick={loadGroupsList}
            disabled={loading}
            className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-sm text-xs font-medium transition"
          >
            {loading ? "Đang tải..." : "Làm mới"}
          </button>
        </div>
      </div>

      {/* Error alert */}
      {error && (
        <div className="bg-slate-50 border border-slate-300 text-slate-800 p-3 rounded-sm text-xs flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-slate-500 hover:text-slate-900">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Toolbar Filter */}
      <form
        onSubmit={handleSearch}
        className="bg-white border border-slate-200 p-3 rounded-sm flex flex-col sm:flex-row items-center justify-between gap-3 text-xs"
      >
        <div className="w-full sm:w-80">
          <input
            type="text"
            placeholder="Tìm theo tên nhóm hoặc Zalo Group ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-slate-900 focus:outline-none focus:border-slate-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-800 focus:outline-none focus:border-slate-500 text-xs"
          >
            <option value="">Tất cả vai trò</option>
            <option value="DESTINATION">Khách hàng</option>
            <option value="SOURCE">Nhà xe</option>
            <option value="DHVT">Nội bộ ĐHVT</option>
          </select>

          <select
            value={sendModeFilter}
            onChange={(e) => setSendModeFilter(e.target.value)}
            className="bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-800 focus:outline-none focus:border-slate-500 text-xs"
          >
            <option value="">Tất cả chế độ gửi</option>
            <option value="AUTO">Tự động gửi</option>
            <option value="MANUAL">Chờ duyệt</option>
          </select>

          <button
            type="submit"
            className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-sm font-medium text-xs transition"
          >
            Lọc
          </button>
        </div>
      </form>

      {/* Data Table */}
      <div className="bg-white border border-slate-200 rounded-sm overflow-hidden">
        <div className="p-2.5 border-b border-slate-200 text-xs text-slate-500 flex items-center justify-between">
          <span>
            Hiển thị <strong className="text-slate-900">{groups.length}</strong> nhóm
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-50 text-slate-700 font-semibold border-b border-slate-200 whitespace-nowrap">
              <tr>
                <th className="py-2.5 px-3">Tên nhóm</th>
                <th className="py-2.5 px-3">Vai trò</th>
                <th className="py-2.5 px-3 text-center">Trạng thái</th>
                <th className="py-2.5 px-3 text-center">Chế độ gửi</th>
                <th className="py-2.5 px-3 text-right">Hành động</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 font-normal">
              {loading ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-slate-500">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-1 text-slate-400" />
                    <span>Đang tải danh sách nhóm Zalo...</span>
                  </td>
                </tr>
              ) : groups.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-slate-500">
                    Không tìm thấy nhóm Zalo nào phù hợp.
                  </td>
                </tr>
              ) : (
                groups.map((g) => {
                  const isAuto = (g.send_mode || "").toUpperCase() === "AUTO";
                  const isToggling = togglingId === g.id;
                  const isLoadingDetail = loadingDetailId === g.id;

                  return (
                    <tr key={g.id} className="hover:bg-slate-50 transition">
                      {/* Tên nhóm */}
                      <td className="py-2.5 px-3">
                        <div className="font-semibold text-slate-900">
                          {g.name || "Chưa đặt tên nhóm"}
                        </div>
                        <div className="font-mono text-[11px] text-slate-500 mt-0.5">
                          ID: {g.zalo_group_id}
                        </div>
                      </td>

                      {/* Vai trò */}
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        {getRoleBadge(g.group_role)}
                      </td>

                      {/* Trạng thái hoạt động */}
                      <td className="py-2.5 px-3 text-center whitespace-nowrap">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-sm text-[11px] font-medium ${
                            g.is_active
                              ? "bg-slate-100 text-slate-800 border border-slate-300"
                              : "bg-slate-50 text-slate-400 border border-slate-200"
                          }`}
                        >
                          {g.is_active ? "Hoạt động" : "Tạm dừng"}
                        </span>
                      </td>

                      {/* Chế độ gửi tin */}
                      <td className="py-2.5 px-3 text-center whitespace-nowrap">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-sm text-[11px] font-medium ${
                            isAuto
                              ? "bg-slate-900 text-white"
                              : "bg-white text-slate-700 border border-slate-300"
                          }`}
                        >
                          {isAuto ? "Tự động gửi" : "Chờ duyệt"}
                        </span>
                      </td>

                      {/* Hành động */}
                      <td className="py-2.5 px-3 text-right whitespace-nowrap space-x-1.5">
                        <button
                          type="button"
                          onClick={() => handleOpenDetail(g.id)}
                          disabled={isLoadingDetail}
                          className="px-2 py-1 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-sm text-[11px] font-medium transition disabled:opacity-50"
                        >
                          {isLoadingDetail ? "Đang mở..." : "Xem chi tiết"}
                        </button>

                        <button
                          type="button"
                          onClick={() => handleToggleSendMode(g)}
                          disabled={isToggling}
                          className="px-2 py-1 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-sm text-[11px] font-medium transition disabled:opacity-50"
                        >
                          {isAuto ? "Chuyển Chờ duyệt" : "Bật Tự động"}
                        </button>

                        <button
                          type="button"
                          onClick={() => handleOpenEdit(g)}
                          className="px-2 py-1 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-sm text-[11px] font-medium transition"
                        >
                          Sửa
                        </button>

                        <button
                          type="button"
                          onClick={() => setDeletingGroup(g)}
                          className="px-2 py-1 bg-white border border-slate-300 hover:bg-slate-50 text-slate-500 hover:text-slate-900 rounded-sm text-[11px] font-medium transition"
                        >
                          Xóa
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal Xem Chi Tiết Thông Tin Nhóm */}
      {detailGroup && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setDetailGroup(null)}
        >
          <div
            className="bg-white border border-slate-300 rounded-sm max-w-lg w-full p-5 text-xs text-slate-800"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900">
                Thông Tin Nhóm: {detailGroup.name || detailGroup.zalo_group_id}
              </h3>
              <button
                type="button"
                onClick={() => setDetailGroup(null)}
                className="text-slate-400 hover:text-slate-900"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 py-3 border-b border-slate-200">
              <div>
                <span className="text-slate-500 block">Zalo Group ID:</span>
                <span className="font-mono font-semibold text-slate-900">{detailGroup.zalo_group_id}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Vai trò:</span>
                <span className="font-medium text-slate-900">{getRoleBadge(detailGroup.group_role)}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Chế độ gửi:</span>
                <span className="font-medium text-slate-900">{detailGroup.send_mode_label}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Trạng thái:</span>
                <span className="font-medium text-slate-900">{detailGroup.is_active ? "Hoạt động" : "Tạm dừng"}</span>
              </div>
            </div>

            {/* Thông tin trực tiếp từ Zalo API (thành viên) */}
            <div className="mt-3">
              <div className="text-slate-500 font-semibold mb-2">
                Thành viên trong nhóm ({detailGroup.zalo_live_info?.total_members || 0} thành viên):
              </div>
              {detailGroup.zalo_live_info?.members?.length > 0 ? (
                <div className="max-h-48 overflow-y-auto space-y-1.5 border border-slate-200 p-2 rounded-sm bg-slate-50">
                  {detailGroup.zalo_live_info.members.map((m: any) => (
                    <div key={m.id} className="flex items-center justify-between text-xs py-1 border-b border-slate-200 last:border-none">
                      <span className="font-medium text-slate-800">{m.display_name}</span>
                      <span className="font-mono text-slate-500 text-[11px]">UID: {m.id}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-slate-500 text-xs italic">
                  Không có thông tin thành viên realtime (bot chưa kết nối WebSocket hoặc nhóm riêng tư).
                </div>
              )}
            </div>

            <div className="mt-4 pt-3 border-t border-slate-200 flex justify-end">
              <button
                type="button"
                onClick={() => setDetailGroup(null)}
                className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-sm text-xs font-medium"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Chỉnh Sửa Nhóm */}
      {editingGroup && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-300 rounded-sm max-w-md w-full p-5 text-xs text-slate-800">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900">
                Sửa Nhóm
              </h3>
              <button onClick={() => setEditingGroup(null)}>
                <X className="w-4 h-4 text-slate-400 hover:text-slate-900" />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="space-y-3 mt-3">
              <div>
                <label className="block text-slate-600 mb-1 font-medium">Zalo Group ID:</label>
                <input
                  type="text"
                  disabled
                  value={editingGroup.zalo_group_id}
                  className="w-full bg-slate-100 border border-slate-200 rounded-sm px-3 py-1.5 text-slate-600 font-mono cursor-not-allowed"
                />
              </div>

              <div>
                <label className="block text-slate-600 mb-1 font-medium">Tên nhóm:</label>
                <input
                  type="text"
                  required
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-slate-900 focus:outline-none focus:border-slate-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-600 mb-1 font-medium">Vai trò:</label>
                  <select
                    value={editRole}
                    onChange={(e) => setEditRole(e.target.value)}
                    className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-slate-500"
                  >
                    <option value="DESTINATION">Khách hàng</option>
                    <option value="SOURCE">Nhà xe</option>
                    <option value="DHVT">Nội bộ ĐHVT</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-600 mb-1 font-medium">Chế độ gửi:</label>
                  <select
                    value={editSendMode}
                    onChange={(e) => setEditSendMode(e.target.value as "AUTO" | "MANUAL")}
                    className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-slate-500 font-medium"
                  >
                    <option value="AUTO">Tự động gửi</option>
                    <option value="MANUAL">Chờ duyệt</option>
                  </select>
                </div>
              </div>

              <div className="pt-1">
                <label className="flex items-center space-x-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editIsActive}
                    onChange={(e) => setEditIsActive(e.target.checked)}
                    className="w-4 h-4 rounded text-slate-900 focus:ring-0"
                  />
                  <span className="text-slate-700">Kích hoạt nhóm</span>
                </label>
              </div>

              <div className="flex items-center justify-end space-x-2 pt-3 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => setEditingGroup(null)}
                  className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-sm transition"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submittingEdit}
                  className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-sm font-medium transition"
                >
                  {submittingEdit ? "Đang lưu..." : "Lưu thay đổi"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Xác Nhận Xóa */}
      {deletingGroup && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-300 rounded-sm max-w-sm w-full p-5 text-xs text-slate-800">
            <h3 className="text-sm font-bold text-slate-900">Xác nhận xóa nhóm</h3>
            <p className="text-slate-600 mt-2">
              Bạn có chắc chắn muốn xóa nhóm <strong>{deletingGroup.name || deletingGroup.zalo_group_id}</strong>?
            </p>
            <div className="flex items-center justify-end space-x-2 mt-4 pt-3 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setDeletingGroup(null)}
                className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-sm transition"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={submittingDelete}
                className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-sm font-medium transition"
              >
                {submittingDelete ? "Đang xóa..." : "Xóa nhóm"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Thêm Nhóm Zalo */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-300 rounded-sm max-w-md w-full p-5 text-xs text-slate-800">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900">Thêm Nhóm Zalo</h3>
              <button onClick={() => setIsCreateModalOpen(false)}>
                <X className="w-4 h-4 text-slate-400 hover:text-slate-900" />
              </button>
            </div>

            <form onSubmit={handleCreateGroup} className="space-y-3 mt-3">
              <div>
                <label className="block text-slate-600 mb-1 font-medium">Zalo Group ID:</label>
                <input
                  type="text"
                  required
                  placeholder="VD: 6469608867469758994"
                  value={newZaloId}
                  onChange={(e) => setNewZaloId(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-slate-900 font-mono focus:outline-none focus:border-slate-500"
                />
              </div>

              <div>
                <label className="block text-slate-600 mb-1 font-medium">Tên nhóm:</label>
                <input
                  type="text"
                  placeholder="VD: Khách 1"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-slate-900 focus:outline-none focus:border-slate-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-600 mb-1 font-medium">Vai trò:</label>
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value)}
                    className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-slate-500"
                  >
                    <option value="DESTINATION">Khách hàng</option>
                    <option value="SOURCE">Nhà xe</option>
                    <option value="DHVT">Nội bộ ĐHVT</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-600 mb-1 font-medium">Chế độ gửi:</label>
                  <select
                    value={newSendMode}
                    onChange={(e) => setNewSendMode(e.target.value as "AUTO" | "MANUAL")}
                    className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-slate-500 font-medium"
                  >
                    <option value="AUTO">Tự động gửi</option>
                    <option value="MANUAL">Chờ duyệt</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center justify-end space-x-2 pt-3 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-sm transition"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submittingCreate}
                  className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-sm font-medium transition"
                >
                  {submittingCreate ? "Đang thêm..." : "Thêm nhóm"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
