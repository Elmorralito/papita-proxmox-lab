"""SQLite store for plans, one-time grants and per-router locks."""

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from openwrt_mcp.errors import InvalidInput, NotFound, TargetLocked

ACTIVE_STATES = ("applying", "pending_confirmation", "unknown")
TERMINAL_STATES = ("confirmed", "rolled_back", "failed", "expired", "needs_manual")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
  plan_id TEXT PRIMARY KEY,
  router_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  digest TEXT NOT NULL,
  state_precondition TEXT NOT NULL,
  policy_revision INTEGER NOT NULL,
  operations TEXT NOT NULL,
  recovery TEXT NOT NULL,
  diff TEXT NOT NULL,
  risk TEXT NOT NULL,
  requester TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  new_revision TEXT,
  verify_deadline INTEGER,
  detail TEXT,
  UNIQUE (router_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS grants (
  nonce TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  signature TEXT NOT NULL,
  approver TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  consumed_at INTEGER
);
CREATE TABLE IF NOT EXISTS locks (
  router_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL,
  acquired_at INTEGER NOT NULL
);
"""

_JSON_COLUMNS = ("operations", "recovery", "diff")


class Store:
    """Thread-safe SQLite wrapper (single writer; fine for one local MCP process)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        try:
            path.chmod(0o600)
        except OSError:
            pass

    # --- plans -------------------------------------------------------------------------------

    def _row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        """Convert a sqlite row to a dict."""
        if row is None:
            return None
        data = dict(row)
        for col in _JSON_COLUMNS:
            data[col] = json.loads(data[col])
        return data

    def create_plan(
        self, *, draft: Any, idempotency_key: str, requester: str, now: int | None = None
    ) -> dict[str, Any]:
        """Persist a plan; idempotent per ``(router_id, idempotency_key)``."""
        now = now or int(time.time())
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM plans WHERE router_id=? AND idempotency_key=?", (draft.router_id, idempotency_key)
            ).fetchone()
            if row is not None:
                existing = self._row(row)
                assert existing is not None
                if existing["digest"] != draft.digest:
                    raise InvalidInput("idempotency_key already used for a different plan")
                return existing
            plan_id = "plan_" + secrets.token_hex(4)
            self._db.execute(
                "INSERT INTO plans (plan_id, router_id, idempotency_key, digest, state_precondition, policy_revision,"
                " operations, recovery, diff, risk, requester, status, created_at, expires_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_id,
                    draft.router_id,
                    idempotency_key,
                    draft.digest,
                    draft.state_precondition,
                    draft.policy_revision,
                    json.dumps(draft.operations),
                    json.dumps(draft.recovery),
                    json.dumps(draft.diff),
                    draft.risk,
                    requester,
                    "planned",
                    now,
                    draft.expires_at,
                    now,
                ),
            )
        plan = self.get_plan(plan_id)
        assert plan is not None
        return plan

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        """Return a plan or ``None``."""
        with self._lock:
            return self._row(self._db.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone())

    def require_plan(self, plan_id: str) -> dict[str, Any]:
        """Return a plan or raise ``NotFound``."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise NotFound("unknown plan_id")
        return plan

    def list_plans(self, status: str | None = None) -> list[dict[str, Any]]:
        """List plans (newest first), optionally by status."""
        with self._lock:
            if status:
                rows = self._db.execute(
                    "SELECT * FROM plans WHERE status=? ORDER BY created_at DESC", (status,)
                ).fetchall()
            else:
                rows = self._db.execute("SELECT * FROM plans ORDER BY created_at DESC").fetchall()
        return [p for p in (self._row(r) for r in rows) if p is not None]

    def update_plan(self, plan_id: str, **fields: Any) -> None:
        """Update allowed plan columns."""
        allowed = {"status", "new_revision", "verify_deadline", "detail"}
        if not set(fields) <= allowed:
            raise ValueError("unsupported plan column")
        fields["updated_at"] = int(time.time())
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE plans SET {sets} WHERE plan_id=?", (*fields.values(), plan_id))  # nosec B608

    # --- grants ------------------------------------------------------------------------------

    def add_grant(
        self, *, plan_id: str, nonce: str, payload: str, signature: str, approver: str, expires_at: int
    ) -> None:
        """Store a signed one-time grant."""
        with self._lock:
            self._db.execute(
                "INSERT INTO grants (nonce, plan_id, payload, signature, approver, expires_at, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (nonce, plan_id, payload, signature, approver, expires_at, int(time.time())),
            )

    def get_valid_grant(self, plan_id: str, now: int | None = None) -> dict[str, Any] | None:
        """Return the newest unconsumed, unexpired grant for ``plan_id``."""
        now = now or int(time.time())
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM grants WHERE plan_id=? AND consumed_at IS NULL AND expires_at>? "
                "ORDER BY created_at DESC LIMIT 1",
                (plan_id, now),
            ).fetchone()
        return dict(row) if row else None

    def has_expired_grant(self, plan_id: str, now: int | None = None) -> bool:
        """True when an unconsumed grant exists but is expired."""
        now = now or int(time.time())
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM grants WHERE plan_id=? AND consumed_at IS NULL AND expires_at<=?", (plan_id, now)
            ).fetchone()
        return row is not None

    def consume_grant(self, nonce: str) -> bool:
        """Atomically mark a grant consumed; returns False if it was already consumed."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE grants SET consumed_at=? WHERE nonce=? AND consumed_at IS NULL", (int(time.time()), nonce)
            )
            return cur.rowcount == 1

    # --- locks -------------------------------------------------------------------------------

    def acquire_lock(self, router_id: str, plan_id: str) -> None:
        """Take the per-router lock or raise ``TargetLocked``."""
        with self._lock:
            row = self._db.execute("SELECT plan_id FROM locks WHERE router_id=?", (router_id,)).fetchone()
            if row is not None and row["plan_id"] != plan_id:
                raise TargetLocked(f"router {router_id} is locked by {row['plan_id']}")
            self._db.execute(
                "INSERT OR REPLACE INTO locks (router_id, plan_id, acquired_at) VALUES (?,?,?)",
                (router_id, plan_id, int(time.time())),
            )

    def release_lock(self, router_id: str, plan_id: str) -> None:
        """Release the lock if held by ``plan_id``."""
        with self._lock:
            self._db.execute("DELETE FROM locks WHERE router_id=? AND plan_id=?", (router_id, plan_id))

    def lock_holder(self, router_id: str) -> str | None:
        """Return the plan holding the router lock, if any."""
        with self._lock:
            row = self._db.execute("SELECT plan_id FROM locks WHERE router_id=?", (router_id,)).fetchone()
        return row["plan_id"] if row else None
