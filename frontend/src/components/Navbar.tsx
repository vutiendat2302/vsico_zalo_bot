"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  CalendarDays,
  MessageSquare,
  ShieldAlert,
  Truck,
  Send,
  Users,
  LogOut,
  UserCheck,
  FlaskConical,
} from "lucide-react";
import { getClientSession, clearClientSession } from "@/lib/auth";
import { AuthUser } from "@/features/auth/types";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    setCurrentUser(getClientSession());
  }, [pathname]);

  // Không hiển thị Navbar trên trang Đăng nhập
  if (pathname === "/login") {
    return null;
  }

  const handleLogout = () => {
    clearClientSession();
    setCurrentUser(null);
    router.push("/login");
    router.refresh();
  };

  const navItems = [
    { href: "/", label: "Tổng quan", icon: LayoutDashboard },
    { href: "/plans", label: "Kế hoạch", icon: CalendarDays },
    { href: "/messages", label: "Tin nhắn", icon: MessageSquare },
    { href: "/results", label: "Kết quả gửi", icon: Send },
    { href: "/reviews", label: "Chờ duyệt", icon: ShieldAlert },
    { href: "/groups", label: "Nhóm Zalo", icon: Users },
    { href: "/sandbox", label: "Thử nghiệm", icon: FlaskConical },
    ...(currentUser?.role === "admin"
      ? [{ href: "/admin/users", label: "Người dùng", icon: UserCheck }]
      : []),
  ];

  return (
    <header className="bg-white border-b border-slate-200 text-slate-900 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Logo & Brand */}
          <div className="flex items-center space-x-3">
            <Link href="/" className="flex items-center space-x-2.5">
              <div className="bg-purple-700 w-7 h-7 rounded-sm flex items-center justify-center text-white">
                <Truck className="w-4 h-4" />
              </div>
              <span className="font-bold text-sm tracking-wide text-slate-900">
                VSICO
              </span>
            </Link>
          </div>

          {/* Navigation Links */}
          <nav className="hidden md:flex items-center space-x-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center space-x-1.5 px-2.5 py-1.5 rounded-sm text-xs transition-colors duration-100 ${
                    isActive
                      ? "bg-purple-50 text-purple-700 font-semibold border-b-2 border-purple-700"
                      : "text-slate-600 hover:text-slate-900 hover:bg-slate-100/70"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Right Auth */}
          <div className="flex items-center space-x-3">
            {currentUser ? (
              <div className="flex items-center space-x-2">
                <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-sm border border-purple-200 bg-purple-50/50 text-xs">
                  <UserCheck className="w-3.5 h-3.5 text-purple-700" />
                  <span className="font-semibold text-purple-700 uppercase">
                    {currentUser.role}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleLogout}
                  title="Đăng xuất khỏi hệ thống"
                  className="p-1.5 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-sm border border-transparent hover:border-red-200 transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <Link
                href="/login"
                className="px-2.5 py-1 text-xs font-medium text-purple-700 border border-purple-200 bg-purple-50 hover:bg-purple-100 rounded-sm transition-colors"
              >
                Đăng nhập
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Mobile navigation */}
      <div className="md:hidden border-t border-slate-200 px-2 py-1.5 flex overflow-x-auto space-x-1 bg-slate-50">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center space-x-1 px-2 py-1 rounded-sm text-xs whitespace-nowrap transition-colors ${
                isActive
                  ? "bg-purple-100 text-purple-800 font-semibold"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Icon className="w-3 h-3" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </div>
    </header>
  );
}
