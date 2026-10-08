"""SSH transport: fixed argv, pinned host key, bounded JSON on stdin (never a shell string)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Protocol

from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.constants import MAX_AGENT_REQUEST_BYTES, MAX_AGENT_RESPONSE_BYTES
from openwrt_mcp.errors import RouterError

logger = logging.getLogger("openwrt_mcp.transport")


class RouterTransport(Protocol):
    """Anything that can send one agent request and return the parsed response."""

    async def call(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """Send ``payload`` to the router agent."""


def ssh_base_argv(
    *,
    key_path: Path,
    known_hosts_path: Path,
    user: str,
    host: str,
    port: int,
    connect_timeout: int,
) -> list[str]:
    """Build the fixed ssh argv (strict host-key checking, key only, no multiplexing)."""
    return [
        "ssh",
        "-i",
        str(key_path),
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts_path}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ForwardAgent=no",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        f"{user}@{host}",
    ]


async def run_subprocess(
    argv: list[str], stdin: bytes | None, timeout: float, max_out: int = MAX_AGENT_RESPONSE_BYTES
) -> tuple[int, bytes]:
    """Run ``argv`` (no shell) with a timeout and output cap; return ``(returncode, stdout)``."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise RouterError(f"cannot start {argv[0]}: {exc.__class__.__name__}") from exc
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RouterError("router call timed out") from exc
    if len(out) > max_out:
        raise RouterError("router response exceeded size limit")
    return proc.returncode or 0, out


class SshTransport:
    """Real SSH transport to the router agent."""

    def __init__(self, settings: OpenwrtSettings) -> None:
        self._s = settings

    def argv(self) -> list[str]:
        """Return the ssh argv (the forced command on the router ignores any remote command)."""
        return ssh_base_argv(
            key_path=self._s.ssh_key_path,
            known_hosts_path=self._s.known_hosts_path,
            user=self._s.ssh_user,
            host=self._s.host,
            port=self._s.ssh_port,
            connect_timeout=int(min(self._s.ssh_timeout_sec, 30)),
        )

    async def call(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """Send one JSON request; return the parsed JSON response."""
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_AGENT_REQUEST_BYTES:
            raise RouterError("request exceeds agent size limit", retryable=False)
        rc, out = await run_subprocess(self.argv(), body, timeout or self._s.ssh_timeout_sec)
        text = out.decode("utf-8", errors="replace").strip()
        if not text:
            raise RouterError(f"empty response from router agent (ssh exit {rc})")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:  # tolerate stray leading output; the agent's response is the last JSON line
                data = json.loads(text.splitlines()[-1])
            except (json.JSONDecodeError, IndexError) as exc:
                raise RouterError("router agent returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise RouterError("router agent returned non-object JSON")
        return data
