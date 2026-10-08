"""Process-wide application context."""

from dataclasses import dataclass

from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.router.agent_client import AgentClient
from openwrt_mcp.router.transport import RouterTransport, SshTransport
from openwrt_mcp.store.audit import AuditLog
from openwrt_mcp.store.db import Store


@dataclass
class AppContext:
    """Settings plus long-lived collaborators."""

    settings: OpenwrtSettings
    transport: RouterTransport
    agent: AgentClient
    store: Store
    audit: AuditLog


_ctx: AppContext | None = None


def build_context(settings: OpenwrtSettings, transport: RouterTransport | None = None) -> AppContext:
    """Build a context (``transport`` override is for tests)."""
    transport = transport or SshTransport(settings)
    return AppContext(
        settings=settings,
        transport=transport,
        agent=AgentClient(transport),
        store=Store(settings.db_path),
        audit=AuditLog(settings.audit_path),
    )


def init_context(settings: OpenwrtSettings, transport: RouterTransport | None = None) -> AppContext:
    """Initialise the global context."""
    global _ctx
    _ctx = build_context(settings, transport)
    return _ctx


def get_context() -> AppContext:
    """Return the global context or raise."""
    if _ctx is None:
        raise RuntimeError("context not initialised")
    return _ctx
