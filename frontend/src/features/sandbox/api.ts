import { getAuthToken } from "@/lib/auth";
import type {
  SandboxContextOptions,
  SandboxSimulateRequest,
  SandboxSimulateResponse,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiErrorPayload {
  message?: string;
  detail?: string;
}

/**
 * Tạo headers chuẩn cho request Backend kèm Bearer token từ cookie phiên đăng nhập.
 */
function buildHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Trích xuất thông điệp lỗi dễ đọc từ phản hồi chuẩn hóa của Backend.
 */
async function extractErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorPayload;
    return body.message || body.detail || `${fallback} (HTTP ${res.status})`;
  } catch {
    return `${fallback} (HTTP ${res.status})`;
  }
}

/**
 * Tải danh sách nhà xe và một số kế hoạch mẫu thật từ MySQL (chỉ đọc) để chọn ngữ cảnh test.
 */
export async function fetchSandboxContextOptions(): Promise<SandboxContextOptions> {
  const res = await fetch(`${API_BASE_URL}/api/sandbox/context-options`, {
    method: "GET",
    headers: buildHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(
      await extractErrorMessage(res, "Không thể tải tùy chọn bối cảnh từ máy chủ")
    );
  }
  return (await res.json()) as SandboxContextOptions;
}

/**
 * Gửi tin nhắn/ảnh và ngữ cảnh hội thoại giả lập sang Backend để kiểm thử thuật toán (0% ghi DB).
 */
export async function simulateSandboxPipeline(
  payload: SandboxSimulateRequest
): Promise<SandboxSimulateResponse> {
  const res = await fetch(`${API_BASE_URL}/api/sandbox/simulate`, {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(
      await extractErrorMessage(res, "Không thể chạy mô phỏng thuật toán")
    );
  }
  return (await res.json()) as SandboxSimulateResponse;
}
