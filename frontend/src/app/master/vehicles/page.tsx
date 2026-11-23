"use client";

import React, { useEffect, useState } from "react";
import {
  CarrierOption,
  VehicleItem,
  getCarrierOptions,
  getVehicles,
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

function formatVehicleType(vehicleType: number | null) {
  if (vehicleType === 1) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200/70">
        Đầu kéo nặng
      </span>
    );
  }
  if (vehicleType === 2) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200/70">
        Rơ-moóc
      </span>
    );
  }
  return <span className="text-slate-400">—</span>;
}

function formatCapacity(capacity: number | null) {
  if (capacity === null || capacity === undefined) return "0.00T";
  return `${Number(capacity).toFixed(2)}T`;
}

export default function VehiclesPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [vehicleType, setVehicleType] = useState("");
  const [carrierId, setCarrierId] = useState("");
  const [isActive, setIsActive] = useState("");
  const [page, setPage] = useState(1);
  const perPage = 20;

  const [carrierOptions, setCarrierOptions] = useState<CarrierOption[]>([]);
  const [items, setItems] = useState<VehicleItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<VehicleItem | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getVehicles({
      search,
      vehicle_type: vehicleType,
      carrier_id: carrierId,
      is_active: isActive,
      page,
      per_page: perPage,
    })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
        setTotalPages(res.total_pages);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Không thể tải danh sách xe đầu kéo");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [search, vehicleType, carrierId, isActive, page]);

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Xe đầu kéo</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Danh mục xe đầu kéo và rơ-moóc đồng bộ từ hệ thống TMS
          </p>
        </div>
      </div>

      <div className="flex-1 min-h-0 bg-white border border-slate-200 rounded-sm overflow-hidden flex flex-col">
        {/* Filter Bar */}
        <div className="shrink-0 p-3 border-b border-slate-200 flex flex-wrap items-center gap-2.5">
          <MasterSearchInput
            value={searchInput}
            onChange={setSearchInput}
            placeholder="Tìm theo biển số, tài xế..."
          />
          <MasterSelectFilter
            value={vehicleType}
            onChange={(val) => {
              setVehicleType(val);
              setPage(1);
            }}
            options={[
              { value: "", label: "Tất cả loại" },
              { value: "1", label: "Đầu kéo nặng" },
              { value: "2", label: "Rơ-moóc" },
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
        </div>

        {/* Table */}
        <div className="flex-1 min-h-[220px] overflow-auto">
          <table className="w-full text-left border-collapse">
            <thead className="sticky top-0 z-10">
              <tr className="bg-slate-50 border-b border-slate-200 text-xs font-medium text-slate-500">
                <th className="px-4 py-2.5">Biển số xe</th>
                <th className="px-4 py-2.5">Loại đầu kéo</th>
                <th className="px-4 py-2.5">Tải trọng (tấn)</th>
                <th className="px-4 py-2.5">Thuộc về</th>
                <th className="px-4 py-2.5">Tài xế</th>
                <th className="px-4 py-2.5 text-right">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-500">
                    Đang tải dữ liệu xe đầu kéo...
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
                    Không có xe đầu kéo nào phù hợp với bộ lọc hiện tại.
                  </td>
                </tr>
              ) : (
                items.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelected(row)}
                    className="hover:bg-purple-50/40 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-2.5 font-semibold text-slate-900">
                      {row.plate_no}
                    </td>
                    <td className="px-4 py-2.5">
                      {formatVehicleType(row.vehicle_type)}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {formatCapacity(row.payload_capacity)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {row.carrier_name || "—"}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {row.driver_hint_name || "—"}
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
        title={selected?.plate_no || "Chi tiết xe"}
        subtitle={selected ? `Mã TMS: ${selected.tms_vehicle_id}` : undefined}
      >
        {selected && (
          <>
            <DetailSection title="Thông tin xe">
              <DetailField label="Biển số xe" value={selected.plate_no} />
              <DetailField
                label="Loại phương tiện"
                value={formatVehicleType(selected.vehicle_type)}
              />
              <DetailField
                label="Tải trọng (tấn)"
                value={formatCapacity(selected.payload_capacity)}
              />
              <DetailField
                label="Trạng thái"
                value={<MasterStatusBadge active={selected.is_active} />}
              />
            </DetailSection>

            <DetailSection title="Thuộc về">
              <DetailField
                label="Đơn vị sở hữu"
                value={selected.carrier_name || "—"}
                fullWidth
              />
            </DetailSection>

            <DetailSection title="Tài xế">
              <DetailField
                label="Tài xế gợi ý từ TMS"
                value={selected.driver_hint_name || "—"}
                fullWidth
              />
            </DetailSection>
          </>
        )}
      </MasterDetailModal>
    </div>
  );
}
