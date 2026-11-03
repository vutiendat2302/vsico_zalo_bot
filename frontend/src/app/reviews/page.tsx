"use client";

import React, { useEffect, useState } from "react";
import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  RefreshCw,
  AlertTriangle,
  X,
} from "lucide-react";
import { ReviewCaseItem, getReviewCases, approveReviewCase, rejectReviewCase } from "@/lib/api";

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<ReviewCaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);

  // Modal từ chối
  const [rejectModalId, setRejectModalId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState<string>("Dữ liệu không chính xác theo kiểm tra thủ công.");
  const [rejecting, setRejecting] = useState(false);

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const loadReviews = async (page = currentPage, size = pageSize) => {
    try {
      setLoading(true);
      setError(null);
      const res = await getReviewCases({
        status: statusFilter || undefined,
        limit: size,
        offset: (page - 1) * size,
      });
      setReviews(res.reviews);
      setTotal(res.total);
    } catch (err: any) {
      setError(err.message || "Lỗi khi lấy danh sách ca cần duyệt.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setCurrentPage(1);
    loadReviews(1, pageSize);
  }, [statusFilter]);

  useEffect(() => {
    loadReviews(currentPage, pageSize);
  }, [currentPage, pageSize]);

  const handleApprove = async (id: number) => {
    if (!confirm(`Xác nhận PHÊ DUYỆT ca rà soát #${id}?`)) return;
    try {
      setActionLoadingId(id);
      const res = await approveReviewCase(id);
      if (res?.warnings && res.warnings.length > 0) {
        alert(`Đã phê duyệt ca #${id} trong hệ thống!\n⚠️ Cảnh báo gửi tin Zalo: ${res.warnings.join("\n")}`);
      }
      await loadReviews();
    } catch (err: any) {
      alert("Lỗi khi phê duyệt: " + err.message);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleOpenRejectModal = (id: number) => {
    setRejectModalId(id);
    setRejectReason("Dữ liệu không chính xác theo kiểm tra thủ công.");
  };

  const handleConfirmReject = async () => {
    if (!rejectModalId) return;
    try {
      setRejecting(true);
      await rejectReviewCase(rejectModalId, rejectReason || "Dữ liệu không chính xác theo kiểm tra thủ công.");
      setRejectModalId(null);
      await loadReviews();
    } catch (err: any) {
      alert("Lỗi khi từ chối: " + err.message);
    } finally {
      setRejecting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-amber-400" />
            Hàng Đợi Rà Soát & Phê Duyệt ({total} ca)
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Các trường hợp tin nhắn có cảnh báo nghiệp vụ (sai Check Digit ISO 6346, thiếu thông tin cốt lõi, biển rơ-moóc) cần điều độ viên duyệt
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500"
          >
            <option value="pending">Chỉ ca Chờ Duyệt (pending)</option>
            <option value="approved">Đã Phê Duyệt (approved)</option>
            <option value="rejected">Đã Từ Chối (rejected)</option>
            <option value="">Tất cả</option>
          </select>

          <button
            onClick={() => loadReviews(currentPage, pageSize)}
            disabled={loading}
            className="flex items-center space-x-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="p-3 bg-rose-950/40 border border-rose-800 rounded-lg text-rose-300 text-xs flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Review Cases List */}
      <div className="space-y-4">
        {loading && reviews.length === 0 ? (
          <div className="py-16 text-center text-slate-400 text-sm">Đang tải danh sách ca rà soát...</div>
        ) : reviews.length === 0 ? (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center text-slate-400">
            <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
            <h3 className="text-base font-semibold text-white">Không có ca nào cần rà soát!</h3>
            <p className="text-xs text-slate-500 mt-1">
              Toàn bộ tin nhắn đến đã được bóc tách và thẩm định tự động thành công.
            </p>
          </div>
        ) : (
          reviews.map((r) => {
            const isPending = r.status === "pending";
            const msg = r.message_context;
            const c = r.container_details;

            return (
              <div
                key={r.id}
                className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-xs space-y-3.5 hover:border-slate-700 transition shadow-sm"
              >
                {/* Case Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-slate-800/80">
                  <div className="flex items-center space-x-3">
                    <span className="font-mono font-bold text-sm text-white">Ca #{r.id}</span>
                    <span className="px-2 py-0.5 rounded font-mono text-[11px] bg-amber-950 text-amber-400 border border-amber-800/60">
                      Loại: {r.case_type}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                        isPending
                          ? "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                          : r.status === "approved"
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                          : "bg-red-500/10 text-red-400 border border-red-500/30"
                      }`}
                    >
                      {r.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="text-slate-500 text-[11px]">
                    Tạo lúc: {r.created_at?.slice(0, 16).replace("T", " ")}
                    {r.resolved_at && ` • Xử lý: ${r.resolved_at?.slice(0, 16).replace("T", " ")} (${r.resolved_by})`}
                  </div>
                </div>

                {/* Reason & Warnings */}
                <div className="bg-amber-950/30 border border-amber-800/40 p-3 rounded-lg text-amber-200">
                  <div className="font-bold mb-1 flex items-center gap-1.5 text-amber-300">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    <span>Lý do đưa vào hàng đợi duyệt:</span>
                  </div>
                  <div className="text-amber-100 font-mono text-[11px] whitespace-pre-wrap">{r.reason}</div>
                </div>

                {/* Context Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-slate-300">
                  {/* Tin nhắn Zalo gốc */}
                  <div className="bg-slate-950/70 p-3 rounded-lg border border-slate-800/60 space-y-1.5">
                    <div className="font-semibold text-slate-400 flex items-center justify-between">
                      <span>Ngữ cảnh tin nhắn:</span>
                      <span className="text-[11px] text-blue-400">
                        {msg?.sender_name} (Group: {msg?.group_id})
                      </span>
                    </div>
                    <div className="font-mono text-slate-200 bg-slate-900/80 p-2 rounded border border-slate-800/50 whitespace-pre-wrap">
                      {msg?.raw_text || "—"}
                    </div>
                  </div>

                  {/* Thông tin bóc tách */}
                  <div className="bg-slate-950/70 p-3 rounded-lg border border-slate-800/60 space-y-1.5">
                    <div className="font-semibold text-slate-400">Dữ liệu Container bóc tách:</div>
                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div>
                        <span className="text-slate-500">Số container:</span>{" "}
                        <strong className="font-mono text-purple-300">{c?.container_no || "Chưa có"}</strong>
                      </div>
                      <div>
                        <span className="text-slate-500">Số chì (Seal):</span>{" "}
                        <span className="font-mono text-slate-300">{c?.seal_no || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Khách hàng:</span>{" "}
                        <span className="text-sky-300 font-medium">{c?.customer_hint || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Loại lệnh:</span>{" "}
                        <span className="text-slate-300 font-medium">{c?.order_type || "—"}</span>
                      </div>
                    </div>
                    {c?.warnings && c.warnings.length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-1">
                        {c.warnings.map((w, i) => (
                          <span
                            key={i}
                            className="bg-amber-950/60 text-amber-300 px-1.5 py-0.5 rounded text-[10px] border border-amber-800/50"
                          >
                            {w}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Actions */}
                {isPending && (
                  <div className="flex justify-end space-x-3 pt-2">
                    <button
                      onClick={() => handleOpenRejectModal(r.id)}
                      disabled={actionLoadingId === r.id}
                      className="flex items-center space-x-1.5 px-3 py-1.5 bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800/60 rounded-lg text-xs font-medium transition"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      <span>Từ chối</span>
                    </button>
                    <button
                      onClick={() => handleApprove(r.id)}
                      disabled={actionLoadingId === r.id}
                      className="flex items-center space-x-1.5 px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-sm transition"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Phê duyệt chấp nhận</span>
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Pagination Toolbar */}
        {total > 0 && (
          <div className="p-4 bg-slate-900 border border-slate-800 rounded-xl flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="text-slate-400">
              Hiển thị <span className="font-semibold text-white">{(currentPage - 1) * pageSize + 1}</span> -{" "}
              <span className="font-semibold text-white">{Math.min(currentPage * pageSize, total)}</span> trong{" "}
              <span className="font-semibold text-white">{total}</span> ca rà soát
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
                  className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-amber-500"
                >
                  <option value={5}>5</option>
                  <option value={10}>10</option>
                  <option value={20}>20</option>
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

      {/* Modal xác nhận lý do từ chối */}
      {rejectModalId !== null && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 text-xs text-slate-300 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <h3 className="text-sm font-bold text-rose-400 flex items-center gap-1.5">
                <XCircle className="w-4 h-4 text-rose-400" />
                <span>Từ chối ca rà soát #{rejectModalId}</span>
              </h3>
              <button
                type="button"
                onClick={() => setRejectModalId(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div>
              <label className="block text-slate-300 font-semibold mb-1.5">
                Lý do từ chối (bản ghi và tin gửi khách sẽ chuyển sang Bị Hủy):
              </label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-xs text-white focus:outline-none focus:border-rose-500 font-mono"
                placeholder="Nhập lý do từ chối..."
              />
            </div>

            <div className="flex justify-end space-x-2 pt-2">
              <button
                type="button"
                onClick={() => setRejectModalId(null)}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                disabled={rejecting}
                onClick={handleConfirmReject}
                className="px-4 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold transition flex items-center gap-1.5 shadow-sm disabled:opacity-50"
              >
                {rejecting ? (
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <XCircle className="w-3.5 h-3.5" />
                )}
                <span>{rejecting ? "Đang xử lý..." : "Xác nhận Từ chối"}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
