"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Inbox,
  CheckCircle2,
  AlertTriangle,
  Send,
  MessageCircleOff,
  CalendarCheck,
  RefreshCw,
  Gauge,
  Clock,
  ArrowRight,
  Truck,
  Box,
} from "lucide-react";
import { DashboardSummary, getDashboardSummary, triggerFifoQueue } from "@/lib/api";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDraining, setIsDraining] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await getDashboardSummary();
      setData(res);
    } catch (err: any) {
      setError(err.message || "Không thể kết nối đến Backend API (cổng 8000).");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    if (!autoRefresh) return;
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  const handleDrainQueue = async () => {
    try {
      setIsDraining(true);
      await triggerFifoQueue();
      await loadData();
    } catch (err: any) {
      alert("Lỗi khi kích hoạt xử lý hàng đợi: " + err.message);
    } finally {
      setIsDraining(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-4">
        <RefreshCw className="w-8 h-8 text-blue-500 animate-spin" />
        <p className="text-slate-400 text-sm">Đang tải dữ liệu từ máy chủ...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="bg-red-950/40 border border-red-800/60 p-6 rounded-xl text-center max-w-lg mx-auto my-12">
        <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-3" />
        <h3 className="text-lg font-bold text-red-200">Không thể kết nối API Backend</h3>
        <p className="text-slate-400 text-sm mt-2">{error}</p>
        <button
          onClick={loadData}
          className="mt-4 px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg text-sm font-medium transition"
        >
          Thử lại
        </button>
      </div>
    );
  }

  const kpi = data?.kpi;
  const rl = data?.rate_limiter;
  const q = data?.fifo_queue;

  return (
    <div className="space-y-6">
      {/* Top Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            Bảng Giám Sát Vận Hành Zalo Bot
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Dữ liệu thời gian thực từ Backend MySQL • Tự động điều phối hàng đợi & kiểm soát hạn mức Zalo OA
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <label className="flex items-center space-x-2 text-xs text-slate-400 bg-slate-900 border border-slate-800 px-3 py-2 rounded-lg cursor-pointer hover:bg-slate-800 transition">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-blue-600 focus:ring-0"
            />
            <span>Tự động làm mới (10s)</span>
          </label>

          <button
            onClick={loadData}
            disabled={loading}
            className="flex items-center space-x-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Làm mới</span>
          </button>
        </div>
      </div>

      {/* 6 Core KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        {/* 1. Tổng tin vào */}
        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Tổng tin vào</span>
            <div className="p-2 bg-blue-500/10 text-blue-400 rounded-lg">
              <Inbox className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-bold text-white">{kpi?.total_messages_received || 0}</div>
            <p className="text-[11px] text-slate-500 mt-0.5">Tin Zalo 1-1 & Nhóm</p>
          </div>
        </div>

        {/* 2. Đã xử lý */}
        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Đã xử lý (OK)</span>
            <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-bold text-emerald-400">{kpi?.processed_messages || 0}</div>
            <p className="text-[11px] text-emerald-500/80 mt-0.5">
              Đạt {kpi?.processed_rate_percent || 0}% tổng số tin
            </p>
          </div>
        </div>

        {/* 3. Tin cần duyệt */}
        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Cần duyệt</span>
            <div className="p-2 bg-amber-500/10 text-amber-400 rounded-lg">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-bold text-amber-400">{kpi?.needs_review_messages || 0}</div>
            <Link
              href="/reviews"
              className="text-[11px] text-amber-400/90 hover:underline flex items-center gap-1 mt-0.5"
            >
              <span>{kpi?.reviews_pending || 0} ca chờ duyệt</span>
              <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
        </div>

        {/* 4. Tin đã gửi (Bot replies) */}
        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Tin đã gửi</span>
            <div className="p-2 bg-purple-500/10 text-purple-400 rounded-lg">
              <Send className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-bold text-purple-400">{kpi?.bot_replies_sent || 0}</div>
            <p className="text-[11px] text-slate-500 mt-0.5">Nhắc lỗi / cảnh báo nhà xe</p>
          </div>
        </div>

        {/* 5. Tin rác / Xã giao */}
        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Tin rác / Xã giao</span>
            <div className="p-2 bg-slate-500/10 text-slate-400 rounded-lg">
              <MessageCircleOff className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-bold text-slate-400">{kpi?.ignored_chat_messages || 0}</div>
            <p className="text-[11px] text-slate-500 mt-0.5">Lọc nhanh &lt; 0.05ms</p>
          </div>
        </div>

        {/* 6. Kế hoạch vận chuyển */}
        <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Kế hoạch xe</span>
            <div className="p-2 bg-sky-500/10 text-sky-400 rounded-lg">
              <CalendarCheck className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-bold text-sky-400">{data?.plans_summary.total || 0}</div>
            <p className="text-[11px] text-slate-500 mt-0.5">
              Xuất: {data?.plans_summary.dong || 0} | Nhập: {data?.plans_summary.tra || 0}
            </p>
          </div>
        </div>
      </div>

      {/* Row 2: Rate Limiting & Queue Management Status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Rate Limiting (Zalo OA High-Throughput Protection) */}
        <div className="bg-slate-900/90 border border-slate-800 p-5 rounded-xl">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center space-x-2">
              <Gauge className="w-5 h-5 text-indigo-400" />
              <h2 className="text-base font-semibold text-white">
                Kiểm Soát Hạn Mức Tải Zalo OA (Rate Limiting)
              </h2>
            </div>
            <span
              className={`text-xs px-2.5 py-0.5 rounded-full font-medium border ${
                rl?.is_throttled
                  ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                  : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
              }`}
            >
              {rl?.is_throttled ? "Đang Điều Tiết Giãn Cách" : "Hoạt Động Bình Thường"}
            </span>
          </div>

          <p className="text-xs text-slate-400 mt-3 leading-relaxed">
            Áp dụng thuật toán <strong>Token Bucket</strong> để bảo vệ kết nối khi hàng nghìn nhóm gửi tin cùng lúc,
            đảm bảo không bị Zalo chặn mã 429 Too Many Requests.
          </p>

          <div className="grid grid-cols-3 gap-3 mt-4 text-center">
            <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-lg">
              <div className="text-xs text-slate-400">Giới hạn tối đa</div>
              <div className="text-lg font-bold text-white mt-1">
                {rl?.max_requests_per_second || 10} <span className="text-xs font-normal">req/s</span>
              </div>
            </div>
            <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-lg">
              <div className="text-xs text-slate-400">Token khả dụng</div>
              <div className="text-lg font-bold text-indigo-400 mt-1">
                {rl?.available_tokens || 0} / {rl?.burst_capacity || 20}
              </div>
            </div>
            <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-lg">
              <div className="text-xs text-slate-400">Số lần nghẽn (429)</div>
              <div className="text-lg font-bold text-emerald-400 mt-1">
                {rl?.total_429_hits || 0}
              </div>
            </div>
          </div>
        </div>

        {/* FIFO Queue Status */}
        <div className="bg-slate-900/90 border border-slate-800 p-5 rounded-xl">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center space-x-2">
              <Clock className="w-5 h-5 text-blue-400" />
              <h2 className="text-base font-semibold text-white">
                Hàng Đợi Xử Lý Vào Trước - Ra Trước (FIFO)
              </h2>
            </div>
            <button
              onClick={handleDrainQueue}
              disabled={isDraining}
              className="text-xs bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white px-3 py-1 rounded-md font-medium transition"
            >
              {isDraining ? "Đang xử lý..." : "Vét hàng đợi"}
            </button>
          </div>

          <p className="text-xs text-slate-400 mt-3 leading-relaxed">
            Tin nhắn gửi đến từ hàng nghìn nhóm được đưa vào hàng đợi tuần tự, đảm bảo tin đến trước được bóc tách và phản hồi trước, tuyệt đối không bị mất dữ liệu.
          </p>

          <div className="grid grid-cols-3 gap-3 mt-4 text-center">
            <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-lg">
              <div className="text-xs text-slate-400">Tin đang chờ</div>
              <div className="text-lg font-bold text-amber-400 mt-1">
                {q?.queue_size || 0}
              </div>
            </div>
            <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-lg">
              <div className="text-xs text-slate-400">Đã nạp hàng đợi</div>
              <div className="text-lg font-bold text-white mt-1">
                {q?.total_enqueued || 0}
              </div>
            </div>
            <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-lg">
              <div className="text-xs text-slate-400">Đã tiêu thụ</div>
              <div className="text-lg font-bold text-emerald-400 mt-1">
                {q?.total_processed || 0}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Row 3: Daily Timeline & Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Daily Breakdown */}
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
          <h2 className="text-base font-semibold text-white mb-4">Thống Kê Theo Ngày</h2>
          <div className="space-y-3 max-h-[360px] overflow-y-auto pr-1">
            {data?.daily_breakdown.map((d) => (
              <div
                key={d.date}
                className="bg-slate-950/50 border border-slate-800/80 p-3 rounded-lg flex items-center justify-between text-xs"
              >
                <div>
                  <div className="font-semibold text-white">{d.date}</div>
                  <div className="text-slate-500 mt-0.5">Tổng: {d.total} tin</div>
                </div>
                <div className="flex space-x-2">
                  <span className="text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded">
                    ✓ {d.processed}
                  </span>
                  <span className="text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded">
                    ⚠ {d.needs_review}
                  </span>
                  <span className="text-slate-400 bg-slate-500/10 px-2 py-0.5 rounded">
                    ✕ {d.ignored}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recent Message Feed */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 p-5 rounded-xl">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-white">Tin Nhắn Zalo Mới Nhất</h2>
            <Link
              href="/messages"
              className="text-xs text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1"
            >
              <span>Xem tất cả tin nhắn</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="space-y-2.5 max-h-[360px] overflow-y-auto pr-1">
            {data?.recent_messages.map((m) => (
              <div
                key={m.id}
                className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-lg text-xs hover:border-slate-700 transition"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-blue-400">{m.sender_name}</span>
                    <span className="text-slate-500">Group: {m.group_id}</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="text-slate-500">{m.sent_at?.slice(0, 16).replace("T", " ")}</span>
                    <span
                      className={`px-2 py-0.5 rounded font-medium ${
                        m.processing_status === "processed"
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                          : m.processing_status === "needs_review"
                          ? "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                          : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      {m.processing_status}
                    </span>
                  </div>
                </div>

                <div className="text-slate-300 font-mono mt-1.5 whitespace-pre-line bg-slate-900/60 p-2 rounded border border-slate-800/50">
                  {m.raw_text}
                </div>

                {(m.truck_plates.length > 0 || m.containers.length > 0) && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {m.truck_plates.map((p, i) => (
                      <span
                        key={i}
                        className="inline-flex items-center gap-1 bg-blue-950/60 text-blue-300 px-2 py-0.5 rounded text-[11px] border border-blue-800/50"
                      >
                        <Truck className="w-3 h-3" />
                        <span>{p}</span>
                      </span>
                    ))}
                    {m.containers.map((c, i) => (
                      <span
                        key={i}
                        className="inline-flex items-center gap-1 bg-purple-950/60 text-purple-300 px-2 py-0.5 rounded text-[11px] border border-purple-800/50"
                      >
                        <Box className="w-3 h-3" />
                        <span>{c}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
