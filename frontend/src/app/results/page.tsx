"use client";

/**
 * Trang Kết quả gửi thông báo điều xe ra nhóm Zalo khách hàng.
 * Tuân thủ bảng màu 3 tông đồng bộ với Trang tổng quan (trắng/xám, đen chữ, tím nhấn),
 * không dùng icon trang trí, không giải thích dài, tải dữ liệu thật từ Backend API.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  OutboundMessageItem,
  OutboundSummary,
  approveOutboundMessage,
  cancelOutboundMessage,
  getOutboundMessages,
  getOutboundSummary,
  resendOutboundMessage,
} from "@/lib/api";

interface StatusPresentation {
  label: string;
  dotClass: string;
  textClass: string;
  key: "SENT" | "PENDING_APPROVAL" | "PENDING_SEND" | "SENDING" | "CANCELLED" | "FAILED" | "IGNORED_DUPLICATE";
}

function resolveStatusMeta(rawStatus: string): StatusPresentation {
  const norm = (rawStatus || "").trim().toUpperCase();
  if (norm === "SENT" || norm === "DA_GUI") {
    return { key: "SENT", label: "Đã gửi", dotClass: "bg-emerald-600", textClass: "text-slate-900" };
  }
  if (norm === "PENDING_APPROVAL" || norm === "CHO_DUYET") {
    return { key: "PENDING_APPROVAL", label: "Chờ duyệt", dotClass: "bg-purple-700", textClass: "text-purple-700" };
  }
  if (norm === "PENDING_SEND") {
    return { key: "PENDING_SEND", label: "Chờ gửi", dotClass: "bg-purple-500", textClass: "text-slate-900" };
  }
  if (norm === "SENDING") {
    return { key: "SENDING", label: "Đang gửi", dotClass: "bg-amber-500", textClass: "text-slate-900" };
  }
  if (norm === "CANCELLED" || norm === "HUY") {
    return { key: "CANCELLED", label: "Bị hủy", dotClass: "bg-slate-400", textClass: "text-slate-600" };
  }
  if (norm === "FAILED" || norm === "THAT_BAI") {
    return { key: "FAILED", label: "Thất bại", dotClass: "bg-rose-600", textClass: "text-rose-700" };
  }
  return { key: "IGNORED_DUPLICATE", label: "Trùng lặp", dotClass: "bg-slate-400", textClass: "text-slate-500" };
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
    huy: 0,
    that_bai: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const [totalCount, setTotalCount] = useState(0);

  const [statusFilter, setStatusFilter] = useState<string>("");
  const [orderTypeFilter, setOrderTypeFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [fromTime, setFromTime] = useState<string>("");
  const [toTime, setToTime] = useState<string>("");

  const [selectedMessage, setSelectedMessage] = useState<OutboundMessageItem | null>(null);
  const [editContent, setEditContent] = useState<string>("");
  const [cancelTarget, setCancelTarget] = useState<OutboundMessageItem | null>(null);
  const [cancelReason, setCancelReason] = useState<string>("Điều độ hủy lệnh");

  const loadData = useCallback(
    async (
      page = currentPage,
      size = pageSize,
      filters?: {
        status?: string;
        order_type?: string;
        search?: string;
        from_time?: string;
        to_time?: string;
      }
    ) => {
      const fStatus = filters?.status !== undefined ? filters.status : statusFilter;
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
            status: fStatus || undefined,
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
    [currentPage, pageSize, statusFilter, orderTypeFilter, searchQuery, fromTime, toTime]
  );

  useEffect(() => {
    loadData(currentPage, pageSize);
  }, [currentPage, pageSize, statusFilter, orderTypeFilter]);

  const handleStatusChange = (nextStatus: string) => {
    setStatusFilter((prev) => (prev === nextStatus && nextStatus !== "" ? "" : nextStatus));
    setCurrentPage(1);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    loadData(1, pageSize);
  };

  const handleClearFilters = () => {
    setStatusFilter("");
    setOrderTypeFilter("");
    setSearchQuery("");
    setFromTime("");
    setToTime("");
    setCurrentPage(1);
    loadData(1, pageSize, {
      status: "",
      order_type: "",
      search: "",
      from_time: "",
      to_time: "",
    });
  };

  const handleApprove = async (id: string, customContent?: string) => {
    try {
      setActionLoadingId(id);
      setActionError(null);
      await approveOutboundMessage(id, "Điều độ viên", customContent);
      setSelectedMessage(null);
      await loadData(currentPage, pageSize);
    } catch (err: any) {
      setActionError(err.message || "Lỗi khi duyệt gửi tin.");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleConfirmCancel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cancelTarget) return;
    try {
      setActionLoadingId(cancelTarget.id);
      setActionError(null);
      await cancelOutboundMessage(cancelTarget.id, cancelReason.trim() || "Điều độ hủy lệnh");
      setCancelTarget(null);
      setSelectedMessage(null);
      await loadData(currentPage, pageSize);
    } catch (err: any) {
      setActionError(err.message || "Lỗi khi hủy tin.");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleResend = async (id: string) => {
    try {
      setActionLoadingId(id);
      setActionError(null);
      await resendOutboundMessage(id);
      await loadData(currentPage, pageSize);
    } catch (err: any) {
      setActionError(err.message || "Lỗi khi gửi lại tin.");
    } finally {
      setActionLoadingId(null);
    }
  };

  const openDetailModal = (m: OutboundMessageItem) => {
    setSelectedMessage(m);
    setEditContent(m.content || "");
  };

  const hasActiveFilters = Boolean(
    statusFilter || orderTypeFilter || searchQuery.trim() || fromTime || toTime
  );
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  return (
    <div className="space-y-5 text-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <button
          type="button"
          onClick={() => handleStatusChange("SENT")}
          className={`text-left p-4 rounded-sm border transition ${
            statusFilter === "SENT"
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Đã gửi</div>
          <div className="text-2xl font-bold text-slate-900 mt-2 tabular-nums">
            {summary.da_gui}
          </div>
        </button>

        <button
          type="button"
          onClick={() => handleStatusChange("PENDING_APPROVAL")}
          className={`text-left p-4 rounded-sm border transition ${
            statusFilter === "PENDING_APPROVAL"
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Chờ duyệt</div>
          <div className="text-2xl font-bold text-purple-700 mt-2 tabular-nums">
            {summary.cho_duyet}
          </div>
        </button>

        <button
          type="button"
          onClick={() => handleStatusChange("CANCELLED")}
          className={`text-left p-4 rounded-sm border transition ${
            statusFilter === "CANCELLED"
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Bị hủy</div>
          <div className="text-2xl font-bold text-slate-900 mt-2 tabular-nums">
            {summary.huy}
          </div>
        </button>

        <button
          type="button"
          onClick={() => handleStatusChange("FAILED")}
          className={`text-left p-4 rounded-sm border transition ${
            statusFilter === "FAILED"
              ? "bg-purple-50 border-purple-700"
              : "bg-white border-slate-200 hover:border-purple-300"
          }`}
        >
          <div className="text-xs font-medium text-slate-500">Thất bại</div>
          <div className="text-2xl font-bold text-slate-900 mt-2 tabular-nums">
            {summary.that_bai}
          </div>
        </button>
      </div>

      {/* Tabs lọc nhanh */}
      <div className="flex flex-wrap items-center gap-2">
        {[
          { id: "", label: `Tất cả (${summary.total})` },
          { id: "SENT", label: `Đã gửi (${summary.da_gui})` },
          { id: "PENDING_APPROVAL", label: `Chờ duyệt (${summary.cho_duyet})` },
          { id: "CANCELLED", label: `Bị hủy (${summary.huy})` },
          { id: "FAILED", label: `Thất bại (${summary.that_bai})` },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setStatusFilter(tab.id);
              setCurrentPage(1);
            }}
            className={`px-3 py-1.5 rounded-sm text-xs font-medium border transition tabular-nums ${
              statusFilter === tab.id
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
        className="bg-white border border-slate-200 p-3.5 rounded-sm grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 text-xs items-end"
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
            className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-purple-700"
          >
            <option value="">Tất cả</option>
            <option value="dong">Đóng hàng</option>
            <option value="tra">Trả hàng</option>
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

      {(error || actionError) && (
        <div className="p-3 bg-white border border-rose-300 rounded-sm text-rose-700 text-xs">
          {error || actionError}
        </div>
      )}

      {/* Bảng dữ liệu chính */}
      <div className="bg-white border border-slate-200 rounded-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-700">
            <thead className="bg-slate-50 text-slate-600 uppercase text-[11px] border-b border-slate-200">
              <tr>
                <th className="py-2.5 px-3 w-16">Mã</th>
                <th className="py-2.5 px-3 w-24">Lệnh</th>
                <th className="py-2.5 px-3 w-28">Trạng thái</th>
                <th className="py-2.5 px-3 min-w-[300px]">Thông tin chính</th>
                <th className="py-2.5 px-3 w-44">Nhóm nhận</th>
                <th className="py-2.5 px-3 w-28">Thời gian</th>
                <th className="py-2.5 px-3 text-right w-40">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {loading && messages.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-slate-500">
                    Đang tải dữ liệu...
                  </td>
                </tr>
              ) : messages.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-slate-500">
                    Không có dữ liệu phù hợp.
                  </td>
                </tr>
              ) : (
                messages.map((m) => {
                  const st = resolveStatusMeta(m.status);
                  const isPending = st.key === "PENDING_APPROVAL";
                  const isSent = st.key === "SENT";
                  const isCancelled = st.key === "CANCELLED";
                  const isFailed = st.key === "FAILED";
                  const isBusy = actionLoadingId === m.id;
                  const firstCont = m.containers?.[0];

                  return (
                    <tr key={m.id} className="hover:bg-slate-50 transition">
                      <td className="py-2.5 px-3 font-mono text-slate-600 font-medium whitespace-nowrap tabular-nums">
                        #{m.id}
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
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <span className={`inline-flex items-center gap-1.5 font-medium ${st.textClass}`}>
                          <span className={`w-2 h-2 rounded-full ${st.dotClass}`} />
                          <span>{st.label}</span>
                        </span>
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
                        {m.approved_by && (
                          <div className="text-[11px] text-slate-500 font-sans truncate max-w-[100px]">
                            {m.approved_by}
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-right">
                        <div className="inline-flex items-center gap-1.5">
                          {isPending && (
                            <button
                              type="button"
                              onClick={() => handleApprove(m.id)}
                              disabled={isBusy}
                              className="px-2.5 py-1 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-xs font-medium transition disabled:opacity-50"
                            >
                              Duyệt
                            </button>
                          )}
                          {(isFailed || isCancelled) && (
                            <button
                              type="button"
                              onClick={() => handleResend(m.id)}
                              disabled={isBusy}
                              className="px-2.5 py-1 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-xs font-medium transition disabled:opacity-50"
                            >
                              Gửi lại
                            </button>
                          )}
                          {(isPending || isSent) && (
                            <button
                              type="button"
                              onClick={() => {
                                setCancelTarget(m);
                                setCancelReason("Điều độ hủy lệnh");
                              }}
                              disabled={isBusy}
                              className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm text-xs font-medium transition disabled:opacity-50"
                            >
                              Hủy
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => openDetailModal(m)}
                            className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm text-xs font-medium transition"
                          >
                            Xem
                          </button>
                        </div>
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
          <div className="px-4 py-2.5 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs">
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

      {/* Modal Chi tiết & Duyệt sửa nội dung */}
      {selectedMessage && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-200 rounded-sm max-w-2xl w-full p-5 text-xs text-slate-700 max-h-[90vh] overflow-y-auto space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-3">
                <h3 className="text-base font-bold text-slate-900 font-mono">
                  #{selectedMessage.id}
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

            <div className="grid grid-cols-2 gap-3 bg-slate-50 p-3 rounded-sm border border-slate-200">
              <div>
                <div className="text-slate-500">Loại lệnh</div>
                <div className="text-slate-900 font-medium mt-0.5">
                  {formatOrderLabel(selectedMessage.order_type)}
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
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <div className="font-semibold text-slate-900">Nội dung gửi khách hàng</div>
              {resolveStatusMeta(selectedMessage.status).key === "PENDING_APPROVAL" ? (
                <textarea
                  rows={5}
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full p-3 bg-white border border-slate-300 rounded-sm text-slate-900 font-mono leading-relaxed focus:outline-none focus:border-purple-700"
                />
              ) : (
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-sm text-slate-900 font-mono whitespace-pre-wrap leading-relaxed">
                  {selectedMessage.content}
                </div>
              )}
            </div>

            {selectedMessage.last_error && (
              <div className="p-3 bg-slate-50 border border-rose-300 rounded-sm text-rose-700">
                {selectedMessage.last_error}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-200">
              {resolveStatusMeta(selectedMessage.status).key === "PENDING_APPROVAL" && (
                <button
                  type="button"
                  onClick={() => handleApprove(selectedMessage.id, editContent)}
                  disabled={actionLoadingId === selectedMessage.id}
                  className="px-4 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm font-medium transition disabled:opacity-50"
                >
                  Duyệt gửi
                </button>
              )}
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

      {/* Modal xác nhận hủy */}
      {cancelTarget && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleConfirmCancel}
            className="bg-white border border-slate-200 rounded-sm max-w-md w-full p-5 text-xs text-slate-700 space-y-4"
          >
            <h3 className="text-sm font-bold text-slate-900">
              Hủy tin #{cancelTarget.id}
            </h3>
            <div>
              <label className="block text-slate-600 mb-1 font-medium">Lý do hủy</label>
              <input
                type="text"
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
                className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-slate-900 focus:outline-none focus:border-purple-700"
                required
              />
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setCancelTarget(null)}
                className="px-3.5 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium"
              >
                Đóng
              </button>
              <button
                type="submit"
                disabled={actionLoadingId === cancelTarget.id}
                className="px-3.5 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm font-medium transition disabled:opacity-50"
              >
                Xác nhận hủy
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
