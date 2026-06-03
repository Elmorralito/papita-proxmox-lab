# Usefull Proxmox Maintenance Actions

## WARNINGS

### After enabling the 2FA/TOTP on the cluster...

All nodes have to be online in order for the 2FA to work, otherwise use a recovery user to disable the 2FA as follows: **[`RECOVERY USER GUIDE`](https://forum.proxmox.com/threads/locked-out-proxmox-gui-because-of-totp-2fa-solved.110155/)**

## OSD Storage at startup

When starting the cluster it's necessary to reset the OSD storages before anything in all nodes, this is meant to maintain the integrity of the ceph pools when starting the VMs and CTs, otherwise it might corrupt the storages and the pool.

This is done by doing:

1. Check that all nodes are online.
2. Check OSD health:
   ```shell
    ceph health detail
   ```
3. Restart the osd service for all OSD storages (It can be done at main node):
   ```shell
   systemctl restart ceph-osd.target
   ```
4. Restart the OSD storages individually
   ```shell
   systemctl restart ceph-osd@<id> # The id of the OSD storage.
   ```
5. Check if the MGR system is working, if not then run:
   ```shell
   systemctl restart ceph-mgr.target
   ```
6. Finally, If the OSD is running but not shown, try forcing a refresh of the configuration by restarting the pvestatd service:
   ```shell
   systemctl restart pvestatd
   ```

> [!NOTE]
> **The ID of the ceph OSD storage can be identified by running:**
>
> ```shell
> ceph-volume lvm list # or...
> ceph osd tree
> ```
>
> To know in detail the status of the OSD
>
> ```shell
> pveceph osd details <id>
> ```
>
> ---
>
> **To wipe a disk**
>
> ```shell
> lsblk # List volumes and partitions
> dd if=/dev/zero of="/dev/<disk label>" bs=1M status=progress # wipe disk
> ```
>
> ---
>
> **To remove corrupted pools from GUI and VE**
>
> ```shell
> ceph osd lspools # or ...
> pvesm status # To identify the conflicting pool with type rbd
> pvesm remove "<Pool name>"
> ```

## Remove Proxmox Subscription Alert on GUI (Already set in pve-setup)

**\*Ref:** https://www.youtube.com/watch?v=AlMh0shKDEM&t=256s*

1. Go to `/usr/share/javascript/proxmox-widget-toolkit`
2. Locate and backup the file `proxmoxlib.js`
3. Find Keyword/Pattern **`No Valid Subcription`** within the JS code.
4. At the beginning of the function `checked_command: function (orgi_cmd) { ...` add the following line:
   ```js
   // Suppress "No valid subscription" alert...
   return typeof orig_cmd === "function" && (orig_cmd(), true);
   ```
5. Save and restart service:
   ```shell
   systemctl restart pveproxy.service
   ```

Alternatively run the following command:

```shell
cp /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.bak && sed -i '/checked_command: function (orig_cmd) {$/a\    return (typeof orig_cmd === "function" && (orig_cmd(), true));' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && systemctl restart pveproxy.service
```

> [!WARNING]
>
> 1. This procedure may vary depending on the major version of Proxmox.
> 2. This is only applied in the node where the GUI is being used. In case of using the GUI from other nodes, it's necessary to apply this action in those nodes as well.

## Remove node from cluster

Removing a node from a Proxmox VE (PVE) cluster must be done via the command line, as there is no option to do this directly through the Web GUI.

### Prerequisites

- **Migrate or Stop Resources:** Move all Virtual Machines (VMs) and Containers (CTs) to other nodes or back them up and delete them from the node being removed.
- **Ceph (If Applicable):** If using Ceph, you must first destroy all OSDs, Monitors, and Managers on the target node before proceeding with cluster removal.
- **Powered Off:** Shut down the node you intend to remove and disconnect it from the network.
  Proxmox

### Step-by-Step Removal Process

1. Perform these steps from the command line of a remaining node in the cluster:
2. Verify Node Name: List all nodes to identify the exact name of the node you want to delete.

```bash
pvecm nodes
```

3. **Delete the Node:** Remove the node from the cluster configuration.

```bash
pvecm delnode <NODE_NAME>
```

_Replace <NODE_NAME> with the name found in step 1._

4. **Clean Up the Web GUI (Ghost Node):** If the node still appears in the Datacenter view with a red icon, manually remove its configuration directory from the cluster file system.

```bash
rm -rf /etc/pve/nodes/<NODE_NAME>
```

> [!NOTE]
>
> ### Post-Removal Notes
>
> - ** Never Power On Again:** Do not reconnect the removed node to the network while it still has its old PVE configuration, as it could conflict with the existing cluster.
> - **Reusing the Node:** If you want to use the removed hardware as a standalone server or rejoin it as a "new" node, it is strongly recommended to reinstall Proxmox VE from scratch.
> - **SSH Keys:** You may want to manually remove the old node's keys from /etc/pve/priv/authorized_keys to keep your security configuration clean.

## refresh vmbr0 ip address proxmox

To refresh or change the vmbr0 IP address in Proxmox, edit /etc/network/interfaces to update the IP, subnet, and gateway, then update /etc/hosts to match. Apply changes by running ifdown vmbr0 && ifup vmbr0, or restart the network service/reboot. The GUI method (System > Network) is generally preferred.

### Method 1: Command Line Interface (CLI) - Recommended

1. **Edit Network Configuration:** Open the file using vi or nano:

   ```bash
   nano /etc/network/interfaces
   ```

   Update the address, netmask, and gateway under the vmbr0 section.

2. **Edit Hosts File:** Ensure the hostname points to the new IP:

   ```bash
   nano /etc/hosts
   ```

   Change the old IP to the new IP.

3. **Apply Changes:** Restart the networking service or reboot:

   ```bash
   systemctl restart networking
   # OR
   reboot now
   ```

   **Optional:** If connectivity fails, clear the ARP cache on your router.

4. **Stop PVE Services:** Run on all nodes to prevent conflicts:

   ```bash
   systemctl stop pve-cluster corosync
   ```

5. **Start Local Mode:** Run on the node you are editing:

   ```bash
   pmxcfs -l
   ```

6. **Edit File:** Edit `/etc/pve/corosync.conf` to update the IP addresses of the nodes and increase `config_version`.

7. Restart Services:

   ```bash
   killall pmxcfs
   systemctl start pve-cluster
   ```

8. Reboot all nodes.

### Method 2: Web Interface (GUI)

1. Go to the Proxmox GUI, select your node, and click System > Network.
2. Select **vmbr0** and click Edit.
3. Update the IPv4/CIDR and Gateway fields.
4. Click OK to save.
5. Click Apply Configuration at the top.

#### Important Considerations

- **IP Conflict:** Make sure the new IP is not already in use.
- **Gateway:** Ensure the gateway is correct for the new subnet.
- **Cluster Node:** If in a cluster, update the IP in /etc/pve/corosync.conf if necessary, though the GUI usually handles this better.
- **Loss of Connectivity:** Changing the IP will break current browser sessions. Reconnect using the new IP address.

> [!NOTE]
> Accessing the web interface via `https://< new-IP >:8006`.

## [pfSense] When installing pfSense as Firewall and network traffic manager for VMs

pfSense is commonly deployed as a VM on Proxmox with at least two virtual NICs: one for **WAN** (upstream/internet or transit network) and one for **LAN** (internal VM/client network). This section covers preparing the LAN NIC, initial setup, firewall basics, and Tailscale integration.

**References:**

- [pfSense Setup Wizard](https://docs.netgate.com/pfsense/en/latest/config/setup-wizard.html)
- [WAN vs LAN Interfaces](https://docs.netgate.com/pfsense/en/latest/interfaces/wanvslan.html)
- [Interface Configuration](https://docs.netgate.com/pfsense/en/latest/config/interface-configuration.html)
- [Basic Firewall Configuration Example](https://docs.netgate.com/pfsense/en/latest/recipes/example-basic-configuration.html)
- [Tailscale on pfSense walkthrough](https://davidisaksson.dev/posts/tailscale-on-pfsense/)

---

### Step 1 — Plan networks before touching pfSense

1. **Assign roles to Proxmox NICs** before first boot:
   - **NIC 1 (WAN):** bridged to upstream network (home router, ISP modem, or transit VLAN).
   - **NIC 2 (LAN):** bridged to an internal Proxmox bridge (e.g. `vmbr1`) used only by VMs/CTs behind pfSense.
2. **Pick non-overlapping subnets.** WAN and LAN must not share the same IP range.
   - Example: WAN `192.168.1.0/24` (DHCP from upstream) and LAN `172.16.50.0/24` (static on pfSense).
   - Avoid `192.168.1.0/24` on LAN if WAN is also `192.168.1.0/24` — routing and NAT will break.
3. **Choose the pfSense LAN IP** — typically the first usable host address in the subnet (e.g. `172.16.50.1/24`). This address **becomes the default gateway** for every device on that LAN.

> [!IMPORTANT]
> **LAN NIC IP vs gateway — they are not the same field, and must not be confused.**
>
> - The **LAN interface IP** you assign to pfSense (e.g. `172.16.50.1/24`) **is** the default gateway that DHCP clients on that LAN will receive.
> - On a LAN interface, leave **IPv4 Upstream Gateway** blank (`none`). pfSense treats any interface with an upstream gateway selected as a **WAN-type** interface, which enables unwanted NAT/reply-to behavior on internal networks ([Netgate docs](https://docs.netgate.com/pfsense/en/latest/interfaces/wanvslan.html)).
> - Do **not** set the LAN NIC IP to the same address as an upstream router on that segment (e.g. if your ISP router is `192.168.1.1`, pfSense LAN cannot also be `192.168.1.1`).
> - Do **not** enter the LAN interface IP itself into the **IPv4 Upstream Gateway** field — the gateway for downstream hosts is pfSense's LAN IP; pfSense does not need an upstream gateway on its own LAN port.

---

### Step 2 — Proxmox VM network preparation

1. Create or identify the **internal bridge** (e.g. `vmbr1`) in Proxmox **System → Network**.
2. Attach the pfSense VM:
   - **net0** → WAN bridge (e.g. `vmbr0`)
   - **net1** → LAN bridge (e.g. `vmbr1`)
3. Set LAN-attached VMs to use **no gateway** until pfSense is configured, or give them a temporary static IP in the planned LAN subnet for testing.
4. Install pfSense from ISO; at the console **assign interfaces** when prompted:
   - Map the WAN MAC to `WAN`, LAN MAC to `LAN`.
   - Do not assign LAN as WAN by mistake — check MAC addresses in Proxmox VM hardware settings.

---

### Step 3 — Console: initial LAN NIC configuration

From the pfSense serial/console menu:

1. Select **2) Assign interface IP address**.
2. Select **LAN**.
3. Enter the IPv4 address and CIDR (e.g. `172.16.50.1/24`).
4. When asked for **IPv4 upstream gateway address** on a LAN interface: **press Enter for none** (console text: _"For a LAN, press \<ENTER\> for none"_).
5. Enable DHCP server on LAN if desired; set range (e.g. `172.16.50.100` – `172.16.50.200`).
6. Connect to the LAN bridge from a client VM or your workstation (via a Proxmox-linked VM) and open `https://172.16.50.1` (or the IP you chose).

> [!TIP]
> Default WebGUI credentials:
>
> - **username:** `admin`
> - **password:** `pfsense`

---

### Step 4 — Setup Wizard (WebGUI)

Run **System → Setup Wizard** (or complete it on first login):

| Step              | Action                                            |
| ----------------- | ------------------------------------------------- |
| Hostname / Domain | Set hostname (e.g. `pfsense`) and local domain    |
| Time server       | Enable NTP (default pool is fine)                 |
| WAN               | Usually **DHCP** unless ISP requires static/PPPoE |
| LAN               | Confirm static IP + subnet mask match Step 3      |
| Password          | Change default `admin` password                   |
| Reload            | Apply configuration                               |

**WAN defaults after install** ([pfSense defaults](https://docs.netgate.com/pfsense/en/latest/install/install-pfsense.html)):

- WAN: DHCP client (IPv4/IPv6)
- LAN: `192.168.1.1/24` unless changed in wizard
- All **incoming WAN** traffic blocked
- All **outbound LAN** traffic allowed (permissive default)
- NAT enabled on WAN for LAN traffic
- DHCP server enabled on LAN

---

### Step 5 — WebGUI: verify and finalize LAN NIC settings

1. Go to **Interfaces → LAN**.
2. Confirm:
   - **Enable interface:** checked
   - **IPv4 Configuration Type:** Static IPv4
   - **IPv4 Address:** e.g. `172.16.50.1/24`
   - **IPv4 Upstream Gateway:** **None** (must be empty)
3. Click **Save**, then **Apply Changes**.
4. Verify interface type: **Status → Interfaces** — LAN should **not** show a Gateway IPv4 attribute (that indicates WAN-type).
5. If a stray LAN gateway exists: **Interfaces → LAN** → remove gateway, then **System → Routing → Gateways** → delete any `LANGW` or LAN gateway; set default IPv4 gateway to WAN only.

**Optional — additional LAN-like interfaces (OPT, DMZ, VLAN):**

- Repeat the same pattern: static IP in a unique subnet, **no upstream gateway** on the interface tab.
- Assign the physical/virtual NIC under **Interfaces → Interface Assignments**.

---

### Step 6 — DHCP and DNS on LAN

1. **Services → DHCP Server → LAN**
   - Enable DHCP
   - Range within LAN subnet (exclude pfSense IP and static reservations)
   - **Gateway:** auto-filled with LAN interface IP — do not point clients at a different gateway unless pfSense is not the router for that segment
   - DNS: pfSense LAN IP (default) or custom internal DNS
2. **Services → DNS Resolver**
   - Enabled by default; pfSense resolves client queries and can host local hostnames via DHCP static mappings.

---

### Step 7 — Firewall basics

pfSense evaluates rules **on ingress per interface** — LAN tab rules filter traffic **from LAN hosts outward** ([firewall rules guide](https://www.zenarmor.com/docs/network-security-tutorials/pfsense-firewall-rules-guide)).

**Default policy (fresh install):**

| Interface | Default                                         |
| --------- | ----------------------------------------------- |
| WAN       | Deny all inbound                                |
| LAN       | Allow all outbound (`Default allow LAN to any`) |

**Recommended hardening** ([basic configuration recipe](https://docs.netgate.com/pfsense/en/latest/recipes/example-basic-configuration.html)):

1. **Firewall → Rules → LAN**
   - Keep the **Anti-Lockout Rule** (allows WebGUI access from LAN) — do not delete it.
   - Replace the broad `Default allow LAN to any` with explicit rules as needed, e.g.:
     - Allow LAN → LAN address, TCP/UDP 53 (DNS)
     - Allow LAN → LAN address, TCP 443 (WebGUI)
     - Allow LAN → LAN address, ICMP (ping firewall)
     - Allow LAN → any (internet) — place last among allow rules
2. **Firewall → Rules → WAN**
   - Leave deny-by-default; only add pinholes you need (e.g. IPsec, OpenVPN, or restricted admin access).
3. **Rule order matters** — first match wins; place specific rules above general ones.
4. **Stateful by default** — allowed outbound traffic automatically permits return traffic.

> [!WARNING]
> If there is no connection to the WebGUI or ping from external endpoints to the WAN IP after install, pfSense may be blocking WAN access. For emergency recovery only, from console edit `/cf/conf/config.xml` with `vi` and add under `<system>`:
>
> ```xml
> <disablefilter>1</disablefilter>
> ```
>
> Reboot, restore access, fix WAN rules, then **remove** `disablefilter` and re-enable the firewall.

---

### Step 8 — NAT (outbound)

Default **Automatic outbound NAT** masquerades LAN traffic to the WAN IP. Usually no change is needed for a simple lab.

- **Firewall → NAT → Outbound:** mode **Automatic** (default) or **Hybrid** if you add manual rules (required for some Tailscale site-to-site scenarios — see Step 9.6).

---

### Step 9 — Connect pfSense to Tailscale (site-to-site)

This lab uses Tailscale CGNAT space `100.64.0.0/10` on PVE nodes. pfSense joins the same tailnet as a **subnet router**, exposing LAN(s) to remote tailnet devices. PVE nodes can advertise their own routes/tags (see `src/bash/misc/tailscale/`). Site-to-site requires **both** Tailscale ACL grants **and** pfSense/NAT rules.

**References:**

- [Tailscale site-to-site networking](https://tailscale.com/docs/features/site-to-site)
- [Subnet routers + ACLs](https://tailscale.com/docs/features/subnet-routers)
- [ACL policy examples](https://tailscale.com/docs/reference/examples/acls)
- [pfSense ↔ Linux site-to-site](https://merox.dev/blog/tailscale-site-to-site/)
- [Netgate: subnet routes vs pfSense firewall rules](https://forum.netgate.com/topic/190879/tailscale-subnet-routes-exit-nodes-pfsense-firewall-rules)

#### 9.1 — Install the Tailscale package

1. **System → Package Manager → Available Packages**
2. Search `tailscale` → **Install**
3. Confirm; after install, **VPN → Tailscale** appears

#### 9.2 — Tag pfSense and generate an auth key

Tag the pfSense router so ACLs can reference it as a destination (not just by CIDR).

1. In [Tailscale admin → Access controls](https://login.tailscale.com/admin/acls), add **tag owners** (JSON editor):

```json
"tagOwners": {
  "tag:pfsense-lan-router": ["autogroup:admin"]
}
```

2. [Tailscale admin → Keys](https://login.tailscale.com/admin/settings/keys) → **Generate auth key**
   - Enable **Reusable** for a router
   - Under **Tags**, add `tag:pfsense-lan-router`
3. Copy the key (shown once)

> [!NOTE]
> Lab PVE nodes use tags from `src/bash/misc/tailscale/default.tags.list`: `tag:private-node`, `tag:pve-oldtimers-cluster`, `tag:server-node`. Define matching `tagOwners` entries for each tag your nodes use.

#### 9.3 — Authenticate pfSense

1. **VPN → Tailscale → Authentication** → paste **Pre-authentication Key** → **Save**
2. **VPN → Tailscale → Settings** → check **Enable Tailscale** → **Save**
3. [Tailscale admin → Machines](https://login.tailscale.com/admin/machines):
   - Approve pfSense if required
   - **Disable key expiry** for this trusted router
   - Confirm device shows tag `tag:pfsense-lan-router`

#### 9.4 — Advertise LAN subnets (subnet routing)

1. **VPN → Tailscale → Settings → Routing**
   - Check **Accept Subnet Routes** (required for site-to-site with PVE/other routers)
   - **Advertised Routes:** add each LAN CIDR behind pfSense, e.g. `172.16.1.0/24` (this lab's LAN; gateway typically `172.16.1.1`)
   - **Save**
2. Tailscale admin → pfSense node → **⋯ → Edit route settings** → approve each **Subnet route**
3. Test from a permitted tailnet device: `ping 172.16.1.101`

#### 9.5 — Optional: exit node

1. **VPN → Tailscale → Settings → Routing** → **Advertise Exit Node** → **Save**
2. Tailscale admin → **Edit route settings** → **Use as exit node**
3. Restrict exit-node use in ACLs (see 9.7) — do not grant `autogroup:internet` to everyone if only admins should use it

#### 9.6 — Access control: tags and specific machines → LAN (site-to-site)

Access to subnets **behind** pfSense is enforced primarily by **Tailscale ACLs**, not pfSense interface rules. Traffic forwarded via **subnet routes bypasses pfSense Tailscale-tab firewall rules** ([Netgate forum](https://forum.netgate.com/topic/190879/tailscale-subnet-routes-exit-nodes-pfsense-firewall-rules)). Plan ACLs first; use pfSense rules as a secondary layer where applicable.

##### Layer 1 — Tailscale ACL grants (required)

Open [Access controls → JSON editor](https://login.tailscale.com/admin/acls). Use **`grants`** (recommended) or legacy **`acls`**.

**Automation (this repo):** after advertising the route on pfSense, run:

```bash
export TAILSCALE_API_KEY='tskey-api-...'
export TAILSCALE_TAILNET='tailf1ad0d.ts.net'
./deploy/tailscale-pfsense-lan.sh configure
```

See `./deploy/tailscale-pfsense-lan.sh pfsense-steps` for pfSense WebGUI checklist.

**Example A — Allow one tag full access to pfSense LAN only**

```json
{
  "tagOwners": {
    "tag:pfsense-lan-router": ["autogroup:admin"],
    "tag:private-node": ["autogroup:admin"],
    "tag:pve-oldtimers-cluster": ["autogroup:admin"],
    "tag:server-node": ["autogroup:admin"]
  },
  "grants": [
    {
      "src": ["tag:private-node"],
      "dst": ["172.16.1.0/24"],
      "ip": ["*"]
    },
    {
      "src": ["tag:auth-client"],
      "dst": ["172.16.1.0/24"],
      "ip": ["*"]
    },
    {
      "src": ["tag:pfsense-oldtimers-client"],
      "dst": ["172.16.1.0/24"],
      "ip": ["*"]
    }
  ]
}
```

**Example B — Allow PVE cluster tag ↔ pfSense LAN (bidirectional site-to-site)**

Replace CIDRs with your actual pfSense LAN and PVE management/LAN subnets.

```json
{
  "grants": [
    {
      "src": ["tag:pve-oldtimers-cluster"],
      "dst": ["172.16.50.0/24"],
      "ip": ["*"]
    },
    {
      "src": ["172.16.50.0/24"],
      "dst": ["tag:pve-oldtimers-cluster"],
      "ip": ["*"]
    }
  ]
}
```

**Example C — Restrict to specific ports (e.g. HTTPS + Proxmox only)**

```json
{
  "grants": [
    {
      "src": ["tag:server-node"],
      "dst": ["172.16.50.0/24"],
      "ip": ["tcp:443", "tcp:8006"]
    }
  ]
}
```

**Example D — Allow one specific machine (by Tailscale IP or host alias)**

Add a **`hosts`** entry for readability, then grant by name:

```json
{
  "hosts": {
    "admin-laptop": "100.64.17.26",
    "pfsense-lan": "172.16.50.0/24"
  },
  "grants": [
    {
      "src": ["admin-laptop"],
      "dst": ["172.16.50.0/24"],
      "ip": ["*"]
    }
  ]
}
```

Or use the machine's **100.x Tailscale address** directly in `src` without `hosts`.

**Example E — Allow tag to reach pfSense tailnet IP + advertised LAN (management)**

```json
{
  "grants": [
    {
      "src": ["tag:private-node"],
      "dst": ["tag:pfsense-lan-router"],
      "ip": ["tcp:443", "tcp:22"]
    },
    {
      "src": ["tag:private-node"],
      "dst": ["172.16.50.0/24"],
      "ip": ["*"]
    }
  ]
}
```

**Example F — Default deny, then explicit allows (production pattern)**

Omit grants entirely or use minimal `acls` to deny by default; add only the grants above that you need. Tailscale is **deny-by-default** once you define restrictive grants; avoid leaving a broad `autogroup:member → *` rule alongside these.

**Auto-approve subnet routes by tag** (optional, JSON):

```json
"autoApprovers": {
  "routes": {
    "tag:pfsense-lan-router": ["172.16.50.0/24"],
    "tag:pve-oldtimers-cluster": ["10.0.0.0/24"]
  }
}
```

##### Layer 2 — pfSense firewall rules (secondary / return path)

Use pfSense rules for **exit-node traffic**, **return traffic**, and **defense in depth**. Subnet-route flows may not hit Tailscale-tab rules; still configure the following for site-to-site stability.

**A. Hybrid outbound NAT (LAN ↔ Tailscale site-to-site)**

Required when LAN hosts must reach tailnet or remote subnets with correct return paths ([merox.dev](https://merox.dev/blog/tailscale-site-to-site/)):

1. **Firewall → NAT → Outbound** → mode **Hybrid outbound NAT rule generation**
2. **Add** manual rule:

| Field       | Value                                                                   |
| ----------- | ----------------------------------------------------------------------- |
| Interface   | Tailscale                                                               |
| Source      | `172.16.50.0/24` (LAN net or alias)                                     |
| Destination | Any                                                                     |
| Translation | Interface address (or pfSense Tailscale IP `/32` if alias UI is broken) |

**B. Tailscale interface — allow tailnet → LAN (exit node / direct tailnet traffic)**

**Firewall → Rules → Tailscale** — add **above** any block rules:

| #   | Action | Protocol | Source            | Destination      | Port | Description                    |
| --- | ------ | -------- | ----------------- | ---------------- | ---- | ------------------------------ |
| 1   | Pass   | IPv4 \*  | `100.64.0.0/10`   | `172.16.50.0/24` | \*   | Allow tailnet into pfSense LAN |
| 2   | Pass   | IPv4 \*  | Tailscale subnets | `LAN net`        | \*   | Alias-based variant            |

Create alias **Firewall → Aliases**:

- `TAILNET_ALLOWED` — type **Network(s)**: individual `/32` Tailscale IPs when ACLs allow only specific machines (mirrors ACL `hosts`)
- `TAILNET_CGNAT` — `100.64.0.0/10` (matches this lab's advertised route in `default.gateways.list`)

For **tag-scoped access**, pfSense cannot read Tailscale tags — maintain a **`TAILNET_ALLOWED`** alias listing the **100.x addresses** of machines that ACLs permit, and use that alias as **Source** instead of the full `/10`.

**C. LAN interface — allow return traffic from LAN to tailnet**

**Firewall → Rules → LAN**:

| #   | Action | Protocol | Source    | Destination       | Port | Description                       |
| --- | ------ | -------- | --------- | ----------------- | ---- | --------------------------------- |
| 1   | Pass   | IPv4 \*  | `LAN net` | `100.64.0.0/10`   | \*   | LAN hosts → tailnet               |
| 2   | Pass   | IPv4 \*  | `LAN net` | `TAILNET_ALLOWED` | \*   | Stricter: only ACL-approved peers |

**D. Optional — restrict LAN services by source tailnet IP**

If a LAN VM must accept traffic **only** from specific tailnet machines (e.g. Proxmox :8006):

| Action | Source            | Destination             | Port     |
| ------ | ----------------- | ----------------------- | -------- |
| Pass   | `TAILNET_ALLOWED` | `172.16.50.10` (PVE IP) | TCP 8006 |
| Block  | `100.64.0.0/10`   | `172.16.50.10`          | TCP 8006 |

Place **Pass** before **Block**. Match ACL grants: if ACL allows only `tag:private-node` machines, list those nodes' 100.x IPs in `TAILNET_ALLOWED`.

##### Layer 3 — PVE side (this lab)

PVE nodes join with tags/routes from setup (`setup-pve-node.sh`). For site-to-site **to** pfSense LAN:

1. PVE advertises its management/LAN subnet (if acting as subnet router)
2. ACL grant: `tag:pve-oldtimers-cluster` ↔ `172.16.50.0/24` (both directions if needed)
3. On PVE, Tailscale ACL already controls who can reach `:8006`; pfSense ACL controls who can reach LAN **behind** pfSense

##### Access matrix (example for this lab)

| Source                        | Destination                 | Enforced by               | pfSense rule (optional mirror)        |
| ----------------------------- | --------------------------- | ------------------------- | ------------------------------------- |
| `tag:private-node`            | `172.16.50.0/24`            | Tailscale grant           | Tailscale → LAN pass (100.x in alias) |
| `tag:pve-oldtimers-cluster`   | `172.16.50.0/24`            | Tailscale grant           | Same                                  |
| `tag:server-node`             | `172.16.50.0/24:443,8006`   | Tailscale grant (ports)   | LAN rule to specific host ports       |
| `admin-laptop` (`100.64.x.x`) | `172.16.50.0/24`            | Tailscale grant + `hosts` | Source = `/32` in `TAILNET_ALLOWED`   |
| `172.16.50.0/24`              | `tag:pve-oldtimers-cluster` | Tailscale grant (return)  | LAN → Tailscale pass + Hybrid NAT     |
| Any other tailnet member      | `172.16.50.0/24`            | **Denied** (no grant)     | Block or omit pass rule               |

#### 9.7 — Optional: Split DNS for internal hostnames

In [Tailscale admin → DNS](https://login.tailscale.com/admin/dns):

1. **Add nameserver → Custom** → pfSense LAN IP (e.g. `172.16.50.1`)
2. **Restrict to domain** (Split DNS) with your internal suffix
3. Remote clients resolve internal hostnames only if ACLs allow them to reach pfSense DNS (`udp/tcp:53`)

#### 9.8 — Verify ACL + firewall alignment

1. **Tailscale admin → Access controls → Tests** — add test cases for each tag → LAN grant
2. From a machine in `tag:private-node`: `ping 172.16.50.x` → expect success
3. From an **untagged** or **unauthorized** machine: same ping → expect failure
4. **pfSense → Status → System Logs → Firewall** — confirm pass/block on Tailscale and LAN tabs
5. **Status → Gateways** — WAN only; no LAN upstream gateway

---

### Step 10 — Verify end-to-end connectivity

| Check                      | Command / location                                     |
| -------------------------- | ------------------------------------------------------ |
| LAN clients reach pfSense  | `ping <pfSense-LAN-IP>` from a VM on LAN bridge        |
| LAN clients reach internet | `ping 1.1.1.1` / browse from LAN VM                    |
| pfSense on tailnet         | Tailscale admin shows pfSense **Connected**            |
| Subnet route approved      | Admin → Edit route settings → subnet checked           |
| Remote → LAN host          | `ping <LAN-VM-IP>` from tailnet laptop/phone           |
| ACL tag → LAN              | Access controls → Tests; ping from tagged node only    |
| Unauthorized denied        | Same ping from non-granted machine fails               |
| No LAN gateway mistake     | **Status → Gateways** — only WAN gateway; LAN has none |
| Interface types correct    | **Status → Interfaces** — LAN has no gateway field     |

---

### Quick troubleshooting

| Symptom                             | Likely cause                                                         | Fix                                                                                                                                     |
| ----------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| LAN clients no internet             | WAN down, DNS, or removed default LAN allow rule                     | Check **Status → Gateways**; restore LAN outbound rule                                                                                  |
| LAN clients cannot reach pfSense IP | Wrong subnet, bridge, or IP conflict                                 | Verify VM IP/gateway; pfSense LAN IP must be unique on segment                                                                          |
| `LANGW` gateway down                | Upstream gateway set on LAN                                          | Remove gateway from **Interfaces → LAN**                                                                                                |
| Tailnet cannot reach LAN VMs        | Subnet route not approved, missing ACL grant, or missing pfSense NAT | Approve routes; add `grants` for src tag → `172.16.1.0/24`; run `./deploy/tailscale-pfsense-lan.sh configure`; Hybrid NAT LAN→Tailscale |
| Authorized tag still blocked        | ACL grant missing port or wrong CIDR                                 | Check Access controls → Tests; match `172.16.1.0/24` to advertised route (not `172.16.50.0/24`)                                         |
| Unauthorized machine reaches LAN    | Overly broad ACL or pfSense pass rule for full `100.64.0.0/10`       | Remove broad grant; use tag-scoped grants + `TAILNET_ALLOWED` alias                                                                     |
| WAN WebGUI unreachable              | Default WAN block (expected)                                         | Access via LAN IP or add controlled WAN allow rule                                                                                      |
| WAN/LAN same subnet                 | Overlapping ranges                                                   | Re-number LAN to non-overlapping RFC1918 range                                                                                          |
