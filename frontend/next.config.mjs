import fs from "node:fs";
import path from "node:path";

/**
 * Nạp biến môi trường công khai (NEXT_PUBLIC_*) từ tệp .env tập trung ở thư mục gốc.
 * Chỉ dùng giá trị trong ../.env khi biến chưa được truyền sẵn qua môi trường build/runtime.
 */
function loadRootPublicEnv() {
  const rootEnvPath = path.resolve(process.cwd(), "..", ".env");
  const result = {};
  if (fs.existsSync(rootEnvPath)) {
    const raw = fs.readFileSync(rootEnvPath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx <= 0) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      if (!key.startsWith("NEXT_PUBLIC_")) continue;
      let val = trimmed.slice(eqIdx + 1).trim();
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1);
      }
      result[key] = val;
    }
  }
  if (process.env.NEXT_PUBLIC_API_URL) {
    result.NEXT_PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL;
  }
  return result;
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  env: loadRootPublicEnv(),
};

export default nextConfig;
