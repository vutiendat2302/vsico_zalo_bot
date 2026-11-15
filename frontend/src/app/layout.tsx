import type { Metadata } from "next";
import "./globals.css";
import Navbar from "@/components/Navbar";
import { ToastProvider } from "@/components/shared/Toast";

export const metadata: Metadata = {
  title: "VSICO Logistics — Hệ Thống Điều Hành & Giám Sát Vận Tải Zalo",
  description: "Hệ thống tự động hóa tiếp nhận, bóc tách, đối chiếu kế hoạch và điều phối thông báo vận tải container đa kênh.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi">
      <body className="bg-slate-50 text-slate-900 min-h-screen flex flex-col font-sans antialiased">
        <ToastProvider>
          <Navbar />
          <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 pb-10 flex flex-col">
            {children}
          </main>
        </ToastProvider>
      </body>
    </html>
  );
}
