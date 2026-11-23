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
    body {
        font-family: "Noto Sans", "Roboto", "DejaVu Sans", Arial, sans-serif;
        background: #ffffff;
        color: #0f172a;
        padding: 20px 24px;
        width: 1120px;
    }
    .header {
        background: #0f172a;
        color: #f8fafc;
        padding: 16px 20px;
        border-radius: 4px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
    }
    .header-title { font-size: 20px; font-weight: 700; letter-spacing: 0.3px; }
    .header-sub { font-size: 13px; color: #cbd5e1; margin-top: 4px; }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-bottom: 16px;
    }
    .kpi-card {
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        padding: 12px 14px;
        background: #f8fafc;
    }
    .kpi-label { font-size: 12px; color: #475569; text-transform: uppercase; font-weight: 600; }
    .kpi-val { font-size: 24px; font-weight: 700; color: #0f172a; margin-top: 4px; }
    .section-title {
        font-size: 15px;
        font-weight: 700;
        color: #1e293b;
        margin: 14px 0 8px 0;
        border-left: 4px solid #0284c7;
        padding-left: 10px;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        margin-bottom: 14px;
    }
    th {
        background: #e2e8f0;
        color: #0f172a;
        font-weight: 700;
        text-align: left;
        padding: 8px 10px;
        border: 1px solid #cbd5e1;
    }
    td {
        padding: 7px 10px;
        border: 1px solid #cbd5e1;
        vertical-align: top;
    }
    tr:nth-child(even) td { background: #f8fafc; }
    .num { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
    .badge-ok { color: #15803d; font-weight: 700; }
    .badge-warn { color: #b45309; font-weight: 700; }
    .badge-err { color: #b91c1c; font-weight: 700; }
    .footer {
        font-size: 11px;
        color: #64748b;
        margin-top: 10px;
        text-align: right;
    }
    """

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
        """Sinh ảnh PNG báo cáo tổng hợp gồm cả bảng thống kê tỷ lệ % đóng/mở lẫn bảng danh sách chi tiết các lệnh."""
        now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
        assigned = assigned_count if assigned_count is not None else max(0, total_plans - missing_vehicle_count)
        closed = closed_count if closed_count is not None else assigned
        opened = open_count if open_count is not None else max(0, total_plans - closed)

        load_pct = cls._pct_str(load_count, total_plans)
        return_pct = cls._pct_str(return_count, total_plans)
        assigned_pct = cls._pct_str(assigned, total_plans)
        closed_pct = cls._pct_str(closed, total_plans)
        open_pct = cls._pct_str(opened, total_plans)

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
            for p, t, lo, ro in province_rows[:18]
        ) or "<tr><td colspan='4'>Chưa có dữ liệu tỉnh/thành</td></tr>"

        carrier_section = ""
        extra_h = 0
        if incomplete_carriers:
            c_rows = "".join(
                f"<tr><td>{html.escape(c)}</td><td class='num'>{tot}</td><td class='num badge-warn'>{miss} ({cls._pct_str(miss, tot)})</td></tr>"
                for c, tot, miss in incomplete_carriers[:10]
            )
            carrier_section = (
                "<div class='section-title'>Nhà xe chưa báo đủ thông tin xe / container</div>"
                "<table><thead><tr><th>Nhà xe</th><th class='num'>Tổng lệnh</th><th class='num'>Chưa đủ thông tin</th></tr></thead>"
                f"<tbody>{c_rows}</tbody></table>"
            )
            extra_h += 80 + min(len(incomplete_carriers), 10) * 34

        trips_section = ""
        if trips:
            max_trip_rows = 45
            t_rows_html = "".join(
                "<tr>"
                f"<td class='num'>{idx}</td>"
                f"<td><b>{html.escape(t.get('order_code') or '-')}</b></td>"
                f"<td>{html.escape(t.get('order_type') or '-')}</td>"
                f"<td>{html.escape(t.get('province') or '-')}</td>"
                f"<td>{html.escape(t.get('container_no') or 'Chưa có')}</td>"
                f"<td>{html.escape(t.get('customer') or '-')}</td>"
                f"<td>{html.escape(t.get('carrier_name') or '-')}</td>"
                f"<td>{html.escape(t.get('vehicle') or 'Chưa báo')}</td>"
                f"<td>{html.escape(t.get('status') or '-')}</td>"
                "</tr>"
                for idx, t in enumerate(trips[:max_trip_rows], start=1)
            )
            shown_note = (
                f" (hiển thị {min(len(trips), max_trip_rows)}/{len(trips)} lệnh)"
                if len(trips) > max_trip_rows
                else f" ({len(trips)} lệnh)"
            )
            trips_section = (
                f"<div class='section-title'>Bảng chi tiết các lệnh trong ngày{shown_note}</div>"
                "<table><thead><tr>"
                "<th class='num'>#</th><th>Mã lệnh</th><th>Loại</th><th>Tỉnh/TP</th>"
                "<th>Số Cont</th><th>Khách hàng</th><th>Nhà xe</th><th>Xe / Tài xế</th><th>Trạng thái</th>"
                f"</tr></thead><tbody>{t_rows_html}</tbody></table>"
            )
            extra_h += 95 + min(len(trips), max_trip_rows) * 36

        doc = f"""<!doctype html>
<html lang="vi">
<head><meta charset="utf-8"><style>{cls._BASE_CSS}
.kpi-grid-6 {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 16px; }}
.kpi-sub {{ font-size: 11px; color: #64748b; margin-top: 2px; }}
</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-title">VSICO - BÁO CÁO ĐIỀU HÀNH VẬN TẢI CONTAINER</div>
      <div class="header-sub">Kế hoạch ngày: {html.escape(report_date)} | Thời điểm trích xuất: {now_str}</div>
    </div>
  </div>
  <div class="kpi-grid-6">
    <div class="kpi-card"><div class="kpi-label">Tổng số lệnh</div><div class="kpi-val">{total_plans}</div><div class="kpi-sub">100%</div></div>
    <div class="kpi-card"><div class="kpi-label">Đã bố trí xe</div><div class="kpi-val" style="color:#15803d">{assigned}</div><div class="kpi-sub">{assigned_pct}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đã đóng</div><div class="kpi-val" style="color:#0369a1">{closed}</div><div class="kpi-sub">{closed_pct}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đang mở</div><div class="kpi-val" style="color:#b45309">{opened}</div><div class="kpi-sub">{open_pct}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đóng (LO)</div><div class="kpi-val">{load_count}</div><div class="kpi-sub">{load_pct}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh trả (RO)</div><div class="kpi-val">{return_count}</div><div class="kpi-sub">{return_pct}</div></div>
  </div>
  <div class="section-title">Thống kê theo vùng / miền</div>
  <table>
    <thead><tr><th>Vùng / Miền</th><th class="num">Tổng lệnh</th><th class="num">Lệnh đóng (%)</th><th class="num">Lệnh trả (%)</th></tr></thead>
    <tbody>{reg_html}</tbody>
  </table>
  <div class="section-title">Thống kê theo tỉnh / thành phố</div>
  <table>
    <thead><tr><th>Tỉnh / Thành</th><th class="num">Tổng lệnh</th><th class="num">Lệnh đóng (%)</th><th class="num">Lệnh trả (%)</th></tr></thead>
    <tbody>{prov_html}</tbody>
  </table>
  {carrier_section}
  {trips_section}
  <div class="footer">Hệ thống VSICO Zalo Bot &amp; TMS Integration</div>
</body>
</html>"""
        est_height = 480 + len(region_rows) * 34 + min(len(province_rows), 18) * 34 + extra_h
        return cls.render_html_to_png(doc, width=1220, height=est_height, prefix="stats")

    @classmethod
    def render_province_detail_report(
        cls,
        *,
        province_name: str,
        report_date: str,
        total_plans: int,
        assigned_count: int,
        closed_count: int,
        open_count: int,
        load_count: int,
        return_count: int,
        trips: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Sinh ảnh PNG báo cáo chi tiết các lệnh thuộc riêng một tỉnh/thành trong ngày kèm KPI tỷ lệ %."""
        now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
        max_rows = 60
        body_html = "".join(
            "<tr>"
            f"<td class='num'>{idx}</td>"
            f"<td><b>{html.escape(r.get('order_code') or '-')}</b></td>"
            f"<td>{html.escape(r.get('order_type') or '-')}</td>"
            f"<td>{html.escape(r.get('container_no') or 'Chưa có')}</td>"
            f"<td>{html.escape(r.get('customer') or '-')}</td>"
            f"<td>{html.escape(r.get('warehouse') or '-')}</td>"
            f"<td>{html.escape(r.get('carrier_name') or '-')}</td>"
            f"<td>{html.escape(r.get('vehicle') or 'Chưa báo')}</td>"
            f"<td>{html.escape(r.get('status') or '-')}</td>"
            "</tr>"
            for idx, r in enumerate(trips[:max_rows], start=1)
        ) or "<tr><td colspan='9'>Không có lệnh nào phù hợp tại địa phương này</td></tr>"

        doc = f"""<!doctype html>
<html lang="vi">
<head><meta charset="utf-8"><style>{cls._BASE_CSS}
.kpi-grid-6 {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 16px; }}
.kpi-sub {{ font-size: 11px; color: #64748b; margin-top: 2px; }}
</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-title">VSICO - CHI TIẾT KẾ HOẠCH {html.escape(province_name.upper())}</div>
      <div class="header-sub">Ngày kế hoạch: {html.escape(report_date)} | Thời điểm trích xuất: {now_str}</div>
    </div>
  </div>
  <div class="kpi-grid-6">
    <div class="kpi-card"><div class="kpi-label">Tổng lệnh tỉnh</div><div class="kpi-val">{total_plans}</div><div class="kpi-sub">100%</div></div>
    <div class="kpi-card"><div class="kpi-label">Đã bố trí xe</div><div class="kpi-val" style="color:#15803d">{assigned_count}</div><div class="kpi-sub">{cls._pct_str(assigned_count, total_plans)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đã đóng</div><div class="kpi-val" style="color:#0369a1">{closed_count}</div><div class="kpi-sub">{cls._pct_str(closed_count, total_plans)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đang mở</div><div class="kpi-val" style="color:#b45309">{open_count}</div><div class="kpi-sub">{cls._pct_str(open_count, total_plans)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh đóng (LO)</div><div class="kpi-val">{load_count}</div><div class="kpi-sub">{cls._pct_str(load_count, total_plans)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lệnh trả (RO)</div><div class="kpi-val">{return_count}</div><div class="kpi-sub">{cls._pct_str(return_count, total_plans)}</div></div>
  </div>
  <div class="section-title">Danh sách chi tiết các lệnh ({min(len(trips), max_rows)}/{len(trips)} lệnh)</div>
  <table>
    <thead>
      <tr>
        <th class="num">#</th><th>Mã lệnh</th><th>Loại</th><th>Số Cont</th><th>Khách hàng</th>
        <th>Kho / Điểm đến</th><th>Nhà xe</th><th>Xe / Tài xế</th><th>Trạng thái</th>
      </tr>
    </thead>
    <tbody>{body_html}</tbody>
  </table>
  <div class="footer">Hiển thị {min(len(trips), max_rows)}/{len(trips)} lệnh tại {html.escape(province_name)} | VSICO Zalo Bot</div>
</body>
</html>"""
        est_height = 320 + min(max(len(trips), 1), max_rows) * 38
        return cls.render_html_to_png(doc, width=1240, height=est_height, prefix="province")

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
        return cls.render_html_to_png(doc, width=1180, height=est_height, prefix="trips")
