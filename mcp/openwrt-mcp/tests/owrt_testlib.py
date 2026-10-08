"""Test helpers (uniquely named so root-level pytest runs across MCP packages do not collide)."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


class FakeTransport:
    """Scripted router: ``handlers[op]`` is a dict, an exception, or a callable(payload)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.handlers: dict[str, Any] = {"inspect": load_fixture("inspect_ok.json")}

    async def call(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        self.calls.append(payload)
        handler = self.handlers[payload["op"]]
        if callable(handler):
            handler = handler(payload)
        if isinstance(handler, Exception):
            raise handler
        return handler

    def ops(self) -> list[str]:
        """Operations called so far."""
        return [c["op"] for c in self.calls]
