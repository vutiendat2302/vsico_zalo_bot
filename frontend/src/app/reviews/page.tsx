"use client";

/**
 * Trang Chờ duyệt (Review Cases Queue).
 * Đồng bộ 3 màu với Trang tổng quan (trắng/xám, đen chữ, tím nhấn),
 * không dùng icon trang trí, không giải thích dài dòng, 100% dữ liệu thật từ Backend API.
 */

import React, { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ReviewCaseItem,
  TransportPlanItem,
  approveReviewCase,
  claimReviewCase,
  getReviewCases,
  getTransportPlans,
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

function formatPlanDate(dateStr?: string | null): string {
  if (!dateStr) return "";
  const m = String(dateStr).trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[3]}/${m[2]}/${m[1]}`;
  return String(dateStr).trim();
}

const CASE_TYPE_LABELS: Record<string, string> = {
  REVIEW_CHANGE_AFTER_SENT: "Đề xuất thay đổi sau khi gửi",
  PLAN_SYNC_REQUIRED: "Chọn kế hoạch đồng bộ",
  missing_fields: "Thiếu / sai thông tin xe",
  MISSING_FIELDS: "Thiếu / sai thông tin xe",
  invalid_check_digit: "Sai số kiểm tra container",
  INVALID_CHECK_DIGIT: "Sai số kiểm tra container",
  PLAN_FIELD_CONFLICT: "Lệch thông tin kế hoạch",
  CARRIER_MISMATCH: "Lệch nhà xe kế hoạch",
  SHIPPING_NOT_FOUND: "Chưa tìm thấy kế hoạch",
  ROUTING_NOT_FOUND: "Chưa có nhóm Zalo nhận",
  OUTBOUND_PENDING_APPROVAL: "Chờ duyệt gửi khách",
  OUTBOUND_SEND_FAILED: "Gửi Zalo thất bại",
  group_manual_review: "Nhóm ở chế độ chờ duyệt",
  GROUP_MANUAL_REVIEW: "Nhóm ở chế độ chờ duyệt",
  CUSTOMER_CHANGE_REQUEST: "Khách yêu cầu thay đổi",
  CARRIER_CANCEL_REQUEST: "Nhà xe báo hủy chuyến",
  PLAN_RESOLUTION: "Đối chiếu kế hoạch",
};

function formatCaseTypeLabel(caseType?: string | null): string {
  if (!caseType) return "Ca rà soát";
  return CASE_TYPE_LABELS[caseType] || CASE_TYPE_LABELS[caseType.toUpperCase()] || caseType;
}

function ReviewsPageContent() {
  const searchParams = useSearchParams();
  const deepRef = searchParams.get("ref");
  const deepReviewId = searchParams.get("reviewId");
  const deepOutboundId = searchParams.get("outboundId");
  const openedDeepLinkRef = useRef<string | null>(null);

  const [reviews, setReviews] = useState<ReviewCaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("PENDING");
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);

  const [approveTarget, setApproveTarget] = useState<ReviewCaseItem | null>(null);
  const [detailTarget, setDetailTarget] = useState<ReviewCaseItem | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<string>("");
  const [availablePlans, setAvailablePlans] = useState<TransportPlanItem[]>([]);
  const [planSearch, setPlanSearch] = useState<string>("");
  const [loadingPlans, setLoadingPlans] = useState<boolean>(false);
  const [approveCont, setApproveCont] = useState("");
  const [approveSeal, setApproveSeal] = useState("");
  const [approvePlate, setApprovePlate] = useState("");
  const [approveTrailer, setApproveTrailer] = useState("");
  const [approveDriver, setApproveDriver] = useState("");
  const [approvePhone, setApprovePhone] = useState("");
  const [approveOutboundContent, setApproveOutboundContent] = useState("");

  const DEFAULT_REJECT_REASON = "Yêu cầu chưa đáp ứng điều kiện xử lý tại thời điểm hiện tại.";
  const [rejectModalId, setRejectModalId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string>("");
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

  useEffect(() => {
    const key = deepRef
      ? `ref:${deepRef}`
      : deepReviewId
        ? `r:${deepReviewId}`
        : deepOutboundId
          ? `o:${deepOutboundId}`
          : null;
    if (!key || openedDeepLinkRef.current === key) return;
    openedDeepLinkRef.current = key;
    let cancelled = false;
    (async () => {
      try {
        const res = await getReviewCases(
          deepRef
            ? { short_token: deepRef, limit: 1 }
            : deepReviewId
              ? { review_id: deepReviewId, limit: 1 }
              : { outbound_id: deepOutboundId || "", limit: 1 }
        );
        if (!cancelled && res.reviews && res.reviews.length > 0) {
          setDetailTarget(res.reviews[0]);
        } else if (!cancelled && deepRef) {
          setError("Liên kết chi tiết không hợp lệ hoặc ca duyệt không còn tồn tại.");
        }
      } catch {
        // Bỏ qua nếu không tìm thấy ca từ tham số URL
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [deepReviewId, deepOutboundId]);

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

  const openApproveModal = (r: ReviewCaseItem, preselectedPlanId?: string) => {
    setApproveTarget(r);
    const defaultPid =
      preselectedPlanId ||
      r.details?.selected_plan_id ||
      r.details?.transport_plan_id ||
      r.candidate_plans?.[0]?.plan_id ||
      "";
    setSelectedPlanId(defaultPid ? String(defaultPid) : "");
    setPlanSearch("");
    setApproveCont(r.container_details?.container_no || "");
    setApproveSeal(r.container_details?.seal_no || "");
    setApprovePlate(r.container_details?.truck_plate || "");
    setApproveTrailer(r.container_details?.trailer_plate || "");
    setApproveDriver(r.container_details?.driver_name || "");
    setApprovePhone(r.container_details?.driver_phone || "");
    setApproveOutboundContent(r.outbound_preview?.content || "");
  };

  useEffect(() => {
    if (!approveTarget) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        setLoadingPlans(true);
        const res = await getTransportPlans({
          q: planSearch.trim() || undefined,
          limit: 100,
        });
        if (!cancelled) {
          setAvailablePlans(res.plans || []);
        }
      } catch {
        if (!cancelled) {
          setAvailablePlans([]);
        }
      } finally {
        if (!cancelled) {
          setLoadingPlans(false);
        }
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [approveTarget, planSearch]);

  const handleConfirmApprove = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!approveTarget) return;
    try {
      setActionLoadingId(approveTarget.id);
      setActionNotice(null);
      setError(null);
      const origOutboundText = (approveTarget.outbound_preview?.content || "").trim();
      const editedOutboundText = approveOutboundContent.trim();
      const res = await approveReviewCase(approveTarget.id, {
        operator_name: getOperatorName(),
        save_warehouse_habit: true,
        ...(selectedPlanId.trim() ? { selected_plan_id: selectedPlanId.trim() } : {}),
        ...(approveCont.trim() ? { container_no: approveCont.trim() } : {}),
        ...(approveSeal.trim() ? { seal_no: approveSeal.trim() } : {}),
        ...(approvePlate.trim() ? { truck_plate: approvePlate.trim() } : {}),
        ...(approveTrailer.trim() ? { trailer_plate: approveTrailer.trim() } : {}),
        ...(approveDriver.trim() ? { driver_name: approveDriver.trim() } : {}),
        ...(approvePhone.trim() ? { driver_phone: approvePhone.trim() } : {}),
        ...(editedOutboundText && editedOutboundText !== origOutboundText
          ? { outbound_content: editedOutboundText }
          : {}),
      });
      if (res?.warnings && res.warnings.length > 0) {
        const refLabel = approveTarget.container_details?.container_no
          ? `Cont ${approveTarget.container_details.container_no}`
          : formatCaseTypeLabel(approveTarget.case_type);
        setActionNotice(`Đã duyệt ca (${refLabel}): ${res.warnings.join("; ")}`);
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
    setRejectReason("");
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
        rejectReason.trim() || DEFAULT_REJECT_REASON,
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
    <div className="h-full min-h-0 flex flex-col gap-3 text-sm">
      {/* Header */}
      <div className="shrink-0 flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
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
      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
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
                    <span className="font-semibold text-sm text-slate-900">
                      {formatCaseTypeLabel(r.case_type)}
                    </span>
                    {c?.container_no && (
                      <span className="font-mono font-semibold text-xs text-slate-800 bg-slate-100 px-2 py-0.5 rounded-sm border border-slate-200">
                        {c.container_no}
                      </span>
                    )}
                    <span className={`inline-flex items-center gap-1.5 font-medium ${st.textClass}`}>
                      <span className={`w-2 h-2 rounded-full ${st.dotClass}`} />
                      <span>{st.label}</span>
                    </span>
                    {r.assigned_to && (
                      <span className="text-[11px] text-purple-700 font-medium">
                        • {r.assigned_to}
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
                      <div>
                        <span className="text-slate-500">Xe / Moóc: </span>
                        <span className="font-mono text-slate-900">
                          {[c?.truck_plate, c?.trailer_plate].filter(Boolean).join(" / ") || "—"}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500">Giờ dự kiến: </span>
                        <span className="font-mono text-slate-900">{c?.eta || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Tài xế / SĐT: </span>
                        <span className="text-slate-900">
                          {[c?.driver_name, c?.driver_phone].filter(Boolean).join(" • ") || "—"}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500">Kho: </span>
                        <span className="font-medium text-slate-900">{c?.warehouse_hint || "—"}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Các trường thay đổi (nếu là bản cập nhật) */}
                {Array.isArray(r.details?.changes) && r.details.changes.length > 0 && (
                  <div className="bg-purple-50 border border-purple-200 p-2.5 rounded-sm space-y-1">
                    <div className="font-medium text-purple-800">Trường cập nhật so với thông tin cũ</div>
                    <div className="font-mono text-slate-900 whitespace-pre-wrap">
                      {r.details.changes.join("\n")}
                    </div>
                  </div>
                )}

                {/* Mẫu thông báo sẽ gửi khách hàng (giống trang Kết quả gửi) */}
                {r.outbound_preview && (
                  <div className="bg-slate-50 p-3 rounded-sm border border-slate-200 space-y-1.5">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-slate-600">
                      <span className="font-medium text-slate-700">
                        Mẫu output gửi khách hàng
                        {r.outbound_preview.target_group_name
                          ? ` • ${r.outbound_preview.target_group_name}`
                          : ""}
                      </span>
                      <span className="font-mono text-[11px] text-purple-700">
                        {r.outbound_preview.status === "FAILED"
                          ? "Gửi thất bại"
                          : r.outbound_preview.status === "PENDING_APPROVAL"
                          ? "Chờ duyệt gửi"
                          : r.outbound_preview.status === "PREVIEW"
                          ? "Xem trước đầu ra"
                          : r.outbound_preview.status}
                      </span>
                    </div>
                    <div className="font-mono text-slate-900 whitespace-pre-wrap leading-relaxed bg-white p-2.5 rounded-sm border border-slate-200">
                      {r.outbound_preview.content}
                    </div>
                    {r.outbound_preview.last_error && (
                      <div className="text-[11px] text-rose-700">{r.outbound_preview.last_error}</div>
                    )}
                  </div>
                )}

                {/* Kế hoạch ứng viên (nếu có) */}
                {r.candidate_plans && r.candidate_plans.length > 0 && (
                  <div className="bg-slate-50 p-3 rounded-sm border border-slate-200 space-y-2">
                    <div className="font-medium text-slate-700">
                      Ứng viên kế hoạch ({r.candidate_plans.length})
                    </div>
                    <div className="space-y-1.5">
                      {r.candidate_plans.map((cand) => (
                        <div
                          key={cand.plan_id}
                          className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 bg-white px-2.5 py-1.5 rounded-sm border border-slate-200"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono font-semibold text-slate-900">
                              {cand.order_code || `#${cand.plan_id}`}
                            </span>
                            {cand.order_type && (
                              <span className="font-mono text-[11px] px-1.5 py-0.5 bg-slate-100 border border-slate-200 rounded-sm text-slate-700">
                                {cand.order_type}
                              </span>
                            )}
                            {cand.customer_name && (
                              <span className="text-slate-800">{cand.customer_name}</span>
                            )}
                            {cand.warehouse_name && (
                              <span className="text-slate-600">• {cand.warehouse_name}</span>
                            )}
                            {cand.plan_date && (
                              <span className="font-mono text-[11px] text-slate-700">
                                • Ngày: {formatPlanDate(cand.plan_date)}
                              </span>
                            )}
                            {cand.required_time && (
                              <span className="font-mono text-[11px] text-slate-700">
                                • Giờ dự kiến: {cand.required_time}
                              </span>
                            )}
                            {typeof cand.score === "number" && (
                              <span className="font-mono text-[11px] text-purple-700 font-semibold">
                                Điểm: {cand.score}
                              </span>
                            )}
                            {cand.evidences && cand.evidences.length > 0 && (
                              <span className="font-mono text-[11px] text-slate-500">
                                [{cand.evidences.join(", ")}]
                              </span>
                            )}
                          </div>
                          {st.isPending && (
                            <button
                              type="button"
                              onClick={() => openApproveModal(r, String(cand.plan_id))}
                              className="px-2.5 py-1 bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 rounded-sm font-medium transition"
                            >
                              Chọn lệnh này
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Thao tác */}
                <div className="flex justify-end items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => setDetailTarget(r)}
                    className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium transition"
                  >
                    Xem chi tiết
                  </button>
                  {st.isPending && (
                    <>
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
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}

        {/* Phân trang */}
        {total > 0 && (
          <div className="shrink-0 px-4 py-2.5 bg-white border border-slate-200 rounded-sm flex flex-col sm:flex-row items-center justify-between gap-2 text-xs">
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

      {/* Modal Xem chi tiết ca & Output gửi khách hàng */}
      {detailTarget && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white border border-slate-200 rounded-sm max-w-2xl w-full max-h-[90vh] overflow-y-auto p-5 text-xs text-slate-700 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-3">
                <h3 className="text-base font-bold text-slate-900">
                  {formatCaseTypeLabel(detailTarget.case_type)}
                  {detailTarget.container_details?.container_no
                    ? ` — Cont ${detailTarget.container_details.container_no}`
                    : ""}
                </h3>
                {(() => {
                  const dst = resolveReviewStatusMeta(detailTarget.status);
                  return (
                    <span className={`inline-flex items-center gap-1.5 font-medium ${dst.textClass}`}>
                      <span className={`w-2 h-2 rounded-full ${dst.dotClass}`} />
                      <span>{dst.label}</span>
                    </span>
                  );
                })()}
              </div>
              <button
                type="button"
                onClick={() => setDetailTarget(null)}
                className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm"
              >
                Đóng
              </button>
            </div>

            <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-sm text-slate-900 font-medium">
              {detailTarget.reason}
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 bg-slate-50 p-3 rounded-sm border border-slate-200">
              <div>
                <div className="text-slate-500">Số container</div>
                <div className="font-mono font-semibold text-slate-900 mt-0.5">
                  {detailTarget.container_details?.container_no || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Biển số xe</div>
                <div className="font-mono text-slate-900 mt-0.5">
                  {detailTarget.container_details?.truck_plate || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Biển số rơ-moóc</div>
                <div className="font-mono text-slate-900 mt-0.5">
                  {detailTarget.container_details?.trailer_plate || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Tài xế</div>
                <div className="text-slate-900 mt-0.5">
                  {detailTarget.container_details?.driver_name || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">SĐT tài xế</div>
                <div className="font-mono text-slate-900 mt-0.5">
                  {detailTarget.container_details?.driver_phone || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Số chì (tùy chọn)</div>
                <div className="font-mono text-slate-900 mt-0.5">
                  {detailTarget.container_details?.seal_no || "Chưa có"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Khách hàng</div>
                <div className="text-slate-900 mt-0.5">
                  {detailTarget.container_details?.customer_hint || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Kho / Điểm đến</div>
                <div className="text-slate-900 mt-0.5">
                  {detailTarget.container_details?.warehouse_hint || "—"}
                </div>
              </div>
              <div>
                <div className="text-slate-500">Giờ dự kiến</div>
                <div className="font-mono text-slate-900 mt-0.5">
                  {detailTarget.container_details?.eta || "—"}
                </div>
              </div>
            </div>

            {Array.isArray(detailTarget.details?.changes) && detailTarget.details.changes.length > 0 && (
              <div className="space-y-1">
                <div className="font-semibold text-purple-800">Thay đổi so với thông tin cũ</div>
                <div className="p-2.5 bg-purple-50 border border-purple-200 rounded-sm font-mono text-slate-900 whitespace-pre-wrap">
                  {detailTarget.details.changes.join("\n")}
                </div>
              </div>
            )}

            <div className="space-y-1">
              <div className="font-semibold text-slate-900">Tin nhắn gốc từ nhà xe</div>
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-sm font-mono text-slate-900 whitespace-pre-wrap leading-relaxed">
                {detailTarget.message_context?.raw_text || "—"}
              </div>
            </div>

            <div className="space-y-1">
              <div className="font-semibold text-slate-900">
                Output dự kiến gửi khách hàng
                {detailTarget.outbound_preview?.target_group_name
                  ? ` (${detailTarget.outbound_preview.target_group_name})`
                  : ""}
              </div>
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-sm font-mono text-slate-900 whitespace-pre-wrap leading-relaxed">
                {detailTarget.outbound_preview?.content || "Chưa đủ dữ liệu tạo mẫu thông báo."}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-200">
              {resolveReviewStatusMeta(detailTarget.status).isPending && (
                <button
                  type="button"
                  onClick={() => {
                    const target = detailTarget;
                    setDetailTarget(null);
                    openApproveModal(target);
                  }}
                  className="px-4 py-1.5 bg-purple-700 hover:bg-purple-800 text-white rounded-sm font-medium transition"
                >
                  Chuyển sang Duyệt
                </button>
              )}
              <button
                type="button"
                onClick={() => setDetailTarget(null)}
                className="px-4 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-sm font-medium"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Phê duyệt */}
      {approveTarget && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleConfirmApprove}
            className="bg-white border border-slate-200 rounded-sm max-w-lg w-full max-h-[90vh] overflow-y-auto p-5 text-xs text-slate-700 space-y-4"
          >
            <div className="flex items-center justify-between pb-2.5 border-b border-slate-200">
              <h3 className="text-sm font-bold text-slate-900">
                Duyệt: {formatCaseTypeLabel(approveTarget.case_type)}
                {approveTarget.container_details?.container_no
                  ? ` — Cont ${approveTarget.container_details.container_no}`
                  : ""}
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

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-slate-600 font-medium">
                  Chọn kế hoạch đồng bộ (tự động lưu thói quen kho)
                </label>
                {loadingPlans && (
                  <span className="text-[11px] text-slate-400">Đang tải kế hoạch...</span>
                )}
              </div>
              <input
                type="text"
                value={planSearch}
                onChange={(e) => setPlanSearch(e.target.value)}
                placeholder="Tìm nhanh theo mã lệnh, tên khách, kho hoặc cont..."
                className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 text-slate-900 placeholder:text-xs placeholder:text-slate-400 focus:outline-none focus:border-purple-700"
              />
              <select
                value={selectedPlanId}
                onChange={(e) => setSelectedPlanId(e.target.value)}
                className={`w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 font-mono focus:outline-none focus:border-purple-700 ${
                  selectedPlanId ? "text-xs text-slate-900" : "text-xs text-slate-400"
                }`}
              >
                <option value="" className="text-xs text-slate-400">Tự động đối chiếu</option>
                {approveTarget.candidate_plans && approveTarget.candidate_plans.length > 0 && (
                  <optgroup label="Kế hoạch gợi ý">
                    {approveTarget.candidate_plans.map((cand) => (
                      <option key={`cand-${cand.plan_id}`} value={cand.plan_id}>
                        {cand.order_code || `#${cand.plan_id}`}
                        {cand.plan_date ? ` | ${formatPlanDate(cand.plan_date)}` : ""}
                        {" | "}
                        {cand.customer_name || "—"} | {cand.warehouse_name || "—"} (Điểm: {cand.score ?? 0})
                      </option>
                    ))}
                  </optgroup>
                )}
                {availablePlans.length > 0 && (
                  <optgroup label="Danh sách kế hoạch">
                    {availablePlans
                      .filter(
                        (p) =>
                          !(approveTarget.candidate_plans || []).some(
                            (cand) => String(cand.plan_id) === String(p.id)
                          )
                      )
                      .map((p) => {
                        const typeLabel = p.order_type === "dong" ? "Đóng" : p.order_type === "tra" ? "Trả" : p.order_type;
                        const dateLabel = formatPlanDate(p.plan_date);
                        const contLabel = p.container_no || "Chưa cont";
                        const truckLabel = p.planned_truck_plate || "Chưa xe";
                        return (
                          <option key={p.id} value={p.id}>
                            {p.order_code || `#${p.id}`} ({typeLabel})
                            {dateLabel ? ` | ${dateLabel}` : ""} | {contLabel} |{" "}
                            {p.customer_name || "—"} | {p.warehouse_name || "—"} | {truckLabel}
                          </option>
                        );
                      })}
                  </optgroup>
                )}
              </select>
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
                <label className="block text-slate-600 mb-1 font-medium">Biển số rơ-moóc</label>
                <input
                  type="text"
                  value={approveTrailer}
                  onChange={(e) => setApproveTrailer(e.target.value)}
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
              <div>
                <label className="block text-slate-600 mb-1 font-medium">Số điện thoại</label>
                <input
                  type="text"
                  value={approvePhone}
                  onChange={(e) => setApprovePhone(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm px-2.5 py-1.5 font-mono text-slate-900 focus:outline-none focus:border-purple-700"
                />
              </div>
            </div>

            {approveTarget.outbound_preview && (
              <div>
                <label className="block text-slate-600 mb-1 font-medium">
                  Nội dung gửi khách hàng (để nguyên để tự cập nhật theo các ô trên)
                </label>
                <textarea
                  rows={5}
                  value={approveOutboundContent}
                  onChange={(e) => setApproveOutboundContent(e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded-sm p-2.5 font-mono text-slate-900 leading-relaxed focus:outline-none focus:border-purple-700"
                />
              </div>
            )}

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
            {(() => {
              const target = reviews.find((item) => item.id === rejectModalId);
              const cont = target?.container_details?.container_no;
              return (
                <h3 className="text-sm font-bold text-slate-900">
                  Từ chối: {formatCaseTypeLabel(target?.case_type)}
                  {cont ? ` — Cont ${cont}` : ""}
                </h3>
              );
            })()}
            <div>
              <label className="block text-slate-600 mb-1 font-medium">Lý do từ chối</label>
              <textarea
                rows={3}
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Nhập lý do từ chối (để trống sẽ dùng lý do chung mặc định)..."
                className="w-full bg-white border border-slate-300 rounded-sm p-2.5 text-slate-900 focus:outline-none focus:border-purple-700"
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

export default function ReviewsPage() {
  return (
    <Suspense
      fallback={
        <div className="bg-white border border-slate-200 rounded-sm py-10 text-center text-slate-500 text-xs">
          Đang tải danh sách chờ duyệt...
        </div>
      }
    >
      <ReviewsPageContent />
    </Suspense>
  );
}
