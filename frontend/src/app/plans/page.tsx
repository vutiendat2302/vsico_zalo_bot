"use client";

import React, { useEffect, useState, useRef } from "react";
import {
  CalendarDays,
  Upload,
  Plus,
  Trash2,
  RefreshCw,
  Check,
  X,
  AlertTriangle,
  Shuffle,
} from "lucide-react";
import {
  TransportPlanItem,
  getTransportPlans,
  importPlanFile,
  createTransportPlan,
  deleteTransportPlan,
  randomizePlanGroups,
  setAllPlansGroup,
} from "@/lib/api";

const DEFAULT_GROUP_ID = "6469608867469758994";

export default function PlansPage() {
  const [plans, setPlans] = useState<TransportPlanItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Filters
  const [planDate, setPlanDate] = useState<string>("2026-10-12");
  const [containerNo, setContainerNo] = useState<string>("");
  const [customerName, setCustomerName] = useState<string>("");
  const [orderType, setOrderType] = useState<string>("");

  // Modals & Upload State
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [randomizing, setRandomizing] = useState(false);
  const [settingDefaultGroup, setSettingDefaultGroup] = useState(false);
  const [importSuccessMsg, setImportSuccessMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Create Form State
  const [newPlan, setNewPlan] = useState({
    plan_date: "2026-10-12",
    stt: "",
    route_name: "",
    cargo_io_type: "I",
    order_type: "tra",
    container_no: "",
    seal_no: "",
    container_size: "40",
    cargo_weight: "",
    required_time: "7h",
    customer_name: "",
    cargo_type: "",
    vessel_voyage: "",
    empty_depot: "",
    full_depot: "PTSC",
    fleet_partner: "",
    planned_truck_plate: "",
    delivery_address: "",
    group_id: DEFAULT_GROUP_ID,
  });

  const loadPlans = async (page = currentPage, size = pageSize) => {
    try {
      setLoading(true);
      setError(null);
      const res = await getTransportPlans({
        plan_date: planDate || undefined,
        container_no: containerNo || undefined,
        customer_name: customerName || undefined,
        order_type: orderType || undefined,
        limit: size,
        offset: (page - 1) * size,
      });
      setPlans(res.plans);
      setTotal(res.total);
    } catch (err: any) {
      setError(err.message || "Lỗi khi tải danh sách kế hoạch vận chuyển.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setCurrentPage(1);
    loadPlans(1, pageSize);
  }, [planDate, orderType]);

  useEffect(() => {
    loadPlans(currentPage, pageSize);
  }, [currentPage, pageSize]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    loadPlans(1, pageSize);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setImporting(true);
      setImportSuccessMsg(null);
      const res = await importPlanFile(file, true);
      setImportSuccessMsg(
        `Nạp thành công ${res.total_imported} dòng cho ngày ${res.plan_date}. Đã tự động map Group ID: ${res.default_group_id_applied}`
      );
      if (res.plan_date) {
        setPlanDate(res.plan_date);
      }
      await loadPlans();
    } catch (err: any) {
      alert("Lỗi khi import file: " + err.message);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createTransportPlan({
        ...newPlan,
        stt: newPlan.stt ? parseInt(newPlan.stt) : undefined,
        cargo_weight: newPlan.cargo_weight ? parseFloat(newPlan.cargo_weight) : undefined,
      } as any);
      setIsCreateModalOpen(false);
      await loadPlans();
    } catch (err: any) {
      alert("Lỗi khi thêm mới kế hoạch: " + err.message);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Bạn có chắc chắn muốn xóa dòng kế hoạch này không?")) return;
    try {
      await deleteTransportPlan(id);
      await loadPlans();
    } catch (err: any) {
      alert("Lỗi khi xóa: " + err.message);
    }
  };

  const handleRandomizeGroups = async () => {
    try {
      setRandomizing(true);
      setError(null);
      const res = await randomizePlanGroups(planDate || undefined);
      const dist = res.group_distribution || {};
      setImportSuccessMsg(
        `🎲 ${res.message} [test3: ${dist["3051850159021421440"] || 0} xe | khách hàng: ${dist["6469608867469758994"] || 0} xe | nhà xe: ${dist["7196206900754562564"] || 0} xe]`
      );
      await loadPlans(currentPage, pageSize);
    } catch (err: any) {
      setError(err.message || "Lỗi khi random nhóm kế hoạch.");
    } finally {
      setRandomizing(false);
    }
  };

  const handleSetAllDefaultGroup = async () => {
    if (
      !confirm(
        "Bạn có chắc chắn muốn đổi tất cả groupId trong kế hoạch về nhóm Zalo DC Logistics (6469608867469758994)?"
      )
    )
      return;
    try {
      setSettingDefaultGroup(true);
      setError(null);
      const res = await setAllPlansGroup(DEFAULT_GROUP_ID);
      setImportSuccessMsg(`✅ ${res.message}`);
      await loadPlans(currentPage, pageSize);
    } catch (err: any) {
      setError(err.message || "Lỗi khi gán nhóm mặc định.");
    } finally {
      setSettingDefaultGroup(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            <CalendarDays className="w-6 h-6 text-sky-400" />
            Kế Hoạch Vận Chuyển Hằng Ngày
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Dữ liệu đối chiếu số container, địa chỉ đóng/trả, phân định Lệnh Đóng/Mở và tự động ánh xạ Group ID Zalo
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* File Upload Trigger */}
          <label className="flex items-center space-x-1.5 px-3 py-2 bg-emerald-700 hover:bg-emerald-600 text-white rounded-lg text-xs font-medium cursor-pointer transition shadow-sm">
            <Upload className="w-4 h-4" />
            <span>{importing ? "Đang import..." : "Import Excel / CSV"}</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              onChange={handleFileUpload}
              disabled={importing}
              className="hidden"
            />
          </label>

          {/* Manual Create Trigger */}
          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="flex items-center space-x-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-medium transition shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>Thêm Kế Hoạch</span>
          </button>

          {/* Randomize 3 Zalo Groups Trigger */}
          <button
            type="button"
            onClick={handleRandomizeGroups}
            disabled={randomizing || loading}
            title="Phân bổ ngẫu nhiên kế hoạch vào 3 nhóm Zalo thật (test3, khách hàng, nhà xe)"
            className="flex items-center space-x-1.5 px-3 py-2 bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition shadow-sm"
          >
            <Shuffle className={`w-3.5 h-3.5 ${randomizing ? "animate-spin" : ""}`} />
            <span>{randomizing ? "Đang random..." : "Random 3 Nhóm Zalo"}</span>
          </button>

          {/* Gán tất cả về nhóm 6469608867469758994 */}
          <button
            type="button"
            onClick={handleSetAllDefaultGroup}
            disabled={settingDefaultGroup || loading}
            title="Đổi toàn bộ groupId của các kế hoạch về nhóm Zalo DC Logistics 6469608867469758994"
            className="flex items-center space-x-1.5 px-3 py-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition shadow-sm"
          >
            <Check className={`w-3.5 h-3.5 ${settingDefaultGroup ? "animate-spin" : ""}`} />
            <span>{settingDefaultGroup ? "Đang gán..." : "Gán Nhóm 6469608867469758994"}</span>
          </button>

          <button
            type="button"
            onClick={() => loadPlans(currentPage, pageSize)}
            disabled={loading}
            className="flex items-center space-x-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {/* Success Notification after upload */}
      {importSuccessMsg && (
        <div className="bg-emerald-950/60 border border-emerald-600/50 text-emerald-300 p-3 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            <span>{importSuccessMsg}</span>
          </div>
          <button onClick={() => setImportSuccessMsg(null)}>
            <X className="w-4 h-4 text-emerald-400 hover:text-white" />
          </button>
        </div>
      )}

      {/* Error Notification */}
      {error && (
        <div className="bg-rose-950/60 border border-rose-600/50 text-rose-300 p-3 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)}>
            <X className="w-4 h-4 text-rose-400 hover:text-white" />
          </button>
        </div>
      )}
      <form
        onSubmit={handleSearchSubmit}
        className="bg-slate-900 border border-slate-800 p-4 rounded-xl grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 text-xs"
      >
        <div>
          <label className="block text-slate-400 mb-1 font-medium">Ngày kế hoạch:</label>
          <input
            type="date"
            value={planDate}
            onChange={(e) => setPlanDate(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Số container:</label>
          <input
            type="text"
            placeholder="VD: SELU4396800"
            value={containerNo}
            onChange={(e) => setContainerNo(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white uppercase focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Tên khách hàng:</label>
          <input
            type="text"
            placeholder="VD: Logitem, DC, Asia..."
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Loại lệnh:</label>
          <select
            value={orderType}
            onChange={(e) => setOrderType(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          >
            <option value="">Tất cả lệnh (Đóng & Trả)</option>
            <option value="tra">Lệnh Trả / Mở cont (Nhập - I)</option>
            <option value="dong">Lệnh Đóng (Xuất - X)</option>
          </select>
        </div>
      </form>

      {/* Main Table view matching ketnoi.xlsx */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between text-xs text-slate-400">
          <div>
            Hiển thị <span className="text-white font-semibold">{plans.length}</span> / {total} dòng kế hoạch
          </div>
          <div className="flex items-center space-x-3">
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-500"></span>
              <span>Lệnh Trả / Mở (Hàng Nhập - I)</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
              <span>Lệnh Đóng (Hàng Xuất - X)</span>
            </span>
          </div>
        </div>

        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-950/80 sticky top-0 text-slate-300 font-semibold border-b border-slate-800 whitespace-nowrap">
              <tr>
                <th className="py-3 px-3">STT</th>
                <th className="py-3 px-3">Tuyến</th>
                <th className="py-3 px-3">Lệnh</th>
                <th className="py-3 px-3">Số Container</th>
                <th className="py-3 px-3">Số Seal</th>
                <th className="py-3 px-3">Cỡ</th>
                <th className="py-3 px-3">Tải trọng</th>
                <th className="py-3 px-3">Giờ hẹn</th>
                <th className="py-3 px-3">Khách hàng</th>
                <th className="py-3 px-3">Loại hàng</th>
                <th className="py-3 px-3">Tàu / Số</th>
                <th className="py-3 px-3">Bãi hàng</th>
                <th className="py-3 px-3">Đội xe</th>
                <th className="py-3 px-3">Số xe</th>
                <th className="py-3 px-4 min-w-[260px]">Địa chỉ đóng / trả hàng</th>
                <th className="py-3 px-3 text-emerald-400">Group ID Zalo</th>
                <th className="py-3 px-2 text-center">Xóa</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-normal">
              {plans.length === 0 ? (
                <tr>
                  <td colSpan={17} className="py-12 text-center text-slate-500">
                    Không tìm thấy bản ghi kế hoạch nào khớp với điều kiện lọc.
                  </td>
                </tr>
              ) : (
                plans.map((p) => {
                  const isTra = p.order_type === "tra";
                  return (
                    <tr key={p.id} className="hover:bg-slate-800/40 transition">
                      <td className="py-2.5 px-3 text-slate-400">{p.stt || p.id}</td>
                      <td className="py-2.5 px-3 font-medium text-slate-200 whitespace-nowrap">
                        {p.route_name || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                            isTra
                              ? "bg-purple-950/80 text-purple-300 border border-purple-800/60"
                              : "bg-blue-950/80 text-blue-300 border border-blue-800/60"
                          }`}
                        >
                          {isTra ? "Trả (Nhập)" : "Đóng (Xuất)"}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 font-mono font-bold text-white whitespace-nowrap">
                        {p.container_no || "—"}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-slate-300 whitespace-nowrap">
                        {p.seal_no || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-300">
                        {p.container_size ? `${p.container_size}'` : "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-300">
                        {p.cargo_weight ? `${p.cargo_weight}T` : "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-300 font-medium">
                        {p.required_time || "—"}
                      </td>
                      <td className="py-2.5 px-3 font-semibold text-sky-400 whitespace-nowrap">
                        {p.customer_name || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-300">
                        {p.cargo_type || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-400">
                        {p.vessel_voyage || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-400">
                        {p.full_depot || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-300">
                        {p.fleet_partner || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap font-mono text-amber-300">
                        {p.planned_truck_plate || "—"}
                      </td>
                      <td className="py-2.5 px-4 text-slate-300 text-[11px] max-w-sm truncate" title={p.delivery_address || ""}>
                        {p.delivery_address || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <span className="font-mono text-[11px] bg-emerald-950/60 text-emerald-300 border border-emerald-700/50 px-2 py-0.5 rounded">
                          {p.group_id || DEFAULT_GROUP_ID}
                        </span>
                      </td>
                      <td className="py-2.5 px-2 text-center whitespace-nowrap">
                        <button
                          onClick={() => handleDelete(p.id)}
                          className="p-1 hover:bg-red-500/20 text-slate-400 hover:text-red-400 rounded transition"
                          title="Xóa dòng"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Toolbar */}
        {total > 0 && (
          <div className="px-4 py-3 bg-slate-950/80 border-t border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-slate-400">
              Hiển thị <span className="font-semibold text-white">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-white">{Math.min(currentPage * pageSize, total)}</span> trong{" "}
              <span className="font-semibold text-white">{total}</span> dòng kế hoạch
            </div>

            <div className="flex items-center space-x-2">
              <div className="flex items-center space-x-1.5 mr-2">
                <span className="text-slate-500">Dòng/trang:</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    const newSize = parseInt(e.target.value);
                    setPageSize(newSize);
                    setCurrentPage(1);
                  }}
                  className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-sky-500"
                >
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1 || loading}
                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700 transition"
              >
                ← Trước
              </button>

              <span className="px-2 font-mono text-slate-300">
                Trang <span className="text-white font-bold">{currentPage}</span> / {Math.ceil(total / pageSize) || 1}
              </span>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(Math.ceil(total / pageSize), p + 1))}
                disabled={currentPage >= Math.ceil(total / pageSize) || loading}
                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700 transition"
              >
                Sau →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-2xl w-full p-6 text-xs text-slate-300 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white">Thêm Mới Bản Ghi Kế Hoạch Vận Chuyển</h3>
              <button onClick={() => setIsCreateModalOpen(false)}>
                <X className="w-5 h-5 text-slate-400 hover:text-white" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4 mt-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Ngày kế hoạch:</label>
                  <input
                    type="date"
                    required
                    value={newPlan.plan_date}
                    onChange={(e) => setNewPlan({ ...newPlan, plan_date: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Tuyến vận chuyển:</label>
                  <input
                    type="text"
                    placeholder="VD: HP - Tân Quang"
                    value={newPlan.route_name}
                    onChange={(e) => setNewPlan({ ...newPlan, route_name: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Hàng (Xuất/Nhập):</label>
                  <select
                    value={newPlan.cargo_io_type}
                    onChange={(e) => {
                      const io = e.target.value;
                      setNewPlan({
                        ...newPlan,
                        cargo_io_type: io,
                        order_type: io === "X" ? "dong" : "tra",
                      });
                    }}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  >
                    <option value="I">Nhập (I) - Trả/Mở hàng</option>
                    <option value="X">Xuất (X) - Đóng hàng</option>
                  </select>
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Số container:</label>
                  <input
                    type="text"
                    required
                    placeholder="VD: SELU4396800"
                    value={newPlan.container_no}
                    onChange={(e) => setNewPlan({ ...newPlan, container_no: e.target.value.toUpperCase() })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white uppercase font-mono font-bold"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Số chì niêm phong:</label>
                  <input
                    type="text"
                    placeholder="VD: 23715411"
                    value={newPlan.seal_no}
                    onChange={(e) => setNewPlan({ ...newPlan, seal_no: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Kích cỡ cont:</label>
                  <select
                    value={newPlan.container_size}
                    onChange={(e) => setNewPlan({ ...newPlan, container_size: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  >
                    <option value="20">20 feet</option>
                    <option value="40">40 feet</option>
                    <option value="45">45 feet</option>
                  </select>
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Tải trọng (tấn):</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="VD: 25.96"
                    value={newPlan.cargo_weight}
                    onChange={(e) => setNewPlan({ ...newPlan, cargo_weight: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-400">YC thời gian có mặt:</label>
                  <input
                    type="text"
                    placeholder="VD: 7h"
                    value={newPlan.required_time}
                    onChange={(e) => setNewPlan({ ...newPlan, required_time: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Tên khách hàng:</label>
                  <input
                    type="text"
                    placeholder="VD: Logitem, Asia..."
                    value={newPlan.customer_name}
                    onChange={(e) => setNewPlan({ ...newPlan, customer_name: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white font-semibold"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Loại hàng hóa:</label>
                  <input
                    type="text"
                    placeholder="VD: Mỳ, Bột ngọt, Nắp lon..."
                    value={newPlan.cargo_type}
                    onChange={(e) => setNewPlan({ ...newPlan, cargo_type: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Đội xe phân công:</label>
                  <input
                    type="text"
                    placeholder="VD: Tuấn Hưng, Phương Anh HP..."
                    value={newPlan.fleet_partner}
                    onChange={(e) => setNewPlan({ ...newPlan, fleet_partner: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-400">Số xe dự kiến:</label>
                  <input
                    type="text"
                    placeholder="VD: 29C-445.41"
                    value={newPlan.planned_truck_plate}
                    onChange={(e) => setNewPlan({ ...newPlan, planned_truck_plate: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block mb-1 font-medium text-slate-400">Địa chỉ đóng / trả hàng:</label>
                <textarea
                  rows={2}
                  placeholder="VD: Kho Logitem (Tân Quang). LH thủ kho Mr Sơn 096 7327975"
                  value={newPlan.delivery_address}
                  onChange={(e) => setNewPlan({ ...newPlan, delivery_address: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                />
              </div>

              <div>
                <label className="block mb-1 font-medium text-emerald-400">Group ID Zalo nhận thông báo:</label>
                <input
                  type="text"
                  value={newPlan.group_id}
                  onChange={(e) => setNewPlan({ ...newPlan, group_id: e.target.value })}
                  className="w-full bg-slate-950 border border-emerald-700 rounded p-2 text-emerald-300 font-mono font-bold"
                />
              </div>

              <div className="flex justify-end space-x-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Hủy bỏ
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded"
                >
                  Lưu kế hoạch
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
