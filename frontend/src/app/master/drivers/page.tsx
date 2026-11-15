"use client";

import React, { useEffect, useState } from "react";
import {
  CarrierOption,
  DriverItem,
  getCarrierOptions,
  getDrivers,
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

export default function DriversPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [carrierId, setCarrierId] = useState("");
  const [isActive, setIsActive] = useState("");
  const [page, setPage] = useState(1);
  const perPage = 20;

  const [carrierOptions, setCarrierOptions] = useState<CarrierOption[]>([]);
  const [items, setItems] = useState<DriverItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<DriverItem | null>(null);

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
    getDrivers({
      search,
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
        setError(err instanceof Error ? err.message : "Không thể tải danh sách tài xế");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [search, carrierId, isActive, page]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Tài xế</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Danh mục tài xế và đơn vị vận tải đồng bộ từ hệ thống TMS
          </p>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-sm overflow-hidden">
        {/* Filter Bar */}
        <div className="p-3 border-b border-slate-200 flex flex-wrap items-center gap-2.5">
          <MasterSearchInput
            value={searchInput}
            onChange={setSearchInput}
            placeholder="Tìm theo tên, số điện thoại..."
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
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-xs font-medium text-slate-500">
                <th className="px-4 py-2.5">Họ tên tài xế</th>
                <th className="px-4 py-2.5">Số điện thoại</th>
                <th className="px-4 py-2.5">Số CCCD</th>
                <th className="px-4 py-2.5">Thuộc về</th>
                <th className="px-4 py-2.5">Số GPLX</th>
                <th className="px-4 py-2.5 text-right">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-500">
                    Đang tải dữ liệu tài xế...
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
                    Không có tài xế nào phù hợp với bộ lọc hiện tại.
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
                      {row.full_name}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {row.phone || "—"}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {row.identity_no || "—"}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {row.carrier_name || "—"}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {row.license_no || "—"}
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
        title={selected?.full_name || "Chi tiết tài xế"}
        subtitle={selected ? `Mã TMS: ${selected.tms_driver_id}` : undefined}
      >
        {selected && (
          <>
            <DetailSection title="Thông tin cá nhân">
              <DetailField label="Họ tên tài xế" value={selected.full_name} />
              <DetailField label="Số điện thoại" value={selected.phone || "—"} />
              <DetailField label="Số CCCD" value={selected.identity_no || "—"} />
              <DetailField
                label="Trạng thái"
                value={<MasterStatusBadge active={selected.is_active} />}
              />
            </DetailSection>

            <DetailSection title="Thuộc về">
              <DetailField
                label="Đơn vị vận tải"
                value={selected.carrier_name || "—"}
                fullWidth
              />
            </DetailSection>

            <DetailSection title="Giấy phép lái xe">
              <DetailField
                label="Số GPLX"
                value={selected.license_no || "—"}
                fullWidth
              />
            </DetailSection>
          </>
        )}
      </MasterDetailModal>
    </div>
  );
}
