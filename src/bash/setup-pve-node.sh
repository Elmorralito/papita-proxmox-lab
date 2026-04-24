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
START_FROM_STEP=0
DEFAULT_CRONTAB_SCHEDULE="0 4 * * 6"
# Tailscale Proxmox cert renewal cron (step 11.2); five fields only — user/command appended by script.
DEFAULT_TAILSCALE_PVE_CERT_CRON_SCHEDULE="0 */12 * * *"
# paste -sd, avoids a trailing comma from tr '\n' ',' (empty tag after last newline).
DEFAULT_SUBNET_ROUTES="$(
    sed '/^[[:space:]]*$/d' "${SCRIPT_DIR}/misc/tailscale/default.gateways.list" | paste -sd, -
)"
DEFAULT_TAGS="\"$(
    sed '/^[[:space:]]*$/d' "${SCRIPT_DIR}/misc/tailscale/default.tags.list" | paste -sd, -
)\""

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
5. Setup Tailscale
6. Initialize Tailscale
7. Setup Post-startup procedure
8. Setup Pre-shutdown procedure
9. Remove PVE subscription alert
10. Restrict Proxmox web UI (8006) to Tailscale only
11. Proxmox Web UI: Tailscale-issued TLS certificate (HTTPS 8006)

  Usage: at the "Input:" prompt, enter h, help, ?, usage, -h, or --help to open the full manual in less (q to quit), then choose again.
EOF
    while true; do
        prompt_pve_start confirm 11
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

# -----------------------------------------------------------------------------
# APT: sources and upgrades. On failure we exit (do not return to main).
# -----------------------------------------------------------------------------
setup_apt_config() {

    if [ "$START_FROM_STEP" -gt 1 ]; then
        log INFO "Skipping APT configuration..."
        return 0
    fi

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
    apt_deps=$(grep -vE '^(\s*#|\s*$)' "${APT_DEPENDENCIES_LIST}" | tr '\n' ' ')
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

    log INFO "APT Configuration and auto-upgrades set up. Done."
}

# -----------------------------------------------------------------------------
# Hibernate: low swappiness (server-ish); disable sleep via sleep.conf + logind (no masked
# sleep targets—masks can stall or confuse shutdown, blocking clean S5 needed for WoL).
# -----------------------------------------------------------------------------
setup_hibernate() {
    if [ "$START_FROM_STEP" -gt 2 ]; then
        log INFO "Skipping Hibernate setup..."
        return 0
    fi

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

    if [ "$START_FROM_STEP" -gt 3 ]; then
        log INFO "Skipping Wake-on-LAN setup..."
        return 0
    fi

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

    if [ "$START_FROM_STEP" -gt 4 ]; then
        log INFO "Skipping locales setup..."
        return 0
    fi

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
    log INFO "Generating locales: ${locale}.${charset}..."
    if ! locale-gen "${locale}.${charset}"; then
        log ERROR "Failed to generate locale."
        return 1
    fi
    log INFO "Updating locale: ${locale}.${charset}..."
    update-locale LANG="${locale}.${charset}"
    log INFO "Locales are set up. Done."
    return 0
}

# -----------------------------------------------------------------------------
# Tailscale: install and sysctl. On failure return to main.
# -----------------------------------------------------------------------------
setup_tailscale() {

    if [ "$START_FROM_STEP" -gt 5 ]; then
        log INFO "Skipping Tailscale setup..."
        return 0
    fi

    prompt_until_ycnet "5. QUESTION: Setup Tailscale? (y/c/n, e or t to exit setup): " confirm

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

    prompt_until_yn "5.1. QUESTION: Allow Tailscale (100.64.0.0/10) in Proxmox firewall? (y/n): " confirm

    if [ "$confirm" == "y" ]; then
        setup_proxmox_firewall_tailscale || log WARN "Proxmox firewall rule for Tailscale failed; continuing."
    fi


    prompt_until_yn "5.2. QUESTION: Masquerade firewall due to known issue with Tailscale? (y/n): " confirm

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
    local cluster_fw="/etc/pve/firewall/cluster.fw"
    local rule_line="IN ACCEPT -source ${tailscale_cidr} -log n"

    if [ ! -d "$(dirname "${cluster_fw}")" ]; then
        log WARN "Proxmox firewall directory not found; skipping Tailscale firewall rule."
        return 1
    fi

    if [ -f "${cluster_fw}" ]; then
        if grep -qF "${tailscale_cidr}" "${cluster_fw}"; then
            log INFO "Proxmox firewall already has a rule for ${tailscale_cidr}."
            return 0
        fi
        if ! awk -v rule="${rule_line}" '/^\[RULES\]$/ { print; print rule; next } 1' "${cluster_fw}" > "${cluster_fw}.tmp" && mv "${cluster_fw}.tmp" "${cluster_fw}"; then
            log ERROR "Failed to add Tailscale rule to ${cluster_fw}."
            return 1
        fi
        log INFO "Added Proxmox firewall rule: accept IN from ${tailscale_cidr}."
    else
        cat <<EOF > "${cluster_fw}"
[OPTIONS]
enable: 0

[RULES]
${rule_line}
EOF
        log INFO "Created ${cluster_fw} with rule: accept IN from ${tailscale_cidr} (firewall left disabled; set enable: 1 to use)."
    fi
    return 0
}

init_tailscale() {

    if [ "$START_FROM_STEP" -gt 6 ]; then
        log INFO "Skipping Tailscale initialization..."
        return 0
    fi

    prompt_until_ynet "6. QUESTION: Initialize Tailscale? (y/n, e or t to exit setup): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi
    log INFO "Initializing Tailscale..."
    local ts_host_input=""
    prompt_line_trimmed "6.1. QUESTION: Specify Tailscale hostname (empty = this node's FQDN): " ts_host_input

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

    hostname=""
    if [ -n "$ts_host_input" ]; then
        hostname=" --hostname=${ts_host_input}"
    fi

    prompt_line_trimmed "6.2. QUESTION: Advertise which routes to Tailscale? (e.g. 10.0.0.0/8) or leave empty for default: " subnet_routes

    if [ -n "$subnet_routes" ]; then
        subnet_routes=" --advertise-routes=${subnet_routes}"
    else
        prompt_until_yn "6.2.1. QUESTION: Use default subnet routes? (y/n): " confirm
        if [ "$confirm" == "y" ]; then
            subnet_routes=" --advertise-routes=${DEFAULT_SUBNET_ROUTES}"
        fi
    fi

    prompt_line_trimmed "6.3. QUESTION: Specify tag names to advertise? (e.g. tag:pve-node,tag:...) or leave empty for default: " tag_names
    if [ -n "$tag_names" ]; then
        tag_names="$(_str_trim "$tag_names")"
        while [[ "$tag_names" == *, ]]; do tag_names="${tag_names%,}"; done
        tag_names=" --advertise-tags=${tag_names}"
    else
        prompt_until_yn "6.3.1. QUESTION: Use default tag names? (y/n): " confirm
        if [ "$confirm" == "y" ]; then
            tag_names=" --advertise-tags=${DEFAULT_TAGS}"
        fi
    fi

    COMMAND="tailscale up --accept-dns --ssh --reset${hostname}${subnet_routes}${tag_names}"
    log INFO "Running command: ${COMMAND}"
    bash -c "${COMMAND}" || {
        log ERROR "Failed to initialize Tailscale."
        return 1
    }
    log INFO "Tailscale initialized. Done."
    return 0
}

# -----------------------------------------------------------------------------
# Post-startup procedure: set noout flag to false for ceph cluster
# -----------------------------------------------------------------------------
setup_post_startup_procedure() {

    if [ "$START_FROM_STEP" -gt 7 ]; then
        log INFO "Skipping post-startup procedure setup..."
        return 0
    fi

    prompt_until_yqnet "7. QUESTION: Setup post-startup procedure? (y/?/n, e or t to exit setup steps): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "?" ]; then
        return 0
    fi

    if [ "$confirm" == "?" ]; then
        log INFO "This procedure configures a post-startup service for the node."
        log INFO "It installs a script that is triggered during startup to set the Ceph 'noout' flag to false, ensuring data integrity during cluster node transitions."
        log INFO "Below is the content of 'post-startup-proc.sh' that will be installed and run at startup:"
        less "${SCRIPT_DIR}/post-startup-proc.sh"

        confirm_continue=
        prompt_until_yn "7.1. QUESTION: Continue to set up post-startup procedure now? (y/n): " confirm_continue
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
    log INFO "Reloading systemd daemon..."
    systemctl daemon-reload
    systemctl enable post-startup-proc.service
    systemctl start post-startup-proc.service
    prompt_until_yn "7.2. QUESTION: Is this node $HOSTNAME the main node? (y/n): " confirm
    if [ "$confirm" == "y" ]; then
        log INFO "Setting up /etc/default/pve-main-node..."
        echo "$HOSTNAME" > /etc/default/pve-main-node
        log INFO "/etc/default/pve-main-node set to $HOSTNAME"
    else
        log INFO "Skipping /etc/default/pve-main-node setup."
    fi
    log INFO "Post-startup procedure is set up. Done."
    return 0
}

# -----------------------------------------------------------------------------
# Pre-shutdown procedure: set noout flag to true for ceph cluster
# -----------------------------------------------------------------------------
setup_pre_shutdown_procedure() {

    if [ "$START_FROM_STEP" -gt 8 ]; then
        log INFO "Skipping pre-shutdown procedure setup..."
        return 0
    fi

    prompt_until_yqnet "8. QUESTION: Setup pre-shutdown procedure? (y/?/n, e or t to exit setup steps): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "?" ]; then
        return 0
    fi

    if [ "$confirm" == "?" ]; then
        log INFO "This procedure configures a pre-shutdown service for the node."
        log INFO "It installs a script that is triggered during shutdown/reboot to set the Ceph 'noout' flag, ensuring data integrity during cluster node transitions."
        log INFO "Below is the content of 'pre-shutdown-proc.sh' that will be installed and run at shutdown:"
        less "${SCRIPT_DIR}/pre-shutdown-proc.sh"

        prompt_until_yn "8.1. QUESTION: Continue to set up pre-shutdown procedure now? (y/n): " confirm_continue
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
    log INFO "Pre-shutdown procedure is set up. Done."
    return 0
}

remove_pve_subscription_alert() {
    if [ "$START_FROM_STEP" -gt 9 ]; then
        log INFO "Skipping PVE subscription alert removal..."
        return 0
    fi

    prompt_until_ynet "9. QUESTION: Remove PVE subscription alert? (y/n, e or t to exit setup steps): " confirm
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
# Step 10: allow Proxmox HTTPS UI (8006) only from Tailscale CGNAT (iptables).
# See operational notes: run only when all cluster nodes are on Tailscale and reachable.
# -----------------------------------------------------------------------------
setup_pve_webui_tailscale_only() {
    if [ "$START_FROM_STEP" -gt 10 ]; then
        log INFO "Skipping Proxmox web UI Tailscale-only restriction..."
        return 0
    fi

    log WARN "Step 10 adds iptables rules so TCP port 8006 (Proxmox web UI) accepts traffic only from Tailscale (100.64.0.0/10)."
    log WARN "Do NOT enable this until every planned cluster node is connected on Tailscale (and you can reach the UI via Tailscale)."
    log WARN "Otherwise you can lock out non-Tailscale access before the cluster is fully reachable and complicate recovery."
    prompt_until_ynet "10. QUESTION: Apply Tailscale-only restriction for port 8006? (y/n, e or t to exit setup steps): " confirm
    if [ "$confirm" != "y" ]; then
        log INFO "Skipping Proxmox web UI Tailscale-only restriction..."
        return 0
    fi

    if [[ -f /etc/default/pve-main-node ]]; then
        local _pve_main_designate
        _pve_main_designate="$(sed 's/^[[:space:]]*//;s/[[:space:]]*$//' /etc/default/pve-main-node)"
        if [[ -n "$_pve_main_designate" && "$_pve_main_designate" == "$HOSTNAME" ]]; then
            log INFO "This host is the cluster main node (/etc/default/pve-main-node from step 7.2). Skipping iptables configuration for step 10."
            return 0
        fi
    fi

    if iptables-save -t filter 2>/dev/null | grep -qF "papita-allow-ts-8006"; then
        log INFO "iptables rules for papita-allow-ts-8006 / papita-drop-8006 already present; skipping insert."
    else
        log INFO "Inserting iptables rules (ACCEPT from Tailscale before DROP on 8006)..."
        iptables -I INPUT 1 -p tcp --dport 8006 -m comment --comment "papita-drop-8006" -j DROP
        iptables -I INPUT 1 -p tcp -s 100.64.0.0/10 --dport 8006 -m comment --comment "papita-allow-ts-8006" -j ACCEPT
    fi

    log INFO "Ensuring iptables rules persist across reboots..."
    apt-get install -y iptables-persistent
    netfilter-persistent save

    log INFO "Step 10 done. Verify: UI via Tailscale https://<tailscale-ip>:8006 ; from public IP it should not connect."
    log WARN "Optional: Datacenter/Node firewall in Proxmox UI can complement this; order ACCEPT before DROP if you mirror rules there."
    return 0
}

# -----------------------------------------------------------------------------
# Step 11: Tailscale-issued TLS certificate for Proxmox Web UI (port 8006).
# Walkthrough: https://tailscale.com/docs/integrations/proxmox
# Only runs when the operator confirms this is the main node (single designated place).
# -----------------------------------------------------------------------------
setup_pve_tailscale_ui_certificate() {
    if [ "$START_FROM_STEP" -gt 11 ]; then
        log INFO "Skipping Proxmox HTTPS certificate via Tailscale..."
        return 0
    fi

    log INFO "Step 11 replaces the default self-signed Proxmox UI certificate with one issued via Tailscale (trusted in browsers on your tailnet)."
    log INFO "Upstream guide: https://tailscale.com/docs/integrations/proxmox"

    prompt_until_ynet "11. QUESTION: Is this the main Proxmox cluster node (enable step 11 certificate setup only here)? (y/n, e or t to exit setup steps): " confirm_main
    if [ "${confirm_main:-}" != "y" ]; then
        log INFO "Skipping step 11 — run it on the main node when you want Tailscale-managed TLS for that host's UI."
        return 0
    fi

    prompt_until_yn "11.1. QUESTION: Fetch Tailscale certificate and install it with pvenode cert set (restarts API proxy)? (y/n): " confirm
    if [ "$confirm" != "y" ]; then
        log INFO "Skipping Proxmox HTTPS certificate via Tailscale..."
        return 0
    fi

    if ! command -v tailscale &>/dev/null; then
        log ERROR "tailscale not found. Complete steps 5–6 first."
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

    log INFO "Step 11 certificate installed. Open the UI with https://${ts_name}:8006 (or your tailnet MagicDNS name) without the old self-signed warning."

    prompt_until_yn "11.2. QUESTION: Install renewal helper + /etc/cron.d entry (Tailscale-style periodic renew)? (y/n): " confirm_cron
    if [ "${confirm_cron:-}" != "y" ]; then
        log INFO "Skipping renewal cron; re-run step 11 or renew manually before certificate expiry."
        return 0
    fi

    local cert_renew_schedule=""
    prompt_crontab_schedule cert_renew_schedule "${DEFAULT_TAILSCALE_PVE_CERT_CRON_SCHEDULE}" \
        "11.2.1. QUESTION: Renewal cron schedule (five time fields; empty = default ${DEFAULT_TAILSCALE_PVE_CERT_CRON_SCHEDULE}): "

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
# Papita: renew Proxmox UI cert from Tailscale (step 11).
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
${cert_renew_schedule} root ${renew_script}
EOF
        chmod 0644 "$cron_file"
        log INFO "Installed ${cron_file} (schedule: ${cert_renew_schedule})."
    fi

    log INFO "Step 11 done."
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

    setup_tailscale || log WARN "Tailscale setup failed; continuing."
    init_tailscale || log WARN "Tailscale initialization failed; continuing."

    setup_post_startup_procedure || log WARN "Post-startup procedure setup failed; continuing."
    setup_pre_shutdown_procedure || log WARN "Pre-shutdown procedure setup failed; continuing."

    remove_pve_subscription_alert || log WARN "PVE subscription alert removal failed; continuing."

    setup_pve_webui_tailscale_only || log WARN "Proxmox web UI Tailscale-only restriction failed; continuing."

    setup_pve_tailscale_ui_certificate || log WARN "Proxmox Tailscale UI certificate step failed; continuing."

    log WARN "Remember to setup the other PVE nodes in /etc/hosts after setup is complete."
    log INFO "Done."
}

main "$@"
