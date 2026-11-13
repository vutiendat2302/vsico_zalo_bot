"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { DashboardSummary, getDashboardSummary, triggerFifoQueue } from "@/lib/api";
import { toast } from "@/components/shared/Toast";

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
      setError(err.message || "Không thể kết nối Backend API.");
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
      toast.success("Đã kích hoạt xử lý hàng đợi FIFO thành công.");
      await loadData();
    } catch (err: any) {
      toast.error("Lỗi xử lý hàng đợi: " + err.message);
    } finally {
      setIsDraining(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <p className="text-slate-500 text-sm">Đang tải dữ liệu...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="bg-white border border-slate-200 p-6 rounded-sm text-center max-w-md mx-auto my-12">
        <h3 className="text-base font-bold text-slate-900">Lỗi kết nối Backend</h3>
        <p className="text-slate-500 text-sm mt-2">{error}</p>
        <button
          onClick={loadData}
          className="mt-4 px-4 py-2 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-xs font-medium transition"
        >
          Thử lại
        </button>
      </div>
    );
  }

  const kpi = data?.kpi;
  const q = data?.fifo_queue;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <h1 className="text-xl font-bold text-slate-900">
          Tổng quan vận hành
        </h1>

        <div className="flex items-center space-x-2">
          <label className="flex items-center space-x-2 text-xs text-slate-900 bg-white border border-slate-200 px-3 py-1.5 rounded-sm cursor-pointer hover:bg-slate-50">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-slate-300 text-purple-700 focus:ring-0"
            />
            <span>Tự làm mới (10s)</span>
          </label>

          <button
            onClick={loadData}
            disabled={loading}
            className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-900 rounded-sm text-xs font-medium border border-slate-200 transition"
          >
            {loading ? "Đang tải..." : "Làm mới"}
          </button>
        </div>
      </div>

      {/* 4 Core KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-xs font-medium text-slate-500">Tổng tin vào</div>
          <div className="text-2xl font-bold text-slate-900 mt-2">
            {kpi?.total_messages_received || 0}
          </div>
        </div>

        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-xs font-medium text-slate-500">Đã xử lý</div>
          <div className="text-2xl font-bold text-slate-900 mt-2">
            {kpi?.processed_messages || 0}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            {kpi?.processed_rate_percent || 0}%
          </div>
        </div>

        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-xs font-medium text-slate-500">Cần duyệt</div>
          <div className="text-2xl font-bold text-purple-700 mt-2">
            {kpi?.needs_review_messages || 0}
          </div>
          <Link
            href="/reviews"
            className="text-[11px] text-purple-700 hover:underline inline-block mt-1"
          >
            {kpi?.reviews_pending || 0} ca chờ duyệt
          </Link>
        </div>

        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-xs font-medium text-slate-500">Tin rác</div>
          <div className="text-2xl font-bold text-slate-900 mt-2">
            {kpi?.ignored_chat_messages || 0}
          </div>
        </div>
      </div>

      {/* Bố cục 2 cột: Trái (Thống kê theo ngày + Hàng đợi FIFO), Phải (Tin nhắn mới nhất) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* Cột trái */}
        <div className="space-y-4">
          <div className="bg-white border border-slate-200 p-4 rounded-sm">
            <h2 className="text-sm font-semibold text-slate-900 mb-3">Thống kê theo ngày</h2>
            <div className="space-y-2 max-h-[260px] overflow-y-auto pr-1">
              {data?.daily_breakdown.map((d) => (
                <div
                  key={d.date}
                  className="bg-slate-50 border border-slate-200 p-2.5 rounded-sm flex items-center justify-between text-xs"
                >
                  <div>
                    <div className="font-semibold text-slate-900">{d.date}</div>
                    <div className="text-slate-500 mt-0.5">{d.total} tin</div>
                  </div>
                  <div className="flex space-x-2 text-[11px]">
                    <span className="text-slate-900 bg-white border border-slate-200 px-2 py-0.5 rounded-sm">
                      OK: {d.processed}
                    </span>
                    <span className="text-purple-700 bg-purple-50 border border-purple-200 px-2 py-0.5 rounded-sm">
                      Duyệt: {d.needs_review}
                    </span>
                    <span className="text-slate-500 bg-white border border-slate-200 px-2 py-0.5 rounded-sm">
                      Rác: {d.ignored}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Hàng đợi FIFO */}
          <div className="bg-white border border-slate-200 p-4 rounded-sm">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h2 className="text-sm font-semibold text-slate-900">
                Hàng đợi xử lý (FIFO)
              </h2>
              <button
                onClick={handleDrainQueue}
                disabled={isDraining}
                className="text-xs bg-purple-700 hover:bg-purple-800 disabled:bg-purple-400 text-white px-3 py-1.5 rounded-sm font-medium transition"
              >
                {isDraining ? "Đang xử lý..." : "Vét hàng đợi"}
              </button>
            </div>

            <div className="grid grid-cols-3 gap-3 mt-3 text-center">
              <div className="bg-slate-50 border border-slate-200 p-3 rounded-sm">
                <div className="text-xs text-slate-500">Đang chờ</div>
                <div className="text-lg font-bold text-purple-700 mt-1">
                  {q?.queue_size || 0}
                </div>
              </div>
              <div className="bg-slate-50 border border-slate-200 p-3 rounded-sm">
                <div className="text-xs text-slate-500">Đã nạp</div>
                <div className="text-lg font-bold text-slate-900 mt-1">
                  {q?.total_enqueued || 0}
                </div>
              </div>
              <div className="bg-slate-50 border border-slate-200 p-3 rounded-sm">
                <div className="text-xs text-slate-500">Đã xử lý</div>
                <div className="text-lg font-bold text-slate-900 mt-1">
                  {q?.total_processed || 0}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Cột phải: Tin nhắn mới nhất */}
        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-900">Tin nhắn mới nhất</h2>
            <Link
              href="/messages"
              className="text-xs text-purple-700 hover:underline font-medium"
            >
              Xem tất cả
            </Link>
          </div>

          <div className="space-y-2.5 max-h-[440px] overflow-y-auto pr-1">
            {data?.recent_messages.map((m) => (
              <div
                key={m.id}
                className="bg-slate-50 border border-slate-200 p-3 rounded-sm text-xs"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-slate-900">{m.sender_name}</span>
                    <span className="text-slate-500">{m.group_id}</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="text-slate-500">{m.sent_at?.slice(0, 16).replace("T", " ")}</span>
                    <span className="px-2 py-0.5 rounded-sm font-medium bg-white border border-slate-200 text-purple-700">
                      {m.processing_status}
                    </span>
                  </div>
                </div>

                <div className="text-slate-900 font-mono mt-1.5 whitespace-pre-line bg-white p-2 rounded-sm border border-slate-200">
                  {m.raw_text}
                </div>

                {(m.truck_plates.length > 0 || m.containers.length > 0) && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {m.truck_plates.map((p, i) => (
                      <span
                        key={i}
                        className="bg-white text-slate-900 px-2 py-0.5 rounded-sm text-[11px] border border-slate-200 font-mono"
                      >
                        {p}
                      </span>
                    ))}
                    {m.containers.map((c, i) => (
                      <span
                        key={i}
                        className="bg-purple-50 text-purple-700 px-2 py-0.5 rounded-sm text-[11px] border border-purple-200 font-mono"
                      >
                        {c}
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
