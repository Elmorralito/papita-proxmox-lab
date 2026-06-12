"""Async HTTP client for pfREST ``/api/v2`` endpoints."""

from typing import Any

import httpx

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.config import PfsSettings
from pfsense_mcp.constants import LONG_HTTP_TIMEOUT_SEC


class PfsClient:
    """Thin httpx wrapper for pfSense REST API v2."""

    def __init__(self, settings: PfsSettings) -> None:
        """Build an async client using ``PfsSettings`` base URL, API key, and TLS options."""
        self._settings = settings
        self._default_timeout = settings.http_timeout_sec
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers={
                "X-API-Key": settings.api_key_header(),
                "Accept": "application/json",
            },
            verify=settings.verify_ssl,
            timeout=httpx.Timeout(self._default_timeout),
        )

    async def aclose(self) -> None:
        """Close the underlying httpx connection pool."""
        await self._client.aclose()

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Issue a pfREST GET request and return unwrapped response data."""
        return await self._request("GET", path, params=params, timeout=timeout)

    async def patch(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Issue a pfREST PATCH request with a JSON body."""
        return await self._request("PATCH", path, json_body=json_body, timeout=timeout)

    async def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Issue a pfREST POST request with a JSON body."""
        return await self._request("POST", path, json_body=json_body, timeout=timeout)

    async def delete(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Issue a pfREST DELETE request with an optional JSON body."""
        return await self._request("DELETE", path, json_body=json_body, timeout=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Execute an HTTP request and map transport or HTTP failures to ``PfsApiError``."""
        normalized = path if path.startswith("/") else f"/{path}"
        request_timeout = timeout or self._default_timeout
        try:
            response = await self._client.request(
                method,
                normalized,
                params=params,
                json=json_body,
                timeout=httpx.Timeout(request_timeout),
            )
        except httpx.HTTPError as exc:
            raise PfsApiError.from_transport(
                f"HTTP request failed: {exc}",
                endpoint=normalized,
                host=self._settings.host,
                api_user=self._settings.api_user,
            ) from exc

        return self._parse_response(response, endpoint=normalized)

    def _parse_response(self, response: httpx.Response, *, endpoint: str) -> Any:
        """Parse pfREST JSON envelopes and raise ``PfsApiError`` on failure codes."""
        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = response.text[:500] if response.text else response.reason_phrase

        if not response.is_success:
            raise PfsApiError.from_http(
                response.status_code,
                payload,
                endpoint=endpoint,
                host=self._settings.host,
                api_user=self._settings.api_user,
            )

        if isinstance(payload, dict):
            pfrest_code = payload.get("code")
            if isinstance(pfrest_code, int) and pfrest_code != 200:
                raise PfsApiError.from_pfrest(payload, endpoint=endpoint)
            if "data" in payload:
                return payload["data"]

        return payload

    @staticmethod
    def long_timeout() -> float:
        """Return the configured long-running pfREST timeout in seconds."""
        return LONG_HTTP_TIMEOUT_SEC
