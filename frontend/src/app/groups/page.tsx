"use client";

import React, { useEffect, useState } from "react";
import {
  Users,
  RefreshCw,
  Search,
  Plus,
  Clock,
  CheckCircle2,
  AlertTriangle,
  X,
  Copy,
  Check,
  SlidersHorizontal,
  Trash2,
  Edit,
  Power,
  ShieldAlert,
} from "lucide-react";
import {
  ZaloGroupItem,
  getGroups,
  updateGroupSendMode,
  updateRealGroupStatus,
  createGroup,
  deleteAllTestGroups,
  deleteGroup,
} from "@/lib/api";

export default function GroupsManagementPage() {
  const [groups, setGroups] = useState<ZaloGroupItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState("");
  const [sendModeFilter, setSendModeFilter] = useState<string>("");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [testFilter, setTestFilter] = useState<string>("real_only"); // 'all', 'real_only', 'test_only'

  // Action states
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [togglingActiveId, setTogglingActiveId] = useState<number | null>(null);
  const [deletingTestGroups, setDeletingTestGroups] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // New Group Modal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newZaloId, setNewZaloId] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("destination");
  const [newSendMode, setNewSendMode] = useState<"tu_dong" | "cho_duyet">("tu_dong");
  const [submittingNew, setSubmittingNew] = useState(false);

  // Edit Group Modal
  const [editingGroup, setEditingGroup] = useState<ZaloGroupItem | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState("destination");
  const [editSendMode, setEditSendMode] = useState<"tu_dong" | "cho_duyet">("tu_dong");
  const [editIsActive, setEditIsActive] = useState(true);
  const [editIsTest, setEditIsTest] = useState(false);
  const [submittingEdit, setSubmittingEdit] = useState(false);

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

      let list = res.groups || [];
      if (testFilter === "real_only") {
        list = list.filter((g) => !g.is_test);
      } else if (testFilter === "test_only") {
        list = list.filter((g) => g.is_test);
      }

      setGroups(list);
      setTotal(res.total || 0);
    } catch (err: unknown) {
      const e = err as Error;
      setError(e.message || "Lỗi khi tải danh sách nhóm Zalo");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGroupsList();
  }, [sendModeFilter, roleFilter, testFilter]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadGroupsList();
  };

  // Toggle nhanh Chế độ gửi (Tự động <-> Chờ duyệt)
  const handleToggleSendMode = async (group: ZaloGroupItem) => {
    const nextMode = group.send_mode === "tu_dong" ? "cho_duyet" : "tu_dong";
    try {
      setTogglingId(group.id);
      setError(null);
      const res = await updateGroupSendMode(group.id, nextMode);
      setSuccessMsg(res.message);
      setGroups((prev) =>
        prev.map((g) =>
          g.id === group.id
            ? {
                ...g,
                send_mode: res.send_mode,
                send_mode_label: res.send_mode_label,
              }
            : g
        )
      );
      setTimeout(() => setSuccessMsg(null), 3500);
    } catch (err: unknown) {
      const e = err as Error;
      setError(e.message || `Lỗi khi chuyển trạng thái nhóm #${group.id}`);
    } finally {
      setTogglingId(null);
    }
  };

  // Toggle nhanh Trạng thái hoạt động (Active <-> Inactive)
  const handleToggleActive = async (group: ZaloGroupItem) => {
    const nextActive = !group.is_active;
    try {
      setTogglingActiveId(group.id);
      setError(null);
      const res = await updateRealGroupStatus(group.id, { is_active: nextActive });
      setSuccessMsg(`Đã ${nextActive ? "kích hoạt" : "tạm dừng"} nhóm '${group.name || group.zalo_group_id}'`);
      setGroups((prev) =>
        prev.map((g) => (g.id === group.id ? { ...g, is_active: nextActive } : g))
      );
      setTimeout(() => setSuccessMsg(null), 3500);
    } catch (err: unknown) {
      const e = err as Error;
      setError(e.message || `Lỗi khi đổi trạng thái kích hoạt nhóm #${group.id}`);
    } finally {
      setTogglingActiveId(null);
    }
  };

  // Mở modal chỉnh sửa chi tiết nhóm thật
  const handleOpenEditModal = (group: ZaloGroupItem) => {
    setEditingGroup(group);
    setEditName(group.name || "");
    setEditRole(group.group_role || "destination");
    setEditSendMode(group.send_mode === "tu_dong" ? "tu_dong" : "cho_duyet");
    setEditIsActive(group.is_active);
    setEditIsTest(group.is_test);
  };

  // Lưu chỉnh sửa nhóm thật
  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingGroup) return;

    try {
      setSubmittingEdit(true);
      setError(null);
      const res = await updateRealGroupStatus(editingGroup.id, {
        name: editName.trim(),
        group_role: editRole,
        send_mode: editSendMode,
        is_active: editIsActive,
        is_test: editIsTest,
      });

      setSuccessMsg(res.message);
      setEditingGroup(null);
      loadGroupsList();
      setTimeout(() => setSuccessMsg(null), 3500);
    } catch (err: unknown) {
      const e = err as Error;
      alert(e.message || "Lỗi khi lưu trạng thái nhóm");
    } finally {
      setSubmittingEdit(false);
    }
  };

  // Xóa toàn bộ nhóm test
  const handleDeleteAllTests = async () => {
    if (!confirm("Bạn có chắc chắn muốn XÓA TẤT CẢ CÁC NHÓM THỬ NGHIỆM (Test Groups)? Thao tác này sẽ chỉ giữ lại nhóm thật.")) {
      return;
    }
    try {
      setDeletingTestGroups(true);
      setError(null);
      const res = await deleteAllTestGroups();
      setSuccessMsg(res.message);
      loadGroupsList();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: unknown) {
      const e = err as Error;
      setError(e.message || "Lỗi khi xóa danh sách nhóm test");
    } finally {
      setDeletingTestGroups(false);
    }
  };

  // Xóa nhóm riêng lẻ
  const handleDeleteSingleGroup = async (group: ZaloGroupItem) => {
    if (!confirm(`Bạn có chắc muốn xóa nhóm '${group.name || group.zalo_group_id}' (ID: ${group.id})?`)) {
      return;
    }
    try {
      setError(null);
      const res = await deleteGroup(group.id);
      setSuccessMsg(res.message);
      loadGroupsList();
      setTimeout(() => setSuccessMsg(null), 3500);
    } catch (err: unknown) {
      const e = err as Error;
      alert(e.message || `Lỗi khi xóa nhóm #${group.id}`);
    }
  };

  // Tạo nhóm mới
  const handleCreateGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newZaloId.trim()) {
      alert("Vui lòng nhập Zalo Group ID");
      return;
    }
    try {
      setSubmittingNew(true);
      setError(null);
      const res = await createGroup({
        zalo_group_id: newZaloId.trim(),
        name: newName.trim() || undefined,
        group_role: newRole,
        send_mode: newSendMode,
        is_active: true,
        is_test: false,
      });
      setSuccessMsg(res.message);
      setIsModalOpen(false);
      setNewZaloId("");
      setNewName("");
      loadGroupsList();
      setTimeout(() => setSuccessMsg(null), 3500);
    } catch (err: unknown) {
      const e = err as Error;
      alert(e.message || "Lỗi khi tạo nhóm mới");
    } finally {
      setSubmittingNew(false);
    }
  };

  const handleCopy = (text: string) => {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(text);
      setCopiedId(text);
      setTimeout(() => setCopiedId(null), 2000);
    }
  };

  // KPIs
  const realCount = groups.filter((g) => !g.is_test).length;
  const autoCount = groups.filter((g) => g.send_mode === "tu_dong").length;
  const reviewCount = groups.filter((g) => g.send_mode === "cho_duyet").length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            <Users className="w-6 h-6 text-blue-400" />
            <span>Quản Lý Nhóm Zalo & Cập Nhật Trạng Thái Nhóm Thật</span>
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Cấu hình chế độ phát hành tin (Tự động gửi / Chờ ĐHVT duyệt) và trạng thái hoạt động của các Nhóm Khách Hàng thực tế
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Nút Xóa tất cả nhóm test */}
          <button
            type="button"
            disabled={deletingTestGroups}
            onClick={handleDeleteAllTests}
            className="flex items-center space-x-1.5 px-3 py-2 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/40 rounded-lg text-xs font-semibold shadow-sm transition disabled:opacity-50"
            title="Dọn sạch toàn bộ nhóm thử nghiệm test/pytest/direct để chỉ giữ lại nhóm thật"
          >
            <Trash2 className={`w-4 h-4 ${deletingTestGroups ? "animate-spin" : ""}`} />
            <span>{deletingTestGroups ? "Đang xóa..." : "Xóa tất cả nhóm test"}</span>
          </button>

          {/* Thêm nhóm mới */}
          <button
            type="button"
            onClick={() => setIsModalOpen(true)}
            className="flex items-center space-x-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-sm transition"
          >
            <Plus className="w-4 h-4" />
            <span>Thêm nhóm Zalo</span>
          </button>

          {/* Làm mới */}
          <button
            type="button"
            onClick={loadGroupsList}
            disabled={loading}
            className="flex items-center space-x-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {/* Notifications */}
      {successMsg && (
        <div className="p-3 bg-emerald-950/50 border border-emerald-600 rounded-lg text-emerald-200 text-xs flex items-center justify-between shadow-lg">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)}>
            <X className="w-3.5 h-3.5 text-emerald-400 hover:text-white" />
          </button>
        </div>
      )}

      {error && (
        <div className="p-3 bg-rose-950/50 border border-rose-700 rounded-lg text-rose-200 text-xs flex items-center justify-between shadow-lg">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)}>
            <X className="w-3.5 h-3.5 text-rose-400 hover:text-white" />
          </button>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-400 font-medium">Nhóm Thật Đang Vận Hành</div>
            <div className="text-2xl font-bold text-white mt-1">{realCount}</div>
            <div className="text-[11px] text-slate-500 mt-0.5">Nhóm Zalo kết nối khách hàng & nhà xe</div>
          </div>
          <div className="p-3 bg-blue-500/10 rounded-xl border border-blue-500/20 text-blue-400">
            <Users className="w-6 h-6" />
          </div>
        </div>

        <div className="bg-slate-900 border border-emerald-900/40 rounded-xl p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-emerald-400 font-medium flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>Chế Độ: Tự Động Gửi (tu_dong)</span>
            </div>
            <div className="text-2xl font-bold text-emerald-300 mt-1">{autoCount}</div>
            <div className="text-[11px] text-emerald-500/80 mt-0.5">Gửi thẳng tới Zalo khi dữ liệu hợp lệ</div>
          </div>
          <div className="p-3 bg-emerald-500/10 rounded-xl border border-emerald-500/20 text-emerald-400">
            <CheckCircle2 className="w-6 h-6" />
          </div>
        </div>

        <div className="bg-slate-900 border border-amber-900/40 rounded-xl p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-amber-400 font-medium flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-400"></span>
              <span>Chế Độ: Chờ Duyệt (cho_duyet)</span>
            </div>
            <div className="text-2xl font-bold text-amber-300 mt-1">{reviewCount}</div>
            <div className="text-[11px] text-amber-500/80 mt-0.5">Bắt buộc ĐHVT duyệt trước khi gửi khách</div>
          </div>
          <div className="p-3 bg-amber-500/10 rounded-xl border border-amber-500/20 text-amber-400">
            <Clock className="w-6 h-6" />
          </div>
        </div>
      </div>

      {/* Toolbar Filter */}
      <form
        onSubmit={handleSearch}
        className="bg-slate-900 border border-slate-800 p-4 rounded-xl flex flex-col sm:flex-row items-center justify-between gap-3 text-xs"
      >
        <div className="relative flex-1 w-full sm:w-auto">
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Tìm theo tên nhóm hoặc Zalo Group ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-white focus:outline-none focus:border-blue-500 text-xs"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <select
            value={testFilter}
            onChange={(e) => setTestFilter(e.target.value)}
            className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs font-medium"
          >
            <option value="real_only">⭐ Chỉ hiển thị Nhóm Thật</option>
            <option value="all">Tất cả nhóm</option>
            <option value="test_only">🧪 Chỉ nhóm test/nội bộ</option>
          </select>

          <select
            value={sendModeFilter}
            onChange={(e) => setSendModeFilter(e.target.value)}
            className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
          >
            <option value="">Tất cả chế độ gửi</option>
            <option value="tu_dong">🟢 Tự động gửi (tu_dong)</option>
            <option value="cho_duyet">⏳ Chờ duyệt (cho_duyet)</option>
          </select>

          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
          >
            <option value="">Tất cả vai trò</option>
            <option value="destination">Khách hàng (Đích)</option>
            <option value="source">Nhà xe (Nguồn)</option>
            <option value="internal">Nội bộ điều vận (ĐHVT)</option>
          </select>

          <button
            type="submit"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium text-xs transition"
          >
            Lọc
          </button>
        </div>
      </form>

      {/* Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="p-3 border-b border-slate-800 text-xs text-slate-400 flex items-center justify-between">
          <span>
            Đang hiển thị <strong className="text-white">{groups.length}</strong> nhóm
          </span>
          <span className="text-slate-500">
            💡 Nhấn &quot;Cập nhật&quot; để đổi tên hoặc thiết lập chi tiết nhóm thật • Nhấn nút gạt để đổi trạng thái nhanh
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-950/80 sticky top-0 text-slate-300 font-semibold border-b border-slate-800 whitespace-nowrap">
              <tr>
                <th className="py-3 px-3">ID</th>
                <th className="py-3 px-4">Tên nhóm & Định danh</th>
                <th className="py-3 px-3">Zalo Group ID</th>
                <th className="py-3 px-3">Vai trò</th>
                <th className="py-3 px-3 text-center">Hoạt động</th>
                <th className="py-3 px-3 text-center">Chế độ gửi tin</th>
                <th className="py-3 px-3 text-center min-w-[200px]">Hành động</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-normal">
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-blue-500" />
                    <span>Đang tải danh sách nhóm Zalo...</span>
                  </td>
                </tr>
              ) : groups.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    Không tìm thấy nhóm Zalo nào phù hợp với bộ lọc.
                  </td>
                </tr>
              ) : (
                groups.map((g) => {
                  const isAuto = g.send_mode === "tu_dong";
                  const isToggling = togglingId === g.id;
                  const isTogglingActive = togglingActiveId === g.id;

                  return (
                    <tr key={g.id} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-3 font-mono text-slate-400">#{g.id}</td>

                      <td className="py-3 px-4">
                        <div className="font-semibold text-white text-sm flex items-center gap-2">
                          <span>{g.name || "Chưa đặt tên nhóm"}</span>
                          {!g.is_test ? (
                            <span className="text-[10px] text-emerald-300 bg-emerald-950/80 px-2 py-0.5 rounded font-semibold border border-emerald-700/60 flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                              NHÓM THẬT
                            </span>
                          ) : (
                            <span className="text-[10px] text-amber-300 bg-amber-950/80 px-2 py-0.5 rounded font-semibold border border-amber-700/60">
                              TEST
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-400 mt-1 flex items-center gap-3">
                          {g.carrier_name && <span>Nhà xe: <strong className="text-slate-200">{g.carrier_name}</strong></span>}
                          {g.created_at && (
                            <span className="text-slate-500">Tạo: {new Date(g.created_at).toLocaleDateString("vi-VN")}</span>
                          )}
                        </div>
                      </td>

                      <td className="py-3 px-3 font-mono whitespace-nowrap">
                        <div className="flex items-center space-x-1.5">
                          <span className="bg-slate-950 px-2.5 py-1 rounded text-emerald-400 font-bold border border-slate-800">
                            {g.zalo_group_id}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleCopy(g.zalo_group_id)}
                            className="p-1 text-slate-400 hover:text-white transition"
                            title="Sao chép Zalo Group ID"
                          >
                            {copiedId === g.zalo_group_id ? (
                              <Check className="w-3.5 h-3.5 text-emerald-400" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                      </td>

                      <td className="py-3 px-3 whitespace-nowrap">
                        <span
                          className={`px-2.5 py-1 rounded text-[11px] font-semibold ${
                            g.group_role === "destination"
                              ? "bg-purple-950/60 text-purple-300 border border-purple-800/60"
                              : g.group_role === "source"
                              ? "bg-blue-950/60 text-blue-300 border border-blue-800/60"
                              : "bg-slate-800 text-slate-300 border border-slate-700"
                          }`}
                        >
                          {g.group_role === "destination"
                            ? "Khách hàng (Đích)"
                            : g.group_role === "source"
                            ? "Nhà xe (Nguồn)"
                            : g.group_role === "internal"
                            ? "Nội bộ ĐHVT"
                            : g.group_role}
                        </span>
                      </td>

                      {/* Trạng thái Hoạt Động (is_active) */}
                      <td className="py-3 px-3 text-center whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => handleToggleActive(g)}
                          disabled={isTogglingActive}
                          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold transition ${
                            g.is_active
                              ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/25"
                              : "bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700"
                          }`}
                          title="Nhấn để Bật/Tắt trạng thái hoạt động"
                        >
                          <Power className={`w-3 h-3 ${g.is_active ? "text-emerald-400" : "text-slate-500"}`} />
                          <span>{g.is_active ? "Hoạt động" : "Tạm dừng"}</span>
                        </button>
                      </td>

                      {/* Trạng thái Chế độ gửi (send_mode) */}
                      <td className="py-3 px-3 text-center whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
                            isAuto
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                              : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                          }`}
                        >
                          <span
                            className={`w-2 h-2 rounded-full ${
                              isAuto ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
                            }`}
                          ></span>
                          <span>{isAuto ? "Tự động gửi" : "Chờ duyệt"}</span>
                        </span>
                      </td>

                      {/* Hành động */}
                      <td className="py-3 px-3 text-center whitespace-nowrap">
                        <div className="inline-flex items-center space-x-1.5">
                          {/* Nút Chuyển đổi nhanh chế độ gửi */}
                          <button
                            type="button"
                            onClick={() => handleToggleSendMode(g)}
                            disabled={isToggling}
                            className={`inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                              isAuto
                                ? "bg-amber-950/60 hover:bg-amber-900 text-amber-300 border border-amber-800/60"
                                : "bg-emerald-950/60 hover:bg-emerald-900 text-emerald-300 border border-emerald-800/60"
                            } disabled:opacity-50`}
                            title={`Chuyển sang ${isAuto ? "Chờ duyệt" : "Tự động gửi"}`}
                          >
                            {isToggling ? (
                              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <SlidersHorizontal className="w-3.5 h-3.5" />
                            )}
                            <span>{isAuto ? "Chuyển Chờ duyệt" : "Bật Tự động"}</span>
                          </button>

                          {/* Nút Cập nhật chi tiết */}
                          <button
                            type="button"
                            onClick={() => handleOpenEditModal(g)}
                            className="inline-flex items-center space-x-1 px-2.5 py-1 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/40 rounded-lg text-xs font-medium transition"
                            title="Cập nhật tên nhóm, vai trò, chế độ gửi"
                          >
                            <Edit className="w-3.5 h-3.5" />
                            <span>Cập nhật</span>
                          </button>

                          {/* Nút Xóa nhóm */}
                          <button
                            type="button"
                            onClick={() => handleDeleteSingleGroup(g)}
                            className="p-1 text-slate-500 hover:text-rose-400 transition rounded"
                            title="Xóa nhóm này"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal Cập Nhật Trạng Thái Nhóm Thật */}
      {editingGroup && (
        <div className="fixed inset-0 bg-black/75 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 text-xs text-slate-300 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Edit className="w-5 h-5 text-blue-400" />
                <span>Cập Nhật Trạng Thái Nhóm #{editingGroup.id}</span>
              </h3>
              <button onClick={() => setEditingGroup(null)}>
                <X className="w-5 h-5 text-slate-400 hover:text-white" />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="space-y-4 mt-4">
              <div>
                <label className="block text-slate-400 mb-1 font-semibold">
                  Zalo Group ID (bất biến):
                </label>
                <input
                  type="text"
                  disabled
                  value={editingGroup.zalo_group_id}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-emerald-400 font-mono opacity-80 cursor-not-allowed"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-semibold">
                  Tên gợi nhớ nhóm khách hàng / nhà xe:
                </label>
                <input
                  type="text"
                  required
                  placeholder="Ví dụ: Nhóm Khách Hàng Logitem - Tân Quang"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500 text-sm"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 mb-1 font-semibold">Vai trò nhóm:</label>
                  <select
                    value={editRole}
                    onChange={(e) => setEditRole(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="destination">Khách hàng (Đích nhận tin)</option>
                    <option value="source">Nhà xe (Nguồn gửi tin)</option>
                    <option value="internal">Nội bộ điều vận (ĐHVT)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-semibold">Chế độ gửi tin (send_mode):</label>
                  <select
                    value={editSendMode}
                    onChange={(e) => setEditSendMode(e.target.value as "tu_dong" | "cho_duyet")}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-semibold"
                  >
                    <option value="tu_dong">🟢 Tự động gửi (tu_dong)</option>
                    <option value="cho_duyet">⏳ Chờ ĐHVT duyệt (cho_duyet)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-2">
                <label className="flex items-center space-x-2 p-2 bg-slate-950 border border-slate-800 rounded-lg cursor-pointer hover:border-slate-700">
                  <input
                    type="checkbox"
                    checked={editIsActive}
                    onChange={(e) => setEditIsActive(e.target.checked)}
                    className="w-4 h-4 rounded text-blue-600 focus:ring-0"
                  />
                  <div>
                    <span className="font-semibold text-white block">Kích hoạt nhóm</span>
                    <span className="text-[10px] text-slate-500">Cho phép bot tương tác</span>
                  </div>
                </label>

                <label className="flex items-center space-x-2 p-2 bg-slate-950 border border-slate-800 rounded-lg cursor-pointer hover:border-slate-700">
                  <input
                    type="checkbox"
                    checked={!editIsTest}
                    onChange={(e) => setEditIsTest(!e.target.checked)}
                    className="w-4 h-4 rounded text-emerald-600 focus:ring-0"
                  />
                  <div>
                    <span className="font-semibold text-emerald-300 block">⭐ Nhóm Thật</span>
                    <span className="text-[10px] text-slate-500">Vận hành khách hàng thực</span>
                  </div>
                </label>
              </div>

              <div className="flex items-center justify-end space-x-2 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setEditingGroup(null)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submittingEdit}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition disabled:opacity-50 flex items-center gap-1.5"
                >
                  <Check className="w-4 h-4" />
                  <span>{submittingEdit ? "Đang lưu..." : "Lưu Thay Đổi"}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Thêm Nhóm Mới */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/75 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 text-xs text-slate-300 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Users className="w-5 h-5 text-blue-400" />
                <span>Thêm Nhóm Zalo Mới</span>
              </h3>
              <button onClick={() => setIsModalOpen(false)}>
                <X className="w-5 h-5 text-slate-400 hover:text-white" />
              </button>
            </div>

            <form onSubmit={handleCreateGroup} className="space-y-4 mt-4">
              <div>
                <label className="block text-slate-400 mb-1 font-semibold">
                  Zalo Group ID (threadId) <span className="text-rose-400">*</span>:
                </label>
                <input
                  type="text"
                  required
                  placeholder="Ví dụ: 6469608867469758994"
                  value={newZaloId}
                  onChange={(e) => setNewZaloId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:outline-none focus:border-blue-500"
                />
                <span className="text-[11px] text-slate-500 mt-1 block">
                  ID định danh duy nhất của nhóm Zalo trong hệ thống ZCA
                </span>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-semibold">Tên gợi nhớ nhóm:</label>
                <input
                  type="text"
                  placeholder="Ví dụ: Nhóm Khách Hàng Logitem Tân Quang"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 mb-1 font-semibold">Vai trò nhóm:</label>
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="destination">Khách hàng (Đích nhận tin)</option>
                    <option value="source">Nhà xe (Nguồn gửi tin)</option>
                    <option value="internal">Nội bộ điều vận (ĐHVT)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-semibold">Chế độ phát hành:</label>
                  <select
                    value={newSendMode}
                    onChange={(e) => setNewSendMode(e.target.value as "tu_dong" | "cho_duyet")}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="tu_dong">🟢 Tự động gửi</option>
                    <option value="cho_duyet">⏳ Chờ duyệt trước</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center justify-end space-x-2 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submittingNew}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition disabled:opacity-50"
                >
                  {submittingNew ? "Đang tạo..." : "Thêm nhóm"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}