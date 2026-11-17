/**
 * API Client cho nhóm màn hình Dữ liệu danh mục TMS (Master Data).
 * Chỉ hỗ trợ đọc, tìm kiếm, lọc và phân trang từ Backend MySQL.
 */

import { getAuthToken, redirectToLoginOnUnauthorized } from "@/lib/auth";
import { TransportPlanItem } from "@/lib/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Id = string;

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface CarrierOption {
  id: Id;
  code: string | null;
  name: string;
  short_name: string | null;
}

export interface CarrierItem {
  id: Id;
  tms_carrier_id: string;
  code: string | null;
  name: string;
  short_name: string | null;
  tax_code: string | null;
  is_active: boolean;
  vehicle_count: number;
  driver_count: number;
}

export interface DriverItem {
  id: Id;
  tms_driver_id: string;
  carrier_id: Id | null;
  carrier_name: string | null;
  full_name: string;
  phone: string | null;
  identity_no: string | null;
  license_no: string | null;
  is_active: boolean;
}

export interface VehicleItem {
  id: Id;
  tms_vehicle_id: string;
  carrier_id: Id | null;
  carrier_name: string | null;
  plate_no: string;
  vehicle_type: number | null;
  payload_capacity: number | null;
  driver_hint_name: string | null;
  is_active: boolean;
}

export interface TrailerItem {
  id: Id;
  tms_mooc_id: string;
  tms_carrier_id: string | null;
  carrier_id: Id | null;
  carrier_name: string | null;
  carrier_short_name: string | null;
  license_plate: string;
  normalized_plate: string;
  mooc_type: number | null;
  model: string | null;
  note: string | null;
  is_active: boolean;
  synced_at: string | null;
}

export interface PaginatedTrailersResponse extends PaginatedResponse<TrailerItem> {
  filter_options?: {
    models: string[];
  };
}

export interface CustomerItem {
  id: Id;
  tms_customer_id: string;
  name: string;
  normalized_name: string;
  is_active: boolean;
  warehouse_count: number;
}

export interface WarehouseItem {
  id: Id;
  tms_warehouse_id: string;
  customer_id: Id | null;
  customer_name: string | null;
  location_type: "warehouse" | "port" | "depot" | string;
  name: string;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  is_active: boolean;
}

async function fetchMasterJson<T>(path: string, params?: Record<string, string | number | boolean | undefined | null>): Promise<T> {
  const qs = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        qs.set(key, String(value));
      }
    });
  }
  const url = `${API_BASE_URL}${path}${qs.toString() ? `?${qs.toString()}` : ""}`;
  const token = getAuthToken();
  const res = await fetch(url, {
    cache: "no-store",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });

  if (!res.ok) {
    if (res.status === 401) {
      redirectToLoginOnUnauthorized();
    }
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.message || "Không thể tải dữ liệu danh mục");
  }
  return res.json();
}

export async function getCarrierOptions(): Promise<CarrierOption[]> {
  return fetchMasterJson<CarrierOption[]>("/api/master/carriers/options");
}

export async function getCarriers(params: {
  search?: string;
  is_active?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedResponse<CarrierItem>> {
  return fetchMasterJson<PaginatedResponse<CarrierItem>>("/api/master/carriers", params);
}

export async function getDrivers(params: {
  search?: string;
  carrier_id?: string;
  is_active?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedResponse<DriverItem>> {
  return fetchMasterJson<PaginatedResponse<DriverItem>>("/api/master/drivers", params);
}

export async function getVehicles(params: {
  search?: string;
  vehicle_type?: string;
  carrier_id?: string;
  is_active?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedResponse<VehicleItem>> {
  return fetchMasterJson<PaginatedResponse<VehicleItem>>("/api/master/vehicles", params);
}

export async function getTrailers(params: {
  search?: string;
  mooc_type?: string;
  model?: string;
  carrier_id?: string;
  is_active?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedTrailersResponse> {
  return fetchMasterJson<PaginatedTrailersResponse>("/api/master/trailers", params);
}

export async function syncTrailersFromTms(): Promise<{
  ok: boolean;
  message: string;
  fetched: number;
  created: number;
  updated: number;
}> {
  const token = getAuthToken();
  const res = await fetch(`${API_BASE_URL}/api/master/trailers/sync`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    if (res.status === 401) {
      redirectToLoginOnUnauthorized();
    }
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.message || "Không thể đồng bộ rơ-moóc từ TMS");
  }
  return res.json();
}

export async function getCustomers(params: {
  search?: string;
  is_active?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedResponse<CustomerItem>> {
  return fetchMasterJson<PaginatedResponse<CustomerItem>>("/api/master/customers", params);
}

export async function getWarehouses(params: {
  search?: string;
  location_type?: string;
  is_active?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedResponse<WarehouseItem>> {
  return fetchMasterJson<PaginatedResponse<WarehouseItem>>("/api/master/warehouses", params);
}

export interface ContainerBalanceBucket {
  return_count: number;
  unmatchable_count: number;
  matchable_count: number;
  loading_count: number;
  balance: number;
}

export interface MasterPlanSummary {
  container_balance: {
    size_20ft: ContainerBalanceBucket;
    size_40ft: ContainerBalanceBucket;
    total: ContainerBalanceBucket;
  };
  container_warning_counts: {
    normal: number;
    over_combined: number;
    empty_drop: number;
    other_requested: number;
    soc: number;
  };
}

export interface MasterPlanProvinceGroup {
  province_id: number | null;
  province_name: string;
  total_orders: number;
  return_orders_count: number;
  loading_orders_count: number;
  container_balance: MasterPlanSummary["container_balance"];
  container_warning_counts: MasterPlanSummary["container_warning_counts"];
  return_orders: TransportPlanItem[];
  loading_orders: TransportPlanItem[];
}

export interface MasterTransportPlansResponse {
  ok: boolean;
  plan_date: string;
  region: number;
  total_orders: number;
  summary: MasterPlanSummary;
  filter_options: {
    forwarders: string[];
    dispatch_states: number[];
  };
  provinces: MasterPlanProvinceGroup[];
  orders: TransportPlanItem[];
}

export async function getMasterTransportPlans(params: {
  plan_date: string;
  region?: number;
  search?: string;
  forwarder_name?: string;
  order_type?: string;
  container_size?: string;
  delivery_term?: string;
  dispatch_state?: string;
  container_warning?: string;
}): Promise<MasterTransportPlansResponse> {
  return fetchMasterJson<MasterTransportPlansResponse>("/api/master/transport-plans", params);
}

export interface TmsAutoSyncStatus {
  ok: boolean;
  enabled: boolean;
  credentials_configured: boolean;
  running: boolean;
  is_syncing: boolean;
  interval_minutes: number;
  last_success_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
}

export async function getTmsAutoSyncStatus(): Promise<TmsAutoSyncStatus> {
  return fetchMasterJson<TmsAutoSyncStatus>("/api/plans/tms-sync-status");
}
