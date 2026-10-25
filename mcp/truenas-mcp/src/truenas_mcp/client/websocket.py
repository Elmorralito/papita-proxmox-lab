"""TrueNAS WebSocket JSON-RPC client."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import ssl
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import InvalidHandshake, InvalidURI

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.config import TnasSettings

logger = logging.getLogger("truenas_mcp.client.websocket")

_UNREACHABLE_HINT = (
    "Host did not answer. TrueNAS is reachable only through the LAN router guest "
    "(pfSense/OpenWrt) or its Tailscale device; check that both are up."
)


def classify_connect_error(exc: BaseException, settings: TnasSettings) -> TnasApiError:
    """Map a connect/handshake failure to an actionable :class:`TnasApiError`."""
    target = f"{settings.host}:{settings.port}"
    if isinstance(exc, TnasApiError):
        return exc
    if isinstance(exc, socket.gaierror):
        return TnasApiError(
            f"TRUENAS_HOST '{settings.host}' does not resolve: {exc}",
            code="DNS_ERROR",
            hint="Check the Tailscale device name (MagicDNS) or use the LAN IP 172.16.0.100.",
        )
    if isinstance(exc, ConnectionRefusedError):
        return TnasApiError(
            f"Connection refused by {target}",
            code="CONNECTION_REFUSED",
            hint="Host is up but nothing listens on TRUENAS_PORT; check the port and the TrueNAS web service.",
        )
    if isinstance(exc, ssl.SSLError):
        return TnasApiError(
            f"TLS handshake with {target} failed: {exc}",
            code="TLS_ERROR",
            hint="Set TRUENAS_VERIFY_SSL=false for self-signed certs, or install a trusted certificate.",
        )
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return TnasApiError(
            f"Timed out connecting to {target}",
            code="CONNECT_TIMEOUT",
            hint=_UNREACHABLE_HINT,
        )
    if isinstance(exc, (InvalidHandshake, InvalidURI)):
        return TnasApiError(
            f"WebSocket handshake with {settings.ws_uri} failed: {exc}",
            code="HANDSHAKE_ERROR",
            hint="Check TRUENAS_WS_PATH (/websocket on SCALE 25+, /api/v2.0/websocket on older builds).",
        )
    if isinstance(exc, OSError):
        return TnasApiError(
            f"Cannot connect to {target}: {exc or type(exc).__name__}",
            code="CONNECTION_ERROR",
            hint=_UNREACHABLE_HINT,
        )
    return TnasApiError(
        f"Unexpected error connecting to {target}: {type(exc).__name__}: {exc}",
        code="CONNECTION_ERROR",
    )


class TnasClient:
    """Persistent WebSocket client for TrueNAS middleware API calls."""

    def __init__(self, settings: TnasSettings) -> None:
        self._settings = settings
        self._ws: ClientConnection | None = None
        self._lock = asyncio.Lock()
        self._msg_id = 0
        self._authenticated = False

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._settings.verify_ssl:
            return ssl.create_default_context()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _next_id(self) -> str:
        self._msg_id += 1
        return str(self._msg_id)

    async def _recv_json(self) -> dict[str, Any]:
        if self._ws is None:
            raise TnasApiError("WebSocket not connected", code="NOT_CONNECTED")
        raw = await asyncio.wait_for(self._ws.recv(), timeout=self._settings.ws_timeout_sec)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TnasApiError("Unexpected non-object WebSocket response", details=data)
        return data

    @staticmethod
    def _matches_request_id(response: dict[str, Any], req_id: str) -> bool:
        resp_id = response.get("id")
        if resp_id is None:
            return False
        return str(resp_id) == req_id or resp_id == int(req_id)

    async def _recv_matching(self, req_id: str) -> dict[str, Any]:
        """Read WebSocket frames until the response for ``req_id`` arrives."""
        deadline = asyncio.get_running_loop().time() + self._settings.ws_timeout_sec
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TnasApiError(
                    f"Timed out waiting for response id={req_id}",
                    code="TIMEOUT",
                )
            response = await asyncio.wait_for(self._recv_json(), timeout=remaining)
            if self._matches_request_id(response, req_id):
                return response
            logger.debug(
                "Skipping non-matching WebSocket message msg=%s id=%s",
                response.get("msg"),
                response.get("id"),
            )

    async def _connect_and_auth(self) -> None:
        uri = self._settings.ws_uri
        logger.info("Connecting to TrueNAS WebSocket at %s", uri)
        self._ws = await websockets.connect(
            uri,
            ssl=self._ssl_context(),
            open_timeout=self._settings.ws_timeout_sec,
            close_timeout=5,
            ping_interval=self._settings.ws_ping_interval_sec or None,
            ping_timeout=self._settings.ws_timeout_sec if self._settings.ws_ping_interval_sec else None,
        )

        connect_msg = {"msg": "connect", "version": "1", "support": ["1"]}
        await self._ws.send(json.dumps(connect_msg))
        connected = await self._recv_json()
        if connected.get("msg") != "connected":
            raise TnasApiError(
                "TrueNAS connect handshake failed",
                details=connected,
            )

        auth_id = self._next_id()
        auth_msg = {
            "id": auth_id,
            "msg": "method",
            "method": "auth.login_with_api_key",
            "params": [self._settings.api_key],
        }
        await self._ws.send(json.dumps(auth_msg))
        auth_resp = await self._recv_json()
        if auth_resp.get("error"):
            raise TnasApiError(
                "TrueNAS API key authentication failed",
                code="AUTH_FAILED",
                details=auth_resp.get("error"),
            )
        if auth_resp.get("msg") == "result" and auth_resp.get("result") is True:
            self._authenticated = True
            logger.info("Authenticated to TrueNAS WebSocket API")
            return
        if auth_resp.get("result") is True:
            self._authenticated = True
            logger.info("Authenticated to TrueNAS WebSocket API")
            return
        raise TnasApiError("Unexpected auth response", details=auth_resp)

    async def _ensure_connected(self) -> None:
        if self._ws is not None and self._authenticated:
            return
        await self._connect_and_auth()

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        """Invoke a TrueNAS middleware method and return the result payload."""
        async with self._lock:
            try:
                await self._ensure_connected()
            except Exception as exc:
                await self.aclose()
                raise classify_connect_error(exc, self._settings) from exc
            assert self._ws is not None
            req_id = self._next_id()
            payload = {
                "id": req_id,
                "msg": "method",
                "method": method,
                "params": params if params is not None else [],
            }
            try:
                await self._ws.send(json.dumps(payload))
                response = await self._recv_matching(req_id)
            except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as exc:
                await self.aclose()
                raise TnasApiError(
                    f"WebSocket call failed for {method}: {exc}",
                    code="CONNECTION_ERROR",
                    method=method,
                ) from exc

            if response.get("error"):
                raise TnasApiError(
                    f"TrueNAS API error for {method}",
                    method=method,
                    details=response.get("error"),
                )

            if response.get("msg") == "result" or "result" in response:
                return response.get("result")

            raise TnasApiError(
                f"Unexpected response for {method}",
                method=method,
                details=response,
            )

    async def aclose(self) -> None:
        """Close the WebSocket connection and reset session state."""
        self._authenticated = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
