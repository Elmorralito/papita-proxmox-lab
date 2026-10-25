"""Async HTTP client for the Proxmox VE JSON API.

Provides :class:`PveClient`, a thin :mod:`httpx` wrapper that attaches ``PVEAPIToken`` authentication,
enforces a concurrency limit, parses Proxmox ``{data, errors, message}`` envelopes, and raises
:class:`~proxmox_ve_mcp.client.errors.PveApiError` on transport or API failures.

Successful calls return the unwrapped ``data`` field when present; otherwise the decoded JSON body.
"""

import asyncio
import socket
import ssl
from typing import Any

import httpx

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.constants import (
    DEFAULT_HTTP_TIMEOUT_SEC,
    LONG_HTTP_TIMEOUT_SEC,
    MAX_CONCURRENT_REQUESTS,
)

_UNREACHABLE_HINT = (
    "PVE_HOST did not answer: the node may be powered off or its Tailscale device offline. "
    "Point PVE_HOST at another online cluster member."
)


def _cause_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def transport_error(
    exc: httpx.HTTPError,
    settings: PveSettings,
    *,
    endpoint: str,
    timeout: float,
) -> PveApiError:
    """Map an httpx transport failure to a :class:`PveApiError` with a stable code and hint."""
    target = f"{settings.host}:{settings.port}"
    chain = _cause_chain(exc)
    detail = next((str(e) for e in chain if str(e)), type(exc).__name__)

    def _err(message: str, code: str, hint: str) -> PveApiError:
        return PveApiError(message, endpoint=endpoint, code=code, hint=hint)

    if any(isinstance(e, socket.gaierror) for e in chain) or "Name or service not known" in detail:
        return _err(
            f"PVE_HOST '{settings.host}' does not resolve: {detail}",
            "PVE_DNS_ERROR",
            "Check the Tailscale device name (MagicDNS) or use a node LAN IP (172.16.0.101-104).",
        )
    if isinstance(exc, httpx.ConnectTimeout):
        return _err(f"Timed out connecting to {target}", "PVE_CONNECT_TIMEOUT", _UNREACHABLE_HINT)
    if isinstance(exc, httpx.TimeoutException):
        return _err(
            f"{type(exc).__name__} after {timeout:g}s on {endpoint} ({target})",
            "PVE_TIMEOUT",
            "Connected but the API did not answer in time: node busy, shutting down, or task still running.",
        )
    if any(isinstance(e, ssl.SSLError) for e in chain) or "[SSL" in detail:
        return _err(
            f"TLS handshake with {target} failed: {detail}",
            "PVE_TLS_ERROR",
            "Set PVE_VERIFY_SSL=false for self-signed certs, or use the node's Tailscale TLS name.",
        )
    if any(isinstance(e, ConnectionRefusedError) for e in chain) or "Connection refused" in detail:
        return _err(
            f"Connection refused by {target}",
            "PVE_CONNECTION_REFUSED",
            "Host is up but pveproxy is not listening on PVE_PORT; check the port or pveproxy status.",
        )
    return _err(f"HTTP request to {target}{endpoint} failed: {detail}", "PVE_CONNECTION_ERROR", _UNREACHABLE_HINT)


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
                raise transport_error(exc, self._settings, endpoint=normalized, timeout=request_timeout) from exc

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
