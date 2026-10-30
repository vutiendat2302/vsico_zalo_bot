"use client";

/**
 * Trang Thống kê Phân loại Taxonomy Tin nhắn (Bảng 1 & Bảng 2).
 * 
 * Hiển thị toàn bộ dữ liệu phân loại nhận diện thực tế từ Backend API:
 * - Bảng 1: Các hạng mục dữ liệu nhận diện trong tin nhắn (1.1 -> 1.6).
 * - Bảng 2: 40 dạng tình huống tin nhắn thực tế (T01 -> T40).
 * 
 * Tuân thủ nghiêm ngặt quy tắc Zero Mock Data: Dữ liệu tải trực tiếp từ GET /api/messages/statistics.
 */

import React, { useEffect, useState } from "react";
import {
  BarChart3,
  Layers,
  FileSpreadsheet,
  RefreshCw,
  Search,
  Filter,
  Calendar,
  Users,
} from "lucide-react";
import { getTaxonomyStatistics } from "@/lib/api";

interface Bang1Item {
  code: string;
  hang_muc: string;
  so_tin_co: number;
  message_ids: number[];
  cac_kieu_viet: string;
  vi_du_thuc_te: string | null;
}

interface Bang2Item {
  ma: string;
  dang_tin: string;
  so_tin_primary: number;
  so_tin_co_dac_diem: number;
  primary_message_ids: number[];
  all_message_ids: number[];
  quy_tac_nhan_dien: string;
}

export default function StatisticsPage() {
  const [activeTab, setActiveTab] = useState<"bang1" | "bang2">("bang1");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dữ liệu API thực tế
  const [totalAnalyzed, setTotalAnalyzed] = useState<number>(0);
  const [bang1Data, setBang1Data] = useState<Record<string, Bang1Item[]>>({});
  const [bang2Data, setBang2Data] = useState<Bang2Item[]>([]);

  // Bộ lọc
  const [groupId, setGroupId] = useState("");
  const [fromTime, setFromTime] = useState("");
  const [toTime, setToTime] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  /**
   * Gọi API Backend để nạp số liệu thống kê taxonomy thời gian thực.
   */
  const loadStatistics = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await getTaxonomyStatistics({
        group_id: groupId || undefined,
        from_time: fromTime || undefined,
        to_time: toTime || undefined,
      });

      if (res.ok) {
        setTotalAnalyzed(res.total_messages_analyzed || 0);
        setBang1Data(res.bang_1_hang_muc_du_lieu || {});
        setBang2Data(res.bang_2_tinh_huong_thuc_te || []);
      } else {
        throw new Error(res.message || "Không thể tải dữ liệu thống kê");
      }
    } catch (err: any) {
      setError(err.message || "Lỗi kết nối máy chủ khi nạp thống kê.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatistics();
  }, []);

  // Tính tổng số hạng mục Bảng 1
  const totalBang1Items = Object.values(bang1Data).reduce(
    (acc, items) => acc + (items?.length || 0),
    0
  );

  // Danh mục tên thân thiện cho Bảng 1
  const sectionTitleMap: Record<string, string> = {
    "1.1_nhan_dien_lenh_va_cau_truc": "1.1. Nhận diện Lệnh & Cấu trúc Tin nhắn",
    "1.2_thong_tin_xe_va_tai_xe": "1.2. Nhận diện Thông tin Xe & Tài xế",
    "1.3_thong_tin_container_va_chi": "1.3. Nhận diện Container & Số Seal / Chì",
    "1.4_thong_tin_dia_diem_va_tuyen": "1.4. Nhận diện Địa điểm, Kho bãi & Tuyến đường",
    "1.5_thong_tin_thoi_gian": "1.5. Nhận diện Thời gian (Ngày kế hoạch, Giờ ETA)",
    "1.6_thong_tin_khac_va_bat_thuong": "1.6. Thông tin Bất thường, Phát sinh & Chi phí",
  };

  // Lọc Bảng 2 theo tìm kiếm
  const filteredBang2 = bang2Data.filter((item) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      item.ma.toLowerCase().includes(q) ||
      item.dang_tin.toLowerCase().includes(q) ||
      item.quy_tac_nhan_dien.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <BarChart3 className="w-7 h-7 text-indigo-400" />
            Thống kê Taxonomy Nhận diện Tin nhắn
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Bảng phân loại chuyên sâu theo quy chuẩn Hệ thống Đọc hiểu Zalo VSICO (Bảng 1 & Bảng 2).
          </p>
        </div>

        <button
          onClick={loadStatistics}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-sm transition"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Làm mới dữ liệu
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Tổng tin phân tích
            </span>
            <FileSpreadsheet className="w-5 h-5 text-indigo-400" />
          </div>
          <div className="text-3xl font-bold text-white mt-2">{totalAnalyzed}</div>
          <p className="text-xs text-slate-500 mt-1">
            Tổng tin nhắn Zalo có trong cơ sở dữ liệu hệ thống
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Hạng mục dữ liệu (Bảng 1)
            </span>
            <Layers className="w-5 h-5 text-emerald-400" />
          </div>
          <div className="text-3xl font-bold text-emerald-400 mt-2">{totalBang1Items}</div>
          <p className="text-xs text-slate-500 mt-1">
            6 nhóm trường dữ liệu (Lệnh, Xe, Cont, Kho, Giờ, Bất thường)
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Tình huống thực tế (Bảng 2)
            </span>
            <BarChart3 className="w-5 h-5 text-amber-400" />
          </div>
          <div className="text-3xl font-bold text-amber-400 mt-2">{bang2Data.length}</div>
          <p className="text-xs text-slate-500 mt-1">
            40 tình huống tin nhắn (T01 → T40) đã định nghĩa
          </p>
        </div>
      </div>

      {/* Bộ lọc API */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-slate-400 text-sm font-medium mr-2">
            <Filter className="w-4 h-4" />
            Bộ lọc API:
          </div>

          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Group ID Zalo..."
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-slate-400" />
            <input
              type="date"
              value={fromTime}
              onChange={(e) => setFromTime(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              title="Từ ngày"
            />
            <span className="text-slate-500 text-xs">đến</span>
            <input
              type="date"
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              title="Đến ngày"
            />
          </div>

          <button
            onClick={loadStatistics}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium transition"
          >
            Áp dụng
          </button>
        </div>
      </div>

      {/* Tab Switcher */}
      <div className="flex border-b border-slate-800 gap-4">
        <button
          onClick={() => setActiveTab("bang1")}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 transition border-b-2 ${
            activeTab === "bang1"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Layers className="w-4 h-4" />
          Bảng 1: Hạng mục Dữ liệu Nhận diện ({totalBang1Items})
        </button>

        <button
          onClick={() => setActiveTab("bang2")}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 transition border-b-2 ${
            activeTab === "bang2"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          Bảng 2: 40 Tình huống Tin nhắn Thực tế ({bang2Data.length})
        </button>
      </div>

      {/* Thông báo lỗi */}
      {error && (
        <div className="p-4 bg-rose-950/40 border border-rose-800 rounded-lg text-rose-300 text-sm">
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="p-12 text-center text-slate-400 flex flex-col items-center justify-center">
          <RefreshCw className="w-8 h-8 animate-spin text-indigo-500 mb-2" />
          Đang tính toán phân loại taxonomy từ cơ sở dữ liệu thực tế...
        </div>
      )}

      {/* Tab Content: Bảng 1 */}
      {!loading && activeTab === "bang1" && (
        <div className="space-y-6">
          {Object.entries(bang1Data).map(([sectionKey, items]) => {
            const sectionTitle = sectionTitleMap[sectionKey] || sectionKey;
            return (
              <div
                key={sectionKey}
                className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm"
              >
                <div className="px-5 py-3.5 bg-slate-800/80 border-b border-slate-700/60 flex items-center justify-between">
                  <h2 className="text-base font-semibold text-white flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-indigo-400"></span>
                    {sectionTitle}
                  </h2>
                  <span className="text-xs text-slate-400 font-mono">
                    {items.length} hạng mục
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-950/40 text-slate-400 uppercase tracking-wider text-[11px] border-b border-slate-800">
                      <tr>
                        <th className="py-2.5 px-4 w-20">Mã</th>
                        <th className="py-2.5 px-4 w-52">Hạng mục dữ liệu</th>
                        <th className="py-2.5 px-4 w-28 text-center">Số tin có</th>
                        <th className="py-2.5 px-4 w-28 text-center">Tỷ lệ</th>
                        <th className="py-2.5 px-4">Các kiểu viết phát hiện</th>
                        <th className="py-2.5 px-4">Ví dụ trích xuất thực tế</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 text-slate-300">
                      {items.map((item) => {
                        const pct =
                          totalAnalyzed > 0
                            ? ((item.so_tin_co / totalAnalyzed) * 100).toFixed(1)
                            : "0.0";
                        return (
                          <tr key={item.code} className="hover:bg-slate-800/40 transition">
                            <td className="py-3 px-4 font-mono font-semibold text-indigo-400">
                              {item.code}
                            </td>
                            <td className="py-3 px-4 font-medium text-white">
                              {item.hang_muc}
                            </td>
                            <td className="py-3 px-4 text-center">
                              <span
                                className={`px-2 py-0.5 rounded font-mono font-bold ${
                                  item.so_tin_co > 0
                                    ? "bg-indigo-950/80 text-indigo-300 border border-indigo-800"
                                    : "text-slate-500"
                                }`}
                              >
                                {item.so_tin_co}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-center text-slate-400 font-mono">
                              {pct}%
                            </td>
                            <td className="py-3 px-4 text-slate-400">
                              {item.cac_kieu_viet}
                            </td>
                            <td className="py-3 px-4 text-slate-400 font-mono text-[11px] max-w-xs truncate">
                              {item.vi_du_thuc_te ? (
                                <span
                                  className="text-amber-300 bg-amber-950/30 px-2 py-0.5 rounded border border-amber-900/40 block truncate"
                                  title={item.vi_du_thuc_te}
                                >
                                  {item.vi_du_thuc_te}
                                </span>
                              ) : (
                                <span className="text-slate-600">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Tab Content: Bảng 2 */}
      {!loading && activeTab === "bang2" && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
          {/* Thanh tìm kiếm tình huống */}
          <div className="p-4 bg-slate-950/30 border-b border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="relative w-full sm:w-80">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Tìm mã (T01...), tên tình huống, quy tắc..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div className="text-xs text-slate-400">
              Hiển thị <span className="text-white font-semibold">{filteredBang2.length}</span> /{" "}
              {bang2Data.length} tình huống
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/50 text-slate-400 uppercase tracking-wider text-[11px] border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4 w-20">Mã</th>
                  <th className="py-3 px-4 w-64">Dạng tình huống tin nhắn</th>
                  <th className="py-3 px-4 w-32 text-center">Phân loại chính</th>
                  <th className="py-3 px-4 w-32 text-center">Có đặc điểm</th>
                  <th className="py-3 px-4">Quy tắc nhận diện phân loại</th>
                  <th className="py-3 px-4 w-40 text-center">Mã tin nhắn khớp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {filteredBang2.map((item) => (
                  <tr key={item.ma} className="hover:bg-slate-800/40 transition">
                    <td className="py-3 px-4 font-mono font-bold text-amber-400">
                      {item.ma}
                    </td>
                    <td className="py-3 px-4 font-semibold text-white">
                      {item.dang_tin}
                    </td>
                    <td className="py-3 px-4 text-center">
                      <span
                        className={`px-2.5 py-0.5 rounded font-mono font-bold ${
                          item.so_tin_primary > 0
                            ? "bg-emerald-950/80 text-emerald-300 border border-emerald-800"
                            : "text-slate-500"
                        }`}
                      >
                        {item.so_tin_primary}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <span
                        className={`px-2.5 py-0.5 rounded font-mono font-medium ${
                          item.so_tin_co_dac_diem > 0
                            ? "bg-slate-800 text-slate-200 border border-slate-700"
                            : "text-slate-600"
                        }`}
                      >
                        {item.so_tin_co_dac_diem}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-300">
                      {item.quy_tac_nhan_dien}
                    </td>
                    <td className="py-3 px-4 text-center">
                      {item.all_message_ids.length > 0 ? (
                        <div
                          className="text-[11px] font-mono text-slate-400 max-w-[140px] truncate mx-auto bg-slate-950/40 px-2 py-0.5 rounded border border-slate-800"
                          title={`Message IDs: ${item.all_message_ids.join(", ")}`}
                        >
                          {item.all_message_ids.slice(0, 4).join(", ")}
                          {item.all_message_ids.length > 4 && "..."}
                        </div>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
