#!/usr/bin/env bash
# Grafana on the dedicated QDevice host (raspi-qdevice-oldtimers), outside the PVE cluster.
# Dashboards only: Prometheus stays on k8s-monitor CT 231; Scrutiny stays on TrueNAS (Infinity REST).
# corosync-qnetd keeps priority: Grafana is niced, CPU-capped, the preferred OOM victim,
# and logs to journald only (no extra SD-card log writes).
# Run as root on the QDevice host after papita-qdevice-host-extras.sh. Idempotent.
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
SRC="${SCRIPT_DIR}/qdevice-grafana"
GRAFANA_VERSION="${PAPITA_GRAFANA_VERSION:-}" # empty = latest from apt.grafana.com (pinned versions are apt-mark held)
GRAFANA_UNIT="${PAPITA_GRAFANA_UNIT:-grafana-server}"
GRAFANA_PORT="${PAPITA_GRAFANA_PORT:-3000}"
GRAFANA_ROOT_URL="${PAPITA_GRAFANA_ROOT_URL:-http://172.16.0.99:${GRAFANA_PORT}}"
PROMETHEUS_URL="${PAPITA_PROMETHEUS_URL:-http://172.16.20.11:9090}"
SCRUTINY_URL="${PAPITA_SCRUTINY_URL:-http://172.16.0.100:31054}"
INFINITY_PLUGIN="yesoreyeram-infinity-datasource"
ENV_FILE=/etc/grafana/papita.env
PROV_DIR=/etc/grafana/provisioning
PLUGINS_DIR=/var/lib/grafana/plugins
GRAFANA_DB=/var/lib/grafana/grafana.db

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[ERROR] Run as root on the QDevice host." >&2
    exit 1
fi
if command -v pvecm >/dev/null 2>&1; then
    echo "[ERROR] Do not run on a Proxmox VE node." >&2
    exit 1
fi
if [[ ! -d "$SRC" ]]; then
    echo "[ERROR] missing ${SRC}" >&2
    exit 1
fi

arch="$(dpkg --print-architecture)"
case "$arch" in
    arm64 | armhf | amd64) ;;
    *)
        echo "[ERROR] Unsupported dpkg architecture '${arch}' (apt.grafana.com ships arm64/armhf/amd64)." >&2
        exit 1
        ;;
esac
echo "[INFO] Architecture: ${arch}"

if ! systemctl is-active --quiet corosync-qnetd; then
    echo "[WARN] corosync-qnetd is not active; this host's primary role is the cluster QDevice."
fi

if ss -Htln "sport = :${GRAFANA_PORT}" | grep -q . && ! systemctl is-active --quiet "$GRAFANA_UNIT"; then
    echo "[ERROR] :${GRAFANA_PORT} is already in use by another service:" >&2
    ss -Htlnp "sport = :${GRAFANA_PORT}" >&2
    exit 1
fi

# The admin password is only applied when Grafana creates its DB, so require it before the first start.
mkdir -p /etc/grafana
if [[ ! -f "$ENV_FILE" ]]; then
    install -m 0600 "${SRC}/papita-grafana.env.example" "$ENV_FILE"
    echo "[INFO] Wrote ${ENV_FILE} from example."
fi
chmod 600 "$ENV_FILE"
if [[ ! -f "$GRAFANA_DB" ]] && ! grep -Eq '^GF_SECURITY_ADMIN_PASSWORD=.+' "$ENV_FILE"; then
    echo "[ERROR] Set GF_SECURITY_ADMIN_PASSWORD in ${ENV_FILE} (root-only, not in git), then re-run." >&2
    exit 1
fi

if grep -qw 'cgroup_disable=memory' /proc/cmdline || ! grep -qw memory /sys/fs/cgroup/cgroup.controllers 2>/dev/null; then
    echo "[WARN] Memory cgroup controller is disabled: Grafana MemoryHigh/MemoryMax will NOT be enforced."
    echo "[WARN] Nice/CPUQuota/OOMScoreAdjust still apply. To enforce memory limits, add"
    echo "[WARN] 'cgroup_enable=memory cgroup_memory=1' to /boot/firmware/cmdline.txt (single line) and reboot"
    echo "[WARN] while all PVE nodes are healthy (check 'pvecm status' first: the reboot drops the QDevice vote)."
fi

echo "[INFO] Configuring apt.grafana.com..."
export DEBIAN_FRONTEND=noninteractive
mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.grafana.com/gpg-full.key -o /etc/apt/keyrings/grafana.asc
chmod 644 /etc/apt/keyrings/grafana.asc
echo "deb [signed-by=/etc/apt/keyrings/grafana.asc] https://apt.grafana.com stable main" \
    >/etc/apt/sources.list.d/grafana.list
apt-get update -qq

if [[ -n "$GRAFANA_VERSION" ]]; then
    apt-mark unhold grafana >/dev/null 2>&1 || true
    apt-get install -y --allow-downgrades "grafana=${GRAFANA_VERSION}"
    apt-mark hold grafana
else
    apt-get install -y grafana
fi

if ! systemctl cat "${GRAFANA_UNIT}.service" >/dev/null 2>&1; then
    echo "[ERROR] systemd unit ${GRAFANA_UNIT}.service not found after install; set PAPITA_GRAFANA_UNIT." >&2
    exit 1
fi

echo "[INFO] Writing ${GRAFANA_UNIT} drop-in (settings + resource guardrails)..."
mkdir -p "/etc/systemd/system/${GRAFANA_UNIT}.service.d"
cat >"/etc/systemd/system/${GRAFANA_UNIT}.service.d/papita.conf" <<EOF
# Managed by papita-qdevice-grafana.sh. corosync-qnetd must always win contention.
[Service]
EnvironmentFile=-${ENV_FILE}
Environment=GF_SERVER_HTTP_PORT=${GRAFANA_PORT}
Environment=GF_SERVER_ROOT_URL=${GRAFANA_ROOT_URL}
Environment=GF_USERS_ALLOW_SIGN_UP=false
Environment=GF_AUTH_ANONYMOUS_ENABLED=false
Environment=GF_ANALYTICS_REPORTING_ENABLED=false
Environment=GF_ANALYTICS_CHECK_FOR_UPDATES=false
Environment=GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES=false
Environment=GF_DATABASE_WAL=true
Environment=GF_LOG_MODE=console
Environment=GF_LOG_LEVEL=warn
Nice=10
CPUWeight=50
CPUQuota=150%
IOSchedulingClass=idle
OOMScoreAdjust=500
MemoryHigh=600M
MemoryMax=800M
EOF

if systemctl cat corosync-qnetd.service >/dev/null 2>&1; then
    echo "[INFO] Raising corosync-qnetd priority (persistent drop-in + live, no restart)..."
    mkdir -p /etc/systemd/system/corosync-qnetd.service.d
    cat >/etc/systemd/system/corosync-qnetd.service.d/papita-priority.conf <<'EOF'
# Managed by papita-qdevice-grafana.sh. Keep the quorum vote alive under contention.
[Service]
Nice=-5
CPUWeight=1000
OOMScoreAdjust=-900
EOF
    systemctl daemon-reload
    systemctl set-property --runtime corosync-qnetd.service CPUWeight=1000
    qnetd_pid="$(systemctl show -p MainPID --value corosync-qnetd)"
    if [[ -n "$qnetd_pid" && "$qnetd_pid" != "0" ]]; then
        echo -900 >"/proc/${qnetd_pid}/oom_score_adj"
        renice -n -5 -p "$qnetd_pid" >/dev/null
    fi
fi

if [[ ! -d "${PLUGINS_DIR}/${INFINITY_PLUGIN}" ]]; then
    echo "[INFO] Installing ${INFINITY_PLUGIN} (Scrutiny REST datasource)..."
    if command -v grafana >/dev/null 2>&1; then
        grafana cli --pluginsDir "$PLUGINS_DIR" plugins install "$INFINITY_PLUGIN"
    else
        grafana-cli --pluginsDir "$PLUGINS_DIR" plugins install "$INFINITY_PLUGIN"
    fi
    chown -R grafana:grafana "$PLUGINS_DIR"
fi

echo "[INFO] Provisioning datasources and Papita dashboards..."
install -d -m 0755 "${PROV_DIR}/datasources" "${PROV_DIR}/dashboards/json"
sed \
    -e "s#http://172.16.20.11:9090#${PROMETHEUS_URL}#g" \
    -e "s#http://172.16.0.100:31054#${SCRUTINY_URL}#g" \
    "${SRC}/provisioning/datasources/papita.yml" >"${PROV_DIR}/datasources/papita.yml"
chmod 644 "${PROV_DIR}/datasources/papita.yml"
install -m 0644 "${SRC}/provisioning/dashboards/provider.yml" "${PROV_DIR}/dashboards/provider.yml"
install -m 0644 "${SRC}"/provisioning/dashboards/json/*.json "${PROV_DIR}/dashboards/json/"

systemctl daemon-reload
systemctl enable "$GRAFANA_UNIT"
systemctl restart "$GRAFANA_UNIT"

echo "[INFO] Waiting for Grafana health..."
for _ in $(seq 1 30); do
    if curl -fsS -m 2 "http://127.0.0.1:${GRAFANA_PORT}/api/health" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
if ! curl -fsS -m 2 "http://127.0.0.1:${GRAFANA_PORT}/api/health"; then
    echo "[ERROR] Grafana not healthy; see: journalctl -u ${GRAFANA_UNIT} -n 50" >&2
    exit 1
fi
echo

curl -fsS -m 5 -o /dev/null "${PROMETHEUS_URL}/-/ready" \
    && echo "[INFO] Prometheus reachable: ${PROMETHEUS_URL}" \
    || echo "[WARN] Prometheus unreachable from this host: ${PROMETHEUS_URL} (CT 231 up? 231.fw allows LAN :9090)"
curl -fsS -m 5 -o /dev/null "${SCRUTINY_URL}/api/summary" \
    && echo "[INFO] Scrutiny reachable: ${SCRUTINY_URL}" \
    || echo "[WARN] Scrutiny unreachable from this host: ${SCRUTINY_URL} (TrueNAS app running? WebUI port published?)"

systemctl is-active --quiet corosync-qnetd && echo "[INFO] corosync-qnetd: active"
echo "[INFO] Grafana: ${GRAFANA_ROOT_URL}  (Tailscale: http://raspi-qdevice-oldtimers:${GRAFANA_PORT})"
echo "[INFO] Resource usage: systemctl status ${GRAFANA_UNIT} --no-pager | grep -E 'Memory|CPU'"
