"use client";

/**
 * Trang Chờ duyệt (Review Cases Queue).
 * Đồng bộ 3 màu với Trang tổng quan (trắng/xám, đen chữ, tím nhấn),
 * không dùng icon trang trí, không giải thích dài dòng, 100% dữ liệu thật từ Backend API.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  ReviewCaseItem,
  approveReviewCase,
  claimReviewCase,
  getReviewCases,
  rejectReviewCase,
} from "@/lib/api";
import { getClientSession } from "@/lib/auth";

function resolveReviewStatusMeta(rawStatus: string) {
  const norm = (rawStatus || "").trim().toUpperCase();
  if (norm === "PENDING") {
    return { isPending: true, label: "Chờ duyệt", dotClass: "bg-purple-700", textClass: "text-purple-700" };
  }
  if (norm === "APPROVED") {
    return { isPending: false, label: "Đã duyệt", dotClass: "bg-emerald-600", textClass: "text-slate-900" };
  }
  if (norm === "RESOLVED") {
    return { isPending: false, label: "Đã xử lý", dotClass: "bg-emerald-600", textClass: "text-slate-900" };
  }
  if (norm === "REJECTED") {
    return { isPending: false, label: "Từ chối", dotClass: "bg-rose-600", textClass: "text-rose-700" };
  }
  return { isPending: false, label: norm || "—", dotClass: "bg-slate-400", textClass: "text-slate-600" };
}

function formatShortTime(isoStr?: string | null): string {
  if (!isoStr) return "—";
  const dt = new Date(isoStr);
  if (Number.isNaN(dt.getTime())) return isoStr.slice(0, 16).replace("T", " ");
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

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<ReviewCaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("PENDING");
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);

  const [approveTarget, setApproveTarget] = useState<ReviewCaseItem | null>(null);
  const [approveCont, setApproveCont] = useState("");
  const [approveSeal, setApproveSeal] = useState("");
  const [approvePlate, setApprovePlate] = useState("");
  const [approveDriver, setApproveDriver] = useState("");
  const [approvePhone, setApprovePhone] = useState("");

  const [rejectModalId, setRejectModalId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string>("Dữ liệu không hợp lệ");
  const [rejecting, setRejecting] = useState(false);

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const getOperatorName = () => {
    const user = getClientSession();
    return user?.username || "admin";
  };

  const loadReviews = useCallback(
    async (page = currentPage, size = pageSize) => {
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
        setError(err.message || "Không thể tải danh sách chờ duyệt.");
      } finally {
        setLoading(false);
      }
    },
    [currentPage, pageSize, statusFilter]
  );

  useEffect(() => {
    loadReviews(currentPage, pageSize);
  }, [currentPage, pageSize, statusFilter, loadReviews]);

  const handleClaim = async (id: string) => {
    try {
      setActionLoadingId(id);
      setActionNotice(null);
      setError(null);
      await claimReviewCase(id, getOperatorName());
      await loadReviews(currentPage, pageSize);
    } catch (err: any) {
      setError(err.message || "Lỗi khi nhận ca.");
    } finally {
      setActionLoadingId(null);
    }
  };

  const openApproveModal = (r: ReviewCaseItem) => {
    setApproveTarget(r);
    setApproveCont(r.container_details?.container_no || "");
    setApproveSeal(r.container_details?.seal_no || "");
    setApprovePlate(r.container_details?.truck_plate || "");
    setApproveDriver(r.container_details?.driver_name || "");
    setApprovePhone(r.container_details?.driver_phone || "");
  };

  const handleConfirmApprove = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!approveTarget) return;
    try {
      setActionLoadingId(approveTarget.id);
      setActionNotice(null);
      setError(null);
      const res = await approveReviewCase(approveTarget.id, {
        operator_name: getOperatorName(),
        ...(approveCont.trim() ? { container_no: approveCont.trim() } : {}),
        ...(approveSeal.trim() ? { seal_no: approveSeal.trim() } : {}),
        ...(approvePlate.trim() ? { truck_plate: approvePlate.trim() } : {}),
        ...(approveDriver.trim() ? { driver_name: approveDriver.trim() } : {}),
        ...(approvePhone.trim() ? { driver_phone: approvePhone.trim() } : {}),
      });
      if (res?.warnings && res.warnings.length > 0) {
        setActionNotice(`Đã duyệt ca #${approveTarget.id}: ${res.warnings.join("; ")}`);
      }
      setApproveTarget(null);
      await loadReviews(currentPage, pageSize);
    } catch (err: any) {
      setError(err.message || "Lỗi khi phê duyệt.");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleOpenRejectModal = (id: string) => {
    setRejectModalId(id);
    setRejectReason("Dữ liệu không hợp lệ");
  };

  const handleConfirmReject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rejectModalId) return;
    try {
      setRejecting(true);
      setActionNotice(null);
      setError(null);
      await rejectReviewCase(
        rejectModalId,
        rejectReason.trim() || "Dữ liệu không hợp lệ",
        getOperatorName()
      );
      setRejectModalId(null);
      await loadReviews(currentPage, pageSize);
    } catch (err: any) {
      setError(err.message || "Lỗi khi từ chối.");
    } finally {
      setRejecting(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-5 text-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-slate-900">Chờ duyệt</h1>
          <span className="text-xs font-mono text-purple-700 font-semibold tabular-nums">
            {total}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setCurrentPage(1);
            }}
            className="bg-white border border-slate-300 rounded-sm px-3 py-1.5 text-xs text-slate-900 focus:outline-none focus:border-purple-700"
          >
            <option value="PENDING">Chờ duyệt</option>
            <option value="APPROVED">Đã duyệt</option>
            <option value="REJECTED">Từ chối</option>
            <option value="">Tất cả</option>
          </select>

          <button
            type="button"
            onClick={() => loadReviews(currentPage, pageSize)}
            disabled={loading}
            className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-900 rounded-sm text-xs font-medium border border-slate-200 transition"
          >
            {loading ? "Đang tải..." : "Làm mới"}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-white border border-rose-300 rounded-sm text-rose-700 text-xs">
          {error}
        </div>
      )}

      {actionNotice && (
        <div className="p-3 bg-purple-50 border border-purple-200 rounded-sm text-purple-700 text-xs">
          {actionNotice}
        </div>
      )}

      {/* Danh sách ca */}
      <div className="space-y-3">
        {loading && reviews.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-sm py-10 text-center text-slate-500 text-xs">
            Đang tải dữ liệu...
          </div>
        ) : reviews.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-sm py-10 text-center text-slate-500 text-xs">
            Không có ca cần duyệt.
          </div>
        ) : (
          reviews.map((r) => {
            const st = resolveReviewStatusMeta(r.status);
            const msg = r.message_context;
            const c = r.container_details;
            const isBusy = actionLoadingId === r.id;

            return (
              <div
                key={r.id}
                className="bg-white border border-slate-200 rounded-sm p-4 text-xs space-y-3 hover:border-purple-300 transition"
              >
                {/* Header ca */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-slate-200">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-mono font-bold text-sm text-slate-900 tabular-nums">
                      #{r.id}
                    </span>
                    <span className={`inline-flex items-center gap-1.5 font-medium ${st.textClass}`}>
                      <span className={`w-2 h-2 rounded-full ${st.dotClass}`} />
                      <span>{st.label}</span>
                    </span>
                    <span className="font-mono text-[11px] px-2 py-0.5 rounded-sm bg-slate-100 text-slate-700 border border-slate-200">
                      {r.case_type}
                    </span>
                    {r.assigned_to && (
                      <span className="text-[11px] text-purple-700 font-medium">
                        {r.assigned_to}
                      </span>
                    )}
                  </div>

                  <div className="text-slate-500 font-mono text-[11px] tabular-nums">
                    {formatShortTime(r.created_at)}
                    {r.resolved_at && ` • ${formatShortTime(r.resolved_at)}`}
                    {r.resolved_by && ` • ${r.resolved_by}`}
                  </div>
                </div>

                {/* Lý do */}
                <div className="bg-slate-50 border border-slate-200 p-2.5 rounded-sm text-slate-900 font-medium">
                  {r.reason}
                </div>

                {/* Thông tin chính */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="bg-slate-50 p-3 rounded-sm border border-slate-200 space-y-1">
                    <div className="flex items-center justify-between text-slate-500">
                      <span className="font-medium text-slate-700">Tin nhắn</span>
                      <span className="font-mono text-[11px]">
                        {msg?.sender_name || "—"} • {msg?.group_id || "—"}
                      </span>
                    </div>
                    <div className="font-mono text-slate-900 whitespace-pre-wrap leading-relaxed">
                      {msg?.raw_text || "—"}
                    </div>
                  </div>

                  <div className="bg-slate-50 p-3 rounded-sm border border-slate-200 space-y-2">
                    <div className="font-medium text-slate-700">Thông tin bóc tách</div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                      <div>
                        <span className="text-slate-500">Container: </span>
                        <span className="font-mono font-semibold text-slate-900">
                          {c?.container_no || "—"}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500">Số chì: </span>
                        <span className="font-mono text-slate-900">{c?.seal_no || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Khách hàng: </span>
                        <span className="font-medium text-slate-900">{c?.customer_hint || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Lệnh: </span>
                        <span className="font-medium text-slate-900">{c?.order_type || "—"}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Thao tác */}
                {st.isPending && (
                  <div className="flex justify-end items-center gap-2 pt-1">
                    {!r.assigned_to && (
                      <button
                        type="button"
                        onClick={() => handleClaim(r.id)}
                        disabled={isBusy}
                        className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium transition disabled:opacity-50"
                      >
                        Nhận ca
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleOpenRejectModal(r.id)}
                      disabled={isBusy}
                      className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium transition disabled:opacity-50"
                    >
                      Từ chối
                    </button>
                    <button
                      type="button"
                      onClick={() => openApproveModal(r)}
                      disabled={isBusy}
                      className="px-4 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm font-medium transition disabled:opacity-50"
                    >
                      Duyệt
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Phân trang */}
        {total > 0 && (
          <div className="px-4 py-2.5 bg-white border border-slate-200 rounded-sm flex flex-col sm:flex-row items-center justify-between gap-2 text-xs">
            <div className="text-slate-600 tabular-nums">
              {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, total)} / {total}
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
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={20}>20</option>
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

      {/* Modal Phê duyệt */}
      {approveTarget && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleConfirmApprove}
            className="bg-white border border-slate-200 rounded-sm max-w-lg w-full p-5 text-xs text-slate-700 space-y-4"
          >
            <div className="flex items-center justify-between pb-2.5 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900 font-mono">
                Duyệt ca #{approveTarget.id}
              </h3>
              <button
                type="button"
                onClick={() => setApproveTarget(null)}
                className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm"
              >
                Đóng
              </button>
            </div>

            <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-sm text-slate-900">
              {approveTarget.reason}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-600 mb-1 font-medium">Số container</label>
                <input
                  type="text"
                  value={approveCont}
                  onChange={(e) => setApproveCont(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 font-mono text-slate-900 focus:outline-none focus:border-purple-700"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1 font-medium">Số chì</label>
                <input
                  type="text"
                  value={approveSeal}
                  onChange={(e) => setApproveSeal(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 font-mono text-slate-900 focus:outline-none focus:border-purple-700"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1 font-medium">Biển số xe</label>
                <input
                  type="text"
                  value={approvePlate}
                  onChange={(e) => setApprovePlate(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 font-mono text-slate-900 focus:outline-none focus:border-purple-700"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1 font-medium">Tài xế</label>
                <input
                  type="text"
                  value={approveDriver}
                  onChange={(e) => setApproveDriver(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-purple-700"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-slate-600 mb-1 font-medium">Số điện thoại</label>
                <input
                  type="text"
                  value={approvePhone}
                  onChange={(e) => setApprovePhone(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 font-mono text-slate-900 focus:outline-none focus:border-purple-700"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setApproveTarget(null)}
                className="px-3.5 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium"
              >
                Đóng
              </button>
              <button
                type="submit"
                disabled={actionLoadingId === approveTarget.id}
                className="px-4 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm font-medium transition disabled:opacity-50"
              >
                {actionLoadingId === approveTarget.id ? "Đang duyệt..." : "Xác nhận duyệt"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Modal Từ chối */}
      {rejectModalId && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleConfirmReject}
            className="bg-white border border-slate-200 rounded-sm max-w-md w-full p-5 text-xs text-slate-700 space-y-4"
          >
            <h3 className="text-sm font-bold text-slate-900 font-mono">
              Từ chối ca #{rejectModalId}
            </h3>
            <div>
              <label className="block text-slate-600 mb-1 font-medium">Lý do từ chối</label>
              <textarea
                rows={3}
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                className="w-full bg-white border border-slate-300 rounded-sm p-2.5 text-slate-900 focus:outline-none focus:border-purple-700"
                required
              />
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setRejectModalId(null)}
                className="px-3.5 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium"
              >
                Đóng
              </button>
              <button
                type="submit"
                disabled={rejecting}
                className="px-4 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm font-medium transition disabled:opacity-50"
              >
                {rejecting ? "Đang xử lý..." : "Xác nhận từ chối"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
