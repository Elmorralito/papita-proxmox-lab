"""Append-only, hash-chained audit log. Failures are logged, never raised (must not block recovery)."""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("openwrt_mcp.audit")
_GENESIS = "0" * 64


class AuditLog:
    """JSONL audit file where each record carries the hash of the previous record."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._last = self._read_last_hash()

    def _read_last_hash(self) -> str:
        """Return the hash of the last audit record."""
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            return json.loads(lines[-1])["hash"] if lines else _GENESIS
        except (OSError, ValueError, KeyError, IndexError):
            return _GENESIS

    @staticmethod
    def _digest(prev: str, body: dict[str, Any]) -> str:
        """Chain ``body`` onto the previous record hash."""
        return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()

    def record(self, event: str, **fields: Any) -> None:
        """Append an event; swallow I/O errors."""
        body = {"ts": int(time.time()), "event": event, **fields}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            rec = {**body, "prev": self._last, "hash": self._digest(self._last, body)}
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
            self._last = rec["hash"]
        except OSError as exc:
            logger.error("audit write failed (continuing): %s", exc.__class__.__name__)

    def verify(self) -> bool:
        """Verify the full hash chain."""
        prev = _GENESIS
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                body = {k: v for k, v in rec.items() if k not in ("prev", "hash")}
                if rec["prev"] != prev or rec["hash"] != self._digest(prev, body):
                    return False
                prev = rec["hash"]
        except FileNotFoundError:
            return True
        except (OSError, ValueError, KeyError):
            return False
        return True
