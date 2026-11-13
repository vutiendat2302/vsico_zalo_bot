import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { AUTH_COOKIE_NAME } from "./lib/auth";
import { AuthUser } from "./features/auth/types";

/**
 * Middleware bảo vệ các tuyến đường nội bộ của VSICO Logistics Dashboard.
 * Kiểm tra phiên đăng nhập qua cookie và phân quyền vai trò (admin / dhvt).
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Bỏ qua các file tĩnh, favicon và api nội bộ của next
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/fonts") ||
    pathname.startsWith("/favicon.ico") ||
    pathname.startsWith("/api")
  ) {
    return NextResponse.next();
  }

  // Đọc cookie phiên
  const sessionCookie = request.cookies.get(AUTH_COOKIE_NAME)?.value;
  let currentUser: AuthUser | null = null;

  if (sessionCookie) {
    try {
      const decoded = decodeURIComponent(sessionCookie);
      currentUser = JSON.parse(decoded) as AuthUser;
    } catch {
      currentUser = null;
    }
  }

  const isLoginPage = pathname === "/login";

  // 1. Đã đăng nhập nhưng truy cập vào trang login -> Chuyển về Dashboard
  if (isLoginPage && currentUser) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  // 2. Chưa đăng nhập và truy cập vào các trang quản trị -> Chuyển hướng về /login
  if (!isLoginPage && !currentUser) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // 3. Phân quyền: Chỉ role admin mới được vào các tuyến /admin/*
  if (pathname.startsWith("/admin") && currentUser?.role !== "admin") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
