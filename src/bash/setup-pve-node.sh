#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
# Remote (proxmox.sh): utils.sh lives next to this script. Local repo: deploy/utils.sh.
if [[ -f "${SCRIPT_DIR}/utils.sh" ]]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/utils.sh"
elif [[ -f "${REPO_ROOT}/deploy/utils.sh" ]]; then
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/deploy/utils.sh"
else
    echo "[ERROR] Cannot find utils.sh (tried ${SCRIPT_DIR}/utils.sh and ${REPO_ROOT}/deploy/utils.sh)." >&2
    exit 255
fi

if [[ -f "${SCRIPT_DIR}/usage.sh" ]]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/usage.sh"
elif [[ -f "${REPO_ROOT}/deploy/usage.sh" ]]; then
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/deploy/usage.sh"
else
    echo "[ERROR] Cannot find usage.sh (tried ${SCRIPT_DIR}/usage.sh and ${REPO_ROOT}/deploy/usage.sh)." >&2
    exit 255
fi

APT_DEPENDENCIES_LIST="${SCRIPT_DIR}/apt-dependencies.list"

# Python bundle: proxmox.sh copies src/python/ → <deploy>/python/ (misc/cluster + datafiles).
_resolve_python_root() {
    local candidate=""
    for candidate in \
        "${SCRIPT_DIR}/python" \
        "${SCRIPT_DIR}/../python" \
        "${REPO_ROOT}/src/python"; do
        if [[ -d "${candidate}/misc/cluster" && -d "${candidate}/datafiles" ]]; then
            cd "${candidate}" && pwd
            return 0
        fi
    done
    printf '%s\n' "${SCRIPT_DIR}/python"
    return 1
}

PYTHON_ROOT="$(_resolve_python_root)" || PYTHON_ROOT="${SCRIPT_DIR}/python"
CLUSTER_HOSTS_LIST="${PYTHON_ROOT}/datafiles/default.hosts.list"
CLUSTER_HOSTS_REGEX_FILE="${PYTHON_ROOT}/datafiles/default.hosts.regex"
CLUSTER_ZONE_SUFFIXES_FILE="${PYTHON_ROOT}/datafiles/default.domain.suffixes.list"
DISCOVER_HOSTS_PY="${PYTHON_ROOT}/misc/cluster/discover_hosts.py"
PAPITA_HOSTS_BLOCK_BEGIN="# BEGIN papita-pve-cluster-hosts"
PAPITA_HOSTS_BLOCK_END="# END papita-pve-cluster-hosts"
PVE_SETUP_LAST_STEP=17
START_FROM_STEP=0
DEFAULT_CRONTAB_SCHEDULE="0 4 * * 6"
# Tailscale Proxmox cert renewal cron (step 17.2); five fields only — user/command appended by script.
DEFAULT_TAILSCALE_PVE_CERT_CRON_SCHEDULE="0 */12 * * *"
DEFAULT_NTP_SERVERS="pool.ntp.org"
DEFAULT_SMART_CRON_SCHEDULE="0 3 1 * *"
DEFAULT_VZDUMP_CRON_SCHEDULE="0 2 * * 0"
DEFAULT_STOPALL_TIMEOUT="120"
DEFAULT_QUORUM_WAIT_SEC="120"
TAILSCALE_GATEWAYS_LIST="${SCRIPT_DIR}/misc/tailscale/default.gateways.list"
TAILSCALE_LAN_ROUTES_LIST="${SCRIPT_DIR}/misc/tailscale/default.lan.routes.list"
TAILSCALE_TAGS_LIST="${SCRIPT_DIR}/misc/tailscale/default.tags.list"

_default_subnet_routes() {
    list_file_csv "$TAILSCALE_GATEWAYS_LIST" 2>/dev/null || true
}

_default_lan_subnet_routes() {
    list_file_csv "$TAILSCALE_LAN_ROUTES_LIST" 2>/dev/null || true
}

_default_tags() {
    local tags=""
    tags="$(list_file_csv "$TAILSCALE_TAGS_LIST" 2>/dev/null || true)"
    if [[ -n "$tags" ]]; then
        printf '"%s"' "$tags"
    fi
}

# Returns 0 when START_FROM_STEP is past step_num (caller should return 0).
_skip_pve_step() {
    local step_num=$1
    local step_label=$2
    if (( START_FROM_STEP > step_num )); then
        log INFO "Skipping ${step_label}..."
        return 0
    fi
    return 1
}

# -----------------------------------------------------------------------------
# Confirmation: exit script if user declines
# -----------------------------------------------------------------------------
confirm_pve_setup() {

    cat <<EOF
## QUESTION: Are you sure you want to setup PVE? (y/n), a number to skip to a specific step, or usage keys below:
1. Setup APT configuration
2. Setup Hibernate
3. Setup Wake-on-LAN
4. Setup Locales
5. Setup lm-sensors (temperature monitoring)
6. Setup time sync (NTP)
7. Configure cluster /etc/hosts (DNS discovery, pre-cluster)
8. Setup Tailscale
9. Initialize Tailscale
10. Setup Post-startup procedure
11. Setup Pre-shutdown procedure
12. Configure email notifications
13. Setup SMART disk health monitoring
14. Enable Proxmox cluster firewall
15. Remove PVE subscription alert
16. Configure periodic backup job (vzdump)
17. Proxmox Web UI: Tailscale-issued TLS certificate (HTTPS 8006)

  Usage: at the "Input:" prompt, enter h, help, ?, usage, -h, or --help to open the full manual in less (q to quit), then choose again.
EOF
    while true; do
        prompt_pve_start confirm "${PVE_SETUP_LAST_STEP}"
        if [[ "$confirm" == "__USAGE__" ]]; then
            usage_setup_pve_node || log WARN "Usage manual could not be shown (see message above)."
            continue
        fi
        break
    done

    if [ -z "$confirm" ]; then
        log WARN "Invalid input. Starting from the beginning..."
        START_FROM_STEP=1
        return 0
    fi

    if [ "$confirm" == "y" ]; then
        log INFO "Starting setup from the beginning..."
        START_FROM_STEP=1
        return 0
    elif [ "$confirm" == "n" ]; then
        log INFO "Exiting..."
        exit 0
    elif [[ "$confirm" =~ ^[0-9]+$ ]]; then
        log INFO "Skipping to step $confirm..."
        START_FROM_STEP="$confirm"
        return 0
    else
        log WARN "Invalid input. Starting from the beginning..."
        START_FROM_STEP=1
        return 0
    fi
}

_read_default_hosts_regex() {
    if list_file_first_line "$CLUSTER_HOSTS_REGEX_FILE" 2>/dev/null; then
        return 0
    fi
    echo '^pve.*'
}

_validate_python_cluster_bundle() {
    local path missing=0
    for path in \
        "$DISCOVER_HOSTS_PY" \
        "${PYTHON_ROOT}/misc/cluster/domain_pattern.py" \
        "$CLUSTER_HOSTS_LIST" \
        "$CLUSTER_HOSTS_REGEX_FILE"; do
        if [[ ! -f "$path" ]]; then
            log ERROR "Missing required file: ${path}"
            missing=1
        fi
    done
    if [[ ! -f "$CLUSTER_ZONE_SUFFIXES_FILE" ]]; then
        log WARN "Zone suffixes file not found (${CLUSTER_ZONE_SUFFIXES_FILE}); built-in defaults will be used."
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        log ERROR "python3 is required for step 7 host discovery."
        missing=1
    fi
    return "$missing"
}

_papita_merge_hosts_block() {
    local block_file="$1"
    local hosts_path="/etc/hosts"
    local tmp="${hosts_path}.papita.tmp"
    if [[ -f "$hosts_path" ]]; then
        awk -v b="$PAPITA_HOSTS_BLOCK_BEGIN" -v e="$PAPITA_HOSTS_BLOCK_END" '
            $0 == b { skip=1; next }
            $0 == e { skip=0; next }
            !skip { print }
        ' "$hosts_path" >"$tmp"
    else
        : >"$tmp"
    fi
    {
        cat "$tmp"
        echo "$PAPITA_HOSTS_BLOCK_BEGIN"
        cat "$block_file"
        echo "$PAPITA_HOSTS_BLOCK_END"
    } >"${hosts_path}.new"
    mv "${hosts_path}.new" "$hosts_path"
    rm -f "$tmp"
}

_install_cpu_microcode() {
    local pkg=""
    if grep -qiE 'vendor_id[[:space:]]+:[[:space:]]+GenuineIntel' /proc/cpuinfo 2>/dev/null; then
        pkg="intel-microcode"
    elif grep -qiE 'vendor_id[[:space:]]+:[[:space:]]+AuthenticAMD' /proc/cpuinfo 2>/dev/null; then
        pkg="amd64-microcode"
    else
        log WARN "Could not detect Intel/AMD CPU; skipping microcode package."
        return 0
    fi
    log INFO "Installing CPU microcode package: ${pkg}"
    apt-get install -y "$pkg"
    return 0
}

# -----------------------------------------------------------------------------
# APT: sources and upgrades. On failure we exit (do not return to main).
# -----------------------------------------------------------------------------
setup_apt_config() {

    _skip_pve_step 1 "APT configuration" && return 0

    prompt_until_ynet "1. QUESTION: Setup APT configuration? (y/n, e or t to exit setup): " confirm

    if [ "$confirm" != "y" ]; then
        log INFO "Skipping APT configuration..."
        return 0
    fi
    log INFO "Setting up APT repositories..."
    cat <<EOF > /etc/apt/sources.list
deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware
deb http://deb.debian.org/debian bookworm-updates main contrib non-free non-free-firmware
EOF
    if [[ -d /etc/apt/sources.list.d/ ]]; then
        log INFO "/etc/apt/sources.list.d/ directory found."
        log INFO "Changing APT repositories..."
        log INFO "pve-no-subscription repository..."
        cat <<EOF > /etc/apt/sources.list.d/pve-no-subscription.sources
Types: deb
URIs: https://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
        log INFO "pve-no-subscription repository changed."

        log INFO "pve-enterprise repository..."
        cat <<EOF > /etc/apt/sources.list.d/pve-enterprise.sources
Types: deb
URIs: https://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
        log INFO "pve-enterprise repository changed."

        log INFO "ceph repository..."
        cat <<EOF > /etc/apt/sources.list.d/ceph.sources
Types: deb
URIs: https://download.proxmox.com/debian/ceph-squid
Suites: trixie
Components: enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
        log INFO "ceph repository changed."
    fi

    log INFO "Updating and upgrading packages..."
    apt update && apt dist-upgrade -y && apt autoremove -y && apt clean && apt autoclean

    log INFO "Installing dependencies..."
    if [ ! -f "${APT_DEPENDENCIES_LIST}" ]; then
        log ERROR "${APT_DEPENDENCIES_LIST} not found. Exiting..."
        exit 1
    fi
    apt_deps=$(list_file_active_lines "${APT_DEPENDENCIES_LIST}" | tr '\n' ' ')
    log WARN "Installing dependencies: ${apt_deps}"
    log WARN "To modify the dependencies list, edit file: ${APT_DEPENDENCIES_LIST}"
    prompt_until_yn "1.1. QUESTION: Continue to install dependencies? (y/n): " confirm
    if [ "$confirm" != "y" ]; then
        log INFO "Skipping dependencies installation..."
        return 0
    fi
    if ! $SHELL -c "apt install -y ${apt_deps}"; then
        log ERROR "Failed to install dependencies. Exiting..."
        exit 1
    fi
    log INFO "Dependencies installed."
    if ! which unattended-upgrades &>/dev/null || ! which jq &>/dev/null || ! which vim &>/dev/null; then
        log ERROR "There are some dependencies like jq, unattended-upgrades, and vim that are required for the setup. Exiting..."
        exit 1
    fi
    log INFO "Setting up security patches..."
    systemctl enable --now unattended-upgrades

    crontab_schedule=
    prompt_crontab_schedule crontab_schedule "${DEFAULT_CRONTAB_SCHEDULE}"
    log INFO "Upgrade CRONTAB schedule: ${crontab_schedule}"
    log INFO "Setting up upgrade CRONTAB..."
    cron_command="apt-get update && apt-get dist-upgrade -y && apt-get autoremove -y && apt-get clean && apt-get autoclean"
    awk -v cmd="$cron_command" 'index($0, cmd)==0' /etc/crontab > /etc/crontab.tmp && mv /etc/crontab.tmp /etc/crontab
    echo "${crontab_schedule} $cron_command" | tee -a /etc/crontab

    prompt_until_yn "1.3. QUESTION: Install CPU microcode updates (intel-microcode / amd64-microcode)? (y/n): " confirm
    if [ "$confirm" == "y" ]; then
        _install_cpu_microcode || log WARN "Microcode package install failed; continuing."
    fi

    log INFO "APT Configuration and auto-upgrades set up. Done."
}

# -----------------------------------------------------------------------------
# Hibernate: low swappiness (server-ish); disable sleep via sleep.conf + logind (no masked
# sleep targets—masks can stall or confuse shutdown, blocking clean S5 needed for WoL).
# -----------------------------------------------------------------------------
setup_hibernate() {
    _skip_pve_step 2 "Hibernate setup" && return 0

    prompt_until_ynet "2. QUESTION: Set hibernate off? (y/n, e or t to exit setup): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi
    log INFO "Setting hibernate off..."
    cat <<EOF > /etc/sysctl.d/99-hibernate.conf
vm.swappiness = 0
EOF

    log INFO "Disabling suspend/hibernate via systemd sleep.conf (idempotent)..."
    install -d -m 0755 /etc/systemd/sleep.conf.d
    cat <<'EOF' > /etc/systemd/sleep.conf.d/99-papita-no-sleep.conf
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowHybridSleep=no
AllowSuspendThenHibernate=no
EOF

    log INFO "Configuring systemd-logind (drop-in, idempotent)..."
    install -d -m 0755 /etc/systemd/logind.conf.d
    rm -f /etc/systemd/logind.conf.d/99-papita-ignore-lidswitch.conf
    cat <<'EOF' > /etc/systemd/logind.conf.d/99-papita-logind-sleep.conf
[Login]
# Do not suspend on lid/keys; lid closed while headless does not power off the node.
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
# Idle sessions must not try to suspend; power button should reach full poweroff (S5) for WoL.
IdleAction=ignore
HandlePowerKey=poweroff
HandleRebootKey=reboot
EOF

    log INFO "Removing legacy sleep.target masks (if any) so shutdown is not blocked..."
    systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true

    systemctl daemon-reload
    systemctl restart systemd-logind

    log INFO "Hibernate configuration is set up. Done."
    return 0
}

# -----------------------------------------------------------------------------
# Wake-on-LAN: configure interface. On failure return to main.
# -----------------------------------------------------------------------------
setup_wake_on_lan() {

    _skip_pve_step 3 "Wake-on-LAN setup" && return 0

    prompt_until_ynet "3. QUESTION: Setup Wake-on-LAN? (y/n, e or t to exit setup): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi

    interface=
    if ! prompt_existing_wol_interface interface; then
        log ERROR "Wake-on-LAN interface prompt aborted."
        return 1
    fi
    log INFO "Wake-on-LAN is supported on interface $interface."
    log INFO "Setting up Wake-on-LAN for interface $interface..."
    if ! ethtool -s "${interface}" wol pg; then
        log ERROR "Failed to set up Wake-on-LAN for interface $interface."
        return 1
    fi
    cat <<EOF > /etc/systemd/system/wol.service
[Unit]
Description=Wake-on-LAN (${interface})
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -s ${interface} wol pg

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable wol.service
    systemctl start wol.service
    log INFO "Wake-on-LAN is set up for interface $interface."
    mac_addr=
    if [[ -r "/sys/class/net/${interface}/address" ]]; then
        read -r mac_addr < "/sys/class/net/${interface}/address"
    fi
    if [ -z "$mac_addr" ]; then
        log ERROR "Could not determine MAC address for interface $interface."
        return 1
    fi
    log INFO "Enabling Wake-on-LAN for MAC address in cluster config..."
    if ! pvenode config set --wakeonlan "$mac_addr"; then
        log ERROR "Failed to enable Wake-on-LAN for MAC address in cluster config."
        return 1
    fi
    log INFO "Wake-on-LAN for MAC address in cluster config enabled."
    log INFO "Done."
    return 0
}

# -----------------------------------------------------------------------------
# Locales: locale-gen and update-locale. On failure return to main.
# -----------------------------------------------------------------------------
setup_locales() {

    _skip_pve_step 4 "locales setup" && return 0

    prompt_until_ynet "4. QUESTION: Setup locales? (y/n, e or t to exit setup): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi

    prompt_locale_field "4.1. QUESTION: Enter locale: " locale

    if [ -z "$locale" ]; then
        locale="en_US"
    fi

    prompt_locale_field "4.2. QUESTION: Enter charset: " charset

    if [ -z "$charset" ]; then
        charset="UTF-8"
    fi
    log INFO "Setting up locale to: ${locale}.${charset}"
    local full_locale="${locale}.${charset}"
    if [ -f /etc/locale.gen ] && ! grep -qE "^${full_locale}[[:space:]]" /etc/locale.gen; then
        if grep -qE "^#.*${full_locale}" /etc/locale.gen; then
            sed -i "s/^#[[:space:]]*${full_locale}/${full_locale}/" /etc/locale.gen
            log INFO "Enabled ${full_locale} in /etc/locale.gen."
        fi
    fi
    log INFO "Generating locales: ${full_locale}..."
    if ! locale-gen "${full_locale}"; then
        log ERROR "Failed to generate locale."
        return 1
    fi
    log INFO "Updating locale: ${full_locale}..."
    # LANG + LC_CTYPE avoids Perl warnings when SSH sends LC_CTYPE=UTF-8 (invalid on Debian).
    update-locale LANG="${full_locale}" LC_CTYPE="${full_locale}"
    _papita_install_locale_profile_fix "${full_locale}"
    _papita_fix_sshd_accept_env_locales
    log INFO "Locales are set up. Done."
    return 0
}

# macOS/Cursor SSH often sends LC_CTYPE=UTF-8 (invalid on Debian). profile.d runs after bash
# warns; rejecting LC_* in sshd AcceptEnv stops the bad value reaching login shells.
_papita_install_locale_profile_fix() {
    local full_locale="$1"
    local dropin="/etc/profile.d/papita-locale-fix.sh"
    cat <<EOF >"${dropin}"
# Papita: override invalid LC_CTYPE from some SSH clients (e.g. macOS sends UTF-8).
case "\${LC_CTYPE:-}" in
    UTF-8|C.UTF-8|'') export LC_CTYPE=${full_locale} ;;
esac
export LANG="\${LANG:-${full_locale}}"
EOF
    chmod 0644 "${dropin}"
    log INFO "Installed ${dropin} (child shells and tools after login)."
}

_papita_fix_sshd_accept_env_locales() {
    local sshd_config="/etc/ssh/sshd_config"
    if [[ ! -f "${sshd_config}" ]]; then
        return 0
    fi
    if grep -qE '^AcceptEnv[[:space:]]+.*LC_\*' "${sshd_config}"; then
        sed -i -E '/^AcceptEnv[[:space:]]+.*LC_\*/c AcceptEnv LANG LANGUAGE' "${sshd_config}"
        if systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null; then
            log INFO "sshd: AcceptEnv LANG LANGUAGE only (ignores client LC_CTYPE=UTF-8)."
        else
            log WARN "Could not reload sshd; run: systemctl reload ssh"
        fi
    fi
    return 0
}

# -----------------------------------------------------------------------------
# lm-sensors: detect chips and enable monitoring (used by proxmox.sh get-temp).
# -----------------------------------------------------------------------------
setup_lm_sensors() {
    _skip_pve_step 5 "lm-sensors setup" && return 0

    prompt_until_ynet "5. QUESTION: Configure lm-sensors for hardware temperature monitoring? (y/n, e or t to exit setup): " confirm
    if [ "$confirm" != "y" ]; then
        return 0
    fi

    if ! command -v sensors-detect &>/dev/null; then
        log ERROR "sensors-detect not found. Install lm-sensors via step 1."
        return 1
    fi

    log INFO "Running sensors-detect (non-interactive)..."
    sensors-detect --auto >/var/log/papita-sensors-detect.log 2>&1 || log WARN "sensors-detect returned non-zero; see /var/log/papita-sensors-detect.log."

    if systemctl list-unit-files lm-sensors.service &>/dev/null; then
        systemctl enable lm-sensors.service
        systemctl restart lm-sensors.service || systemctl start lm-sensors.service || true
    fi

    if command -v sensors &>/dev/null && sensors &>/dev/null; then
        log INFO "lm-sensors is responding. Sample output:"
        sensors | head -n 20 || true
    else
        log WARN "sensors command did not return data yet; a reboot may be required for some modules."
    fi

    log INFO "lm-sensors setup done."
    return 0
}

# -----------------------------------------------------------------------------
# Time sync: chrony (configurable NTP servers).
# -----------------------------------------------------------------------------
setup_time_sync() {
    _skip_pve_step 6 "time sync setup" && return 0

    prompt_until_ynet "6. QUESTION: Configure time synchronization (chrony)? (y/n, e or t to exit setup): " confirm
    if [ "$confirm" != "y" ]; then
        return 0
    fi

    apt-get install -y chrony

    local ntp_servers=""
    prompt_line_trimmed "6.1. QUESTION: NTP servers (space-separated; empty = ${DEFAULT_NTP_SERVERS}): " ntp_servers
    if [ -z "$ntp_servers" ]; then
        ntp_servers="$DEFAULT_NTP_SERVERS"
    fi

    install -d -m 0755 /etc/chrony/chrony.conf.d
    local conf_drop="/etc/chrony/chrony.conf.d/99-papita-ntp.conf"
    {
        echo "# Papita PVE setup (step 6)"
        for srv in $ntp_servers; do
            echo "pool ${srv} iburst"
        done
        echo "makestep 1.0 3"
        echo "rtcsync"
    } >"$conf_drop"

    systemctl enable chrony.service
    systemctl restart chrony.service
    if command -v chronyc &>/dev/null; then
        log INFO "chrony tracking:"
        chronyc tracking 2>/dev/null | head -n 8 || true
    fi
    log INFO "Time sync configured (chrony). Servers: ${ntp_servers}"
    return 0
}

# -----------------------------------------------------------------------------
# /etc/hosts: discover cluster peers via DNS before joining a Proxmox cluster.
# -----------------------------------------------------------------------------
setup_cluster_hosts() {
    _skip_pve_step 7 "cluster /etc/hosts setup" && return 0

    prompt_until_ynet "7. QUESTION: Configure /etc/hosts for cluster peers (DNS discovery)? (y/n, e or t to exit setup): " confirm
    if [ "$confirm" != "y" ]; then
        return 0
    fi

    local domain regex discover_out block_file confirm_merge=""
    domain=""
    prompt_line_trimmed "7.1. QUESTION: Cluster DNS domain suffix (literal e.g. cluster.home.arpa, or keyword oldtimers.* / *.oldtimers.lan): " domain
    if [ -z "$domain" ]; then
        log ERROR "Domain suffix is required for host discovery."
        return 1
    fi

    regex="$(_read_default_hosts_regex)"
    prompt_line_trimmed "7.2. QUESTION: Hostname regex for FQDNs (empty = ${regex}): " regex_input
    if [ -n "${regex_input:-}" ]; then
        regex="$regex_input"
    fi

    if ! _validate_python_cluster_bundle; then
        log ERROR "Python cluster bundle incomplete (expected ${PYTHON_ROOT}/misc/cluster/ and ${PYTHON_ROOT}/datafiles/)."
        return 1
    fi

    block_file="$(mktemp)"
    local -a discover_zone_args=()
    if [[ -f "$CLUSTER_ZONE_SUFFIXES_FILE" ]]; then
        discover_zone_args=(--zone-suffixes-file "$CLUSTER_ZONE_SUFFIXES_FILE")
    fi
    if ! discover_out="$(python3 "$DISCOVER_HOSTS_PY" --domain "$domain" --pattern "$regex" \
        --candidates-file "$CLUSTER_HOSTS_LIST" \
        "${discover_zone_args[@]}" \
        --include-self 2>/var/log/papita-discover-hosts.err)"; then
        log ERROR "Host discovery failed (see /var/log/papita-discover-hosts.err)."
        if [[ -f /var/log/papita-discover-hosts.err ]]; then
            cat /var/log/papita-discover-hosts.err >&2
        fi
        rm -f "$block_file"
        return 1
    fi
    if [ -z "$discover_out" ]; then
        log ERROR "Host discovery returned no entries."
        rm -f "$block_file"
        return 1
    fi

    log INFO "Discovered hosts:"
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        log INFO "  ${line}"
        echo "$line" >>"$block_file"
    done <<<"$discover_out"

    prompt_until_yn "7.3. QUESTION: Merge these entries into /etc/hosts? (y/n): " confirm_merge
    if [ "$confirm_merge" != "y" ]; then
        rm -f "$block_file"
        log INFO "Skipping /etc/hosts merge."
        return 0
    fi

    _papita_merge_hosts_block "$block_file"
    rm -f "$block_file"
    log INFO "Cluster hosts block updated in /etc/hosts."
    return 0
}

# -----------------------------------------------------------------------------
# Tailscale: install and sysctl. On failure return to main.
# -----------------------------------------------------------------------------
setup_tailscale() {

    _skip_pve_step 8 "Tailscale setup" && return 0

    prompt_until_ycnet "8. QUESTION: Setup Tailscale? (y/c/n, e or t to exit setup): " confirm

    if [ "$confirm" != "y" ] && [ "$confirm" != "c" ]; then
        log INFO "Skipping Tailscale setup..."
        return 0
    fi
    if [ "$confirm" == "y" ]; then
        if ! curl -fsSL https://tailscale.com/install.sh | sh; then
            log ERROR "Failed to install Tailscale."
            return 1
        fi
        log INFO "Tailscale installed."
    fi
    log INFO "Continuing with Tailscale setup..."
    install -d -m 0755 /etc/sysctl.d
    cat <<'EOF' > /etc/sysctl.d/99-tailscale.conf
# Papita Proxmox lab: forwarding for Tailscale exit/subnet routes
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
    sysctl -p /etc/sysctl.d/99-tailscale.conf

    prompt_until_yn "8.1. QUESTION: Allow Tailscale (100.64.0.0/10) in Proxmox firewall? (y/n): " confirm

    if [ "$confirm" == "y" ]; then
        setup_proxmox_firewall_tailscale || log WARN "Proxmox firewall rule for Tailscale failed; continuing."
    fi


    prompt_until_yn "8.2. QUESTION: Masquerade firewall due to known issue with Tailscale? (y/n): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi
    log WARN "Masquerading firewall due to known issue with Tailscale (outbound interface vmbr0)..."
    if iptables-save -t nat 2>/dev/null | grep -qF "papita-tailscale-masq-vmbr0"; then
        log INFO "iptables NAT MASQUERADE rule papita-tailscale-masq-vmbr0 already present; skipping insert."
    else
        iptables -t nat -A POSTROUTING -o vmbr0 -m comment --comment "papita-tailscale-masq-vmbr0" -j MASQUERADE
    fi
    apt-get install -y iptables-persistent
    netfilter-persistent save
    log INFO "Restarting tailscaled.service..."
    systemctl restart tailscaled.service
    log INFO "Tailscale is set up. Done."
    return 0
}

# Proxmox firewall: allow incoming traffic from Tailscale (100.64.0.0/10).
setup_proxmox_firewall_tailscale() {
    local tailscale_cidr="100.64.0.0/10"
    local cluster_lan_cidr="172.16.0.0/16"
    local cluster_fw="/etc/pve/firewall/cluster.fw"
    local ts_rule="IN ACCEPT -source ${tailscale_cidr} -log nolog"
    local lan_rule="IN ACCEPT -source ${cluster_lan_cidr} -log nolog"
    local out_rule="OUT ACCEPT -log nolog"

    if [ ! -d "$(dirname "${cluster_fw}")" ]; then
        log WARN "Proxmox firewall directory not found; skipping Tailscale firewall rule."
        return 1
    fi

    # Repair legacy invalid rule from earlier script versions (-log n is not valid PVE syntax).
    if [ -f "${cluster_fw}" ] && grep -qF '-log n' "${cluster_fw}"; then
        sed -i 's/-log n$/-log nolog/g' "${cluster_fw}"
        log INFO "Fixed invalid -log n in ${cluster_fw} (use -log nolog)."
    fi

    if [ -f "${cluster_fw}" ]; then
        if grep -qF "${tailscale_cidr}" "${cluster_fw}"; then
            log INFO "Proxmox firewall already has a rule for ${tailscale_cidr}."
        else
            if ! awk -v rule="${ts_rule}" '/^\[RULES\]$/ { print; print rule; next } 1' "${cluster_fw}" > "${cluster_fw}.tmp" && mv "${cluster_fw}.tmp" "${cluster_fw}"; then
                log ERROR "Failed to add Tailscale rule to ${cluster_fw}."
                return 1
            fi
            log INFO "Added Proxmox firewall rule: accept IN from ${tailscale_cidr}."
        fi
        if ! grep -qF "${cluster_lan_cidr}" "${cluster_fw}"; then
            awk -v rule="${lan_rule}" '/^\[RULES\]$/ { print; print rule; next } 1' "${cluster_fw}" > "${cluster_fw}.tmp" && mv "${cluster_fw}.tmp" "${cluster_fw}"
            log INFO "Added Proxmox firewall rule: accept IN from ${cluster_lan_cidr} (cluster LAN)."
        fi
        if ! grep -qE '^[[:space:]]*OUT ACCEPT' "${cluster_fw}"; then
            awk -v rule="${out_rule}" '/^\[RULES\]$/ { print; print rule; next } 1' "${cluster_fw}" > "${cluster_fw}.tmp" && mv "${cluster_fw}.tmp" "${cluster_fw}"
            log INFO "Added Proxmox firewall rule: OUT ACCEPT (preserves internet/cluster egress)."
        fi
        if ! grep -qE '^[[:space:]]*policy_out:' "${cluster_fw}"; then
            if grep -qE '^\[OPTIONS\]' "${cluster_fw}"; then
                awk '/^\[OPTIONS\]$/ { print; print "policy_out: ACCEPT"; next } 1' "${cluster_fw}" > "${cluster_fw}.tmp" && mv "${cluster_fw}.tmp" "${cluster_fw}"
                log INFO "Set policy_out: ACCEPT in ${cluster_fw}."
            fi
        fi
    else
        cat <<EOF > "${cluster_fw}"
[OPTIONS]
enable: 0
policy_out: ACCEPT

[RULES]
${lan_rule}
${ts_rule}
${out_rule}
EOF
        log INFO "Created ${cluster_fw} with Tailscale + cluster LAN rules (firewall left disabled; set enable: 1 to use)."
    fi
    return 0
}

tailscale_post_init_sanity_check() {
    if ! command -v tailscale &>/dev/null || ! command -v jq &>/dev/null; then
        log WARN "tailscale or jq missing; skipping sanity check."
        return 0
    fi
    log INFO "--- Tailscale sanity check (step 9.4) ---"
    tailscale status 2>/dev/null || log WARN "tailscale status failed."
    local ts_ip ts_dns
    ts_ip="$(tailscale ip -4 2>/dev/null || true)"
    ts_dns="$(tailscale status --json 2>/dev/null | jq -r '.Self.DNSName // empty' || true)"
    log INFO "Tailscale IPv4: ${ts_ip:-<none>}"
    log INFO "MagicDNS name: ${ts_dns:-<none>}"
    log INFO "Advertised routes/tags: approve in https://login.tailscale.com/admin/machines if pending."
    log INFO "Verify SSH: tailscale ssh ${ts_dns%%.} (or use the Tailscale IP)."
    return 0
}

init_tailscale() {

    _skip_pve_step 9 "Tailscale initialization" && return 0

    prompt_until_ynet "9. QUESTION: Initialize Tailscale? (y/n, e or t to exit setup): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi
    log INFO "Initializing Tailscale..."
    log INFO "Topology: all nodes join Tailscale for AWS EFS; remote admin uses the main node + pfSense LAN route."
    local is_main_node="n"
    prompt_until_yn "9.0. QUESTION: Is this the designated main Proxmox cluster node (admin hub; step 17 TLS only here)? (y/n): " is_main_node

    local ts_host_input=""
    prompt_line_trimmed "9.1. QUESTION: Specify Tailscale hostname (empty = this node's FQDN): " ts_host_input

    if [ -z "$ts_host_input" ]; then
        ts_host_input="$(hostname -f 2>/dev/null || true)"
        if [ -z "$ts_host_input" ]; then
            ts_host_input="$(hostname 2>/dev/null || true)"
        fi
        if [ -n "$ts_host_input" ]; then
            log INFO "Using node hostname for Tailscale: ${ts_host_input}"
        else
            log WARN "Could not read hostname; tailscale up will run without --hostname."
        fi
    fi

    local ts_hostname_arg=""
    if [ -n "$ts_host_input" ]; then
        ts_hostname_arg=" --hostname=${ts_host_input}"
    fi

    subnet_routes=""
    if [ "$is_main_node" != "y" ]; then
        log INFO "Worker node: skipping --advertise-routes (pfSense advertises LAN; dual routers cause conflicts)."
    else
        log INFO "Main node: pfSense should advertise 172.16.0.0/16 — PVE route advertisement is usually unnecessary."
        prompt_line_trimmed "9.2. QUESTION: Advertise subnet routes on this node? (empty = none; recommended) or CIDR list: " subnet_routes
        if [ -n "$subnet_routes" ]; then
            subnet_routes=" --advertise-routes=${subnet_routes}"
        elif default_routes="$(_default_subnet_routes)" && [ -n "$default_routes" ]; then
            prompt_until_yn "9.2.1. QUESTION: Use routes from default.gateways.list? (y/n): " confirm
            if [ "$confirm" == "y" ]; then
                subnet_routes=" --advertise-routes=${default_routes}"
            fi
        else
            prompt_until_yn "9.2.1. QUESTION: Advertise LAN fallback routes from default.lan.routes.list (main-node backup if pfSense is down)? (y/n): " confirm
            if [ "$confirm" == "y" ] && lan_routes="$(_default_lan_subnet_routes)" && [ -n "$lan_routes" ]; then
                subnet_routes=" --advertise-routes=${lan_routes}"
                log WARN "Only one device should advertise 172.16.0.0/16 — disable pfSense route first if using PVE fallback."
            fi
        fi
    fi

    prompt_line_trimmed "9.3. QUESTION: Specify tag names to advertise? (e.g. tag:pve-node,tag:...) or leave empty for default: " tag_names
    if [ -n "$tag_names" ]; then
        tag_names="$(_str_trim "$tag_names")"
        while [[ "$tag_names" == *, ]]; do tag_names="${tag_names%,}"; done
        tag_names=" --advertise-tags=${tag_names}"
    else
        prompt_until_yn "9.3.1. QUESTION: Use default tag names? (y/n): " confirm
        if [ "$confirm" == "y" ] && default_tags="$(_default_tags)" && [ -n "$default_tags" ]; then
            tag_names=" --advertise-tags=${default_tags}"
        elif [ "$confirm" == "y" ]; then
            log WARN "Default tags list not found or empty (${TAILSCALE_TAGS_LIST})."
        fi
    fi

    local ts_up_command="tailscale up --accept-dns --ssh --reset${ts_hostname_arg}${subnet_routes}${tag_names}"
    log INFO "Running command: ${ts_up_command}"
    bash -c "${ts_up_command}" || {
        log ERROR "Failed to initialize Tailscale."
        return 1
    }
    log INFO "Tailscale initialized."

    local confirm_sanity=""
    prompt_until_yn "9.4. QUESTION: Run Tailscale post-init sanity check (status, IP, DNS name)? (y/n): " confirm_sanity
    if [ "$confirm_sanity" == "y" ]; then
        tailscale_post_init_sanity_check || log WARN "Tailscale sanity check had warnings."
    fi

    log INFO "Tailscale initialization done."
    return 0
}

# -----------------------------------------------------------------------------
# Post-startup procedure: set noout flag to false for ceph cluster
# -----------------------------------------------------------------------------
setup_post_startup_procedure() {

    _skip_pve_step 10 "post-startup procedure setup" && return 0

    prompt_until_yqnet "10. QUESTION: Setup post-startup procedure? (y/?/n, e or t to exit setup steps): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "?" ]; then
        return 0
    fi

    if [ "$confirm" == "?" ]; then
        log INFO "This procedure configures a post-startup service for the node."
        log INFO "It installs a script that is triggered during startup to set the Ceph 'noout' flag to false, ensuring data integrity during cluster node transitions."
        log INFO "Below is the content of 'post-startup-proc.sh' that will be installed and run at startup:"
        less "${SCRIPT_DIR}/post-startup-proc.sh"

        confirm_continue=
        prompt_until_yn "10.1. QUESTION: Continue to set up post-startup procedure now? (y/n): " confirm_continue
        if [ "$confirm_continue" != "y" ]; then
            log INFO "Skipping post-startup procedure setup."
            return 0
        fi
    fi
    log INFO "Setting up post-startup procedure..."
    log INFO "Linking post-startup-proc.sh to /usr/local/bin/post-startup-proc.sh"
    ln -sfv "${SCRIPT_DIR}/post-startup-proc.sh" /usr/local/bin/post-startup-proc.sh
    log INFO "Linking post-startup-proc.service to /etc/systemd/system/post-startup-proc.service"
    ln -sfv "${SCRIPT_DIR}/post-startup-proc.service" /etc/systemd/system/post-startup-proc.service

    prompt_until_yn "10.2. QUESTION: Is this node $HOSTNAME the main node? (y/n): " confirm
    if [ "$confirm" == "y" ]; then
        log INFO "Setting up /etc/default/pve-main-node..."
        echo "$HOSTNAME" > /etc/default/pve-main-node
        log INFO "/etc/default/pve-main-node set to $HOSTNAME"
        local quorum_wait=""
        prompt_line_trimmed "10.3. QUESTION: Seconds to wait for cluster quorum at boot (empty = ${DEFAULT_QUORUM_WAIT_SEC}): " quorum_wait
        if [ -z "$quorum_wait" ]; then
            quorum_wait="$DEFAULT_QUORUM_WAIT_SEC"
        fi
        cat <<EOF >/etc/default/papita-post-startup
# Papita post-startup (step 10)
QUORUM_WAIT_SEC=${quorum_wait}
EOF
        log INFO "Wrote /etc/default/papita-post-startup (QUORUM_WAIT_SEC=${quorum_wait})."
    else
        log INFO "Skipping /etc/default/pve-main-node setup."
    fi

    log INFO "Reloading systemd daemon..."
    systemctl daemon-reload
    systemctl enable post-startup-proc.service
    log INFO "Enabled post-startup-proc.service (runs at boot; not started during setup)."

    log INFO "Post-startup procedure is set up. Done."
    return 0
}

# -----------------------------------------------------------------------------
# Pre-shutdown procedure: set noout flag to true for ceph cluster
# -----------------------------------------------------------------------------
setup_pre_shutdown_procedure() {

    _skip_pve_step 11 "pre-shutdown procedure setup" && return 0

    prompt_until_yqnet "11. QUESTION: Setup pre-shutdown procedure? (y/?/n, e or t to exit setup steps): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "?" ]; then
        return 0
    fi

    if [ "$confirm" == "?" ]; then
        log INFO "This procedure configures a pre-shutdown service for the node."
        log INFO "It installs a script that is triggered during shutdown/reboot to set the Ceph 'noout' flag, ensuring data integrity during cluster node transitions."
        log INFO "Below is the content of 'pre-shutdown-proc.sh' that will be installed and run at shutdown:"
        less "${SCRIPT_DIR}/pre-shutdown-proc.sh"

        prompt_until_yn "11.1. QUESTION: Continue to set up pre-shutdown procedure now? (y/n): " confirm_continue
        if [ "$confirm_continue" != "y" ]; then
            log INFO "Skipping pre-shutdown procedure setup."
            return 0
        fi
    fi

    log INFO "Setting up pre-shutdown procedure..."
    log INFO "Linking pre-shutdown-proc.sh to /usr/local/bin/pre-shutdown-proc.sh"
    ln -sfv "${SCRIPT_DIR}/pre-shutdown-proc.sh" /usr/local/bin/pre-shutdown-proc.sh
    log INFO "Linking pre-shutdown-proc.service to /etc/systemd/system/pre-shutdown-proc.service"
    ln -sfv "${SCRIPT_DIR}/pre-shutdown-proc.service" /etc/systemd/system/pre-shutdown-proc.service
    log INFO "Reloading systemd daemon..."
    systemctl daemon-reload
    systemctl enable pre-shutdown-proc.service
    systemctl start pre-shutdown-proc.service

    local confirm_stopall=""
    prompt_until_yn "11.2. QUESTION: Run pvesh stopall before shutdown/reboot? (y/n): " confirm_stopall
    local enable_stopall=0
    if [ "$confirm_stopall" == "y" ]; then
        enable_stopall=1
    fi
    local stopall_timeout=""
    prompt_line_trimmed "11.3. QUESTION: stopall timeout in seconds (empty = ${DEFAULT_STOPALL_TIMEOUT}): " stopall_timeout
    if [ -z "$stopall_timeout" ]; then
        stopall_timeout="$DEFAULT_STOPALL_TIMEOUT"
    fi
    cat <<EOF >/etc/default/papita-pre-shutdown
# Papita pre-shutdown (step 11)
ENABLE_STOPALL=${enable_stopall}
STOPALL_TIMEOUT=${stopall_timeout}
EOF
    log INFO "Wrote /etc/default/papita-pre-shutdown."

    log INFO "Pre-shutdown procedure is set up. Done."
    return 0
}

# -----------------------------------------------------------------------------
# Email notifications: postfix relay + Proxmox cluster mailto/mailfrom.
# -----------------------------------------------------------------------------
setup_email_notifications() {
    _skip_pve_step 12 "email notification setup" && return 0

    prompt_until_ynet "12. QUESTION: Configure email notifications (postfix + Proxmox mailto)? (y/n, e or t to exit setup): " confirm
    if [ "$confirm" != "y" ]; then
        return 0
    fi

    local mailto mailfrom relay
    prompt_line_trimmed "12.1. QUESTION: Alert recipient (mailto, e.g. admin@example.com): " mailto
    if [ -z "$mailto" ]; then
        log ERROR "mailto address is required."
        return 1
    fi
    prompt_line_trimmed "12.2. QUESTION: mailfrom address (empty = root@pam): " mailfrom
    if [ -z "$mailfrom" ]; then
        mailfrom="root@pam"
    fi
    prompt_line_trimmed "12.3. QUESTION: SMTP relay [host]:port (empty = local postfix only): " relay

    export DEBIAN_FRONTEND=noninteractive
    echo "postfix postfix/main_mailer_type select Satellite system" | debconf-set-selections
    if [ -n "$relay" ]; then
        echo "postfix postfix/relayhost string ${relay}" | debconf-set-selections
    else
        echo "postfix postfix/relayhost string " | debconf-set-selections
    fi
    apt-get install -y postfix

    if command -v pvesh &>/dev/null; then
        pvesh set /cluster/options --mailto "$mailto" --mailfrom "$mailfrom" || log WARN "pvesh set mail options failed."
    else
        log WARN "pvesh not found; configure mailto in the Proxmox UI later."
    fi

    systemctl enable postfix.service
    systemctl restart postfix.service
    log INFO "Email notifications configured (mailto=${mailto}, mailfrom=${mailfrom})."
    return 0
}

# -----------------------------------------------------------------------------
# SMART disk health: periodic smartctl scan (all disks; useful with NAS/external storage).
# -----------------------------------------------------------------------------
setup_smart_monitoring() {
    _skip_pve_step 13 "SMART monitoring setup" && return 0

    prompt_until_ynet "13. QUESTION: Setup SMART disk health monitoring (smartmontools cron)? (y/n, e or t to exit setup): " confirm
    if [ "$confirm" != "y" ]; then
        return 0
    fi

    apt-get install -y smartmontools

    local smart_schedule=""
    prompt_crontab_schedule smart_schedule "${DEFAULT_SMART_CRON_SCHEDULE}" \
        "13.1. QUESTION: SMART scan cron schedule (five time fields; empty = default ${DEFAULT_SMART_CRON_SCHEDULE}): "

    local scan_script="/usr/local/sbin/papita-smart-scan.sh"
    cat <<'SMART_EOF' >"${scan_script}.tmp"
#!/bin/bash
# Papita: SMART health summary for all detected devices.
set -euo pipefail
if ! command -v smartctl >/dev/null 2>&1; then
    echo "[papita-smart-scan] smartctl not installed." >&2
    exit 1
fi
mapfile -t devs < <(smartctl --scan-open 2>/dev/null | awk '{print $1}' || true)
if [[ ${#devs[@]} -eq 0 ]]; then
    echo "[papita-smart-scan] no devices from smartctl --scan-open."
    exit 0
fi
for dev in "${devs[@]}"; do
    echo "=== ${dev} ==="
    smartctl -H "$dev" 2>/dev/null || echo "WARN: smartctl -H failed for ${dev}"
done
SMART_EOF
    mv -f "${scan_script}.tmp" "$scan_script"
    chmod 0755 "$scan_script"

    local cron_file="/etc/cron.d/papita-smart-scan"
    cat <<EOF >"$cron_file"
# Papita: SMART health scan (step 13).
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
${smart_schedule} root ${scan_script} >>/var/log/papita-smart-scan.log 2>&1
EOF
    chmod 0644 "$cron_file"
    touch /var/log/papita-smart-scan.log
    log INFO "SMART monitoring cron installed (${cron_file}, schedule: ${smart_schedule})."
    return 0
}

# -----------------------------------------------------------------------------
# Enable Proxmox cluster firewall (after Tailscale rule exists from step 8.1).
# -----------------------------------------------------------------------------
enable_proxmox_cluster_firewall() {
    _skip_pve_step 14 "Proxmox cluster firewall enable" && return 0

    local cluster_fw="/etc/pve/firewall/cluster.fw" confirm_create=""
    if [ ! -f "$cluster_fw" ]; then
        log WARN "No ${cluster_fw}; run step 8.1 first or create rules manually."
        prompt_until_ynet "14. QUESTION: Enable cluster firewall anyway (creates minimal cluster.fw)? (y/n, e or t to exit setup): " confirm_create
        if [ "$confirm_create" != "y" ]; then
            return 0
        fi
        setup_proxmox_firewall_tailscale || true
    fi

    if grep -qE '^[[:space:]]*enable:[[:space:]]*1' "$cluster_fw" 2>/dev/null; then
        log INFO "Proxmox cluster firewall already enabled."
        return 0
    fi

    log WARN "Enabling the cluster firewall affects ALL nodes. Ensure Tailscale/management access works first."
    prompt_until_ynet "14. QUESTION: Set enable: 1 in ${cluster_fw}? (y/n, e or t to exit setup): " confirm
    if [ "$confirm" != "y" ]; then
        return 0
    fi

    if grep -qE '^[[:space:]]*enable:' "$cluster_fw"; then
        sed -i 's/^[[:space:]]*enable:.*/enable: 1/' "$cluster_fw"
    else
        sed -i '/^\[OPTIONS\]/a enable: 1' "$cluster_fw"
    fi
    log INFO "Proxmox cluster firewall enabled (enable: 1)."
    return 0
}

remove_pve_subscription_alert() {
    _skip_pve_step 15 "PVE subscription alert removal" && return 0

    prompt_until_ynet "15. QUESTION: Remove PVE subscription alert? (y/n, e or t to exit setup steps): " confirm
    if [ "$confirm" != "y" ]; then
        log INFO "Skipping PVE subscription alert removal..."
        return 0
    fi

    if [ -f /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.bak ]; then
        log WARN "PVE subscription alert backup file found. Restoring..."
        cp -fv /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.bak /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
        log INFO "PVE subscription alert backup file restored."
    fi

    log INFO "Removing PVE subscription alert..."
    cp /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.bak
    sed -i '/checked_command: function (orig_cmd) {$/a\    return (typeof orig_cmd === "function" && (orig_cmd(), true));' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
    log WARN "PVE subscription alert removed. Restarting pveproxy.service..."
    systemctl restart pveproxy.service
    log INFO "PVE subscription alert removed. Done."
    return 0
}

# -----------------------------------------------------------------------------
# Periodic vzdump backup job (configurable schedule).
# -----------------------------------------------------------------------------
setup_backup_job() {
    _skip_pve_step 16 "backup job setup" && return 0

    prompt_until_ynet "16. QUESTION: Configure a periodic vzdump backup job (cron)? (y/n, e or t to exit setup): " confirm
    if [ "$confirm" != "y" ]; then
        return 0
    fi

    local storage mode compress backup_schedule
    prompt_line_trimmed "16.1. QUESTION: Proxmox storage ID for backups (empty = local): " storage
    if [ -z "$storage" ]; then
        storage="local"
    fi
    prompt_line_trimmed "16.2. QUESTION: Backup mode snapshot|suspend|stop (empty = snapshot): " mode
    if [ -z "$mode" ]; then
        mode="snapshot"
    fi
    prompt_line_trimmed "16.3. QUESTION: Compression zstd|gzip|0 (empty = zstd): " compress
    if [ -z "$compress" ]; then
        compress="zstd"
    fi
    prompt_crontab_schedule backup_schedule "${DEFAULT_VZDUMP_CRON_SCHEDULE}" \
        "16.4. QUESTION: Backup cron schedule (five time fields; empty = default ${DEFAULT_VZDUMP_CRON_SCHEDULE}): "

    local dump_script="/usr/local/sbin/papita-vzdump-all.sh"
    cat <<DUMP_EOF >"${dump_script}.tmp"
#!/bin/bash
# Papita: backup all VMs and CTs on this node (step 16).
set -euo pipefail
STORAGE="${storage}"
MODE="${mode}"
COMPRESS="${compress}"
MAILTO="root@pam"
vzdump_one() {
    local id="\$1"
    vzdump "\$id" --storage "\$STORAGE" --mode "\$MODE" --compress "\$COMPRESS" --mailto "\$MAILTO"
}
if command -v qm >/dev/null 2>&1; then
    while read -r vmid; do
        [[ -z "\$vmid" ]] && continue
        vzdump_one "\$vmid"
    done < <(qm list 2>/dev/null | awk 'NR>1 {print \$1}')
fi
if command -v pct >/dev/null 2>&1; then
    while read -r ctid; do
        [[ -z "\$ctid" ]] && continue
        vzdump_one "\$ctid"
    done < <(pct list 2>/dev/null | awk 'NR>1 {print \$1}')
fi
DUMP_EOF
    mv -f "${dump_script}.tmp" "$dump_script"
    chmod 0755 "$dump_script"

    local cron_file="/etc/cron.d/papita-vzdump-all"
    cat <<EOF >"$cron_file"
# Papita: cluster-wide vzdump (step 16). Review storage ${storage} before first run.
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
${backup_schedule} root ${dump_script} >>/var/log/papita-vzdump-all.log 2>&1
EOF
    chmod 0644 "$cron_file"
    touch /var/log/papita-vzdump-all.log
    log INFO "Backup cron installed (${cron_file}, schedule: ${backup_schedule})."
    log WARN "Verify storage '${storage}' exists and has enough space before the first scheduled run."
    return 0
}

# -----------------------------------------------------------------------------
# Step 17: Tailscale-issued TLS certificate for Proxmox Web UI (port 8006).
# Walkthrough: https://tailscale.com/docs/integrations/proxmox
# Only runs when the operator confirms this is the main node (single designated place).
# -----------------------------------------------------------------------------
setup_pve_tailscale_ui_certificate() {
    _skip_pve_step 17 "Proxmox HTTPS certificate via Tailscale" && return 0

    log INFO "Step 17 replaces the default self-signed Proxmox UI certificate with one issued via Tailscale (trusted in browsers on your tailnet)."
    log INFO "Upstream guide: https://tailscale.com/docs/integrations/proxmox"

    prompt_until_ynet "17. QUESTION: Is this the main Proxmox cluster node (enable step 17 certificate setup only here)? (y/n, e or t to exit setup steps): " confirm_main
    if [ "${confirm_main:-}" != "y" ]; then
        log INFO "Skipping step 17 — run it on the main node when you want Tailscale-managed TLS for that host's UI."
        return 0
    fi

    prompt_until_yn "17.1. QUESTION: Fetch Tailscale certificate and install it with pvenode cert set (restarts API proxy)? (y/n): " confirm
    if [ "$confirm" != "y" ]; then
        log INFO "Skipping Proxmox HTTPS certificate via Tailscale..."
        return 0
    fi

    if ! command -v tailscale &>/dev/null; then
        log ERROR "tailscale not found. Complete steps 8–9 first."
        return 1
    fi
    if ! command -v jq &>/dev/null; then
        log ERROR "jq not found (required for tailscale status --json). Install via step 1 / apt-dependencies.list."
        return 1
    fi
    if ! command -v pvenode &>/dev/null; then
        log ERROR "pvenode not found. This does not look like a Proxmox VE node."
        return 1
    fi

    local cert_dir="/var/lib/papita-tailscale-pve-cert"
    install -d -m 0700 "$cert_dir"

    local ts_name
    if ! ts_name="$(tailscale status --json | jq -r '.Self.DNSName | if . == null then empty else .[:-1] end')"; then
        log ERROR "Failed to read Tailscale status JSON."
        return 1
    fi
    if [[ -z "$ts_name" ]]; then
        log ERROR "Tailscale DNS name is empty. Is the node logged in (tailscale up)?"
        return 1
    fi

    log INFO "Using Tailscale certificate name: ${ts_name}"
    (
        set -euo pipefail
        cd "$cert_dir"
        tailscale cert "$ts_name"
        pvenode cert set "${ts_name}.crt" "${ts_name}.key" --force --restart
    ) || {
        log ERROR "tailscale cert or pvenode cert set failed."
        return 1
    }

    log INFO "Step 17 certificate installed. Open the UI with https://${ts_name}:8006 (or your tailnet MagicDNS name) without the old self-signed warning."

    prompt_until_yn "17.2. QUESTION: Install renewal helper + /etc/cron.d entry (Tailscale-style periodic renew)? (y/n): " confirm_cron
    if [ "${confirm_cron:-}" != "y" ]; then
        log INFO "Skipping renewal cron; re-run step 17 or renew manually before certificate expiry."
        return 0
    fi

    local cert_renew_schedule=""
    prompt_crontab_schedule cert_renew_schedule "${DEFAULT_TAILSCALE_PVE_CERT_CRON_SCHEDULE}" \
        "17.2.1. QUESTION: Renewal cron schedule (five time fields; empty = default ${DEFAULT_TAILSCALE_PVE_CERT_CRON_SCHEDULE}): "

    local renew_script="/usr/local/sbin/papita-pve-tailscale-cert-renew.sh"
    cat <<'RENEW_EOF' >"${renew_script}.tmp"
#!/bin/bash
# Papita: renew Tailscale-issued cert for Proxmox UI (see Tailscale Proxmox integration).
set -euo pipefail
CERT_DIR="/var/lib/papita-tailscale-pve-cert"
cd "$CERT_DIR"
NAME="$(tailscale status --json | jq -r '.Self.DNSName | if . == null then empty else .[:-1] end')"
if [[ -z "$NAME" ]]; then
    echo "[papita-pve-tailscale-cert-renew] empty Tailscale DNS name; abort." >&2
    exit 1
fi
tailscale cert "$NAME"
pvenode cert set "${NAME}.crt" "${NAME}.key" --force --restart
RENEW_EOF
    mv -f "${renew_script}.tmp" "$renew_script"
    chmod 0755 "$renew_script"

    local cron_file="/etc/cron.d/papita-pve-tailscale-cert"
    if [[ -f "$cron_file" ]] && grep -qF "papita-pve-tailscale-cert-renew" "$cron_file" 2>/dev/null; then
        log INFO "Cron entry already present in ${cron_file}; not duplicating."
    else
        cat <<EOF >"$cron_file"
# Papita: renew Proxmox UI cert from Tailscale (step 17).
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
${cert_renew_schedule} root ${renew_script}
EOF
        chmod 0644 "$cron_file"
        log INFO "Installed ${cron_file} (schedule: ${cert_renew_schedule})."
    fi

    log INFO "Step 17 done."
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    case "${1:-}" in
        -h | --help)
            usage_setup_pve_node || true
            exit 0
            ;;
    esac

    confirm_pve_setup

    # Apt configuration: on failure the script exits (set -e)
    setup_apt_config || {
        RETURN_CODE=$?
        log ERROR "APT configuration failed. Exiting..."
        exit "$RETURN_CODE"
    }

    setup_hibernate || log WARN "Hibernate setup failed; continuing."
    setup_wake_on_lan || log WARN "Wake-on-LAN setup failed; continuing."

    setup_locales || log WARN "Locales setup failed; continuing."

    setup_lm_sensors || log WARN "lm-sensors setup failed; continuing."
    setup_time_sync || log WARN "Time sync setup failed; continuing."
    setup_cluster_hosts || log WARN "Cluster /etc/hosts setup failed; continuing."

    setup_tailscale || log WARN "Tailscale setup failed; continuing."
    init_tailscale || log WARN "Tailscale initialization failed; continuing."

    setup_post_startup_procedure || log WARN "Post-startup procedure setup failed; continuing."
    setup_pre_shutdown_procedure || log WARN "Pre-shutdown procedure setup failed; continuing."

    setup_email_notifications || log WARN "Email notification setup failed; continuing."
    setup_smart_monitoring || log WARN "SMART monitoring setup failed; continuing."
    enable_proxmox_cluster_firewall || log WARN "Proxmox cluster firewall enable failed; continuing."

    remove_pve_subscription_alert || log WARN "PVE subscription alert removal failed; continuing."

    setup_backup_job || log WARN "Backup job setup failed; continuing."
    setup_pve_tailscale_ui_certificate || log WARN "Proxmox Tailscale UI certificate step failed; continuing."

    log INFO "Done."
}

main "$@"
