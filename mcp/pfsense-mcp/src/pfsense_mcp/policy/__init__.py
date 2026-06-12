"""Lab policy evaluation across pfREST domains."""

from pfsense_mcp.policy.api_endpoints import REQUIRED_READ_ENDPOINTS, evaluate_api_endpoints_policy
from pfsense_mcp.policy.registry import policy_smoke_checks, verify_all_policies
from pfsense_mcp.policy.restapi_access import evaluate_restapi_access_policy
from pfsense_mcp.policy.types import PolicyReport, PolicySuiteReport

__all__ = [
    "PolicyReport",
    "PolicySuiteReport",
    "REQUIRED_READ_ENDPOINTS",
    "evaluate_api_endpoints_policy",
    "evaluate_restapi_access_policy",
    "policy_smoke_checks",
    "verify_all_policies",
]
