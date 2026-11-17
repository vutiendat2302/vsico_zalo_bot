import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { AUTH_COOKIE_NAME, TOKEN_COOKIE_NAME, isJwtExpired } from "./lib/auth";
import { AuthUser } from "./features/auth/types";

/**
 * Xóa cookie phiên đăng nhập hết hạn khỏi phản hồi Next.js Middleware.
 */
function clearExpiredCookies(res: NextResponse): NextResponse {
  res.cookies.delete(AUTH_COOKIE_NAME);
  res.cookies.delete(TOKEN_COOKIE_NAME);
  return res;
}

/**
 * Middleware bảo vệ các tuyến đường nội bộ của VSICO Logistics Dashboard.
 * Kiểm tra phiên đăng nhập, hạn dùng JWT token và phân quyền vai trò (admin / dhvt).
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

  // Đọc cookie phiên và JWT token
  const sessionCookie = request.cookies.get(AUTH_COOKIE_NAME)?.value;
  const tokenCookie = request.cookies.get(TOKEN_COOKIE_NAME)?.value;
  let currentUser: AuthUser | null = null;

  if (sessionCookie) {
    try {
      const decoded = decodeURIComponent(sessionCookie);
      currentUser = JSON.parse(decoded) as AuthUser;
    } catch {
      currentUser = null;
    }
  }

  const hasValidToken = Boolean(tokenCookie && !isJwtExpired(tokenCookie));
  const isAuthenticated = Boolean(currentUser && hasValidToken);
  const isLoginPage = pathname === "/login";

  // 1. Đã đăng nhập hợp lệ nhưng truy cập vào trang login -> Chuyển về Dashboard
  if (isLoginPage && isAuthenticated) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  // Ở trang login nhưng còn sót cookie hết hạn -> Dọn cookie để đăng nhập mới
  if (isLoginPage && (sessionCookie || tokenCookie) && !isAuthenticated) {
    return clearExpiredCookies(NextResponse.next());
  }

  // 2. Chưa đăng nhập hoặc JWT đã hết hạn -> Dọn cookie và chuyển về /login
  if (!isLoginPage && !isAuthenticated) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return clearExpiredCookies(NextResponse.redirect(loginUrl));
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
