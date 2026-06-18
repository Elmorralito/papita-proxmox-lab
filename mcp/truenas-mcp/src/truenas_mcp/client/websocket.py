"""TrueNAS WebSocket JSON-RPC client."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.config import TnasSettings

logger = logging.getLogger("truenas_mcp.client.websocket")


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
            await self._ensure_connected()
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
