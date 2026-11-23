"use client";

import React, { useEffect, useState } from "react";
import { CustomerItem, getCustomers } from "@/features/master/api";
import {
  DetailField,
  DetailSection,
  MasterDetailModal,
  MasterPagination,
  MasterSearchInput,
  MasterSelectFilter,
  MasterStatusBadge,
} from "@/features/master/components/MasterShell";

export default function CustomersPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [isActive, setIsActive] = useState("");
  const [page, setPage] = useState(1);
  const perPage = 20;

  const [items, setItems] = useState<CustomerItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CustomerItem | null>(null);

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
    getCustomers({
      search,
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
        setError(err instanceof Error ? err.message : "Không thể tải danh sách khách hàng");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [search, isActive, page]);

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Danh sách khách hàng</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Danh mục khách hàng vận tải đồng bộ từ hệ thống TMS
          </p>
        </div>
      </div>

      <div className="flex-1 min-h-0 bg-white border border-slate-200 rounded-sm overflow-hidden flex flex-col">
        {/* Filter Bar */}
        <div className="shrink-0 p-3 border-b border-slate-200 flex flex-wrap items-center gap-2.5">
          <MasterSearchInput
            value={searchInput}
            onChange={setSearchInput}
            placeholder="Tìm theo tên khách hàng..."
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
                <th className="px-4 py-2.5">Mã TMS</th>
                <th className="px-4 py-2.5">Tên khách hàng</th>
                <th className="px-4 py-2.5 text-center">Số kho</th>
                <th className="px-4 py-2.5 text-right">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-slate-500">
                    Đang tải dữ liệu khách hàng...
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-red-600">
                    {error}
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-slate-500">
                    Không có khách hàng nào phù hợp với bộ lọc hiện tại.
                  </td>
                </tr>
              ) : (
                items.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelected(row)}
                    className="hover:bg-purple-50/40 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-2.5 font-mono text-slate-600">
                      {row.tms_customer_id}
                    </td>
                    <td className="px-4 py-2.5 font-semibold text-slate-900">
                      {row.name}
                    </td>
                    <td className="px-4 py-2.5 text-center font-medium text-slate-700">
                      {row.warehouse_count}
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
        title={selected?.name || "Chi tiết khách hàng"}
        subtitle={selected ? `Mã TMS: ${selected.tms_customer_id}` : undefined}
      >
        {selected && (
          <DetailSection title="Thông tin khách hàng">
            <DetailField label="Tên khách hàng" value={selected.name} fullWidth />
            <DetailField label="Mã TMS" value={selected.tms_customer_id} />
            <DetailField label="Số lượng kho" value={selected.warehouse_count} />
            <DetailField
              label="Trạng thái"
              value={<MasterStatusBadge active={selected.is_active} />}
            />
          </DetailSection>
        )}
      </MasterDetailModal>
    </div>
  );
}
