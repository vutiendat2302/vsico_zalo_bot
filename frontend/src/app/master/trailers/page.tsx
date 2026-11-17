"use client";

import React, { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "@/components/shared/Toast";
import {
  CarrierOption,
  TrailerItem,
  getCarrierOptions,
  getTrailers,
  syncTrailersFromTms,
} from "@/features/master/api";
import {
  DetailField,
  DetailSection,
  MasterDetailModal,
  MasterPagination,
  MasterSearchInput,
  MasterSelectFilter,
  MasterStatusBadge,
} from "@/features/master/components/MasterShell";

function formatMoocType(moocType: number | null) {
  if (moocType === 1) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200/70">
        Moóc xương (Loại 1)
      </span>
    );
  }
  if (moocType === 2) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200/70">
        Moóc sàn (Loại 2)
      </span>
    );
  }
  if (moocType !== null && moocType !== undefined) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-slate-100 text-slate-700 border border-slate-200">
        Loại {moocType}
      </span>
    );
  }
  return <span className="text-slate-400">—</span>;
}

function formatSyncedAt(iso: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("vi-VN");
  } catch {
    return iso;
  }
}

export default function TrailersPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [moocType, setMoocType] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [carrierId, setCarrierId] = useState("");
  const [isActive, setIsActive] = useState("");
  const [page, setPage] = useState(1);
  const perPage = 20;

  const [carrierOptions, setCarrierOptions] = useState<CarrierOption[]>([]);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [items, setItems] = useState<TrailerItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<TrailerItem | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    getCarrierOptions()
      .then(setCarrierOptions)
      .catch(() => setCarrierOptions([]));
  }, []);

  const fetchTrailers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTrailers({
        search,
        mooc_type: moocType,
        model: modelFilter,
        carrier_id: carrierId,
        is_active: isActive,
        page,
        per_page: perPage,
      });
      setItems(res.items);
      setTotal(res.total);
      setTotalPages(res.total_pages);
      if (res.filter_options?.models) {
        setModelOptions(res.filter_options.models);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải danh sách rơ-moóc");
    } finally {
      setLoading(false);
    }
  }, [search, moocType, modelFilter, carrierId, isActive, page]);

  useEffect(() => {
    fetchTrailers();
  }, [fetchTrailers]);

  const handleSyncFromTms = async () => {
    setSyncing(true);
    try {
      const res = await syncTrailersFromTms();
      toast.success(res.message);
      await fetchTrailers();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lỗi đồng bộ rơ-moóc từ TMS");
    } finally {
      setSyncing(false);
    }
  };

  const hasActiveFilter = Boolean(search || moocType || modelFilter || carrierId || isActive);

  const clearFilters = () => {
    setSearchInput("");
    setSearch("");
    setMoocType("");
    setModelFilter("");
    setCarrierId("");
    setIsActive("");
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Rơ-moóc</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Danh mục rơ-moóc (moóc) đồng bộ từ hệ thống TMS
          </p>
        </div>

        <button
          type="button"
          onClick={handleSyncFromTms}
          disabled={syncing}
          className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium bg-purple-700 hover:bg-purple-800 text-white rounded-sm disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} />
          <span>{syncing ? "Đang đồng bộ..." : "Đồng bộ TMS"}</span>
        </button>
      </div>

      <div className="bg-white border border-slate-200 rounded-sm overflow-hidden">
        {/* Filter Bar */}
        <div className="p-3 border-b border-slate-200 flex flex-wrap items-center gap-2.5">
          <MasterSearchInput
            value={searchInput}
            onChange={setSearchInput}
            placeholder="Tìm theo biển số rơ-moóc, model, ghi chú, nhà xe..."
          />
          <MasterSelectFilter
            value={moocType}
            onChange={(val) => {
              setMoocType(val);
              setPage(1);
            }}
            options={[
              { value: "", label: "Tất cả loại moóc" },
              { value: "1", label: "Moóc xương (Loại 1)" },
              { value: "2", label: "Moóc sàn (Loại 2)" },
            ]}
          />
          <MasterSelectFilter
            value={modelFilter}
            onChange={(val) => {
              setModelFilter(val);
              setPage(1);
            }}
            options={[
              { value: "", label: "Tất cả model" },
              ...modelOptions.map((m) => ({ value: m, label: m })),
            ]}
          />
          <MasterSelectFilter
            value={carrierId}
            onChange={(val) => {
              setCarrierId(val);
              setPage(1);
            }}
            className="min-w-[200px] max-w-[260px]"
            options={[
              { value: "", label: "Tất cả đơn vị" },
              ...carrierOptions.map((c) => ({
                value: c.id,
                label: c.short_name ? `${c.short_name} - ${c.name}` : c.name,
              })),
            ]}
          />
          <MasterSelectFilter
            value={isActive}
            onChange={(val) => {
              setIsActive(val);
              setPage(1);
            }}
            options={[
              { value: "", label: "Tất cả trạng thái" },
              { value: "true", label: "Hoạt động" },
              { value: "false", label: "Ngừng hoạt động" },
            ]}
          />
          {hasActiveFilter && (
            <button
              type="button"
              onClick={clearFilters}
              className="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-sm"
            >
              Xóa lọc
            </button>
          )}
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-xs font-medium text-slate-500">
                <th className="px-4 py-2.5">Biển số rơ-moóc</th>
                <th className="px-4 py-2.5">Loại rơ-moóc</th>
                <th className="px-4 py-2.5">Model / Quy cách</th>
                <th className="px-4 py-2.5">Đơn vị sở hữu</th>
                <th className="px-4 py-2.5">Ghi chú</th>
                <th className="px-4 py-2.5 text-right">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-500">
                    Đang tải dữ liệu rơ-moóc...
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-red-600">
                    {error}
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-500">
                    Không có rơ-moóc nào phù hợp với bộ lọc hiện tại.
                  </td>
                </tr>
              ) : (
                items.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelected(row)}
                    className="hover:bg-purple-50/40 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-2.5 font-mono font-semibold text-slate-900">
                      {row.license_plate}
                    </td>
                    <td className="px-4 py-2.5">{formatMoocType(row.mooc_type)}</td>
                    <td className="px-4 py-2.5 text-slate-700">{row.model || "—"}</td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {row.carrier_short_name
                        ? `${row.carrier_short_name} - ${row.carrier_name || ""}`
                        : row.carrier_name || "—"}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 max-w-[260px] truncate">
                      {row.note || "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <MasterStatusBadge active={row.is_active} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <MasterPagination
          page={page}
          perPage={perPage}
          total={total}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      </div>

      {/* Detail Modal */}
      <MasterDetailModal
        open={!!selected}
        onClose={() => setSelected(null)}
        title={selected?.license_plate || "Chi tiết rơ-moóc"}
        subtitle={selected ? `Mã TMS: ${selected.tms_mooc_id}` : undefined}
      >
        {selected && (
          <>
            <DetailSection title="Thông tin rơ-moóc">
              <DetailField label="Biển số rơ-moóc" value={selected.license_plate} />
              <DetailField label="Biển số chuẩn hóa" value={selected.normalized_plate} />
              <DetailField
                label="Loại rơ-moóc"
                value={formatMoocType(selected.mooc_type)}
              />
              <DetailField label="Model / Quy cách" value={selected.model || "—"} />
              <DetailField
                label="Trạng thái"
                value={<MasterStatusBadge active={selected.is_active} />}
              />
              <DetailField
                label="Đồng bộ gần nhất"
                value={formatSyncedAt(selected.synced_at)}
              />
            </DetailSection>

            <DetailSection title="Đơn vị vận tải">
              <DetailField
                label="Nhà xe sở hữu"
                value={selected.carrier_name || "—"}
                fullWidth
              />
              <DetailField
                label="TMS Carrier ID"
                value={selected.tms_carrier_id || "—"}
              />
            </DetailSection>

            <DetailSection title="Ghi chú">
              <DetailField label="Ghi chú TMS" value={selected.note || "—"} fullWidth />
            </DetailSection>
          </>
        )}
      </MasterDetailModal>
    </div>
  );
}
