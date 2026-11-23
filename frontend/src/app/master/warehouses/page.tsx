"use client";

import React, { useEffect, useState } from "react";
import { WarehouseItem, getWarehouses } from "@/features/master/api";
import {
  DetailField,
  DetailSection,
  MasterDetailModal,
  MasterPagination,
  MasterSearchInput,
  MasterSelectFilter,
  MasterStatusBadge,
} from "@/features/master/components/MasterShell";

function formatLocationType(type: string) {
  if (type === "port") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200/70">
        Cảng
      </span>
    );
  }
  if (type === "depot") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200/70">
        Depot
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium bg-purple-50 text-purple-700 border border-purple-200/70">
      Kho khách hàng
    </span>
  );
}

export default function WarehousesPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [locationType, setLocationType] = useState("");
  const [isActive, setIsActive] = useState("");
  const [page, setPage] = useState(1);
  const perPage = 20;

  const [items, setItems] = useState<WarehouseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<WarehouseItem | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getWarehouses({
      search,
      location_type: locationType,
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
        setError(err instanceof Error ? err.message : "Không thể tải danh sách kho khách hàng");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [search, locationType, isActive, page]);

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Kho khách hàng</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Danh mục kho khách hàng, cảng và depot đồng bộ từ hệ thống TMS
          </p>
        </div>
      </div>

      <div className="flex-1 min-h-0 bg-white border border-slate-200 rounded-sm overflow-hidden flex flex-col">
        {/* Filter Bar */}
        <div className="shrink-0 p-3 border-b border-slate-200 flex flex-wrap items-center gap-2.5">
          <MasterSearchInput
            value={searchInput}
            onChange={setSearchInput}
            placeholder="Tìm theo tên kho, địa chỉ..."
          />
          <MasterSelectFilter
            value={locationType}
            onChange={(val) => {
              setLocationType(val);
              setPage(1);
            }}
            options={[
              { value: "", label: "Tất cả loại địa điểm" },
              { value: "warehouse", label: "Kho khách hàng" },
              { value: "port", label: "Cảng" },
              { value: "depot", label: "Depot" },
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
                <th className="px-4 py-2.5">Tên kho / địa điểm</th>
                <th className="px-4 py-2.5">Loại</th>
                <th className="px-4 py-2.5">Khách hàng</th>
                <th className="px-4 py-2.5">Địa chỉ</th>
                <th className="px-4 py-2.5 text-right">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-slate-500">
                    Đang tải dữ liệu kho khách hàng...
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-red-600">
                    {error}
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-slate-500">
                    Không có kho nào phù hợp với bộ lọc hiện tại.
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
                      {row.name}
                    </td>
                    <td className="px-4 py-2.5">
                      {formatLocationType(row.location_type)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {row.customer_name || "—"}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 max-w-md truncate">
                      {row.address || "—"}
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
        title={selected?.name || "Chi tiết địa điểm"}
        subtitle={selected ? `Mã TMS: ${selected.tms_warehouse_id}` : undefined}
      >
        {selected && (
          <DetailSection title="Thông tin địa điểm">
            <DetailField label="Tên địa điểm" value={selected.name} fullWidth />
            <DetailField label="Loại" value={formatLocationType(selected.location_type)} />
            <DetailField
              label="Trạng thái"
              value={<MasterStatusBadge active={selected.is_active} />}
            />
            <DetailField label="Khách hàng" value={selected.customer_name || "—"} fullWidth />
            <DetailField label="Địa chỉ" value={selected.address || "—"} fullWidth />
            <DetailField
              label="Tọa độ (Lat, Lng)"
              value={
                selected.latitude != null && selected.longitude != null
                  ? `${selected.latitude}, ${selected.longitude}`
                  : "—"
              }
              fullWidth
            />
          </DetailSection>
        )}
      </MasterDetailModal>
    </div>
  );
}
