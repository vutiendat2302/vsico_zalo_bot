"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  CalendarDays,
  MessageSquare,
  ShieldAlert,
  BarChart3,
  Truck,
  Send,
  Users,
} from "lucide-react";

export default function Navbar() {
  const pathname = usePathname();

  const navItems = [
    { href: "/", label: "Tổng Quan", icon: LayoutDashboard },
    { href: "/plans", label: "Kế Hoạch Vận Chuyển", icon: CalendarDays },
    { href: "/messages", label: "Quản Lý Tin Nhắn", icon: MessageSquare },
    { href: "/results", label: "Kết Quả Tin Nhắn", icon: Send },
    { href: "/reviews", label: "Chờ Duyệt (Reviews)", icon: ShieldAlert },
    { href: "/groups", label: "Quản Lý Nhóm", icon: Users },
    { href: "/statistics", label: "Thống Kê Taxonomy", icon: BarChart3 },
  ];

  return (
    <header className="bg-slate-900 border-b border-slate-800 text-white sticky top-0 z-50 shadow-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Brand */}
          <div className="flex items-center space-x-3">
            <div className="bg-blue-600 p-2 rounded-lg flex items-center justify-center">
              <Truck className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-bold text-lg tracking-wide text-white">VSICO LOGISTICS</span>
              <span className="ml-2 text-xs font-semibold px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">
                BOT ZALO OA
              </span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="hidden md:flex space-x-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center space-x-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-blue-600 text-white shadow-sm"
                      : "text-slate-300 hover:bg-slate-800 hover:text-white"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Right Status */}
          <div className="flex items-center space-x-3">
            <div className="flex items-center space-x-2 bg-emerald-950/60 border border-emerald-600/40 px-3 py-1 rounded-full text-xs text-emerald-400">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span className="font-medium">Backend Live (Real API)</span>
            </div>
          </div>
        </div>
      </div>

      {/* Mobile navigation */}
      <div className="md:hidden border-t border-slate-800 px-2 py-2 flex overflow-x-auto space-x-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center space-x-1.5 px-2.5 py-1.5 rounded text-xs font-medium whitespace-nowrap ${
                isActive ? "bg-blue-600 text-white" : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </div>
    </header>
  );
}
