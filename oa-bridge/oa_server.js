import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { loadRootEnv } from "./env_loader.js";
import {
  getConversationMessages,
  getFollowers,
  getGroupConversation,
  getGroupInfo,
  getGroupMembers,
  getGroupsOfOa,
  getOaInfo,
  getRecentChats,
  getUserDetail,
  sendGroupMessage,
  sendTextMessage,
} from "./oa_client.js";

loadRootEnv();

const PORT = Number(process.env.OA_BRIDGE_PORT || process.env.BOT_API_PORT || 3000);
const BACKEND_WEBHOOK_URL = (
  process.env.BACKEND_WEBHOOK_URL || "http://localhost:8000/webhook"
).trim();
const OA_SECRET_KEY = (process.env.ZALO_OA_SECRET_KEY || "").trim();
const VERIFY_SIGNATURE =
  String(process.env.ZALO_OA_VERIFY_SIGNATURE || "true").toLowerCase() !== "false";

const MAX_REALTIME_CACHE = 200;
const realtimeMessages = [];

/**
 * Lưu một tin nhắn mới nhận qua Webhook vào bộ nhớ đệm RAM để phục vụ tra cứu realtime.
 *
 * @param {any} mappedPayload Payload đã chuẩn hóa theo `ZcaWebhookPayload`.
 */
function pushRealtimeCache(mappedPayload) {
  const senderId = String(mappedPayload?.sender?.id || "");
  const groupId = String(mappedPayload?.group_id || "") || (senderId ? `direct_${senderId}` : "");
  realtimeMessages.unshift({
    groupId,
    senderId,
    senderName: mappedPayload?.sender?.name || null,
    msgId: mappedPayload?.message?.msg_id || null,
    text: mappedPayload?.message?.text || "",
    imageUrl: mappedPayload?.image_url || null,
    eventName: mappedPayload?.event_name || "user_send_text",
    timestamp: mappedPayload?.timestamp || Date.now(),
  });
  if (realtimeMessages.length > MAX_REALTIME_CACHE) {
    realtimeMessages.length = MAX_REALTIME_CACHE;
  }
}

/**
 * Tách `userId` từ `groupId` dạng `direct_<userId>` hoặc trả về `null` nếu là nhóm GMF.
 *
 * @param {string} groupId
 * @returns {string | null}
 */
function extractDirectUserId(groupId) {
  const raw = String(groupId || "").trim();
  return raw.startsWith("direct_") ? raw.slice("direct_".length) : null;
}

/**
 * Đọc toàn bộ body thô từ HTTP request.
 *
 * @param {http.IncomingMessage} req
 * @returns {Promise<string>}
 */
function readRawBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    req.on("error", reject);
  });
}

/**
 * Trả phản hồi JSON chuẩn hóa cho client.
 *
 * @param {http.ServerResponse} res
 * @param {number} statusCode
 * @param {any} data
 */
function sendJson(res, statusCode, data) {
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(data));
}

/**
 * Kiểm tra chữ ký `X-ZEvent-Signature` của Zalo OA Webhook (`sha256(app_id + rawBody + timestamp + OA_SECRET_KEY)`).
 *
 * @param {string} signatureHeader Giá trị header `X-ZEvent-Signature`.
 * @param {string} rawBody Chuỗi JSON nguyên bản.
 * @param {any} parsedBody Đối tượng JSON đã parse.
 * @returns {boolean}
 */
function verifyZaloOaSignature(signatureHeader, rawBody, parsedBody) {
  if (!VERIFY_SIGNATURE || !OA_SECRET_KEY) {
    return true;
  }
  if (!signatureHeader) {
    return false;
  }

  const receivedHex = String(signatureHeader).replace(/^mac=/i, "").trim().toLowerCase();
  const appId = String(parsedBody?.app_id || process.env.ZALO_OA_APP_ID || "");
  const timestamp = String(parsedBody?.timestamp || "");

  const rawConcat = `${appId}${rawBody}${timestamp}${OA_SECRET_KEY}`;
  const expectedHex = crypto.createHash("sha256").update(rawConcat, "utf-8").digest("hex");

  return (
    receivedHex.length === expectedHex.length &&
    crypto.timingSafeEqual(Buffer.from(receivedHex), Buffer.from(expectedHex))
  );
}

/**
 * Chuyển đổi sự kiện Webhook từ Zalo OA (1-1 hoặc nhóm GMF) sang cấu trúc `ZcaWebhookPayload` của Backend VSICO.
 *
 * @param {any} oaEvent Payload gốc từ Zalo OA.
 * @returns {Promise<any>}
 */
async function mapOaEventToBackendPayload(oaEvent) {
  const senderId = String(oaEvent?.sender?.id || "").trim();
  const rawEventName = String(oaEvent?.event_name || "").trim();
  const oaId = String(oaEvent?.oa_id || "").trim();
  const recipientId = String(oaEvent?.recipient?.id || "").trim();
  const groupId = String(
    oaEvent?.group_id ||
      oaEvent?.recipient?.group_id ||
      oaEvent?.message?.group_id ||
      (rawEventName.includes("_group_") && recipientId && recipientId !== oaId ? recipientId : "")
  ).trim();
  const attachments = oaEvent?.message?.attachments || [];
  const firstImage = attachments.find((item) => item?.type === "image");
  const imageUrl = firstImage?.payload?.url || null;

  let senderName = oaEvent?.sender?.name || null;
  if (!senderName && senderId) {
    try {
      const detail = await getUserDetail(senderId);
      senderName = detail?.display_name || null;
    } catch {
      // Không chặn luồng nhận tin nếu lấy tên người dùng thất bại
    }
  }

  return {
    app_id: String(oaEvent?.app_id || process.env.ZALO_OA_APP_ID || "zalo_oa_bot"),
    event_name: oaEvent?.event_name || "user_send_text",
    group_id: groupId,
    group_name: oaEvent?.group_name || null,
    sender: {
      id: senderId,
      ...(senderName ? { name: senderName } : {}),
    },
    timestamp: oaEvent?.timestamp || Date.now(),
    quote_msg_id: oaEvent?.message?.quote_msg_id || null,
    message: oaEvent?.message || {},
    image_url: imageUrl,
    attachments: attachments.length > 0 ? attachments : null,
    raw_payload: oaEvent,
  };
}

/**
 * Chuyển tiếp payload đã chuẩn hóa sang cổng `POST /webhook` của Backend FastAPI.
 *
 * @param {any} payload
 * @returns {Promise<{ ok: boolean, status: number, body: string }>}
 */
async function forwardToBackend(payload) {
  const headers = {
    "Content-Type": "application/json; charset=utf-8",
    "User-Agent": "VSICO-OA-Bridge/1.0",
  };
  const webhookSecret = (process.env.ZALO_SECRET_KEY || "").trim();
  if (webhookSecret) {
    headers["x-webhook-secret"] = webhookSecret;
  }
  const resp = await fetch(BACKEND_WEBHOOK_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  const body = await resp.text();
  return { ok: resp.ok, status: resp.status, body };
}

const server = http.createServer(async (req, res) => {
  const parsedUrl = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  const pathname = parsedUrl.pathname;
  const method = req.method || "GET";

  try {
    // 0. Phục vụ tệp HTML xác thực domain Zalo (`GET /zalo_verifier*.html`)
    if (method === "GET" && /^\/zalo_verifier[A-Za-z0-9_-]+\.html$/.test(pathname)) {
      const fileName = path.basename(pathname);
      const candidates = [path.resolve(".", fileName), path.resolve("..", fileName)];
      const matchedPath = candidates.find((p) => fs.existsSync(p));
      if (matchedPath) {
        const html = fs.readFileSync(matchedPath, "utf-8");
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(html);
        return;
      }
    }

    // 1. Kiểm tra sức khỏe Bridge & trạng thái kết nối Zalo OA
    if (
      method === "GET" &&
      (pathname === "/health" || pathname === "/api/health" || pathname === "/api/bot/status")
    ) {
      const oaCheck = await getOaInfo().catch((err) => ({ ok: false, error: err.message }));
      return sendJson(res, oaCheck.ok ? 200 : 502, {
        ok: oaCheck.ok,
        bridge: "oa-bridge",
        oa_id: process.env.ZALO_OA_ID || null,
        oa_info: oaCheck.ok ? oaCheck.data : null,
        error: oaCheck.ok ? null : oaCheck.error,
      });
    }

    // 2. Endpoint test nhanh kết nối thực tế với Zalo OA
    if (method === "GET" && pathname === "/api/oa/test-connection") {
      const oaCheck = await getOaInfo();
      return sendJson(res, oaCheck.ok ? 200 : 502, oaCheck);
    }

    // 3. GET /api/bot/groups — Lấy danh sách nhóm GMF thật của OA + hội thoại 1-1 gần nhất
    if (method === "GET" && pathname === "/api/bot/groups") {
      const count = Number(parsedUrl.searchParams.get("count") || 20);
      const offset = Number(parsedUrl.searchParams.get("offset") || 0);
      const includeDirect = parsedUrl.searchParams.get("includeDirect") !== "false";

      const gmfRes = await getGroupsOfOa(offset, count);
      const groupMap = new Map();

      for (const g of gmfRes.groups || []) {
        if (g?.group_id) {
          groupMap.set(String(g.group_id), {
            ...g,
            type: "gmf",
          });
        }
      }

      if (includeDirect) {
        const recent = await getRecentChats(0, 10);
        for (const msg of recent.messages || []) {
          const uid = String(msg?.from_id === process.env.ZALO_OA_ID ? msg?.to_id : msg?.from_id || "");
          if (uid && !groupMap.has(`direct_${uid}`)) {
            groupMap.set(`direct_${uid}`, {
              group_id: `direct_${uid}`,
              userId: uid,
              name: msg?.from_display_name || msg?.to_display_name || `User ${uid}`,
              type: "oa_direct",
              lastMessage: msg?.message || "",
              timestamp: msg?.time || null,
            });
          }
        }
      }

      const groups = Array.from(groupMap.values());
      return sendJson(res, 200, {
        ok: gmfRes.ok || groups.length > 0,
        total: groups.length,
        groupIds: groups.map((g) => g.group_id),
        groups,
        error: gmfRes.ok ? null : gmfRes.error,
      });
    }

    // 4. GET /api/bot/groups/:groupId/info — Chi tiết nhóm GMF hoặc hội thoại 1-1
    const groupInfoMatch = pathname.match(/^\/api\/bot\/groups\/([^/]+)\/info$/);
    if (method === "GET" && groupInfoMatch) {
      const groupId = decodeURIComponent(groupInfoMatch[1]);
      const directUserId = extractDirectUserId(groupId);

      if (directUserId) {
        const detail = await getUserDetail(directUserId);
        if (!detail) {
          return sendJson(res, 404, { ok: false, error: `Không tìm thấy người dùng ${directUserId}` });
        }
        return sendJson(res, 200, {
          ok: true,
          groupId,
          type: "oa_direct",
          name: detail.display_name || `User ${directUserId}`,
          members: [detail],
        });
      }

      const [infoRes, membersRes] = await Promise.all([
        getGroupInfo(groupId),
        getGroupMembers(groupId, 0, 50),
      ]);
      if (!infoRes.ok) {
        return sendJson(res, 502, { ok: false, error: infoRes.error, raw: infoRes.raw });
      }
      return sendJson(res, 200, {
        ok: true,
        groupId,
        type: "gmf",
        group: infoRes.group,
        members: membersRes.ok ? membersRes.members : [],
        totalMembers: membersRes.ok
          ? membersRes.total
          : infoRes.group?.group_info?.total_member ?? infoRes.group?.total_member ?? 0,
        ...(membersRes.ok ? {} : { membersError: membersRes.error }),
      });
    }

    // 4b. GET /api/bot/groups/:groupId/members — Lấy danh sách thành viên theo groupId
    const groupMembersMatch = pathname.match(/^\/api\/bot\/groups\/([^/]+)\/members$/);
    if (method === "GET" && groupMembersMatch) {
      const groupId = decodeURIComponent(groupMembersMatch[1]);
      const offset = Number(parsedUrl.searchParams.get("offset") || 0);
      const count = Number(parsedUrl.searchParams.get("count") || 50);
      const directUserId = extractDirectUserId(groupId);

      if (directUserId) {
        const detail = await getUserDetail(directUserId);
        if (!detail) {
          return sendJson(res, 404, { ok: false, error: `Không tìm thấy người dùng ${directUserId}` });
        }
        return sendJson(res, 200, {
          ok: true,
          groupId,
          type: "oa_direct",
          total: 1,
          offset: 0,
          count: 1,
          members: [detail],
        });
      }

      const membersRes = await getGroupMembers(groupId, offset, count);
      if (!membersRes.ok) {
        return sendJson(res, 502, {
          ok: false,
          groupId,
          type: "gmf",
          total: 0,
          members: [],
          error: membersRes.error,
        });
      }
      return sendJson(res, 200, {
        ok: true,
        groupId,
        type: "gmf",
        total: membersRes.total,
        offset,
        count: membersRes.members.length,
        members: membersRes.members,
      });
    }

    // 5. GET /api/bot/users — Danh sách người dùng đang quan tâm OA
    if (method === "GET" && pathname === "/api/bot/users") {
      const count = Number(parsedUrl.searchParams.get("count") || 50);
      const offset = Number(parsedUrl.searchParams.get("offset") || 0);
      const listRes = await getFollowers(offset, count);
      if (!listRes.ok) {
        return sendJson(res, 502, { ok: false, error: listRes.error });
      }
      return sendJson(res, 200, {
        ok: true,
        total: listRes.total,
        userIds: listRes.users.map((u) => u.user_id),
        users: listRes.users,
      });
    }

    // 6. GET /api/bot/users/:userId — Chi tiết một người dùng OA
    const userInfoMatch = pathname.match(/^\/api\/bot\/users\/([^/]+)$/);
    if (method === "GET" && userInfoMatch) {
      const userId = decodeURIComponent(userInfoMatch[1]);
      const detail = await getUserDetail(userId);
      if (!detail) {
        return sendJson(res, 404, { ok: false, error: `Không tìm thấy userId=${userId}` });
      }
      return sendJson(res, 200, { ok: true, user: detail });
    }

    // 7. GET /api/bot/groups/:groupId/messages — Lịch sử tin nhắn nhóm GMF hoặc hội thoại 1-1
    const groupMsgsMatch = pathname.match(/^\/api\/bot\/groups\/([^/]+)\/messages$/);
    if (method === "GET" && groupMsgsMatch) {
      const groupId = decodeURIComponent(groupMsgsMatch[1]);
      const directUserId = extractDirectUserId(groupId);
      const count = Number(parsedUrl.searchParams.get("count") || 20);
      const offset = Number(parsedUrl.searchParams.get("offset") || 0);

      const conv = directUserId
        ? await getConversationMessages(directUserId, offset, Math.min(count, 10))
        : await getGroupConversation(groupId, offset, count);

      const cached = realtimeMessages.filter(
        (m) => m.groupId === groupId || (directUserId && m.senderId === directUserId)
      );
      return sendJson(res, 200, {
        ok: conv.ok || cached.length > 0,
        groupId,
        type: directUserId ? "oa_direct" : "gmf",
        messages: conv.ok ? conv.messages : cached,
        realtimeFallback: !conv.ok ? cached : undefined,
        error: conv.ok ? null : conv.error,
      });
    }

    // 8. GET /api/bot/groups/:groupId/users/:userId/messages — Lọc tin nhắn theo userId trong nhóm
    const groupUserMsgsMatch = pathname.match(
      /^\/api\/bot\/groups\/([^/]+)\/users\/([^/]+)\/messages$/
    );
    if (method === "GET" && groupUserMsgsMatch) {
      const groupId = decodeURIComponent(groupUserMsgsMatch[1]);
      const userId = decodeURIComponent(groupUserMsgsMatch[2]);
      const directUserId = extractDirectUserId(groupId);
      const count = Number(parsedUrl.searchParams.get("count") || 20);
      const offset = Number(parsedUrl.searchParams.get("offset") || 0);

      const conv = directUserId
        ? await getConversationMessages(directUserId, offset, Math.min(count, 10))
        : await getGroupConversation(groupId, offset, count);

      const filtered = (conv.messages || []).filter(
        (m) => String(m?.from_id || m?.sender_id || "") === String(userId)
      );
      return sendJson(res, 200, {
        ok: conv.ok,
        groupId,
        userId,
        messages: filtered,
        error: conv.ok ? null : conv.error,
      });
    }

    // 9. GET /api/bot/realtime/messages & POST /api/bot/realtime/clear
    if (method === "GET" && pathname === "/api/bot/realtime/messages") {
      const limit = Number(parsedUrl.searchParams.get("limit") || 20);
      return sendJson(res, 200, {
        ok: true,
        total: realtimeMessages.length,
        messages: realtimeMessages.slice(0, limit),
      });
    }

    if (method === "POST" && pathname === "/api/bot/realtime/clear") {
      realtimeMessages.length = 0;
      return sendJson(res, 200, { ok: true, message: "Đã xóa bộ nhớ đệm realtime" });
    }

    // 10. Zalo OA Webhook verification (GET ping)
    if (method === "GET" && pathname === "/webhook/zalo-oa") {
      return sendJson(res, 200, { ok: true, service: "vsico-oa-bridge" });
    }

    // 11. Tiếp nhận sự kiện Webhook từ Zalo OA (1-1 và GMF), lưu cache và đẩy sang Backend
    if (method === "POST" && pathname === "/webhook/zalo-oa") {
      const rawBody = await readRawBody(req);
      const oaEvent = rawBody ? JSON.parse(rawBody) : {};
      const sig = req.headers["x-zevent-signature"];

      if (!verifyZaloOaSignature(sig, rawBody, oaEvent)) {
        console.warn("[OA_WEBHOOK] Từ chối request sai chữ ký X-ZEvent-Signature");
        return sendJson(res, 401, { ok: false, error: "Invalid X-ZEvent-Signature" });
      }

      const eventName = oaEvent?.event_name || "";
      console.log(`[OA_WEBHOOK] Nhận sự kiện: ${eventName} từ sender=${oaEvent?.sender?.id || "?"}`);

      if (eventName.startsWith("user_send_")) {
        const mapped = await mapOaEventToBackendPayload(oaEvent);
        pushRealtimeCache(mapped);
        const forwarded = await forwardToBackend(mapped);
        if (!forwarded.ok) {
          console.error(`[OA_WEBHOOK] Lỗi forward sang Backend (${forwarded.status}): ${forwarded.body}`);
        }
      }

      return sendJson(res, 200, { ok: true });
    }

    // 12. POST /api/bot/send/user — Gửi tin nhắn 1-1 cho User (tương thích ZaloDispatcher.send_to_user)
    if (method === "POST" && pathname === "/api/bot/send/user") {
      const rawBody = await readRawBody(req);
      const body = rawBody ? JSON.parse(rawBody) : {};
      const { userId, message, quoteMsgId } = body;

      if (!userId || !message) {
        return sendJson(res, 400, { ok: false, error: "Thiếu userId hoặc message" });
      }

      const result = await sendTextMessage(userId, message, quoteMsgId || null);
      if (!result.ok) {
        return sendJson(res, 502, { ok: false, error: result.error, raw: result.raw });
      }

      return sendJson(res, 200, {
        ok: true,
        result: { message: { msgId: result.msgId } },
      });
    }

    // 13. POST /api/bot/send/group — Gửi tin nhắn vào nhóm GMF hoặc direct_<user_id>
    if (method === "POST" && pathname === "/api/bot/send/group") {
      const rawBody = await readRawBody(req);
      const body = rawBody ? JSON.parse(rawBody) : {};
      const { groupId, message, quoteMsgId } = body;

      if (!groupId || !message) {
        return sendJson(res, 400, { ok: false, error: "Thiếu groupId hoặc message" });
      }

      const normalizedGroupId = String(groupId).trim();
      const directUserId = extractDirectUserId(normalizedGroupId);
      const result = directUserId
        ? await sendTextMessage(directUserId, message, quoteMsgId || null)
        : await sendGroupMessage(normalizedGroupId, message, quoteMsgId || null);

      if (!result.ok) {
        return sendJson(res, 502, { ok: false, error: result.error, raw: result.raw });
      }

      return sendJson(res, 200, {
        ok: true,
        result: { message: { msgId: result.msgId } },
      });
    }

    return sendJson(res, 404, { ok: false, error: "Endpoint không tồn tại" });
  } catch (err) {
    console.error("[OA_BRIDGE_ERR]", err);
    return sendJson(res, 500, { ok: false, error: err.message || "Internal Server Error" });
  }
});

server.listen(PORT, () => {
  console.log(`[OA_BRIDGE] Đang lắng nghe tại http://localhost:${PORT}`);
  console.log(`[OA_BRIDGE] Backend Webhook đích: ${BACKEND_WEBHOOK_URL}`);
  getOaInfo()
    .then((res) => {
      if (res.ok) {
        console.log(`[OA_BRIDGE] Kết nối Zalo OA thành công: ${res.data?.name} (ID: ${res.data?.oa_id})`);
      } else {
        console.warn(`[OA_BRIDGE] Cảnh báo kiểm tra Zalo OA thất bại: ${res.error}`);
      }
    })
    .catch((err) => {
      console.warn(`[OA_BRIDGE] Lỗi kết nối Zalo OA lúc khởi động: ${err.message}`);
    });
});
