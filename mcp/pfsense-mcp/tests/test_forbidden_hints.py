"""Tests for pfREST forbidden error hints."""

from pfsense_mcp.client.forbidden_hints import forbidden_hint


def test_interface_not_allowed_hint() -> None:
    hint = forbidden_hint(
        status_code=403,
        message="The requested action is not allowed by admin policy",
        response_id="ENDPOINT_INTERFACE_NOT_ALLOWED",
        endpoint="/system/version",
        host="100.89.204.62",
    )
    assert hint is not None
    assert "deselect all" in hint.lower() or "Allowed Interfaces" in hint
    assert "100.89.204.62" in hint


def test_acl_denied_hint() -> None:
    hint = forbidden_hint(
        status_code=403,
        message="The requested action is not allowed by admin policy",
        response_id="ENDPOINT_CLIENT_NOT_ALLOWED_BY_ACL",
        endpoint="/system/version",
        host="100.89.204.62",
    )
    assert hint is not None
    assert "Access Lists" in hint


def test_unauthorized_hint_uses_api_user() -> None:
    hint = forbidden_hint(
        status_code=401,
        message="Authentication failed",
        response_id=None,
        endpoint="/system/version",
        host="172.16.0.1",
        api_user="my-bot",
    )
    assert hint is not None
    assert "my-bot" in hint
