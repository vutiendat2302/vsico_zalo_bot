"use client";

import React, { useRef, useState } from "react";
import { Play, Plus, RotateCcw, Trash2, Upload, X } from "lucide-react";
import { PRESETS } from "../presets";
import type {
  SandboxContextOptions,
  SandboxPreset,
  SandboxSamplePlan,
  SandboxVirtualJob,
} from "../types";

interface SandboxInputPanelProps {
  text: string;
  onTextChange: (val: string) => void;
  imageBase64: string | null;
  imageName: string | null;
  onImageChange: (base64: string | null, name: string | null) => void;
  quoteMessage: string;
  onQuoteMessageChange: (val: string) => void;
  contextMessages: string[];
  onAddContextMessage: (msg: string) => void;
  onRemoveContextMessage: (index: number) => void;
  virtualJobs: SandboxVirtualJob[];
  onRemoveVirtualJob: (index: number) => void;
  carrierHint: string;
  onCarrierHintChange: (val: string) => void;
  timestamp: string;
  onTimestampChange: (val: string) => void;
  allowAiFallback: boolean;
  onAllowAiFallbackChange: (val: boolean) => void;
  contextOptions: SandboxContextOptions | null;
  contextOptionsLoading: boolean;
  loading: boolean;
  onRun: () => void;
  onResetSession: () => void;
  onApplyPreset: (preset: SandboxPreset) => void;
  onApplySamplePlan: (plan: SandboxSamplePlan) => void;
}

/**
 * Cột trái (INPUT): Nhập tin nhắn, ảnh OCR, Quote, bối cảnh phiên và tùy chọn AI Fallback.
 */
export function SandboxInputPanel({
  text,
  onTextChange,
  imageBase64,
  imageName,
  onImageChange,
  quoteMessage,
  onQuoteMessageChange,
  contextMessages,
  onAddContextMessage,
  onRemoveContextMessage,
  virtualJobs,
  onRemoveVirtualJob,
  carrierHint,
  onCarrierHintChange,
  timestamp,
  onTimestampChange,
  allowAiFallback,
  onAllowAiFallbackChange,
  contextOptions,
  contextOptionsLoading,
  loading,
  onRun,
  onResetSession,
  onApplyPreset,
  onApplySamplePlan,
}: SandboxInputPanelProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [newContextDraft, setNewContextDraft] = useState<string>("");
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);

  const selectedPreset = PRESETS.find((p) => p.id === selectedPresetId) || null;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        onImageChange(reader.result, file.name);
      }
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!loading) {
        onRun();
      }
    }
  };

  const handleAddContextClick = () => {
    const trimmed = newContextDraft.trim();
    if (!trimmed) return;
    onAddContextMessage(trimmed);
    setNewContextDraft("");
  };

  const canRun = !loading && (text.trim().length > 0 || Boolean(imageBase64));

  return (
    <section className="flex flex-col bg-white border border-slate-200 rounded-sm overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wide">
          INPUT
        </h2>
        <span className="text-[11px] font-mono text-slate-500">
          Ctrl + Enter
        </span>
      </div>

      <div className="p-3 space-y-3">
        {/* Kịch bản nhanh */}
        <div className="space-y-1.5">
          <div className="flex flex-wrap gap-1">
            {PRESETS.map((preset) => {
              const isSelected = selectedPresetId === preset.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => {
                    setSelectedPresetId(preset.id);
                    onApplyPreset(preset);
                  }}
                  title={preset.description}
                  className={`px-2 py-1 text-xs border rounded-sm transition-colors cursor-pointer ${
                    isSelected
                      ? "bg-purple-700 text-white border-purple-700 font-medium"
                      : "bg-white text-slate-700 border-slate-300 hover:border-purple-700 hover:text-purple-700"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>
          {selectedPreset?.suggested_follow_up && (
            <div className="flex items-center justify-between gap-2 bg-purple-50 border border-purple-200 px-2 py-1 rounded-sm">
              <span className="text-xs font-mono text-purple-900 truncate">
                {selectedPreset.suggested_follow_up}
              </span>
              <button
                type="button"
                onClick={() =>
                  onTextChange(selectedPreset.suggested_follow_up || "")
                }
                className="shrink-0 px-2 py-0.5 text-[11px] font-medium bg-white border border-purple-300 text-purple-700 hover:bg-purple-100 rounded-sm cursor-pointer"
              >
                Điền tin tiếp theo
              </button>
            </div>
          )}
        </div>

        {/* Mẫu TMS thật (chỉ hiển thị các kế hoạch đã có số container) */}
        {(() => {
          const validSamplePlans = (contextOptions?.sample_plans || []).filter(
            (p) => Boolean(p.container_no && p.container_no.trim())
          );
          if (validSamplePlans.length === 0) return null;
          return (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-mono text-[11px] text-slate-500">
                TMS ({contextOptionsLoading ? "..." : (contextOptions?.total_plans_in_db ?? 0)}):
              </span>
              {validSamplePlans.map((plan, idx) => (
                <button
                  key={`${plan.container_no}-${idx}`}
                  type="button"
                  onClick={() => onApplySamplePlan(plan)}
                  title={`${plan.customer_name || ""} | ${plan.fleet_partner || ""}`}
                  className="px-1.5 py-0.5 text-[11px] font-mono bg-slate-50 border border-slate-300 text-slate-800 hover:border-purple-700 hover:text-purple-700 rounded-sm cursor-pointer"
                >
                  {plan.container_no}
                </button>
              ))}
            </div>
          );
        })()}

        {/* Tin nhắn + Ảnh OCR */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <label
              htmlFor="sandbox-message-text"
              className="text-xs font-semibold text-slate-700"
            >
              Tin nhắn
            </label>
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleFileChange}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium text-slate-700 bg-white border border-slate-300 hover:border-purple-700 hover:text-purple-700 rounded-sm cursor-pointer"
              >
                <Upload className="w-3 h-3" />
                Ảnh OCR
              </button>
              {text.length > 0 && (
                <button
                  type="button"
                  onClick={() => onTextChange("")}
                  className="text-[11px] text-slate-500 hover:text-slate-900 cursor-pointer"
                >
                  Xóa
                </button>
              )}
            </div>
          </div>
          <textarea
            id="sandbox-message-text"
            rows={10}
            value={text}
            onChange={(e) => onTextChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Nhập nội dung tin nhắn..."
            className="w-full min-h-[220px] resize-y px-2.5 py-2 text-xs font-mono text-slate-900 bg-white border border-slate-300 rounded-sm focus:outline-none focus:border-purple-700"
          />
          {imageBase64 && (
            <div className="flex items-center justify-between gap-2 bg-slate-50 border border-slate-200 px-2 py-1.5 rounded-sm">
              <div className="flex items-center gap-2 min-w-0">
                <img
                  src={imageBase64}
                  alt={imageName || "OCR"}
                  className="w-10 h-10 object-cover border border-slate-300 rounded-sm shrink-0 bg-white"
                />
                <span className="text-xs font-mono text-slate-700 truncate">
                  {imageName || "anh.png"} ({(imageBase64.length / 1024).toFixed(0)} KB)
                </span>
              </div>
              <button
                type="button"
                onClick={() => onImageChange(null, null)}
                className="p-1 text-slate-500 hover:text-rose-700 cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* Quote & Bối cảnh */}
        <div className="space-y-2 border border-slate-200 p-2.5 rounded-sm bg-slate-50">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700">
              Bối cảnh ({contextMessages.length} tin | {virtualJobs.length} ca)
            </span>
            {quoteMessage.length > 0 && (
              <button
                type="button"
                onClick={() => onQuoteMessageChange("")}
                className="text-[11px] text-slate-500 hover:text-slate-900 cursor-pointer"
              >
                Xóa Quote
              </button>
            )}
          </div>

          <textarea
            id="sandbox-quote-message"
            rows={2}
            value={quoteMessage}
            onChange={(e) => onQuoteMessageChange(e.target.value)}
            placeholder="Quote (tùy chọn)..."
            className="w-full px-2 py-1 text-xs font-mono text-slate-900 bg-white border border-slate-300 rounded-sm focus:outline-none focus:border-purple-700"
          />

          {contextMessages.length > 0 && (
            <ul className="space-y-1 max-h-28 overflow-y-auto">
              {contextMessages.map((msg, idx) => (
                <li
                  key={`${idx}-${msg.slice(0, 12)}`}
                  className="flex items-center justify-between gap-2 bg-white border border-slate-200 px-2 py-1 rounded-sm"
                >
                  <span className="text-[11px] font-mono text-slate-800 truncate flex-1">
                    #{idx + 1}: {msg}
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemoveContextMessage(idx)}
                    className="text-slate-400 hover:text-rose-700 shrink-0 cursor-pointer"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex gap-1.5">
            <input
              type="text"
              value={newContextDraft}
              onChange={(e) => setNewContextDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAddContextClick();
                }
              }}
              placeholder="Thêm tin trước đó..."
              className="flex-1 px-2 py-1 text-xs text-slate-900 bg-white border border-slate-300 rounded-sm focus:outline-none focus:border-purple-700"
            />
            <button
              type="button"
              onClick={handleAddContextClick}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-white border border-slate-300 text-slate-700 hover:border-purple-700 hover:text-purple-700 rounded-sm cursor-pointer"
            >
              <Plus className="w-3 h-3" />
              Thêm
            </button>
          </div>

          {virtualJobs.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {virtualJobs.map((job, idx) => (
                <div
                  key={`${job.container_no || "job"}-${idx}`}
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] font-mono bg-white border border-slate-300 rounded-sm"
                >
                  <span className="font-semibold text-slate-900">
                    {job.container_no || "NO_CONT"}
                  </span>
                  <span className="text-slate-500">
                    {job.truck_plate || "-"} | {job.seal_no || "-"}
                  </span>
                  <span
                    className={
                      job.status === "PROCESSED"
                        ? "text-emerald-700"
                        : job.status === "CANCELLED"
                        ? "text-rose-700"
                        : "text-amber-700"
                    }
                  >
                    [{job.status}]
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemoveVirtualJob(idx)}
                    className="text-slate-400 hover:text-rose-700 cursor-pointer"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tham số phụ & AI */}
        <div className="grid grid-cols-2 gap-2">
          <input
            id="sandbox-carrier-hint"
            list="sandbox-carrier-list"
            type="text"
            value={carrierHint}
            onChange={(e) => onCarrierHintChange(e.target.value)}
            placeholder="Nhà xe giả lập (tùy chọn)"
            className="w-full px-2 py-1 text-xs text-slate-900 bg-white border border-slate-300 rounded-sm focus:outline-none focus:border-purple-700"
          />
          <datalist id="sandbox-carrier-list">
            {(contextOptions?.carriers || []).map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>

          <input
            id="sandbox-timestamp"
            type="text"
            value={timestamp}
            onChange={(e) => onTimestampChange(e.target.value)}
            placeholder="Giờ gửi ISO (tùy chọn)"
            className="w-full px-2 py-1 text-xs font-mono text-slate-900 bg-white border border-slate-300 rounded-sm focus:outline-none focus:border-purple-700"
          />
        </div>

        <label className="flex items-center justify-between gap-2 px-2.5 py-1.5 border border-slate-200 bg-white rounded-sm cursor-pointer">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={allowAiFallback}
              onChange={(e) => onAllowAiFallbackChange(e.target.checked)}
              className="w-3.5 h-3.5 accent-purple-700"
            />
            <span className="text-xs font-medium text-slate-800">
              Gọi AI Fallback
            </span>
          </div>
          <span
            className={`text-[11px] font-mono px-1.5 py-0.5 rounded-sm border ${
              allowAiFallback
                ? "bg-amber-50 text-amber-800 border-amber-300"
                : "bg-emerald-50 text-emerald-800 border-emerald-300"
            }`}
          >
            {allowAiFallback ? "ON" : "OFF (0 token)"}
          </span>
        </label>
      </div>

      {/* Action Footer */}
      <div className="px-3 py-2.5 border-t border-slate-200 bg-slate-50 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onResetSession}
          disabled={loading}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-100 rounded-sm disabled:opacity-50 cursor-pointer"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Xóa phiên
        </button>

        <button
          type="button"
          onClick={onRun}
          disabled={!canRun}
          className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-purple-700 hover:bg-purple-800 rounded-sm disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          <Play className="w-3.5 h-3.5" />
          {loading ? "Đang chạy..." : "Chạy kiểm thử"}
        </button>
      </div>
    </section>
  );
}
