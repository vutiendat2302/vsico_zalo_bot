"use client";

import React, { useState } from "react";
import { Quote } from "lucide-react";
import type {
  SandboxSimulateResponse,
  SandboxTurnHistoryItem,
} from "../types";

interface SandboxOutputPanelProps {
  result: SandboxSimulateResponse | null;
  loading: boolean;
  error: string | null;
  history: SandboxTurnHistoryItem[];
  onUseBotReplyAsQuote: (replyText: string) => void;
  onUseMessageAsQuote: (msgText: string) => void;
}

type InspectorTab = "none" | "pii" | "ocr" | "history" | "json";

/**
 * Cột phải (OUTPUT): Hiển thị gọn Intent, Context Diff, Bản ghi chuẩn hóa và Tin mẫu.
 */
export function SandboxOutputPanel({
  result,
  loading,
  error,
  history,
  onUseBotReplyAsQuote,
  onUseMessageAsQuote,
}: SandboxOutputPanelProps) {
  const [activeTab, setActiveTab] = useState<InspectorTab>("none");

  const getStatusDotClass = (status: string): string => {
    switch (status) {
      case "PROCESSED":
        return "bg-emerald-600";
      case "NEEDS_REVIEW":
        return "bg-amber-600";
      case "IGNORED_CHAT":
      case "IGNORED_NON_TEXT":
        return "bg-slate-400";
      default:
        return "bg-purple-700";
    }
  };

  const toggleTab = (tab: Exclude<InspectorTab, "none">) => {
    setActiveTab((prev) => (prev === tab ? "none" : tab));
  };

  const hasInterestingPlanMatches = Boolean(
    result?.plan_matches.some((pm) => pm.plan_found || pm.carrier_mismatch)
  );

  return (
    <section className="flex flex-col bg-white border border-slate-200 rounded-sm overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-2">
        <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wide">
          OUTPUT
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono px-1.5 py-0.5 bg-emerald-50 border border-emerald-300 text-emerald-800 rounded-sm">
            persisted = false
          </span>
          {result && (
            <button
              type="button"
              onClick={() => onUseMessageAsQuote(result.effective_text)}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium bg-white border border-slate-300 text-slate-700 hover:border-purple-700 hover:text-purple-700 rounded-sm cursor-pointer"
            >
              <Quote className="w-3 h-3" />
              Quote tin này
            </button>
          )}
        </div>
      </div>

      <div className="p-3 space-y-3">
        {error && (
          <div className="p-2.5 border border-rose-300 bg-rose-50 text-rose-800 text-xs rounded-sm">
            {error}
          </div>
        )}

        {loading && (
          <div className="p-3 border border-purple-200 bg-purple-50 text-purple-900 text-xs font-medium rounded-sm">
            Đang xử lý...
          </div>
        )}

        {!result && !loading && (
          <div className="py-16 px-4 text-center border border-dashed border-slate-200 rounded-sm">
            <p className="text-xs text-slate-500">
              Chọn kịch bản hoặc nhập tin nhắn bên trái rồi nhấn Chạy kiểm thử.
            </p>
          </div>
        )}

        {result && (
          <>
            {/* 4 KPI cốt lõi */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div className="border border-slate-200 bg-slate-50 px-2.5 py-2 rounded-sm">
                <div className="text-[10px] font-semibold text-slate-500 uppercase">
                  Intent
                </div>
                <div className="mt-0.5 text-xs font-mono font-semibold text-slate-900 break-words">
                  {result.initial_intent === result.resolved_intent
                    ? result.resolved_intent
                    : `${result.initial_intent} -> ${result.resolved_intent}`}
                </div>
              </div>

              <div className="border border-slate-200 bg-slate-50 px-2.5 py-2 rounded-sm">
                <div className="text-[10px] font-semibold text-slate-500 uppercase">
                  Trạng thái
                </div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full shrink-0 ${getStatusDotClass(
                      result.processing_status
                    )}`}
                  />
                  <span className="text-xs font-mono font-semibold text-slate-900">
                    {result.processing_status}
                  </span>
                </div>
              </div>

              <div className="border border-slate-200 bg-slate-50 px-2.5 py-2 rounded-sm">
                <div className="text-[10px] font-semibold text-slate-500 uppercase">
                  AI / Token
                </div>
                <div className="mt-0.5 text-xs font-mono font-semibold text-slate-900">
                  {result.ai_executed
                    ? result.ai_service_status
                    : result.ai_would_trigger
                    ? "Cần AI (Đã chặn)"
                    : "0 token"}
                </div>
              </div>

              <div className="border border-slate-200 bg-slate-50 px-2.5 py-2 rounded-sm">
                <div className="text-[10px] font-semibold text-slate-500 uppercase">
                  Độ trễ / Format
                </div>
                <div className="mt-0.5 text-xs font-mono font-semibold text-purple-700 tabular-nums">
                  {result.latency_ms} ms{" "}
                  <span className="text-slate-500 font-normal">
                    ({result.source_format || "-"})
                  </span>
                </div>
              </div>
            </div>

            {/* Hiểu bối cảnh & Diff */}
            <div className="border border-slate-200 rounded-sm px-3 py-2 space-y-1.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] font-semibold text-slate-500 uppercase">
                  Bối cảnh:
                </span>
                <span className="text-xs font-mono px-1.5 py-0.5 bg-slate-100 border border-slate-300 text-slate-900 rounded-sm">
                  {result.context_resolution.resolution_type}
                </span>
                {result.context_resolution.target_container && (
                  <span className="text-xs font-mono px-1.5 py-0.5 bg-purple-50 border border-purple-300 text-purple-800 rounded-sm">
                    {result.context_resolution.target_container}
                  </span>
                )}
                {result.context_resolution.clarify_missing_container && (
                  <span className="text-[11px] font-medium px-1.5 py-0.5 bg-amber-50 border border-amber-300 text-amber-800 rounded-sm">
                    Thiếu Cont
                  </span>
                )}
                {result.context_resolution.is_duplicate_update && (
                  <span className="text-[11px] font-medium px-1.5 py-0.5 bg-slate-100 border border-slate-300 text-slate-700 rounded-sm">
                    Trùng lặp
                  </span>
                )}
              </div>
              {result.context_resolution.changes_list.length > 0 ? (
                <ul className="space-y-0.5">
                  {result.context_resolution.changes_list.map((ch, idx) => (
                    <li key={idx} className="text-xs font-mono text-slate-900">
                      - {ch}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-700">
                  {result.context_resolution.summary}
                </p>
              )}
            </div>

            {/* Bảng dữ liệu bóc tách chính */}
            {result.records.length > 0 && (
              <div className="border border-slate-200 rounded-sm overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-slate-600">
                      <th className="py-1.5 px-2 font-semibold">Cont</th>
                      <th className="py-1.5 px-2 font-semibold">Xe / Mooc</th>
                      <th className="py-1.5 px-2 font-semibold">Tài xế / SĐT</th>
                      <th className="py-1.5 px-2 font-semibold">Lệnh / Size / Chì</th>
                      <th className="py-1.5 px-2 font-semibold">KH / Kho / ETA</th>
                      <th className="py-1.5 px-2 font-semibold">Kiểm định</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {result.records.map((rec) => (
                      <tr key={rec.line_no} className="align-top">
                        <td className="py-1.5 px-2 font-mono">
                          <div className="font-semibold text-slate-900">
                            {rec.cont_no || "-"}
                          </div>
                          {rec.cont_no && (
                            <span
                              className={`inline-block mt-0.5 px-1 py-0.2 text-[10px] rounded-sm border ${
                                rec.check_digit_valid === true
                                  ? "bg-emerald-50 text-emerald-800 border-emerald-300"
                                  : rec.check_digit_valid === false
                                  ? "bg-rose-50 text-rose-800 border-rose-300"
                                  : "bg-slate-100 text-slate-700 border-slate-300"
                              }`}
                            >
                              {rec.check_digit_valid === true
                                ? "ISO OK"
                                : rec.check_digit_valid === false
                                ? "SAI ISO"
                                : "-"}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 px-2 font-mono text-slate-900">
                          <div>{rec.plate || rec.raw_plate || "-"}</div>
                          {rec.trailer_plate && (
                            <div className="text-[11px] text-slate-500">
                              {rec.trailer_plate}
                            </div>
                          )}
                        </td>
                        <td className="py-1.5 px-2">
                          <div className="text-slate-900">
                            {rec.driver_name || "-"}
                          </div>
                          <div className="font-mono text-slate-600">
                            {rec.driver_phone || "-"}
                          </div>
                        </td>
                        <td className="py-1.5 px-2 font-mono text-slate-900">
                          <div>
                            {rec.order_type || "-"} | {rec.cont_size || "-"}
                          </div>
                          <div className="text-slate-600">
                            {rec.seal_no || "-"}
                          </div>
                        </td>
                        <td className="py-1.5 px-2">
                          <div className="text-slate-900">
                            {rec.customer_raw || "-"}
                          </div>
                          <div className="text-slate-600">
                            {rec.location_raw || "-"}
                          </div>
                          <div className="font-mono text-[11px] text-slate-500">
                            {rec.eta || "-"}
                          </div>
                        </td>
                        <td className="py-1.5 px-2">
                          <div className="font-mono text-slate-900">
                            {rec.validation_status}
                          </div>
                          {rec.warnings.map((w, wi) => (
                            <div
                              key={wi}
                              className="mt-0.5 font-mono text-[10px] text-amber-800"
                            >
                              {w}
                            </div>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Đối chiếu TMS (chỉ hiện nếu khớp hoặc lệch nhà xe) */}
            {hasInterestingPlanMatches && (
              <div className="border border-slate-200 rounded-sm overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-slate-600">
                      <th className="py-1 px-2 font-semibold">Cont TMS</th>
                      <th className="py-1 px-2 font-semibold">Khách hàng</th>
                      <th className="py-1 px-2 font-semibold">Nhà xe KH</th>
                      <th className="py-1 px-2 font-semibold">Đối chiếu</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {result.plan_matches
                      .filter((pm) => pm.plan_found || pm.carrier_mismatch)
                      .map((pm, idx) => (
                        <tr key={idx}>
                          <td className="py-1 px-2 font-mono text-slate-900">
                            {pm.container_no || "-"}
                          </td>
                          <td className="py-1 px-2 text-slate-800">
                            {pm.plan_customer || "-"}
                          </td>
                          <td className="py-1 px-2 text-slate-800">
                            {pm.plan_carrier || "-"}
                          </td>
                          <td className="py-1 px-2 font-mono">
                            {pm.carrier_mismatch ? (
                              <span className="text-rose-700 font-semibold">
                                LỆCH NHÀ XE
                              </span>
                            ) : (
                              <span className="text-emerald-700">KHỚP TMS</span>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Tin nhắn đầu ra (chỉ hiện block có dữ liệu) */}
            {result.preview_outputs.bot_reply && (
              <div className="border border-amber-300 bg-amber-50 rounded-sm overflow-hidden">
                <div className="px-2.5 py-1.5 border-b border-amber-200 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-amber-900">
                    BotReply -&gt; Nhà xe
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      onUseBotReplyAsQuote(
                        result.preview_outputs.bot_reply || ""
                      )
                    }
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold bg-white border border-amber-400 text-amber-900 hover:bg-amber-100 rounded-sm cursor-pointer"
                  >
                    <Quote className="w-3 h-3" />
                    Dùng tin Bot làm Quote
                  </button>
                </div>
                <pre className="p-2.5 text-xs font-mono text-amber-950 whitespace-pre-wrap break-words">
                  {result.preview_outputs.bot_reply}
                </pre>
              </div>
            )}

            {result.preview_outputs.customer_notification && (
              <div className="border border-emerald-300 bg-emerald-50 rounded-sm overflow-hidden">
                <div className="px-2.5 py-1.5 border-b border-emerald-200 text-xs font-semibold text-emerald-900">
                  Thông báo -&gt; Khách hàng
                </div>
                <pre className="p-2.5 text-xs font-mono text-emerald-950 whitespace-pre-wrap break-words">
                  {result.preview_outputs.customer_notification}
                </pre>
              </div>
            )}

            {result.preview_outputs.dhvt_alert && (
              <div className="border border-rose-300 bg-rose-50 rounded-sm overflow-hidden">
                <div className="px-2.5 py-1.5 border-b border-rose-200 text-xs font-semibold text-rose-900">
                  Cảnh báo -&gt; ĐHVT
                </div>
                <pre className="p-2.5 text-xs font-mono text-rose-950 whitespace-pre-wrap break-words">
                  {result.preview_outputs.dhvt_alert}
                </pre>
              </div>
            )}

            {/* Thanh tab mở rộng chi tiết kỹ thuật khi cần */}
            <div className="border border-slate-200 rounded-sm overflow-hidden">
              <div className="flex flex-wrap bg-slate-50 border-b border-slate-200">
                {(
                  [
                    { id: "pii", label: "Che SĐT (PII)" },
                    { id: "ocr", label: "OCR" },
                    { id: "history", label: `Lượt (${history.length})` },
                    { id: "json", label: "JSON" },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => toggleTab(tab.id)}
                    className={`px-2.5 py-1.5 text-[11px] font-medium border-r border-slate-200 cursor-pointer ${
                      activeTab === tab.id
                        ? "bg-white text-purple-700 font-semibold"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {activeTab === "pii" && (
                <pre className="p-2.5 text-xs font-mono text-slate-800 whitespace-pre-wrap break-words bg-white">
                  {result.masked_text || "(Rỗng)"}
                </pre>
              )}

              {activeTab === "ocr" && (
                <div className="p-2.5 space-y-1.5 bg-white text-xs">
                  <div className="font-mono text-slate-600">
                    triggered={String(result.ocr.triggered)} | has_text=
                    {String(result.ocr.has_text)} | conf={result.ocr.confidence}
                  </div>
                  <pre className="p-2 bg-slate-50 border border-slate-200 rounded-sm font-mono text-slate-800 whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                    {result.ocr.extracted_text || "(Không có văn bản OCR)"}
                  </pre>
                </div>
              )}

              {activeTab === "history" && (
                <div className="p-2.5 space-y-1.5 max-h-56 overflow-y-auto bg-white">
                  {history.map((item) => (
                    <div
                      key={item.turn}
                      className="border border-slate-200 bg-slate-50 px-2 py-1.5 rounded-sm text-[11px] font-mono"
                    >
                      <span className="font-semibold text-purple-700">
                        #{item.turn} {item.resolved_intent} ({item.resolution_type})
                      </span>{" "}
                      - {item.processing_status} - {item.latency_ms}ms
                      <div className="text-slate-700 truncate">
                        {item.input_text}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === "json" && (
                <pre className="p-2.5 text-[11px] font-mono text-slate-800 whitespace-pre-wrap break-words max-h-72 overflow-y-auto bg-white">
                  {JSON.stringify(result, null, 2)}
                </pre>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
