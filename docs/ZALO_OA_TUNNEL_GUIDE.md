# Hướng Dẫn Kết Nối Zalo OA Webhook Qua Cloudflare Tunnel

## 1. Luồng dữ liệu
1. Người dùng gửi tin nhắn vào Zalo OA.
2. Zalo đẩy sự kiện Webhook qua HTTPS đến `https://oa.vtdat.com/webhook/zalo-oa`.
3. Cloudflare Tunnel (`cloudflared`) chuyển tiếp request về cầu nối `OA_BRIDGE` đang chạy tại `http://localhost:3000`.
4. `OA_BRIDGE` xác thực chữ ký Zalo OA, chuẩn hóa dữ liệu và đẩy tiếp sang Backend FastAPI tại `http://localhost:8000/webhook`.

---

## 2. Cài đặt `cloudflared` (Ubuntu/Debian)
```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

---

## 3. Khởi tạo Tunnel và trỏ DNS (chỉ làm lần đầu)

1. Đăng nhập tài khoản Cloudflare và chọn domain (ví dụ `vtdat.com`):
   ```bash
   cloudflared tunnel login
   ```
2. Tạo tunnel mới tên `vsico-oa`:
   ```bash
   cloudflared tunnel create vsico-oa
   ```
3. Trỏ subdomain `oa.vtdat.com` vào tunnel:
   ```bash
   cloudflared tunnel route dns --overwrite-dns vsico-oa oa.vtdat.com
   ```

---

## 4. Chạy Tunnel kết nối vào `localhost:3000`

Tại thư mục gốc của project, chạy lệnh ngắn gọn:

```bash
make oa-tunnel
```

*(Lệnh này tương đương với `cloudflared tunnel --protocol http2 --edge-ip-version 4 run --url http://localhost:3000 vsico-oa`, giúp tránh lỗi timeout QUIC/IPv6).*

Khi log hiển thị `Environment is healthy` và `Registered tunnel connection` (4 connections `connIndex=0..3`) là tunnel đã thông. Giữ nguyên cửa sổ terminal này trong suốt quá trình chạy.

---

## 5. Cấu hình trên Zalo Developers

1. **Xác thực domain**: Xác thực domain gốc (`vtdat.com`) và tiền tố URL (`https://oa.vtdat.com/`).
2. **Khai báo Webhook**:
   - **Webhook URL**: `https://oa.vtdat.com/webhook/zalo-oa`
   - **Webhook Retry**: Bật.
3. **Bật sự kiện nhận tin**: Trong danh sách sự kiện webhook, bật các sự kiện nhận tin nhắn cần thiết như `user_send_text`, `user_send_image` (và các sự kiện nhóm tương ứng nếu sử dụng nhóm).
4. **Kiểm tra kết nối**: Bấm nút **Test** bên cạnh sự kiện và kiểm tra terminal của `OA_BRIDGE` (`localhost:3000`) xem đã nhận được request và trả về `200 OK` chưa.

---

## 6. Xử lý lỗi thường gặp

- **`tunnel credentials file not found`**: Tunnel tên `vsico-oa` đã tồn tại từ trước trên Cloudflare nhưng file `.json` không còn trên máy hiện tại. Xóa tunnel cũ và tạo lại:
  ```bash
  cloudflared tunnel delete -f vsico-oa
  cloudflared tunnel create vsico-oa
  cloudflared tunnel route dns --overwrite-dns vsico-oa oa.vtdat.com
  ```
- **Lỗi `failed to dial to edge with quic: timeout` hoặc `region2 ... FAIL`**: Mạng chặn UDP/QUIC hoặc lỗi IPv6. Bắt buộc thêm `--protocol http2 --edge-ip-version 4` đặt **trước** chữ `run`.
