"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import {
  ZaloMessageItem,
  getMessages,
  getMessageDetail,
  approveMessageByDHVT,
  rejectMessageByDHVT,
  approveOutboundMessage,
} from "@/lib/api";
import { toast } from "@/components/shared/Toast";

export default function MessagesPage() {
  const [messages, setMessages] = useState<ZaloMessageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);

  // Filters & Search
  const [search, setSearch] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [groupId, setGroupId] = useState<string>("");
  const [userId, setUserId] = useState<string>("");
  const [fromTime, setFromTime] = useState<string>("");
  const [toTime, setToTime] = useState<string>("");

  // Detail Modal State
  const [selectedMsgId, setSelectedMsgId] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<any | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [approvingMsg, setApprovingMsg] = useState(false);
  const [rejectingMsg, setRejectingMsg] = useState(false);

  // Reject Dialog State
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectTargetId, setRejectTargetId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string>(
    "Dữ liệu không chính xác hoặc lệnh điều xe bị hủy."
  );

  const handleApproveMessage = async (msgId: string) => {
    try {
      setApprovingMsg(true);
      const res = await approveMessageByDHVT(msgId as any);
      toast.success(res.message || "ĐHVT đã duyệt tin nhắn và gửi tới Zalo thành công.");
      await handleOpenDetail(msgId);
      loadMessages(currentPage, pageSize);
    } catch (err: any) {
      toast.error(err.message || "Lỗi khi duyệt tin nhắn");
    } finally {
      setApprovingMsg(false);
    }
  };

  const handleOpenRejectModal = (msgId: string) => {
    setRejectTargetId(msgId);
    setRejectReason("Dữ liệu không chính xác hoặc lệnh điều xe bị hủy.");
    setRejectModalOpen(true);
  };

  const handleConfirmReject = async () => {
    if (!rejectTargetId) return;
    if (!rejectReason.trim()) {
      toast.error("Vui lòng nhập lý do từ chối tin nhắn.");
      return;
    }
    try {
      setRejectingMsg(true);
      const res = await rejectMessageByDHVT(rejectTargetId as any, rejectReason.trim());
      toast.success(res.message || "ĐHVT đã từ chối tin nhắn thành công.");
      setRejectModalOpen(false);
      if (selectedMsgId) {
        await handleOpenDetail(selectedMsgId);
      }
      loadMessages(currentPage, pageSize);
    } catch (err: any) {
      toast.error(err.message || "Lỗi khi từ chối tin nhắn");
    } finally {
      setRejectingMsg(false);
    }
  };

  const handleApproveOutbound = async (outboundId: number) => {
    try {
      setApprovingMsg(true);
      const res = await approveOutboundMessage(outboundId, "Điều độ viên ĐHVT");
      toast.success(res.message || "Đã phê duyệt và gửi tin nhắn ra Nhóm Zalo.");
      if (selectedMsgId) {
        await handleOpenDetail(selectedMsgId);
      }
      loadMessages(currentPage, pageSize);
    } catch (err: any) {
      toast.error(err.message || "Lỗi khi duyệt tin gửi đi");
    } finally {
      setApprovingMsg(false);
    }
  };

  const loadMessages = async (page = currentPage, size = pageSize) => {
    try {
      setLoading(true);
      setError(null);
      const res = await getMessages({
        search: search.trim() || undefined,
        status: status || undefined,
        group_id: groupId.trim() || undefined,
        user_id: userId.trim() || undefined,
        from_time: fromTime || undefined,
        to_time: toTime || undefined,
        limit: size,
        offset: (page - 1) * size,
      });
      setMessages(res.messages);
      setTotal(res.total);
    } catch (err: any) {
      setError(err.message || "Lỗi khi lấy danh sách tin nhắn.");
      toast.error(err.message || "Lỗi khi lấy danh sách tin nhắn.");
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

  const handleResetFilter = () => {
    setSearch("");
    setStatus("");
    setGroupId("");
    setUserId("");
    setFromTime("");
    setToTime("");
    setCurrentPage(1);
  };

  const handleOpenDetail = async (id: string | number, fallbackZaloId?: string) => {
    const safeId = String(id);
    try {
      setSelectedMsgId(safeId);
      setLoadingDetail(true);
      let res;
      try {
        res = await getMessageDetail(safeId);
      } catch (firstErr: any) {
        if (fallbackZaloId) {
          res = await getMessageDetail(fallbackZaloId);
        } else {
          throw firstErr;
        }
      }
      setDetailData(res);
    } catch (err: any) {
      toast.error("Lỗi khi tải chi tiết tin nhắn: " + err.message);
    } finally {
      setLoadingDetail(false);
    }
  };

  const getStatusLabel = (s: string) => {
    switch (s?.toLowerCase()) {
      case "processed":
        return "Thành công";
      case "needs_review":
        return "Chờ duyệt";
      case "cancelled":
        return "Bị hủy";
      case "failed":
        return "Thất bại";
      case "ignored_chat":
        return "Tin rác";
      case "ignored_non_text":
        return "Bỏ qua (ảnh trống)";
      case "received":
        return "Mới nhận";
      case "queued":
        return "Đang chờ hàng đợi";
      case "processing":
        return "Đang xử lý";
      default:
        return s || "Chưa rõ";
    }
  };

  const getStatusBadgeClass = (s: string) => {
    switch (s?.toLowerCase()) {
      case "processed":
        return "bg-emerald-50 text-emerald-700 border-emerald-200";
      case "needs_review":
        return "bg-purple-50 text-purple-700 border-purple-200";
      case "cancelled":
      case "failed":
        return "bg-rose-50 text-rose-700 border-rose-200";
      case "ignored_chat":
      case "ignored_non_text":
        return "bg-slate-100 text-slate-600 border-slate-200";
      default:
        return "bg-slate-50 text-slate-700 border-slate-200";
    }
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            Quản lý tin nhắn Zalo
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Tin nhắn tiếp nhận qua Zalo OA & Webhook, dữ liệu bóc tách xe, container
          </p>
        </div>

        <button
          type="button"
          onClick={() => loadMessages(currentPage, pageSize)}
          disabled={loading}
          className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-900 rounded-sm text-xs font-medium border border-slate-200 transition"
        >
          {loading ? "Đang tải..." : "Làm mới"}
        </button>
      </div>

      {/* Error Message */}
      {error && (
        <div className="p-3 bg-white border border-rose-200 text-rose-700 rounded-sm text-xs">
          {error}
        </div>
      )}

      {/* Quick Status Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2 pb-1 border-b border-slate-200">
        {[
          { id: "", label: "Tất cả" },
          { id: "processed", label: "Thành công" },
          { id: "needs_review", label: "Chờ duyệt" },
          { id: "cancelled", label: "Bị hủy" },
          { id: "failed", label: "Thất bại" },
          { id: "ignored_chat", label: "Tin rác / Xã giao" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setStatus(tab.id);
              setCurrentPage(1);
            }}
            className={`px-3 py-1.5 rounded-sm text-xs font-medium transition ${
              status === tab.id
                ? "bg-purple-700 text-white"
                : "bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900 border border-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search & Filters Toolbar */}
      <form
        onSubmit={handleSearch}
        className="bg-white border border-slate-200 p-3.5 rounded-sm grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-2.5 text-xs"
      >
        <div className="lg:col-span-2">
          <label className="block text-slate-600 mb-1 font-medium">Tìm kiếm:</label>
          <input
            type="text"
            placeholder="Nội dung, biển số, container, người gửi..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-slate-900 focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Trạng thái:</label>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setCurrentPage(1);
            }}
            className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-purple-600"
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
          <label className="block text-slate-600 mb-1 font-medium">Group ID:</label>
          <input
            type="text"
            placeholder="Lọc Group ID"
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-slate-900 focus:outline-none focus:border-purple-600 font-mono text-[11px]"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Từ ngày:</label>
          <input
            type="date"
            value={fromTime}
            onChange={(e) => setFromTime(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-2 py-1.5 text-slate-900 focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Đến ngày:</label>
          <div className="flex gap-1.5">
            <input
              type="date"
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
              className="w-full bg-white border border-slate-300 rounded-sm px-2 py-1.5 text-slate-900 focus:outline-none focus:border-purple-600"
            />
            <button
              type="submit"
              className="bg-purple-700 hover:bg-purple-800 text-white px-3 py-1.5 rounded-sm font-medium transition"
            >
              Lọc
            </button>
            <button
              type="button"
              onClick={handleResetFilter}
              className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 px-2.5 py-1.5 rounded-sm font-medium transition"
              title="Đặt lại bộ lọc"
            >
              Xóa
            </button>
          </div>
        </div>
      </form>

      {/* Messages Table */}
      <div className="bg-white border border-slate-200 rounded-sm overflow-hidden">
        <div className="p-3 border-b border-slate-200 text-xs text-slate-500 flex items-center justify-between">
          <span>
            Hiển thị <strong className="text-slate-900">{messages.length}</strong> / {total} tin nhắn
          </span>
        </div>

        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-50 sticky top-0 text-slate-900 font-semibold border-b border-slate-200 whitespace-nowrap">
              <tr>
                <th className="py-2.5 px-3">Người gửi</th>
                <th className="py-2.5 px-3">Nhóm Zalo</th>
                <th className="py-2.5 px-3">Thời gian</th>
                <th className="py-2.5 px-3 min-w-[240px]">Nội dung</th>
                <th className="py-2.5 px-3">Trạng thái</th>
                <th className="py-2.5 px-3">Xe bóc tách</th>
                <th className="py-2.5 px-3">Container</th>
                <th className="py-2.5 px-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 font-normal">
              {messages.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-10 text-center text-slate-500">
                    Không có tin nhắn nào khớp với bộ lọc.
                  </td>
                </tr>
              ) : (
                messages.map((m) => {
                  const plates = (m.trucks || []).map((t) => t?.truck_plate).filter(Boolean);
                  const conts = (m.containers || []).map((c) => c?.container_no).filter(Boolean);
                  return (
                    <tr
                      key={m.id}
                      onClick={() => handleOpenDetail(m.id, m.zalo_message_id)}
                      className="hover:bg-slate-50 transition cursor-pointer"
                    >
                      <td className="py-2.5 px-3 whitespace-nowrap font-medium text-slate-900">
                        {m.sender_name || m.sender_id || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-500 text-[11px] max-w-[160px] truncate" title={m.group_name || m.group_id}>
                        {m.group_name || m.group_id || "Direct"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap text-slate-500">
                        {(m.sent_at || m.received_at)?.slice(0, 16).replace("T", " ") || "—"}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-slate-900 max-w-sm truncate" title={m.raw_text || ""}>
                        {m.raw_text || "—"}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <span className={`px-2 py-0.5 rounded-sm text-[11px] font-medium border ${getStatusBadgeClass(m.processing_status)}`}>
                          {getStatusLabel(m.processing_status)}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        {plates.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {plates.map((p, idx) => (
                              <span key={idx} className="bg-white text-slate-900 px-1.5 py-0.5 rounded-sm text-[11px] font-mono border border-slate-200">
                                {p}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        {conts.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {conts.map((c, idx) => (
                              <span key={idx} className="bg-purple-50 text-purple-700 px-1.5 py-0.5 rounded-sm text-[11px] font-mono font-medium border border-purple-200">
                                {c}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td
                        className="py-2.5 px-3 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          type="button"
                          onClick={() => handleOpenDetail(m.id, m.zalo_message_id)}
                          className="px-2 py-1 text-[11px] bg-white border border-slate-200 hover:border-purple-300 text-purple-700 rounded-sm font-medium"
                        >
                          Chi tiết
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
          <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-slate-500">
              Hiển thị <span className="font-semibold text-slate-900">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-slate-900">{Math.min(currentPage * pageSize, total)}</span> trong{" "}
              <span className="font-semibold text-slate-900">{total}</span> tin nhắn
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
                  className="bg-white border border-slate-300 rounded-sm px-2 py-1 text-slate-900 focus:outline-none focus:border-purple-600"
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
                className="px-2.5 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed border transition"
              >
                Trước
              </button>

              <span className="px-2 font-mono text-slate-700">
                Trang <span className="text-slate-900 font-bold">{currentPage}</span> / {Math.ceil(total / pageSize) || 1}
              </span>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(Math.ceil(total / pageSize), p + 1))}
                disabled={currentPage >= Math.ceil(total / pageSize) || loading}
                className="px-2.5 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed border transition"
              >
                Sau
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {selectedMsgId && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => {
            setSelectedMsgId(null);
            setDetailData(null);
          }}
        >
          <div
            className="bg-white border border-slate-200 rounded-sm max-w-3xl w-full p-6 text-xs text-slate-900 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-slate-900">
                  Chi tiết tin nhắn #{selectedMsgId}
                </h3>
                {detailData?.message?.processing_status && (
                  <span className={`text-[11px] px-2 py-0.5 rounded-sm border font-medium ${getStatusBadgeClass(detailData.message.processing_status)}`}>
                    {getStatusLabel(detailData.message.processing_status)}
                  </span>
                )}
              </div>

              <div className="flex items-center space-x-2">
                {(detailData?.message?.processing_status === "needs_review" ||
                  detailData?.outbound_messages?.some((o: any) => o.status === "cho_duyet")) && (
                  <>
                    <button
                      type="button"
                      disabled={rejectingMsg || approvingMsg}
                      onClick={() => selectedMsgId && handleOpenRejectModal(selectedMsgId)}
                      className="px-3 py-1.5 bg-white border border-rose-300 hover:bg-rose-50 text-rose-700 rounded-sm text-xs font-medium transition disabled:opacity-50"
                    >
                      {rejectingMsg ? "Đang xử lý..." : "Từ chối"}
                    </button>
                    <button
                      type="button"
                      disabled={approvingMsg || rejectingMsg}
                      onClick={() => selectedMsgId && handleApproveMessage(selectedMsgId)}
                      className="px-3 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-xs font-medium transition disabled:opacity-50"
                    >
                      {approvingMsg ? "Đang gửi Zalo..." : "Duyệt & Gửi Zalo"}
                    </button>
                  </>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setSelectedMsgId(null);
                    setDetailData(null);
                  }}
                  className="text-slate-500 hover:text-slate-900"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {loadingDetail ? (
              <div className="py-12 text-center text-slate-500">Đang tải chi tiết tin nhắn...</div>
            ) : (
              <div className="space-y-4 mt-4">
                {/* Thông tin meta */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3 bg-slate-50 border border-slate-200 rounded-sm text-xs">
                  <div>
                    <span className="text-slate-500 block">Người gửi:</span>
                    <strong className="text-slate-900 font-medium">
                      {detailData?.message?.sender_name || detailData?.message?.sender_id || "—"}
                    </strong>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Nhóm Zalo:</span>
                    <strong className="text-slate-900 font-medium truncate block" title={detailData?.message?.group_name || detailData?.message?.group_id}>
                      {detailData?.message?.group_name || detailData?.message?.group_id || "Direct"}
                    </strong>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Thời gian:</span>
                    <strong className="text-slate-900 font-medium">
                      {(detailData?.message?.sent_at || detailData?.message?.received_at)?.slice(0, 16).replace("T", " ") || "—"}
                    </strong>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Zalo Msg ID:</span>
                    <span className="font-mono text-slate-900 text-[11px] truncate block" title={detailData?.message?.zalo_message_id}>
                      {detailData?.message?.zalo_message_id || "—"}
                    </span>
                  </div>
                </div>

                {/* Nội dung tin nhắn gốc */}
                <div>
                  <div className="text-xs font-semibold text-slate-900 mb-1">
                    Nội dung tin nhắn gốc:
                  </div>
                  <div className="p-3 bg-white border border-slate-200 rounded-sm font-mono text-xs text-slate-900 whitespace-pre-wrap leading-relaxed">
                    {detailData?.message?.raw_text || "—"}
                  </div>
                </div>

                {/* Thông tin Outbound gửi khách hàng */}
                {detailData?.outbound_messages && detailData.outbound_messages.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold text-slate-900">
                        Thông báo gửi khách hàng ({detailData.outbound_messages.length})
                      </div>
                      <Link
                        href="/results"
                        className="text-[11px] text-purple-700 hover:underline font-medium"
                      >
                        Mở trang Kết quả
                      </Link>
                    </div>

                    <div className="space-y-2">
                      {detailData.outbound_messages.map((out: any) => (
                        <div
                          key={out.id}
                          className="bg-slate-50 border border-slate-200 rounded-sm p-3 space-y-2"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                            <div className="flex items-center gap-2">
                              <span
                                className={`px-2 py-0.5 rounded-sm font-medium text-[11px] border ${
                                  out.status === "da_gui"
                                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                    : out.status === "cho_duyet"
                                    ? "bg-purple-50 text-purple-700 border-purple-200"
                                    : out.status === "bo_qua_trung_lap"
                                    ? "bg-slate-100 text-slate-600 border-slate-200"
                                    : "bg-rose-50 text-rose-700 border-rose-200"
                                }`}
                              >
                                {out.status === "da_gui"
                                  ? "Đã gửi"
                                  : out.status === "cho_duyet"
                                  ? "Chờ duyệt"
                                  : out.status === "bo_qua_trung_lap"
                                  ? "Bỏ qua gửi trùng"
                                  : "Gửi thất bại"}
                              </span>
                              {out.message_kind === "update" && (
                                <span className="px-2 py-0.5 rounded-sm font-medium text-[11px] bg-purple-50 text-purple-700 border border-purple-200">
                                  Cập nhật xe
                                </span>
                              )}
                              <span className="text-slate-500">
                                Nhóm đích: <strong className="text-slate-900 font-mono">{out.target_zalo_group_id || out.target_group_name || "—"}</strong>
                              </span>
                            </div>

                            {out.status === "cho_duyet" && (
                              <button
                                type="button"
                                disabled={approvingMsg}
                                onClick={() => handleApproveOutbound(out.id)}
                                className="px-2.5 py-1 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-[11px] font-medium transition disabled:opacity-50"
                              >
                                {approvingMsg ? "Đang gửi..." : "Duyệt & Gửi ngay"}
                              </button>
                            )}
                          </div>

                          <div className="bg-white border border-slate-200 rounded-sm p-3 font-mono text-xs text-slate-900 whitespace-pre-wrap">
                            {out.content}
                          </div>

                          {out.last_error && (
                            <div className="text-[11px] text-rose-700 bg-rose-50 p-2 rounded-sm border border-rose-200">
                              Lỗi gửi: {out.last_error}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Cảnh báo ca duyệt / Bot replies */}
                {(detailData?.review_cases?.length > 0 || detailData?.bot_replies?.length > 0) && (
                  <div className="bg-slate-50 border border-slate-200 rounded-sm p-3.5 space-y-2.5">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold text-slate-900">
                        Cảnh báo nghiệp vụ & Ca duyệt
                      </div>
                      <Link
                        href="/reviews"
                        className="text-xs text-purple-700 hover:underline font-medium"
                      >
                        Mở Hàng đợi duyệt
                      </Link>
                    </div>

                    {detailData?.review_cases?.length > 0 && (
                      <div className="space-y-1.5">
                        {detailData.review_cases.map((rc: any) => (
                          <div
                            key={rc.id}
                            className="p-2.5 bg-white border border-purple-200 rounded-sm text-xs space-y-1"
                          >
                            <div className="flex items-center justify-between font-mono">
                              <span className="font-semibold text-purple-700">Ca #{rc.id}: {rc.case_type}</span>
                              <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-slate-100 text-slate-700">
                                {rc.status}
                              </span>
                            </div>
                            <div className="text-slate-700">{rc.reason}</div>
                          </div>
                        ))}
                      </div>
                    )}

                    {detailData?.bot_replies?.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-xs text-slate-500 font-medium">Tin Bot nhắc nhà xe sửa lỗi:</div>
                        {detailData.bot_replies.map((br: any) => (
                          <div
                            key={br.id}
                            className="p-2.5 bg-white border border-slate-200 rounded-sm font-mono text-xs text-slate-900 whitespace-pre-wrap"
                          >
                            {br.reply_text}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Chi tiết Phương tiện & Container đã bóc tách */}
                <div className="space-y-2.5">
                  <div className="text-xs font-semibold text-slate-900">
                    Phương tiện & Container đã bóc tách:
                  </div>

                  {/* Xe & Lái xe */}
                  {detailData?.message?.trucks && detailData.message.trucks.length > 0 && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {detailData.message.trucks.map((t: any) => (
                        <div
                          key={t.id}
                          className="bg-slate-50 p-2.5 rounded-sm border border-slate-200 space-y-1 text-xs"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono font-bold text-slate-900">
                              Xe: {t.truck_plate || "Chưa rõ"}
                            </span>
                            {t.trailer_plate && (
                              <span className="text-[11px] text-slate-500 font-mono">
                                Mooc: {t.trailer_plate}
                              </span>
                            )}
                          </div>
                          <div className="text-slate-700">
                            Lái xe: <strong className="text-slate-900">{t.driver_name || "—"}</strong>
                          </div>
                          <div className="text-slate-700">
                            SĐT: <strong className="font-mono text-purple-700">{t.driver_phone || "—"}</strong>
                          </div>
                          {t.eta_text && (
                            <div className="text-slate-500 text-[11px]">
                              Giờ hẹn: {t.eta_text}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Container jobs */}
                  <div className="space-y-2">
                    {(detailData?.message?.containers || []).map((c: any) => (
                      <div
                        key={c.id}
                        className="bg-slate-50 p-3 rounded-sm border border-slate-200 space-y-2"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold text-slate-900 text-xs">
                              Cont: {c.container_no || "Chưa có"}
                            </span>
                            {c.container_size && (
                              <span className="text-xs font-mono text-slate-500">
                                ({c.container_size}&#39;)
                              </span>
                            )}
                            {c.seal_no && (
                              <span className="text-xs font-mono text-slate-700">
                                Chì: <strong>{c.seal_no}</strong>
                              </span>
                            )}
                            <span className="text-[11px] px-2 py-0.5 rounded-sm font-medium bg-white border border-slate-200 text-slate-900">
                              {c.order_type === "dong" ? "Lệnh Đóng" : c.order_type === "tra" ? "Lệnh Trả" : "Chưa rõ"}
                            </span>
                          </div>

                          <span className={`text-[11px] px-2 py-0.5 rounded-sm font-medium border ${
                            c.validation_status === "valid" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-purple-50 text-purple-700 border-purple-200"
                          }`}>
                            {c.validation_status === "valid" ? "Hợp lệ ISO 6346" : "Cần kiểm tra"}
                          </span>
                        </div>

                        <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 pt-1 border-t border-slate-200">
                          <div>Khách hàng: <strong className="text-slate-900">{c.customer_hint || "—"}</strong></div>
                          <div>Điểm giao/nhận: <strong className="text-slate-900">{c.warehouse_hint || "—"}</strong></div>
                          <div>Nguồn ghép: <strong className="text-slate-900 font-mono">{c.match_source || "unmatched"}</strong></div>
                          <div>Định dạng: <strong className="text-slate-900 font-mono">{c.source_format || "tu_do"}</strong></div>
                        </div>

                        {(c.warnings || []).length > 0 && (
                          <div className="flex flex-wrap gap-1 text-[11px] text-purple-700 pt-1">
                            {(c.warnings || []).map((w: string, i: number) => (
                              <span key={i} className="bg-purple-50 px-2 py-0.5 rounded-sm border border-purple-200">
                                {w}
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

      {/* Reject Modal thay thế hoàn toàn prompt mặc định của browser */}
      {rejectModalOpen && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
          onClick={() => setRejectModalOpen(false)}
        >
          <div
            className="bg-white border border-slate-200 rounded-sm max-w-md w-full p-5 text-xs text-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-2.5 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900">
                Từ chối tin nhắn #{rejectTargetId}
              </h3>
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="mt-3 space-y-2">
              <label className="block text-xs font-medium text-slate-700">
                Lý do ĐHVT từ chối:
              </label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
                className="w-full border border-slate-200 rounded-sm p-2 text-xs focus:outline-none focus:border-purple-600 font-sans"
                placeholder="Nhập lý do từ chối..."
              />
            </div>

            <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                disabled={rejectingMsg}
                className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-sm text-xs font-medium transition"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                onClick={handleConfirmReject}
                disabled={rejectingMsg}
                className="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded-sm text-xs font-medium transition disabled:opacity-50"
              >
                {rejectingMsg ? "Đang xử lý..." : "Xác nhận từ chối"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
