"use client";

/**
 * Trang Kết quả gửi thông báo điều xe ra nhóm Zalo khách hàng.
 * Chỉ lưu các kết quả đã duyệt hoặc kết quả đạt của phần tự động gửi, chỉ cho phép xem chi tiết.
 * Tuân thủ bảng màu 3 tông đồng bộ với Trang tổng quan (trắng/xám, đen chữ, tím nhấn),
 * không dùng icon trang trí, tải dữ liệu thật từ Backend API.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  OutboundMessageItem,
  OutboundSummary,
  getOutboundMessages,
  getOutboundSummary,
} from "@/lib/api";

interface StatusPresentation {
  label: string;
  dotClass: string;
  textClass: string;
  key: "SENT" | "PENDING_SEND" | "SENDING";
}

function resolveStatusMeta(rawStatus: string): StatusPresentation {
  const norm = (rawStatus || "").trim().toUpperCase();
  if (norm === "SENT" || norm === "DA_GUI") {
    return { key: "SENT", label: "Đã gửi", dotClass: "bg-emerald-600", textClass: "text-slate-900" };
  }
  if (norm === "SENDING") {
    return { key: "SENDING", label: "Đang gửi", dotClass: "bg-amber-500", textClass: "text-slate-900" };
  }
  return { key: "PENDING_SEND", label: "Chờ gửi", dotClass: "bg-purple-600", textClass: "text-slate-900" };
}

function resolveApprovalSourceLabel(m: OutboundMessageItem): string {
  if (m.approval_source === "approved" || (m.approved_by && m.approved_by !== "auto_system")) {
    return "Đã duyệt";
  }
  return "Tự động gửi";
}

function formatShortTime(isoStr?: string): string {
  if (!isoStr) return "—";
  const dt = new Date(isoStr);
  if (Number.isNaN(dt.getTime())) {
    return isoStr.slice(0, 16).replace("T", " ");
  }
  const now = new Date();
  const isToday =
    dt.getFullYear() === now.getFullYear() &&
    dt.getMonth() === now.getMonth() &&
    dt.getDate() === now.getDate();
  const hh = String(dt.getHours()).padStart(2, "0");
  const mm = String(dt.getMinutes()).padStart(2, "0");
  if (isToday) return `${hh}:${mm}`;
  const dd = String(dt.getDate()).padStart(2, "0");
  const mo = String(dt.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mo} ${hh}:${mm}`;
}

function formatOrderLabel(orderType: string): string {
  const norm = (orderType || "").trim().toLowerCase();
  if (norm === "dong" || norm === "load" || norm === "xuat") return "Đóng";
  if (norm === "tra" || norm === "return" || norm === "nhap") return "Trả";
  return orderType || "—";
}

export default function MessageResultsPage() {
  const [messages, setMessages] = useState<OutboundMessageItem[]>([]);
  const [summary, setSummary] = useState<OutboundSummary>({
    ok: true,
    total: 0,
    da_gui: 0,
    cho_duyet: 0,
    cho_gui: 0,
    huy: 0,
    that_bai: 0,
    ket_qua_dat: 0,
    da_duyet: 0,
    tu_dong_dat: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const [totalCount, setTotalCount] = useState(0);

  const [statusFilter, setStatusFilter] = useState<string>("");
  const [sourceModeFilter, setSourceModeFilter] = useState<string>("");
  const [orderTypeFilter, setOrderTypeFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [fromTime, setFromTime] = useState<string>("");
  const [toTime, setToTime] = useState<string>("");

  const [selectedMessage, setSelectedMessage] = useState<OutboundMessageItem | null>(null);

  const loadData = useCallback(
    async (
      page = currentPage,
      size = pageSize,
      filters?: {
        status?: string;
        source_mode?: string;
        order_type?: string;
        search?: string;
        from_time?: string;
        to_time?: string;
      }
    ) => {
      const fStatus = filters?.status !== undefined ? filters.status : statusFilter;
      const fSource = filters?.source_mode !== undefined ? filters.source_mode : sourceModeFilter;
      const fOrder = filters?.order_type !== undefined ? filters.order_type : orderTypeFilter;
      const fSearch = filters?.search !== undefined ? filters.search : searchQuery;
      const fFrom = filters?.from_time !== undefined ? filters.from_time : fromTime;
      const fTo = filters?.to_time !== undefined ? filters.to_time : toTime;

      try {
        setLoading(true);
        setError(null);
        const [sumRes, listRes] = await Promise.all([
          getOutboundSummary(),
          getOutboundMessages({
            results_only: true,
            status: fStatus || undefined,
            source_mode: fSource || undefined,
            order_type: fOrder || undefined,
            search: fSearch.trim() || undefined,
            from_time: fFrom || undefined,
            to_time: fTo || undefined,
            limit: size,
            offset: (page - 1) * size,
          }),
        ]);
        setSummary(sumRes);
        setMessages(listRes.messages);
        setTotalCount(listRes.total);
      } catch (err: any) {
        setError(err.message || "Không thể tải dữ liệu kết quả gửi.");
      } finally {
        setLoading(false);
      }
    },
    [currentPage, pageSize, statusFilter, sourceModeFilter, orderTypeFilter, searchQuery, fromTime, toTime]
  );

  useEffect(() => {
    loadData(currentPage, pageSize);
  }, [currentPage, pageSize, statusFilter, sourceModeFilter, orderTypeFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    loadData(1, pageSize);
  };

  const handleClearFilters = () => {
    setStatusFilter("");
    setSourceModeFilter("");
    setOrderTypeFilter("");
    setSearchQuery("");
    setFromTime("");
    setToTime("");
    setCurrentPage(1);
    loadData(1, pageSize, {
      status: "",
      source_mode: "",
      order_type: "",
      search: "",
      from_time: "",
      to_time: "",
    });
  };

  const hasActiveFilters = Boolean(
    statusFilter || sourceModeFilter || orderTypeFilter || searchQuery.trim() || fromTime || toTime
  );
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const totalResultsCount = summary.ket_qua_dat ?? summary.da_gui + (summary.cho_gui ?? 0);
  const approvedCount = summary.da_duyet ?? 0;
  const autoCount = summary.tu_dong_dat ?? 0;
  const pendingSendCount = summary.cho_gui ?? 0;

  return (
    <div className="h-full min-h-0 flex flex-col gap-3 text-sm">
      {/* Header */}
      <div className="shrink-0 flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <h1 className="text-xl font-bold text-slate-900">Kết quả gửi</h1>
        <button
          type="button"
          onClick={() => loadData(currentPage, pageSize)}
          disabled={loading}
          className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-900 rounded-sm text-xs font-medium border border-slate-200 transition self-start sm:self-auto"
        >
          {loading ? "Đang tải..." : "Làm mới"}
        </button>
      </div>

      {/* 4 KPI Cards */}
      <div className="shrink-0 grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button
          type="button"
          onClick={() => {
            setStatusFilter("");
            setSourceModeFilter("");
            setCurrentPage(1);
          }}
          className={`text-left p-4 rounded-sm border transition ${
            !statusFilter && !sourceModeFilter
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Tổng kết quả đạt</div>
          <div className="text-2xl font-bold text-slate-900 mt-2 tabular-nums">
            {totalResultsCount}
          </div>
        </button>

        <button
          type="button"
          onClick={() => {
            setStatusFilter((prev) => (prev === "SENT" ? "" : "SENT"));
            setSourceModeFilter("");
            setCurrentPage(1);
          }}
          className={`text-left p-4 rounded-sm border transition ${
            statusFilter === "SENT"
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Đã gửi thành công</div>
          <div className="text-2xl font-bold text-slate-900 mt-2 tabular-nums">
            {summary.da_gui}
          </div>
        </button>

        <button
          type="button"
          onClick={() => {
            setStatusFilter("");
            setSourceModeFilter((prev) => (prev === "approved" ? "" : "approved"));
            setCurrentPage(1);
          }}
          className={`text-left p-4 rounded-sm border transition ${
            sourceModeFilter === "approved"
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Đã duyệt</div>
          <div className="text-2xl font-bold text-purple-700 mt-2 tabular-nums">
            {approvedCount}
          </div>
        </button>

        <button
          type="button"
          onClick={() => {
            setStatusFilter("");
            setSourceModeFilter((prev) => (prev === "auto" ? "" : "auto"));
            setCurrentPage(1);
          }}
          className={`text-left p-4 rounded-sm border transition ${
            sourceModeFilter === "auto"
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Tự động gửi</div>
          <div className="text-2xl font-bold text-slate-900 mt-2 tabular-nums">
            {autoCount}
          </div>
        </button>
      </div>

      {/* Tabs lọc nhanh */}
      <div className="shrink-0 flex flex-wrap items-center gap-2">
        {[
          {
            id: "all",
            active: !statusFilter && !sourceModeFilter,
            label: `Tất cả (${totalResultsCount})`,
            onClick: () => {
              setStatusFilter("");
              setSourceModeFilter("");
              setCurrentPage(1);
            },
          },
          {
            id: "sent",
            active: statusFilter === "SENT" && !sourceModeFilter,
            label: `Đã gửi (${summary.da_gui})`,
            onClick: () => {
              setStatusFilter("SENT");
              setSourceModeFilter("");
              setCurrentPage(1);
            },
          },
          {
            id: "approved",
            active: sourceModeFilter === "approved",
            label: `Đã duyệt (${approvedCount})`,
            onClick: () => {
              setStatusFilter("");
              setSourceModeFilter("approved");
              setCurrentPage(1);
            },
          },
          {
            id: "auto",
            active: sourceModeFilter === "auto",
            label: `Tự động gửi (${autoCount})`,
            onClick: () => {
              setStatusFilter("");
              setSourceModeFilter("auto");
              setCurrentPage(1);
            },
          },
          ...(pendingSendCount > 0
            ? [
                {
                  id: "pending_send",
                  active: statusFilter === "PENDING_SEND",
                  label: `Chờ gửi (${pendingSendCount})`,
                  onClick: () => {
                    setStatusFilter("PENDING_SEND");
                    setSourceModeFilter("");
                    setCurrentPage(1);
                  },
                },
              ]
            : []),
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={tab.onClick}
            className={`px-3 py-1.5 rounded-sm text-xs font-medium border transition tabular-nums ${
              tab.active
                ? "bg-purple-700 text-white border-purple-700"
                : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Thanh tìm kiếm & bộ lọc */}
      <form
        onSubmit={handleSearchSubmit}
        className="shrink-0 bg-white border border-slate-200 p-3.5 rounded-sm grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 text-xs items-end"
      >
        <div className="lg:col-span-2">
          <label className="block text-slate-600 mb-1 font-medium">Tìm kiếm</label>
          <input
            type="text"
            placeholder="Số cont, biển số, tài xế, nhóm, nội dung..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-slate-900 focus:outline-none focus:border-purple-700"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Loại lệnh</label>
          <select
            value={orderTypeFilter}
            onChange={(e) => {
              setOrderTypeFilter(e.target.value);
              setCurrentPage(1);
            }}
            className={`w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 focus:outline-none focus:border-purple-700 ${
              orderTypeFilter ? "text-xs text-slate-900" : "text-xs text-slate-400"
            }`}
          >
            <option value="" className="text-xs text-slate-400">Chọn loại lệnh</option>
            <option value="dong" className="text-xs text-slate-900">Đóng hàng</option>
            <option value="tra" className="text-xs text-slate-900">Trả hàng</option>
          </select>
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Từ ngày</label>
          <input
            type="date"
            value={fromTime}
            onChange={(e) => setFromTime(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-purple-700"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Đến ngày</label>
          <div className="flex gap-2">
            <input
              type="date"
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
              className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-purple-700"
            />
            <button
              type="submit"
              className="px-3.5 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm font-medium transition whitespace-nowrap"
            >
              Lọc
            </button>
            {hasActiveFilters && (
              <button
                type="button"
                onClick={handleClearFilters}
                className="px-2.5 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium transition whitespace-nowrap"
              >
                Xóa
              </button>
            )}
          </div>
        </div>
      </form>

      {error && (
        <div className="shrink-0 p-3 bg-white border border-rose-300 rounded-sm text-rose-700 text-xs">
          {error}
        </div>
      )}

      {/* Bảng dữ liệu chính */}
      <div className="flex-1 min-h-0 bg-white border border-slate-200 rounded-sm overflow-hidden flex flex-col">
        <div className="flex-1 min-h-[220px] overflow-auto">
          <table className="w-full text-left text-xs text-slate-700">
            <thead className="bg-slate-50 sticky top-0 z-10 text-slate-600 uppercase text-[11px] border-b border-slate-200">
              <tr>
                <th className="py-2.5 px-3 w-14">STT</th>
                <th className="py-2.5 px-3 w-24">Lệnh</th>
                <th className="py-2.5 px-3 min-w-[300px]">Thông tin chính</th>
                <th className="py-2.5 px-3 w-44">Nhóm nhận</th>
                <th className="py-2.5 px-3 w-28">Thời gian</th>
                <th className="py-2.5 px-3 text-right w-24">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {loading && messages.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-slate-500">
                    Đang tải dữ liệu...
                  </td>
                </tr>
              ) : messages.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-slate-500">
                    Không có dữ liệu phù hợp.
                  </td>
                </tr>
              ) : (
                messages.map((m, idx) => {
                  const firstCont = m.containers?.[0];

                  return (
                    <tr key={m.id} className="hover:bg-slate-50 transition">
                      <td className="py-2.5 px-3 font-mono text-slate-500 whitespace-nowrap tabular-nums">
                        {(currentPage - 1) * pageSize + idx + 1}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <span className="font-medium text-slate-900">
                          {formatOrderLabel(m.order_type)}
                        </span>
                        {m.message_kind === "update" && (
                          <span className="ml-1.5 text-[11px] text-purple-700 font-medium">
                            Cập nhật
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 max-w-lg">
                        {firstCont && (firstCont.container_no || firstCont.truck_plate || firstCont.driver_name) ? (
                          <div className="space-y-0.5">
                            <div className="font-mono text-slate-900 font-semibold truncate">
                              {[
                                firstCont.container_no,
                                firstCont.truck_plate,
                                firstCont.driver_name,
                                firstCont.driver_phone,
                              ]
                                .filter(Boolean)
                                .join(" • ")}
                            </div>
                            <div className="text-slate-500 truncate" title={m.content}>
                              {m.content}
                            </div>
                          </div>
                        ) : (
                          <div className="text-slate-900 font-medium truncate" title={m.content}>
                            {m.content}
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <div className="font-medium text-slate-900 truncate max-w-[165px]">
                          {m.target_group_name || "—"}
                        </div>
                        {m.target_zalo_group_id && (
                          <div className="text-[11px] text-slate-500 font-mono truncate max-w-[165px]">
                            {m.target_zalo_group_id}
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-600 font-mono tabular-nums">
                        <div>{formatShortTime(m.sent_at || m.created_at)}</div>
                        {m.approved_by && m.approved_by !== "auto_system" && (
                          <div className="text-[11px] text-slate-500 font-sans truncate max-w-[100px]">
                            {m.approved_by}
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-right">
                        <button
                          type="button"
                          onClick={() => setSelectedMessage(m)}
                          className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm text-xs font-medium transition"
                        >
                          Xem
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Phân trang */}
        {totalCount > 0 && (
          <div className="shrink-0 px-4 py-2.5 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs">
            <div className="text-slate-600 tabular-nums">
              {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, totalCount)} / {totalCount}
            </div>
            <div className="flex items-center gap-2">
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(parseInt(e.target.value, 10));
                  setCurrentPage(1);
                }}
                className="bg-white border border-slate-300 rounded-sm px-2 py-1 text-slate-900 focus:outline-none focus:border-purple-700"
              >
                <option value={10}>10</option>
                <option value={15}>15</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1 || loading}
                className="px-2.5 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 disabled:opacity-40 transition"
              >
                Trước
              </button>
              <span className="font-mono text-slate-700 tabular-nums">
                {currentPage}/{totalPages}
              </span>
              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages || loading}
                className="px-2.5 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 disabled:opacity-40 transition"
              >
                Sau
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Modal Chi tiết (chỉ xem) */}
      {selectedMessage && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-200 rounded-sm max-w-2xl w-full p-5 text-xs text-slate-700 max-h-[90vh] overflow-y-auto space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-3">
                <h3 className="text-base font-bold text-slate-900">
                  {selectedMessage.containers?.[0]?.container_no
                    ? `Thông báo gửi — Cont ${selectedMessage.containers[0].container_no}`
                    : selectedMessage.target_group_name || "Chi tiết thông báo gửi"}
                </h3>
                {(() => {
                  const st = resolveStatusMeta(selectedMessage.status);
                  return (
                    <span className={`inline-flex items-center gap-1.5 font-medium ${st.textClass}`}>
                      <span className={`w-2 h-2 rounded-full ${st.dotClass}`} />
                      <span>{st.label}</span>
                    </span>
                  );
                })()}
              </div>
              <button
                type="button"
                onClick={() => setSelectedMessage(null)}
                className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm"
              >
                Đóng
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 bg-slate-50 p-3 rounded-sm border border-slate-200">
              <div>
                <div className="text-slate-500">Loại lệnh</div>
                <div className="text-slate-900 font-medium mt-0.5">
                  {formatOrderLabel(selectedMessage.order_type)}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Nguồn kết quả</div>
                <div className="text-slate-900 font-medium mt-0.5">
                  {resolveApprovalSourceLabel(selectedMessage)}
                  {selectedMessage.approved_by && selectedMessage.approved_by !== "auto_system"
                    ? ` (${selectedMessage.approved_by})`
                    : ""}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Nhóm nhận</div>
                <div className="text-slate-900 font-medium mt-0.5">
                  {selectedMessage.target_group_name || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Thời gian tạo</div>
                <div className="text-slate-900 font-mono mt-0.5">
                  {formatShortTime(selectedMessage.created_at)}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Thời gian gửi</div>
                <div className="text-slate-900 font-mono mt-0.5">
                  {formatShortTime(selectedMessage.sent_at)}
                </div>
              </div>
            </div>

            {selectedMessage.containers && selectedMessage.containers.length > 0 && (
              <div className="space-y-1.5">
                <div className="font-semibold text-slate-900">Thông tin xe & container</div>
                <div className="border border-slate-200 rounded-sm divide-y divide-slate-200">
                  {selectedMessage.containers.map((c, idx) => (
                    <div key={idx} className="p-2.5 font-mono text-slate-900 flex flex-wrap gap-x-4 gap-y-1">
                      <span>{c.container_no || "—"}</span>
                      <span>{c.truck_plate || "—"}</span>
                      <span className="font-sans">{c.driver_name || "—"}</span>
                      <span>{c.driver_phone || "—"}</span>
                      {c.seal_no && <span>Seal: {c.seal_no}</span>}
                      {c.eta && <span>Giờ dự kiến: {c.eta}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <div className="font-semibold text-slate-900">Nội dung gửi khách hàng</div>
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-sm text-slate-900 font-mono whitespace-pre-wrap leading-relaxed">
                {selectedMessage.content}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setSelectedMessage(null)}
                className="px-4 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
