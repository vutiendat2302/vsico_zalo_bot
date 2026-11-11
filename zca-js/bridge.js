/**
 * VSICO Zalo Connector
 * Dùng thư viện zca-js để đăng nhập tài khoản Zalo cá nhân,
 * bắt sự kiện tin nhắn từ các nhóm nhà xe thời gian thực
 * và chuyển tiếp sang Backend
 * 
 * Cách chạy:
 *   node bridge.js
 */

import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { Zalo, ThreadType } from 'zca-js';

const BACKEND_URL = process.env.BACKEND_WEBHOOK_URL || 'http://localhost:8000/webhook';
const CREDENTIALS_FILE = path.resolve('./credentials.json');

const zalo = new Zalo({
    selfListen: false,
    checkUpdate: true,
    logging: true,
});

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

/**
 * Đẩy Webhook sang Backend Python
 */
async function forwardToBackend(payload) {
    const dataString = JSON.stringify(payload);

    return new Promise((resolve, reject) => {
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
                    const parsed = JSON.parse(body);
                    resolve({ status: res.statusCode, body: parsed });
                } catch (e) {
                    resolve({ status: res.statusCode, body });
                }
            });
        });

        req.on('error', reject);
        req.write(dataString);
        req.end();
    });
}

async function main() {
    console.log('[INFO] Khởi động VSICO Zalo Connector Bridge...');

    let api;
    const savedCreds = loadSavedCredentials();

    if (savedCreds) {
        console.log('[INFO] Tìm thấy phiên đăng nhập cũ, đang đăng nhập tự động...');
        try {
            api = await zalo.login(savedCreds);
            console.log('[INFO] Đăng nhập tự động thành công.');
        } catch (err) {
            console.warn('[WARN] Phiên đăng nhập hết hạn, đang tạo mã QR đăng nhập mới...');
            console.log('[INFO] Vui lòng mở file qr.png và sử dụng ứng dụng Zalo trên điện thoại để quét mã.');
            api = await zalo.loginQR({ qrPath: './qr.png' });
            saveCredentials(api);
        }
    } else {
        console.log('[INFO] Chưa có credentials. Đang tải mã QR từ máy chủ Zalo...');
        console.log('[INFO] Vui lòng mở file qr.png và sử dụng ứng dụng Zalo trên điện thoại để quét mã.');
        api = await zalo.loginQR({ qrPath: './qr.png' });
        saveCredentials(api);
    }

    const myProfile = await api.fetchAccountInfo();
    console.log(`[INFO] Tài khoản bot: ${myProfile?.data?.name || 'Zalo User'} (ID: ${myProfile?.data?.userId || 'N/A'})`);

    const { listener } = api;

    // Lắng nghe tin nhắn
    listener.on('message', async (message) => {
        // 1. Chống lặp tin: Bỏ qua tin nhắn do chính bot gửi
        if (message.isSelf) return;

        // 2. Chỉ xử lý tin nhắn văn bản thuần
        if (typeof message.data.content !== 'string') return;

        const isGroup = message.type === ThreadType.Group;
        const threadId = message.threadId;
        const senderId = message.data.uidFrom;
        const senderName = message.data.dName || '';
        const content = message.data.content;
        const msgId = String(message.data.msgId || message.data.cliMsgId);
        const quoteMsgId = message.data.quote ? String(message.data.quote.globalMsgId || message.data.quote.cliMsgId) : null;

        console.log(`\n[INFO] [ZALO NHẬN TIN] [${isGroup ? 'GROUP: ' + threadId : 'DIRECT: ' + senderId}] [${senderName}]:`);
        console.log(`   Nội dung: ${content.replace(/\n/g, ' ')}`);

        // Kiểm tra xem có phải lệnh điều hành của ĐHVT không
        const cleanContent = content.trim().toLowerCase();
        const isDhvtCommand = cleanContent === 'ok' 
            || cleanContent.startsWith('sửa ') 
            || cleanContent === 'huỷ' 
            || cleanContent === 'huy';

        // Tự động ánh xạ cho môi trường thử nghiệm nếu threadId chưa có trong danh bạ demo 19 số
        let effectiveGroupId = isGroup ? threadId : '';
        let effectiveSenderId = senderId;
        if (!effectiveGroupId || effectiveGroupId.length !== 19) {
            effectiveGroupId = isDhvtCommand ? '2000000000000000001' : '2001000000000000001';
            effectiveSenderId = isDhvtCommand ? '9001000000000000001' : '1001000000000000001';
            console.log(`   [AUTO-TEST-MAP] Ánh xạ sang nhóm test: ${effectiveGroupId} | Người gửi: ${effectiveSenderId}`);
        }

        // Đóng gói Inbound Payload theo DATA_CONTRACT.md
        const payload = {
            app_id: 'zca_personal_bot',
            event_name: 'user_send_text',
            group_id: effectiveGroupId,
            sender: {
                id: effectiveSenderId,
                name: senderName || (isDhvtCommand ? 'Điều Hành VSICO' : 'Lái Xe Test')
            },
            timestamp: String(message.data.ts || Date.now()),
            quote_msg_id: quoteMsgId,
            message: {
                msg_id: msgId,
                text: content,
                quote_msg_id: quoteMsgId
            }
        };

        try {
            const res = await forwardToBackend(payload);
            if (!res.body || !res.body.ok) {
                console.error('[ERROR] Backend trả về lỗi:', res.body?.error || res.status);
                return;
            }

            const data = res.body.data;
            console.log(`[INFO] [BACKEND XỬ LÝ] Action: ${data.action} | Xe: ${data.total_vehicles || 0}`);

            // 1. Phản hồi lại nhà xe (nếu cần bổ sung thông tin hoặc câu hỏi)
            if (data.reply_to_carrier) {
                console.log(`[INFO] [ZALO PHẢN HỒI NHÀ XE] Nhóm ${threadId}: "${data.reply_to_carrier}"`);
                await api.sendMessage(
                    {
                        msg: data.reply_to_carrier,
                        quote: message.data // Quote lại đúng tin nhắn của nhà xe
                    },
                    threadId,
                    message.type
                );
            }

            // 2. Gửi thông báo đến các nhóm Zalo khách hàng
            if (data.customer_notifications && data.customer_notifications.length > 0) {
                for (const notif of data.customer_notifications) {
                    console.log(`[INFO] [ZALO GỬI KHÁCH HÀNG] Nhóm ${notif.target_group_id} (Cont: ${notif.cont})`);
                    // Nếu nhóm đích là ID giả lập 19 số, gửi kết quả vào chính thread chat hiện tại để tester nhìn thấy kết quả ngay
                    const destThread = (notif.target_group_id && notif.target_group_id.length === 19) ? threadId : notif.target_group_id;
                    const destType = (notif.target_group_id && notif.target_group_id.length === 19) ? message.type : ThreadType.Group;
                    try {
                        await api.sendMessage(
                            notif.message_text,
                            destThread,
                            destType
                        );
                    } catch (sendErr) {
                        console.warn(`[WARN] Không thể gửi tới ${destThread}:`, sendErr.message);
                    }
                }
            }

            // 3. Cảnh báo nội bộ Điều hành vận tải (nếu có)
            if (data.admin_alert) {
                console.warn(`[WARN] [CẢNH BÁO ADMIN ĐHVT]: ${data.admin_message}`);
            }

        } catch (err) {
            console.error('[ERROR] Lỗi kết nối tới Backend Python:', err.message);
        }
    });

    listener.onConnected(() => {
        console.log('[INFO] [ZALO WEBSOCKET] Kết nối thành công. Đang lắng nghe tin nhắn...');
    });

    listener.onClosed((code, reason) => {
        console.warn(`[WARN] [ZALO WEBSOCKET] Bị ngắt kết nối [code ${code}]: ${reason}`);
    });

    listener.onError((err) => {
        console.error('[ERROR] [ZALO WEBSOCKET] Lỗi kết nối:', err);
    });

    listener.start();
}

main().catch(console.error);
