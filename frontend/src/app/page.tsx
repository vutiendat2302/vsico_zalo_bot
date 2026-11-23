"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { DashboardSummary, getDashboardSummary, triggerFifoQueue } from "@/lib/api";
import { getMessageStatusMeta } from "@/lib/utils";
import { toast } from "@/components/shared/Toast";

/**
 * Trang tổng quan vận hành điều phối Zalo và hàng đợi xử lý.
 */
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
      setError(err.message || "Không thể kết nối máy chủ.");
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
      toast.success("Đã kích hoạt xử lý hàng đợi thành công.");
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
        <p className="text-slate-500 text-base">Đang tải dữ liệu...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="bg-white border border-slate-200 p-6 rounded-sm text-center max-w-md mx-auto my-12">
        <h3 className="text-lg font-bold text-slate-900">Lỗi kết nối hệ thống</h3>
        <p className="text-slate-500 text-base mt-2">{error}</p>
        <button
          onClick={loadData}
          className="mt-4 px-4 py-2 bg-purple-700 hover:bg-purple-800 text-white rounded-sm text-sm font-medium transition"
        >
          Thử lại
        </button>
      </div>
    );
  }

  const kpi = data?.kpi;
  const q = data?.fifo_queue;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <h1 className="text-2xl font-bold text-slate-900">
          Tổng quan vận hành
        </h1>

        <div className="flex items-center space-x-2">
          <label className="flex items-center space-x-2 text-sm text-slate-900 bg-white border border-slate-200 px-3 py-1.5 rounded-sm cursor-pointer hover:bg-slate-50">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-slate-300 text-purple-700 focus:ring-0"
            />
            <span>Tự làm mới</span>
          </label>

          <button
            onClick={loadData}
            disabled={loading}
            className="px-3.5 py-1.5 bg-white hover:bg-slate-50 text-slate-900 rounded-sm text-sm font-medium border border-slate-200 transition"
          >
            {loading ? "Đang tải..." : "Làm mới"}
          </button>
        </div>
      </div>

      {/* 4 Core KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-sm font-medium text-slate-500">Tổng tin vào</div>
          <div className="text-3xl font-bold text-slate-900 mt-2 tabular-nums">
            {kpi?.total_messages_received || 0}
          </div>
        </div>

        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-sm font-medium text-slate-500">Đã xử lý</div>
          <div className="text-3xl font-bold text-slate-900 mt-2 tabular-nums">
            {kpi?.processed_messages || 0}
          </div>
          <div className="text-sm text-slate-500 mt-1 tabular-nums">
            {kpi?.processed_rate_percent || 0}%
          </div>
        </div>

        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-sm font-medium text-slate-500">Cần duyệt</div>
          <div className="text-3xl font-bold text-purple-700 mt-2 tabular-nums">
            {kpi?.needs_review_messages || 0}
          </div>
          <Link
            href="/reviews"
            className="text-sm text-purple-700 hover:underline inline-block mt-1 font-medium"
          >
            {kpi?.reviews_pending || 0} ca chờ duyệt
          </Link>
        </div>

        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="text-sm font-medium text-slate-500">Tin xã giao</div>
          <div className="text-3xl font-bold text-slate-900 mt-2 tabular-nums">
            {kpi?.ignored_chat_messages || 0}
          </div>
        </div>
      </div>

      {/* Bố cục 2 cột: Trái (Thống kê theo ngày + Hàng đợi), Phải (Tin nhắn mới nhất) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* Cột trái */}
        <div className="space-y-4">
          <div className="bg-white border border-slate-200 p-4 rounded-sm">
            <h2 className="text-lg font-semibold text-slate-900 mb-3">Thống kê theo ngày</h2>
            <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
              {data?.daily_breakdown.map((d) => (
                <div
                  key={d.date}
                  className="bg-slate-50 border border-slate-200 p-3 rounded-sm flex items-center justify-between text-sm"
                >
                  <div>
                    <div className="font-semibold text-slate-900 tabular-nums">{d.date}</div>
                    <div className="text-slate-500 mt-0.5 tabular-nums">{d.total} tin</div>
                  </div>
                  <div className="flex flex-wrap gap-2 text-sm">
                    <span className="text-slate-900 bg-white border border-slate-200 px-2.5 py-0.5 rounded-sm tabular-nums">
                      Thành công: {d.processed}
                    </span>
                    <span className="text-purple-700 bg-purple-50 border border-purple-200 px-2.5 py-0.5 rounded-sm tabular-nums">
                      Chờ duyệt: {d.needs_review}
                    </span>
                    <span className="text-slate-600 bg-white border border-slate-200 px-2.5 py-0.5 rounded-sm tabular-nums">
                      Xã giao: {d.ignored}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Hàng đợi xử lý */}
          <div className="bg-white border border-slate-200 p-4 rounded-sm">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h2 className="text-lg font-semibold text-slate-900">
                Hàng đợi xử lý
              </h2>
              <button
                onClick={handleDrainQueue}
                disabled={isDraining}
                className="text-sm bg-purple-700 hover:bg-purple-800 disabled:bg-purple-400 text-white px-3.5 py-1.5 rounded-sm font-medium transition"
              >
                {isDraining ? "Đang xử lý..." : "Xử lý ngay"}
              </button>
            </div>

            <div className="grid grid-cols-3 gap-3 mt-3 text-center">
              <div className="bg-slate-50 border border-slate-200 p-3 rounded-sm">
                <div className="text-sm text-slate-500">Đang chờ</div>
                <div className="text-xl font-bold text-purple-700 mt-1 tabular-nums">
                  {q?.queue_size || 0}
                </div>
              </div>
              <div className="bg-slate-50 border border-slate-200 p-3 rounded-sm">
                <div className="text-sm text-slate-500">Đã tiếp nhận</div>
                <div className="text-xl font-bold text-slate-900 mt-1 tabular-nums">
                  {q?.total_enqueued || 0}
                </div>
              </div>
              <div className="bg-slate-50 border border-slate-200 p-3 rounded-sm">
                <div className="text-sm text-slate-500">Đã xử lý</div>
                <div className="text-xl font-bold text-slate-900 mt-1 tabular-nums">
                  {q?.total_processed || 0}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Cột phải: Tin nhắn mới nhất */}
        <div className="bg-white border border-slate-200 p-4 rounded-sm">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-slate-900">Tin nhắn mới nhất</h2>
            <Link
              href="/messages"
              className="text-sm text-purple-700 hover:underline font-medium"
            >
              Xem tất cả
            </Link>
          </div>

          <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
            {data?.recent_messages.map((m) => {
              const statusMeta = getMessageStatusMeta(m.processing_status);
              const displayGroup =
                m.group_name ||
                (m.group_id?.startsWith("direct_") ? "Tin nhắn trực tiếp" : "Nhóm Zalo");

              return (
                <div
                  key={m.id}
                  className="bg-slate-50 border border-slate-200 p-3.5 rounded-sm text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <span className="font-semibold text-slate-900">{m.sender_name || "Người dùng Zalo"}</span>
                      <span className="text-slate-400">·</span>
                      <span className="text-slate-600">{displayGroup}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-slate-500 tabular-nums">
                        {m.sent_at?.slice(0, 16).replace("T", " ")}
                      </span>
                      <span className={`inline-flex items-center gap-1.5 font-medium ${statusMeta.textClass}`}>
                        <span className={`w-2 h-2 rounded-full ${statusMeta.dotClass}`} />
                        <span>{statusMeta.label}</span>
                      </span>
                    </div>
                  </div>

                  <div className="text-slate-900 text-base mt-2 whitespace-pre-line bg-white p-2.5 rounded-sm border border-slate-200 leading-relaxed">
                    {m.raw_text}
                  </div>

                  {(m.truck_plates.length > 0 || m.containers.length > 0) && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {m.truck_plates.map((p, i) => (
                        <span
                          key={i}
                          className="bg-white text-slate-900 px-2.5 py-0.5 rounded-sm text-sm border border-slate-200 font-medium tabular-nums"
                        >
                          {p}
                        </span>
                      ))}
                      {m.containers.map((c, i) => (
                        <span
                          key={i}
                          className="bg-purple-50 text-purple-700 px-2.5 py-0.5 rounded-sm text-sm border border-purple-200 font-medium tabular-nums"
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
