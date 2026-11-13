"use client";

import React, { useEffect, useState } from "react";
import {
  fetchSandboxContextOptions,
  simulateSandboxPipeline,
} from "@/features/sandbox/api";
import { SandboxInputPanel } from "@/features/sandbox/components/SandboxInputPanel";
import { SandboxOutputPanel } from "@/features/sandbox/components/SandboxOutputPanel";
import type {
  SandboxContextOptions,
  SandboxPreset,
  SandboxSamplePlan,
  SandboxSimulateResponse,
  SandboxTurnHistoryItem,
  SandboxVirtualJob,
} from "@/features/sandbox/types";

/**
 * Trang Sandbox kiểm thử thuật toán & bối cảnh (Dry-Run 100%, không lưu CSDL).
 */
export default function SandboxPage() {
  const [text, setText] = useState<string>("");
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [imageName, setImageName] = useState<string | null>(null);
  const [quoteMessage, setQuoteMessage] = useState<string>("");
  const [contextMessages, setContextMessages] = useState<string[]>([]);
  const [virtualJobs, setVirtualJobs] = useState<SandboxVirtualJob[]>([]);
  const [carrierHint, setCarrierHint] = useState<string>("");
  const [timestamp, setTimestamp] = useState<string>("");
  const [allowAiFallback, setAllowAiFallback] = useState<boolean>(false);
  const [autoKeepContext, setAutoKeepContext] = useState<boolean>(true);

  const [contextOptions, setContextOptions] =
    useState<SandboxContextOptions | null>(null);
  const [contextOptionsLoading, setContextOptionsLoading] =
    useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SandboxSimulateResponse | null>(null);
  const [history, setHistory] = useState<SandboxTurnHistoryItem[]>([]);

  useEffect(() => {
    let active = true;
    setContextOptionsLoading(true);
    fetchSandboxContextOptions()
      .then((data) => {
        if (active) {
          setContextOptions(data);
        }
      })
      .catch(() => {
        // Không chặn giao diện nếu danh mục TMS phụ chưa tải được
      })
      .finally(() => {
        if (active) {
          setContextOptionsLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const handleRun = async () => {
    if (!text.trim() && !imageBase64) return;
    setLoading(true);
    setError(null);
    try {
      const response = await simulateSandboxPipeline({
        text,
        image_base64: imageBase64,
        quote_message: quoteMessage.trim() || null,
        context_messages: contextMessages,
        virtual_jobs: virtualJobs,
        carrier_hint: carrierHint.trim() || null,
        timestamp: timestamp.trim() || null,
        allow_ai_fallback: allowAiFallback,
      });
      setResult(response);
      setHistory((prev) => [
        {
          turn: prev.length + 1,
          input_text: response.effective_text || "(OCR)",
          quote_message: quoteMessage.trim() || null,
          resolved_intent: response.resolved_intent,
          processing_status: response.processing_status,
          resolution_type: response.context_resolution.resolution_type,
          summary: response.context_resolution.summary,
          ai_executed: response.ai_executed,
          latency_ms: response.latency_ms,
        },
        ...prev,
      ]);

      if (
        autoKeepContext &&
        response.processing_status !== "IGNORED_CHAT" &&
        response.processing_status !== "IGNORED_NON_TEXT"
      ) {
        if (response.effective_text.trim()) {
          setContextMessages((prev) =>
            [...prev, response.effective_text.trim()].slice(-10)
          );
        }
        setVirtualJobs(response.virtual_jobs_next);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Đã xảy ra lỗi khi chạy kiểm thử"
      );
    } finally {
      setLoading(false);
    }
  };

  const handleResetSession = () => {
    setQuoteMessage("");
    setContextMessages([]);
    setVirtualJobs([]);
    setResult(null);
    setHistory([]);
    setError(null);
  };

  const handleApplyPreset = (preset: SandboxPreset) => {
    setText(preset.text);
    setImageBase64(null);
    setImageName(null);
    if (preset.quote_message !== undefined) {
      setQuoteMessage(preset.quote_message);
    }
    if (preset.carrier_hint !== undefined) {
      setCarrierHint(preset.carrier_hint);
    }
    setError(null);
  };

  const handleApplySamplePlan = (plan: SandboxSamplePlan) => {
    const orderLabel =
      (plan.order_type || "").toLowerCase().includes("load") ||
      (plan.order_type || "").toLowerCase().includes("dong")
        ? "đóng hàng"
        : "trả hàng";
    const sampleLines = [
      `Khách hàng: ${plan.customer_name || "Khách hàng TMS"}`,
      `Lệnh: ${orderLabel}`,
      "Xe: 15H-012.34 - Tài xế: Nguyễn Văn Nam - 0912345678",
      `Cont: ${plan.container_no || "VSIU7399796"} - Size: 40HC - Số chì: SL889900`,
      plan.delivery_address ? `Kho: ${plan.delivery_address}` : "",
      "Dự kiến đến kho: 09:00",
    ]
      .filter(Boolean)
      .join("\n");
    setText(sampleLines);
    if (plan.fleet_partner) {
      setCarrierHint(plan.fleet_partner);
    }
    setError(null);
  };

  return (
    <div className="space-y-3">
      <div className="bg-white border border-slate-200 rounded-sm px-3 py-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h1 className="text-sm font-semibold text-slate-900">
            Thử nghiệm thuật toán &amp; bối cảnh
          </h1>
          <span className="text-[11px] font-mono px-1.5 py-0.5 bg-purple-50 text-purple-700 border border-purple-200 rounded-sm">
            Dry-run (Không lưu DB)
          </span>
        </div>

        <label className="inline-flex items-center gap-1.5 text-xs text-slate-700 cursor-pointer">
          <input
            type="checkbox"
            checked={autoKeepContext}
            onChange={(e) => setAutoKeepContext(e.target.checked)}
            className="w-3.5 h-3.5 accent-purple-700"
          />
          Giữ bối cảnh lượt sau
        </label>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
        <div className="lg:col-span-5">
          <SandboxInputPanel
            text={text}
            onTextChange={setText}
            imageBase64={imageBase64}
            imageName={imageName}
            onImageChange={(b64, name) => {
              setImageBase64(b64);
              setImageName(name);
            }}
            quoteMessage={quoteMessage}
            onQuoteMessageChange={setQuoteMessage}
            contextMessages={contextMessages}
            onAddContextMessage={(msg) =>
              setContextMessages((prev) => [...prev, msg])
            }
            onRemoveContextMessage={(idx) =>
              setContextMessages((prev) => prev.filter((_, i) => i !== idx))
            }
            virtualJobs={virtualJobs}
            onRemoveVirtualJob={(idx) =>
              setVirtualJobs((prev) => prev.filter((_, i) => i !== idx))
            }
            carrierHint={carrierHint}
            onCarrierHintChange={setCarrierHint}
            timestamp={timestamp}
            onTimestampChange={setTimestamp}
            allowAiFallback={allowAiFallback}
            onAllowAiFallbackChange={setAllowAiFallback}
            contextOptions={contextOptions}
            contextOptionsLoading={contextOptionsLoading}
            loading={loading}
            onRun={handleRun}
            onResetSession={handleResetSession}
            onApplyPreset={handleApplyPreset}
            onApplySamplePlan={handleApplySamplePlan}
          />
        </div>

        <div className="lg:col-span-7">
          <SandboxOutputPanel
            result={result}
            loading={loading}
            error={error}
            history={history}
            onUseBotReplyAsQuote={(replyText) => setQuoteMessage(replyText)}
            onUseMessageAsQuote={(msgText) => setQuoteMessage(msgText)}
          />
        </div>
      </div>
    </div>
  );
}
