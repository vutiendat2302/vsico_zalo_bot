"use client";

import React from "react";
import { TransportPlanItem } from "@/lib/api";
import {
  DetailField,
  DetailSection,
  MasterDetailModal,
} from "@/features/master/components/MasterShell";

interface PlanDetailModalProps {
  plan: TransportPlanItem | null;
  onClose: () => void;
}

export function formatDeliveryTerm(term?: number | null): string {
  if (term === 1) return "Nguyên cont";
  if (term === 2) return "Kiểm đếm";
  return "—";
}

export function formatContainerSizeBadge(size?: string | null, type?: string | null): string {
  if (!size) return "—";
  if (type) return `${size}${type}`;
  return `${size}HC`;
}

function formatOwnership(ownership?: number | null): string {
  if (ownership === 1) return "COC (vỏ VSICO)";
  if (ownership === 2) return "SOC";
  return "—";
}

function formatDispatchState(state?: number | null): string {
  if (state === 2) return "Chờ điều phối";
  if (state === 3) return "Đã nhận / Sẵn sàng";
  if (state === 5) return "Đang thực hiện";
  if (state !== null && state !== undefined) return `Trạng thái #${state}`;
  return "Chưa gán TMS";
}

function renderWarningBadge(warning?: string | null, msg?: string | null) {
  if (!warning && !msg) return "—";
  const label = msg || warning;
  let cls = "bg-slate-100 text-slate-700 border-slate-200";
  if (warning === "normal") cls = "bg-emerald-50 text-emerald-700 border-emerald-200";
  else if (warning === "over_combined") cls = "bg-amber-50 text-amber-700 border-amber-200";
  else if (warning === "empty_drop") cls = "bg-rose-50 text-rose-700 border-rose-200";
  else if (warning === "other_requested" || warning === "soc") {
    cls = "bg-purple-50 text-purple-700 border-purple-200";
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium border ${cls}`}>
      {label}
    </span>
  );
}

/**
 * Modal hiển thị chi tiết đầy đủ một lệnh kế hoạch vận chuyển (dùng chung cho /plans và /master/transport-plans).
 */
export function PlanDetailModal({ plan, onClose }: PlanDetailModalProps) {
  if (!plan) return null;

  const isTra = plan.order_type === "tra";
  const headerPrefix = isTra ? "Lệnh trả" : "Lệnh đóng";
  const headerTitle = `${headerPrefix}${plan.order_code ? ` (${plan.order_code})` : ""}${
    plan.forwarder_name ? ` — ${plan.forwarder_name}` : ""
  }`;
  const subtitleParts = [
    plan.plan_date ? `Ngày: ${plan.plan_date}` : null,
    plan.container_no ? `Cont: ${plan.container_no}` : null,
    plan.tms_order_id ? `Mã TMS: ${plan.tms_order_id}` : null,
  ].filter(Boolean);

  const points = Array.isArray(plan.points_json) ? plan.points_json : [];

  return (
    <MasterDetailModal
      open={!!plan}
      onClose={onClose}
      title={headerTitle}
      subtitle={subtitleParts.join("  |  ") || `ID: ${plan.id}`}
    >
      {/* 1. THÔNG TIN CHUNG */}
      <DetailSection title="Thông tin chung">
        <DetailField label="Mã lệnh" value={plan.order_code || `#${plan.stt || plan.id}`} />
        <DetailField
          label="Loại lệnh"
          value={
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium ${
                isTra
                  ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                  : "bg-sky-50 text-sky-700 border border-sky-200"
              }`}
            >
              {isTra ? "Trả hàng (Nhập - I)" : "Đóng hàng (Xuất - X)"}
            </span>
          }
        />
        <DetailField label="Đơn vị Forwarder" value={plan.forwarder_name || "—"} />
        <DetailField label="Khách hàng" value={plan.customer_name || "—"} />
        <DetailField label="Hàng hóa" value={plan.cargo_type || "—"} />
        <DetailField
          label={isTra ? "Số B/L" : "Số Booking"}
          value={plan.bill_of_lading_no || plan.booking_no || "—"}
        />
      </DetailSection>

      {/* 2. CONTAINER & TÌNH TRẠNG VỎ */}
      <DetailSection title="Container & Vỏ">
        <DetailField
          label="Số Container"
          value={
            <span className="font-mono font-semibold text-slate-900">
              {plan.container_no || "Chưa cấp số cont"}
            </span>
          }
        />
        <DetailField label="Số Seal" value={plan.seal_no || "—"} />
        <DetailField
          label="Kích cỡ / Loại cont"
          value={formatContainerSizeBadge(plan.container_size, plan.container_type)}
        />
        <DetailField label="Phân hạng vỏ (Grade)" value={plan.container_grade || "—"} />
        <DetailField label="Loại vỏ" value={formatOwnership(plan.container_ownership)} />
        <DetailField label="Phương thức giao nhận" value={formatDeliveryTerm(plan.delivery_term)} />
        <DetailField
          label="Tải trọng (cả vỏ)"
          value={plan.cargo_weight != null ? `${Number(plan.cargo_weight).toFixed(2)}T` : "—"}
        />
        <DetailField
          label="Tình trạng vỏ"
          value={renderWarningBadge(plan.container_warning, plan.container_status_message)}
        />
      </DetailSection>

      {/* 3. TUYẾN & ĐỊA ĐIỂM */}
      <DetailSection title="Tuyến & Địa điểm">
        <DetailField
          label={isTra ? "Kho trả" : "Kho đóng"}
          value={plan.warehouse_name || "—"}
          fullWidth
        />
        <DetailField label="Tỉnh / Thành phố" value={plan.province_name || "—"} />
        <DetailField label="Phường / Xã" value={plan.ward_name || "—"} />
        <DetailField label="Cảng nhập / xuất" value={plan.full_depot || plan.empty_depot || "—"} />
        <DetailField label="Tuyến vận chuyển" value={plan.route_name || "—"} />
        <DetailField label="Tàu - Số chuyến" value={plan.vessel_voyage || "—"} />
        <DetailField label={isTra ? "ETA tàu" : "ETD tàu"} value={plan.eta || "—"} />
        <DetailField label="Địa chỉ chi tiết" value={plan.delivery_address || "—"} fullWidth />
      </DetailSection>

      {/* 4. THỜI GIAN & ĐIỀU PHỐI XE / ZALO */}
      <DetailSection title="Thời gian, Điều phối & Zalo">
        <DetailField label="YC giờ có mặt" value={plan.required_time || "—"} />
        <DetailField label="Trạng thái TMS" value={formatDispatchState(plan.dispatch_state)} />
        <DetailField label="Đội xe / Nhà xe" value={plan.fleet_partner || plan.carrier_name || "—"} />
        <DetailField label="Biển số xe" value={plan.planned_truck_plate || "—"} />
        <DetailField label="Tài xế" value={plan.driver_name || "—"} />
        <DetailField label="SĐT tài xế" value={plan.driver_phone || "—"} />
        <DetailField label="Cán bộ giao nhận" value={plan.operator_staff || "—"} />
        <DetailField
          label="Nhóm Zalo nhận tin"
          value={
            <span className="font-mono text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded-sm">
              {plan.group_name ? `${plan.group_name} (${plan.group_id})` : plan.group_id || "—"}
            </span>
          }
        />
      </DetailSection>

      {/* 5. LỊCH TRÌNH ĐA ĐIỂM (NẾU CÓ) */}
      {points.length > 0 && (
        <DetailSection title={`Lịch trình điểm (${points.length} điểm)`}>
          <div className="sm:col-span-2 space-y-1.5">
            {points.map((pt, idx) => (
              <div
                key={idx}
                className="bg-white border border-slate-200 rounded-sm px-2.5 py-2 text-[11px]"
              >
                <div className="flex items-center justify-between gap-2 font-semibold text-slate-900">
                  <span>
                    Điểm {pt.sequence ?? idx + 1}: {pt.warehouse_name || "Kho"}
                  </span>
                  <span className="text-purple-700 font-mono">
                    {pt.required_time || "—"}
                    {pt.end_time ? ` - ${pt.end_time}` : ""}
                  </span>
                </div>
                {pt.address && <div className="text-slate-600 mt-0.5">{pt.address}</div>}
              </div>
            ))}
          </div>
        </DetailSection>
      )}

      {/* 6. GHI CHÚ & PHÁT SINH */}
      {(plan.notes || plan.extra_fee_notes) && (
        <DetailSection title="Ghi chú & Phát sinh">
          <DetailField label="Ghi chú" value={plan.notes || "—"} fullWidth />
          <DetailField label="Phát sinh" value={plan.extra_fee_notes || "—"} fullWidth />
        </DetailSection>
      )}
    </MasterDetailModal>
  );
}
