"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

export type ToastType = "success" | "error" | "info";

export interface ToastItem {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType, duration?: number) => void;
  success: (message: string, duration?: number) => void;
  error: (message: string, duration?: number) => void;
  info: (message: string, duration?: number) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

// Global trigger cho phép gọi toast từ bất cứ đâu không cần hook
export const toast = {
  success: (message: string, duration?: number) => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("app:toast", {
          detail: { message, type: "success", duration },
        })
      );
    }
  },
  error: (message: string, duration?: number) => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("app:toast", {
          detail: { message, type: "error", duration },
        })
      );
    }
  },
  info: (message: string, duration?: number) => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("app:toast", {
          detail: { message, type: "info", duration },
        })
      );
    }
  },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: ToastType = "info", duration = 3500) => {
      const id = `${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
      setToasts((prev) => [...prev, { id, type, message, duration }]);

      if (duration > 0) {
        setTimeout(() => {
          removeToast(id);
        }, duration);
      }
    },
    [removeToast]
  );

  const success = useCallback(
    (message: string, duration?: number) => showToast(message, "success", duration),
    [showToast]
  );

  const error = useCallback(
    (message: string, duration?: number) => showToast(message, "error", duration),
    [showToast]
  );

  const info = useCallback(
    (message: string, duration?: number) => showToast(message, "info", duration),
    [showToast]
  );

  useEffect(() => {
    const handleCustomToast = (event: Event) => {
      const customEvent = event as CustomEvent<{
        message: string;
        type: ToastType;
        duration?: number;
      }>;
      if (customEvent.detail) {
        showToast(
          customEvent.detail.message,
          customEvent.detail.type || "info",
          customEvent.detail.duration || 3500
        );
      }
    };

    window.addEventListener("app:toast", handleCustomToast);
    return () => {
      window.removeEventListener("app:toast", handleCustomToast);
    };
  }, [showToast]);

  return (
    <ToastContext.Provider value={{ showToast, success, error, info }}>
      {children}
      {/* Toast viewport cố định góc dưới bên phải */}
      <div className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2 max-w-sm w-full pointer-events-none">
        {toasts.map((t) => {
          const borderClass =
            t.type === "success"
              ? "border-l-4 border-l-purple-700"
              : t.type === "error"
              ? "border-l-4 border-l-rose-600"
              : "border-l-4 border-l-slate-700";

          const badgeTitle =
            t.type === "success"
              ? "Thành công"
              : t.type === "error"
              ? "Lỗi thao tác"
              : "Thông báo";

          const badgeClass =
            t.type === "success"
              ? "text-purple-700"
              : t.type === "error"
              ? "text-rose-600"
              : "text-slate-700";

          return (
            <div
              key={t.id}
              className={`pointer-events-auto bg-white border border-slate-200 rounded-sm shadow-md p-3.5 flex items-start justify-between text-xs transition-all duration-200 ${borderClass}`}
            >
              <div className="flex-1 pr-2">
                <div className={`font-semibold ${badgeClass}`}>{badgeTitle}</div>
                <div className="text-slate-700 mt-1 whitespace-pre-line leading-relaxed">
                  {t.message}
                </div>
              </div>
              <button
                onClick={() => removeToast(t.id)}
                className="text-slate-400 hover:text-slate-700 text-sm font-bold px-1 transition"
                aria-label="Đóng"
              >
                &times;
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    // Fallback nếu gọi ngoài context
    return {
      showToast: (m: string, t?: ToastType, d?: number) => {
        if (t === "success") toast.success(m, d);
        else if (t === "error") toast.error(m, d);
        else toast.info(m, d);
      },
      success: toast.success,
      error: toast.error,
      info: toast.info,
    };
  }
  return context;
}
