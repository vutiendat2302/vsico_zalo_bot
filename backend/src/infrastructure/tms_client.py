"""Client tích hợp API đọc dữ liệu từ hệ thống TMS (`be-tms`).

Tuân thủ đặc tả trong `docs/VSICO_bot_api.docx`:
- `POST /login` lấy Bearer token (tự động đăng nhập lại nếu gặp 401).
- `GET /carriers` (phân trang) lấy danh mục nhà xe.
- `GET /customers/get-dropdown` lấy danh mục khách hàng.
- `GET /warehouses` (phân trang) lấy danh mục kho và `forwarder_relations`.
- `GET /dispatch/confirmed?plan_date=YYYY-MM-DD` và `GET /transport-plan/my-orders` lấy kế hoạch ngày.
- `GET /dispatch/{id}` lấy chi tiết các điểm khi lệnh nhiều điểm.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from typing import Any, Optional

import httpx

from src.config.settings import settings
from src.domain.rules import mask_phone
from src.observability.logging import get_logger

logger = get_logger(__name__)


class TmsApiError(RuntimeError):
    """Lỗi khi gọi API hệ thống TMS."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        *,
        response_body: Optional[dict[str, Any] | str] = None,
        is_retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.is_retryable = is_retryable


class TmsApiClient:
    """HTTP client kết nối, đọc và đẩy cập nhật điều phối sang API `be-tms`."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        integration_token: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or settings.TMS_BASE_URL).rstrip("/")
        self.username = username if username is not None else settings.TMS_USERNAME
        self.password = password if password is not None else settings.TMS_PASSWORD
        self.timeout = timeout_seconds or settings.TMS_TIMEOUT_SECONDS
        self.integration_token = (
            integration_token
            if integration_token is not None
            else settings.TMS_ZALO_INTEGRATION_TOKEN
        )
        self._token: Optional[str] = None
        self.token_obtained_at: Optional[datetime] = None
        self._token_lock = threading.Lock()
        self.forwarder_id: Optional[int] = None

    def has_valid_credentials(self) -> bool:
        """Kiểm tra đã cấu hình đầy đủ URL, tài khoản và mật khẩu TMS thực hay chưa."""
        if not self.base_url or not self.username or not self.password:
            return False
        if "your_tms_" in self.username or "your_tms_" in self.password:
            return False
        return True

    def _is_token_stale(self) -> bool:
        """Kiểm tra token TMS hiện tại đã quá tuổi làm mới chủ động hay chưa."""
        if not self._token or self.token_obtained_at is None:
            return True
        max_age_min = max(1, int(getattr(settings, "TMS_TOKEN_MAX_AGE_MINUTES", 120) or 120))
        return datetime.now(timezone.utc) - self.token_obtained_at >= timedelta(minutes=max_age_min)

    def _validate_credentials(self) -> None:
        """Kiểm tra cấu hình kết nối TMS trước khi gọi API."""
        if not self.base_url or not self.username or not self.password:
            raise TmsApiError(
                "Thiếu cấu hình TMS_BASE_URL, TMS_USERNAME hoặc TMS_PASSWORD trong file .env."
            )
        if "your_tms_" in self.username or "your_tms_" in self.password:
            raise TmsApiError(
                "TMS_USERNAME / TMS_PASSWORD trong .env vẫn đang là giá trị mẫu. "
                "Vui lòng điền tài khoản TMS thật trước khi đồng bộ."
            )

    def login(self) -> str:
        """Đăng nhập `POST /login` để lấy Bearer token và `forwarder_id`."""
        self._validate_credentials()
        url = f"{self.base_url}/login"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                url,
                json={"username": self.username, "password": self.password},
                headers={"Accept": "application/json"},
            )
        if resp.status_code >= 400:
            raise TmsApiError(
                f"Đăng nhập TMS thất bại ({resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
            )
        payload = resp.json()
        token = (payload.get("authorisation") or {}).get("token")
        if not token:
            raise TmsApiError("Phản hồi /login của TMS không chứa authorisation.token.")
        user_info = payload.get("user") or {}
        with self._token_lock:
            if user_info.get("forwarder_id") is not None:
                self.forwarder_id = int(user_info["forwarder_id"])
            self._token = str(token)
            self.token_obtained_at = datetime.now(timezone.utc)
            return self._token

    def ensure_fresh_token(self, *, force_refresh: bool = False) -> str:
        """Bảo đảm luôn có Bearer token còn hạn; tự đăng nhập lại khi trống hoặc quá tuổi."""
        with self._token_lock:
            needs_login = force_refresh or not self._token or self._is_token_stale()
            current_token = self._token
        if needs_login or not current_token:
            return self.login()
        return current_token

    def _request_json(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        headers_extra: Optional[dict[str, str]] = None,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        """Gửi HTTP request có Bearer token và tự đăng nhập lại khi token hết hạn."""
        token = self.ensure_fresh_token()

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **(headers_extra or {}),
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
            )

        if resp.status_code == 401 and retry_on_401:
            logger.info("Token TMS hết hạn (401), đang tự động đăng nhập lại bằng TMS_USERNAME...")
            self.login()
            return self._request_json(
                method,
                path,
                params=params,
                json_body=json_body,
                headers_extra=headers_extra,
                retry_on_401=False,
            )

        if resp.status_code >= 400:
            raise TmsApiError(
                f"Lỗi gọi TMS {method} {path} ({resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
            )

        payload = resp.json()
        if isinstance(payload, dict) and payload.get("status") == "error":
            err_msg = str(payload.get("message") or "")
            low_err = err_msg.lower()
            if retry_on_401 and any(k in low_err for k in ("token", "unauth", "expired", "hết hạn")):
                logger.info("TMS báo token không hợp lệ ở payload, đang tự đăng nhập lại...")
                self.login()
                return self._request_json(
                    method,
                    path,
                    params=params,
                    json_body=json_body,
                    headers_extra=headers_extra,
                    retry_on_401=False,
                )
            raise TmsApiError(f"TMS trả lỗi tại {path}: {err_msg}")
        return payload

    def _fetch_paginated(self, path: str, per_page: int = 100, **extra_params: Any) -> list[dict[str, Any]]:
        """Lặp toàn bộ các trang theo khối `pagination.last_page`."""
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            params = {"page": page, "per_page": per_page, **extra_params}
            payload = self._request_json("GET", path, params=params)
            data = payload.get("data") or []
            if isinstance(data, list):
                items.extend(data)
            pagination = payload.get("pagination") or {}
            last_page = int(pagination.get("last_page") or 1)
            if page >= last_page or not data:
                break
            page += 1
        return items

    def fetch_carriers(self, per_page: int = 100, active_only: bool = True) -> list[dict[str, Any]]:
        """Lấy toàn bộ danh mục nhà xe từ `GET /carriers`."""
        rows = self._fetch_paginated("/carriers", per_page=per_page)
        if active_only:
            return [r for r in rows if int(r.get("status", 1)) == 1]
        return rows

    def fetch_customers(self, forwarder_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Lấy toàn bộ danh mục khách hàng từ `/customers/get-dropdown` (fallback `/customers`)."""
        eff_fid = forwarder_id if forwarder_id is not None else self.forwarder_id
        params = {"forwarder_id": eff_fid} if eff_fid is not None else None
        try:
            payload = self._request_json("GET", "/customers/get-dropdown", params=params)
            data = payload.get("data") or []
            return data if isinstance(data, list) else []
        except TmsApiError as exc:
            if exc.status_code == 422 and eff_fid is None:
                logger.info("TMS /customers/get-dropdown yêu cầu forwarder_id -> chuyển sang GET /customers phân trang.")
                return self._fetch_paginated("/customers", per_page=100)
            raise

    def fetch_warehouses(self, per_page: int = 100, active_only: bool = True) -> list[dict[str, Any]]:
        """Lấy toàn bộ danh mục kho và liên kết khách hàng từ `GET /warehouses`."""
        rows = self._fetch_paginated("/warehouses", per_page=per_page)
        if active_only:
            return [r for r in rows if int(r.get("status", 1)) == 1]
        return rows

    def fetch_trailers(self, per_page: int = 100, active_only: bool = True) -> list[dict[str, Any]]:
        """Lấy toàn bộ danh mục rơ-moóc (moóc) từ `GET /carrier-moocs`."""
        rows = self._fetch_paginated("/carrier-moocs", per_page=per_page)
        if active_only:
            return [r for r in rows if int(r.get("status", 1)) == 1]
        return rows

    def fetch_confirmed_dispatches(self, plan_date: str) -> list[dict[str, Any]]:
        """Lấy danh sách chuyến đã gán nhà xe theo ngày từ `GET /dispatch/confirmed`."""
        payload = self._request_json("GET", "/dispatch/confirmed", params={"plan_date": plan_date})
        data = payload.get("data") or []
        return data if isinstance(data, list) else []

    def fetch_my_orders(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Lấy danh sách lệnh đóng/trả trong khoảng ngày từ `GET /transport-plan/my-orders`."""
        payload = self._request_json(
            "GET",
            "/transport-plan/my-orders",
            params={"start_date": start_date, "end_date": end_date},
        )
        data = payload.get("data") or []
        return data if isinstance(data, list) else []

    def fetch_dispatch_detail(self, dispatch_id: int) -> dict[str, Any]:
        """Lấy chi tiết chuyến (bao gồm danh sách điểm `points`) từ `GET /dispatch/{id}`."""
        payload = self._request_json("GET", f"/dispatch/{dispatch_id}")
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {}

    def fetch_transport_plan_by_date(self, plan_date: str, region: int = 1) -> dict[str, Any]:
        """Kéo toàn bộ kế hoạch vận chuyển theo ngày (`YYYY-MM-DD`) và miền từ `GET /transport-plan`."""
        payload = self._request_json(
            "GET",
            "/transport-plan",
            params={"plan_date": plan_date, "region": region},
        )
        return payload if isinstance(payload, dict) else {"data": []}

    def _resolve_integration_url(self, endpoint: Optional[str] = None) -> str:
        """Chuẩn hóa URL endpoint tích hợp Zalo, tránh lặp `/api/api` khi `TMS_BASE_URL` đã có `/api`."""
        ep = (endpoint or settings.TMS_WRITE_ENDPOINT or "/api/integrations/zalo/dispatch-assignment").strip()
        if not ep.startswith("/"):
            ep = f"/{ep}"
        base = self.base_url.rstrip("/")
        if base.endswith("/api") and ep.startswith("/api/"):
            return f"{base}{ep[4:]}"
        if not base.endswith("/api") and not ep.startswith("/api/"):
            return f"{base}/api{ep}"
        return f"{base}{ep}"

    def _validate_integration_token(self) -> str:
        """Kiểm tra token tích hợp Zalo riêng biệt (không dùng chung token đăng nhập Admin)."""
        token = (self.integration_token or "").strip()
        if not self.base_url:
            raise TmsApiError("Thiếu cấu hình TMS_BASE_URL.", status_code=None, is_retryable=False)
        if not token or token.startswith("your_tms_"):
            raise TmsApiError(
                "Thiếu hoặc chưa cấu hình TMS_ZALO_INTEGRATION_TOKEN hợp lệ.",
                status_code=401,
                is_retryable=False,
            )
        return token

    def push_dispatch_assignment(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> tuple[int, dict[str, Any]]:
        """Gọi API chính thức `POST /api/integrations/zalo/dispatch-assignment` để cập nhật từng phần."""
        token = self._validate_integration_token()
        url = self._resolve_integration_url()
        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise TmsApiError(
                f"Hết thời gian chờ kết nối TMS ({self.timeout}s): {mask_phone(str(exc))}",
                status_code=None,
                is_retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise TmsApiError(
                f"Lỗi mạng khi kết nối TMS: {mask_phone(str(exc))}",
                status_code=None,
                is_retryable=True,
            ) from exc

        parsed_body: Optional[dict[str, Any] | str] = None
        try:
            parsed_body = resp.json()
        except Exception:
            parsed_body = mask_phone((resp.text or "")[:500])

        status = int(resp.status_code)
        if status >= 400:
            retryable = status == 429 or status >= 500
            err_detail = (
                parsed_body.get("message") or parsed_body.get("detail") or parsed_body.get("error")
                if isinstance(parsed_body, dict)
                else str(parsed_body or "")
            )
            raise TmsApiError(
                f"TMS trả lỗi HTTP {status} tại dispatch-assignment: {mask_phone(str(err_detail)[:300])}",
                status_code=status,
                response_body=parsed_body,
                is_retryable=retryable,
            )

        if isinstance(parsed_body, dict) and parsed_body.get("status") == "error":
            raise TmsApiError(
                f"TMS từ chối nghiệp vụ tại dispatch-assignment: {mask_phone(str(parsed_body.get('message') or '')[:300])}",
                status_code=status,
                response_body=parsed_body,
                is_retryable=False,
            )

        return status, parsed_body if isinstance(parsed_body, dict) else {"data": parsed_body}

    def push_dispatch_update(
        self,
        payload: dict[str, Any],
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> tuple[int, dict[str, Any]]:
        """Wrapper tương thích ngược: đẩy cập nhật điều phối qua `push_dispatch_assignment`."""
        return self.push_dispatch_assignment(
            payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
