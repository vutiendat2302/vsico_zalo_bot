import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadRootEnv } from "./env_loader.js";

loadRootEnv();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_ENV_FILE = path.resolve(__dirname, "../.env");
const ZALO_OAUTH_URL = "https://oauth.zaloapp.com/v4/oa/access_token";

let refreshInFlight = null;
let cachedExpiresAt = Number(process.env.ZALO_OA_TOKEN_EXPIRES_AT || 0);

/**
 * Đọc cặp `access_token` và `refresh_token` hiện tại từ biến môi trường (nạp từ `.env` gốc).
 *
 * @returns {{ access_token: string, refresh_token: string, expires_at: number }}
 */
export function loadTokens() {
  return {
    access_token: (process.env.ZALO_OA_ACCESS_TOKEN || "").trim(),
    refresh_token: (process.env.ZALO_OA_REFRESH_TOKEN || "").trim(),
    expires_at: cachedExpiresAt,
  };
}

/**
 * Cập nhật một khóa cấu hình trong tệp `.env` tại thư mục gốc (hoặc nối thêm nếu chưa tồn tại).
 *
 * @param {string} envContent Nội dung hiện tại của tệp `.env`.
 * @param {string} key Tên biến môi trường.
 * @param {string} value Giá trị mới.
 * @returns {string}
 */
function upsertEnvLine(envContent, key, value) {
  const lineBreak = envContent.includes("\r\n") ? "\r\n" : "\n";
  const regex = new RegExp(`^${key}=.*$`, "m");
  const nextLine = `${key}=${value}`;
  if (regex.test(envContent)) {
    return envContent.replace(regex, nextLine);
  }
  const suffix = envContent.endsWith("\n") || envContent === "" ? "" : lineBreak;
  return `${envContent}${suffix}${nextLine}${lineBreak}`;
}

/**
 * Lưu đè cặp `access_token` và `refresh_token` mới nhất vào `process.env` và tệp `.env` gốc.
 *
 * @param {{ access_token: string, refresh_token: string, expires_at?: number }} tokenData
 */
export function saveTokens(tokenData) {
  const accessToken = String(tokenData.access_token || "").trim();
  const refreshToken = String(tokenData.refresh_token || "").trim();
  const expiresAt = Number(tokenData.expires_at || 0);

  process.env.ZALO_OA_ACCESS_TOKEN = accessToken;
  process.env.ZALO_OA_REFRESH_TOKEN = refreshToken;
  process.env.ZALO_OA_TOKEN_EXPIRES_AT = String(expiresAt);
  cachedExpiresAt = expiresAt;

  let content = fs.existsSync(ROOT_ENV_FILE)
    ? fs.readFileSync(ROOT_ENV_FILE, "utf-8")
    : "";
  content = upsertEnvLine(content, "ZALO_OA_ACCESS_TOKEN", accessToken);
  content = upsertEnvLine(content, "ZALO_OA_REFRESH_TOKEN", refreshToken);
  content = upsertEnvLine(content, "ZALO_OA_TOKEN_EXPIRES_AT", String(expiresAt));
  fs.writeFileSync(ROOT_ENV_FILE, content, "utf-8");
}

/**
 * Trả về `access_token` hợp lệ; tự động làm mới nếu đã gần hết hạn (trước 5 phút).
 *
 * @returns {Promise<string>}
 */
export async function getAccessToken() {
  const current = loadTokens();
  const fiveMinutesMs = 5 * 60 * 1000;

  if (
    current.access_token &&
    (!current.expires_at || Date.now() + fiveMinutesMs < current.expires_at)
  ) {
    return current.access_token;
  }

  if (current.refresh_token) {
    return refreshAccessToken();
  }

  if (!current.access_token) {
    throw new Error("Thiếu ZALO_OA_ACCESS_TOKEN và ZALO_OA_REFRESH_TOKEN trong .env");
  }
  return current.access_token;
}

/**
 * Gọi Zalo OAuth v4 để đổi `refresh_token` lấy cặp token mới và lưu đè vào `.env` gốc.
 * Có khóa đồng bộ (`refreshInFlight`) để tránh nhiều request cùng làm mới một lúc.
 *
 * @returns {Promise<string>}
 */
export async function refreshAccessToken() {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  refreshInFlight = (async () => {
    const appId = (process.env.ZALO_OA_APP_ID || "").trim();
    const appSecret = (process.env.ZALO_OA_APP_SECRET || "").trim();
    const current = loadTokens();

    if (!appId || !appSecret || !current.refresh_token) {
      throw new Error("Thiếu ZALO_OA_APP_ID, ZALO_OA_APP_SECRET hoặc ZALO_OA_REFRESH_TOKEN để làm mới token");
    }

    const body = new URLSearchParams({
      refresh_token: current.refresh_token,
      app_id: appId,
      grant_type: "refresh_token",
    });

    const resp = await fetch(ZALO_OAUTH_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        secret_key: appSecret,
      },
      body: body.toString(),
    });

    const data = await resp.json();
    if (!resp.ok || !data.access_token) {
      throw new Error(
        `Làm mới Zalo OA token thất bại: ${JSON.stringify(data)}`
      );
    }

    const expiresInSec = Number(data.expires_in || 90000);
    const nextTokens = {
      access_token: data.access_token,
      refresh_token: data.refresh_token || current.refresh_token,
      expires_at: Date.now() + expiresInSec * 1000,
    };
    saveTokens(nextTokens);
    console.log(`[OA_TOKEN] Đã làm mới access_token và cập nhật .env (hết hạn sau ${expiresInSec}s).`);
    return nextTokens.access_token;
  })();

  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}
