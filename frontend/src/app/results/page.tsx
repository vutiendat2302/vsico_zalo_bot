"use client";

/**
 * Trang Quản lý & Xem Kết Quả Tin Nhắn (Message Results & Outbound Dispatch Notifications).
 * 
 * Hiển thị toàn diện các trạng thái kết quả tin nhắn:
 * - Đã gửi (da_gui): Tin thông báo điều xe đã gửi thành công tới nhóm Zalo khách hàng.
 * - Chờ duyệt (cho_duyet): Tin thông báo đang chờ điều độ viên duyệt trước khi bắn ra ngoài.
 * - Bị hủy (huy): Tin thông báo bị hủy do thay đổi chuyến hoặc điều độ từ chối.
 * - Thất bại (that_bai): Gửi không thành công (lỗi mạng hoặc rate limit Zalo OA).
 * 
 * Tuân thủ nghiêm ngặt quy tắc Zero Mock Data: Dữ liệu tải trực tiếp từ GET /api/outbound/messages và /api/outbound/summary.
 */

import React, { useEffect, useState } from "react";
import {
  Send,
  CheckCircle2,
  Clock,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  Eye,
  Check,
  X,
  RotateCcw,
  PlusCircle,
  MessageSquare,
} from "lucide-react";
import {
  OutboundMessageItem,
  OutboundSummary,
  getOutboundSummary,
  getOutboundMessages,
  approveOutboundMessage,
  cancelOutboundMessage,
  resendOutboundMessage,
  seedOutboundSamples,
} from "@/lib/api";

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
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const [totalCount, setTotalCount] = useState(0);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [orderTypeFilter, setOrderTypeFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [fromTime, setFromTime] = useState<string>("");
  const [toTime, setToTime] = useState<string>("");

  // Modal State
  const [selectedMessage, setSelectedMessage] = useState<OutboundMessageItem | null>(null);

  /**
   * Tải số liệu thống kê và danh sách kết quả tin nhắn từ Backend API.
   */
  const loadData = async (page = currentPage, size = pageSize) => {
    try {
      setLoading(true);
      setError(null);
      const [sumRes, listRes] = await Promise.all([
        getOutboundSummary(),
        getOutboundMessages({
          status: statusFilter || undefined,
          order_type: orderTypeFilter || undefined,
          search: searchQuery || undefined,
          from_time: fromTime || undefined,
          to_time: toTime || undefined,
          limit: size,
          offset: (page - 1) * size,
        }),
      ]);
      setSummary(sumRes);
      setMessages(listRes.messages);
      setTotalCount(listRes.total);
    } catch (err: any) {
      setError(err.message || "Lỗi khi tải danh sách kết quả tin nhắn.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setCurrentPage(1);
    loadData(1, pageSize);
  }, [statusFilter, orderTypeFilter]);

  useEffect(() => {
    loadData(currentPage, pageSize);
  }, [currentPage, pageSize]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    loadData(1, pageSize);
  };

  const handleApprove = async (id: number) => {
    try {
      setActionLoadingId(id);
      await approveOutboundMessage(id, "Điều độ viên");
      await loadData();
    } catch (err: any) {
      alert("Lỗi khi duyệt gửi tin: " + err.message);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleCancel = async (id: number) => {
    const reason = prompt("Nhập lý do hủy tin nhắn này:", "Điều độ viên hủy lệnh điều xe.");
    if (reason === null) return;
    try {
      setActionLoadingId(id);
      await cancelOutboundMessage(id, reason);
      await loadData();
    } catch (err: any) {
      alert("Lỗi khi hủy tin: " + err.message);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleResend = async (id: number) => {
    try {
      setActionLoadingId(id);
      await resendOutboundMessage(id);
      await loadData();
    } catch (err: any) {
      alert("Lỗi khi gửi lại tin: " + err.message);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleSeedSamples = async () => {
    try {
      setLoading(true);
      await seedOutboundSamples();
      await loadData();
    } catch (err: any) {
      alert("Lỗi khi tạo dữ liệu mẫu: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2.5">
            <Send className="w-6 h-6 text-indigo-400" />
            Kết Quả Tin Nhắn & Thông Báo Điều Xe
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Theo dõi tình trạng gửi tin nhắn ra Zalo OA: Đã gửi thành công, Chờ duyệt gửi, Bị hủy, Thất bại
          </p>
        </div>

        <div className="flex items-center space-x-2.5">
          <button
            onClick={handleSeedSamples}
            disabled={loading}
            className="flex items-center space-x-1.5 px-3 py-2 bg-indigo-950/80 hover:bg-indigo-900 text-indigo-300 rounded-lg text-xs font-medium border border-indigo-800 transition"
            title="Tạo các bản ghi kết quả mẫu với đủ 4 trạng thái để kiểm thử trực quan"
          >
            <PlusCircle className="w-3.5 h-3.5 text-indigo-400" />
            <span>Tạo mẫu kiểm thử</span>
          </button>

          <button
            type="button"
            onClick={() => loadData(currentPage, pageSize)}
            disabled={loading}
            className="flex items-center space-x-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {/* KPI Cards: 4 Trạng thái chính */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3.5">
        <div
          onClick={() => setStatusFilter("da_gui")}
          className={`cursor-pointer p-4 rounded-xl border transition shadow-sm ${
            statusFilter === "da_gui"
              ? "bg-emerald-950/40 border-emerald-500/80 ring-1 ring-emerald-500"
              : "bg-slate-900 border-slate-800 hover:border-slate-700"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">
              Đã gửi (da_gui)
            </span>
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-white mt-1.5">{summary.da_gui}</div>
          <p className="text-[11px] text-slate-500 mt-0.5">Đã xuất bản ra nhóm Zalo</p>
        </div>

        <div
          onClick={() => setStatusFilter("cho_duyet")}
          className={`cursor-pointer p-4 rounded-xl border transition shadow-sm ${
            statusFilter === "cho_duyet"
              ? "bg-amber-950/40 border-amber-500/80 ring-1 ring-amber-500"
              : "bg-slate-900 border-slate-800 hover:border-slate-700"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
              Chờ duyệt (cho_duyet)
            </span>
            <Clock className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-amber-300 mt-1.5">{summary.cho_duyet}</div>
          <p className="text-[11px] text-slate-500 mt-0.5">Chờ điều độ bấm gửi</p>
        </div>

        <div
          onClick={() => setStatusFilter("huy")}
          className={`cursor-pointer p-4 rounded-xl border transition shadow-sm ${
            statusFilter === "huy"
              ? "bg-rose-950/40 border-rose-500/80 ring-1 ring-rose-500"
              : "bg-slate-900 border-slate-800 hover:border-slate-700"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-rose-400 uppercase tracking-wider">
              Bị hủy (huy)
            </span>
            <XCircle className="w-4 h-4 text-rose-400" />
          </div>
          <div className="text-2xl font-bold text-rose-300 mt-1.5">{summary.huy}</div>
          <p className="text-[11px] text-slate-500 mt-0.5">Đã hủy cuốc / từ chối</p>
        </div>

        <div
          onClick={() => setStatusFilter("that_bai")}
          className={`cursor-pointer p-4 rounded-xl border transition shadow-sm ${
            statusFilter === "that_bai"
              ? "bg-purple-950/40 border-purple-500/80 ring-1 ring-purple-500"
              : "bg-slate-900 border-slate-800 hover:border-slate-700"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-purple-400 uppercase tracking-wider">
              Thất bại (that_bai)
            </span>
            <AlertTriangle className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-bold text-purple-300 mt-1.5">{summary.that_bai}</div>
          <p className="text-[11px] text-slate-500 mt-0.5">Lỗi mạng / Rate limit Zalo</p>
        </div>
      </div>

      {/* Error notification */}
      {error && (
        <div className="p-3 bg-rose-950/40 border border-rose-800 rounded-lg text-rose-300 text-xs flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Quick Status Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2 pb-1 border-b border-slate-800">
        {[
          { id: "", label: `Tất cả kết quả (${summary.total})` },
          { id: "da_gui", label: `📤 Đã gửi (${summary.da_gui})` },
          { id: "cho_duyet", label: `⏳ Chờ duyệt (${summary.cho_duyet})` },
          { id: "huy", label: `🚫 Bị hủy (${summary.huy})` },
          { id: "that_bai", label: `⚠️ Thất bại (${summary.that_bai})` },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setStatusFilter(tab.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
              statusFilter === tab.id
                ? "bg-indigo-600 text-white shadow-sm"
                : "bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-slate-800"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search & Filters Toolbar */}
      <form
        onSubmit={handleSearchSubmit}
        className="bg-slate-900 border border-slate-800 p-4 rounded-xl grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 text-xs"
      >
        <div className="relative">
          <label className="block text-slate-400 mb-1 font-medium">Tìm kiếm:</label>
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Nội dung, cont, biển số..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-8 pr-3 py-2 text-white focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Loại lệnh:</label>
          <select
            value={orderTypeFilter}
            onChange={(e) => setOrderTypeFilter(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-indigo-500"
          >
            <option value="">Tất cả (Đóng & Trả)</option>
            <option value="tra">Lệnh Trả Hàng (tra)</option>
            <option value="dong">Lệnh Đóng Hàng (dong)</option>
          </select>
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Từ ngày:</label>
          <input
            type="date"
            value={fromTime}
            onChange={(e) => setFromTime(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Đến ngày:</label>
          <div className="flex gap-2">
            <input
              type="date"
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-indigo-500"
            />
            <button
              type="submit"
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-medium transition"
            >
              Lọc
            </button>
          </div>
        </div>
      </form>

      {/* Messages List Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-950/60 text-slate-400 uppercase text-[11px] tracking-wider border-b border-slate-800">
              <tr>
                <th className="py-3 px-3 w-16">Mã</th>
                <th className="py-3 px-3 w-24">Lệnh</th>
                <th className="py-3 px-3 w-32">Trạng thái</th>
                <th className="py-3 px-4 min-w-[280px]">Nội dung gửi khách hàng</th>
                <th className="py-3 px-3 w-44">Nhóm Zalo đích</th>
                <th className="py-3 px-3 w-36">Thời gian</th>
                <th className="py-3 px-3 text-center w-36">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-normal">
              {loading && messages.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-400" />
                    Đang tải dữ liệu kết quả tin nhắn từ máy chủ...
                  </td>
                </tr>
              ) : messages.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    <MessageSquare className="w-8 h-8 mx-auto mb-2 text-slate-600" />
                    Chưa có tin nhắn kết quả nào khớp với bộ lọc.
                  </td>
                </tr>
              ) : (
                messages.map((m) => {
                  const isPending = m.status === "cho_duyet";
                  const isSent = m.status === "da_gui";
                  const isCancelled = m.status === "huy";
                  const isFailed = m.status === "that_bai";
                  const isDuplicate = m.status === "bo_qua_trung_lap";
                  const isBusy = actionLoadingId === m.id;

                  return (
                    <tr key={m.id} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-3 font-mono text-slate-400 font-semibold">
                        #{m.id}
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                            m.order_type === "dong"
                              ? "bg-purple-950/80 text-purple-300 border border-purple-800"
                              : "bg-sky-950/80 text-sky-300 border border-sky-800"
                          }`}
                        >
                          {m.order_type === "dong" ? "Đóng hàng" : "Trả hàng"}
                        </span>
                        {m.message_kind === "update" && (
                          <span className="ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                            Cập nhật xe
                          </span>
                        )}
                      </td>

                      {/* Status Badge */}
                      <td className="py-3 px-3 whitespace-nowrap">
                        {isSent && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 inline-flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                            Đã gửi
                          </span>
                        )}
                        {isPending && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30 inline-flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
                            Chờ duyệt
                          </span>
                        )}
                        {isCancelled && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30 inline-flex items-center gap-1">
                            <XCircle className="w-3 h-3 text-rose-400" />
                            Bị hủy
                          </span>
                        )}
                        {isFailed && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-purple-500/15 text-purple-300 border border-purple-500/30 inline-flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3 text-purple-400" />
                            Thất bại
                          </span>
                        )}
                        {isDuplicate && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-700/50 text-slate-300 border border-slate-600 inline-flex items-center gap-1">
                            Bỏ qua (trùng)
                          </span>
                        )}
                      </td>

                      {/* Content Preview */}
                      <td className="py-3 px-4 font-mono text-slate-300 max-w-sm truncate" title={m.content}>
                        {m.content}
                      </td>

                      {/* Target Group */}
                      <td className="py-3 px-3 whitespace-nowrap text-slate-300">
                        <div className="font-medium truncate max-w-[150px]">{m.target_group_name}</div>
                        {m.target_zalo_group_id && (
                          <div className="text-[10px] text-slate-500 font-mono">
                            {m.target_zalo_group_id}
                          </div>
                        )}
                      </td>

                      {/* Timestamps */}
                      <td className="py-3 px-3 whitespace-nowrap text-slate-400 font-mono text-[11px]">
                        <div>{m.sent_at ? `Gửi: ${m.sent_at.slice(0, 16).replace("T", " ")}` : `Tạo: ${m.created_at?.slice(0, 16).replace("T", " ")}`}</div>
                        {m.approved_by && (
                          <div className="text-[10px] text-emerald-400 truncate max-w-[120px]">
                            Duyệt: {m.approved_by}
                          </div>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-3 whitespace-nowrap text-center">
                        <div className="inline-flex items-center space-x-1.5">
                          {isPending && (
                            <button
                              onClick={() => handleApprove(m.id)}
                              disabled={isBusy}
                              className="px-2 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[11px] font-medium transition inline-flex items-center space-x-1 shadow-sm"
                              title="Phê duyệt và kích hoạt gửi ra Zalo OA"
                            >
                              <Check className="w-3 h-3" />
                              <span>Duyệt</span>
                            </button>
                          )}

                          {(isPending || isSent) && (
                            <button
                              onClick={() => handleCancel(m.id)}
                              disabled={isBusy}
                              className="px-2 py-1 bg-slate-800 hover:bg-rose-950 text-slate-400 hover:text-rose-300 rounded text-[11px] font-medium border border-slate-700 hover:border-rose-800 transition inline-flex items-center space-x-1"
                              title="Hủy tin nhắn thông báo này"
                            >
                              <X className="w-3 h-3" />
                              <span>Hủy</span>
                            </button>
                          )}

                          {(isFailed || isCancelled) && (
                            <button
                              onClick={() => handleResend(m.id)}
                              disabled={isBusy}
                              className="px-2 py-1 bg-indigo-950 hover:bg-indigo-900 text-indigo-300 rounded text-[11px] font-medium border border-indigo-800 transition inline-flex items-center space-x-1"
                              title="Thử gửi lại tin này ra Zalo OA"
                            >
                              <RotateCcw className="w-3 h-3" />
                              <span>Gửi lại</span>
                            </button>
                          )}

                          <button
                            onClick={() => setSelectedMessage(m)}
                            className="p-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded transition"
                            title="Xem chi tiết nội dung tin nhắn"
                          >
                            <Eye className="w-3.5 h-3.5" />
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

        {/* Pagination Toolbar */}
        {totalCount > 0 && (
          <div className="px-4 py-3 bg-slate-950/80 border-t border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-slate-400">
              Hiển thị <span className="font-semibold text-white">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-white">{Math.min(currentPage * pageSize, totalCount)}</span> trong{" "}
              <span className="font-semibold text-white">{totalCount}</span> tin nhắn kết quả
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
                  className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value={10}>10</option>
                  <option value={15}>15</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                </select>
              </div>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1 || loading}
                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700 transition"
              >
                ← Trước
              </button>

              <span className="px-2 font-mono text-slate-300">
                Trang <span className="text-white font-bold">{currentPage}</span> / {Math.ceil(totalCount / pageSize) || 1}
              </span>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(Math.ceil(totalCount / pageSize), p + 1))}
                disabled={currentPage >= Math.ceil(totalCount / pageSize) || loading}
                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700 transition"
              >
                Sau →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {selectedMessage && (
        <div className="fixed inset-0 bg-black/75 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-2xl w-full p-6 text-xs text-slate-300 max-h-[90vh] overflow-y-auto space-y-4 shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Send className="w-4 h-4 text-indigo-400" />
                <span>Chi Tiết Tin Nhắn Kết Quả #{selectedMessage.id}</span>
                <span className="text-xs px-2 py-0.5 rounded font-mono bg-indigo-950 text-indigo-300 border border-indigo-800">
                  {selectedMessage.status}
                </span>
              </h3>
              <button
                onClick={() => setSelectedMessage(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Info grid */}
            <div className="grid grid-cols-2 gap-3 bg-slate-950 p-3.5 rounded-lg border border-slate-800">
              <div>
                <span className="text-slate-500 block">Loại lệnh:</span>
                <span className="text-slate-200 font-semibold uppercase">{selectedMessage.order_type}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Nhóm Zalo nhận:</span>
                <span className="text-slate-200">{selectedMessage.target_group_name}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Thời gian tạo:</span>
                <span className="text-slate-200 font-mono">{selectedMessage.created_at || "—"}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Thời gian gửi Zalo:</span>
                <span className="text-slate-200 font-mono">{selectedMessage.sent_at || "Chưa gửi"}</span>
              </div>
              {selectedMessage.approved_by && (
                <div>
                  <span className="text-slate-500 block">Người duyệt:</span>
                  <span className="text-emerald-400">{selectedMessage.approved_by}</span>
                </div>
              )}
              {selectedMessage.zalo_message_id && (
                <div>
                  <span className="text-slate-500 block">Mã Zalo Msg ID:</span>
                  <span className="text-indigo-400 font-mono">{selectedMessage.zalo_message_id}</span>
                </div>
              )}
            </div>

            {/* Content text */}
            <div>
              <h4 className="font-semibold text-slate-200 mb-1.5 flex items-center gap-1.5">
                <MessageSquare className="w-3.5 h-3.5 text-indigo-400" />
                Nội Dung Tin Nhắn Gửi Ra Zalo OA:
              </h4>
              <div className="p-3.5 bg-slate-950 border border-slate-800 rounded-lg text-slate-200 font-mono whitespace-pre-wrap leading-relaxed text-xs">
                {selectedMessage.content}
              </div>
            </div>

            {/* Error or cancellation reason */}
            {selectedMessage.last_error && (
              <div className="p-3 bg-rose-950/40 border border-rose-800/80 rounded-lg text-rose-300">
                <span className="font-semibold block mb-0.5">Lý do / Lỗi ghi nhận:</span>
                <span>{selectedMessage.last_error}</span>
              </div>
            )}

            <div className="flex justify-end pt-2 border-t border-slate-800">
              <button
                onClick={() => setSelectedMessage(null)}
                className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs"
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
