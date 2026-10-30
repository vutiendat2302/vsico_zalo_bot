"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  MessageSquare,
  RefreshCw,
  Eye,
  X,
  AlertTriangle,
  Clock,
  CheckCircle2,
  XCircle,
  Send,
  Truck,
  Box,
  ExternalLink,
} from "lucide-react";
import {
  ZaloMessageItem,
  getMessages,
  getMessageDetail,
  approveMessageByDHVT,
  approveOutboundMessage,
} from "@/lib/api";

export default function MessagesPage() {
  const [messages, setMessages] = useState<ZaloMessageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);

  // Filters
  const [status, setStatus] = useState<string>("");
  const [groupId, setGroupId] = useState<string>("");
  const [userId, setUserId] = useState<string>("");
  const [fromTime, setFromTime] = useState<string>("");
  const [toTime, setToTime] = useState<string>("");

  // Detail Modal State
  const [selectedMsgId, setSelectedMsgId] = useState<number | null>(null);
  const [detailData, setDetailData] = useState<any | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [approvingMsg, setApprovingMsg] = useState(false);

  const handleApproveMessage = async (msgId: number) => {
    try {
      setApprovingMsg(true);
      const res = await approveMessageByDHVT(msgId);
      alert(res.message || "ĐHVT đã duyệt tin nhắn và gửi tới Zalo thành công!");
      await handleOpenDetail(msgId);
      loadMessages(currentPage, pageSize);
    } catch (err: any) {
      alert(err.message || "Lỗi khi duyệt tin nhắn");
    } finally {
      setApprovingMsg(false);
    }
  };

  const handleApproveOutbound = async (outboundId: number) => {
    try {
      setApprovingMsg(true);
      const res = await approveOutboundMessage(outboundId, "Điều độ viên ĐHVT");
      alert(res.message || "Đã phê duyệt và gửi tin nhắn ra Nhóm Zalo!");
      if (selectedMsgId) {
        await handleOpenDetail(selectedMsgId);
      }
      loadMessages(currentPage, pageSize);
    } catch (err: any) {
      alert(err.message || "Lỗi khi duyệt tin gửi đi");
    } finally {
      setApprovingMsg(false);
    }
  };

  const loadMessages = async (page = currentPage, size = pageSize) => {
    try {
      setLoading(true);
      setError(null);
      const res = await getMessages({
        status: status || undefined,
        group_id: groupId || undefined,
        user_id: userId || undefined,
        from_time: fromTime || undefined,
        to_time: toTime || undefined,
        limit: size,
        offset: (page - 1) * size,
      });
      setMessages(res.messages);
      setTotal(res.total);
    } catch (err: any) {
      setError(err.message || "Lỗi khi lấy danh sách tin nhắn.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      const qStatus = new URLSearchParams(window.location.search).get("status");
      if (qStatus) {
        setStatus(qStatus);
        return;
      }
    }
    loadMessages(1, pageSize);
  }, []);

  useEffect(() => {
    loadMessages(currentPage, pageSize);
  }, [currentPage, pageSize, status]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    loadMessages(1, pageSize);
  };

  const handleOpenDetail = async (id: number) => {
    try {
      setSelectedMsgId(id);
      setLoadingDetail(true);
      const res = await getMessageDetail(id);
      setDetailData(res);
    } catch (err: any) {
      alert("Lỗi khi tải chi tiết tin nhắn: " + err.message);
    } finally {
      setLoadingDetail(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            <MessageSquare className="w-6 h-6 text-blue-400" />
            Quản Lý Tin Nhắn Zalo
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Toàn bộ tin nhắn nhận được qua Zalo OA & Webhook • Dữ liệu bóc tách xe, container và cảnh báo
          </p>
        </div>

        <button
          type="button"
          onClick={() => loadMessages(currentPage, pageSize)}
          disabled={loading}
          className="flex items-center space-x-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Error Message */}
      {error && (
        <div className="p-3 bg-rose-950/40 border border-rose-800 rounded-lg text-rose-300 text-xs flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Quick Status Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2 pb-1 border-b border-slate-800">
        {[
          { id: "", label: "Tất cả tin nhắn" },
          { id: "processed", label: "✅ Thành công (processed)" },
          { id: "needs_review", label: "⏳ Chờ duyệt (needs_review)" },
          { id: "cancelled", label: "🚫 Bị hủy (cancelled)" },
          { id: "failed", label: "⚠️ Thất bại / Lỗi (failed)" },
          { id: "ignored_chat", label: "💬 Tin rác / Bỏ qua" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setStatus(tab.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
              status === tab.id
                ? "bg-blue-600 text-white shadow-sm"
                : "bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-slate-800"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Filters Toolbar */}
      <form
        onSubmit={handleSearch}
        className="bg-slate-900 border border-slate-800 p-4 rounded-xl grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3 text-xs"
      >
        <div>
          <label className="block text-slate-400 mb-1 font-medium">Trạng thái:</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          >
            <option value="">Tất cả trạng thái</option>
            <option value="processed">Thành công (processed)</option>
            <option value="needs_review">Chờ duyệt (needs_review)</option>
            <option value="cancelled">Bị hủy (cancelled)</option>
            <option value="failed">Thất bại / Lỗi (failed)</option>
            <option value="ignored_chat">Tin rác / Xã giao (ignored)</option>
            <option value="received">Mới nhận / Chờ xử lý</option>
          </select>
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Group ID:</label>
          <input
            type="text"
            placeholder="Lọc theo Group ID"
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-mono"
          />
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">User ID:</label>
          <input
            type="text"
            placeholder="Lọc theo User ID người gửi"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-mono"
          />
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Từ ngày:</label>
          <input
            type="date"
            value={fromTime}
            onChange={(e) => setFromTime(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-slate-400 mb-1 font-medium">Đến ngày:</label>
          <div className="flex gap-2">
            <input
              type="date"
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
            />
            <button
              type="submit"
              className="bg-blue-600 hover:bg-blue-500 text-white px-3 py-2 rounded-lg font-medium"
            >
              Lọc
            </button>
          </div>
        </div>
      </form>

      {/* Messages Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="p-3 border-b border-slate-800 text-xs text-slate-400 flex items-center justify-between">
          <span>
            Tìm thấy <strong className="text-white">{messages.length}</strong> / {total} tin nhắn
          </span>
        </div>

        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-950/80 sticky top-0 text-slate-300 font-semibold border-b border-slate-800 whitespace-nowrap">
              <tr>
                <th className="py-3 px-3">ID</th>
                <th className="py-3 px-3">Người gửi</th>
                <th className="py-3 px-3">Group ID</th>
                <th className="py-3 px-3">Thời gian</th>
                <th className="py-3 px-3">Trạng thái</th>
                <th className="py-3 px-4 min-w-[280px]">Nội dung gốc</th>
                <th className="py-3 px-3">Xe bóc tách</th>
                <th className="py-3 px-3">Container</th>
                <th className="py-3 px-3 text-center">Chi tiết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-normal">
              {messages.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-slate-500">
                    Không có tin nhắn nào khớp với bộ lọc.
                  </td>
                </tr>
              ) : (
                messages.map((m) => {
                  const plates = (m.trucks || []).map((t) => t?.truck_plate).filter(Boolean);
                  const conts = (m.containers || []).map((c) => c?.container_no).filter(Boolean);
                  return (
                    <tr key={m.id} className="hover:bg-slate-800/40 transition">
                      <td className="py-2.5 px-3 font-mono text-slate-400">#{m.id}</td>
                      <td className="py-2.5 px-3 whitespace-nowrap font-medium text-slate-200">
                        {m.sender_name || m.sender_id || "Chưa rõ"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap font-mono text-slate-400">
                        {m.group_id || "Direct"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-400">
                        {(m.sent_at || m.received_at)?.slice(0, 16).replace("T", " ") || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        {m.processing_status === "processed" && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 inline-flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                            Thành công
                          </span>
                        )}
                        {m.processing_status === "needs_review" && (
                          <div className="flex items-center space-x-1.5">
                            <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30 inline-flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
                              Chờ duyệt
                            </span>
                            <Link
                              href="/reviews"
                              className="text-[10px] text-amber-300 hover:text-amber-200 underline font-medium"
                              title="Chuyển tới trang phê duyệt"
                            >
                              Duyệt ngay
                            </Link>
                          </div>
                        )}
                        {m.processing_status === "cancelled" && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30 inline-flex items-center gap-1">
                            <XCircle className="w-3 h-3 text-rose-400" />
                            Bị hủy
                          </span>
                        )}
                        {m.processing_status === "failed" && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30 inline-flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3 text-rose-400" />
                            Thất bại
                          </span>
                        )}
                        {m.processing_status === "ignored_chat" && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">
                            Tin rác / Xã giao
                          </span>
                        )}
                        {m.processing_status === "received" && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-500/15 text-blue-400 border border-blue-500/30 inline-flex items-center gap-1">
                            <Clock className="w-3 h-3 text-blue-400" />
                            Mới nhận
                          </span>
                        )}
                        {!["processed", "needs_review", "cancelled", "failed", "ignored_chat", "received"].includes(m.processing_status) && (
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-400">
                            {m.processing_status}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-slate-300 max-w-md truncate" title={m.raw_text || ""}>
                        {m.raw_text || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        {plates.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {plates.map((p, idx) => (
                              <span key={idx} className="bg-blue-950/80 text-blue-300 px-1.5 py-0.5 rounded text-[11px] font-mono">
                                {p}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        {conts.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {conts.map((c, idx) => (
                              <span key={idx} className="bg-purple-950/80 text-purple-300 px-1.5 py-0.5 rounded text-[11px] font-mono font-semibold">
                                {c}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-center whitespace-nowrap">
                        <button
                          onClick={() => handleOpenDetail(m.id)}
                          className="inline-flex items-center space-x-1 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-blue-400 rounded text-xs transition"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          <span>Xem</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Toolbar */}
        {total > 0 && (
          <div className="px-4 py-3 bg-slate-950/80 border-t border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-slate-400">
              Hiển thị <span className="font-semibold text-white">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-white">{Math.min(currentPage * pageSize, total)}</span> trong{" "}
              <span className="font-semibold text-white">{total}</span> tin nhắn
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
                  className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-blue-500"
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
                Trang <span className="text-white font-bold">{currentPage}</span> / {Math.ceil(total / pageSize) || 1}
              </span>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(Math.ceil(total / pageSize), p + 1))}
                disabled={currentPage >= Math.ceil(total / pageSize) || loading}
                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700 transition"
              >
                Sau →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {selectedMsgId && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-3xl w-full p-6 text-xs text-slate-300 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <span>Chi Tiết Tin Nhắn #{selectedMsgId}</span>
                {detailData?.message?.processing_status && (
                  <span className="text-xs px-2 py-0.5 rounded font-mono bg-blue-950 text-blue-400 border border-blue-800">
                    {detailData.message.processing_status}
                  </span>
                )}
              </h3>
              <div className="flex items-center space-x-2">
                {(detailData?.message?.processing_status === "needs_review" ||
                  detailData?.outbound_messages?.some((o: any) => o.status === "cho_duyet")) && (
                  <button
                    type="button"
                    disabled={approvingMsg}
                    onClick={() => handleApproveMessage(selectedMsgId)}
                    className="flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition shadow-sm disabled:opacity-50"
                  >
                    <CheckCircle2 className={`w-4 h-4 ${approvingMsg ? "animate-spin" : ""}`} />
                    <span>{approvingMsg ? "Đang gửi Zalo..." : "ĐHVT Duyệt & Gửi Zalo"}</span>
                  </button>
                )}
                <button
                  onClick={() => {
                    setSelectedMsgId(null);
                    setDetailData(null);
                  }}
                >
                  <X className="w-5 h-5 text-slate-400 hover:text-white" />
                </button>
              </div>
            </div>

            {loadingDetail ? (
              <div className="py-12 text-center text-slate-400">Đang tải chi tiết tin nhắn...</div>
            ) : (
              <div className="space-y-5 mt-4">
                {/* 1. Raw message block */}
                <div>
                  <div className="text-xs font-semibold text-slate-400 mb-1.5 flex items-center gap-1.5">
                    <MessageSquare className="w-3.5 h-3.5 text-blue-400" />
                    <span>NỘI DUNG TIN NHẮN GỐC NHẬN TỪ ZALO:</span>
                  </div>
                  <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg font-mono text-sm text-slate-200 whitespace-pre-wrap leading-relaxed shadow-inner">
                    {detailData?.message?.raw_text}
                  </div>
                </div>

                {/* 2. FORM TIN NHẮN GỬI ĐI CHO KHÁCH HÀNG / NHÓM ZALO */}
                {detailData?.outbound_messages && detailData.outbound_messages.length > 0 ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-bold text-emerald-400 flex items-center gap-1.5 uppercase tracking-wide">
                        <Send className="w-3.5 h-3.5 text-emerald-400" />
                        <span>Form Tin Nhắn Gửi Đi Tới Nhóm Zalo ({detailData.outbound_messages.length} thông báo)</span>
                      </div>
                      <Link
                        href="/results"
                        className="text-[11px] text-blue-400 hover:text-blue-300 hover:underline flex items-center gap-1 font-medium"
                      >
                        <span>Xem chi tiết tại Kết Quả Outbound</span>
                        <ExternalLink className="w-3 h-3" />
                      </Link>
                    </div>

                    <div className="space-y-3">
                      {detailData.outbound_messages.map((out: any) => (
                        <div
                          key={out.id}
                          className="bg-slate-950 border border-emerald-500/40 rounded-xl p-4 space-y-3 shadow-lg"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-800 text-xs">
                            <div className="flex items-center gap-2">
                              <span
                                className={`px-2 py-0.5 rounded font-semibold text-[11px] ${
                                  out.status === "da_gui"
                                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                                    : out.status === "cho_duyet"
                                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                                    : out.status === "bo_qua_trung_lap"
                                    ? "bg-slate-700/40 text-slate-300 border border-slate-600"
                                    : "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                                }`}
                              >
                                {out.status === "da_gui"
                                  ? "✅ ĐÃ GỬI TỚI NHÓM ZALO"
                                  : out.status === "cho_duyet"
                                  ? "⏳ CHỜ PHÊ DUYỆT"
                                  : out.status === "bo_qua_trung_lap"
                                  ? "🛡️ BỎ QUA GỬI TRÙNG"
                                  : "❌ GỬI THẤT BẠI"}
                              </span>
                              {out.message_kind === "update" && (
                                <span className="px-2 py-0.5 rounded font-semibold text-[11px] bg-amber-500/20 text-amber-300 border border-amber-500/40">
                                  🔄 CẬP NHẬT XE
                                </span>
                              )}
                              <span className="text-slate-400">
                                Nhóm đích:{" "}
                                <strong className="text-white font-mono">
                                  {out.target_zalo_group_id || out.target_group_name}
                                </strong>
                              </span>
                            </div>
                            {out.zalo_message_id && (
                              <span className="text-[11px] font-mono text-emerald-400/90 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-800/40">
                                Zalo MsgID: {out.zalo_message_id}
                              </span>
                            )}
                            {out.status === "cho_duyet" && (
                              <button
                                type="button"
                                disabled={approvingMsg}
                                onClick={() => handleApproveOutbound(out.id)}
                                className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[11px] font-semibold transition disabled:opacity-50 flex items-center gap-1 shadow-sm"
                              >
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                <span>{approvingMsg ? "Đang gửi..." : "Duyệt & Gửi ngay"}</span>
                              </button>
                            )}
                          </div>

                          {/* Khung bong bóng tin nhắn gửi đi thực tế */}
                          <div>
                            <div className="text-[11px] font-semibold text-slate-400 mb-1 flex items-center gap-1">
                              <span>Nội dung gửi vào nhóm Zalo khách hàng:</span>
                            </div>
                            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3.5 font-mono text-xs sm:text-sm text-slate-100 whitespace-pre-wrap leading-relaxed shadow-inner">
                              {out.content}
                            </div>
                          </div>

                          {out.last_error && (
                            <div className="text-[11px] text-rose-400 bg-rose-950/30 p-2 rounded border border-rose-800/30">
                              Lỗi gửi: {out.last_error}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg text-slate-400 text-xs flex items-center justify-between">
                    <span className="flex items-center gap-1.5">
                      <Send className="w-3.5 h-3.5 text-slate-500" />
                      <span>
                        Chưa có tin nhắn gửi khách hàng (Outbound) cho tin nhắn này
                        {detailData?.message?.processing_status === "needs_review" && " • Đang chờ ĐHVT phê duyệt"}
                        {detailData?.message?.processing_status === "ignored_chat" && " • Tin rác/xã giao, không cần gửi thông báo"}
                      </span>
                    </span>
                  </div>
                )}

                {/* 3. KẾT QUẢ XỬ LÝ LỖI & CẢNH BÁO NGHIỆP VỤ (Nếu tin có lỗi hoặc cần rà soát) */}
                {(detailData?.review_cases?.length > 0 ||
                  detailData?.bot_replies?.length > 0 ||
                  detailData?.message?.processing_status === "needs_review" ||
                  detailData?.message?.processing_status === "failed") && (
                  <div className="bg-amber-950/20 border border-amber-500/40 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-bold text-amber-400 flex items-center gap-1.5 uppercase tracking-wide">
                        <AlertTriangle className="w-4 h-4 text-amber-400" />
                        <span>Kết Quả Xử Lý: Cảnh Báo Nghiệp Vụ & Lỗi Dữ Liệu</span>
                      </div>
                      <Link
                        href="/reviews"
                        className="text-xs bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold px-3 py-1 rounded transition flex items-center gap-1"
                      >
                        <span>Duyệt tại Hàng Đợi (Reviews)</span>
                        <ExternalLink className="w-3 h-3" />
                      </Link>
                    </div>

                    {/* Danh sách các ca review */}
                    {detailData?.review_cases?.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-xs text-amber-300 font-semibold">Lý do cảnh báo / ca cần duyệt:</div>
                        {detailData.review_cases.map((rc: any) => (
                          <div
                            key={rc.id}
                            className="p-2.5 bg-amber-950/50 border border-amber-800/50 rounded-lg text-xs text-amber-200 space-y-1"
                          >
                            <div className="flex items-center justify-between font-mono">
                              <span className="font-bold text-amber-300">Ca #{rc.id}: {rc.case_type}</span>
                              <span className="text-[10px] bg-amber-900/60 px-1.5 py-0.5 rounded text-amber-200">
                                {rc.status}
                              </span>
                            </div>
                            <div>{rc.reason}</div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Tin Bot phản hồi nhắc nhà xe */}
                    {detailData?.bot_replies?.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-xs text-rose-300 font-semibold">Tin nhắn Bot đã nhắc nhà xe sửa lỗi:</div>
                        {detailData.bot_replies.map((br: any) => (
                          <div
                            key={br.id}
                            className="p-3 bg-slate-900 border border-rose-800/50 rounded-lg font-mono text-xs text-rose-300 whitespace-pre-wrap"
                          >
                            {br.reply_text}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* 4. CHI TIẾT XE VÀ CONTAINER BÓC TÁCH ĐƯỢC (Giao diện trực quan) */}
                <div className="space-y-3">
                  <div className="text-xs font-semibold text-slate-400 flex items-center gap-1.5 uppercase tracking-wider">
                    <Truck className="w-3.5 h-3.5 text-blue-400" />
                    <span>Phương Tiện & Container Đã Bóc Tách:</span>
                  </div>

                  {/* Danh sách xe & lái xe */}
                  {detailData?.message?.trucks && detailData.message.trucks.length > 0 && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {detailData.message.trucks.map((t: any) => (
                        <div
                          key={t.id}
                          className="bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-1.5 text-xs"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono font-bold text-white bg-slate-900 px-2 py-0.5 rounded border border-slate-700">
                              🚛 Xe: {t.truck_plate || "Chưa rõ biển"}
                            </span>
                            {t.trailer_plate && (
                              <span className="text-[11px] text-slate-400 font-mono">
                                Mooc: {t.trailer_plate}
                              </span>
                            )}
                          </div>
                          <div className="text-slate-300">
                            Lái xe: <strong className="text-white">{t.driver_name || "Chưa rõ"}</strong>
                          </div>
                          <div className="text-slate-300">
                            SĐT liên hệ:{" "}
                            <strong className="text-emerald-400 font-mono text-sm">
                              {t.driver_phone || "Không có SĐT"}
                            </strong>
                          </div>
                          {t.eta_text && (
                            <div className="text-slate-400 text-[11px]">
                              ETA: <span className="text-amber-300 font-medium">{t.eta_text}</span>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Danh sách containers */}
                  <div className="space-y-2.5">
                    {(detailData?.message?.containers || []).map((c: any) => (
                      <div
                        key={c.id}
                        className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 space-y-2.5 hover:border-slate-700 transition"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold text-white text-sm bg-slate-900 px-2.5 py-1 rounded border border-slate-700">
                              📦 Cont: {c.container_no || "Chưa có cont"}
                            </span>
                            {c.container_size && (
                              <span className="text-xs text-blue-300 font-mono">
                                ({c.container_size}&#39;)
                              </span>
                            )}
                            {c.seal_no && (
                              <span className="text-xs text-slate-300 font-mono">
                                (Chì: <strong className="text-amber-400">{c.seal_no}</strong>)
                              </span>
                            )}
                            <span className={`text-[11px] px-2 py-0.5 rounded font-semibold ${
                              c.order_type === "dong" ? "bg-blue-500/20 text-blue-300" : "bg-emerald-500/20 text-emerald-300"
                            }`}>
                              {c.order_type === "dong" ? "LỆNH ĐÓNG" : c.order_type === "tra" ? "LỆNH TRẢ" : "CHƯA RÕ"}
                            </span>
                          </div>

                          <span className={`text-[11px] px-2 py-0.5 rounded ${
                            c.validation_status === "valid" ? "bg-emerald-950 text-emerald-400" : "bg-amber-950 text-amber-400"
                          }`}>
                            {c.validation_status === "valid" ? "✅ Hợp lệ ISO 6346" : "⚠️ Cần kiểm tra"}
                          </span>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-slate-300 pt-1 border-t border-slate-900">
                          <div>
                            Khách hàng: <strong className="text-white">{c.customer_hint || "N/A"}</strong>
                          </div>
                          <div>
                            Điểm nhận/giao: <strong className="text-white">{c.warehouse_hint || "N/A"}</strong>
                          </div>
                          <div>
                            Nguồn ghép: <strong className="text-purple-300 font-mono">{c.match_source || "unmatched"}</strong>
                          </div>
                          <div>
                            Định dạng: <strong className="text-blue-300 font-mono">{c.source_format || "tu_do"}</strong>
                          </div>
                        </div>

                        {(c.warnings || []).length > 0 && (
                          <div className="flex flex-wrap gap-1 text-[11px] text-amber-400 pt-1">
                            {(c.warnings || []).map((w: string, i: number) => (
                              <span key={i} className="bg-amber-950/60 px-2 py-0.5 rounded border border-amber-800/50">
                                ⚠️ {w}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
