"use client";

import React, { useEffect, useState, useRef } from "react";
import { X } from "lucide-react";
import { toast } from "@/components/shared/Toast";
import {
  TransportPlanItem,
  getTransportPlans,
  importPlanFile,
  createTransportPlan,
  updateTransportPlan,
  deleteTransportPlan,
} from "@/lib/api";

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
  const [truckPlate, setTruckPlate] = useState<string>("");
  const [driverName, setDriverName] = useState<string>("");
  const [searchKeyword, setSearchKeyword] = useState<string>("");

  // Modals & Upload State
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingPlan, setEditingPlan] = useState<Partial<TransportPlanItem> | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<TransportPlanItem | null>(null);
  const [importing, setImporting] = useState(false);
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
    driver_name: "",
    driver_phone: "",
    delivery_address: "",
    group_id: "",
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
        truck_plate: truckPlate || undefined,
        driver_name: driverName || undefined,
        q: searchKeyword || undefined,
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
  }, [planDate, orderType, containerNo, customerName, truckPlate, driverName, searchKeyword]);

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
      const msg = `Nạp thành công ${res.total_imported} dòng cho ngày ${res.plan_date}. Đã tự động map Group ID: ${res.default_group_id_applied}`;
      setImportSuccessMsg(msg);
      toast.success(msg);
      if (res.plan_date) {
        setPlanDate(res.plan_date);
      }
      await loadPlans();
    } catch (err: any) {
      toast.error("Lỗi khi import file: " + err.message);
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
      toast.success("Thêm mới kế hoạch thành công.");
      setIsCreateModalOpen(false);
      await loadPlans();
    } catch (err: any) {
      toast.error("Lỗi khi thêm mới kế hoạch: " + err.message);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingPlan || !editingPlan.id) return;
    try {
      await updateTransportPlan(editingPlan.id, {
        ...editingPlan,
        stt: editingPlan.stt ? Number(editingPlan.stt) : undefined,
        cargo_weight: editingPlan.cargo_weight ? Number(editingPlan.cargo_weight) : undefined,
      });
      toast.success("Cập nhật kế hoạch thành công.");
      setIsEditModalOpen(false);
      setEditingPlan(null);
      await loadPlans();
    } catch (err: any) {
      toast.error("Lỗi khi cập nhật kế hoạch: " + err.message);
    }
  };

  const handleDelete = async (id: string | number) => {
    if (!confirm("Bạn có chắc chắn muốn xóa dòng kế hoạch này không?")) return;
    try {
      await deleteTransportPlan(id);
      toast.success("Đã xóa dòng kế hoạch thành công.");
      await loadPlans();
    } catch (err: any) {
      toast.error("Lỗi khi xóa: " + err.message);
    }
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <h1 className="text-xl font-bold text-slate-900">
          Kế hoạch vận chuyển
        </h1>

        <div className="flex flex-wrap items-center gap-2">
          <label className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-900 border border-slate-200 rounded-sm text-xs font-medium cursor-pointer transition">
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

          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="px-3 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-xs font-medium transition"
          >
            Thêm kế hoạch
          </button>

          <button
            type="button"
            onClick={() => loadPlans(currentPage, pageSize)}
            disabled={loading}
            className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-900 rounded-sm text-xs font-medium border border-slate-200 transition"
          >
            {loading ? "Đang tải..." : "Làm mới"}
          </button>
        </div>
      </div>

      {/* Success Notification after upload */}
      {importSuccessMsg && (
        <div className="bg-purple-50 border border-purple-200 text-purple-700 p-3 rounded-sm text-xs flex items-center justify-between">
          <span>{importSuccessMsg}</span>
          <button onClick={() => setImportSuccessMsg(null)} className="text-slate-500 hover:text-slate-900">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Error Notification */}
      {error && (
        <div className="bg-white border border-slate-200 text-slate-900 p-3 rounded-sm text-xs flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-slate-500 hover:text-slate-900">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
      <form
        onSubmit={handleSearchSubmit}
        className="bg-white border border-slate-200 p-4 rounded-sm grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 text-xs"
      >
        <div>
          <label className="block text-slate-600 mb-1 font-medium">Ngày kế hoạch:</label>
          <input
            type="date"
            value={planDate}
            onChange={(e) => setPlanDate(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Số container:</label>
          <input
            type="text"
            placeholder="VD: SELU4396800"
            value={containerNo}
            onChange={(e) => setContainerNo(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 uppercase focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Tên khách hàng:</label>
          <input
            type="text"
            placeholder="VD: Logitem, DC..."
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Tên tài xế:</label>
          <input
            type="text"
            placeholder="VD: Hải, Hòa, Dũng..."
            value={driverName}
            onChange={(e) => setDriverName(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Biển số xe:</label>
          <input
            type="text"
            placeholder="VD: 29C-445.41"
            value={truckPlate}
            onChange={(e) => setTruckPlate(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 uppercase focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Loại lệnh:</label>
          <select
            value={orderType}
            onChange={(e) => setOrderType(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 focus:outline-none focus:border-blue-500"
          >
            <option value="">Tất cả lệnh</option>
            <option value="tra">Lệnh Trả (Nhập - I)</option>
            <option value="dong">Lệnh Đóng (Xuất - X)</option>
          </select>
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Tìm tổng hợp:</label>
          <div className="flex gap-1.5">
            <input
              type="text"
              placeholder="Từ khóa..."
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 focus:outline-none focus:border-blue-500"
            />
            {(planDate || containerNo || customerName || driverName || truckPlate || orderType || searchKeyword) && (
              <button
                type="button"
                onClick={() => {
                  setPlanDate("");
                  setContainerNo("");
                  setCustomerName("");
                  setDriverName("");
                  setTruckPlate("");
                  setOrderType("");
                  setSearchKeyword("");
                }}
                className="px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-sm text-[11px] whitespace-nowrap"
                title="Xóa nhanh các bộ lọc"
              >
                Xóa lọc
              </button>
            )}
          </div>
        </div>
      </form>

      {/* Main Table */}
      <div className="bg-white border border-slate-200 rounded-sm overflow-hidden">
        <div className="p-3 border-b border-slate-200 flex items-center justify-between text-xs text-slate-500">
          <div>
            Hiển thị <span className="text-slate-900 font-semibold">{plans.length}</span> / {total} dòng
          </div>
        </div>

        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-50 sticky top-0 text-slate-900 font-semibold border-b border-slate-200 whitespace-nowrap">
              <tr>
                <th className="py-2.5 px-3">STT</th>
                <th className="py-2.5 px-3">Số Container</th>
                <th className="py-2.5 px-3">Khách hàng</th>
                <th className="py-2.5 px-3">Tài xế</th>
                <th className="py-2.5 px-3">Biển số xe</th>
                <th className="py-2.5 px-3">Nhóm Zalo</th>
                <th className="py-2.5 px-3">Tuyến</th>
                <th className="py-2.5 px-3">Địa chỉ</th>
                <th className="py-2.5 px-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 font-normal">
              {plans.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-10 text-center text-slate-500">
                    Không có dữ liệu kế hoạch.
                  </td>
                </tr>
              ) : (
                plans.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => setSelectedPlan(p)}
                    className="hover:bg-slate-50 transition cursor-pointer"
                  >
                    <td className="py-2.5 px-3 text-slate-500">{p.stt || p.id}</td>
                    <td className="py-2.5 px-3 font-mono font-semibold text-slate-900 whitespace-nowrap">
                      {p.container_no || "—"}
                    </td>
                    <td className="py-2.5 px-3 font-medium text-purple-700 whitespace-nowrap">
                      {p.customer_name || "—"}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap text-slate-900 font-medium">
                      {p.driver_name || "—"}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap font-mono text-slate-900">
                      {p.planned_truck_plate || "—"}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <span
                        className="inline-block max-w-[150px] truncate text-[11px] font-medium text-emerald-800 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded-sm"
                        title={p.group_name ? `${p.group_name} (${p.group_id})` : p.group_id || ""}
                      >
                        {p.group_name || p.group_id || "—"}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-slate-900 whitespace-nowrap">
                      {p.route_name || "—"}
                    </td>
                    <td className="py-2.5 px-3 text-slate-500 max-w-[240px] truncate" title={p.delivery_address || ""}>
                      {p.delivery_address || "—"}
                    </td>
                    <td
                      className="py-2.5 px-3 text-right whitespace-nowrap space-x-1.5"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedPlan(p)}
                        className="px-2 py-1 text-[11px] bg-white border border-slate-200 hover:border-purple-300 text-purple-700 rounded-sm"
                      >
                        Chi tiết
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditingPlan({ ...p });
                          setIsEditModalOpen(true);
                        }}
                        className="px-2 py-1 text-[11px] bg-white border border-slate-200 hover:bg-slate-50 text-blue-600 hover:text-blue-800 rounded-sm"
                      >
                        Sửa
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(p.id)}
                        className="px-2 py-1 text-[11px] bg-white border border-slate-200 hover:bg-slate-50 text-slate-500 hover:text-red-600 rounded-sm"
                      >
                        Xóa
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Toolbar */}
        {total > 0 && (
          <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-slate-600">
              Hiển thị <span className="font-semibold text-slate-900">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-slate-900">{Math.min(currentPage * pageSize, total)}</span> trong{" "}
              <span className="font-semibold text-slate-900">{total}</span> dòng kế hoạch
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
                  className="bg-white border border-slate-300 rounded-sm px-2 py-1 text-slate-800 focus:outline-none focus:border-sky-500"
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
                className="px-2.5 py-1 rounded bg-white hover:bg-slate-50 text-slate-700 border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-300 transition"
              >
                ← Trước
              </button>

              <span className="px-2 font-mono text-slate-700">
                Trang <span className="text-slate-900 font-bold">{currentPage}</span> / {Math.ceil(total / pageSize) || 1}
              </span>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(Math.ceil(total / pageSize), p + 1))}
                disabled={currentPage >= Math.ceil(total / pageSize) || loading}
                className="px-2.5 py-1 rounded bg-white hover:bg-slate-50 text-slate-700 border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-300 transition"
              >
                Sau →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Dialog */}
      {selectedPlan && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedPlan(null)}
        >
          <div
            className="bg-white border border-slate-200 rounded-sm max-w-xl w-full p-5 text-xs text-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900">
                Chi tiết chuyến — {selectedPlan.container_no || selectedPlan.id}
              </h3>
              <button
                type="button"
                onClick={() => setSelectedPlan(null)}
                className="text-slate-500 hover:text-slate-900"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 mt-4">
              <div>
                <div className="text-slate-500">Ngày kế hoạch</div>
                <div className="font-medium text-slate-900 mt-0.5">{selectedPlan.plan_date || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Lệnh</div>
                <div className="font-medium text-purple-700 mt-0.5">
                  {selectedPlan.order_type === "tra" ? "Trả (Nhập)" : "Đóng (Xuất)"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Số Container</div>
                <div className="font-mono font-semibold text-slate-900 mt-0.5">{selectedPlan.container_no || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Số Seal</div>
                <div className="font-mono text-slate-900 mt-0.5">{selectedPlan.seal_no || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Cỡ / Tải trọng</div>
                <div className="text-slate-900 mt-0.5">
                  {selectedPlan.container_size ? `${selectedPlan.container_size}'` : "—"} /{" "}
                  {selectedPlan.cargo_weight ? `${selectedPlan.cargo_weight}T` : "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Giờ hẹn</div>
                <div className="font-medium text-slate-900 mt-0.5">{selectedPlan.required_time || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Khách hàng</div>
                <div className="font-medium text-purple-700 mt-0.5">{selectedPlan.customer_name || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Tuyến</div>
                <div className="text-slate-900 mt-0.5">{selectedPlan.route_name || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Tàu / Số</div>
                <div className="text-slate-900 mt-0.5">{selectedPlan.vessel_voyage || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Bãi hàng</div>
                <div className="text-slate-900 mt-0.5">{selectedPlan.full_depot || selectedPlan.empty_depot || "—"}</div>
              </div>
              <div>
                <div className="text-slate-500">Tài xế / SĐT</div>
                <div className="font-medium text-slate-900 mt-0.5">
                  {selectedPlan.driver_name || "—"}{" "}
                  {selectedPlan.driver_phone ? `(${selectedPlan.driver_phone})` : ""}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Biển số xe / Đội xe</div>
                <div className="font-mono text-slate-900 mt-0.5">
                  {selectedPlan.planned_truck_plate || "—"} ({selectedPlan.fleet_partner || "—"})
                </div>
              </div>
              <div>
                <div className="text-slate-500">Loại hàng</div>
                <div className="text-slate-900 mt-0.5">{selectedPlan.cargo_type || "—"}</div>
              </div>
              <div className="col-span-2">
                <div className="text-slate-500">Địa chỉ đóng / trả hàng</div>
                <div className="text-slate-900 mt-0.5">{selectedPlan.delivery_address || "—"}</div>
              </div>
              <div className="col-span-2">
                <div className="text-slate-500">Nhóm Zalo nhận thông báo</div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-sm">
                    {selectedPlan.group_name || "Chưa đặt tên nhóm"}
                  </span>
                  <span className="font-mono text-slate-500 text-[11px]">
                    (ID: {selectedPlan.group_id || "—"})
                  </span>
                </div>
              </div>
            </div>

            <div className="mt-5 pt-3 border-t border-slate-200 flex justify-end">
              <button
                type="button"
                onClick={() => setSelectedPlan(null)}
                className="px-4 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-xs font-medium"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-200 rounded-sm max-w-2xl w-full p-6 text-xs text-slate-700 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-base font-bold text-slate-900">Thêm Mới Bản Ghi Kế Hoạch Vận Chuyển</h3>
              <button onClick={() => setIsCreateModalOpen(false)}>
                <X className="w-5 h-5 text-slate-600 hover:text-slate-900" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4 mt-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Ngày kế hoạch:</label>
                  <input
                    type="date"
                    required
                    value={newPlan.plan_date}
                    onChange={(e) => setNewPlan({ ...newPlan, plan_date: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tuyến vận chuyển:</label>
                  <input
                    type="text"
                    placeholder="VD: HP - Tân Quang"
                    value={newPlan.route_name}
                    onChange={(e) => setNewPlan({ ...newPlan, route_name: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Hàng (Xuất/Nhập):</label>
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
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  >
                    <option value="I">Nhập (I) - Trả/Mở hàng</option>
                    <option value="X">Xuất (X) - Đóng hàng</option>
                  </select>
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Số container:</label>
                  <input
                    type="text"
                    required
                    placeholder="VD: SELU4396800"
                    value={newPlan.container_no}
                    onChange={(e) => setNewPlan({ ...newPlan, container_no: e.target.value.toUpperCase() })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 uppercase font-mono font-bold"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Số chì niêm phong:</label>
                  <input
                    type="text"
                    placeholder="VD: 23715411"
                    value={newPlan.seal_no}
                    onChange={(e) => setNewPlan({ ...newPlan, seal_no: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Kích cỡ cont:</label>
                  <select
                    value={newPlan.container_size}
                    onChange={(e) => setNewPlan({ ...newPlan, container_size: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  >
                    <option value="20">20 feet</option>
                    <option value="40">40 feet</option>
                    <option value="45">45 feet</option>
                  </select>
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tải trọng (tấn):</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="VD: 25.96"
                    value={newPlan.cargo_weight}
                    onChange={(e) => setNewPlan({ ...newPlan, cargo_weight: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">YC thời gian có mặt:</label>
                  <input
                    type="text"
                    placeholder="VD: 7h"
                    value={newPlan.required_time}
                    onChange={(e) => setNewPlan({ ...newPlan, required_time: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tên khách hàng:</label>
                  <input
                    type="text"
                    placeholder="VD: Logitem, Asia..."
                    value={newPlan.customer_name}
                    onChange={(e) => setNewPlan({ ...newPlan, customer_name: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 font-semibold"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Loại hàng hóa:</label>
                  <input
                    type="text"
                    placeholder="VD: Mỳ, Bột ngọt, Nắp lon..."
                    value={newPlan.cargo_type}
                    onChange={(e) => setNewPlan({ ...newPlan, cargo_type: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Đội xe phân công:</label>
                  <input
                    type="text"
                    placeholder="VD: Tuấn Hưng..."
                    value={newPlan.fleet_partner}
                    onChange={(e) => setNewPlan({ ...newPlan, fleet_partner: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tên tài xế:</label>
                  <input
                    type="text"
                    placeholder="VD: Nguyễn Văn Hải"
                    value={newPlan.driver_name}
                    onChange={(e) => setNewPlan({ ...newPlan, driver_name: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Biển số xe dự kiến:</label>
                  <input
                    type="text"
                    placeholder="VD: 29C-445.41"
                    value={newPlan.planned_truck_plate}
                    onChange={(e) => setNewPlan({ ...newPlan, planned_truck_plate: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block mb-1 font-medium text-slate-600">Địa chỉ đóng / trả hàng:</label>
                <textarea
                  rows={2}
                  placeholder="VD: Kho Logitem (Tân Quang). LH thủ kho Mr Sơn 096 7327975"
                  value={newPlan.delivery_address}
                  onChange={(e) => setNewPlan({ ...newPlan, delivery_address: e.target.value })}
                  className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                />
              </div>

              <div>
                <label className="block mb-1 font-medium text-emerald-400">Group ID Zalo nhận thông báo:</label>
                <input
                  type="text"
                  value={newPlan.group_id}
                  onChange={(e) => setNewPlan({ ...newPlan, group_id: e.target.value })}
                  className="w-full bg-emerald-50 border border-emerald-300 rounded-sm p-2 text-emerald-900 font-mono font-bold"
                />
              </div>

              <div className="flex justify-end space-x-3 pt-3 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-4 py-2 bg-white hover:bg-slate-50 text-slate-700 border-slate-200 rounded"
                >
                  Hủy bỏ
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-purple-700 hover:bg-purple-800 text-white font-medium rounded"
                >
                  Lưu kế hoạch
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {isEditModalOpen && editingPlan && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-200 rounded-sm max-w-2xl w-full p-6 text-xs text-slate-700 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-base font-bold text-slate-900">
                Chỉnh Sửa Kế Hoạch Vận Chuyển #{editingPlan.id}
              </h3>
              <button
                onClick={() => {
                  setIsEditModalOpen(false);
                  setEditingPlan(null);
                }}
              >
                <X className="w-5 h-5 text-slate-600 hover:text-slate-900" />
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="space-y-4 mt-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Ngày kế hoạch:</label>
                  <input
                    type="date"
                    required
                    value={editingPlan.plan_date || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, plan_date: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tuyến vận chuyển:</label>
                  <input
                    type="text"
                    placeholder="VD: HP - Tân Quang"
                    value={editingPlan.route_name || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, route_name: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Hàng (Xuất/Nhập):</label>
                  <select
                    value={editingPlan.cargo_io_type || (editingPlan.order_type === "dong" ? "X" : "I")}
                    onChange={(e) => {
                      const io = e.target.value;
                      setEditingPlan({
                        ...editingPlan,
                        cargo_io_type: io,
                        order_type: io === "X" ? "dong" : "tra",
                      });
                    }}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  >
                    <option value="I">Nhập (I) - Trả/Mở hàng</option>
                    <option value="X">Xuất (X) - Đóng hàng</option>
                  </select>
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Số container:</label>
                  <input
                    type="text"
                    required
                    placeholder="VD: SELU4396800"
                    value={editingPlan.container_no || ""}
                    onChange={(e) =>
                      setEditingPlan({ ...editingPlan, container_no: e.target.value.toUpperCase() })
                    }
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 uppercase font-mono font-bold"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Số chì niêm phong:</label>
                  <input
                    type="text"
                    placeholder="VD: 23715411"
                    value={editingPlan.seal_no || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, seal_no: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Kích cỡ cont:</label>
                  <select
                    value={editingPlan.container_size || "40"}
                    onChange={(e) => setEditingPlan({ ...editingPlan, container_size: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  >
                    <option value="20">20 feet</option>
                    <option value="40">40 feet</option>
                    <option value="45">45 feet</option>
                  </select>
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tải trọng (tấn):</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="VD: 25.96"
                    value={editingPlan.cargo_weight || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, cargo_weight: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">YC thời gian có mặt:</label>
                  <input
                    type="text"
                    placeholder="VD: 7h"
                    value={editingPlan.required_time || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, required_time: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tên khách hàng:</label>
                  <input
                    type="text"
                    placeholder="VD: Logitem, Asia..."
                    value={editingPlan.customer_name || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, customer_name: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 font-semibold"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Loại hàng hóa:</label>
                  <input
                    type="text"
                    placeholder="VD: Mỳ, Bột ngọt, Nắp lon..."
                    value={editingPlan.cargo_type || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, cargo_type: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Đội xe phân công:</label>
                  <input
                    type="text"
                    placeholder="VD: Tuấn Hưng..."
                    value={editingPlan.fleet_partner || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, fleet_partner: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Tên tài xế:</label>
                  <input
                    type="text"
                    placeholder="VD: Nguyễn Văn Hải"
                    value={editingPlan.driver_name || ""}
                    onChange={(e) => setEditingPlan({ ...editingPlan, driver_name: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                  />
                </div>
                <div>
                  <label className="block mb-1 font-medium text-slate-600">Biển số xe dự kiến:</label>
                  <input
                    type="text"
                    placeholder="VD: 29C-445.41"
                    value={editingPlan.planned_truck_plate || ""}
                    onChange={(e) =>
                      setEditingPlan({ ...editingPlan, planned_truck_plate: e.target.value })
                    }
                    className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900 font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block mb-1 font-medium text-slate-600">Địa chỉ đóng / trả hàng:</label>
                <textarea
                  rows={2}
                  placeholder="VD: Kho Logitem (Tân Quang)..."
                  value={editingPlan.delivery_address || ""}
                  onChange={(e) => setEditingPlan({ ...editingPlan, delivery_address: e.target.value })}
                  className="w-full bg-white border border-slate-300 rounded-sm p-2 text-slate-900"
                />
              </div>

              <div>
                <label className="block mb-1 font-medium text-emerald-400">Group ID Zalo nhận thông báo:</label>
                <input
                  type="text"
                  placeholder="Nhập Group ID Zalo (nếu có)"
                  value={editingPlan.group_id || ""}
                  onChange={(e) => setEditingPlan({ ...editingPlan, group_id: e.target.value })}
                  className="w-full bg-emerald-50 border border-emerald-300 rounded-sm p-2 text-emerald-900 font-mono font-bold"
                />
              </div>

              <div className="flex justify-end space-x-3 pt-3 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => {
                    setIsEditModalOpen(false);
                    setEditingPlan(null);
                  }}
                  className="px-4 py-2 bg-white hover:bg-slate-50 text-slate-700 border-slate-200 rounded"
                >
                  Hủy bỏ
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded"
                >
                  Cập nhật kế hoạch
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
