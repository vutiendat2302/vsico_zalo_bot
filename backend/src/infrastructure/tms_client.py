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

from typing import Any, Optional

import httpx

from src.config.settings import settings
from src.observability.logging import get_logger

logger = get_logger(__name__)


class TmsApiError(RuntimeError):
    """Lỗi khi gọi API hệ thống TMS."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TmsApiClient:
    """HTTP client kết nối và đọc dữ liệu từ API `be-tms`."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        self.base_url = (base_url or settings.TMS_BASE_URL).rstrip("/")
        self.username = username if username is not None else settings.TMS_USERNAME
        self.password = password if password is not None else settings.TMS_PASSWORD
        self.timeout = timeout_seconds or settings.TMS_TIMEOUT_SECONDS
        self._token: Optional[str] = None
        self.forwarder_id: Optional[int] = None

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
        if user_info.get("forwarder_id") is not None:
            self.forwarder_id = int(user_info["forwarder_id"])
        self._token = str(token)
        return self._token

    def _request_json(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        """Gửi HTTP request có Bearer token và tự đăng nhập lại khi token hết hạn."""
        if not self._token:
            self.login()

        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.request(
                method,
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                },
            )

        if resp.status_code == 401 and retry_on_401:
            logger.info("Token TMS hết hạn (401), đang đăng nhập lại...")
            self.login()
            return self._request_json(method, path, params=params, retry_on_401=False)

        if resp.status_code >= 400:
            raise TmsApiError(
                f"Lỗi gọi TMS {method} {path} ({resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
            )

        payload = resp.json()
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise TmsApiError(f"TMS trả lỗi tại {path}: {payload.get('message')}")
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

    def fetch_customers(self) -> list[dict[str, Any]]:
        """Lấy toàn bộ danh mục khách hàng từ `GET /customers/get-dropdown`."""
        payload = self._request_json("GET", "/customers/get-dropdown")
        data = payload.get("data") or []
        return data if isinstance(data, list) else []

    def fetch_warehouses(self, per_page: int = 100, active_only: bool = True) -> list[dict[str, Any]]:
        """Lấy toàn bộ danh mục kho và liên kết khách hàng từ `GET /warehouses`."""
        rows = self._fetch_paginated("/warehouses", per_page=per_page)
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
