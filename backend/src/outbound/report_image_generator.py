"""Bộ sinh ảnh báo cáo thống kê và bảng chuyến vận tải từ HTML sang PNG qua Headless Chrome.

Cơ chế hoạt động:
1. Dựng tài liệu HTML5 + CSS nội tuyến sắc nét (bảng thống kê theo vùng/miền/tỉnh thành,
   bảng danh sách chuyến trong ngày hoặc danh sách lệnh thiếu thông tin).
2. Gọi `/usr/bin/google-chrome --headless=new --screenshot` để kết xuất sang ảnh PNG.
3. Lưu ảnh vào thư mục tạm có chữ ký HMAC (và đồng bộ MinIO nếu sẵn sàng) để phục vụ qua
   endpoint công khai `GET /api/public/reports/{token}.png` cho máy chủ Zalo OA tải và hiển thị.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import html
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Optional
from zoneinfo import ZoneInfo

from src.config.settings import settings
from src.infrastructure.minio_client import minio_storage
from src.observability.logging import get_logger

logger = get_logger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
REPORT_CACHE_DIR = Path(tempfile.gettempdir()) / "vsico_report_images"
REPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _find_chrome_binary() -> Optional[str]:
    """Tìm tệp thực thi trình duyệt Chromium/Chrome trên máy chủ Linux."""
    for candidate in (
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _sign_report_token(raw_key: str) -> str:
    """Tạo token ngắn gọn có chữ ký HMAC để chống đoán đường dẫn ảnh báo cáo."""
    secret = settings.short_link_secret.encode("utf-8")
    sig = hmac.new(secret, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"{raw_key}_{sig}"


def resolve_report_image_path(token: str) -> Optional[Path]:
    """Xác thực chữ ký token và trả về đường dẫn file PNG hợp lệ trên đĩa (chống path traversal)."""
    clean_tok = (token or "").strip()
    if clean_tok.endswith(".png"):
        clean_tok = clean_tok[:-4]
    if "_" not in clean_tok:
        return None
    raw_key, sig = clean_tok.rsplit("_", 1)
    if not raw_key or not raw_key.isalnum():
        return None
    expected = _sign_report_token(raw_key).rsplit("_", 1)[1]
    if not hmac.compare_digest(sig, expected):
        return None
    target = (REPORT_CACHE_DIR / f"{clean_tok}.png").resolve()
    if target.parent != REPORT_CACHE_DIR.resolve() or not target.exists():
        return None
    return target


class HtmlReportImageGenerator:
    """Bộ kết xuất bảng thống kê và chi tiết chuyến vận tải thành ảnh PNG gửi qua Zalo."""

    _BASE_CSS = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
        font-family: "Noto Sans", "Roboto", "DejaVu Sans", Arial, sans-serif;
        background: #ffffff;
        color: #0f172a;
        width: 100%;
        min-height: 100%;
        margin: 0;
    }
    body {
        padding: 12px 14px;
    }
    .header {
        background: #0f172a;
        color: #f8fafc;
        padding: 14px 18px;
        border-radius: 4px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 14px;
        width: 100%;
    }
    .header-title { font-size: 20px; font-weight: 700; letter-spacing: 0.3px; }
    .header-sub { font-size: 13px; color: #cbd5e1; margin-top: 4px; }
    .page-pill {
        background: #1e293b;
        border: 1px solid #475569;
        color: #f8fafc;
        font-size: 13px;
        font-weight: 700;
        padding: 6px 12px;
        border-radius: 4px;
        white-space: nowrap;
    }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin-bottom: 14px;
        width: 100%;
    }
    .kpi-grid-5 {
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 10px;
        margin-bottom: 14px;
        width: 100%;
    }
    .kpi-card {
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        padding: 11px 14px;
        background: #f8fafc;
    }
    .kpi-label { font-size: 12px; color: #475569; text-transform: uppercase; font-weight: 600; }
    .kpi-val { font-size: 24px; font-weight: 700; color: #0f172a; margin-top: 4px; }
    .kpi-sub { font-size: 12px; color: #64748b; margin-top: 2px; font-weight: 600; }
    .section-title {
        font-size: 15px;
        font-weight: 700;
        color: #1e293b;
        margin: 12px 0 8px 0;
        border-left: 4px solid #0284c7;
        padding-left: 10px;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        margin-bottom: 12px;
        table-layout: auto;
    }
    th {
        background: #e2e8f0;
        color: #0f172a;
        font-weight: 700;
        text-align: left;
        padding: 8px 9px;
        border: 1px solid #cbd5e1;
        white-space: nowrap;
    }
    td {
        padding: 7px 9px;
        border: 1px solid #cbd5e1;
        vertical-align: top;
        word-break: break-word;
    }
    tr:nth-child(even) td { background: #f8fafc; }
    .num { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
    .nowrap { white-space: nowrap; }
    .badge-ok { color: #15803d; font-weight: 700; white-space: nowrap; }
    .badge-warn { color: #b45309; font-weight: 700; white-space: nowrap; }
    .badge-err { color: #b91c1c; font-weight: 700; white-space: nowrap; }
    .footer {
        font-size: 12px;
        color: #64748b;
        margin-top: 8px;
        text-align: right;
    }
    """

    _REPORT_WIDTH = 1280
    _PROVINCE_FIRST_PAGE_ROWS = 25
    _PROVINCE_NEXT_PAGE_ROWS = 30
    _DAILY_TRIPS_INLINE_MAX = 15
    _DAILY_TRIPS_PER_PAGE = 30

    @classmethod
    def render_html_to_png(
        cls,
        html_content: str,
        *,
        width: int = 1120,
        height: int = 860,
        prefix: str = "report",
    ) -> dict[str, Any]:
        """Chuyển nội dung HTML thành ảnh PNG bằng Headless Chrome, lưu đĩa + MinIO và trả về URL công khai."""
        chrome_bin = _find_chrome_binary()
        if not chrome_bin:
            return {"ok": False, "error": "Không tìm thấy Google Chrome/Chromium trên máy chủ."}

        ts_key = f"{prefix}{datetime.now(VN_TZ).strftime('%Y%m%d%H%M%S%f')[:18]}"
        raw_key = "".join(ch for ch in ts_key if ch.isalnum())
        token = _sign_report_token(raw_key)
        png_path = REPORT_CACHE_DIR / f"{token}.png"
        html_path = REPORT_CACHE_DIR / f"{token}.html"

        try:
            html_path.write_text(html_content, encoding="utf-8")
            cmd = [
                chrome_bin,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                f"--window-size={width},{max(420, min(height, 4000))}",
                f"--screenshot={png_path}",
                f"file://{html_path}",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode != 0 or not png_path.exists():
                return {
                    "ok": False,
                    "error": f"Headless Chrome thất bại (code={proc.returncode}): {(proc.stderr or '')[:200]}",
                }
            png_bytes = png_path.read_bytes()
            minio_key: Optional[str] = None
            try:
                uploaded = minio_storage.upload_bytes(
                    object_key=f"reports/{token}.png",
                    data=png_bytes,
                    content_type="image/png",
                    bucket_name=settings.MINIO_BUCKET_NAME or "vsico-zalo-files",
                )
                minio_key = uploaded.object_key
            except Exception:
                pass

            public_base = (settings.PUBLIC_API_BASE_URL or f"http://localhost:{settings.PORT}").rstrip("/")
            return {
                "ok": True,
                "token": token,
                "png_path": str(png_path),
                "size_bytes": len(png_bytes),
                "minio_key": minio_key,
                "public_url": f"{public_base}/api/public/reports/{token}.png",
            }
        except Exception as exc:
            logger.warning("Lỗi render HTML sang PNG: %s", exc)
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                if html_path.exists():
                    html_path.unlink()
            except OSError:
                pass

    @staticmethod
    def _pct_str(part: int, total: int) -> str:
        """Tính tỷ lệ phần trăm dạng chuỗi tiếng Việt (ví dụ 33,1%)."""
        if not total or total <= 0:
            return "0,0%"
        return f"{(part / total) * 100:.1f}%".replace(".", ",")

    @staticmethod
    def _status_badge_class(status_text: str) -> str:
        """Chọn lớp màu CSS phù hợp cho cột trạng thái bố trí xe."""
        low = (status_text or "").strip().lower()
        if "đã bố trí" in low or "đã đóng" in low or "hoàn tất" in low:
            return "badge-ok"
        if "lỗi" in low or "hủy" in low:
            return "badge-err"
        return "badge-warn"

    @staticmethod
    def _estimate_trip_rows_height(rows: list[dict[str, str]], col_wrap_chars: dict[str, int]) -> int:
        """Ước lượng chiều cao bảng theo số dòng wrap thực tế để ảnh PNG không bị cắt đáy."""
        if not rows:
            return 42
        total_h = 0
        for row in rows:
            max_lines = 1
            for col_key, chars_per_line in col_wrap_chars.items():
                val_len = len(str(row.get(col_key) or ""))
                if val_len > chars_per_line:
                    est_lines = (val_len + chars_per_line - 1) // chars_per_line
                    if est_lines > max_lines:
                        max_lines = est_lines
            total_h += 18 + max_lines * 19
        return total_h

    @staticmethod
    def _slice_pages(items: list[dict[str, str]], first_page_size: int, next_page_size: int) -> list[tuple[int, list[dict[str, str]]]]:
        """Chia danh sách lệnh thành các trang nối tiếp kèm chỉ số bắt đầu (1-based)."""
        if not items:
            return [(1, [])]
        chunks: list[tuple[int, list[dict[str, str]]]] = []
        first_chunk = items[:first_page_size]
        chunks.append((1, first_chunk))
        offset = first_page_size
        while offset < len(items):
            chunks.append((offset + 1, items[offset : offset + next_page_size]))
            offset += next_page_size
        return chunks

    @classmethod
    def render_daily_stats_report(
        cls,
        *,
        report_date: str,
        total_plans: int,
        load_count: int,
        return_count: int,
        missing_vehicle_count: int,
        region_rows: list[tuple[str, int, int, int]],
        province_rows: list[tuple[str, int, int, int]],
        incomplete_carriers: list[tuple[str, int, int]] | None = None,
        assigned_count: int | None = None,
        closed_count: int | None = None,
        open_count: int | None = None,
        trips: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Sinh bộ ảnh PNG full chiều rộng báo cáo tổng quan ngày và phân trang đầy đủ toàn bộ danh sách lệnh."""
        del closed_count, open_count  # Giữ tham số tương thích ngược, không hiển thị KPI trùng lặp
        now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
        assigned = assigned_count if assigned_count is not None else max(0, total_plans - missing_vehicle_count)
        unassigned = max(0, total_plans - assigned)

        load_pct = cls._pct_str(load_count, total_plans)
        return_pct = cls._pct_str(return_count, total_plans)
        assigned_pct = cls._pct_str(assigned, total_plans)
        unassigned_pct = cls._pct_str(unassigned, total_plans)

        reg_html = "".join(
            f"<tr><td>{html.escape(r)}</td>"
            f"<td class='num'>{t}</td>"
            f"<td class='num'>{lo} ({cls._pct_str(lo, t)})</td>"
            f"<td class='num'>{ro} ({cls._pct_str(ro, t)})</td></tr>"
            for r, t, lo, ro in region_rows
        ) or "<tr><td colspan='4'>Chưa có dữ liệu vùng miền</td></tr>"

        prov_html = "".join(
            f"<tr><td>{html.escape(p)}</td>"
            f"<td class='num'>{t}</td>"
            f"<td class='num'>{lo} ({cls._pct_str(lo, t)})</td>"
            f"<td class='num'>{ro} ({cls._pct_str(ro, t)})</td></tr>"
            for p, t, lo, ro in province_rows
        ) or "<tr><td colspan='4'>Chưa có dữ liệu tỉnh/thành</td></tr>"

        carrier_section = ""
        carrier_h = 0
        if incomplete_carriers:
            c_rows = "".join(
                f"<tr><td>{html.escape(c)}</td><td class='num'>{tot}</td><td class='num badge-warn'>{miss} ({cls._pct_str(miss, tot)})</td></tr>"
                for c, tot, miss in incomplete_carriers
            )
            carrier_section = (
                "<div class='section-title'>Nhà xe chưa báo đủ thông tin xe / container</div>"
                "<table><thead><tr><th>Nhà xe</th><th class='num'>Tổng lệnh</th><th class='num'>Chưa đủ thông tin</th></tr></thead>"
                f"<tbody>{c_rows}</tbody></table>"
            )
            carrier_h = 74 + len(incomplete_carriers) * 35

        all_trips = list(trips or [])
        base_summary_h = 330 + max(1, len(region_rows)) * 35 + max(1, len(province_rows)) * 35 + carrier_h
        trip_col_wraps = {"customer": 24, "carrier_name": 18, "vehicle": 22, "province": 14}

        inline_trips = False
        trip_pages: list[tuple[int, list[dict[str, str]]]] = []
        if all_trips:
            inline_est_h = base_summary_h + 75 + cls._estimate_trip_rows_height(all_trips, trip_col_wraps)
            if len(all_trips) <= cls._DAILY_TRIPS_INLINE_MAX and inline_est_h <= 1850:
                inline_trips = True
            else:
                trip_pages = cls._slice_pages(all_trips, cls._DAILY_TRIPS_PER_PAGE, cls._DAILY_TRIPS_PER_PAGE)

        total_pages = 1 + len(trip_pages)

        def _render_daily_trip_table(start_idx: int, batch: list[dict[str, str]], section_label: str) -> str:
            t_rows_html = "".join(
                "<tr>"
                f"<td class='num'>{start_idx + offset}</td>"
                f"<td class='nowrap'><b>{html.escape(t.get('order_code') or '-')}</b></td>"
                f"<td class='nowrap'>{html.escape(t.get('order_type') or '-')}</td>"
                f"<td>{html.escape(t.get('province') or '-')}</td>"
                f"<td class='nowrap'>{html.escape(t.get('container_no') or 'Chưa có')}</td>"
                f"<td>{html.escape(t.get('customer') or '-')}</td>"
                f"<td>{html.escape(t.get('carrier_name') or '-')}</td>"
                f"<td>{html.escape(t.get('vehicle') or 'Chưa bố trí')}</td>"
                f"<td class='{cls._status_badge_class(t.get('status') or '')}'>{html.escape(t.get('status') or '-')}</td>"
                "</tr>"
                for offset, t in enumerate(batch)
            )
            return (
                f"<div class='section-title'>{html.escape(section_label)}</div>"
                "<table><thead><tr>"
                "<th class='num'>#</th><th>Mã lệnh</th><th>Loại</th><th>Tỉnh/TP</th>"
                "<th>Số Cont</th><th>Khách hàng</th><th>Nhà xe</th><th>Xe / Tài xế</th><th>Trạng thái</th>"
                f"</tr></thead><tbody>{t_rows_html}</tbody></table>"
            )

        inline_trips_section = ""
        page1_extra_h = 0
        if inline_trips:
            inline_trips_section = _render_daily_trip_table(
                1, all_trips, f"Bảng chi tiết các lệnh trong ngày ({len(all_trips)} lệnh)"
            )
            page1_extra_h = 75 + cls._estimate_trip_rows_height(all_trips, trip_col_wraps)

        page1_pill = f'<div class="page-pill">Trang 1 / {total_pages}</div>' if total_pages > 1 else ""
        page1_footer = (
            f"Trang 1/{total_pages} · Tổng hợp kế hoạch ({len(all_trips)} lệnh) | Hệ thống VSICO Zalo Bot"
            if total_pages > 1
            else "Hệ thống VSICO Zalo Bot & TMS Integration"
        )

        doc1 = f"""<!doctype html>
<html lang="vi">
<head><meta charset="utf-8"><style>{cls._BASE_CSS}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-title">VSICO - BÁO CÁO ĐIỀU HÀNH VẬN TẢI CONTAINER</div>
      <div class="header-sub">Kế hoạch ngày: {html.escape(report_date)} | Thời điểm trích xuất: {now_str}</div>
    </div>
    {page1_pill}
  </div>
  <div class="kpi-grid-5">
    <div class="kpi-card"><div class="kpi-label">Tổng số lệnh</div><div class="kpi-val">{total_plans}</div><div class="kpi-sub">100%</div></div>
    <div class="kpi-card"><div class="kpi-label">Đã bố trí xe</div><div class="kpi-val" style="color:#15803d">{assigned}</div><div class="kpi-sub">{assigned_pct}</div></div>
    <div class="kpi-card"><div class="kpi-label">Chưa có xe</div><div class="kpi-val" style="color:#b45309">{unassigned}</div><div class="kpi-sub">{unassigned_pct}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đóng (LO)</div><div class="kpi-val" style="color:#0369a1">{load_count}</div><div class="kpi-sub">{load_pct}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh trả (RO)</div><div class="kpi-val" style="color:#334155">{return_count}</div><div class="kpi-sub">{return_pct}</div></div>
  </div>
  <div class="section-title">Thống kê theo vùng / miền</div>
  <table>
    <thead><tr><th>Vùng / Miền</th><th class="num">Tổng lệnh</th><th class="num">Lệnh đóng (%)</th><th class="num">Lệnh trả (%)</th></tr></thead>
    <tbody>{reg_html}</tbody>
  </table>
  <div class="section-title">Thống kê theo tỉnh / thành phố ({len(province_rows)} địa phương)</div>
  <table>
    <thead><tr><th>Tỉnh / Thành</th><th class="num">Tổng lệnh</th><th class="num">Lệnh đóng (%)</th><th class="num">Lệnh trả (%)</th></tr></thead>
    <tbody>{prov_html}</tbody>
  </table>
  {carrier_section}
  {inline_trips_section}
  <div class="footer">{html.escape(page1_footer)}</div>
</body>
</html>"""
        est_height_1 = base_summary_h + page1_extra_h + 70
        res1 = cls.render_html_to_png(doc1, width=cls._REPORT_WIDTH, height=est_height_1, prefix="stats1")
        if not res1.get("ok"):
            return res1

        pages: list[dict[str, Any]] = [
            {
                **res1,
                "page": 1,
                "total_pages": total_pages,
                "row_start": 1 if inline_trips else 0,
                "row_end": len(all_trips) if inline_trips else 0,
                "kind": "summary_and_trips" if inline_trips else "summary",
            }
        ]

        for page_offset, (start_idx, batch) in enumerate(trip_pages, start=2):
            end_idx = start_idx + len(batch) - 1
            table_html = _render_daily_trip_table(
                start_idx,
                batch,
                f"Bảng chi tiết các lệnh trong ngày (Lệnh {start_idx}–{end_idx} / {len(all_trips)})",
            )
            doc_k = f"""<!doctype html>
<html lang="vi">
<head><meta charset="utf-8"><style>{cls._BASE_CSS}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-title">VSICO - DANH SÁCH LỆNH VẬN CHUYỂN NGÀY {html.escape(report_date)}</div>
      <div class="header-sub">Hiển thị lệnh {start_idx}–{end_idx} / {len(all_trips)} | Thời điểm trích xuất: {now_str}</div>
    </div>
    <div class="page-pill">Trang {page_offset} / {total_pages}</div>
  </div>
  {table_html}
  <div class="footer">Trang {page_offset}/{total_pages} · Hiển thị lệnh {start_idx}–{end_idx}/{len(all_trips)} | VSICO Zalo Bot</div>
</body>
</html>"""
            est_h_k = 210 + cls._estimate_trip_rows_height(batch, trip_col_wraps) + 50
            res_k = cls.render_html_to_png(
                doc_k, width=cls._REPORT_WIDTH, height=est_h_k, prefix=f"stats{page_offset}"
            )
            if res_k.get("ok"):
                pages.append(
                    {
                        **res_k,
                        "page": page_offset,
                        "total_pages": total_pages,
                        "row_start": start_idx,
                        "row_end": end_idx,
                        "kind": "trips",
                    }
                )

        return {
            **res1,
            "total_pages": len(pages),
            "pages": pages,
        }

    @classmethod
    def render_province_detail_report(
        cls,
        *,
        province_name: str,
        report_date: str,
        total_plans: int,
        assigned_count: int,
        closed_count: int | None = None,
        open_count: int | None = None,
        load_count: int = 0,
        return_count: int = 0,
        trips: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Sinh bộ ảnh PNG full chiều rộng báo cáo chi tiết 100% lệnh thuộc một tỉnh/thành (tự tách nhiều ảnh khi dài)."""
        del closed_count, open_count  # Giữ tham số tương thích ngược, không hiển thị KPI trùng lặp
        now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
        unassigned_count = max(0, total_plans - assigned_count)
        sliced_pages = cls._slice_pages(
            trips,
            first_page_size=cls._PROVINCE_FIRST_PAGE_ROWS,
            next_page_size=cls._PROVINCE_NEXT_PAGE_ROWS,
        )
        total_pages = len(sliced_pages)
        prov_col_wraps = {"customer": 22, "warehouse": 22, "carrier_name": 16, "vehicle": 20}

        pages: list[dict[str, Any]] = []
        for page_num, (start_idx, batch) in enumerate(sliced_pages, start=1):
            end_idx = start_idx + len(batch) - 1 if batch else 0
            body_html = "".join(
                "<tr>"
                f"<td class='num'>{start_idx + offset}</td>"
                f"<td class='nowrap'><b>{html.escape(r.get('order_code') or '-')}</b></td>"
                f"<td class='nowrap'>{html.escape(r.get('order_type') or '-')}</td>"
                f"<td class='nowrap'>{html.escape(r.get('container_no') or 'Chưa có')}</td>"
                f"<td>{html.escape(r.get('customer') or '-')}</td>"
                f"<td>{html.escape(r.get('warehouse') or '-')}</td>"
                f"<td>{html.escape(r.get('carrier_name') or '-')}</td>"
                f"<td>{html.escape(r.get('vehicle') or 'Chưa bố trí')}</td>"
                f"<td class='{cls._status_badge_class(r.get('status') or '')}'>{html.escape(r.get('status') or '-')}</td>"
                "</tr>"
                for offset, r in enumerate(batch)
            ) or "<tr><td colspan='9'>Không có lệnh nào phù hợp tại địa phương này</td></tr>"

            page_pill = f'<div class="page-pill">Trang {page_num} / {total_pages}</div>' if total_pages > 1 else ""
            kpi_block = ""
            base_h = 215
            if page_num == 1:
                kpi_block = f"""  <div class="kpi-grid-5">
    <div class="kpi-card"><div class="kpi-label">Tổng lệnh tỉnh</div><div class="kpi-val">{total_plans}</div><div class="kpi-sub">100%</div></div>
    <div class="kpi-card"><div class="kpi-label">Đã bố trí xe</div><div class="kpi-val" style="color:#15803d">{assigned_count}</div><div class="kpi-sub">{cls._pct_str(assigned_count, total_plans)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Chưa có xe</div><div class="kpi-val" style="color:#b45309">{unassigned_count}</div><div class="kpi-sub">{cls._pct_str(unassigned_count, total_plans)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đóng (LO)</div><div class="kpi-val" style="color:#0369a1">{load_count}</div><div class="kpi-sub">{cls._pct_str(load_count, total_plans)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh trả (RO)</div><div class="kpi-val" style="color:#334155">{return_count}</div><div class="kpi-sub">{cls._pct_str(return_count, total_plans)}</div></div>
  </div>"""
                base_h = 325

            sec_title = (
                f"Danh sách chi tiết các lệnh (Lệnh {start_idx}–{end_idx} / {len(trips)})"
                if total_pages > 1 and batch
                else f"Danh sách chi tiết các lệnh ({len(trips)} lệnh)"
            )
            footer_txt = (
                f"Trang {page_num}/{total_pages} · Hiển thị lệnh {start_idx}–{end_idx}/{len(trips)} tại {province_name} | VSICO Zalo Bot"
                if total_pages > 1 and batch
                else f"Hiển thị đủ {len(trips)}/{len(trips)} lệnh tại {province_name} | VSICO Zalo Bot"
            )

            doc = f"""<!doctype html>
<html lang="vi">
<head><meta charset="utf-8"><style>{cls._BASE_CSS}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-title">VSICO - CHI TIẾT KẾ HOẠCH {html.escape(province_name.upper())}</div>
      <div class="header-sub">Ngày kế hoạch: {html.escape(report_date)} | Thời điểm trích xuất: {now_str}</div>
    </div>
    {page_pill}
  </div>
{kpi_block}
  <div class="section-title">{html.escape(sec_title)}</div>
  <table>
    <thead>
      <tr>
        <th class="num">#</th><th>Mã lệnh</th><th>Loại</th><th>Số Cont</th><th>Khách hàng</th>
        <th>Kho / Điểm đến</th><th>Nhà xe</th><th>Xe / Tài xế</th><th>Trạng thái</th>
      </tr>
    </thead>
    <tbody>{body_html}</tbody>
  </table>
  <div class="footer">{html.escape(footer_txt)}</div>
</body>
</html>"""
            est_height = base_h + cls._estimate_trip_rows_height(batch, prov_col_wraps) + 55
            res = cls.render_html_to_png(
                doc, width=cls._REPORT_WIDTH, height=est_height, prefix=f"province{page_num}"
            )
            if not res.get("ok"):
                if page_num == 1:
                    return res
                break
            pages.append(
                {
                    **res,
                    "page": page_num,
                    "total_pages": total_pages,
                    "row_start": start_idx if batch else 0,
                    "row_end": end_idx,
                }
            )

        if not pages:
            return {"ok": False, "error": "Không thể tạo ảnh báo cáo chi tiết tỉnh."}
        return {
            **pages[0],
            "total_pages": len(pages),
            "pages": pages,
        }

    @classmethod
    def render_trip_table_report(
        cls,
        *,
        title: str,
        subtitle: str,
        rows: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Sinh ảnh PNG bảng danh sách chi tiết các chuyến xe (Mã lệnh, Loại, Cont, Nhà xe, Xe/Moóc, Tài xế, Trạng thái)."""
        now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
        body_html = "".join(
            "<tr>"
            f"<td><b>{html.escape(r.get('order_code') or '-')}</b></td>"
            f"<td>{html.escape(r.get('order_type') or '-')}</td>"
            f"<td>{html.escape(r.get('container_no') or 'Chưa có')}</td>"
            f"<td>{html.escape(r.get('carrier_name') or '-')}</td>"
            f"<td>{html.escape(r.get('vehicle') or 'Chưa báo')}</td>"
            f"<td>{html.escape(r.get('driver') or '-')}</td>"
            f"<td>{html.escape(r.get('warehouse') or '-')}</td>"
            f"<td>{html.escape(r.get('status') or '-')}</td>"
            "</tr>"
            for r in rows[:25]
        ) or "<tr><td colspan='8'>Không có chuyến nào phù hợp</td></tr>"

        doc = f"""<!doctype html>
<html lang="vi">
<head><meta charset="utf-8"><style>{cls._BASE_CSS}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-title">{html.escape(title)}</div>
      <div class="header-sub">{html.escape(subtitle)} | Cập nhật lúc: {now_str}</div>
    </div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Mã lệnh</th><th>Loại</th><th>Số Cont</th><th>Nhà xe</th>
        <th>Đầu kéo / Moóc</th><th>Tài xế / SĐT</th><th>Kho / Điểm đến</th><th>Trạng thái TMS</th>
      </tr>
    </thead>
    <tbody>{body_html}</tbody>
  </table>
  <div class="footer">Hiển thị {min(len(rows), 25)}/{len(rows)} chuyến | VSICO Zalo Bot</div>
</body>
</html>"""
        est_height = 240 + min(max(len(rows), 1), 25) * 40
        return cls.render_html_to_png(doc, width=cls._REPORT_WIDTH, height=est_height, prefix="trips")
