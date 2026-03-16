#!/bin/bash

set -euo pipefail

GREEN_TEXT='\033[0;32m'
RED_TEXT='\033[0;31m'
YELLOW_TEXT='\033[0;33m'
NC_TEXT='\033[0m'
BOLD_TEXT=$(tput bold)
NORMAL_TEXT=$(tput sgr0)

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
APT_DEPENDENCIES_LIST="${SCRIPT_DIR}/apt-dependencies.list"
START_FROM_STEP=0
DEFAULT_CRONTAB_SCHEDULE="0 4 * * 6"

log() {
    local level="$1"
    shift
    local color="${NC_TEXT}"
    if [[ "${level}" == "ERROR" ]]; then
        color="${RED_TEXT}"
    elif [[ "${level}" == "INFO" ]]; then
        color="${GREEN_TEXT}"
    elif [[ "${level}" == "WARN" ]]; then
        color="${YELLOW_TEXT}"
    elif [[ "$level" == "TRACE" ]]; then
        echo -e "$*"
        return
    fi
    echo -e "${color}$(date +"%Y-%m-%d %H:%M:%S") :: ${BOLD_TEXT}$(basename "$0")${NORMAL_TEXT} ${color}:: ${BOLD_TEXT}${level}${NORMAL_TEXT} ${color}:: $*${NC_TEXT}"
}



# -----------------------------------------------------------------------------
# Confirmation: exit script if user declines
# -----------------------------------------------------------------------------
confirm_pve_setup() {

    cat <<EOF
## QUESTION: Are you sure you want to setup PVE? (y/n) or a number to skip to a specific step:
1. Setup APT configuration
2. Setup Hibernate
3. Setup Wake-on-LAN
4. Setup Locales
5. Setup Tailscale
6. Initialize Tailscale
7. Setup Post-startup procedure
8. Setup Pre-shutdown procedure
9. Remove PVE subscription alert
EOF
    read -r -p "Input: " confirm

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

    read -r -p "1. QUESTION: Setup APT configuration? (y/n): " confirm

    if [ "$confirm" != "y" ]; then
        log INFO "Skipping APT configuration..."
        return 0
    fi
    log INFO "Setting up APT configuration..."
    if [[ ! -d /etc/apt/sources.list.d/ ]]; then
        log WARN "/etc/apt/sources.list.d/ directory not found. Creating..."
        cat <<EOF > /etc/apt/sources.list
deb http://ftp.debian.ord/debian stretch main contrib

deb http://download.proxmox.com/debian/pve stretch pve-no-subscription

deb http://security.debian.org strech/updates main contrib

EOF
    else
        log INFO "/etc/apt/sources.list.d/ directory found."
        log INFO "Chanding APT repositories..."
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
    read -r -p "1.1. QUESTION: Continue to install dependencies? (y/n): " confirm
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

    read -r -p "1.2. QUESTION: Define upgrade CRONTAB schedule: " crontab_schedule

    if [ -z "$crontab_schedule" ]; then
        log INFO "No upgrade CRONTAB schedule provided. Using default: ${DEFAULT_CRONTAB_SCHEDULE}"
        crontab_schedule="${DEFAULT_CRONTAB_SCHEDULE}"
    else
        log INFO "Upgrade CRONTAB schedule: $crontab_schedule"
    fi
    if [[ ! "$crontab_schedule" =~ ^([0-9\*]+[[:space:]]+){4,5}[0-9\*]+$ ]]; then
        log WARN "Invalid upgrade CRONTAB schedule. Using default: ${DEFAULT_CRONTAB_SCHEDULE}"
        crontab_schedule="${DEFAULT_CRONTAB_SCHEDULE}"
    fi
    log INFO "Setting up upgrade CRONTAB..."
    cron_command="apt-get update && apt-get dist-upgrade -y && apt-get autoremove -y && apt-get clean && apt-get autoclean"
    awk -v cmd="$cron_command" 'index($0, cmd)==0' /etc/crontab > /etc/crontab.tmp && mv /etc/crontab.tmp /etc/crontab
    echo "$crontab_schedule $cron_command" | tee -a /etc/crontab

    log INFO "APT Configuration and auto-upgrades set up. Done."
}

# -----------------------------------------------------------------------------
# Hibernate: set swappiness, logind, mask sleep targets. On failure return to main.
# -----------------------------------------------------------------------------
setup_hibernate() {
    if [ "$START_FROM_STEP" -gt 2 ]; then
        log INFO "Skipping Hibernate setup..."
        return 0
    fi

    read -r -p "2. QUESTION: Set hibernate off? (y/n): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi
    log INFO "Setting hibernate off..."
    cat <<EOF > /etc/sysctl.d/99-hibernate.conf
vm.swappiness = 0
EOF

    log INFO "Setting logind to ignore lid switch..."
    cat <<EOF >> /etc/systemd/logind.conf
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
EOF

    log INFO "Masking sleep, suspend, hibernate, and hybrid-sleep targets..."
    systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
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

    read -r -p "3. QUESTION: Setup Wake-on-LAN? (y/n): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi

    read -r -p "3.1. QUESTION: Enter interface name: " interface

    if ! ip link show "$interface" &>/dev/null; then
        log ERROR "Interface $interface not found."
        return 1
    fi
    check_wol=$(ethtool "$interface" 2>/dev/null | grep "Wake-on:" || true)
    if [ -z "$check_wol" ]; then
        log ERROR "Wake-on-LAN is not supported on interface $interface."
        return 1
    fi
    log INFO "Wake-on-LAN is supported on interface $interface."
    log INFO "Setting up Wake-on-LAN for interface $interface..."
    if ! ethtool -s "$interface" wol pg; then
        log ERROR "Failed to set up Wake-on-LAN for interface $interface."
        return 1
    fi
    cat <<EOF > /etc/systemd/system/wol.service
[Unit]
Description=Wake-on-LAN
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -s $interface wol pg

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable wol.service
    systemctl start wol.service
    log INFO "Wake-on-LAN is set up for interface $interface."
    mac_addr=$(ip link show "$interface" | awk '/ether/ {print $2}')
    if [ -z "$mac_addr" ]; then
        log ERROR "Could not determine MAC address for interface $interface."
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

    read -r -p "4. QUESTION: Setup locales? (y/n): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi

    read -r -p "4.1. QUESTION: Enter locale: " locale

    if [ -z "$locale" ]; then
        locale="en_US"
    fi

    read -r -p "4.2. QUESTION: Enter charset: " charset

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

    read -r -p "5. QUESTION: Setup Tailscale? (y/c/n): " confirm

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
    if [ -d "/etc/sysctl.d" ]; then
        log INFO "/etc/sysctl.d/ directory found. Setting up Tailscale..."
        echo 'net.ipv4.ip_forward = 1' | tee -a /etc/sysctl.d/99-tailscale.conf
        echo 'net.ipv6.conf.all.forwarding = 1' | tee -a /etc/sysctl.d/99-tailscale.conf
        sysctl -p /etc/sysctl.d/99-tailscale.conf
    else
        log INFO "/etc/sysctl.d/ directory not found. Setting up Tailscale..."
        echo 'net.ipv4.ip_forward = 1' | tee -a /etc/sysctl.conf
        echo 'net.ipv6.conf.all.forwarding = 1' | tee -a /etc/sysctl.conf
        sudo sysctl -p /etc/sysctl.conf
    fi

    read -r -p "5.1. QUESTION: Allow Tailscale (100.64.0.0/10) in Proxmox firewall? (y/n): " confirm

    if [ "$confirm" == "y" ]; then
        setup_proxmox_firewall_tailscale || log WARN "Proxmox firewall rule for Tailscale failed; continuing."
    fi


    read -r -p "5.2. QUESTION: Masquerade firewall due to known issue with Tailscale? (y/n): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi
    log WARN "Masquerading firewall due to known issue with Tailscale..."
    iptables -t nat -A POSTROUTING -o vmbr0 -j MASQUERADE
    apt install iptables-persistent -y
    netfilter-persistent save -y
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

    read -r -p "6. QUESTION: Initialize Tailscale? (y/n): " confirm

    if [ "$confirm" != "y" ]; then
        return 0
    fi
    log INFO "Initializing Tailscale..."
    read -r -p "6.1. QUESTION: Specify Tailscale hostname: " hostname

    if [ -n "$hostname" ]; then
        hostname=" --hostname=${hostname}"
    fi

    read -r -p "6.2. QUESTION: Advertise which routes to Tailscale? (e.g. 10.0.0.0/8): " subnet_routes

    if [ -n "$subnet_routes" ]; then
        subnet_routes=" --advertise-routes=${subnet_routes}"
    fi

    read -r -p "6.3. QUESTION: Specify tag names to advertise? (e.g. tag:pve-node,tag:...): " tag_names

    if [ -n "$tag_names" ]; then
        tag_names=" --advertise-tags=${tag_names}"
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

    read -r -p "7. QUESTION: Setup post-startup procedure? (y/?/n): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "?" ]; then
        return 0
    fi

    if [ "$confirm" == "?" ]; then
        log INFO "This procedure configures a post-startup service for the node."
        log INFO "It installs a script that is triggered during startup to set the Ceph 'noout' flag to false, ensuring data integrity during cluster node transitions."
        log INFO "Below is the content of 'post-startup-proc.sh' that will be installed and run at startup:"
        less "${SCRIPT_DIR}/post-startup-proc.sh"

        read -r -p "7.1. QUESTION: Continue to set up post-startup procedure now? (y/n): " confirm_continue
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
    read -r -p "7.2. QUESTION: Is this node $HOSTNAME the main node? (y/n): " confirm
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

    read -r -p "8. QUESTION: Setup pre-shutdown procedure? (y/?/n): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "?" ]; then
        return 0
    fi

    if [ "$confirm" == "?" ]; then
        log INFO "This procedure configures a pre-shutdown service for the node."
        log INFO "It installs a script that is triggered during shutdown/reboot to set the Ceph 'noout' flag, ensuring data integrity during cluster node transitions."
        log INFO "Below is the content of 'pre-shutdown-proc.sh' that will be installed and run at shutdown:"
        less "${SCRIPT_DIR}/pre-shutdown-proc.sh"

        read -r -p "8.1. QUESTION: Continue to set up pre-shutdown procedure now? (y/n): " confirm_continue
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

    read -r -p "9. QUESTION: Remove PVE subscription alert? (y/n): " confirm
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
# Main
# -----------------------------------------------------------------------------
main() {
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

    log WARN "Remember to setup the other PVE nodes in /etc/hosts after setup is complete."
    log INFO "Done."
}

main "$@"
