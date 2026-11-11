---
name: vsico-frontend
description: >-
  Phát triển, sửa lỗi, refactor, review và kiểm thử Frontend Dashboard tại frontend/
  sử dụng Next.js 14+ (App Router), React 18, TypeScript 5, TanStack Query, TanStack Table,
  Tailwind CSS, shadcn/ui, openapi-typescript và Playwright. Sử dụng khi làm page, features/<domain>,
  shared component (DataTable, StatusText, FilterBar), middleware.ts, authentication (httpOnly cookie,
  RBAC dhvt/admin), SSE/polling realtime, hoặc frontend lint/build/test. Không sử dụng cho Backend-only,
  AI Service, SQL migration, Docker hoặc tài liệu.
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

1. **Bố cục**:
   - Bảng dữ liệu (`DataTable`) là thành phần chính. Không dùng lưới thẻ (card) để liệt kê bản ghi.
   - Trang `reviews/` dùng bố cục 2 cột Master–Detail (danh sách trái, chi tiết phải), không mở modal, không chuyển trang.
   - Bộ lọc `FilterBar` nằm trên bảng, gọn trên 1 hàng, mặc định lọc ngày hôm nay.
   - Không lồng Card/Modal. Modal chỉ dùng để xác nhận hành động nguy hiểm (như hủy chuyến).
2. **Hình thức**:
   - Bo góc tối đa `rounded-sm` (2–4px), `--radius: 0.25rem`. Cấm `rounded-lg`, `rounded-xl`, `rounded-2xl`, `rounded-full` (trừ chấm tròn trạng thái).
   - Không đổ bóng (`shadow-*`), không `bg-gradient-*`, không hiệu ứng mờ kính. Phân tách bằng đường kẻ `1px`.
   - Chữ 13–14px, số liệu dùng `tabular-nums`. Số cont, biển số, seal, SĐT dùng font `monospace`.
   - Không dùng icon trang trí, không dùng emoji.
3. **Nội dung**:
   - Trạng thái hiển thị bằng chấm màu + một từ (`StatusText`), không dùng badge lớn.
   - Ngày giờ ngắn theo ngữ cảnh: hôm nay `14:05`, khác ngày `12/11 14:05`.
   - Toast chỉ bật cho kết quả thao tác của chính người dùng; cập nhật realtime chỉ đổi dòng tại chỗ.

---

## 4. Kiểm tra Trước Khi Hoàn thành

```bash
cd frontend
npm run lint
npm run build
```

Không báo hoàn thành nếu còn lỗi TypeScript, ESLint, vi phạm class bị cấm hoặc lỗi build.
