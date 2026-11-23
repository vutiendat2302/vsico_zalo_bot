"use client";

import React, { useCallback, useEffect, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { toast } from "@/components/shared/Toast";
import {
  TransportPlanItem,
  getTransportPlans,
  downloadTransportPlansExcel,
  syncTransportPlansFromTms,
} from "@/lib/api";
import { getTmsAutoSyncStatus, TmsAutoSyncStatus } from "@/features/master/api";
import { PlanDetailModal } from "@/features/plans/components/PlanDetailModal";
import { formatSyncTime, todayVnIso } from "@/lib/utils";

/**
 * Trang quản lý kế hoạch vận chuyển đồng bộ từ TMS.
 */
export default function PlansPage() {
  const [plans, setPlans] = useState<TransportPlanItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Phân trang
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Bộ lọc (mặc định ngày hôm nay theo giờ Việt Nam)
  const [planDate, setPlanDate] = useState<string>(() => todayVnIso());
  const [containerNo, setContainerNo] = useState<string>("");
  const [customerName, setCustomerName] = useState<string>("");
  const [orderType, setOrderType] = useState<string>("");
  const [truckPlate, setTruckPlate] = useState<string>("");
  const [driverName, setDriverName] = useState<string>("");
  const [searchKeyword, setSearchKeyword] = useState<string>("");

  // Chi tiết & Đồng bộ TMS
  const [selectedPlan, setSelectedPlan] = useState<TransportPlanItem | null>(null);
  const [syncingTms, setSyncingTms] = useState(false);
  const [autoSyncStatus, setAutoSyncStatus] = useState<TmsAutoSyncStatus | null>(null);

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

  const refreshSyncStatus = useCallback(async () => {
    try {
      const st = await getTmsAutoSyncStatus();
      setAutoSyncStatus(st);
    } catch {
      // Bỏ qua lỗi đọc trạng thái nền
    }
  }, []);

  useEffect(() => {
    setCurrentPage(1);
    loadPlans(1, pageSize);
  }, [planDate, orderType, containerNo, customerName, truckPlate, driverName, searchKeyword]);

  useEffect(() => {
    loadPlans(currentPage, pageSize);
  }, [currentPage, pageSize]);

  useEffect(() => {
    refreshSyncStatus();
    const timer = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        loadPlans(currentPage, pageSize);
        refreshSyncStatus();
      }
    }, 60 * 1000);
    return () => clearInterval(timer);
  }, [currentPage, pageSize, planDate, orderType, containerNo, customerName, truckPlate, driverName, searchKeyword, refreshSyncStatus]);

  const handleSyncFromTms = async () => {
    const targetDate = planDate || todayVnIso();
    setSyncingTms(true);
    try {
      const res = await syncTransportPlansFromTms({ plan_date: targetDate, region: 1 });
      toast.success(res.message);
      if (!planDate) {
        setPlanDate(targetDate);
      }
      await Promise.all([loadPlans(1, pageSize), refreshSyncStatus()]);
    } catch (err: any) {
      toast.error(err?.message || "Lỗi đồng bộ kế hoạch từ TMS");
    } finally {
      setSyncingTms(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    loadPlans(1, pageSize);
  };

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      {/* Header */}
      <div className="shrink-0 flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <h1 className="text-2xl font-bold text-slate-900">
          Kế hoạch vận chuyển
        </h1>

        <div className="flex flex-wrap items-center gap-2">
          {autoSyncStatus && (
            <span
              className="text-sm text-slate-500 hidden sm:inline tabular-nums mr-1"
              title={autoSyncStatus.last_error || "Tự động đồng bộ từ TMS"}
            >
              {autoSyncStatus.enabled
                ? `Tự động đồng bộ ${autoSyncStatus.interval_minutes} phút · Lần cuối ${formatSyncTime(autoSyncStatus.last_success_at)}`
                : "Tự động đồng bộ đang tắt"}
            </span>
          )}

          <button
            type="button"
            onClick={handleSyncFromTms}
            disabled={syncingTms}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-sm font-medium transition disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${syncingTms ? "animate-spin" : ""}`} />
            <span>{syncingTms ? "Đang đồng bộ..." : "Đồng bộ TMS"}</span>
          </button>

          <button
            type="button"
            onClick={() =>
              downloadTransportPlansExcel({
                plan_date: planDate || undefined,
                order_type: orderType || undefined,
                q: searchKeyword || undefined,
              }).catch((err) => toast.error(err.message))
            }
            className="px-3.5 py-2 bg-white hover:bg-slate-50 text-slate-900 border border-slate-200 rounded-sm text-sm font-medium transition"
          >
            Xuất Excel
          </button>
        </div>
      </div>

      {/* Thông báo lỗi */}
      {error && (
        <div className="bg-white border border-rose-200 text-rose-700 p-3.5 rounded-sm text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-slate-500 hover:text-slate-900">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Bộ lọc tìm kiếm */}
      <form
        onSubmit={handleSearchSubmit}
        className="shrink-0 bg-white border border-slate-200 p-4 rounded-sm grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 text-sm"
      >
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-slate-600 font-medium">Ngày kế hoạch</label>
            <button
              type="button"
              onClick={() => setPlanDate(todayVnIso())}
              className="text-sm text-purple-700 hover:underline font-medium"
            >
              Hôm nay
            </button>
          </div>
          <input
            type="date"
            value={planDate}
            onChange={(e) => setPlanDate(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-base text-slate-900 focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Số container</label>
          <input
            type="text"
            placeholder="Nhập số container..."
            value={containerNo}
            onChange={(e) => setContainerNo(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-base text-slate-900 uppercase placeholder:normal-case placeholder:text-xs placeholder:text-slate-400 focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Khách hàng</label>
          <input
            type="text"
            placeholder="Nhập tên khách hàng..."
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-base text-slate-900 focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Tài xế</label>
          <input
            type="text"
            placeholder="Nhập tên tài xế..."
            value={driverName}
            onChange={(e) => setDriverName(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-base text-slate-900 focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Biển số xe</label>
          <input
            type="text"
            placeholder="Nhập biển số..."
            value={truckPlate}
            onChange={(e) => setTruckPlate(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-base text-slate-900 uppercase placeholder:normal-case placeholder:text-xs placeholder:text-slate-400 focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Loại lệnh</label>
          <select
            value={orderType}
            onChange={(e) => setOrderType(e.target.value)}
            className={`w-full bg-white border border-slate-300 rounded-sm px-3 py-2 focus:outline-none focus:border-purple-600 ${
              orderType ? "text-sm text-slate-900" : "text-xs text-slate-400"
            }`}
          >
            <option value="" className="text-xs text-slate-400">Chọn loại lệnh</option>
            <option value="tra" className="text-sm text-slate-900">Lệnh trả</option>
            <option value="dong" className="text-sm text-slate-900">Lệnh đóng</option>
          </select>
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Tìm nhanh</label>
          <div className="flex gap-1.5">
            <input
              type="text"
              placeholder="Nhập từ khóa..."
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-base text-slate-900 focus:outline-none focus:border-purple-600"
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
                className="px-2.5 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-sm text-sm whitespace-nowrap font-medium"
                title="Xóa nhanh bộ lọc"
              >
                Xóa
              </button>
            )}
          </div>
        </div>
      </form>

      {/* Bảng kế hoạch */}
      <div className="flex-1 min-h-0 bg-white border border-slate-200 rounded-sm overflow-hidden flex flex-col">
        <div className="flex-1 min-h-[220px] overflow-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead className="bg-slate-50 sticky top-0 z-10 text-slate-900 font-semibold border-b border-slate-200 whitespace-nowrap">
              <tr>
                <th className="py-3 px-3">STT</th>
                <th className="py-3 px-3">Số container</th>
                <th className="py-3 px-3">Khách hàng</th>
                <th className="py-3 px-3">Tài xế</th>
                <th className="py-3 px-3">Biển số xe</th>
                <th className="py-3 px-3">Rơ-moóc</th>
                <th className="py-3 px-3">Nhóm Zalo</th>
                <th className="py-3 px-3">Tuyến</th>
                <th className="py-3 px-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 font-normal">
              {plans.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-10 text-center text-slate-500 text-base">
                    Không có dữ liệu kế hoạch.
                  </td>
                </tr>
              ) : (
                plans.map((p, index) => (
                  <tr
                    key={p.id}
                    onClick={() => setSelectedPlan(p)}
                    className="hover:bg-slate-50 transition cursor-pointer"
                  >
                    <td className="py-3 px-3 text-slate-500 tabular-nums">
                      {p.stt ?? (currentPage - 1) * pageSize + index + 1}
                    </td>
                    <td className="py-3 px-3 font-semibold text-slate-900 whitespace-nowrap tabular-nums">
                      {p.container_no || "—"}
                    </td>
                    <td className="py-3 px-3 font-medium text-purple-700 whitespace-nowrap">
                      {p.customer_name || "—"}
                    </td>
                    <td className="py-3 px-3 whitespace-nowrap text-slate-900">
                      {p.driver_name || "—"}
                    </td>
                    <td className="py-3 px-3 whitespace-nowrap text-slate-900 tabular-nums">
                      {p.planned_truck_plate || "—"}
                    </td>
                    <td className="py-3 px-3 whitespace-nowrap text-slate-700 tabular-nums">
                      {p.planned_trailer_plate || "—"}
                    </td>
                    <td className="py-3 px-3 whitespace-nowrap">
                      {p.group_name ? (
                        <span
                          className="inline-block max-w-[180px] truncate text-sm font-medium text-slate-700 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-sm"
                          title={p.group_name}
                        >
                          {p.group_name}
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="py-3 px-3 text-slate-900 whitespace-nowrap">
                      {p.route_name || "—"}
                    </td>
                    <td
                      className="py-3 px-3 text-right whitespace-nowrap"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedPlan(p)}
                        className="px-3 py-1.5 text-sm bg-white border border-slate-200 hover:border-purple-400 text-purple-700 rounded-sm font-medium transition"
                      >
                        Chi tiết
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer phân trang */}
        {total > 0 && (
          <div className="shrink-0 px-4 py-3 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm">
            <div className="text-slate-600 tabular-nums">
              Hiển thị <span className="font-semibold text-slate-900">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-slate-900">{Math.min(currentPage * pageSize, total)}</span> trong{" "}
              <span className="font-semibold text-slate-900">{total}</span> dòng kế hoạch
            </div>

            <div className="flex items-center space-x-2">
              <div className="flex items-center space-x-1.5 mr-2">
                <span className="text-slate-500">Dòng mỗi trang:</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    const newSize = parseInt(e.target.value);
                    setPageSize(newSize);
                    setCurrentPage(1);
                  }}
                  className="bg-white border border-slate-300 rounded-sm px-2.5 py-1 text-slate-900 focus:outline-none focus:border-purple-600"
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
                className="px-3 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                Trước
              </button>

              <span className="px-2 text-slate-700 tabular-nums">
                Trang <span className="text-slate-900 font-bold">{currentPage}</span> / {Math.ceil(total / pageSize) || 1}
              </span>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(Math.ceil(total / pageSize), p + 1))}
                disabled={currentPage >= Math.ceil(total / pageSize) || loading}
                className="px-3 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                Sau
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Hộp thoại xem chi tiết */}
      <PlanDetailModal plan={selectedPlan} onClose={() => setSelectedPlan(null)} />
    </div>
  );
}
