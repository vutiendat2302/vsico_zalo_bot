"use client";

import React from "react";
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";

interface StatusBadgeProps {
  active: boolean;
  activeLabel?: string;
  inactiveLabel?: string;
}

export function MasterStatusBadge({
  active,
  activeLabel = "Hoạt động",
  inactiveLabel = "Ngừng hoạt động",
}: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-medium ${
        active
          ? "bg-emerald-50 text-emerald-700 border border-emerald-200/70"
          : "bg-slate-100 text-slate-600 border border-slate-200"
      }`}
    >
      {active ? activeLabel : inactiveLabel}
    </span>
  );
}

interface SearchInputProps {
  value: string;
  onChange: (val: string) => void;
  placeholder: string;
}

export function MasterSearchInput({ value, onChange, placeholder }: SearchInputProps) {
  return (
    <div className="relative flex-1 min-w-[240px]">
      <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full pl-8 pr-3 py-1.5 text-xs bg-white border border-slate-200 rounded-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-purple-600"
      />
    </div>
  );
}

interface SelectFilterOption {
  value: string;
  label: string;
}

interface SelectFilterProps {
  value: string;
  onChange: (val: string) => void;
  options: SelectFilterOption[];
  className?: string;
}

export function MasterSelectFilter({
  value,
  onChange,
  options,
  className = "min-w-[160px]",
}: SelectFilterProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-sm text-slate-700 focus:outline-none focus:border-purple-600 ${className}`}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

interface PaginationProps {
  page: number;
  perPage: number;
  total: number;
  totalPages: number;
  onPageChange: (nextPage: number) => void;
}

export function MasterPagination({
  page,
  perPage,
  total,
  totalPages,
  onPageChange,
}: PaginationProps) {
  const start = total === 0 ? 0 : (page - 1) * perPage + 1;
  const end = Math.min(page * perPage, total);

  return (
    <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-t border-slate-200 bg-slate-50/50 text-xs text-slate-600">
      <div>
        Hiển thị <span className="font-medium text-slate-900">{start}</span> -{" "}
        <span className="font-medium text-slate-900">{end}</span> trên{" "}
        <span className="font-medium text-slate-900">{total}</span> bản ghi
      </div>
      <div className="flex items-center space-x-1.5">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="inline-flex items-center px-2 py-1 border border-slate-200 rounded-sm bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronLeft className="w-3.5 h-3.5 mr-0.5" />
          Trước
        </button>
        <span className="px-2 text-slate-700">
          Trang <span className="font-semibold text-slate-900">{page}</span> / {totalPages}
        </span>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className="inline-flex items-center px-2 py-1 border border-slate-200 rounded-sm bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Sau
          <ChevronRight className="w-3.5 h-3.5 ml-0.5" />
        </button>
      </div>
    </div>
  );
}

interface DetailModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  maxWidthClass?: string;
  children: React.ReactNode;
}

/**
 * Khung hộp thoại chi tiết dùng chung cho các màn hình danh mục và kế hoạch.
 */
export function MasterDetailModal({
  open,
  onClose,
  title,
  subtitle,
  maxWidthClass = "max-w-lg",
  children,
}: DetailModalProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
    >
      <div
        className={`w-full ${maxWidthClass} bg-white border border-slate-200 rounded-sm overflow-hidden`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Purple Header matching TMS modal design */}
        <div className="bg-purple-700 text-white px-6 py-4 flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold leading-snug">{title}</h3>
            {subtitle && (
              <p className="text-sm text-purple-100 mt-0.5">{subtitle}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-purple-100 hover:text-white p-1 rounded-sm"
            aria-label="Đóng"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 max-h-[78vh] overflow-y-auto bg-white">
          {children}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-slate-50 border-t border-slate-200 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-sm hover:bg-slate-100"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Nhóm thông tin theo từng chủ đề trong hộp thoại chi tiết.
 */
export function DetailSection({
  title,
  columns = 2,
  children,
}: {
  title: string;
  columns?: 2 | 3;
  children: React.ReactNode;
}) {
  const gridClass =
    columns === 3
      ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-5 gap-y-3 text-base"
      : "grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-3 text-base";

  return (
    <div className="border border-slate-200 rounded-sm p-4 bg-slate-50/50">
      <div className="text-sm font-semibold text-slate-700 mb-3 pb-1.5 border-b border-slate-200">
        {title}
      </div>
      <div className={gridClass}>
        {children}
      </div>
    </div>
  );
}

/**
 * Một cặp nhãn và giá trị trong hộp thoại chi tiết.
 */
export function DetailField({
  label,
  value,
  fullWidth = false,
}: {
  label: string;
  value: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <div className={fullWidth ? "sm:col-span-2 lg:col-span-3" : undefined}>
      <div className="text-sm text-slate-500">{label}</div>
      <div className="text-base font-medium text-slate-900 mt-0.5 break-words">
        {value ?? "—"}
      </div>
    </div>
  );
}
