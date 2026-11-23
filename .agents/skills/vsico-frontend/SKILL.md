---
name: vsico-frontend
description: >-
  Phát triển, sửa lỗi, refactor, review và kiểm thử Frontend Dashboard tại frontend/
  sử dụng Next.js 16+ (App Router, Turbopack), React 19, TypeScript 5, Tailwind CSS v4,
  ESLint 9, TanStack Query, TanStack Table, shadcn/ui, openapi-typescript và Playwright.
  Sử dụng khi làm page, features/<domain>, shared component (DataTable, StatusText, FilterBar),
  middleware.ts/proxy, authentication (httpOnly cookie, RBAC dhvt/admin), SSE/polling realtime,
  hoặc frontend lint/build/test. Không sử dụng cho Backend-only, AI Service, SQL migration,
  Docker hoặc tài liệu.
---
# VSICO Frontend — Engineering Standards & Development Guide

Làm việc trong thư mục `frontend/`. Tài liệu kiến trúc chuẩn nằm tại `frontend/FRONTEND.md`.

---

## 1. Cấu trúc Phân lớp Theo Miền Nghiệp vụ (`frontend/src/`)

Không gom toàn bộ endpoint vào một file `lib/api.ts` duy nhất và không viết lặp lại bảng/trạng thái ở từng trang. Tổ chức code theo đúng cấu trúc sau:

```text
frontend/
├── tests/e2e/                      # Kiểm thử Playwright (cho phép dùng MSW / route mocking)
└── src/
    ├── middleware.ts               # Chặn route theo đăng nhập (httpOnly cookie) & role (dhvt / admin)
    ├── app/
    │   ├── layout.tsx              # Root: font, QueryClientProvider
    │   ├── error.tsx / not-found.tsx
    │   ├── (auth)/login/           # Đăng nhập
    │   └── (app)/                  # Khu vực cần đăng nhập
    │       ├── layout.tsx          # Sidebar + thanh trên
    │       ├── loading.tsx
    │       ├── page.tsx            # Tổng quan: hàng đợi cần xử lý ngay
    │       ├── messages/           # Tin nhắn Zalo thô (zalo_messages)
    │       ├── reviews/            # Duyệt ca (review_cases) bố cục 2 cột Master–Detail
    │       ├── outbound/           # Bản tin gửi khách (outbound_messages)
    │       ├── plans/              # Kế hoạch vận chuyển (transport_plans)
    │       ├── directory/          # Danh mục: customers, carriers, warehouses, zalo, routes
    │       ├── statistics/         # Thống kê
    │       └── admin/users/        # Quản lý tài khoản nội bộ (chỉ role = 'admin')
    ├── features/<domain>/          # Mỗi domain một thư mục (reviews, messages, outbound, plans, directory, users):
    │   ├── api.ts                  # Gọi endpoint của riêng domain này qua lib/api/client.ts
    │   ├── hooks.ts                # TanStack Query hooks (useReviews, useResolveReview...)
    │   ├── columns.tsx             # Định nghĩa cột TanStack Table
    │   └── components/             # Component đặc thù của domain
    ├── components/
    │   ├── ui/                     # shadcn/ui primitive (--radius: 0.25rem)
    │   └── shared/                 # DataTable, StatusText, PageHeader, EmptyState, FilterBar
    ├── lib/
    │   ├── api/client.ts           # Fetch wrapper dùng chung: base URL, chuẩn hóa lỗi, bắt 401
    │   ├── auth.ts                 # Xử lý phiên & kiểm tra quyền (dhvt / admin)
    │   ├── format.ts               # Định dạng ngày giờ ngắn, biển số, SĐT, số cont, type Id = string
    │   └── utils.ts
    └── types/api.d.ts              # Sinh tự động từ OpenAPI (openapi-typescript), KHÔNG sửa tay
```

---

## 2. Quy chuẩn Dữ liệu, Kiểu & Realtime

1. **Zero Mock Data Policy (Phạm vi rõ ràng)**:
   - **Code chạy thật (`src/`)**: 100% lấy từ Backend API. Nghiêm cấm tạo mảng dữ liệu giả lập. Không có dữ liệu thì render `EmptyState` một dòng.
   - **Code kiểm thử (`tests/`)**: Được phép dùng MSW (Mock Service Worker) hoặc Playwright route mocking để test.
2. **Snowflake ID (`type Id = string`)**:
   - Định nghĩa một lần duy nhất `export type Id = string;`.
   - Backend trả Snowflake ID 64-bit dưới dạng chuỗi trong JSON; Frontend giữ nguyên kiểu `string`, không ép sang `number`.
3. **Sinh kiểu tự động (`openapi-typescript`)**:
   - Không viết tay các interface DTO trùng lặp với Backend. Sinh tự động vào `src/types/api.d.ts` từ schema OpenAPI của FastAPI.
4. **Quản lý Server State & Realtime**:
   - Dùng **TanStack Query** cho toàn bộ việc lấy dữ liệu, cache và mutation; dùng **TanStack Table** cho `DataTable`.
   - **Realtime**: Sử dụng **SSE (`/api/events/stream`)** để nhận sự kiện mới và gọi `queryClient.invalidateQueries` cập nhật tại chỗ, kết hợp **Polling có chu kỳ (`refetchInterval: 10000` khi tab active)** làm dự phòng.
5. **Xác thực & Phân quyền (`Auth`)**:
   - Lưu token trong **`httpOnly` cookie**, tuyệt đối không lưu vào `localStorage`.
   - Kiểm tra đăng nhập và phân quyền (`dhvt` / `admin`) tại `src/middleware.ts`.

---

## 3. Quy chuẩn Thiết kế Giao diện Điều hành (Strict UI Rules)

### 3.1. Bố cục

- Thông minh, có dashboard thống kê, chia các trang hợp lý.
- Hành động nằm ngay tại dòng hoặc ở thanh cố định. Hỗ trợ phím tắt cho thao tác lặp lại (lên/xuống chọn dòng, Enter mở, phím duyệt/từ chối).
- Không Card/Modal lồng nhau.

### 3.2. Hình thức

- Không đổ bóng, không gradient, không hiệu ứng mờ kính. Phân tách bằng đường kẻ `1px`.
- Bảng màu: nền trắng/xám nhạt, màu chủ đạo tím (`purple-700`). Tối đa 3–4 màu trong một màn hình. Màu ngữ nghĩa (đỏ, vàng, xanh) chỉ dùng cho chấm trạng thái hoặc chữ trạng thái nhẹ, không lạm dụng nhiều màu viền/nền rối mắt trong cùng một thẻ chi tiết.
- Cỡ chữ dễ đọc (tăng 2 size so với bản cũ): văn bản nội dung và modal dùng **14–16px (`text-sm` / `text-base`)**, tiêu đề mục `text-lg`, tiêu đề trang `text-2xl`; hạn chế dùng chữ nhỏ `10–11px`.
- Thống nhất kiểu chữ `font-sans` sạch sẽ trong các vùng chi tiết/modal, tránh trộn quá nhiều font chữ (`font-mono` + `font-sans`), cỡ chữ và màu sắc khác nhau trong cùng một khối; số liệu dùng `tabular-nums`.
- Icon chỉ dùng khi thay được chữ (nút đóng, sắp xếp, đồng bộ). Không icon trang trí, không emoji, không minh họa.
- Hoạt ảnh tối thiểu. Chỉ có hiệu ứng chuyển trạng thái nhanh (<150ms), không hoạt ảnh vào trang. Hiệu ứng hover vào các button, các dòng.

### 3.3. Nội dung & Ngôn ngữ Thân thiện Người dùng

- **Tuyệt đối không hiển thị ID nội bộ hoặc biến hệ thống**: Không đưa Snowflake ID, `zalo_group_id`, `zalo_message_id`, mã biến tiếng Anh (`processed`, `needs_review`, `tu_do`, `unmatched`, `SHIPPING_NOT_FOUND`, `carrier_id`, v.v.) lên giao diện. Luôn hiển thị bằng **tên hiển thị thật** (tên nhóm Zalo, tên khách hàng) và **nhãn tiếng Việt tự nhiên**.
- **Không mở ngoặc giải thích thuật ngữ hệ thống**: Hệ thống xử lý đặt biến tiếng Anh nhưng hiển thị phải thuần tiếng Việt, gọn gàng. Không viết kiểu `Thành công (processed)`, `Đóng hàng (Xuất - X)`, `Phân hạng vỏ (Grade)`, `Lịch trình điểm (1 điểm)`, `Hợp lệ ISO 6346`.
- Ít chữ nhất có thể mà vẫn đủ nghĩa. Nhãn là danh từ ngắn ("Biển số", "Kho"), nút là động từ ngắn ("Duyệt", "Từ chối", "Gửi lại").
- Không viết đoạn mô tả, tiêu đề chào mừng hay câu hướng dẫn dài.
- Nội dung tin nhắn dài trong bảng danh sách phải rút gọn một dòng kết thúc bằng `...` để người dùng bấm vào chi tiết xem đầy đủ.
- Không lặp lại thanh đếm `"Hiển thị X / Y dòng"` ở đầu bảng nếu footer phân trang của bảng đã hiển thị số dòng và số trang.
- Trạng thái hiển thị bằng chấm màu + chữ ngắn (`StatusText`), không dùng badge lớn.
- Ngày giờ ngắn theo ngữ cảnh: hôm nay `14:05`, khác ngày `12/11 14:05`.
- Thông báo (toast) chỉ cho kết quả thao tác của chính người dùng. Cập nhật realtime thì đổi dòng tại chỗ, không bật thông báo.
- Các hành động delete, update, thông báo ... không dùng mặc định của hệ thống (`alert`/`confirm`/`prompt`). Sử dụng modal/form của thư viện.

### 3.4. Cách kiểm soát

- Mọi màn hình mới phải trả lời được: người điều hành cần làm gì ở đây, và mất bao nhiêu thao tác?

---

## 4. Kiểm tra Trước Khi Hoàn thành

```bash
cd frontend
npm run lint
npm run build
```

Không báo hoàn thành nếu còn lỗi TypeScript, ESLint, vi phạm class bị cấm hoặc lỗi build.
