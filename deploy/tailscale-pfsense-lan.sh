#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
set -euo pipefail

PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
LAN_CIDR="${LAN_CIDR:-172.16.0.0/16}"
LAN_TEST_IP="${LAN_TEST_IP:-172.16.0.101}"
MAIN_PVE_LAN_IP="${MAIN_PVE_LAN_IP:-172.16.0.101}"
MAIN_PVE_TAILSCALE_NAME="${MAIN_PVE_TAILSCALE_NAME:-}"
PFSENSE_NAME="${PFSENSE_NAME:-pfsense-fw001}"
TAILSCALE_TAILNET="${TAILSCALE_TAILNET:-tailf1ad0d.ts.net}"

while [[ "$#" -gt 0 ]]; do
    case "$1" in
    --env-file | -ef)
        ENV_FILE="$2"
        shift 2
        ;;
    *)
        break
        ;;
    esac
done

if [[ -n "${ENV_FILE:-}" ]]; then
    ENV_FILE="$(realpath "${ENV_FILE}")"
    if [[ ! -f "${ENV_FILE}" ]]; then
        echo "[ERROR] Environment file not found: ${ENV_FILE}" >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
fi

# shellcheck source=${PROJECT_PATH}/deploy/utils.sh
{
    cd "${PROJECT_PATH}" && source "${PROJECT_PATH}/deploy/utils.sh"
} || {
    echo "[ERROR] Runtime - cannot load utils path."
    exit 255
}

# shellcheck source=${PROJECT_PATH}/deploy/usage.sh
source "${PROJECT_PATH}/deploy/usage.sh"

require_tailscale_api() {
    if [[ -z "${TAILSCALE_API_KEY:-}" ]]; then
        log ERROR "TAILSCALE_API_KEY is not set. Export it or use --env-file .env, then re-run."
        log INFO "Example: cp .env.example .env  # edit key, then:"
        log INFO "  ./deploy/tailscale-pfsense-lan.sh --env-file .env configure"
        exit 1
    fi
    if [[ -z "${TAILSCALE_TAILNET:-}" ]]; then
        log ERROR "TAILSCALE_TAILNET is not set (e.g. tailf1ad0d.ts.net)."
        exit 1
    fi
    command -v curl >/dev/null 2>&1 || {
        log ERROR "curl is required."
        exit 1
    }
    command -v python3 >/dev/null 2>&1 || {
        log ERROR "python3 is required for ACL merge."
        exit 1
    }
}

ts_api() {
    local method="$1"
    local path="$2"
    local data="${3:-}"
    local tmp
    tmp="$(mktemp)"
    local code
    if [[ -n "$data" ]]; then
        code="$(curl -fsS -o "$tmp" -w '%{http_code}' -X "$method" \
            -u "${TAILSCALE_API_KEY}:" \
            -H 'Content-Type: application/json' \
            --data-binary "$data" \
            "https://api.tailscale.com/api/v2${path}")" || code="000"
    else
        code="$(curl -fsS -o "$tmp" -w '%{http_code}' -X "$method" \
            -u "${TAILSCALE_API_KEY}:" \
            "https://api.tailscale.com/api/v2${path}")" || code="000"
    fi
    if [[ "$code" -lt 200 || "$code" -ge 300 ]]; then
        log ERROR "Tailscale API ${method} ${path} failed (HTTP ${code}): $(cat "$tmp")"
        rm -f "$tmp"
        exit 1
    fi
    cat "$tmp"
    rm -f "$tmp"
}

find_pfsense_device_id() {
    local devices_json device_id
    devices_json="$(ts_api GET "/tailnet/${TAILSCALE_TAILNET}/devices")"
    device_id="$(python3 - <<'PY' "$devices_json" "$PFSENSE_NAME"
import json, sys
data = json.loads(sys.argv[1])
needle = sys.argv[2].lower()
for dev in data.get("devices", []):
    name = (dev.get("name") or "").lower()
    hostname = (dev.get("hostname") or "").lower()
    if needle in name or needle in hostname:
        print(dev.get("id") or dev.get("nodeId") or "")
        break
PY
)"
    if [[ -z "$device_id" ]]; then
        log ERROR "Could not find pfSense device matching name '${PFSENSE_NAME}'."
        exit 1
    fi
    printf '%s' "$device_id"
}

approve_subnet_route() {
    local device_id="$1"
    local routes_json payload status
    routes_json="$(ts_api GET "/device/${device_id}/routes")"
    payload="$(python3 - <<'PY' "$routes_json" "$LAN_CIDR"
import json, sys
data = json.loads(sys.argv[1])
cidr = sys.argv[2]
adv = data.get("advertisedRoutes") or []
en = data.get("enabledRoutes") or []
if cidr not in adv:
    print(json.dumps({"status": "missing_advertise", "advertised": adv}))
else:
    new_en = sorted(set(en) | {cidr})
    print(json.dumps({"status": "ok", "routes": new_en, "advertised": adv}))
PY
)"
    status="$(python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" <<<"$payload")"
    if [[ "$status" == "missing_advertise" ]]; then
        log WARN "pfSense is not advertising ${LAN_CIDR} yet."
        log INFO "On pfSense: VPN → Tailscale → Settings → Routing → Advertised Routes → add ${LAN_CIDR} → Save."
        log INFO "Then re-run: $0 approve-routes"
        return 1
    fi
    payload="$(python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps({'routes': d['routes']}))" <<<"$payload")"
    ts_api POST "/device/${device_id}/routes" "$payload" >/dev/null
    log INFO "Enabled subnet route ${LAN_CIDR} on device ${device_id}."
}

patch_acl_grants() {
    local current merged
    current="$(ts_api GET "/tailnet/${TAILSCALE_TAILNET}/acl")"
    merged="$(python3 - <<'PY' "$current" "$LAN_CIDR" "$MAIN_PVE_LAN_IP" "$MAIN_PVE_TAILSCALE_NAME"
import json, sys

acl = json.loads(sys.argv[1])
lan = sys.argv[2]
main_lan = sys.argv[3]
main_ts = sys.argv[4].strip()
main_ip = f"{main_lan}/32"

tag_owners = acl.setdefault("tagOwners", {})
for tag in (
    "tag:auth-client",
    "tag:pfsense-oldtimers-client",
    "tag:pfsense-lan-router",
    "tag:private-node",
    "tag:pve-oldtimers-cluster",
    "tag:server-node",
):
    tag_owners.setdefault(tag, ["autogroup:admin"])

new_grants = [
    {"src": ["tag:auth-client"], "dst": [lan], "ip": ["*"]},
    {"src": ["tag:pfsense-oldtimers-client"], "dst": [lan], "ip": ["*"]},
    {"src": ["tag:private-node"], "dst": [lan], "ip": ["*"]},
    {"src": ["tag:private-node"], "dst": [main_ip], "ip": ["tcp:8006", "tcp:22"]},
    {"src": ["tag:pve-oldtimers-cluster"], "dst": [lan], "ip": ["*"]},
    {"src": ["tag:server-node"], "dst": [main_ip], "ip": ["tcp:443", "tcp:8006", "tcp:22"]},
    {"src": [lan], "dst": ["tag:pve-oldtimers-cluster"], "ip": ["*"]},
    {"src": [lan], "dst": ["tag:private-node"], "ip": ["*"]},
]
if main_ts:
    new_grants.append(
        {"src": ["tag:private-node"], "dst": [main_ts], "ip": ["tcp:8006", "tcp:22"]}
    )

grants = acl.setdefault("grants", [])

def grant_key(g):
    return (
        tuple(g.get("src", [])),
        tuple(g.get("dst", [])),
        tuple(g.get("ip", [])),
    )

# Replace broad server-node → whole LAN :8006 grant with main-node-only rule.
superseded = {
    (("tag:server-node",), (lan,), ("tcp:443", "tcp:8006", "tcp:22")),
}
grants[:] = [g for g in grants if grant_key(g) not in superseded]

existing = {grant_key(g) for g in grants}
for g in new_grants:
    if grant_key(g) not in existing:
        grants.append(g)

auto = acl.setdefault("autoApprovers", {}).setdefault("routes", {})
for tag in ("tag:pfsense-lan-router",):
    routes = auto.setdefault(tag, [])
    if lan not in routes:
        routes.append(lan)

print(json.dumps(acl))
PY
)"
    ts_api POST "/tailnet/${TAILSCALE_TAILNET}/acl" "$merged" >/dev/null
    log INFO "ACL updated with grants for ${LAN_CIDR} (main PVE admin: ${MAIN_PVE_LAN_IP})."
}

print_pfsense_steps() {
    cat <<EOF
pfSense WebGUI (LAN ${LAN_CIDR}; gateway 172.16.0.1):

1. VPN → Tailscale → Settings → Routing
   - Advertised Routes: ${LAN_CIDR}
   - Accept Subnet Routes: enabled (for site-to-site)
   - Save
   - Approve route in Tailscale admin (or run: $0 approve-routes)

2. Firewall → NAT → Outbound → Hybrid outbound NAT
   - Add: Interface Tailscale, Source ${LAN_CIDR}, Destination any, Translation interface address

3. Firewall → Rules → Tailscale (top → bottom; keep all passes)
   - Pass AUTH_CLIENTS → This firewall  TCP 22,443  (merge old :443/:80/:22; drop 80 if unused)
   - Pass AUTH_CLIENTS → 172.16.0.1/32  TCP 22,443  (pfSense LAN IP — WebGUI, pfREST via subnet route)
   - Pass AUTH_CLIENTS → ${LAN_CIDR}  *  (tailnet → lab LAN — required; do not block)

4. Skip LAN net → 100.64.0.0/10 unless a LAN-only host must reach tailnet via pfSense
   (PVE nodes use their own Tailscale client in this lab)

5. Optional — restrict Proxmox UI to main node (defense in depth; ACLs are primary):
   - Firewall → Aliases → TAILNET_ALLOWED: admin laptop 100.x /32 addresses
   - LAN rules (order matters):
     - Pass: Source TAILNET_ALLOWED → Destination ${MAIN_PVE_LAN_IP}, TCP 8006, 22
     - Block: Source 100.64.0.0/10 → Destination <worker PVE LAN IPs>, TCP 8006

Then run: $0 configure
EOF
}

verify_connectivity() {
    log INFO "Checking local route to ${LAN_TEST_IP}..."
    route -n get "${LAN_TEST_IP}" 2>/dev/null || true
    if command -v tailscale >/dev/null 2>&1; then
        log INFO "tailscale ping ${LAN_TEST_IP} ..."
        if tailscale ping -c 2 "${LAN_TEST_IP}"; then
            log INFO "Tailscale path to ${LAN_TEST_IP} is up."
        else
            log WARN "tailscale ping failed; route or ACL may still be propagating."
        fi
    fi
    if ping -c 2 -W 3 "${LAN_TEST_IP}" >/dev/null 2>&1; then
        log INFO "ICMP to ${LAN_TEST_IP} succeeded."
    else
        log WARN "ICMP to ${LAN_TEST_IP} failed (host firewall may block ping)."
    fi
    if command -v curl >/dev/null 2>&1; then
        log INFO "Proxmox UI probe https://${LAN_TEST_IP}:8006 (main node) ..."
        if curl -fsSk --connect-timeout 5 "https://${LAN_TEST_IP}:8006/" >/dev/null 2>&1; then
            log INFO "HTTPS :8006 on ${LAN_TEST_IP} responded (admin path via pfSense route)."
        else
            log WARN "HTTPS :8006 on ${LAN_TEST_IP} did not respond (node down, firewall, or ACL)."
        fi
    fi
    if [[ -n "${MAIN_PVE_TAILSCALE_NAME:-}" ]] && command -v curl >/dev/null 2>&1; then
        log INFO "Proxmox UI probe https://${MAIN_PVE_TAILSCALE_NAME}:8006 (MagicDNS) ..."
        if curl -fsSk --connect-timeout 5 "https://${MAIN_PVE_TAILSCALE_NAME}:8006/" >/dev/null 2>&1; then
            log INFO "HTTPS :8006 on ${MAIN_PVE_TAILSCALE_NAME} responded (direct tailnet path)."
        else
            log WARN "HTTPS :8006 on ${MAIN_PVE_TAILSCALE_NAME} did not respond."
        fi
    fi
}

action_configure() {
    require_tailscale_api
    local device_id
    device_id="$(find_pfsense_device_id)"
    log INFO "pfSense device id: ${device_id}"
    approve_subnet_route "$device_id"
    patch_acl_grants
    log INFO "Waiting 5s for route propagation..."
    sleep 5
    verify_connectivity
}

action_approve_routes() {
    require_tailscale_api
    approve_subnet_route "$(find_pfsense_device_id)"
}

action_patch_acl() {
    require_tailscale_api
    patch_acl_grants
}

ACTION="${1:-}"
shift || true

case "$ACTION" in
    configure)
        action_configure
        ;;
    approve-routes)
        action_approve_routes
        ;;
    patch-acl)
        action_patch_acl
        ;;
    verify)
        verify_connectivity
        ;;
    pfsense-steps)
        print_pfsense_steps
        ;;
    -h | --help | help | "")
        usage_tailscale_pfsense_lan 0
        ;;
    *)
        log ERROR "Unknown action: ${ACTION}"
        usage_tailscale_pfsense_lan
        ;;
esac
