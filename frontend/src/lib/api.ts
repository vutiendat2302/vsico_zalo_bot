/**
 * Module Dịch Vụ Gọi API Backend (Real Backend API Client).
 *
 * TUYỆT ĐỐI KHÔNG SỬ DỤNG MOCK DATA.
 * Toàn bộ dữ liệu hiển thị trên giao diện người dùng được gọi trực tiếp từ FastAPI Backend.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DashboardSummary {
  ok: boolean;
  status: string;
  timestamp: string;
  kpi: {
    total_messages_received: number;
    processed_messages: number;
    needs_review_messages: number;
    ignored_chat_messages: number;
    queued_messages: number;
    processed_rate_percent: number;
    total_trucks_extracted: number;
    total_containers_extracted: number;
    total_plans_registered: number;
    bot_replies_sent: number;
    reviews_pending: number;
  };
  plans_summary: {
    total: number;
    dong: number;
    tra: number;
  };
  fifo_queue: {
    queue_size: number;
    total_enqueued: number;
    total_processed: number;
  };
  rate_limiter: {
    max_requests_per_second: number;
    burst_capacity: number;
    available_tokens: number;
    is_throttled: boolean;
    is_backing_off_429: boolean;
    remaining_backoff_seconds: number;
    total_requests_approved: number;
    total_throttled_waits: number;
    total_429_hits: number;
  };
  daily_breakdown: Array<{
    date: string;
    total: number;
    processed: number;
    needs_review: number;
    ignored: number;
  }>;
  recent_messages: Array<{
    id: number;
    zalo_message_id: string;
    group_id: string;
    sender_name: string;
    raw_text: string;
    sent_at: string;
    processing_status: string;
    truck_plates: string[];
    containers: string[];
    customers: string[];
  }>;
}

export interface TransportPlanItem {
  id: number;
  plan_date: string;
  stt?: number | null;
  route_name?: string | null;
  cargo_io_type?: string | null;
  order_type: string;
  container_no?: string | null;
  seal_no?: string | null;
  container_size?: string | null;
  cargo_weight?: number | string | null;
  required_time?: string | null;
  customer_name?: string | null;
  customer_id?: number | null;
  warehouse_id?: number | null;
  cargo_type?: string | null;
  vessel_voyage?: string | null;
  empty_depot?: string | null;
  full_depot?: string | null;
  estimated_drop_time?: string | null;
  fleet_partner?: string | null;
  planned_truck_plate?: string | null;
  delivery_address?: string | null;
  group_id?: string | null;
  operator_staff?: string | null;
  notes?: string | null;
  extra_fee_notes?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface TransportPlansResponse {
  ok: boolean;
  status: string;
  total: number;
  total_returned: number;
  filters: Record<string, any>;
  plans: TransportPlanItem[];
}

export interface ZaloMessageItem {
  id: number;
  zalo_message_id: string;
  group_id: string;
  sender_id: string;
  sender_name?: string | null;
  message_type: string;
  raw_text?: string | null;
  sent_at?: string | null;
  received_at: string;
  processing_status: string;
  taxonomy?: any;
  trucks: Array<{
    id: number;
    truck_plate?: string | null;
    trailer_plate?: string | null;
    driver_name?: string | null;
    driver_phone?: string | null;
    eta_text?: string | null;
    estimated_at?: string | null;
    note?: string | null;
    status: string;
  }>;
  containers: Array<{
    id: number;
    truck_record_id?: number | null;
    line_no: number;
    source_format?: string | null;
    plan_date?: string | null;
    container_no?: string | null;
    container_size?: string | null;
    seal_no?: string | null;
    booking_no?: string | null;
    order_type?: string | null;
    warehouse_hint?: string | null;
    customer_hint?: string | null;
    eta?: string | null;
    estimated_at?: string | null;
    match_source?: string | null;
    check_digit_valid?: boolean | null;
    validation_status: string;
    routing_status: string;
    tms_sync_status: string;
    warnings: string[];
    canonical_record?: any;
  }>;
}

export interface MessagesResponse {
  ok: boolean;
  status: string;
  total: number;
  total_returned: number;
  filters: Record<string, any>;
  messages: ZaloMessageItem[];
}

export interface ReviewCaseItem {
  id: number;
  message_id: number;
  container_job_id?: number | null;
  case_type: string;
  reason: string;
  status: string;
  created_at: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  message_context?: {
    zalo_message_id: string;
    sender_name: string;
    group_id: string;
    raw_text: string;
    sent_at: string;
  };
  container_details?: {
    container_no?: string | null;
    container_size?: string | null;
    seal_no?: string | null;
    order_type?: string | null;
    customer_hint?: string | null;
    warehouse_hint?: string | null;
    validation_status?: string | null;
    warnings: string[];
  };
}

export interface ReviewsResponse {
  ok: boolean;
  status: string;
  total: number;
  total_returned: number;
  reviews: ReviewCaseItem[];
}

// ======================= API CLIENT FUNCTIONS =======================

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const res = await fetch(`${API_BASE_URL}/api/dashboard/summary`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy dữ liệu Dashboard: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getTransportPlans(params?: {
  plan_date?: string;
  container_no?: string;
  customer_name?: string;
  order_type?: string;
  group_id?: string;
  limit?: number;
  offset?: number;
}): Promise<TransportPlansResponse> {
  const query = new URLSearchParams();
  if (params?.plan_date) query.set("plan_date", params.plan_date);
  if (params?.container_no) query.set("container_no", params.container_no);
  if (params?.customer_name) query.set("customer_name", params.customer_name);
  if (params?.order_type) query.set("order_type", params.order_type);
  if (params?.group_id) query.set("group_id", params.group_id);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));

  const url = `${API_BASE_URL}/api/plans?${query.toString()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy danh sách Kế hoạch: HTTP ${res.status}`);
  }
  return res.json();
}

export async function createTransportPlan(data: Partial<TransportPlanItem>): Promise<TransportPlanItem> {
  const res = await fetch(`${API_BASE_URL}/api/plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi tạo Kế hoạch: HTTP ${res.status}`);
  }
  return res.json();
}

export async function updateTransportPlan(
  id: number,
  data: Partial<TransportPlanItem>
): Promise<TransportPlanItem> {
  const res = await fetch(`${API_BASE_URL}/api/plans/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi cập nhật Kế hoạch: HTTP ${res.status}`);
  }
  return res.json();
}

export async function deleteTransportPlan(id: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${API_BASE_URL}/api/plans/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Lỗi khi xóa Kế hoạch: HTTP ${res.status}`);
  }
  return res.json();
}

export async function deletePlansByDate(dateStr: string): Promise<{ ok: boolean; deleted_count: number }> {
  const res = await fetch(`${API_BASE_URL}/api/plans/by-date/${dateStr}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Lỗi khi xóa Kế hoạch theo ngày: HTTP ${res.status}`);
  }
  return res.json();
}

export async function importPlanFile(
  file: File,
  replaceExisting = true,
  planDate?: string
): Promise<any> {
  const formData = new FormData();
  formData.append("file", file);

  const query = new URLSearchParams();
  query.set("replace_existing", String(replaceExisting));
  if (planDate) query.set("plan_date", planDate);

  const res = await fetch(`${API_BASE_URL}/api/plans/import?${query.toString()}`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi Import tệp kế hoạch: HTTP ${res.status}`);
  }
  return res.json();
}

export interface RandomizePlanGroupsResponse {
  ok: boolean;
  status: string;
  message: string;
  total_updated: number;
  group_distribution: Record<string, number>;
}

export async function randomizePlanGroups(
  planDate?: string,
  groupIds?: string[]
): Promise<RandomizePlanGroupsResponse> {
  const query = new URLSearchParams();
  if (planDate) query.set("plan_date", planDate);

  const res = await fetch(`${API_BASE_URL}/api/plans/randomize-groups?${query.toString()}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(
      groupIds || [
        "3051850159021421440",
        "6469608867469758994",
        "7196206900754562564",
      ]
    ),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi phân bổ ngẫu nhiên nhóm: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getMessages(params?: {
  from_time?: string;
  to_time?: string;
  status?: string;
  user_id?: string;
  group_id?: string;
  limit?: number;
  offset?: number;
}): Promise<MessagesResponse> {
  const query = new URLSearchParams();
  if (params?.from_time) query.set("from_time", params.from_time);
  if (params?.to_time) query.set("to_time", params.to_time);
  if (params?.status) query.set("status", params.status);
  if (params?.user_id) query.set("user_id", params.user_id);
  if (params?.group_id) query.set("group_id", params.group_id);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));

  const url = `${API_BASE_URL}/api/messages?${query.toString()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy danh sách tin nhắn: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getMessageDetail(idOrMsgId: string | number): Promise<any> {
  const res = await fetch(`${API_BASE_URL}/api/messages/detail/${idOrMsgId}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy chi tiết tin nhắn: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getReviewCases(params?: {
  status?: string;
  case_type?: string;
  limit?: number;
  offset?: number;
}): Promise<ReviewsResponse> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.case_type) query.set("case_type", params.case_type);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));

  const url = `${API_BASE_URL}/api/reviews?${query.toString()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy danh sách rà soát: HTTP ${res.status}`);
  }
  return res.json();
}

export async function approveReviewCase(reviewId: number): Promise<any> {
  const res = await fetch(`${API_BASE_URL}/api/reviews/${reviewId}/approve`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi phê duyệt ca ${reviewId}`);
  }
  return res.json();
}

export async function rejectReviewCase(reviewId: number, reason: string): Promise<any> {
  const res = await fetch(`${API_BASE_URL}/api/reviews/${reviewId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi từ chối ca ${reviewId}`);
  }
  return res.json();
}

export async function getTaxonomyStatistics(params?: {
  from_time?: string;
  to_time?: string;
  group_id?: string;
}): Promise<any> {
  const query = new URLSearchParams();
  if (params?.from_time) query.set("from_time", params.from_time);
  if (params?.to_time) query.set("to_time", params.to_time);
  if (params?.group_id) query.set("group_id", params.group_id);

  const url = `${API_BASE_URL}/api/messages/statistics?${query.toString()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy thống kê Taxonomy: HTTP ${res.status}`);
  }
  return res.json();
}

export async function triggerFifoQueue(): Promise<any> {
  const res = await fetch(`${API_BASE_URL}/api/messages/process-fifo`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error("Lỗi khi kích hoạt xử lý hàng đợi FIFO");
  }
  return res.json();
}

// ==========================================
// OUTBOUND & KẾT QUẢ TIN NHẮN (MESSAGE RESULTS)
// ==========================================

export interface OutboundContainerInfo {
  container_no?: string;
  truck_plate?: string;
  driver_name?: string;
  driver_phone?: string;
  seal_no?: string;
  plan_date?: string;
}

export interface OutboundMessageItem {
  id: number;
  target_group_id: number;
  target_group_name?: string;
  target_zalo_group_id?: string;
  order_type: string;
  message_kind: string;
  content: string;
  idempotency_key: string;
  review_zalo_msg_id?: string;
  approved_by?: string;
  approved_at?: string;
  status: "cho_duyet" | "da_gui" | "huy" | "that_bai" | string;
  attempt_count: number;
  zalo_message_id?: string;
  last_error?: string;
  created_at?: string;
  sent_at?: string;
  containers: OutboundContainerInfo[];
}

export interface OutboundSummary {
  ok: boolean;
  total: number;
  da_gui: number;
  cho_duyet: number;
  huy: number;
  that_bai: number;
}

export async function getOutboundSummary(): Promise<OutboundSummary> {
  const res = await fetch(`${API_BASE_URL}/api/outbound/summary`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy thống kê kết quả tin nhắn: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getOutboundMessages(params?: {
  status?: string;
  order_type?: string;
  search?: string;
  from_time?: string;
  to_time?: string;
  limit?: number;
  offset?: number;
}): Promise<{ ok: boolean; total: number; messages: OutboundMessageItem[] }> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.order_type) query.set("order_type", params.order_type);
  if (params?.search) query.set("search", params.search);
  if (params?.from_time) query.set("from_time", params.from_time);
  if (params?.to_time) query.set("to_time", params.to_time);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));

  const url = `${API_BASE_URL}/api/outbound/messages?${query.toString()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Lỗi khi tải danh sách kết quả tin nhắn: HTTP ${res.status}`);
  }
  return res.json();
}

export async function approveOutboundMessage(id: number, operatorName?: string): Promise<any> {
  const url = `${API_BASE_URL}/api/outbound/messages/${id}/approve?operator_name=${encodeURIComponent(
    operatorName || "Điều độ viên"
  )}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi duyệt tin #${id}`);
  }
  return res.json();
}

export async function approveMessageByDHVT(messageId: number, operatorName?: string): Promise<any> {
  const url = `${API_BASE_URL}/api/messages/${messageId}/approve?operator_name=${encodeURIComponent(
    operatorName || "Điều độ viên ĐHVT"
  )}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi ĐHVT duyệt tin #${messageId}`);
  }
  return res.json();
}

export async function rejectMessageByDHVT(messageId: number, reason?: string, operatorName?: string): Promise<any> {
  const url = `${API_BASE_URL}/api/messages/${messageId}/reject?operator_name=${encodeURIComponent(
    operatorName || "Điều độ viên ĐHVT"
  )}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason || "ĐHVT từ chối tin nhắn điều xe." }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi ĐHVT từ chối tin #${messageId}`);
  }
  return res.json();
}

export async function cancelOutboundMessage(id: number, reason?: string): Promise<any> {
  const url = `${API_BASE_URL}/api/outbound/messages/${id}/cancel`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi hủy tin #${id}`);
  }
  return res.json();
}

export async function resendOutboundMessage(id: number): Promise<any> {
  const url = `${API_BASE_URL}/api/outbound/messages/${id}/resend`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi gửi lại tin #${id}`);
  }
  return res.json();
}

export async function seedOutboundSamples(): Promise<any> {
  const url = `${API_BASE_URL}/api/outbound/seed-samples`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    throw new Error("Lỗi khi tạo tin nhắn kết quả mẫu");
  }
  return res.json();
}

// ======================= GROUPS MANAGEMENT API =======================

export interface ZaloGroupItem {
  id: number;
  zalo_group_id: string;
  name?: string | null;
  group_role: string;
  carrier_id?: string | null;
  carrier_name?: string | null;
  send_mode: string; // 'tu_dong' | 'cho_duyet'
  send_mode_label: string; // 'Tự động' | 'Chờ duyệt'
  is_active: boolean;
  is_test: boolean;
  created_at?: string | null;
}

export interface GroupsResponse {
  ok: boolean;
  total: number;
  limit: number;
  offset: number;
  groups: ZaloGroupItem[];
}

export async function getGroups(params?: {
  role?: string;
  send_mode?: string;
  is_active?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<GroupsResponse> {
  const query = new URLSearchParams();
  if (params?.role) query.set("role", params.role);
  if (params?.send_mode) query.set("send_mode", params.send_mode);
  if (params?.is_active !== undefined) query.set("is_active", String(params.is_active));
  if (params?.search) query.set("search", params.search);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));

  const url = `${API_BASE_URL}/api/groups?${query.toString()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Lỗi khi lấy danh sách Nhóm Zalo: HTTP ${res.status}`);
  }
  return res.json();
}

export async function updateGroupSendMode(
  groupId: number,
  sendMode: "tu_dong" | "cho_duyet"
): Promise<{ ok: boolean; message: string; group_id: number; zalo_group_id: string; send_mode: string; send_mode_label: string }> {
  const url = `${API_BASE_URL}/api/groups/${groupId}/send-mode`;
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ send_mode: sendMode }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi cập nhật trạng thái nhóm #${groupId}`);
  }
  return res.json();
}

export async function updateRealGroupStatus(
  groupId: number,
  payload: {
    send_mode?: string;
    is_active?: boolean;
    name?: string;
    group_role?: string;
    carrier_id?: string;
    carrier_name?: string;
    is_test?: boolean;
  }
): Promise<{ ok: boolean; message: string; group: ZaloGroupItem }> {
  const url = `${API_BASE_URL}/api/groups/${groupId}/status`;
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi cập nhật trạng thái nhóm #${groupId}`);
  }
  return res.json();
}

export async function updateRealGroupStatusByZaloId(
  zaloGroupId: string,
  payload: {
    send_mode?: string;
    is_active?: boolean;
    name?: string;
    group_role?: string;
    carrier_id?: string;
    carrier_name?: string;
  }
): Promise<{ ok: boolean; message: string; group: ZaloGroupItem }> {
  const url = `${API_BASE_URL}/api/groups/by-zalo-id/${encodeURIComponent(zaloGroupId)}/status`;
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi cập nhật nhóm Zalo ${zaloGroupId}`);
  }
  return res.json();
}

export async function deleteAllTestGroups(): Promise<{
  ok: boolean;
  message: string;
  deleted_count: number;
  deleted_groups: string[];
  remaining_real_groups: ZaloGroupItem[];
}> {
  const url = `${API_BASE_URL}/api/groups/test-groups`;
  const res = await fetch(url, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Lỗi khi xóa nhóm test");
  }
  return res.json();
}

export async function deleteGroup(
  groupId: number
): Promise<{ ok: boolean; message: string; deleted_id: number }> {
  const url = `${API_BASE_URL}/api/groups/${groupId}`;
  const res = await fetch(url, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Lỗi khi xóa nhóm #${groupId}`);
  }
  return res.json();
}

export async function createGroup(payload: Partial<ZaloGroupItem>): Promise<{ ok: boolean; message: string; group: ZaloGroupItem }> {
  const url = `${API_BASE_URL}/api/groups`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Lỗi khi tạo nhóm Zalo mới");
  }
  return res.json();
}



