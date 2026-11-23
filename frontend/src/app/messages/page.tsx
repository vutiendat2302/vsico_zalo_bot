"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import {
  ZaloGroupItem,
  ZaloMessageItem,
  approveMessageByDHVT,
  approveOutboundMessage,
  getGroups,
  getMessageDetail,
  getMessages,
  rejectMessageByDHVT,
} from "@/lib/api";
import {
  formatDateTime24h,
  getMatchStatusLabel,
  getMessageStatusMeta,
  getOutboundStatusMeta,
  getReviewCaseTypeLabel,
  getReviewStatusLabel,
} from "@/lib/utils";
import { toast } from "@/components/shared/Toast";

/**
 * Chuẩn hóa tên nhóm Zalo hiển thị thân thiện, tuyệt đối không lộ mã ID kỹ thuật.
 */
function formatGroupDisplay(groupName?: string | null, groupId?: string | null): string {
  if (groupName && !groupName.includes("<")) return groupName;
  if (groupId?.startsWith("direct_")) return "Tin nhắn trực tiếp";
  return "Nhóm Zalo";
}

/**
 * Trang quản lý và theo dõi chi tiết tin nhắn Zalo cùng kết quả bóc tách.
 */
export default function MessagesPage() {
  const [messages, setMessages] = useState<ZaloMessageItem[]>([]);
  const [groups, setGroups] = useState<ZaloGroupItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Phân trang
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);

  // Bộ lọc tìm kiếm
  const [search, setSearch] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [groupId, setGroupId] = useState<string>("");
  const [fromTime, setFromTime] = useState<string>("");
  const [toTime, setToTime] = useState<string>("");

  // Hộp thoại chi tiết tin nhắn
  const [selectedMsgId, setSelectedMsgId] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<any | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [approvingMsg, setApprovingMsg] = useState(false);
  const [rejectingMsg, setRejectingMsg] = useState(false);

  // Hộp thoại nhập lý do từ chối
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectTargetId, setRejectTargetId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string>(
    "Dữ liệu không chính xác hoặc lệnh điều xe bị hủy."
  );

  const handleApproveMessage = async (msgId: string) => {
    try {
      setApprovingMsg(true);
      const res = await approveMessageByDHVT(msgId as any);
      toast.success(res.message || "Đã duyệt tin nhắn và gửi tới Zalo thành công.");
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
      toast.success(res.message || "Đã từ chối tin nhắn thành công.");
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
      toast.success(res.message || "Đã phê duyệt và gửi tin nhắn ra nhóm Zalo.");
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
    getGroups({ limit: 200 })
      .then((res) => {
        const cleanGroups = (res.groups || []).filter(
          (g) => g.name && !g.name.includes("<") && !g.zalo_group_id.includes("<")
        );
        setGroups(cleanGroups);
      })
      .catch(() => {
        // Không chặn tải danh sách tin nhắn nếu danh sách nhóm lỗi tạm thời
      });

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
  }, [currentPage, pageSize, status, groupId]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    loadMessages(1, pageSize);
  };

  const handleResetFilter = () => {
    setSearch("");
    setStatus("");
    setGroupId("");
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

  const detailMsg = detailData?.message;
  const detailStatusMeta = getMessageStatusMeta(detailMsg?.processing_status);

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      {/* Header */}
      <div className="shrink-0 flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <h1 className="text-2xl font-bold text-slate-900">
          Quản lý tin nhắn Zalo
        </h1>

        <button
          type="button"
          onClick={() => loadMessages(currentPage, pageSize)}
          disabled={loading}
          className="px-3.5 py-2 bg-white hover:bg-slate-50 text-slate-900 rounded-sm text-sm font-medium border border-slate-200 transition"
        >
          {loading ? "Đang tải..." : "Làm mới"}
        </button>
      </div>

      {/* Lỗi tải dữ liệu */}
      {error && (
        <div className="p-3.5 bg-white border border-rose-200 text-rose-700 rounded-sm text-sm">
          {error}
        </div>
      )}

      {/* Tab lọc nhanh theo trạng thái */}
      <div className="shrink-0 flex flex-wrap items-center gap-2 pb-1 border-b border-slate-200">
        {[
          { id: "", label: "Tất cả" },
          { id: "processed", label: "Thành công" },
          { id: "needs_review", label: "Chờ duyệt" },
          { id: "cancelled", label: "Đã hủy" },
          { id: "failed", label: "Thất bại" },
          { id: "ignored_chat", label: "Tin xã giao" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setStatus(tab.id);
              setCurrentPage(1);
            }}
            className={`px-3.5 py-2 rounded-sm text-sm font-medium transition ${
              status === tab.id
                ? "bg-purple-700 text-white"
                : "bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900 border border-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Thanh bộ lọc */}
      <form
        onSubmit={handleSearch}
        className="shrink-0 bg-white border border-slate-200 p-4 rounded-sm grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 text-sm items-end"
      >
        <div className="lg:col-span-2">
          <label className="block text-slate-600 mb-1 font-medium">Tìm kiếm</label>
          <input
            type="text"
            placeholder="Nhập nội dung, biển số, container, người gửi..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-white border border-slate-300 rounded-sm px-3 py-2 text-sm text-slate-900 placeholder:text-xs placeholder:text-slate-400 placeholder:normal-case focus:outline-none focus:border-purple-600"
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Nhóm Zalo</label>
          <select
            value={groupId}
            onChange={(e) => {
              setGroupId(e.target.value);
              setCurrentPage(1);
            }}
            className={`w-full bg-white border border-slate-300 rounded-sm px-3 py-2 focus:outline-none focus:border-purple-600 ${
              groupId ? "text-sm text-slate-900" : "text-xs text-slate-400"
            }`}
          >
            <option value="" className="text-xs text-slate-400">
              Chọn nhóm Zalo
            </option>
            {groups.map((g) => (
              <option key={g.id} value={g.zalo_group_id} className="text-sm text-slate-900">
                {g.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Từ ngày</label>
          <input
            type="date"
            value={fromTime}
            onChange={(e) => setFromTime(e.target.value)}
            className={`w-full bg-white border border-slate-300 rounded-sm px-2.5 py-2 focus:outline-none focus:border-purple-600 ${
              fromTime ? "text-sm text-slate-900" : "text-xs text-slate-400"
            }`}
          />
        </div>

        <div>
          <label className="block text-slate-600 mb-1 font-medium">Đến ngày</label>
          <div className="flex gap-1.5">
            <input
              type="date"
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
              className={`w-full bg-white border border-slate-300 rounded-sm px-2.5 py-2 focus:outline-none focus:border-purple-600 ${
                toTime ? "text-sm text-slate-900" : "text-xs text-slate-400"
              }`}
            />
            <button
              type="submit"
              className="bg-purple-700 hover:bg-purple-800 text-white px-3.5 py-2 rounded-sm font-medium transition whitespace-nowrap"
            >
              Lọc
            </button>
            <button
              type="button"
              onClick={handleResetFilter}
              className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 px-3 py-2 rounded-sm font-medium transition whitespace-nowrap"
              title="Đặt lại bộ lọc"
            >
              Xóa
            </button>
          </div>
        </div>
      </form>

      {/* Bảng tin nhắn */}
      <div className="flex-1 min-h-0 bg-white border border-slate-200 rounded-sm overflow-hidden flex flex-col">
        <div className="flex-1 min-h-[220px] overflow-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead className="bg-slate-50 sticky top-0 z-10 text-slate-900 font-semibold border-b border-slate-200 whitespace-nowrap">
              <tr>
                <th className="py-3 px-3">Người gửi</th>
                <th className="py-3 px-3">Nhóm Zalo</th>
                <th className="py-3 px-3">Thời gian</th>
                <th className="py-3 px-3">Nội dung</th>
                <th className="py-3 px-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 font-normal">
              {messages.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-slate-500 text-base">
                    Không có tin nhắn nào khớp với bộ lọc.
                  </td>
                </tr>
              ) : (
                messages.map((m) => {
                  const compactText = (m.raw_text || "—").replace(/\s+/g, " ").trim();
                  const groupLabel = formatGroupDisplay(m.group_name, m.group_id);

                  return (
                    <tr
                      key={m.id}
                      onClick={() => handleOpenDetail(m.id, m.zalo_message_id)}
                      className="hover:bg-slate-50 transition cursor-pointer"
                    >
                      <td className="py-3 px-3 whitespace-nowrap font-medium text-slate-900">
                        {m.sender_name || "Người dùng Zalo"}
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap text-slate-600 max-w-[180px] truncate" title={groupLabel}>
                        {groupLabel}
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap text-slate-500 tabular-nums">
                        {formatDateTime24h(m.sent_at || m.received_at)}
                      </td>
                      <td className="py-3 px-3 text-slate-900">
                        <div className="max-w-[420px] truncate" title={m.raw_text || ""}>
                          {compactText}
                        </div>
                      </td>
                      <td
                        className="py-3 px-3 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          type="button"
                          onClick={() => handleOpenDetail(m.id, m.zalo_message_id)}
                          className="px-3 py-1.5 text-sm bg-white border border-slate-200 hover:border-purple-400 text-purple-700 rounded-sm font-medium transition"
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

        {/* Footer phân trang */}
        {total > 0 && (
          <div className="shrink-0 px-4 py-3 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm">
            <div className="text-slate-600 tabular-nums">
              Hiển thị <span className="font-semibold text-slate-900">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-slate-900">{Math.min(currentPage * pageSize, total)}</span> trong{" "}
              <span className="font-semibold text-slate-900">{total}</span> tin nhắn
            </div>

            <div className="flex items-center space-x-2">
              <div className="flex items-center space-x-1.5 mr-2">
                <span className="text-slate-500">Dòng mỗi trang:</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    const newSize = parseInt(e.target.value);
                    setPageSize(newSize);
                    setCurrentPage(1);
                  }}
                  className="bg-white border border-slate-300 rounded-sm px-2.5 py-1 text-slate-900 focus:outline-none focus:border-purple-600"
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
                className="px-3 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                Trước
              </button>

              <span className="px-2 text-slate-700 tabular-nums">
                Trang <span className="text-slate-900 font-bold">{currentPage}</span> / {Math.ceil(total / pageSize) || 1}
              </span>

              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(Math.ceil(total / pageSize), p + 1))}
                disabled={currentPage >= Math.ceil(total / pageSize) || loading}
                className="px-3 py-1 rounded-sm bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                Sau
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Hộp thoại Chi tiết tin nhắn - thiết kế đồng nhất 1 font chữ, tối giản màu sắc, không ID/biến hệ thống */}
      {selectedMsgId && (
        <div
          className="fixed inset-0 bg-slate-900/45 flex items-center justify-center z-50 p-4"
          onClick={() => {
            setSelectedMsgId(null);
            setDetailData(null);
          }}
        >
          <div
            className="bg-white border border-slate-200 rounded-sm max-w-4xl w-full font-sans text-base text-slate-900 max-h-[90vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header Modal */}
            <div className="px-6 py-4 border-b border-slate-200 bg-white flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <h3 className="text-lg font-bold text-slate-900">
                  Chi tiết tin nhắn
                  {detailMsg?.sender_name ? ` — ${detailMsg.sender_name}` : ""}
                </h3>
                {detailMsg?.processing_status && (
                  <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${detailStatusMeta.textClass}`}>
                    <span className={`w-2 h-2 rounded-full ${detailStatusMeta.dotClass}`} />
                    <span>{detailStatusMeta.label}</span>
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                {(detailMsg?.processing_status === "needs_review" ||
                  detailData?.outbound_messages?.some((o: any) => o.status === "cho_duyet")) && (
                  <>
                    <button
                      type="button"
                      disabled={rejectingMsg || approvingMsg}
                      onClick={() => selectedMsgId && handleOpenRejectModal(selectedMsgId)}
                      className="px-3.5 py-2 bg-white border border-slate-300 hover:border-rose-400 hover:text-rose-700 text-slate-700 rounded-sm text-sm font-medium transition disabled:opacity-50"
                    >
                      {rejectingMsg ? "Đang xử lý..." : "Từ chối"}
                    </button>
                    <button
                      type="button"
                      disabled={approvingMsg || rejectingMsg}
                      onClick={() => selectedMsgId && handleApproveMessage(selectedMsgId)}
                      className="px-3.5 py-2 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-sm font-medium transition disabled:opacity-50"
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
                  className="p-1.5 text-slate-500 hover:text-slate-900 rounded-sm"
                  aria-label="Đóng"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Body Modal */}
            <div className="p-6 space-y-5 overflow-y-auto flex-1 bg-white">
              {loadingDetail ? (
                <div className="py-12 text-center text-slate-500 text-base">
                  Đang tải chi tiết tin nhắn...
                </div>
              ) : (
                <>
                  {/* 1. Thông tin ngữ cảnh người gửi & nhóm */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 p-4 bg-slate-50 border border-slate-200 rounded-sm">
                    <div>
                      <div className="text-sm text-slate-500">Người gửi</div>
                      <div className="text-base font-semibold text-slate-900 mt-0.5">
                        {detailMsg?.sender_name || "Người dùng Zalo"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-slate-500">Nhóm Zalo</div>
                      <div className="text-base font-semibold text-slate-900 mt-0.5">
                        {formatGroupDisplay(detailMsg?.group_name, detailMsg?.group_id)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-slate-500">Thời gian gửi</div>
                      <div className="text-base font-semibold text-slate-900 mt-0.5 tabular-nums">
                        {formatDateTime24h(detailMsg?.sent_at || detailMsg?.received_at)}
                      </div>
                    </div>
                  </div>

                  {/* 2. Nội dung tin nhắn gốc */}
                  <div>
                    <div className="text-sm font-semibold text-slate-700 mb-2">
                      Nội dung tin nhắn
                    </div>
                    <div className="p-4 bg-slate-50 border border-slate-200 rounded-sm text-base text-slate-900 whitespace-pre-wrap leading-relaxed">
                      {detailMsg?.raw_text || "—"}
                    </div>
                  </div>

                  {/* 3. Thông tin đã nhận diện (Phương tiện & Container) */}
                  {(detailMsg?.trucks?.length > 0 || detailMsg?.containers?.length > 0) && (
                    <div className="space-y-4">
                      <div className="text-sm font-semibold text-slate-700">
                        Thông tin điều xe đã nhận diện
                      </div>

                      {/* Xe & Lái xe */}
                      {detailMsg?.trucks?.length > 0 && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          {detailMsg.trucks.map((t: any) => (
                            <div
                              key={t.id}
                              className="bg-slate-50 p-4 rounded-sm border border-slate-200 grid grid-cols-2 gap-3"
                            >
                              <div>
                                <div className="text-sm text-slate-500">Biển số xe</div>
                                <div className="text-base font-semibold text-slate-900 mt-0.5 tabular-nums">
                                  {t.truck_plate || "Chưa rõ"}
                                </div>
                              </div>
                              <div>
                                <div className="text-sm text-slate-500">Rơ-moóc</div>
                                <div className="text-base font-medium text-slate-900 mt-0.5 tabular-nums">
                                  {t.trailer_plate || "—"}
                                </div>
                              </div>
                              <div>
                                <div className="text-sm text-slate-500">Tài xế</div>
                                <div className="text-base font-medium text-slate-900 mt-0.5">
                                  {t.driver_name || "—"}
                                </div>
                              </div>
                              <div>
                                <div className="text-sm text-slate-500">Số điện thoại</div>
                                <div className="text-base font-medium text-purple-700 mt-0.5 tabular-nums">
                                  {t.driver_phone || "—"}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Container & Kế hoạch */}
                      {detailMsg?.containers?.length > 0 && (
                        <div className="space-y-3">
                          {detailMsg.containers.map((c: any) => {
                            const orderLabel =
                              c.order_type === "dong"
                                ? "Đóng hàng"
                                : c.order_type === "tra"
                                ? "Trả hàng"
                                : "Chưa xác định";
                            const validOk = c.validation_status === "valid";

                            return (
                              <div
                                key={c.id}
                                className="bg-slate-50 p-4 rounded-sm border border-slate-200 space-y-3"
                              >
                                <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-200">
                                  <div className="flex flex-wrap items-center gap-4">
                                    <span className="text-base font-bold text-slate-900 tabular-nums">
                                      Container: {c.container_no || "Chưa có"}
                                    </span>
                                    {c.container_size && (
                                      <span className="text-sm text-slate-600 tabular-nums">
                                        Cỡ {c.container_size} feet
                                      </span>
                                    )}
                                    {c.seal_no && (
                                      <span className="text-sm text-slate-700 tabular-nums">
                                        Số chì: <strong className="text-slate-900">{c.seal_no}</strong>
                                      </span>
                                    )}
                                    <span className="text-sm font-medium text-purple-700">
                                      {orderLabel}
                                    </span>
                                  </div>

                                  <span
                                    className={`inline-flex items-center gap-1.5 text-sm font-medium ${
                                      validOk ? "text-emerald-700" : "text-purple-700"
                                    }`}
                                  >
                                    <span
                                      className={`w-2 h-2 rounded-full ${
                                        validOk ? "bg-emerald-500" : "bg-purple-600"
                                      }`}
                                    />
                                    <span>{validOk ? "Hợp lệ" : "Cần kiểm tra"}</span>
                                  </span>
                                </div>

                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                                  <div>
                                    <div className="text-sm text-slate-500">Khách hàng</div>
                                    <div className="text-base font-medium text-slate-900 mt-0.5">
                                      {c.customer_hint || "—"}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-sm text-slate-500">Điểm giao / nhận</div>
                                    <div className="text-base font-medium text-slate-900 mt-0.5">
                                      {c.warehouse_hint || "—"}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-sm text-slate-500">Đối chiếu kế hoạch</div>
                                    <div className="text-base font-medium text-slate-900 mt-0.5">
                                      {getMatchStatusLabel(c.match_source)}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-sm text-slate-500">Giờ đến dự kiến</div>
                                    <div className="text-base font-medium text-slate-900 mt-0.5 tabular-nums">
                                      {c.eta || "—"}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-sm text-slate-500">Ngày kế hoạch</div>
                                    <div className="text-base font-medium text-slate-900 mt-0.5 tabular-nums">
                                      {c.plan_date || "—"}
                                    </div>
                                  </div>
                                </div>

                                {(c.warnings || []).length > 0 && (
                                  <div className="pt-2 border-t border-slate-200 space-y-1">
                                    {(c.warnings || []).map((w: string, i: number) => (
                                      <div key={i} className="text-sm text-purple-700">
                                        Lưu ý: {w}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}

                  {/* 4. Thông báo gửi khách hàng */}
                  {detailData?.outbound_messages && detailData.outbound_messages.length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="text-sm font-semibold text-slate-700">
                          Thông báo gửi khách hàng ({detailData.outbound_messages.length})
                        </div>
                        <Link
                          href="/results"
                          className="text-sm text-purple-700 hover:underline font-medium"
                        >
                          Xem ở Kết quả gửi
                        </Link>
                      </div>

                      <div className="space-y-2.5">
                        {detailData.outbound_messages.map((out: any) => {
                          const outMeta = getOutboundStatusMeta(out.status);
                          return (
                            <div
                              key={out.id}
                              className="bg-slate-50 border border-slate-200 rounded-sm p-4 space-y-2.5"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex flex-wrap items-center gap-3">
                                  <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${outMeta.textClass}`}>
                                    <span className={`w-2 h-2 rounded-full ${outMeta.dotClass}`} />
                                    <span>{outMeta.label}</span>
                                  </span>
                                  {out.message_kind === "update" && (
                                    <span className="text-sm font-medium text-purple-700">
                                      · Cập nhật xe
                                    </span>
                                  )}
                                  <span className="text-sm text-slate-600">
                                    Nhóm nhận:{" "}
                                    <strong className="text-slate-900">
                                      {out.target_group_name || "Nhóm khách hàng"}
                                    </strong>
                                  </span>
                                </div>

                                {out.status === "cho_duyet" && (
                                  <button
                                    type="button"
                                    disabled={approvingMsg}
                                    onClick={() => handleApproveOutbound(out.id)}
                                    className="px-3 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-sm font-medium transition disabled:opacity-50"
                                  >
                                    {approvingMsg ? "Đang gửi..." : "Duyệt & Gửi ngay"}
                                  </button>
                                )}
                              </div>

                              <div className="bg-white border border-slate-200 rounded-sm p-3.5 text-base text-slate-900 whitespace-pre-wrap leading-relaxed">
                                {out.content}
                              </div>

                              {out.last_error && (
                                <div className="text-sm text-rose-700">
                                  Lỗi gửi: {out.last_error}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* 5. Cảnh báo & Phản hồi tự động */}
                  {(detailData?.review_cases?.length > 0 || detailData?.bot_replies?.length > 0) && (
                    <div className="bg-slate-50 border border-slate-200 rounded-sm p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="text-sm font-semibold text-slate-700">
                          Cần điều hành kiểm tra & Phản hồi tự động
                        </div>
                        <Link
                          href="/reviews"
                          className="text-sm text-purple-700 hover:underline font-medium"
                        >
                          Mở mục Chờ duyệt
                        </Link>
                      </div>

                      {detailData?.review_cases?.length > 0 && (
                        <div className="space-y-2">
                          {detailData.review_cases.map((rc: any) => (
                            <div
                              key={rc.id}
                              className="p-3.5 bg-white border border-slate-200 rounded-sm space-y-1"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-base font-semibold text-purple-700">
                                  {getReviewCaseTypeLabel(rc.case_type)}
                                </span>
                                <span className="text-sm font-medium text-slate-600">
                                  {getReviewStatusLabel(rc.status)}
                                </span>
                              </div>
                              <div className="text-sm text-slate-700 leading-relaxed">
                                {rc.reason}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {detailData?.bot_replies?.length > 0 && (
                        <div className="space-y-2">
                          <div className="text-sm text-slate-600 font-medium">
                            Tin phản hồi đã gửi trên Zalo:
                          </div>
                          {detailData.bot_replies.map((br: any) => (
                            <div
                              key={br.id}
                              className="p-3.5 bg-white border border-slate-200 rounded-sm text-base text-slate-900 whitespace-pre-wrap leading-relaxed"
                            >
                              {br.reply_text}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Hộp thoại nhập lý do từ chối */}
      {rejectModalOpen && (
        <div
          className="fixed inset-0 bg-slate-900/50 flex items-center justify-center z-[60] p-4"
          onClick={() => setRejectModalOpen(false)}
        >
          <div
            className="bg-white border border-slate-200 rounded-sm max-w-md w-full p-5 text-base text-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-lg font-bold text-slate-900">
                Từ chối tin nhắn điều xe
              </h3>
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="mt-4 space-y-2">
              <label className="block text-sm font-medium text-slate-700">
                Lý do từ chối
              </label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
                className="w-full border border-slate-300 rounded-sm p-2.5 text-sm placeholder:text-xs placeholder:text-slate-400 focus:outline-none focus:border-purple-600 font-sans"
                placeholder="Nhập lý do từ chối..."
              />
            </div>

            <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                disabled={rejectingMsg}
                className="px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-sm text-sm font-medium transition"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                onClick={handleConfirmReject}
                disabled={rejectingMsg}
                className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-sm text-sm font-medium transition disabled:opacity-50"
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
