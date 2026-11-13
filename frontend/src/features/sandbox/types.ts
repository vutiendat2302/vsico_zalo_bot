/**
 * Định nghĩa kiểu dữ liệu TypeScript cho module Kiểm thử Thuật toán & Bối cảnh (Sandbox Dry-Run).
 * Khớp 100% với hợp đồng API `/api/sandbox/simulate` và `/api/sandbox/context-options`.
 */

export interface SandboxVirtualJob {
  container_no: string | null;
  truck_plate: string | null;
  trailer_plate: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  container_size: string | null;
  seal_no: string | null;
  order_type: string | null;
  customer_hint: string | null;
  warehouse_hint: string | null;
  eta_time: string | null;
  plan_date: string | null;
  line_text: string;
  status: string;
}

export interface SandboxSimulateRequest {
  text: string;
  image_base64?: string | null;
  quote_message?: string | null;
  context_messages: string[];
  virtual_jobs: SandboxVirtualJob[];
  carrier_hint?: string | null;
  timestamp?: string | null;
  allow_ai_fallback: boolean;
}

export interface SandboxOcrStage {
  triggered: boolean;
  has_text: boolean;
  confidence: number;
  extracted_text: string;
  lines_count: number;
}

export interface SandboxContextResolution {
  understood: boolean;
  resolution_type: string;
  summary: string;
  changes_list: string[];
  target_container: string | null;
  clarify_missing_container: boolean;
  is_duplicate_update: boolean;
}

export interface SandboxExtractedRecord {
  line_no: number;
  source_format: string;
  plate: string | null;
  raw_plate: string | null;
  trailer_plate: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  cont_no: string | null;
  cont_size: string | null;
  seal_no: string | null;
  order_type: string | null;
  customer_raw: string | null;
  customer_code_or_id: string | number | null;
  location_raw: string | null;
  warehouse_code_or_id: string | number | null;
  eta: string | null;
  plan_date: string | null;
  check_digit_valid: boolean | null;
  validation_status: string;
  match_source: string;
  confidence: number;
  warnings: string[];
}

export interface SandboxPlanMatch {
  container_no: string | null;
  match_source: string;
  plan_found: boolean;
  plan_order_type: string | null;
  plan_customer: string | null;
  plan_carrier: string | null;
  carrier_mismatch: boolean;
}

export interface SandboxPreviewOutputs {
  bot_reply: string | null;
  customer_notification: string | null;
  dhvt_alert: string | null;
}

export interface SandboxSimulateResponse {
  ok: boolean;
  persisted: boolean;
  effective_text: string;
  masked_text: string;
  processing_status: string;
  initial_intent: string;
  resolved_intent: string;
  source_format: string | null;
  ai_would_trigger: boolean;
  ai_executed: boolean;
  ai_service_status: string;
  model_name: string;
  prompt_version: string;
  latency_ms: number;
  ocr: SandboxOcrStage;
  context_resolution: SandboxContextResolution;
  records: SandboxExtractedRecord[];
  plan_matches: SandboxPlanMatch[];
  preview_outputs: SandboxPreviewOutputs;
  warnings: string[];
  taxonomy: Record<string, unknown>;
  virtual_jobs_next: SandboxVirtualJob[];
}

export interface SandboxSamplePlan {
  container_no: string | null;
  order_type: string | null;
  customer_name: string | null;
  fleet_partner: string | null;
  delivery_address: string | null;
  plan_date: string | null;
}

export interface SandboxContextOptions {
  ok: boolean;
  persisted: boolean;
  total_plans_in_db: number;
  carriers: string[];
  sample_plans: SandboxSamplePlan[];
}

export interface SandboxPreset {
  id: string;
  label: string;
  category: string;
  description: string;
  text: string;
  quote_message?: string;
  carrier_hint?: string;
  suggested_follow_up?: string;
}

export interface SandboxTurnHistoryItem {
  turn: number;
  input_text: string;
  quote_message: string | null;
  resolved_intent: string;
  processing_status: string;
  resolution_type: string;
  summary: string;
  ai_executed: boolean;
  latency_ms: number;
}
