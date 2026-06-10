"""Async HTTP client for the Proxmox VE JSON API.

Provides :class:`PveClient`, a thin :mod:`httpx` wrapper that attaches ``PVEAPIToken`` authentication,
enforces a concurrency limit, parses Proxmox ``{data, errors, message}`` envelopes, and raises
:class:`~proxmox_ve_mcp.client.errors.PveApiError` on transport or API failures.

Successful calls return the unwrapped ``data`` field when present; otherwise the decoded JSON body.
"""

import asyncio
from typing import Any

import httpx

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.constants import (
    DEFAULT_HTTP_TIMEOUT_SEC,
    LONG_HTTP_TIMEOUT_SEC,
    MAX_CONCURRENT_REQUESTS,
)


class PveClient:
    """Async HTTP client for Proxmox VE ``/api2/json`` endpoints.

    Uses settings from :class:`~proxmox_ve_mcp.config.PveSettings` for base URL, TLS verification,
    and authorization. Concurrent requests are limited by a semaphore
    (:data:`~proxmox_ve_mcp.constants.MAX_CONCURRENT_REQUESTS`).

    Call :meth:`aclose` when the client is no longer needed (for example at MCP server shutdown).
    """

    def __init__(self, settings: PveSettings) -> None:
        """Create an httpx async client bound to Proxmox settings.

        Args:
            settings: Validated host, port, token, and TLS options used for all requests.
        """
        self._settings = settings
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers={"Authorization": settings.authorization_header()},
            verify=settings.verify_ssl,
            timeout=httpx.Timeout(DEFAULT_HTTP_TIMEOUT_SEC),
        )

    async def aclose(self) -> None:
        """Close the underlying httpx connection pool and release resources."""
        await self._client.aclose()

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a GET request to a Proxmox API path.

        Args:
            path: API path relative to ``/api2/json`` (leading slash optional).
            params: Optional query parameters forwarded to httpx.
            timeout: Per-request timeout in seconds; defaults to
                :data:`~proxmox_ve_mcp.constants.DEFAULT_HTTP_TIMEOUT_SEC`.

        Returns:
            Unwrapped ``data`` field from the JSON response, or the full decoded payload.

        Raises:
            PveApiError: On transport failure, non-success HTTP status, invalid JSON, or Proxmox
                ``errors`` in the response body.
        """
        return await self._request("GET", path, params=params, timeout=timeout)

    async def post(
        self,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a POST request with form-encoded data to a Proxmox API path.

        Args:
            path: API path relative to ``/api2/json`` (leading slash optional).
            data: Optional form body fields (Proxmox write operations).
            timeout: Per-request timeout in seconds; defaults to
                :data:`~proxmox_ve_mcp.constants.DEFAULT_HTTP_TIMEOUT_SEC`.

        Returns:
            Unwrapped ``data`` field from the JSON response, or the full decoded payload.

        Raises:
            PveApiError: On transport failure, non-success HTTP status, invalid JSON, or Proxmox
                ``errors`` in the response body.
        """
        return await self._request("POST", path, data=data, timeout=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Perform an authenticated Proxmox API request and return parsed JSON data."""
        normalized = path if path.startswith("/") else f"/{path}"
        request_timeout = timeout or DEFAULT_HTTP_TIMEOUT_SEC

        async with self._semaphore:
            try:
                response = await self._client.request(
                    method,
                    normalized,
                    params=params,
                    data=data,
                    timeout=httpx.Timeout(request_timeout),
                )
            except httpx.HTTPError as exc:
                raise PveApiError(f"HTTP request failed: {exc}") from exc

        return self._parse_response(response, endpoint=normalized)

    def _parse_response(self, response: httpx.Response, *, endpoint: str) -> Any:
        """Decode a Proxmox JSON envelope or raise :class:`PveApiError`."""
        try:
            payload = response.json()
        except ValueError as exc:
            raise PveApiError(
                f"Invalid JSON from Proxmox API (HTTP {response.status_code})",
                status_code=response.status_code,
                endpoint=endpoint,
            ) from exc

        pve_message = payload.get("message") if isinstance(payload, dict) else None
        pve_errors = payload.get("errors") if isinstance(payload, dict) else payload

        if not response.is_success:
            detail = pve_message or response.reason_phrase
            raise PveApiError(
                f"Proxmox API HTTP {response.status_code}: {detail}".strip(": "),
                status_code=response.status_code,
                pve_errors=pve_errors,
                pve_message=pve_message if isinstance(pve_message, str) else None,
                endpoint=endpoint,
            )

        if isinstance(payload, dict) and payload.get("data") is None and payload.get("errors"):
            raise PveApiError(
                "Proxmox API returned errors",
                status_code=response.status_code,
                pve_errors=payload.get("errors"),
            )

        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]

        return payload

    @staticmethod
    def long_timeout() -> float:
        """Return the recommended timeout for long-running Proxmox tasks.

        Returns:
            Seconds to use when polling task status or waiting on slow operations
            (:data:`~proxmox_ve_mcp.constants.LONG_HTTP_TIMEOUT_SEC`).
        """
        return LONG_HTTP_TIMEOUT_SEC
