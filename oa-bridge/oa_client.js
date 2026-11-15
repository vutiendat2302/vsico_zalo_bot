import { getAccessToken, refreshAccessToken } from "./token_manager.js";

const ZALO_OA_INFO_URL = "https://openapi.zalo.me/v2.0/oa/getoa";
const ZALO_OA_SEND_CS_URL = "https://openapi.zalo.me/v3.0/oa/message/cs";
const ZALO_OA_USER_DETAIL_URL = "https://openapi.zalo.me/v3.0/oa/user/detail";
const ZALO_OA_USER_LIST_URL = "https://openapi.zalo.me/v3.0/oa/user/getlist";
const ZALO_OA_LIST_RECENT_CHAT_URL = "https://openapi.zalo.me/v2.0/oa/listrecentchat";
const ZALO_OA_CONVERSATION_URL = "https://openapi.zalo.me/v2.0/oa/conversation";

// Nhóm endpoint GMF (Zalo OA Group Chat v3)
const ZALO_OA_GROUP_LIST_URL = "https://openapi.zalo.me/v3.0/oa/group/getgroupsofoa";
const ZALO_OA_GROUP_INFO_URL = "https://openapi.zalo.me/v3.0/oa/group/getgroup";
const ZALO_OA_GROUP_MEMBERS_URL = "https://openapi.zalo.me/v3.0/oa/group/listmember";
const ZALO_OA_GROUP_CONVERSATION_URL = "https://openapi.zalo.me/v3.0/oa/group/conversation";
const ZALO_OA_GROUP_MESSAGE_URL = "https://openapi.zalo.me/v3.0/oa/group/message";

const TOKEN_EXPIRED_CODES = new Set([-216, -124]);

/**
 * Thực thi lời gọi API tới máy chủ Zalo OpenAPI và tự động làm mới token nếu bị báo hết hạn.
 *
 * @param {string} url Đường dẫn API Zalo OpenAPI.
 * @param {RequestInit} options Cấu hình fetch (method, body...).
 * @returns {Promise<any>}
 */
async function callZaloApi(url, options = {}) {
  let token = await getAccessToken();

  const doFetch = async (accessToken) => {
    const resp = await fetch(url, {
      ...options,
      headers: {
        ...(options.headers || {}),
        access_token: accessToken,
      },
    });
    return resp.json();
  };

  let data = await doFetch(token);
  if (TOKEN_EXPIRED_CODES.has(Number(data?.error))) {
    console.warn(`[OA_API] Access token hết hạn (error=${data.error}), đang tự động refresh...`);
    token = await refreshAccessToken();
    data = await doFetch(token);
  }
  return data;
}

/**
 * Kiểm tra kết nối và lấy thông tin cơ bản của Official Account từ Zalo.
 *
 * @returns {Promise<{ ok: boolean, error?: string, data?: any }>}
 */
export async function getOaInfo() {
  const data = await callZaloApi(ZALO_OA_INFO_URL, { method: "GET" });
  if (Number(data?.error) !== 0) {
    return {
      ok: false,
      error: data?.message || `Zalo OA error ${data?.error}`,
      data,
    };
  }
  return { ok: true, data: data.data };
}

/**
 * Gửi tin nhắn văn bản tư vấn (1-1) tới người dùng qua Zalo OA API v3.
 *
 * @param {string} userId Mã người dùng OA (`user_id`).
 * @param {string} text Nội dung tin nhắn văn bản.
 * @param {string | null} quoteMsgId Mã tin nhắn cần trích dẫn (nếu có).
 * @returns {Promise<{ ok: boolean, msgId?: string, error?: string, raw?: any }>}
 */
export async function sendTextMessage(userId, text, quoteMsgId = null) {
  const payload = {
    recipient: { user_id: String(userId).trim() },
    message: { text: String(text) },
  };
  if (quoteMsgId) {
    payload.message.quote_message_id = String(quoteMsgId).trim();
  }

  const data = await callZaloApi(ZALO_OA_SEND_CS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (Number(data?.error) !== 0) {
    return {
      ok: false,
      error: data?.message || `Zalo OA error ${data?.error}`,
      raw: data,
    };
  }

  return {
    ok: true,
    msgId: data?.data?.message_id || null,
    raw: data,
  };
}

/**
 * Truy vấn thông tin hiển thị của người dùng đã tương tác với Zalo OA.
 *
 * @param {string} userId Mã người dùng OA.
 * @returns {Promise<any>}
 */
export async function getUserDetail(userId) {
  const query = encodeURIComponent(JSON.stringify({ user_id: String(userId).trim() }));
  const data = await callZaloApi(`${ZALO_OA_USER_DETAIL_URL}?data=${query}`, {
    method: "GET",
  });
  return Number(data?.error) === 0 ? data.data : null;
}

/**
 * Lấy danh sách người dùng đang quan tâm (follower) Zalo OA.
 *
 * @param {number} offset Vị trí bắt đầu phân trang.
 * @param {number} count Số lượng bản ghi tối đa (tối đa 50/lần theo spec Zalo OA).
 * @returns {Promise<{ ok: boolean, total: number, users: Array<{ user_id: string }>, error?: string }>}
 */
export async function getFollowers(offset = 0, count = 50) {
  const safeCount = Math.min(Math.max(Number(count) || 50, 1), 50);
  const query = encodeURIComponent(JSON.stringify({ offset: Number(offset) || 0, count: safeCount }));
  const data = await callZaloApi(`${ZALO_OA_USER_LIST_URL}?data=${query}`, {
    method: "GET",
  });
  if (Number(data?.error) !== 0) {
    return { ok: false, total: 0, users: [], error: data?.message || `Zalo OA error ${data?.error}` };
  }
  return {
    ok: true,
    total: Number(data?.data?.total || 0),
    users: data?.data?.users || [],
  };
}

/**
 * Lấy danh sách các hội thoại 1-1 gần nhất với Zalo OA.
 *
 * @param {number} offset Vị trí bắt đầu.
 * @param {number} count Số lượng hội thoại (tối đa 10 theo API Zalo OA v2).
 * @returns {Promise<{ ok: boolean, messages: any[], error?: string }>}
 */
export async function getRecentChats(offset = 0, count = 10) {
  const safeCount = Math.min(Math.max(Number(count) || 10, 1), 10);
  const query = encodeURIComponent(JSON.stringify({ offset: Number(offset) || 0, count: safeCount }));
  const data = await callZaloApi(`${ZALO_OA_LIST_RECENT_CHAT_URL}?data=${query}`, {
    method: "GET",
  });
  if (Number(data?.error) !== 0) {
    return { ok: false, messages: [], error: data?.message || `Zalo OA error ${data?.error}` };
  }
  return { ok: true, messages: data?.data || [] };
}

/**
 * Lấy lịch sử tin nhắn trong hội thoại 1-1 giữa Zalo OA và một `userId`.
 *
 * @param {string} userId Mã người dùng OA.
 * @param {number} offset Vị trí bắt đầu.
 * @param {number} count Số lượng tin nhắn (tối đa 10 theo API Zalo OA v2).
 * @returns {Promise<{ ok: boolean, messages: any[], error?: string }>}
 */
export async function getConversationMessages(userId, offset = 0, count = 10) {
  const safeCount = Math.min(Math.max(Number(count) || 10, 1), 10);
  const query = encodeURIComponent(
    JSON.stringify({
      user_id: String(userId).trim(),
      offset: Number(offset) || 0,
      count: safeCount,
    })
  );
  const data = await callZaloApi(`${ZALO_OA_CONVERSATION_URL}?data=${query}`, {
    method: "GET",
  });
  if (Number(data?.error) !== 0) {
    return { ok: false, messages: [], error: data?.message || `Zalo OA error ${data?.error}` };
  }
  return { ok: true, messages: data?.data || [] };
}

/**
 * Lấy danh sách nhóm chat GMF mà Zalo OA đang quản lý (`v3.0/oa/group/getgroupsofoa`).
 *
 * @param {number} offset Vị trí bắt đầu.
 * @param {number} count Số lượng nhóm cần lấy.
 * @returns {Promise<{ ok: boolean, total: number, groups: any[], error?: string, raw?: any }>}
 */
export async function getGroupsOfOa(offset = 0, count = 20) {
  const params = new URLSearchParams({
    offset: String(Number(offset) || 0),
    count: String(Math.min(Math.max(Number(count) || 20, 1), 50)),
  });
  const data = await callZaloApi(`${ZALO_OA_GROUP_LIST_URL}?${params.toString()}`, {
    method: "GET",
  });
  if (Number(data?.error) !== 0) {
    return {
      ok: false,
      total: 0,
      groups: [],
      error: data?.message || `Zalo OA GMF error ${data?.error}`,
      raw: data,
    };
  }
  const groups = data?.data?.groups || data?.data || [];
  return {
    ok: true,
    total: Number(data?.data?.total ?? groups.length),
    groups: Array.isArray(groups) ? groups : [],
    raw: data,
  };
}

/**
 * Lấy thông tin chi tiết của một nhóm chat GMF (`v3.0/oa/group/getgroup`).
 *
 * @param {string} groupId Mã nhóm GMF.
 * @returns {Promise<{ ok: boolean, group?: any, error?: string, raw?: any }>}
 */
export async function getGroupInfo(groupId) {
  const params = new URLSearchParams({ group_id: String(groupId).trim() });
  const data = await callZaloApi(`${ZALO_OA_GROUP_INFO_URL}?${params.toString()}`, {
    method: "GET",
  });
  if (Number(data?.error) !== 0) {
    return { ok: false, error: data?.message || `Zalo OA GMF error ${data?.error}`, raw: data };
  }
  return { ok: true, group: data?.data || null, raw: data };
}

/**
 * Lấy danh sách thành viên trong một nhóm chat GMF (`v3.0/oa/group/listmember`).
 *
 * @param {string} groupId Mã nhóm GMF.
 * @param {number} offset Vị trí bắt đầu.
 * @param {number} count Số lượng thành viên tối đa.
 * @returns {Promise<{ ok: boolean, members: any[], total: number, error?: string }>}
 */
export async function getGroupMembers(groupId, offset = 0, count = 50) {
  const params = new URLSearchParams({
    group_id: String(groupId).trim(),
    offset: String(Number(offset) || 0),
    count: String(Math.min(Math.max(Number(count) || 50, 1), 50)),
  });
  const data = await callZaloApi(`${ZALO_OA_GROUP_MEMBERS_URL}?${params.toString()}`, {
    method: "GET",
  });
  if (Number(data?.error) !== 0) {
    return { ok: false, members: [], total: 0, error: data?.message || `Zalo OA GMF error ${data?.error}` };
  }
  const members = data?.data?.members || data?.data || [];
  return {
    ok: true,
    members: Array.isArray(members) ? members : [],
    total: Number(data?.data?.total ?? (Array.isArray(members) ? members.length : 0)),
  };
}

/**
 * Lấy lịch sử tin nhắn trong nhóm chat GMF (`v3.0/oa/group/conversation`).
 *
 * @param {string} groupId Mã nhóm GMF.
 * @param {number} offset Vị trí bắt đầu.
 * @param {number} count Số lượng tin nhắn.
 * @returns {Promise<{ ok: boolean, messages: any[], error?: string }>}
 */
export async function getGroupConversation(groupId, offset = 0, count = 20) {
  const params = new URLSearchParams({
    group_id: String(groupId).trim(),
    offset: String(Number(offset) || 0),
    count: String(Math.min(Math.max(Number(count) || 20, 1), 50)),
  });
  const data = await callZaloApi(`${ZALO_OA_GROUP_CONVERSATION_URL}?${params.toString()}`, {
    method: "GET",
  });
  if (Number(data?.error) !== 0) {
    return { ok: false, messages: [], error: data?.message || `Zalo OA GMF error ${data?.error}` };
  }
  const messages = data?.data?.messages || data?.data || [];
  return { ok: true, messages: Array.isArray(messages) ? messages : [] };
}

/**
 * Gửi tin nhắn văn bản từ Zalo OA vào một nhóm chat GMF (`v3.0/oa/group/message`).
 *
 * @param {string} groupId Mã nhóm GMF.
 * @param {string} text Nội dung tin nhắn.
 * @param {string | null} quoteMsgId Mã tin nhắn trích dẫn (nếu có).
 * @returns {Promise<{ ok: boolean, msgId?: string, error?: string, raw?: any }>}
 */
export async function sendGroupMessage(groupId, text, quoteMsgId = null) {
  const payload = {
    recipient: { group_id: String(groupId).trim() },
    message: { text: String(text) },
  };
  if (quoteMsgId) {
    payload.message.quote_message_id = String(quoteMsgId).trim();
  }

  const data = await callZaloApi(ZALO_OA_GROUP_MESSAGE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (Number(data?.error) !== 0) {
    return {
      ok: false,
      error: data?.message || `Zalo OA GMF error ${data?.error}`,
      raw: data,
    };
  }

  return {
    ok: true,
    msgId: data?.data?.message_id || null,
    raw: data,
  };
}
