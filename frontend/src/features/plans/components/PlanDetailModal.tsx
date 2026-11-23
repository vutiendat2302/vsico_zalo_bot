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

/**
 * Định dạng phương thức giao nhận sang tiếng Việt.
 */
export function formatDeliveryTerm(term?: number | null): string {
  if (term === 1) return "Nguyên cont";
  if (term === 2) return "Kiểm đếm";
  return "—";
}

/**
 * Định dạng kích cỡ và loại container hiển thị.
 */
export function formatContainerSizeBadge(size?: string | null, type?: string | null): string {
  if (!size) return "—";
  if (type) return `${size}${type}`;
  return `${size}HC`;
}

/**
 * Định dạng quyền sở hữu vỏ container sang nhãn thân thiện.
 */
function formatOwnership(ownership?: number | null): string {
  if (ownership === 1) return "Vỏ VSICO";
  if (ownership === 2) return "Vỏ chủ hàng";
  return "—";
}

/**
 * Định dạng trạng thái điều phối TMS sang tiếng Việt.
 */
function formatDispatchState(state?: number | null): string {
  if (state === 2) return "Chờ điều phối";
  if (state === 3) return "Đã nhận";
  if (state === 5) return "Đang thực hiện";
  if (state !== null && state !== undefined) return "Đã đồng bộ";
  return "Chưa gán điều phối";
}

/**
 * Hiển thị trạng thái cảnh báo tình trạng vỏ container.
 */
function renderWarningBadge(warning?: string | null, msg?: string | null) {
  if (!warning && !msg) return "—";
  const label = msg || warning;
  let dotCls = "bg-slate-400";
  let textCls = "text-slate-700";
  if (warning === "normal") {
    dotCls = "bg-emerald-500";
    textCls = "text-emerald-700";
  } else if (warning === "over_combined") {
    dotCls = "bg-amber-500";
    textCls = "text-amber-700";
  } else if (warning === "empty_drop") {
    dotCls = "bg-rose-500";
    textCls = "text-rose-700";
  } else if (warning === "other_requested" || warning === "soc") {
    dotCls = "bg-purple-600";
    textCls = "text-purple-700";
  }

  return (
    <span className={`inline-flex items-center gap-1.5 text-base font-medium ${textCls}`}>
      <span className={`w-2 h-2 rounded-full ${dotCls}`} />
      <span>{label}</span>
    </span>
  );
}

/**
 * Modal hiển thị chi tiết đầy đủ một lệnh kế hoạch vận chuyển (dùng chung cho /plans và /master/transport-plans).
 */
export function PlanDetailModal({ plan, onClose }: PlanDetailModalProps) {
  if (!plan) return null;

  const isTra = plan.order_type === "tra";
  const headerTitle = plan.order_code || (isTra ? "Lệnh trả" : "Lệnh đóng");
  const subtitleParts = [
    plan.plan_date ? `Ngày: ${plan.plan_date}` : null,
    plan.container_no ? `Container: ${plan.container_no}` : null,
  ].filter(Boolean);

  const points = Array.isArray(plan.points_json) ? plan.points_json : [];

  return (
    <MasterDetailModal
      open={!!plan}
      onClose={onClose}
      title={headerTitle}
      subtitle={subtitleParts.join("  |  ") || undefined}
      maxWidthClass="max-w-4xl"
    >
      {/* 1. THÔNG TIN CHUNG */}
      <DetailSection title="Thông tin chung" columns={3}>
        <DetailField label="Mã lệnh" value={plan.order_code || (plan.stt ? `Dòng ${plan.stt}` : "—")} />
        <DetailField
          label="Loại lệnh"
          value={
            <span className={isTra ? "text-emerald-700 font-semibold" : "text-purple-700 font-semibold"}>
              {isTra ? "Trả hàng" : "Đóng hàng"}
            </span>
          }
        />
        <DetailField label="Đơn vị giao nhận" value={plan.forwarder_name || "—"} />
        <DetailField label="Khách hàng" value={plan.customer_name || "—"} />
        <DetailField label="Hàng hóa" value={plan.cargo_type || "—"} />
        <DetailField
          label={isTra ? "Số vận đơn" : "Số đặt chỗ"}
          value={plan.bill_of_lading_no || plan.booking_no || "—"}
        />
      </DetailSection>

      {/* 2. CONTAINER & TÌNH TRẠNG VỎ */}
      <DetailSection title="Container & Vỏ" columns={3}>
        <DetailField
          label="Số container"
          value={
            <span className="font-semibold text-slate-900 tabular-nums">
              {plan.container_no || "Chưa cấp số container"}
            </span>
          }
        />
        <DetailField label="Số chì" value={<span className="tabular-nums">{plan.seal_no || "—"}</span>} />
        <DetailField
          label="Kích cỡ container"
          value={formatContainerSizeBadge(plan.container_size, plan.container_type)}
        />
        <DetailField label="Phân hạng vỏ" value={plan.container_grade || "—"} />
        <DetailField label="Loại vỏ" value={formatOwnership(plan.container_ownership)} />
        <DetailField label="Phương thức giao nhận" value={formatDeliveryTerm(plan.delivery_term)} />
        <DetailField
          label="Tải trọng"
          value={plan.cargo_weight != null ? `${Number(plan.cargo_weight).toFixed(2)} tấn` : "—"}
        />
        <DetailField
          label="Tình trạng vỏ"
          value={renderWarningBadge(plan.container_warning, plan.container_status_message)}
        />
      </DetailSection>

      {/* 3. TUYẾN & ĐỊA ĐIỂM */}
      <DetailSection title="Tuyến & Địa điểm" columns={3}>
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
        <DetailField label={isTra ? "Ngày tàu đến" : "Ngày tàu đi"} value={plan.eta || "—"} />
        <DetailField label="Địa chỉ chi tiết" value={plan.delivery_address || "—"} fullWidth />
      </DetailSection>

      {/* 4. THỜI GIAN & ĐIỀU PHỐI XE / ZALO */}
      <DetailSection title="Thời gian, Điều phối & Zalo" columns={3}>
        <DetailField label="Giờ có mặt" value={<span className="tabular-nums">{plan.required_time || "—"}</span>} />
        <DetailField label="Trạng thái điều phối" value={formatDispatchState(plan.dispatch_state)} />
        <DetailField label="Nhà xe phụ trách" value={plan.fleet_partner || plan.carrier_name || "—"} />
        <DetailField label="Biển số xe" value={<span className="tabular-nums">{plan.planned_truck_plate || "—"}</span>} />
        <DetailField label="Biển số rơ-moóc" value={<span className="tabular-nums">{plan.planned_trailer_plate || "—"}</span>} />
        <DetailField label="Tài xế" value={plan.driver_name || "—"} />
        <DetailField label="SĐT tài xế" value={<span className="tabular-nums">{plan.driver_phone || "—"}</span>} />
        <DetailField label="Cán bộ giao nhận" value={plan.operator_staff || "—"} />
        <DetailField
          label="Nhóm Zalo nhận tin"
          value={plan.group_name || "Chưa gán nhóm"}
        />
      </DetailSection>

      {/* 5. LỊCH TRÌNH ĐIỂM (NẾU CÓ) */}
      {points.length > 0 && (
        <DetailSection title="Lịch trình điểm" columns={2}>
          <div className="sm:col-span-2 space-y-2">
            {points.map((pt, idx) => (
              <div
                key={idx}
                className="bg-white border border-slate-200 rounded-sm px-3.5 py-2.5 text-base"
              >
                <div className="flex items-center justify-between gap-2 font-semibold text-slate-900">
                  <span>
                    Điểm {pt.sequence ?? idx + 1}: {pt.warehouse_name || "Kho"}
                  </span>
                  <span className="text-purple-700 tabular-nums">
                    {pt.required_time || "—"}
                    {pt.end_time ? ` - ${pt.end_time}` : ""}
                  </span>
                </div>
                {pt.address && <div className="text-sm text-slate-600 mt-1">{pt.address}</div>}
              </div>
            ))}
          </div>
        </DetailSection>
      )}

      {/* 6. GHI CHÚ & PHÁT SINH */}
      {(plan.notes || plan.extra_fee_notes) && (
        <DetailSection title="Ghi chú & Phát sinh" columns={2}>
          <DetailField label="Ghi chú" value={plan.notes || "—"} fullWidth />
          <DetailField label="Phát sinh" value={plan.extra_fee_notes || "—"} fullWidth />
        </DetailSection>
      )}
    </MasterDetailModal>
  );
}
