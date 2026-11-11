# VSICO ZALO BOT — FRONTEND DASHBOARD (`FRONTEND.md`)

### HỆ THỐNG QUẢN TRỊ VÀ ĐIỀU HÀNH VẬN TẢI CONTAINER THỜI GIAN THỰC (ĐHVT & ADMIN)

---

## 1. Tổng quan Phân hệ Frontend

Phân hệ **Frontend Dashboard** (`frontend/`) là công cụ điều hành trung tâm dành cho **Nhân viên Điều hành Vận tải (ĐHVT)** và **Quản trị viên (Admin)** của VSICO. Hệ thống cung cấp khả năng giám sát luồng tin nhắn Zalo thời gian thực, thẩm định và phê duyệt các ca báo xe bất thường (`review_cases`), theo dõi bản tin gửi khách (`outbound_messages`), quản lý kế hoạch vận chuyển hằng ngày (`transport_plans`), quản trị danh mục đồng bộ từ TMS (`customers`, `carriers`, `warehouses`, `zalo_info`, `route_maps`), quản lý người dùng (`users`) và thống kê chất lượng bóc tách.

### Công nghệ cốt lõi:
- **Framework**: Next.js 14+ (App Router), React 18+, TypeScript 5+ (Strict Mode).
- **Quản lý dữ liệu & Bảng**: TanStack Query (`@tanstack/react-query`) cho server state/caching và TanStack Table (`@tanstack/react-table`) cho bảng dữ liệu mật độ cao.
- **Giao diện**: Tailwind CSS, `shadcn/ui` (tinh chỉnh tối giản cho nghiệp vụ điều vận), Lucide Icons.
- **Đồng bộ kiểu dữ liệu**: Tự động sinh TypeScript types từ OpenAPI của FastAPI bằng `openapi-typescript` (`src/types/api.d.ts`).
- **Kiểm thử**: Playwright (`tests/e2e/`) kết hợp MSW (Mock Service Worker) cho kiểm thử tự động.

---

## 2. Nguyên tắc Dữ liệu, Định danh & Thời gian thực

### 2.1. Chính sách Zero Mock Data (Phạm vi áp dụng)
- **Trong mã nguồn ứng dụng chạy thật (`src/`)**: Bắt buộc 100% dữ liệu hiển thị phải truy vấn từ REST API của Backend. Tuyệt đối không sử dụng mảng dữ liệu giả (`mockData`), số liệu cố định hay dữ liệu ngẫu nhiên. Khi API trả về danh sách rỗng, hiển thị thành phần `EmptyState` một dòng rõ ràng.
- **Trong môi trường kiểm thử (`tests/`)**: Cho phép và khuyến khích sử dụng **MSW (Mock Service Worker)** hoặc cơ chế chặn route của Playwright để giả lập phản hồi API phục vụ kiểm thử đơn vị và kiểm thử E2E ổn định.

### 2.2. Quy ước Khóa chính Snowflake ID (`type Id = string`)
- Toàn bộ khóa chính `id` và khóa ngoại trong hệ thống Bot sử dụng **Snowflake ID 64-bit (`BigInteger`)**, vượt quá giới hạn số nguyên an toàn `Number.MAX_SAFE_INTEGER` ($2^{53} - 1$) của JavaScript.
- **Quy định bắt buộc**:
  1. Phía Backend serialize toàn bộ các trường ID Snowflake dưới dạng chuỗi (`string`) trong JSON response.
  2. Phía Frontend định nghĩa một lần duy nhất kiểu `export type Id = string;` và sử dụng thống nhất trên toàn bộ URL params, state, form và lời gọi API. Tuyệt đối không ép kiểu ID sang `number`.

### 2.3. Cơ chế Cập nhật Thời gian thực (Realtime Strategy)
- Hệ thống chọn **Server-Sent Events (SSE)** kết hợp **TanStack Query Polling dự phòng**:
  - **Kênh chính (SSE)**: Kết nối một chiều nhẹ từ trình duyệt tới Backend (`/api/events/stream`) để nhận sự kiện tức thời khi có tin nhắn Zalo mới, ca chờ duyệt mới (`review_cases`) hoặc thay đổi trạng thái gửi tin (`outbound_messages`). Khi nhận sự kiện, thực hiện `queryClient.invalidateQueries` theo domain tương ứng để cập nhật dòng tại chỗ.
  - **Kênh dự phòng (Polling có chu kỳ)**: TanStack Query cấu hình `refetchInterval: 10000` (10 giây, chỉ chạy khi cửa sổ trình duyệt đang hiển thị `refetchIntervalInBackground: false`) cho hàng đợi cần xử lý và danh sách ca duyệt khi kết nối SSE tạm thời gián đoạn.

### 2.4. Xác thực & Phân quyền (Authentication & RBAC)
- **Lưu trữ Token**: Sử dụng **`httpOnly` cookie** (`Secure`, `SameSite=Lax`) do Backend hoặc Next.js Route Handler thiết lập khi đăng nhập thành công. Tuyệt đối không lưu JWT token trong `localStorage` hoặc `sessionStorage`.
- **Bảo vệ Route (`src/middleware.ts`)**: Kiểm tra phiên đăng nhập và phân quyền (`role = 'dhvt' | 'admin'`) ngay tại tầng Middleware trước khi render trang:
  - Chưa đăng nhập truy cập vào nhóm `(app)` sẽ tự động chuyển hướng về `/login`.
  - Tài khoản có `role = 'dhvt'` truy cập vào `/admin/users` sẽ bị chặn (403 / chuyển hướng về trang tổng quan).

---

## 3. Nguyên tắc Thiết kế Giao diện Điều hành

Đây là công cụ làm việc cho người điều hành, không phải trang giới thiệu. Ưu tiên mật độ thông tin, tốc độ thao tác và dễ quét mắt. Giao diện đơn giản, bố cục thông minh. Hạn chế màu mè, tối đa 4 loại màu trong một trang. Màu text: tối đa 3 loại. Concept màu: back trắng, còn lại sẽ là tím..., làm nổi bật chi tiết trên back trắng. Hạn chế dùng icon trong nội dung, chỉ dùng ở các nút bấm, button...

### 3.1. Bố cục
- Thông minh, có dashboard thống kê, chia các trang hợp lý. 
- Hành động nằm ngay tại dòng hoặc ở thanh cố định. Hỗ trợ phím tắt cho thao tác lặp lại (lên/xuống chọn dòng, Enter mở, phím duyệt/từ chối).
- Không Card/Modal lồng nhau.

### 3.2. Hình thức
- Không đổ bóng, không gradient, không hiệu ứng mờ kính. Phân tách bằng đường kẻ `1px`.
- Bảng màu: back trắng, còn lại sẽ là tím... Tối đa 3-4 màu trong dự án này thôi. Màu ngữ nghĩa (đỏ, vàng, xanh) chỉ dùng cho trạng thái, không dùng làm nền trang trí.
- Chữ cỡ 13–14px, mật độ dòng gọn. Số liệu dùng `tabular-nums`. Số cont, biển số, seal, SĐT dùng font `monospace` để dễ đối chiếu.
- Icon chỉ dùng khi thay được chữ (nút đóng, sắp xếp, tải lên). Không icon trang trí, không emoji, không minh họa.
- Hoạt ảnh tối thiểu. Chỉ có hiệu ứng chuyển trạng thái nhanh (<150ms), không hoạt ảnh vào trang. Hiệu ứng hover vào các button, các dòng. 

### 3.3. Nội dung
- Ít chữ nhất có thể mà vẫn đủ nghĩa. Nhãn là danh từ ngắn ("Biển số", "Kho"), nút là động từ ngắn ("Duyệt", "Từ chối", "Gửi lại").
- Không viết đoạn mô tả, tiêu đề chào mừng hay câu hướng dẫn dài. Cần giải thích thì dùng tooltip một dòng.
- Trạng thái hiển thị bằng chấm màu + một từ (`StatusText`), không dùng badge lớn.
- Ngày giờ ngắn theo ngữ cảnh: hôm nay `14:05`, khác ngày `12/11 14:05`.
- Thông báo (toast) chỉ cho kết quả thao tác của chính người dùng. Cập nhật realtime thì đổi dòng tại chỗ, không bật thông báo.
- Các hành động delete, update, thông báo ... không dùng mặc định của hệ thống. Sử dụng dựa vào form của thư viện. 

### 3.4. Cách kiểm soát
- Mọi màn hình mới phải trả lời được: người điều hành cần làm gì ở đây, và mất bao nhiêu thao tác?

---

## 4. Cấu trúc Thư mục Chuẩn (`frontend/`)

```text
frontend/
├── FRONTEND.md                         # Tài liệu kỹ thuật phân hệ Frontend (tài liệu này)
├── package.json / tsconfig.json / tailwind.config.ts / next.config.mjs
├── tests/e2e/                          # Kiểm thử Playwright cho luồng đăng nhập, duyệt ca, kế hoạch
└── src/
    ├── middleware.ts                   # Chặn route theo phiên đăng nhập (httpOnly cookie) & role (dhvt/admin)
    ├── app/
    │   ├── layout.tsx                  # Root layout: cấu hình font, QueryClientProvider
    │   ├── error.tsx                   # Giao diện xử lý lỗi runtime cấp ứng dụng
    │   ├── not-found.tsx               # Giao diện 404 tối giản
    │   ├── (auth)/
    │   │   └── login/                  # Màn hình đăng nhập cho ĐHVT & Admin
    │   └── (app)/                      # Khu vực nghiệp vụ yêu cầu đăng nhập
    │       ├── layout.tsx              # Bố cục điều hành: Sidebar thu gọn + Thanh trạng thái trên
    │       ├── loading.tsx             # Skeleton/Loading cấp khu vực điều hành
    │       ├── page.tsx                # Tổng quan: Hàng đợi các việc cần xử lý ngay
    │       ├── messages/               # Giám sát tin nhắn Zalo thô (zalo_messages) & lịch sử bóc tách
    │       ├── reviews/                # Duyệt ca bất thường (review_cases) bố cục 2 cột Master-Detail
    │       ├── outbound/               # Quản lý bản tin gửi khách (outbound_messages)
    │       ├── plans/                  # Quản lý & Import Kế hoạch vận chuyển (transport_plans)
    │       ├── directory/              # Quản trị danh mục chuẩn:
    │       │   ├── customers/          # Danh mục Khách hàng (customers)
    │       │   ├── carriers/           # Danh mục Nhà xe / Đội xe (carriers)
    │       │   ├── warehouses/         # Danh mục Kho đóng/trả hàng (warehouses)
    │       │   ├── zalo/               # Danh bạ Nhóm & Tài khoản Zalo (zalo_info)
    │       │   └── routes/             # Ma trận định tuyến thông báo (route_maps)
    │       ├── statistics/             # Báo cáo thống kê & chất lượng bóc tách
    │       └── admin/
    │           └── users/              # Quản lý tài khoản nội bộ ĐHVT & Admin (chỉ role = 'admin')
    ├── features/                       # Tổ chức code theo từng miền nghiệp vụ (Domain-driven):
    │   ├── auth/
    │   ├── messages/
    │   ├── reviews/
    │   │   ├── api.ts                  # Các hàm gọi endpoint thuộc domain reviews
    │   │   ├── hooks.ts                # TanStack Query hooks: useReviews, useResolveReview...
    │   │   ├── columns.tsx             # Định nghĩa cột TanStack Table cho bảng duyệt ca
    │   │   └── components/             # Các component riêng của màn duyệt ca (ReviewDetailPane...)
    │   ├── outbound/
    │   ├── plans/
    │   ├── directory/
    │   ├── statistics/
    │   └── users/
    ├── components/
    │   ├── ui/                         # Các primitive của shadcn/ui đã chuẩn hóa (--radius: 0.25rem)
    │   └── shared/                     # Thành phần dùng chung: DataTable, StatusText, PageHeader, EmptyState, FilterBar
    ├── lib/
    │   ├── api/
    │   │   └── client.ts               # Fetch wrapper tập trung: cấu hình base URL, chuẩn hóa lỗi, bắt 401
    │   ├── auth.ts                     # Tiện ích kiểm tra phiên đăng nhập và phân quyền
    │   ├── format.ts                   # Định dạng chuẩn: Ngày giờ ngắn, Biển số, SĐT, Số Cont, kiểu Id = string
    │   └── utils.ts                    # Hàm tiện ích kết hợp class (cn)
    └── types/
        └── api.d.ts                    # Kiểu dữ liệu tự động sinh từ OpenAPI Backend, tuyệt đối không sửa tay
```

---

## 5. Cấu hình Môi trường & Quy trình Phát triển

Frontend đọc biến môi trường từ tệp `.env` duy nhất đặt tại thư mục gốc của dự án (`vsico_zalo_bot/.env`):

```ini
NEXT_PUBLIC_API_URL=http://localhost:8000
FRONTEND_PORT=3001
```

### Các lệnh vận hành chuẩn:

```bash
cd frontend

# 1. Cài đặt gói phụ thuộc
npm install

# 2. Sinh tự động TypeScript types từ OpenAPI của Backend (khi Backend có thay đổi schema)
npm run gen:types
# (Tương đương: npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.d.ts)

# 3. Khởi chạy máy chủ phát triển (Cổng 3001)
npm run dev

# 4. Kiểm tra quy chuẩn code (ESLint, TypeScript & kiểm tra class bị cấm)
npm run lint

# 5. Đóng gói bản dựng Production
npm run build

# 6. Chạy kiểm thử tự động E2E với Playwright
npx playwright test
```
