"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  RefreshCw,
} from "lucide-react";
import { toast } from "@/components/shared/Toast";
import {
  TransportPlanItem,
  downloadTransportPlansExcel,
  syncTransportPlansFromTms,
} from "@/lib/api";
import {
  MasterTransportPlansResponse,
  TmsAutoSyncStatus,
  getMasterTransportPlans,
  getTmsAutoSyncStatus,
} from "@/features/master/api";
import { MasterSearchInput, MasterSelectFilter } from "@/features/master/components/MasterShell";
import {
  PlanDetailModal,
  formatContainerSizeBadge,
  formatDeliveryTerm,
} from "@/features/plans/components/PlanDetailModal";
import { formatSyncTime, todayVnIso } from "@/lib/utils";

function shiftIsoDate(iso: string, deltaDays: number): string {
  const parts = iso.split("-").map(Number);
  if (parts.length !== 3) return iso;
  const d = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + deltaDays));
  return d.toISOString().slice(0, 10);
}

function BalanceBadge({ balance }: { balance: number }) {
  if (balance > 0) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200/70">
        Dư {balance} trả
      </span>
    );
  }
  if (balance < 0) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200/70">
        Thiếu {Math.abs(balance)} trả
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
      Đủ
    </span>
  );
}

const WARNING_ROWS = [
  { key: "normal", label: "Bình thường", dotClass: "bg-emerald-500" },
  { key: "over_combined", label: "Quá SL kết hợp", dotClass: "bg-amber-500" },
  { key: "empty_drop", label: "Chỉ định hạ rỗng", dotClass: "bg-rose-500" },
  { key: "other_requested", label: "Bên khác đã xin", dotClass: "bg-purple-500" },
  { key: "soc", label: "SOC", dotClass: "bg-indigo-500" },
] as const;

export default function MasterTransportPlansPage() {
  const [planDate, setPlanDate] = useState<string>(() => todayVnIso());
  const [region, setRegion] = useState<number>(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [forwarderName, setForwarderName] = useState("");
  const [orderType, setOrderType] = useState("");
  const [containerSize, setContainerSize] = useState("");
  const [deliveryTerm, setDeliveryTerm] = useState("");
  const [dispatchState, setDispatchState] = useState("");
  const [containerWarning, setContainerWarning] = useState("");
  const [viewMode, setViewMode] = useState<"province" | "list">("province");

  const [data, setData] = useState<MasterTransportPlansResponse | null>(null);
  const [autoSyncStatus, setAutoSyncStatus] = useState<TmsAutoSyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedProvinces, setExpandedProvinces] = useState<Record<string, boolean>>({});
  const [selectedOrder, setSelectedOrder] = useState<TransportPlanItem | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getMasterTransportPlans({
        plan_date: planDate,
        region,
        search,
        forwarder_name: forwarderName,
        order_type: orderType,
        container_size: containerSize,
        delivery_term: deliveryTerm,
        dispatch_state: dispatchState,
        container_warning: containerWarning,
      });
      setData(res);
      setExpandedProvinces((prev) => {
        if (Object.keys(prev).length > 0) return prev;
        if (res.provinces.length > 0) {
          return { [res.provinces[0].province_name]: true };
        }
        return prev;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải kế hoạch vận chuyển");
    } finally {
      setLoading(false);
    }
  }, [
    planDate,
    region,
    search,
    forwarderName,
    orderType,
    containerSize,
    deliveryTerm,
    dispatchState,
    containerWarning,
  ]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const refreshSyncStatus = useCallback(async () => {
    try {
      const st = await getTmsAutoSyncStatus();
      setAutoSyncStatus(st);
    } catch {
      // Không chặn hiển thị bảng kế hoạch nếu endpoint trạng thái tạm thời lỗi
    }
  }, []);

  useEffect(() => {
    refreshSyncStatus();
    const timer = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        fetchData();
        refreshSyncStatus();
      }
    }, 60 * 1000);
    return () => clearInterval(timer);
  }, [fetchData, refreshSyncStatus]);

  const handleSyncFromTms = async () => {
    setSyncing(true);
    try {
      const res = await syncTransportPlansFromTms({ plan_date: planDate, region });
      toast.success(res.message);
      await Promise.all([fetchData(), refreshSyncStatus()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lỗi đồng bộ kế hoạch từ TMS");
    } finally {
      setSyncing(false);
    }
  };

  const handleExportExcel = async () => {
    setExporting(true);
    try {
      await downloadTransportPlansExcel({
        plan_date: planDate,
        region,
        order_type: orderType || undefined,
        q: search || undefined,
      });
      toast.success(`Đã xuất tệp Excel ngày ${planDate}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lỗi khi xuất Excel");
    } finally {
      setExporting(false);
    }
  };

  const toggleProvince = (provName: string) => {
    setExpandedProvinces((prev) => ({
      ...prev,
      [provName]: !prev[provName],
    }));
  };

  const summary = data?.summary;
  const cb = summary?.container_balance;
  const warnCounts = summary?.container_warning_counts;

  const hasActiveFilter = Boolean(
    search ||
      forwarderName ||
      orderType ||
      containerSize ||
      deliveryTerm ||
      dispatchState ||
      containerWarning
  );

  const clearFilters = () => {
    setSearchInput("");
    setSearch("");
    setForwarderName("");
    setOrderType("");
    setContainerSize("");
    setDeliveryTerm("");
    setDispatchState("");
    setContainerWarning("");
  };

  return (
    <div className="space-y-4">
      {/* Header + Date + Region + Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <h1 className="text-lg font-semibold text-slate-900">Kế hoạch TMS</h1>

          <div className="flex items-center space-x-2 text-xs">
            <span className="text-slate-500">Ngày kế hoạch</span>
            <div className="inline-flex items-center bg-white border border-slate-200 rounded-sm">
              <button
                type="button"
                onClick={() => setPlanDate((d) => shiftIsoDate(d, -1))}
                className="p-1.5 text-slate-500 hover:text-slate-900 hover:bg-slate-50"
                title="Ngày trước"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <input
                type="date"
                value={planDate}
                onChange={(e) => e.target.value && setPlanDate(e.target.value)}
                className="px-2 py-1 text-xs font-medium text-slate-900 bg-transparent focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setPlanDate((d) => shiftIsoDate(d, 1))}
                className="p-1.5 text-slate-500 hover:text-slate-900 hover:bg-slate-50"
                title="Ngày sau"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
            <button
              type="button"
              onClick={() => setPlanDate(todayVnIso())}
              className="px-2 py-1 text-xs font-medium bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 rounded-sm"
            >
              Hôm nay
            </button>
          </div>

          <div className="flex items-center space-x-2 text-xs">
            <span className="text-slate-500">Miền</span>
            <MasterSelectFilter
              value={String(region)}
              onChange={(val) => setRegion(Number(val))}
              className="min-w-[125px]"
              options={[
                { value: "1", label: "Miền Bắc" },
                { value: "2", label: "Miền Trung" },
                { value: "3", label: "Miền Nam" },
              ]}
            />
          </div>
        </div>

        <div className="flex items-center space-x-2">
          {autoSyncStatus && (
            <span
              className="text-[11px] text-slate-500 hidden sm:inline tabular-nums"
              title={autoSyncStatus.last_error || "Tự động đồng bộ nền từ TMS"}
            >
              {autoSyncStatus.enabled
                ? `Tự động ${autoSyncStatus.interval_minutes}p · ${formatSyncTime(autoSyncStatus.last_success_at)}`
                : "Tự động tắt"}
            </span>
          )}
          <button
            type="button"
            onClick={handleSyncFromTms}
            disabled={syncing}
            className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium bg-purple-700 hover:bg-purple-800 text-white rounded-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} />
            <span>{syncing ? "Đang đồng bộ..." : "Đồng bộ TMS"}</span>
          </button>

          <button
            type="button"
            onClick={handleExportExcel}
            disabled={exporting}
            className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium bg-white hover:bg-slate-50 text-purple-700 border border-purple-300 rounded-sm disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5" />
            <span>{exporting ? "Đang xuất..." : "Export Excel"}</span>
          </button>
        </div>
      </div>

      {/* Top Summary Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Cân đối vỏ */}
        <div className="lg:col-span-7 bg-white border border-slate-200 rounded-sm p-4">
          <div className="text-xs font-semibold text-slate-900 mb-3">Cân đối vỏ</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500 font-medium">
                  <th className="py-1.5 text-left">Size</th>
                  <th className="py-1.5 text-right">Lệnh trả</th>
                  <th className="py-1.5 text-right">Vỏ ghép được</th>
                  <th className="py-1.5 text-right">Lệnh đóng</th>
                  <th className="py-1.5 text-right">Cân đối</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { label: "20'", bucket: cb?.size_20ft },
                  { label: "40'", bucket: cb?.size_40ft },
                  { label: "Tổng", bucket: cb?.total, bold: true },
                ].map((r) => (
                  <tr key={r.label} className={r.bold ? "font-semibold text-slate-900" : "text-slate-700"}>
                    <td className="py-2">{r.label}</td>
                    <td className="py-2 text-right font-mono">{r.bucket?.return_count ?? 0}</td>
                    <td className="py-2 text-right font-mono">{r.bucket?.matchable_count ?? 0}</td>
                    <td className="py-2 text-right font-mono">{r.bucket?.loading_count ?? 0}</td>
                    <td className="py-2 text-right">
                      <BalanceBadge balance={r.bucket?.balance ?? 0} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Tình trạng vỏ lệnh trả */}
        <div className="lg:col-span-5 bg-white border border-slate-200 rounded-sm p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Tình trạng vỏ lệnh trả
          </div>
          <div className="space-y-1">
            {WARNING_ROWS.map((item) => {
              const count = warnCounts ? warnCounts[item.key] : 0;
              const active = containerWarning === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() =>
                    setContainerWarning((prev) => (prev === item.key ? "" : item.key))
                  }
                  className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-sm text-xs transition-colors border ${
                    active
                      ? "border-purple-600 bg-purple-50/60 text-purple-900 font-semibold"
                      : "border-transparent hover:bg-slate-50 text-slate-700"
                  }`}
                >
                  <span className="inline-flex items-center space-x-2">
                    <span className={`w-2 h-2 rounded-full ${item.dotClass}`} />
                    <span>{item.label}</span>
                  </span>
                  <span className="font-mono font-semibold text-slate-900">{count}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Filter Card */}
      <div className="bg-white border border-slate-200 rounded-sm p-3 space-y-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <MasterSearchInput
            value={searchInput}
            onChange={setSearchInput}
            placeholder="Tìm mã lệnh, số cont, tên kho, khách hàng..."
          />
          <MasterSelectFilter
            value={forwarderName}
            onChange={setForwarderName}
            className="min-w-[140px]"
            options={[
              { value: "", label: "Tất cả đơn vị" },
              ...(data?.filter_options.forwarders || []).map((f) => ({ value: f, label: f })),
            ]}
          />
          <MasterSelectFilter
            value={orderType}
            onChange={setOrderType}
            className="min-w-[130px]"
            options={[
              { value: "", label: "Tất cả loại lệnh" },
              { value: "tra", label: "Lệnh trả" },
              { value: "dong", label: "Lệnh đóng" },
            ]}
          />
          <MasterSelectFilter
            value={containerSize}
            onChange={setContainerSize}
            className="min-w-[120px]"
            options={[
              { value: "", label: "Tất cả size" },
              { value: "20", label: "20'" },
              { value: "40", label: "40'" },
            ]}
          />
          <MasterSelectFilter
            value={deliveryTerm}
            onChange={setDeliveryTerm}
            className="min-w-[125px]"
            options={[
              { value: "", label: "Tất cả GN" },
              { value: "1", label: "Nguyên cont" },
              { value: "2", label: "Kiểm đếm" },
            ]}
          />
          <MasterSelectFilter
            value={dispatchState}
            onChange={setDispatchState}
            className="min-w-[145px]"
            options={[
              { value: "", label: "Tất cả điều phối" },
              { value: "2", label: "Chờ điều phối" },
              { value: "3", label: "Đã nhận / Sẵn sàng" },
              { value: "5", label: "Đang thực hiện" },
            ]}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center space-x-2">
            <span className="text-slate-500">Xem theo</span>
            <div className="inline-flex border border-slate-200 rounded-sm bg-slate-50 p-0.5">
              <button
                type="button"
                onClick={() => setViewMode("province")}
                className={`px-2.5 py-1 rounded-sm text-xs transition-colors ${
                  viewMode === "province"
                    ? "bg-white text-purple-700 font-semibold border border-purple-200"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Tỉnh
              </button>
              <button
                type="button"
                onClick={() => setViewMode("list")}
                className={`px-2.5 py-1 rounded-sm text-xs transition-colors ${
                  viewMode === "list"
                    ? "bg-white text-purple-700 font-semibold border border-purple-200"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Danh sách lệnh
              </button>
            </div>
          </div>

          <div className="flex items-center space-x-3 text-slate-600">
            <span>
              Hiển thị{" "}
              <span className="font-semibold text-slate-900">{data?.total_orders ?? 0}</span> lệnh
            </span>
            {hasActiveFilter && (
              <button
                type="button"
                onClick={clearFilters}
                className="text-purple-700 hover:underline font-medium"
              >
                Xóa lọc
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Main Content Table */}
      <div className="bg-white border border-slate-200 rounded-sm overflow-hidden">
        {loading ? (
          <div className="px-4 py-12 text-center text-xs text-slate-500">
            Đang tải kế hoạch vận chuyển...
          </div>
        ) : error ? (
          <div className="px-4 py-12 text-center text-xs text-red-600">{error}</div>
        ) : !data || data.total_orders === 0 ? (
          <div className="px-4 py-12 text-center text-xs text-slate-500">
            Không có kế hoạch vận chuyển phù hợp.
          </div>
        ) : viewMode === "province" ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
                  <th className="px-4 py-2.5">Tỉnh</th>
                  <th className="px-3 py-2.5 text-center" colSpan={2}>
                    <div className="text-emerald-700 font-semibold">Lệnh trả</div>
                    <div className="grid grid-cols-2 text-[11px] font-normal text-slate-500 mt-0.5">
                      <span>20&apos;</span>
                      <span>40&apos;</span>
                    </div>
                  </th>
                  <th className="px-3 py-2.5 text-center" colSpan={2}>
                    <div className="text-sky-700 font-semibold">Lệnh đóng</div>
                    <div className="grid grid-cols-2 text-[11px] font-normal text-slate-500 mt-0.5">
                      <span>20&apos;</span>
                      <span>40&apos;</span>
                    </div>
                  </th>
                  <th className="px-3 py-2.5 text-center" colSpan={2}>
                    <div className="text-slate-700 font-semibold">Cân đối</div>
                    <div className="grid grid-cols-2 text-[11px] font-normal text-slate-500 mt-0.5">
                      <span>20&apos;</span>
                      <span>40&apos;</span>
                    </div>
                  </th>
                  <th className="px-4 py-2.5 text-right">Cảnh báo vỏ</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {data.provinces.map((prov) => {
                  const isOpen = !!expandedProvinces[prov.province_name];
                  const b20 = prov.container_balance.size_20ft;
                  const b40 = prov.container_balance.size_40ft;
                  const warnTotal =
                    prov.container_warning_counts.over_combined +
                    prov.container_warning_counts.empty_drop +
                    prov.container_warning_counts.other_requested +
                    prov.container_warning_counts.soc;

                  return (
                    <React.Fragment key={prov.province_name}>
                      <tr
                        onClick={() => toggleProvince(prov.province_name)}
                        className="hover:bg-slate-50 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-2.5 font-semibold text-slate-900">
                          <span className="inline-flex items-center space-x-2">
                            {isOpen ? (
                              <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
                            ) : (
                              <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
                            )}
                            <span>{prov.province_name}</span>
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-center font-semibold text-emerald-700">
                          {b20.return_count}
                        </td>
                        <td className="px-3 py-2.5 text-center font-semibold text-emerald-700">
                          {b40.return_count}
                        </td>
                        <td className="px-3 py-2.5 text-center font-semibold text-sky-700">
                          {b20.loading_count}
                        </td>
                        <td className="px-3 py-2.5 text-center font-semibold text-sky-700">
                          {b40.loading_count}
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <BalanceBadge balance={b20.balance} />
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <BalanceBadge balance={b40.balance} />
                        </td>
                        <td className="px-4 py-2.5 text-right text-slate-600">
                          {warnTotal > 0 ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] bg-amber-50 text-amber-700 border border-amber-200">
                              {warnTotal} cảnh báo
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>

                      {isOpen && (
                        <tr>
                          <td colSpan={8} className="p-0 bg-slate-50/40">
                            {/* LỆNH TRẢ */}
                            {prov.return_orders.length > 0 && (
                              <div className="border-t border-emerald-200">
                                <div className="px-4 py-2 bg-emerald-50/90 text-emerald-800 font-semibold text-[11px] uppercase tracking-wide border-b border-emerald-200">
                                  LỆNH TRẢ ({prov.return_orders.length})
                                </div>
                                <div className="overflow-x-auto bg-white">
                                  <table className="w-full text-left border-collapse text-xs">
                                    <thead>
                                      <tr className="bg-slate-50/70 border-b border-slate-200 text-slate-500 font-medium whitespace-nowrap">
                                        <th className="px-3 py-2">Mã lệnh</th>
                                        <th className="px-3 py-2">Đơn vị</th>
                                        <th className="px-3 py-2">Khách hàng</th>
                                        <th className="px-3 py-2">Phường</th>
                                        <th className="px-3 py-2">Kho</th>
                                        <th className="px-3 py-2">Số cont</th>
                                        <th className="px-3 py-2">Size</th>
                                        <th className="px-3 py-2">Grade</th>
                                        <th className="px-3 py-2">Seal</th>
                                        <th className="px-3 py-2">Hàng hóa</th>
                                        <th className="px-3 py-2">Tải trọng</th>
                                        <th className="px-3 py-2">Cảng nhập</th>
                                        <th className="px-3 py-2">Giờ có mặt</th>
                                        <th className="px-3 py-2">GN</th>
                                        <th className="px-3 py-2">Xe / Tài xế</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-100">
                                      {prov.return_orders.map((o) => (
                                        <tr
                                          key={o.id}
                                          onClick={() => setSelectedOrder(o)}
                                          className="hover:bg-purple-50/40 cursor-pointer whitespace-nowrap"
                                        >
                                          <td className="px-3 py-2 font-semibold text-purple-700">
                                            {o.order_code || o.id}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {o.forwarder_name || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-medium text-slate-900">
                                            {o.customer_name || "—"}
                                          </td>
                                          <td className="px-3 py-2 text-slate-600">
                                            {o.ward_name || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-medium text-slate-900 max-w-[260px] truncate">
                                            {o.warehouse_name || o.delivery_address || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-mono text-slate-800">
                                            {o.container_no || "—"}
                                          </td>
                                          <td className="px-3 py-2">
                                            <span className="inline-flex px-1.5 py-0.5 rounded-sm text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200/70">
                                              {formatContainerSizeBadge(
                                                o.container_size,
                                                o.container_type
                                              )}
                                            </span>
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {o.container_grade || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-mono text-slate-700">
                                            {o.seal_no || "—"}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700 max-w-[160px] truncate">
                                            {o.cargo_type || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-mono text-slate-700">
                                            {o.cargo_weight != null
                                              ? `${Number(o.cargo_weight).toFixed(2)}T`
                                              : "—"}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {o.full_depot || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-mono text-slate-700">
                                            {o.required_time || "—"}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {formatDeliveryTerm(o.delivery_term)}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {o.planned_truck_plate || o.planned_trailer_plate || o.driver_name
                                              ? `${[o.planned_truck_plate, o.planned_trailer_plate].filter(Boolean).join(" / ")} ${o.driver_name || ""}`.trim()
                                              : "—"}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}

                            {/* LỆNH ĐÓNG */}
                            {prov.loading_orders.length > 0 && (
                              <div className="border-t border-sky-200">
                                <div className="px-4 py-2 bg-sky-50/90 text-sky-800 font-semibold text-[11px] uppercase tracking-wide border-b border-sky-200">
                                  LỆNH ĐÓNG ({prov.loading_orders.length})
                                </div>
                                <div className="overflow-x-auto bg-white">
                                  <table className="w-full text-left border-collapse text-xs">
                                    <thead>
                                      <tr className="bg-slate-50/70 border-b border-slate-200 text-slate-500 font-medium whitespace-nowrap">
                                        <th className="px-3 py-2">Mã lệnh</th>
                                        <th className="px-3 py-2">Đơn vị</th>
                                        <th className="px-3 py-2">Khách hàng</th>
                                        <th className="px-3 py-2">Phường</th>
                                        <th className="px-3 py-2">Kho</th>
                                        <th className="px-3 py-2">Booking / Cont</th>
                                        <th className="px-3 py-2">Size</th>
                                        <th className="px-3 py-2">Hàng hóa</th>
                                        <th className="px-3 py-2">Cảng xuất</th>
                                        <th className="px-3 py-2">Giờ có mặt</th>
                                        <th className="px-3 py-2">GN</th>
                                        <th className="px-3 py-2">Xe / Tài xế</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-100">
                                      {prov.loading_orders.map((o) => (
                                        <tr
                                          key={o.id}
                                          onClick={() => setSelectedOrder(o)}
                                          className="hover:bg-purple-50/40 cursor-pointer whitespace-nowrap"
                                        >
                                          <td className="px-3 py-2 font-semibold text-purple-700">
                                            {o.order_code || o.id}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {o.forwarder_name || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-medium text-slate-900">
                                            {o.customer_name || "—"}
                                          </td>
                                          <td className="px-3 py-2 text-slate-600">
                                            {o.ward_name || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-medium text-slate-900 max-w-[260px] truncate">
                                            {o.warehouse_name || o.delivery_address || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-mono text-slate-800">
                                            {o.container_no || o.booking_no || "—"}
                                          </td>
                                          <td className="px-3 py-2">
                                            <span className="inline-flex px-1.5 py-0.5 rounded-sm text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200/70">
                                              {formatContainerSizeBadge(
                                                o.container_size,
                                                o.container_type
                                              )}
                                            </span>
                                          </td>
                                          <td className="px-3 py-2 text-slate-700 max-w-[160px] truncate">
                                            {o.cargo_type || "—"}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {o.full_depot || "—"}
                                          </td>
                                          <td className="px-3 py-2 font-mono text-slate-700">
                                            {o.required_time || "—"}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {formatDeliveryTerm(o.delivery_term)}
                                          </td>
                                          <td className="px-3 py-2 text-slate-700">
                                            {o.planned_truck_plate || o.planned_trailer_plate || o.driver_name
                                              ? `${[o.planned_truck_plate, o.planned_trailer_plate].filter(Boolean).join(" / ")} ${o.driver_name || ""}`.trim()
                                              : "—"}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          /* Danh sách lệnh (phẳng) */
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium whitespace-nowrap">
                  <th className="px-3 py-2.5">Mã lệnh</th>
                  <th className="px-3 py-2.5">Loại</th>
                  <th className="px-3 py-2.5">Tỉnh</th>
                  <th className="px-3 py-2.5">Đơn vị</th>
                  <th className="px-3 py-2.5">Khách hàng</th>
                  <th className="px-3 py-2.5">Kho</th>
                  <th className="px-3 py-2.5">Cont / Booking</th>
                  <th className="px-3 py-2.5">Size</th>
                  <th className="px-3 py-2.5">Hàng hóa</th>
                  <th className="px-3 py-2.5">Cảng</th>
                  <th className="px-3 py-2.5">Giờ</th>
                  <th className="px-3 py-2.5">Xe / Tài xế</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 whitespace-nowrap">
                {data.orders.map((o) => {
                  const isTra = o.order_type === "tra";
                  return (
                    <tr
                      key={o.id}
                      onClick={() => setSelectedOrder(o)}
                      className="hover:bg-purple-50/40 cursor-pointer"
                    >
                      <td className="px-3 py-2 font-semibold text-purple-700">
                        {o.order_code || o.id}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`inline-flex px-1.5 py-0.5 rounded-sm text-[11px] font-medium border ${
                            isTra
                              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                              : "bg-sky-50 text-sky-700 border-sky-200"
                          }`}
                        >
                          {isTra ? "Trả" : "Đóng"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-700">{o.province_name || "—"}</td>
                      <td className="px-3 py-2 text-slate-700">{o.forwarder_name || "—"}</td>
                      <td className="px-3 py-2 font-medium text-slate-900">
                        {o.customer_name || "—"}
                      </td>
                      <td className="px-3 py-2 text-slate-800 max-w-[240px] truncate">
                        {o.warehouse_name || o.delivery_address || "—"}
                      </td>
                      <td className="px-3 py-2 font-mono text-slate-800">
                        {o.container_no || o.booking_no || "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span className="inline-flex px-1.5 py-0.5 rounded-sm text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200/70">
                          {formatContainerSizeBadge(o.container_size, o.container_type)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-700 max-w-[140px] truncate">
                        {o.cargo_type || "—"}
                      </td>
                      <td className="px-3 py-2 text-slate-700">{o.full_depot || "—"}</td>
                      <td className="px-3 py-2 font-mono text-slate-700">
                        {o.required_time || "—"}
                      </td>
                      <td className="px-3 py-2 text-slate-700">
                        {o.planned_truck_plate || o.planned_trailer_plate || o.driver_name
                          ? `${[o.planned_truck_plate, o.planned_trailer_plate].filter(Boolean).join(" / ")} ${o.driver_name || ""}`.trim()
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Shared Detail Modal */}
      <PlanDetailModal plan={selectedOrder} onClose={() => setSelectedOrder(null)} />
    </div>
  );
}
