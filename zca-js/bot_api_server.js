/**
 * VSICO Zalo Bot - HTTP REST API Server & Bridge
 * 
 * Cung cấp đầy đủ các cổng HTTP REST API trên cổng 3000 để kiểm thử trực tiếp qua Postman:
 * 1. GET  /api/bot/groups                              - Lấy tất cả groupId nhóm
 * 2. GET  /api/bot/groups/:groupId/info               - Lấy chi tiết nhóm & thành viên
 * 3. GET  /api/bot/users                              - Lấy tất cả userId (bạn bè)
 * 4. GET  /api/bot/users/:userId                      - Lấy thông tin chi tiết một user
 * 5. GET  /api/bot/groups/:groupId/messages           - Lấy lịch sử tin nhắn trong nhóm
 * 6. GET  /api/bot/groups/:groupId/users/:userId/messages - Lấy tin nhắn của userId trong nhóm
 * 7. POST /api/bot/send/user                          - Gửi tin nhắn đến userId
 * 8. POST /api/bot/send/group                         - Gửi tin nhắn đến groupId
 * 9. GET  /api/bot/realtime/messages                  - Lấy danh sách tin nhắn bắt được realtime
 * 10. GET /api/bot/status                             - Kiểm tra trạng thái Bot & WebSocket
 * 11. GET /api/bot/friends/pending                    - Xem danh sách lời mời kết bạn đang chờ
 * 12. POST /api/bot/friends/accept                    - Chấp thuận lời mời kết bạn từ userId
 * 13. POST /api/bot/friends/request                   - Gửi lời mời kết bạn tới userId
 * 
 * Đồng thời tự động đẩy Webhook sang Backend Python (Port 8000).
 */

import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { Zalo, ThreadType } from 'zca-js';

const PORT = process.env.BOT_API_PORT || 3000;
const BACKEND_URL = process.env.BACKEND_WEBHOOK_URL || 'http://localhost:8000/webhook';
const CREDENTIALS_FILE = path.resolve('./credentials.json');

const zalo = new Zalo({
    selfListen: false,
    checkUpdate: true,
    logging: false,
});

let apiInstance = null;
let isSocketConnected = false;
const realtimeMessagesQueue = [];
const MAX_REALTIME_HISTORY = 100;
const groupNameCache = new Map();

/**
 * Lấy tên nhóm Zalo từ bộ nhớ cache hoặc gọi API nếu chưa lưu
 */
async function getCachedGroupName(groupId) {
    if (!groupId || String(groupId).startsWith('direct_')) return null;
    const gid = String(groupId).trim();
    if (groupNameCache.has(gid)) return groupNameCache.get(gid);
    if (!apiInstance) return null;
    try {
        const infoRes = await apiInstance.getGroupInfo(gid);
        const name = infoRes?.gridInfoMap?.[gid]?.name;
        if (name) {
            groupNameCache.set(gid, name);
            return name;
        }
    } catch {
        // Bỏ qua an toàn nếu lỗi mạng
    }
    return null;
}

function loadSavedCredentials() {
    if (!fs.existsSync(CREDENTIALS_FILE)) return null;
    try {
        const raw = fs.readFileSync(CREDENTIALS_FILE, 'utf-8');
        const creds = JSON.parse(raw);
        if (creds.cookie && creds.imei && creds.userAgent) {
            return creds;
        }
    } catch (e) {
        console.error('Không thể đọc file credentials:', e.message);
    }
    return null;
}

function saveCredentials(api) {
    const ctx = api.getContext();
    const creds = {
        cookie: ctx.cookie.toJSON()?.cookies || [],
        imei: ctx.imei,
        userAgent: ctx.userAgent
    };
    fs.writeFileSync(CREDENTIALS_FILE, JSON.stringify(creds, null, 2), 'utf-8');
    console.log('[INFO] Đã lưu phiên đăng nhập vào:', CREDENTIALS_FILE);
}

async function forwardToBackend(payload) {
    const dataString = JSON.stringify(payload);
    return new Promise((resolve) => {
        const req = http.request(BACKEND_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json; charset=utf-8',
                'Content-Length': Buffer.byteLength(dataString),
                'X-Request-Id': 'zalo-live-' + Date.now()
            }
        }, (res) => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                try {
                    resolve({ status: res.statusCode, body: JSON.parse(body) });
                } catch {
                    resolve({ status: res.statusCode, body });
                }
            });
        });
        req.on('error', (err) => resolve({ status: 500, error: err.message }));
        req.write(dataString);
        req.end();
    });
}

function parseJsonBody(req) {
    return new Promise((resolve, reject) => {
        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', () => {
            if (!body.trim()) return resolve({});
            try {
                resolve(JSON.parse(body));
            } catch (e) {
                reject(new Error('Invalid JSON format: ' + e.message));
            }
        });
        req.on('error', reject);
    });
}

function sendJson(res, statusCode, data) {
    res.writeHead(statusCode, {
        'Content-Type': 'application/json; charset=utf-8',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization'
    });
    res.end(JSON.stringify(data, null, 2));
}

function extractImageUrl(content) {
    if (!content) return null;
    if (typeof content === 'string') {
        const trimmed = content.trim();
        if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
            const lower = trimmed.toLowerCase();
            if (lower.includes('.jpg') || lower.includes('.jpeg') || lower.includes('.png') || lower.includes('.webp') || lower.includes('photo') || lower.includes('image') || lower.includes('res-zalo') || lower.includes('zadn.vn')) {
                return trimmed;
            }
        }
        try {
            const parsed = JSON.parse(content);
            return extractImageUrl(parsed);
        } catch {
            return null;
        }
    }
    if (typeof content === 'object') {
        if (content.params) {
            try {
                const p = typeof content.params === 'string' ? JSON.parse(content.params) : content.params;
                const pUrl = p.hdUrl || p.url || p.normalUrl || p.rawUrl || p.thumb;
                if (pUrl && typeof pUrl === 'string' && (pUrl.startsWith('http://') || pUrl.startsWith('https://'))) {
                    return pUrl;
                }
            } catch {}
        }
        const candidates = [
            content.hdUrl,
            content.normalUrl,
            content.url,
            content.href,
            content.rawUrl,
            content.thumb,
            content.src
        ];
        for (const c of candidates) {
            if (c && typeof c === 'string' && (c.startsWith('http://') || c.startsWith('https://'))) {
                return c;
            }
        }
    }
    return null;
}

async function startBot() {
    console.log('[INFO] Đang khởi động kết nối Zalo Bot Client...');
    const savedCreds = loadSavedCredentials();
    if (savedCreds) {
        try {
            apiInstance = await zalo.login(savedCreds);
            console.log('[INFO] Đăng nhập bằng credentials thành công.');
        } catch {
            console.warn('[WARN] Phiên đăng nhập hết hạn, đang tạo mã QR mới...');
            apiInstance = await zalo.loginQR({ qrPath: './qr.png' });
            saveCredentials(apiInstance);
        }
    } else {
        console.log('[INFO] Chưa có credentials. Vui lòng quét mã qr.png để đăng nhập...');
        apiInstance = await zalo.loginQR({ qrPath: './qr.png' });
        saveCredentials(apiInstance);
    }

    // Tải trước danh sách nhóm để nạp cache tên nhóm
    try {
        const allGroups = await apiInstance.getAllGroups();
        const gids = Object.keys(allGroups?.gridVerMap || {});
        if (gids.length > 0) {
            const groupsInfo = await apiInstance.getGroupInfo(gids);
            for (const [gid, gdata] of Object.entries(groupsInfo?.gridInfoMap || {})) {
                if (gdata?.name) {
                    groupNameCache.set(gid, gdata.name);
                }
            }
            console.log(`[INFO] [GROUP CACHE] Đã nạp thành công tên của ${groupNameCache.size} nhóm Zalo vào RAM.`);
        }
    } catch (err) {
        console.warn('[WARN] [GROUP CACHE] Không thể nạp trước danh sách nhóm:', err.message);
    }

    const { listener } = apiInstance;

    listener.onConnected(() => {
        isSocketConnected = true;
        console.log('[INFO] [ZALO WEBSOCKET] Kết nối thành công. Đang lắng nghe realtime...');
    });

    listener.onClosed((code, reason) => {
        isSocketConnected = false;
        console.warn(`[WARN] [ZALO WEBSOCKET] Bị ngắt kết nối [${code}]: ${reason}`);
    });

    listener.onError((err) => {
        console.error('[ERROR] [ZALO WEBSOCKET] Lỗi kết nối:', err);
    });

    listener.on('message', async (message) => {
        if (message.isSelf) return;

        // Tự động kiểm tra và chấp thuận kết bạn nếu là tin nhắn riêng 1-1
        if (message.type !== ThreadType.Group) {
            autoAcceptFriendRequests().catch(() => {});
        }

        const record = {
            id: message.data.msgId || message.data.cliMsgId,
            threadId: message.threadId,
            type: message.type === ThreadType.Group ? 'group' : 'user',
            senderId: message.data.uidFrom,
            senderName: message.data.dName || '',
            content: message.data.content,
            timestamp: message.data.ts || Date.now(),
            receivedAt: new Date().toISOString()
        };

        realtimeMessagesQueue.unshift(record);
        if (realtimeMessagesQueue.length > MAX_REALTIME_HISTORY) {
            realtimeMessagesQueue.pop();
        }

        const msgType = String(message.data.msgType || '').toLowerCase();
        const imageUrl = extractImageUrl(message.data.content);
        const isImage = Boolean(imageUrl || msgType === 'chat.photo' || msgType === 'photo' || msgType === 'image');
        
        let textContent = '';
        if (typeof message.data.content === 'string') {
            textContent = message.data.content;
        } else if (message.data.content && typeof message.data.content === 'object') {
            textContent = message.data.content.title || message.data.content.description || message.data.content.caption || '';
        }

        // Lấy tên nhóm nếu là tin nhắn trong group
        let groupName = null;
        if (message.type === ThreadType.Group) {
            groupName = await getCachedGroupName(message.threadId);
        } else {
            groupName = `Chat riêng: ${message.data.dName || message.data.uidFrom}`;
        }

        console.log(`[REALTIME] [${record.type.toUpperCase()}:${groupName || record.threadId}] [${record.senderName}]: ${typeof record.content === 'string' ? record.content : (isImage ? `[Ảnh: ${imageUrl || msgType}]` : '[Đính kèm]')}`);

        // Đẩy Webhook sang Backend Python (hỗ trợ cả tin nhắn văn bản và tin nhắn ảnh)
        const inboundPayload = {
            app_id: 'zca_personal_bot',
            event_name: isImage ? 'user_send_image' : 'user_send_text',
            group_id: message.type === ThreadType.Group ? message.threadId : `direct_${message.data.uidFrom}`,
            group_name: groupName || undefined,
            sender: {
                id: message.data.uidFrom,
                name: message.data.dName || 'Zalo User'
            },
            timestamp: String(message.data.ts || Date.now()),
            quote_msg_id: message.data.quote?.globalMsgId || null,
            image_url: imageUrl || undefined,
            message: {
                msg_id: String(message.data.msgId || message.data.cliMsgId),
                text: textContent,
                image_url: imageUrl || undefined,
                quote_msg_id: message.data.quote?.globalMsgId || null
            },
            raw_payload: message.data
        };
        forwardToBackend(inboundPayload);
    });

    listener.start();

    // Chạy kiểm tra tự động kết bạn ngay khi đăng nhập và định kỳ mỗi 30 giây
    autoAcceptFriendRequests().catch(() => {});
    setInterval(() => {
        autoAcceptFriendRequests().catch(() => {});
    }, 30000);
}

/**
 * Tự động duyệt các lời mời kết bạn đang chờ gửi tới tài khoản Bot
 */
async function autoAcceptFriendRequests() {
    if (!apiInstance) return;
    try {
        const rec = await apiInstance.getFriendRecommendations();
        const items = rec?.recommItems || [];
        for (const item of items) {
            // recommItemType === 2 hoặc recommType === 2 là ReceivedFriendRequest
            if (item.recommItemType === 2 || item.recommType === 2) {
                const friendId = item.dataInfo?.userId;
                const friendName = item.dataInfo?.displayName || item.dataInfo?.zaloName || friendId;
                if (friendId) {
                    try {
                        console.log(`[INFO] [AUTO ACCEPT] Phát hiện lời mời kết bạn từ ${friendName} (${friendId}). Đang tự động chấp thuận...`);
                        await apiInstance.acceptFriendRequest(friendId);
                        console.log(`[INFO] [AUTO ACCEPT] Đã chấp thuận kết bạn với ${friendName} (${friendId}).`);
                    } catch (accErr) {
                        console.warn(`[WARN] [AUTO ACCEPT] Không thể chấp thuận kết bạn từ ${friendId}:`, accErr?.message || accErr);
                    }
                }
            }
        }
    } catch {
        // Bỏ qua an toàn nếu API gợi ý kết bạn tạm thời không khả dụng
    }
}

const server = http.createServer(async (req, res) => {
    const parsedUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const pathname = parsedUrl.pathname;
    const method = req.method;

    if (method === 'OPTIONS') {
        res.writeHead(204, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization'
        });
        return res.end();
    }

    try {
        if (!apiInstance) {
            return sendJson(res, 503, { ok: false, error: 'Bot chưa hoàn tất đăng nhập Zalo' });
        }

        // 1. GET /api/bot/status hoặc GET /api/health / GET /health
        if (method === 'GET' && (pathname === '/api/bot/status' || pathname === '/api/health' || pathname === '/health')) {
            const profile = await apiInstance.fetchAccountInfo().catch(() => null);
            return sendJson(res, 200, {
                ok: true,
                service: 'VSICO Zalo Bot (zca-js)',
                status: 'RUNNING',
                websocket_connected: isSocketConnected,
                bot_user: profile?.data || null,
                realtime_cached_count: realtimeMessagesQueue.length
            });
        }

        // 2. GET /api/bot/groups - Lấy tất cả groupId nhóm
        if (method === 'GET' && pathname === '/api/bot/groups') {
            const groupsRes = await apiInstance.getAllGroups();
            const groupIds = Object.keys(groupsRes.gridVerMap || {});
            return sendJson(res, 200, {
                ok: true,
                total_groups: groupIds.length,
                group_ids: groupIds,
                grid_ver_map: groupsRes.gridVerMap
            });
        }

        // 3. GET /api/bot/groups/:groupId/info - Lấy chi tiết nhóm & thành viên
        const groupInfoMatch = pathname.match(/^\/api\/bot\/groups\/([^/]+)\/info$/);
        if (method === 'GET' && groupInfoMatch) {
            const groupId = groupInfoMatch[1];
            const infoRes = await apiInstance.getGroupInfo(groupId);
            const detail = infoRes.gridInfoMap ? infoRes.gridInfoMap[groupId] : null;

            // Bóc tách memberIds từ memVerList của Zalo (dạng "uid_version")
            let memberIds = [];
            let membersProfiles = null;
            if (detail && Array.isArray(detail.memVerList)) {
                memberIds = detail.memVerList.map((item) => String(item).split('_')[0]);
                detail.memberIds = memberIds;

                // Tự động lấy profile chi tiết của các thành viên
                try {
                    const profilesRes = await apiInstance.getGroupMembersInfo(memberIds);
                    membersProfiles = profilesRes?.profiles || null;
                } catch (e) {
                    console.warn('Không thể lấy chi tiết profile thành viên:', e.message);
                }
            }

            return sendJson(res, 200, {
                ok: true,
                group_id: groupId,
                total_members: memberIds.length || detail?.totalMember || 0,
                member_ids: memberIds,
                members_profiles: membersProfiles,
                data: detail
            });
        }

        // 4. GET /api/bot/users - Lấy tất cả userId (bạn bè)
        if (method === 'GET' && pathname === '/api/bot/users') {
            const count = Number(parsedUrl.searchParams.get('count')) || 1000;
            const friends = await apiInstance.getAllFriends(count, 1);
            const userIds = friends.map(u => u.userId);
            return sendJson(res, 200, {
                ok: true,
                total_users: userIds.length,
                user_ids: userIds,
                users: friends
            });
        }

        // 5. GET /api/bot/users/:userId - Lấy thông tin 1 user
        const userInfoMatch = pathname.match(/^\/api\/bot\/users\/([^/]+)$/);
        if (method === 'GET' && userInfoMatch) {
            const userId = userInfoMatch[1];
            const infoRes = await apiInstance.getUserInfo(userId);
            return sendJson(res, 200, {
                ok: true,
                user_id: userId,
                data: infoRes.changed_profiles ? infoRes.changed_profiles[userId] || infoRes.changed_profiles[`${userId}_0`] : null
            });
        }

        // 6. GET /api/bot/groups/:groupId/messages - Lấy lịch sử tin nhắn nhóm
        const groupMsgsMatch = pathname.match(/^\/api\/bot\/groups\/([^/]+)\/messages$/);
        if (method === 'GET' && groupMsgsMatch) {
            const groupId = groupMsgsMatch[1];
            const count = Number(parsedUrl.searchParams.get('count')) || 50;

            // Thử gọi getGroupChatHistory từ Zalo API (nếu endpoint server Zalo khả dụng)
            let messages = [];
            let source = 'zalo_api';
            try {
                const history = await apiInstance.getGroupChatHistory(groupId, count);
                messages = (history.groupMsgs || []).map(m => ({
                    msg_id: m.data?.msgId,
                    sender_id: m.data?.uidFrom,
                    sender_name: m.data?.dName,
                    content: m.data?.content,
                    timestamp: m.data?.ts
                }));
            } catch (err) {
                // Zalo Web hiện tại đã chặn/đóng endpoint tải lịch sử cũ qua REST API (/api/group/history -> 404).
                // Tự động Fallback sang bộ nhớ đệm Realtime + Database Backend đã lưu
                source = 'cached_realtime';
                messages = realtimeMessagesQueue
                    .filter(m => String(m.threadId) === String(groupId))
                    .slice(0, count)
                    .map(m => ({
                        msg_id: m.id,
                        sender_id: m.senderId,
                        sender_name: m.senderName,
                        content: m.content,
                        timestamp: m.timestamp,
                        received_at: m.receivedAt
                    }));
            }

            return sendJson(res, 200, {
                ok: true,
                group_id: groupId,
                source: source,
                total_messages: messages.length,
                messages: messages,
                note: source === 'cached_realtime' ? 'Zalo Web đã đóng endpoint history cũ (404); hệ thống tự động trả về tin nhắn bắt được realtime & lưu trong DB.' : undefined
            });
        }

        // 7. GET /api/bot/groups/:groupId/users/:userId/messages - Lấy tin nhắn của userId trong nhóm
        const groupUserMsgsMatch = pathname.match(/^\/api\/bot\/groups\/([^/]+)\/users\/([^/]+)\/messages$/);
        if (method === 'GET' && groupUserMsgsMatch) {
            const groupId = groupUserMsgsMatch[1];
            const userId = groupUserMsgsMatch[2];
            const count = Number(parsedUrl.searchParams.get('count')) || 100;

            let filtered = [];
            let source = 'zalo_api';
            try {
                const history = await apiInstance.getGroupChatHistory(groupId, count);
                filtered = (history.groupMsgs || [])
                    .filter(m => String(m.data?.uidFrom) === String(userId))
                    .map(m => ({
                        msg_id: m.data?.msgId,
                        sender_id: m.data?.uidFrom,
                        sender_name: m.data?.dName,
                        content: m.data?.content,
                        timestamp: m.data?.ts
                    }));
            } catch (err) {
                source = 'cached_realtime';
                filtered = realtimeMessagesQueue
                    .filter(m => String(m.threadId) === String(groupId) && String(m.senderId) === String(userId))
                    .slice(0, count)
                    .map(m => ({
                        msg_id: m.id,
                        sender_id: m.senderId,
                        sender_name: m.senderName,
                        content: m.content,
                        timestamp: m.timestamp,
                        received_at: m.receivedAt
                    }));
            }

            return sendJson(res, 200, {
                ok: true,
                group_id: groupId,
                user_id: userId,
                source: source,
                matched_messages_count: filtered.length,
                messages: filtered
            });
        }

        // 8. POST /api/bot/send/user - Gửi tin nhắn đến userId
        if (method === 'POST' && pathname === '/api/bot/send/user') {
            const body = await parseJsonBody(req);
            const { userId, message } = body;
            if (!userId || !message) {
                return sendJson(res, 400, { ok: false, error: 'Thiếu trường userId hoặc message' });
            }
            try {
                const sendResult = await apiInstance.sendMessage(message, String(userId), ThreadType.User);
                return sendJson(res, 200, {
                    ok: true,
                    message: 'Đã gửi tin nhắn đến userId thành công',
                    recipient_id: userId,
                    result: sendResult
                });
            } catch (sendErr) {
                if (sendErr?.code === 123) {
                    console.warn(`[WARN] [ZALO CODE 123] Không thể gửi tin trực tiếp đến User ${userId}: Người dùng chưa kết bạn hoặc chặn tin nhắn từ người lạ.`);
                    // Tự động thử gửi lời mời kết bạn để thông tuyến kết nối
                    try {
                        console.log(`[INFO] [AUTO FRIEND REQUEST] Đang tự động gửi lời mời kết bạn tới User ${userId}...`);
                        await apiInstance.sendFriendRequest('Hệ thống VSICO TMS xin gửi lời mời kết bạn để gửi thông báo chuyến xe.', String(userId));
                        console.log(`[INFO] [AUTO FRIEND REQUEST] Đã gửi/xác nhận lời mời kết bạn tới User ${userId}.`);
                    } catch (frErr) {
                        console.log(`[INFO] [AUTO FRIEND REQUEST] Phản hồi kết bạn tới ${userId}: ${frErr?.message || 'Đã gửi'}`);
                    }

                    return sendJson(res, 400, {
                        ok: false,
                        code: 123,
                        error: 'Người nhận chưa kết bạn với Bot hoặc đang bật Chặn tin nhắn từ người lạ (Zalo error 123). Bot đã tự động gửi lời mời kết bạn, vui lòng đồng ý kết bạn trên Zalo để nhận thông báo.'
                    });
                }
                console.error(`[ERROR] [SEND USER ERROR] Lỗi khi gửi tin tới ${userId}:`, sendErr?.message || sendErr);
                return sendJson(res, 500, { ok: false, error: sendErr?.message || 'Lỗi khi gửi tin nhắn' });
            }
        }

        // 9. POST /api/bot/send/group - Gửi tin nhắn đến groupId
        if (method === 'POST' && pathname === '/api/bot/send/group') {
            const body = await parseJsonBody(req);
            const { groupId, message, quoteMsgId } = body;
            if (!groupId || !message) {
                return sendJson(res, 400, { ok: false, error: 'Thiếu trường groupId hoặc message' });
            }
            let payload = message;
            if (quoteMsgId) {
                payload = {
                    msg: message,
                    quote: {
                        msgId: quoteMsgId,
                        content: '',
                        uidFrom: '',
                        ts: Date.now()
                    }
                };
            }
            let sendResult;
            try {
                sendResult = await apiInstance.sendMessage(payload, String(groupId), ThreadType.Group);
            } catch (sendErr) {
                if (quoteMsgId) {
                    console.warn(`[WARN] [QUOTE ERROR] Lỗi khi trích dẫn msgId=${quoteMsgId} (${sendErr.message}), tự động fallback gửi tin nhắn thông thường vào nhóm.`);
                    try {
                        sendResult = await apiInstance.sendMessage(message, String(groupId), ThreadType.Group);
                    } catch (fallbackErr) {
                        console.error(`[ERROR] [SEND GROUP ERROR] Thất bại khi fallback gửi vào nhóm ${groupId}:`, fallbackErr?.message || fallbackErr);
                        return sendJson(res, 500, { ok: false, error: fallbackErr?.message || 'Lỗi gửi tin nhắn vào nhóm' });
                    }
                } else {
                    console.error(`[ERROR] [SEND GROUP ERROR] Lỗi khi gửi vào nhóm ${groupId}:`, sendErr?.message || sendErr);
                    return sendJson(res, 500, { ok: false, error: sendErr?.message || 'Lỗi gửi tin nhắn vào nhóm' });
                }
            }
            return sendJson(res, 200, {
                ok: true,
                message: 'Đã gửi tin nhắn đến groupId thành công',
                group_id: groupId,
                result: sendResult
            });
        }

        // 10. GET /api/bot/realtime/messages - Lấy danh sách tin nhắn realtime vừa nhận
        if (method === 'GET' && pathname === '/api/bot/realtime/messages') {
            const limit = Number(parsedUrl.searchParams.get('limit')) || 20;
            return sendJson(res, 200, {
                ok: true,
                total_cached: realtimeMessagesQueue.length,
                messages: realtimeMessagesQueue.slice(0, limit)
            });
        }

        // 10.1 POST /api/bot/realtime/clear - Dọn sạch hàng đợi tin nhắn realtime trong bộ nhớ cache
        if (method === 'POST' && pathname === '/api/bot/realtime/clear') {
            const clearedCount = realtimeMessagesQueue.length;
            realtimeMessagesQueue.length = 0;
            return sendJson(res, 200, {
                ok: true,
                message: `Đã dọn sạch ${clearedCount} tin nhắn trong bộ nhớ cache realtime.`,
                cleared_count: clearedCount
            });
        }

        // 11. GET /api/bot/friends/pending - Lấy danh sách lời mời kết bạn đang chờ duyệt
        if (method === 'GET' && pathname === '/api/bot/friends/pending') {
            try {
                const rec = await apiInstance.getFriendRecommendations();
                const pending = (rec?.recommItems || [])
                    .filter(item => item.recommItemType === 2 || item.recommType === 2)
                    .map(item => ({
                        user_id: item.dataInfo?.userId,
                        display_name: item.dataInfo?.displayName,
                        zalo_name: item.dataInfo?.zaloName,
                        avatar: item.dataInfo?.avatar,
                        recomm_time: item.dataInfo?.recommTime
                    }));
                return sendJson(res, 200, { ok: true, pending_count: pending.length, items: pending });
            } catch (e) {
                return sendJson(res, 500, { ok: false, error: e.message || 'Lỗi lấy danh sách kết bạn' });
            }
        }

        // 12. POST /api/bot/friends/accept - Chấp nhận lời mời kết bạn từ một userId
        if (method === 'POST' && pathname === '/api/bot/friends/accept') {
            const body = await parseJsonBody(req);
            const { userId } = body;
            if (!userId) {
                return sendJson(res, 400, { ok: false, error: 'Thiếu trường userId' });
            }
            try {
                const result = await apiInstance.acceptFriendRequest(String(userId));
                return sendJson(res, 200, { ok: true, message: `Đã chấp thuận kết bạn với ${userId}`, result });
            } catch (e) {
                return sendJson(res, 400, { ok: false, error: e.message || 'Lỗi chấp thuận kết bạn' });
            }
        }

        // 13. POST /api/bot/friends/request - Gửi lời mời kết bạn tới userId
        if (method === 'POST' && pathname === '/api/bot/friends/request') {
            const body = await parseJsonBody(req);
            const { userId, message } = body;
            if (!userId) {
                return sendJson(res, 400, { ok: false, error: 'Thiếu trường userId' });
            }
            try {
                const frMsg = message || 'Hệ thống VSICO TMS xin gửi lời mời kết bạn để gửi thông báo chuyến xe.';
                const result = await apiInstance.sendFriendRequest(frMsg, String(userId));
                return sendJson(res, 200, { ok: true, message: `Đã gửi lời mời kết bạn tới ${userId}`, result });
            } catch (e) {
                return sendJson(res, 400, { ok: false, error: e.message || 'Lỗi gửi lời mời kết bạn' });
            }
        }

        // Endpoint không tìm thấy
        return sendJson(res, 404, { ok: false, error: 'Endpoint không tồn tại: ' + pathname });

    } catch (err) {
        console.error('Lỗi API Server:', err);
        return sendJson(res, 500, { ok: false, error: err.message });
    }
});

server.listen(PORT, async () => {
    console.log(`[INFO] [BOT REST API] Máy chủ chạy tại: http://localhost:${PORT}`);
    console.log(`[INFO] [BOT REST API] Sẵn sàng nhận yêu cầu từ hệ thống TMS và Postman.`);
    await startBot();
});
