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

## Proxmox VE cluster — configuration & troubleshooting

Reference: [Proxmox Cluster Manager](https://pve.proxmox.com/pve-docs/chapter-pvecm.html). This lab uses corosync over the management LAN (typically `ring0_addr` on `vmbr0`).

### How do I delete or destroy an entire cluster?

Proxmox has **no single “delete cluster” action**. You remove members until one node remains, then convert that node to **standalone**, or reinstall hosts you no longer need.

**Before you start**

- Migrate or stop all VMs/CTs on nodes being removed.
- **Ceph:** destroy OSDs, monitors, and managers on each removed node before `pvecm delnode` (see [Remove node from cluster](#remove-node-from-cluster) above).
- Disable HA groups and remove any QDevice: `pvecm qdevice remove`.
- Do not let two separate clusters share the same storage (NFS, Ceph pool, EFS, etc.).

**Remove all peer nodes** (from any remaining online member):

```bash
pvecm nodes
pvecm delnode <NODE_NAME>
# If quorum blocks removal (common on 2-node clusters):
pvecm expected 1
pvecm delnode <NODE_NAME>
# Ghost node in GUI:
rm -rf /etc/pve/nodes/<NODE_NAME>
```

**Convert the last node to standalone** (official “separate without reinstalling” flow):

```bash
systemctl stop pve-cluster corosync
pmxcfs -l
rm /etc/pve/corosync.conf
rm -rf /etc/corosync/*
killall pmxcfs
systemctl start pve-cluster
rm -rf /var/lib/corosync/*
```

Remove **other** nodes’ directories only (never `rm -rf /etc/pve/nodes` without a specific name — that deletes local VM configs):

```bash
rm -rf /etc/pve/nodes/<OTHER_NODE_NAME>
```

**Safest path for removed hardware:** reinstall Proxmox before reusing or joining another cluster.

---

### How do I change cluster configuration?

Cluster settings live in several layers:

| Layer                         | Location                  | Typical changes                                  |
| ----------------------------- | ------------------------- | ------------------------------------------------ |
| Membership & corosync network | `/etc/pve/corosync.conf`  | Node IPs, links, quorum                          |
| Shared cluster state          | `/etc/pve/` (pmxcfs)      | Storage, users, firewall, HA                     |
| Datacenter options            | Web GUI → Datacenter      | Permissions, cluster firewall                    |
| Per-node network              | `/etc/network/interfaces` | `vmbr0` IP (must stay aligned with `ring0_addr`) |

**Inspect current state**

```bash
pvecm status
pvecm nodes
cat /etc/pve/corosync.conf
corosync-cfgtool -s
```

**Membership (add/remove nodes)** — use `pvecm`, not manual edits:

```bash
# On a fresh standalone node joining an existing cluster:
pvecm add <EXISTING_MEMBER_IP> --link0 <THIS_NODE_RING0_IP>

# Remove a member (from another node):
pvecm delnode <NODE_NAME>
```

**Edit corosync network or links** — always edit a copy, increment `config_version`, then replace:

```bash
cp /etc/pve/corosync.conf /etc/pve/corosync.conf.bak
cp /etc/pve/corosync.conf /etc/pve/corosync.conf.new
nano /etc/pve/corosync.conf.new
# … edit …
# In totem { }: increment config_version (required)
mv /etc/pve/corosync.conf.new /etc/pve/corosync.conf
systemctl status corosync
journalctl -u corosync -n 30 --no-pager
# If needed, one node at a time:
systemctl restart corosync
```

For **management IP changes** on `vmbr0`, see [refresh vmbr0 ip address proxmox](#refresh-vmbr0-ip-address-proxmox) below — update both `/etc/network/interfaces` and each node’s `ring0_addr` in corosync.

> [!WARNING]
> Use `pvecm expected 1` only as a **temporary** recovery aid during maintenance. Do not leave it as a permanent production setting.

---

### Can I merge ring1 into ring0 instead of deleting it?

**No.** In corosync/Proxmox, `ring0` (link 0) and `ring1` (link 1) are **separate redundant paths**, not layers of one link. You cannot combine two subnets into a single ring.

| Goal                                 | What to do                                                               |
| ------------------------------------ | ------------------------------------------------------------------------ |
| Cluster traffic on one network only  | Keep `ring0_addr`; remove `ring1_addr` and `interface { linknumber: 1 }` |
| Use the old ring1 network as primary | Set `ring0_addr` to that IP on every node; remove ring1 entirely         |
| Redundancy across two networks       | Keep both links (current dual-link setup)                                |

Every node in `nodelist` must be updated consistently, and `config_version` must increase.

---

### How do I remove a corosync link (ring1)?

Remove **three** things on **every** node entry and in `totem`:

1. Each `ring1_addr: …` line in `nodelist`
2. The entire `interface { linknumber: 1 }` block under `totem`
3. Bump `config_version`

Example result (single link):

```text
nodelist {
  node {
    name: pvenode-001
    nodeid: 1
    quorum_votes: 1
    ring0_addr: 10.0.0.11
  }
}

totem {
  cluster_name: my-cluster
  config_version: 4
  interface {
    linknumber: 0
  }
  …
}
```

Verify:

```bash
grep -E 'ring1|linknumber: 1' /etc/pve/corosync.conf   # must print nothing
corosync-cfgtool -s                                       # only LINK ID 0
```

Then **regenerate Join Information** in the GUI (Datacenter → Cluster). Old encoded join blobs still reflect the previous link count.

> [!NOTE]
> `corosync-cfgtool -s` may show only link 0 active while `/etc/pve/corosync.conf` still declares link 1. Join requests are built from the **config file**, not from active link status alone.

---

### Join wizard still asks for Link 1 after I removed ring1

The cluster config still defines two links. Common causes:

| Cause                                                                    | Fix                                                        |
| ------------------------------------------------------------------------ | ---------------------------------------------------------- |
| `interface { linknumber: 1 }` left in `totem`                            | Remove the block; bump `config_version`                    |
| `ring1_addr` still in `nodelist`                                         | Remove from all nodes                                      |
| `config_version` not incremented                                         | Increase it in `totem`                                     |
| Edited `/etc/corosync/corosync.conf` instead of `/etc/pve/corosync.conf` | Edit the cluster file under `/etc/pve/`                    |
| Stale join information pasted in GUI                                     | Copy fresh join info from an existing member after the fix |

Workaround until fixed: provide **both** link IPs on the joining node (`--link0` and `--link1`) if the cluster still expects two networks.

---

### Join fails: “cannot use IP 'X.X.X.X', not found on local node!”

The **Link 0** dropdown must be an IP **assigned to the joining node**, not the peer.

| Field               | Which host                      | Example     |
| ------------------- | ------------------------------- | ----------- |
| Peer address        | Existing cluster member         | `10.0.0.11` |
| Link 0 (local)      | **This** node (the one joining) | `10.0.0.12` |
| Peer’s link address | Shown by GUI                    | `10.0.0.11` |

On the **joining** node:

```bash
ip -4 addr show vmbr0
ping -c 2 <PEER_RING0_IP>
pvecm add <PEER_IP> --link0 <THIS_NODE_RING0_IP>
```

If the local IP is missing, configure it in `/etc/network/interfaces` (or System → Network), apply, then retry join.

---

### How do I verify communication between cluster nodes?

Run on any member (or from your workstation using `./deploy/proxmox.sh`).

**Quorum and membership**

```bash
pvecm status
pvecm nodes
```

Healthy: `Quorate: Yes`; all expected nodes listed.

**Corosync links**

```bash
corosync-cfgtool -s
```

Healthy: link 0 shows all node IDs as `connected` (not only `localhost`).

**Layer-3 reachability** (use each node’s `ring0_addr` from corosync):

```bash
ping -c 4 <PEER_RING0_IP>
```

**Services and API**

```bash
systemctl is-active corosync pve-cluster
pvesh get /cluster/resources --type node --output-format json
journalctl -u corosync -n 50 --no-pager
```

**pmxcfs sync** (config replicates via cluster filesystem):

```bash
# On node A
touch /etc/pve/test-sync-$(hostname)
# On node B
ls /etc/pve/test-sync-*
rm /etc/pve/test-sync-*
```

**From this repo’s workstation**

```bash
./deploy/proxmox.sh cluster-nodes --ip-address <ANY_MEMBER_IP>
./deploy/proxmox.sh get-temp --ip-address <ANY_MEMBER_IP>
```

`get-temp` SSHs to each member via `ring0_addr` — useful end-to-end check.

**Quick health one-liner**

```bash
pvecm status && echo && pvecm nodes && echo && corosync-cfgtool -s
```

| Symptom                                   | Likely cause                                                                     |
| ----------------------------------------- | -------------------------------------------------------------------------------- |
| Not quorate                               | Node down, firewall blocking corosync, wrong `ring0_addr`                        |
| Link shows only `localhost`               | Peer offline or UDP blocked between ring0 IPs                                    |
| Quorate but node red in GUI               | `pve-cluster` / `pveproxy` issue on that host                                    |
| `/etc/pve/corosync.conf` differs per node | Corosync/pmxcfs split — fix links before editing cluster config on one node only |

---

### Quorum, QDevice, TrueNAS NFS, and HA (Path B)

This lab runs a **3-node** cluster (`pvenode-001` … `003`) on LAN `172.16.0.0/16`. Default quorum is **2 of 3** (one node may be offline). To stay quorate with **two nodes deliberately offline** (or to prepare for a 4th node later), use a **QDevice** tie-breaker plus **HA fencing** before shared-storage HA.

| Component    | Lab default                                                       | Role                                                        |
| ------------ | ----------------------------------------------------------------- | ----------------------------------------------------------- |
| QDevice host | `172.16.0.102` (`deploy/setup/misc/cluster/default.qdevice.host`) | Runs `corosync-qnetd` — **not** a PVE node, **not** TrueNAS |
| TrueNAS NFS  | `172.16.0.100` (`default.truenas.nfs.env`)                        | Shared storage for HA VMs (`truenas-nfs` storage ID)        |
| PVE nodes    | `corosync-qdevice` + `softdog`                                    | QDevice client + watchdog fencing                           |

**Quorum math (3 PVE + QDevice):** 4 votes total → quorum **3** → cluster stays quorate with **2 PVE nodes + QDevice**.

#### One-time: QDevice server

On a **small Debian/Ubuntu VM** at the IP in `default.qdevice.host` (edit the file if you use another host):

```bash
# Copy qdevice-server-bootstrap.sh to that host, then:
bash qdevice-server-bootstrap.sh
```

Or from the repo checkout on the QDevice host:

```bash
bash deploy/setup/misc/cluster/qdevice-server-bootstrap.sh
```

#### Per-node: QDevice client + watchdog (step 18)

During `setup-pve-node.sh` **step 18**, or manually on each PVE node:

```bash
bash /root/deploy/misc/cluster/papita-node-qdevice-client.sh
```

Installs `corosync-qdevice` and loads **softdog** (`/dev/watchdog*`) for HA fencing.

#### Cluster-wide: QDevice + NFS + HA group

1. Edit `deploy/setup/misc/cluster/default.truenas.nfs.env` — set `TRUENAS_NFS_EXPORT` to your TrueNAS NFS path (TrueNAS **Sharing → NFS** on `172.16.0.100`).
2. Ensure the NFS export allows all PVE node LAN IPs.
3. From your workstation (main node LAN IP):

```bash
./deploy/proxmox.sh setup-cluster-ha --ip-address 172.16.0.101
```

This deploys `misc/cluster/`, runs the node client on **every online member**, then on the entry host:

- Adds cluster firewall allow for TrueNAS (if `cluster.fw` exists)
- `pvesm add nfs truenas-nfs` → `172.16.0.100`
- `pvecm qdevice setup <QDEVICE_IP>`
- `ha-manager add group papita-ha` with all cluster nodes

#### Add a VM to HA

Storage must be on **`truenas-nfs`** (or another shared store). Then:

```bash
ha-manager add vm:<VMID> --group papita-ha --state started
ha-manager status
```

#### Verification

```bash
pvecm status
corosync-quorumtool -s
pvesm status -storage truenas-nfs
ha-manager status
ha-manager crm-command status
```

Healthy QDevice: `pvecm status` lists Qdevice votes; with two PVE nodes online, `Quorate: Yes`.

#### Rollback

```bash
ha-manager remove vm:<VMID>    # per resource
ha-manager remove group papita-ha
pvesm remove truenas-nfs
pvecm qdevice remove
```

> [!WARNING]
> Do **not** use TrueNAS (`172.16.0.100`) as the QDevice host. Do **not** leave `pvecm expected 1` as a permanent quorum workaround. Enable **softdog on all nodes before** adding HA resources.

---

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

## Fedora VM — shared clipboard on Proxmox VE

Copy/paste between your workstation and a Fedora desktop VM requires a **guest agent** inside the VM and the correct **display / clipboard** settings on the Proxmox host. Clipboard sharing only works through a **graphical session** (GNOME, KDE, etc.) — not through the serial / xterm.js console.

There are two practical approaches:

| Approach      | Console                                        | Best for                                                                                  |
| ------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------- |
| **A — noVNC** | Proxmox web UI → Console → noVNC               | Quick access without installing a client; clipboard button appears in the noVNC toolbar   |
| **B — SPICE** | Proxmox web UI → Console → SPICE → Virt-Viewer | Daily use: smoother video, auto-resize, USB redirection, reliable bidirectional clipboard |

Both paths use the same Fedora guest packages. Pick one clipboard backend on the host — do not mix SPICE clipboard with `clipboard=vnc` unless you intend to replace the default SPICE clipboard ([PVE admin guide — Display](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#qm_display)).

**References:**

- [Proxmox VE — SPICE wiki](https://pve.proxmox.com/wiki/SPICE)
- [Proxmox VE admin guide — Display / VNC clipboard](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#qm_display)
- [Fedora — spice-vdagent package](https://packages.fedoraproject.org/pkgs/spice-vdagent/spice-vdagent/)
- [GNOME Boxes — guest tools (spice-vdagent)](https://help.gnome.org/gnome-boxes/install-guest-tools.html)

### Step 1 — Install guest agents in the Fedora VM

On the **Fedora guest** (Workstation or KDE Spin), install the QEMU guest agent and SPICE vdagent:

```bash
sudo dnf install -y qemu-guest-agent spice-vdagent
sudo systemctl enable --now qemu-guest-agent spice-vdagentd
```

`spice-vdagent` has two parts:

- **`spice-vdagentd`** — system daemon (socket-activated; enable with the command above).
- **`spice-vdagent`** — per-session agent; starts automatically on GNOME/KDE via `/etc/xdg/autostart/spice-vdagent.desktop` after you log into a graphical desktop.

Verify both are running **after logging in** (not at the GDM login screen):

```bash
systemctl is-active qemu-guest-agent spice-vdagentd
pgrep -a spice-vdagent    # expect /usr/bin/spice-vdagent in your user session
```

Reboot the VM once after the first install:

```bash
sudo reboot
```

> [!NOTE]
> On **Fedora 43+**, `spice-vdagent` ≥ 0.23.0 fixes GNOME autostart issues ([RHBZ#2394505](https://bugzilla.redhat.com/show_bug.cgi?id=2394505)). On older releases, if clipboard still fails under GNOME, update the package or log out and back in after install.

### Step 2A — noVNC clipboard (web console only)

Use this when you want copy/paste from the **built-in Proxmox noVNC panel** without Virt-Viewer.

1. On a **PVE node shell**, enable the VNC clipboard for the VM (replace `101` with your VMID):

   ```bash
   # Works with default VGA; virtio or qxl are also fine
   qm set 101 -vga virtio,clipboard=vnc
   ```

   You can use the default display type instead of `virtio`:

   ```bash
   qm set 101 -vga std,clipboard=vnc
   ```

2. **Shut down and cold-start** the VM (or reboot from inside the guest) so QEMU picks up the new `qemu-vdagent` device.

3. Open **VM → Console → noVNC** in the Proxmox web UI.

4. Use the **clipboard icon** in the noVNC toolbar to paste text from your browser session into the VM (and copy out where supported).

> [!WARNING]
> **Live migration:** VMs with `clipboard=vnc` use the `qemu-vdagent` device. Live migration is only supported when the VM runs **QEMU machine version ≥ 10.1** ([admin guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#qm_display)). Check **VM → Options → QEMU version** before migrating.

### Step 2B — SPICE clipboard (Virt-Viewer — recommended)

Use this for the most reliable bidirectional clipboard and better desktop integration.

#### On the Proxmox host (VM hardware)

1. **VM → Hardware → Display → Edit**
   - **Graphic card:** `SPICE` (QXL) — default recommendation; or `SPICE (virtio-vga)` if QXL misbehaves on your desktop environment.
   - **Memory:** at least **32 MiB** for high resolutions ([SPICE wiki](https://pve.proxmox.com/wiki/SPICE)).
2. **Do not** set `clipboard=vnc` if you want the native SPICE clipboard — leave the clipboard option empty so Proxmox adds the SPICE vdagent channel automatically.
3. Optional: **VM → Hardware → Add → USB Device → SPICE Port** for USB redirection from Virt-Viewer.
4. Shut down and cold-start the VM.

CLI equivalent:

```bash
qm set 101 -vga qxl
# Do NOT add clipboard=vnc for SPICE-native clipboard
```

#### On your workstation

1. Install **Virt-Viewer** (package `virt-viewer`; provides `remote-viewer`).
2. In Proxmox: **VM → Console → SPICE** → download the `.vv` file → open with Virt-Viewer.
3. In Virt-Viewer: **Edit → Preferences** → ensure clipboard sharing is enabled (on by default).

If clipboard is still one-way, launch explicitly:

```bash
remote-viewer --spice-clipboard=on /path/to/downloaded.vv
```

### Step 3 — Verify clipboard end-to-end

| Check                  | Command / action                                      | Expected                                      |
| ---------------------- | ----------------------------------------------------- | --------------------------------------------- |
| Guest agents installed | `rpm -q qemu-guest-agent spice-vdagent`               | Both packages listed                          |
| Daemon running         | `systemctl is-active spice-vdagentd qemu-guest-agent` | `active`                                      |
| Session agent running  | `pgrep -a spice-vdagent`                              | Process owned by your desktop user            |
| Host → guest           | Copy text on workstation, paste in VM terminal/editor | Text appears                                  |
| Guest → host           | Copy text in VM, paste on workstation                 | Text appears                                  |
| noVNC only             | Clipboard toolbar button visible                      | Button present after `clipboard=vnc` + reboot |

Test with a **logged-in desktop session** (e.g. `gedit`, `kate`, or a terminal) — not at the login greeter.

### Wayland vs X11 on Fedora (common pitfall)

`spice-vdagent` integrates with the **X11 clipboard**. Fedora Workstation defaults to **Wayland** (GNOME) or **Wayland** (KDE Plasma 6).

| Guest session                           | Clipboard behaviour                                                        |
| --------------------------------------- | -------------------------------------------------------------------------- |
| **X11** (e.g. “GNOME on Xorg” at login) | Generally works with SPICE / noVNC + vdagent                               |
| **Wayland** (default on current Fedora) | Often **host → guest** works; **guest → host** may fail or be inconsistent |

**Workarounds (try in order):**

1. **Log in to an X11 session** — at GDM/SDDM, choose _GNOME on Xorg_ (or the X11 Plasma session) and retest.
2. **Update `spice-vdagent`** — Fedora 43+ ships fixes for GNOME autostart; `sudo dnf upgrade spice-vdagent`.
3. **KDE Klipper** — if using KDE, temporarily disable Klipper; it can intercept clipboard sync ([Proxmox forum — Debian KDE](https://forum.proxmox.com/threads/spice-clipboard-not-working-for-debian-12-kde-vm.163219/)).
4. **Switch display adapter** — if QXL + SPICE misbehaves, try **virtio-vga** instead of QXL in **VM → Hardware → Display**.
5. **Wayland bridge (advanced)** — third-party bridges such as [wayland-spice-clipboard-fix](https://github.com/chrisbelson/wayland-spice-clipboard-fix) forward Wayland clipboard → X11 for vdagent; only needed when you must stay on Wayland.

### Quick troubleshooting

| Symptom                                  | Likely cause                               | Fix                                                                     |
| ---------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------- |
| No clipboard button in noVNC             | `clipboard=vnc` not set or VM not rebooted | `qm set <vmid> -vga <type>,clipboard=vnc`; cold-start VM                |
| Clipboard button present but paste fails | `spice-vdagent` missing or no GUI session  | Install packages (Step 1); log into desktop, not serial console         |
| SPICE connects but no clipboard          | Session agent not running                  | `pgrep spice-vdagent`; log out/in; on GNOME try Xorg session            |
| One-way clipboard (in only)              | Wayland guest session                      | Log in with _GNOME on Xorg_ or apply Wayland bridge                     |
| Guest → host broken on KDE               | Klipper interference                       | Disable Klipper; retry                                                  |
| Black screen with SPICE                  | Display not set to SPICE or VM off         | **Hardware → Display → SPICE**; boot VM                                 |
| Resolution does not auto-resize          | vdagent not running or low video memory    | Fix vdagent; increase Display memory (e.g. 32 MiB)                      |
| Live migrate fails after noVNC clipboard | `qemu-vdagent` on old machine type         | Upgrade QEMU machine version to ≥ 10.1 or remove `clipboard=vnc`        |
| Mouse offset / no absolute pointer       | USB tablet disabled                        | Ensure **VM → Options → USB Tablet** is enabled (default for SPICE/QXL) |

---

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

This lab uses Tailscale CGNAT space `100.64.0.0/10` on **all** PVE nodes (AWS EFS data plane). pfSense joins the same tailnet as a **subnet router**, advertising **172.16.0.0/16** (gateway **172.16.0.1**). Remote **admin** access uses the **main node** (default **172.16.0.101**) via pfSense subnet route and/or MagicDNS — worker nodes do not advertise routes. Site-to-site requires **both** Tailscale ACL grants **and** pfSense/NAT rules.

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
> Lab PVE nodes use tags from `deploy/setup/misc/tailscale/default.tags.list`: `tag:private-node`, `tag:pve-oldtimers-cluster`, `tag:server-node`. Define matching `tagOwners` entries for each tag your nodes use.

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
   - **Advertised Routes:** add `172.16.0.0/16` (this lab's LAN; gateway **172.16.0.1**)
   - **Save**
2. Tailscale admin → pfSense node → **⋯ → Edit route settings** → approve each **Subnet route**
3. Or run `./deploy/tailscale-pfsense-lan.sh approve-routes` / `configure` from the repo root
4. Test from a permitted tailnet device: `ping 172.16.0.101`

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
export LAN_CIDR='172.16.0.0/16'
export MAIN_PVE_LAN_IP='172.16.0.101'
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
      "dst": ["172.16.0.0/16"],
      "ip": ["*"]
    },
    {
      "src": ["tag:auth-client"],
      "dst": ["172.16.0.0/16"],
      "ip": ["*"]
    },
    {
      "src": ["tag:pfsense-oldtimers-client"],
      "dst": ["172.16.0.0/16"],
      "ip": ["*"]
    },
    {
      "src": ["tag:private-node"],
      "dst": ["172.16.0.101/32"],
      "ip": ["tcp:8006", "tcp:22"]
    },
    {
      "src": ["tag:server-node"],
      "dst": ["172.16.0.101/32"],
      "ip": ["tcp:443", "tcp:8006", "tcp:22"]
    }
  ]
}
```

**Example B — Allow PVE cluster tag ↔ pfSense LAN (bidirectional site-to-site)**

PVE and pfSense share **172.16.0.0/16** in this lab.

```json
{
  "grants": [
    {
      "src": ["tag:pve-oldtimers-cluster"],
      "dst": ["172.16.0.0/16"],
      "ip": ["*"]
    },
    {
      "src": ["172.16.0.0/16"],
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
      "dst": ["172.16.0.0/16"],
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
    "pfsense-lan": "172.16.0.0/16"
  },
  "grants": [
    {
      "src": ["admin-laptop"],
      "dst": ["172.16.0.0/16"],
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
      "dst": ["172.16.0.0/16"],
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
    "tag:pfsense-lan-router": ["172.16.0.0/16"],
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
| Source      | `172.16.0.0/16` (LAN net or alias)                                      |
| Destination | Any                                                                     |
| Translation | Interface address (or pfSense Tailscale IP `/32` if alias UI is broken) |

**B. Tailscale interface — `AUTH_CLIENTS` access (lab agreed layout)**

Use the Tailscale package alias **`AUTH_CLIENTS`** (authorized tailnet peers) as **Source**, not the full `100.64.0.0/10` range. **Primary enforcement for subnet routes remains Tailscale ACLs**; these rules are admin access + defense in depth ([Netgate forum](https://forum.netgate.com/topic/190879/tailscale-subnet-routes-exit-nodes-pfsense-firewall-rules)).

**Apply via API** (requires firewall write privileges on the API user):

```bash
./deploy/pfsense-firewall-tailscale.sh apply          # live apply + POST /firewall/apply
./deploy/pfsense-firewall-tailscale.sh apply --dry-run
```

**Firewall → Rules → Tailscale** (top to bottom):

| #   | Action | Protocol  | Source         | Destination         | Port    | Description                                                       |
| --- | ------ | --------- | -------------- | ------------------- | ------- | ----------------------------------------------------------------- |
| 1   | Pass   | TCP       | `AUTH_CLIENTS` | **This firewall**   | 22, 443 | Admin → pfSense (SSH, WebGUI, pfREST); omit 80 unless HTTP needed |
| 2   | Pass   | TCP/UDP\* | `AUTH_CLIENTS` | **`172.16.0.1/32`** | \*      | Admin → pfSense **LAN IP** (subnet route / local gateway)         |
| 3   | Pass   | IPv4 \*   | `AUTH_CLIENTS` | **`172.16.0.0/16`** | \*      | Tailnet → lab LAN (keep; do not replace with a block)             |
| 4   | Block  | IPv4 \*   | any            | any                 | \*      | Optional explicit deny below passes                               |

\* Rule 2: use **TCP 22,443** (and ICMP if you ping the gateway) instead of `*` if you want tighter scope. Rule 3 must **remain** — it covers the rest of the LAN behind pfSense.

> **Do not remove** rules 2–3 when merging admin passes: tailnet clients need **`172.16.0.1`** (pfSense LAN gateway, WebGUI, pfREST) **and** **`172.16.0.0/16`** (PVE and other LAN hosts). Rule 1 covers `(self)` on the Tailscale interface; rule 2 documents **LAN IP** access when traffic arrives via the advertised subnet route.

Create alias **Firewall → Aliases** (optional hardening):

- `TAILNET_ALLOWED` — type **Network(s)**: individual `/32` Tailscale IPs when ACLs allow only specific machines (mirrors ACL `hosts`)
- `TAILNET_CGNAT` — `100.64.0.0/10` (reference only; prefer `AUTH_CLIENTS` on pfSense rules)

For **tag-scoped access**, pfSense cannot read Tailscale tags — maintain **`TAILNET_ALLOWED`** listing **100.x** addresses of ACL-permitted machines if you replace `AUTH_CLIENTS` with a manual alias.

**C. LAN interface — LAN → tailnet (optional; usually skip in this lab)**

PVE nodes run Tailscale directly; they reach `100.x` peers without pfSense forwarding. **Do not add** a broad `LAN net → 100.64.0.0/10` pass unless a **LAN-only host without Tailscale** must reach tailnet **via pfSense** — that rule widens blast radius (any compromised LAN host could probe the CGNAT space).

Return traffic for sessions **started from tailnet → LAN** is handled by **stateful firewall** — no LAN rule required for replies.

If you truly need pfSense-routed LAN → tailnet, prefer a narrow destination alias:

**Firewall → Rules → LAN** (only when required):

| #   | Action | Protocol | Source    | Destination       | Port | Description                  |
| --- | ------ | -------- | --------- | ----------------- | ---- | ---------------------------- |
| 1   | Pass   | IPv4 \*  | `LAN net` | `TAILNET_ALLOWED` | \*   | Specific tailnet `/32`s only |

**Skip** the permissive `LAN net → 100.64.0.0/10` rule in the default lab layout.

**D. Optional — restrict LAN services by source tailnet IP**

If a LAN VM must accept traffic **only** from specific tailnet machines (e.g. Proxmox :8006):

| Action | Source            | Destination               | Port         |
| ------ | ----------------- | ------------------------- | ------------ |
| Pass   | `TAILNET_ALLOWED` | `172.16.0.101` (main PVE) | TCP 8006, 22 |
| Block  | `100.64.0.0/10`   | `<worker PVE LAN IP>`     | TCP 8006     |

Place **Pass** before **Block**. Match ACL grants: if ACL allows only `tag:private-node` machines, list those nodes' 100.x IPs in `TAILNET_ALLOWED`.

##### Layer 3 — PVE side (this lab)

Hybrid topology (`setup-pve-node.sh`):

1. **All nodes:** steps 8–9 — Tailscale client + tags (EFS over tailnet)
2. **Workers:** answer **n** at 9.0 — no `--advertise-routes` (pfSense advertises `172.16.0.0/16`)
3. **Main node:** 9.0 **y**, step 10.2 → `/etc/default/pve-main-node`, step 17 Tailscale TLS for `:8006`
4. Enable step 14 cluster firewall only after confirming Tailscale/management access
5. Do **not** dual-advertise `172.16.0.0/16` from pfSense and a PVE node

##### Access matrix (example for this lab)

| Source                        | Destination                 | Enforced by                 | pfSense rule (optional mirror)                   |
| ----------------------------- | --------------------------- | --------------------------- | ------------------------------------------------ |
| `tag:private-node`            | `172.16.0.0/16`             | Tailscale grant             | Tailscale → LAN pass (100.x in alias)            |
| `tag:private-node`            | `172.16.0.101:8006,22`      | Tailscale grant             | TAILNET_ALLOWED → main PVE                       |
| `tag:pve-oldtimers-cluster`   | `172.16.0.0/16`             | Tailscale grant             | Same                                             |
| `tag:server-node`             | `172.16.0.101:443,8006,22`  | Tailscale grant (main only) | LAN rule to main host ports only                 |
| `admin-laptop` (`100.64.x.x`) | `172.16.0.0/16`             | Tailscale grant + `hosts`   | `AUTH_CLIENTS` → LAN (rule 3)                    |
| `admin-laptop` (`100.64.x.x`) | `172.16.0.1` (pfSense LAN)  | Tailscale grant + pfSense   | `AUTH_CLIENTS` → `172.16.0.1/32` + This firewall |
| `172.16.0.0/16`               | `tag:pve-oldtimers-cluster` | Tailscale grant (return)    | PVE uses own Tailscale — skip LAN→tailnet rule   |
| Worker 100.x (direct)         | Any                         | **Denied** (no grant)       | N/A — workers not exposed on tailnet             |
| Any other tailnet member      | `172.16.0.0/16`             | **Denied** (no grant)       | Block or omit pass rule                          |

#### 9.7 — Optional: Split DNS for internal hostnames

In [Tailscale admin → DNS](https://login.tailscale.com/admin/dns):

1. **Add nameserver → Custom** → pfSense LAN IP (`172.16.0.1`)
2. **Restrict to domain** (Split DNS) with your internal suffix
3. Remote clients resolve internal hostnames only if ACLs allow them to reach pfSense DNS (`udp/tcp:53`)

#### 9.8 — Verify ACL + firewall alignment

1. **Tailscale admin → Access controls → Tests** — add test cases for each tag → LAN grant
2. From a machine in `tag:private-node`: `ping 172.16.0.101` → expect success
3. From an **untagged** or **unauthorized** machine: same ping → expect failure
4. `./deploy/tailscale-pfsense-lan.sh verify` — ping + HTTPS `:8006` to main node
5. **pfSense → Status → System Logs → Firewall** — confirm pass/block on Tailscale and LAN tabs
6. **Status → Gateways** — WAN only; no LAN upstream gateway

---

### Step 10 — Verify end-to-end connectivity

| Check                      | Command / location                                     |
| -------------------------- | ------------------------------------------------------ |
| LAN clients reach pfSense  | `ping 172.16.0.1` from a VM on LAN bridge              |
| LAN clients reach internet | `ping 1.1.1.1` / browse from LAN VM                    |
| pfSense on tailnet         | Tailscale admin shows pfSense **Connected**            |
| Subnet route approved      | Admin → Edit route settings → `172.16.0.0/16` checked  |
| Remote → main PVE LAN      | `ping 172.16.0.101` from tailnet laptop                |
| Remote → Proxmox UI (LAN)  | `https://172.16.0.101:8006` via pfSense subnet route   |
| Remote → Proxmox UI (TS)   | `https://<main-magicdns>:8006` after step 17 on main   |
| ACL tag → LAN              | Access controls → Tests; ping from tagged node only    |
| Unauthorized denied        | Same ping from non-granted machine fails               |
| EFS from each PVE node     | On each node: `tailscale status`; mount/test EFS NFS   |
| Toolkit cluster ops        | `./deploy/proxmox.sh -ip 172.16.0.101 get-temp`        |
| No LAN gateway mistake     | **Status → Gateways** — only WAN gateway; LAN has none |
| Interface types correct    | **Status → Interfaces** — LAN has no gateway field     |

---

### Quick troubleshooting

| Symptom                                                             | Likely cause                                                             | Fix                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LAN clients no internet                                             | WAN down, DNS, or removed default LAN allow rule                         | Check **Status → Gateways**; restore LAN outbound rule                                                                                                                                                                                  |
| LAN clients cannot reach pfSense IP                                 | Wrong subnet, bridge, or IP conflict                                     | Verify VM IP/gateway; pfSense LAN IP must be unique on segment                                                                                                                                                                          |
| `LANGW` gateway down                                                | Upstream gateway set on LAN                                              | Remove gateway from **Interfaces → LAN**                                                                                                                                                                                                |
| Tailnet cannot reach LAN VMs                                        | Subnet route not approved, missing ACL grant, or missing pfSense NAT     | Approve `172.16.0.0/16`; run `./deploy/tailscale-pfsense-lan.sh configure`; Hybrid NAT LAN→Tailscale                                                                                                                                    |
| Authorized tag still blocked                                        | ACL grant missing port or wrong CIDR                                     | Check Access controls → Tests; match `172.16.0.0/16` to pfSense advertised route                                                                                                                                                        |
| Unauthorized machine reaches LAN                                    | Overly broad ACL or pfSense pass rule for full `100.64.0.0/10`           | Remove broad grant; use tag-scoped grants + `TAILNET_ALLOWED` alias                                                                                                                                                                     |
| PVE `cluster.fw` parse error `-log n`                               | Invalid log token from older setup script                                | Change to `-log nolog`; run `pve-firewall restart`                                                                                                                                                                                      |
| PVE node lost internet after step 14                                | Cluster firewall enabled without `policy_out: ACCEPT` / `OUT ACCEPT`     | Add `policy_out: ACCEPT` under `[OPTIONS]` and `OUT ACCEPT -log nolog` under `[RULES]`, or set `enable: 0` temporarily                                                                                                                  |
| PVE nodes cannot ping on 172.16.x                                   | Wrong default gateway on dual-homed node (e.g. 192.168.x not 172.16.0.1) | Put `gateway 172.16.0.1` on the 172.16 bridge; verify L2 on same VLAN                                                                                                                                                                   |
| Perl `Setting locale failed` / `LC_CTYPE=UTF-8`                     | SSH client (macOS/Cursor) sends invalid `LC_CTYPE=UTF-8`                 | Node: `locale-gen en_US.UTF-8`; `update-locale LANG=en_US.UTF-8 LC_CTYPE=en_US.UTF-8`; sshd `AcceptEnv LANG LANGUAGE LC_PVE_TICKET` (not `LC_*`); ssh `SendEnv LC_PVE_TICKET`; Mac: `SendEnv -LC_CTYPE` in `~/.ssh/config`              |
| noVNC “Failed to connect” / `Failed to run vncproxy` on remote node | `LC_PVE_TICKET` stripped from inter-node SSH (custom `sshd_config`)      | On **all** cluster nodes: `AcceptEnv LANG LANGUAGE LC_PVE_TICKET` in `/etc/ssh/sshd_config` and `SendEnv LC_PVE_TICKET` in `/etc/ssh/ssh_config`; `systemctl reload ssh`; test: `LC_PVE_TICKET=foo ssh peer-node 'echo $LC_PVE_TICKET'` |
| WAN WebGUI unreachable                                              | Default WAN block (expected)                                             | Access via LAN IP or add controlled WAN allow rule                                                                                                                                                                                      |
| WAN/LAN same subnet                                                 | Overlapping ranges                                                       | Re-number LAN to non-overlapping RFC1918 range                                                                                                                                                                                          |

---

## TrueNAS Scale — storage pools, Scrutiny, and Uptime Kuma

This section covers **TrueNAS Scale** storage pool behaviour, the **Scrutiny** SMART app, and **Uptime Kuma** monitoring for a homelab with **pfSense** and a **3-node Proxmox VE** cluster (`pvenode-001` … `003`, LAN `172.16.0.0/16`, gateway `172.16.0.1`).

**References:**

- [TrueNAS Scale docs](https://www.truenas.com/docs/scale/)
- [Scrutiny (GitHub)](https://github.com/AnalogJ/scrutiny)
- [Scrutiny TrueNAS app catalog](https://apps.truenas.com/catalog/scrutiny_community/)
- [Uptime Kuma (GitHub)](https://github.com/louislam/uptime-kuma)
- [TrueNAS 25.10 SMART changes](https://forums.truenas.com/t/smart-monitoring-functionality-missing-after-latest-update-25-10-rc/55206)

---

### ZFS pools — what is possible

| Scenario                                          | Possible?                        | Notes                                                                                           |
| ------------------------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------- |
| Create pool on a **partition** (CLI)              | Yes                              | `zpool create pool /dev/disk/by-partuuid/...` works at the ZFS level                            |
| Create pool on a **partition** (GUI)              | No (practical)                   | GUI uses **whole disks**; TrueNAS partitions them internally (swap + ZFS)                       |
| **Mixed drive sizes in one vdev** (today)         | Not recommended / blocked in GUI | Vdev capacity = **smallest disk**; GUI may require **Force**                                    |
| **Mixed sizes across separate vdevs** in one pool | Yes                              | e.g. RAIDZ2 on 3 TB drives + another RAIDZ2 on 8 TB drives                                      |
| **AnyRaid** (mixed sizes, full capacity per disk) | **TrueNAS 26** / OpenZFS 2.4     | Requires upgrade + `zpool upgrade`; **not reversible** to older ZFS                             |
| **RAIDZ expansion** (add disk to RAIDZ vdev)      | Yes (24.10+)                     | Add one disk at a time; slow; some parity headroom until rewrite                                |
| **Remove disk from RAIDZ vdev**                   | No                               | Replace disks or destroy pool                                                                   |
| **Remove disk from mirror vdev**                  | Yes                              | `zpool detach` one mirror leg                                                                   |
| **Remove spare / cache / log device**             | Yes                              | Detach via GUI or CLI                                                                           |
| **Replace with larger disks**                     | Yes                              | Replace one-by-one, resilver; pool grows when **all** disks in vdev are upgraded (`autoexpand`) |
| **Pools not in `zpool list`**                     | Expected                         | Exported/foreign pools — use `zpool import`                                                     |
| **Factory reset / wipe all disks**                | Yes                              | Export/destroy pools first, then per-disk wipe                                                  |

**Is mixed-size in one vdev worth it today?** Usually **no** — capacity is capped by the smallest disk. Prefer separate vdevs or wait for **AnyRaid** on TrueNAS 26 if you need heterogeneous drives in one vdev.

**Partition-based pools on TrueNAS:** Avoid unless you accept CLI-only management; the supported path is **whole disks** in the GUI.

---

### Remove disks from pools

Depends on how the disk is used in ZFS:

| Role                     | Action                                                                     |
| ------------------------ | -------------------------------------------------------------------------- |
| **Spare**                | GUI: pool status → Remove/Detach; CLI: `zpool remove <pool> <disk-by-id>`  |
| **Mirror leg**           | `zpool detach <pool> <disk-by-id>` — shrinks mirror to single disk         |
| **RAIDZ / dRAID member** | **Cannot remove** one disk; replace failed disk or add vdev / destroy pool |
| **L2ARC / SLOG**         | Detach/remove via pool device management                                   |
| **Boot pool**            | Separate from data pools — do not treat as data pool disk                  |

Always **back up** before structural changes.

---

### Factory reset disks (remove from all pools)

**System → General → Reset to Defaults** resets **settings only** — it does **not** wipe data pools.

1. **Back up** data and export encryption keys if used.
2. For **each pool**: **Storage → Pools → ⋮ → Export/Disconnect** with **Destroy data on this pool** enabled.
3. Wipe leftover metadata per disk:

```bash
# Find disks
lsblk
zpool import   # should show nothing for wiped disks

# Wipe partition tables (replace sdX with correct disk — NOT the boot disk)
wipefs -a /dev/sdX
sgdisk --zap-all /dev/sdX
```

If `wipefs: Device or resource busy`: something still has the disk open — export/destroy the pool first, unmount partitions, or reboot.

---

### Pools not shown in `zpool list`

`zpool list` shows only **imported** pools.

```bash
zpool import              # pools on disk but not loaded
zpool import -d /dev/disk/by-id
zpool import -v
```

If a pool appears in `zpool import` but not in `zpool list`, it is **on disk but not imported**. Use **Storage → Import Pool** in the GUI or `zpool import <poolname>`.

To clear stale labels after export: `wipefs -a` / `sgdisk --zap-all` on the disk (see above).

---

### Monitoring stack — what to install

| Layer                   | Tool                                  | Purpose                                   |
| ----------------------- | ------------------------------------- | ----------------------------------------- |
| Built-in                | **Reporting**, **Alerts**, SMART cron | Baseline CPU/memory/network/pool I/O      |
| Disk health             | **Scrutiny** app                      | SMART history, trends, failure thresholds |
| Uptime / services       | **Uptime Kuma** app                   | HTTP/TCP/DNS checks, Telegram alerts      |
| Deep metrics (optional) | InfluxDB + Grafana + Telegraf         | Long-term graphs; heavier                 |

**Minimal recommended stack:**

```
Built-in Reporting + Alerts + SMART cron
  + Scrutiny (disk history)
  + Uptime Kuma (services/uptime)
```

Avoid installing Netdata + Beszel + Grafana + Glances together on the NAS — redundant RAM use.

**TrueNAS 25.10+:** built-in SMART scheduling UI was removed; use **Data Protection → Periodic SMART Tests** (cron) and **Scrutiny** for visualization.

---

### Scrutiny — TrueNAS app install checklist

Requires **TrueNAS Scale ≥ 24.10.2.2**. App version: **v0.9.2-omnibus** (web + collector + embedded InfluxDB).

#### Prerequisites

1. **Apps → Settings** — configure an **apps pool/dataset**.
2. List disks on the shell:

```bash
smartctl --scan
# Example output:
# /dev/sda -d scsi
# /dev/nvme0 -d nvme
```

#### Install wizard

| Section                | Setting             | Value                                                   |
| ---------------------- | ------------------- | ------------------------------------------------------- |
| **Disks**              | Host Disk Path      | `/dev/sda`, `/dev/sdb`, `/dev/nvme0`, …                 |
| **Disks**              | Container Disk Path | **Same as host** (e.g. `/dev/sda` → `/dev/sda`)         |
| **Disks**              | Elevate Privileges  | **Enabled** (required for **NVMe** SMART/temp)          |
| **Network → WebUI**    | Bind Mode           | **Published**                                           |
| **Network → WebUI**    | Port                | `31054` (default) or any free port                      |
| **Network → WebUI**    | Host IPs            | Empty (= all interfaces)                                |
| **Network → InfluxDB** | Bind Mode           | **None** or **Expose only** (no LAN access needed)      |
| **Storage**            | Config + InfluxDB   | **ixVolume** (defaults)                                 |
| **Resources**          | Memory              | ≥ **1024 MB** (512 MB minimum; default 4096 MB is fine) |
| **Resources**          | CPUs                | 1–2                                                     |

**Disk path rules:**

| Drive type   | Use                        | Avoid                                     |
| ------------ | -------------------------- | ----------------------------------------- |
| SATA/SAS     | `/dev/sda`, `/dev/sdb`     | —                                         |
| NVMe         | `/dev/nvme0`, `/dev/nvme1` | `/dev/nvme0n1` (less complete SMART data) |
| Boot/OS disk | Optional                   | Skip unless intentional                   |

> [!TIP]
> If install **times out with multiple disks**, add **one disk**, install, then **Edit app** and add the rest.

#### WebUI access

Scrutiny **includes a WebUI** in the TrueNAS app (same omnibus image).

| Method | URL                                    |
| ------ | -------------------------------------- |
| GUI    | **Apps → Installed → Scrutiny → Open** |
| Direct | `http://<truenas-ip>:31054`            |

Use **HTTP**, not HTTPS (unless behind a reverse proxy).

Verify from shell:

```bash
curl -s http://127.0.0.1:31054/api/health
docker ps | grep -i scrutiny
```

#### After install — SMART cron (required)

Scrutiny **reads** SMART data; it does **not** schedule tests.

1. **Data Protection → Periodic SMART Tests**
2. Add **Short** (weekly) and **Long** (monthly) tasks for pool disks.
3. On **fresh 25.10+ installs**, cron jobs may not exist by default — create manually.

#### Scrutiny vs TrueNAS responsibilities

| Task                             | Who               |
| -------------------------------- | ----------------- |
| SMART history & trends           | Scrutiny          |
| Run SHORT/LONG SMART tests       | TrueNAS cron      |
| Pool / ZFS health                | TrueNAS           |
| Alert if Scrutiny is down        | Uptime Kuma       |
| Alert if disk failing thresholds | Scrutiny webhooks |

#### Scrutiny troubleshooting

| Symptom                               | Fix                                                                        |
| ------------------------------------- | -------------------------------------------------------------------------- |
| WebUI unreachable                     | Confirm **Published** port; app **Running**; use `http://` not `https://`  |
| Port 31054 refused                    | Check actual port in **Edit → Network**; test with `curl` on NAS shell     |
| NVMe shows **failed** with good SMART | Enable Elevate Privileges; clear config/db and restart app if status stuck |
| No disks in dashboard                 | Wait 5–15 min; verify disk paths; check `smartctl -a /dev/sdX` on host     |
| `wipefs` busy on disk                 | Export pool first; do not wipe boot disk                                   |
| Healthcheck timeout                   | Increase start_period/timeout; or install with one disk first              |

Clear app data (loses history) if NVMe status stuck after enabling privileges:

```bash
# Stop Scrutiny app first via GUI
rm -rf /mnt/.ix-apps/app_mounts/scrutiny/config/*
rm -rf /mnt/.ix-apps/app_mounts/scrutiny/influxdb/*
```

---

### Uptime Kuma — TrueNAS app basics

Default catalog ports: **WebUI `31054` → Scrutiny**, **Uptime Kuma `31050`**.

#### Minimum resources

| App         | RAM (min) | RAM (comfortable)                  | CPU | Disk                            |
| ----------- | --------- | ---------------------------------- | --- | ------------------------------- |
| Scrutiny    | 512 MB    | 1 GB                               | 1   | ~500 MB–2 GB (InfluxDB history) |
| Uptime Kuma | 512 MB    | 512 MB–1 GB (SQLite, <50 monitors) | 1   | ~1 GB+                          |

TrueNAS app defaults set **4096 MB** limits — safe but overkill; **1024 MB** each is usually enough.

Use **SQLite** (default) for Kuma on a memory-tight NAS; avoid embedded **MariaDB** unless you need hundreds of monitors.

#### Connect to the WebUI

1. **Apps → Installed → Uptime Kuma → Open**
2. Or `http://<truenas-ip>:31050` (confirm port in **Edit → Network**)

First visit: create **admin username/password** immediately.

---

### Uptime Kuma — monitors for this homelab

Checks run **from the TrueNAS container** — they test what the NAS can reach (LAN, Tailscale, internet).

Prefer **HTTP(s)** and **TCP** over **Ping** (ICMP often blocked from the container).

#### Tier 1 — critical

| Monitor        | Type    | Target                                                      |
| -------------- | ------- | ----------------------------------------------------------- |
| Internet / WAN | HTTP(s) | `https://1.1.1.1/cdn-cgi/trace`                             |
| pfSense DNS    | DNS     | `google.com` @ `172.16.0.1`                                 |
| pfSense GUI    | HTTP(s) | `https://172.16.0.1` (ignore TLS if self-signed)            |
| TrueNAS GUI    | HTTP(s) | `https://<truenas-ip>:443`                                  |
| Proxmox ×3     | HTTP(s) | `https://pvenode-00X:8006` (keyword: `Proxmox`; ignore TLS) |

#### Tier 2 — services

| Monitor      | Type    | Target                                       |
| ------------ | ------- | -------------------------------------------- |
| TrueNAS SMB  | TCP     | `<nas-ip>:445`                               |
| TrueNAS NFS  | TCP     | `<nas-ip>:2049`                              |
| Scrutiny     | HTTP(s) | `http://<nas-ip>:31054`                      |
| Proxmox SSH  | TCP     | `<node-ip>:22`                               |
| Internal DNS | DNS     | `pvenode-001.<domain>` via internal resolver |

#### Tier 3 — Tailscale & internet

| Monitor                 | Type    | Target                                |
| ----------------------- | ------- | ------------------------------------- |
| Tailscale control plane | HTTP(s) | `https://controlplane.tailscale.com`  |
| PVE via Tailscale       | HTTP(s) | `https://100.x.x.x:8006` (ignore TLS) |
| TrueNAS via Tailscale   | HTTP(s) | `https://100.x.x.x:443`               |

**LAN vs Tailscale pairs** help isolate failures:

| LAN  | Tailscale | Likely issue              |
| ---- | --------- | ------------------------- |
| Up   | Up        | Healthy                   |
| Up   | Down      | Tailscale / subnet routes |
| Down | Up        | LAN routing / switch      |
| Down | Down      | Host offline              |

#### Push monitors (scheduled jobs)

Use for backups, scrubs, SMART cron completion:

```bash
curl -fsS "http://<kuma-host>:31050/api/push/<TOKEN>?status=up&msg=scrub+ok"
```

#### What Kuma cannot monitor from TrueNAS

- Proxmox **quorum / Ceph** state (use push scripts or API checks)
- pfSense **internal** firewall state (use GUI port checks)
- **Docker container health** on TrueNAS (docker socket not exposed to Kuma app)
- Disks on **Proxmox nodes** (Scrutiny only sees **local TrueNAS disks**)

---

### Uptime Kuma — Telegram notification template (HTML)

**Settings → Notifications → Telegram:**

1. Bot token from [@BotFather](https://t.me/BotFather)
2. Chat ID from [@userinfobot](https://t.me/userinfobot) or getUpdates
3. Enable **Use Custom Template**
4. **Message Format:** `HTML`
5. Paste template below; **Test** before assigning to monitors

```liquid
{%- assign is_down = false -%}
{%- assign is_up = false -%}
{%- if heartbeatJSON -%}
  {%- if heartbeatJSON.status == 0 -%}
    {%- assign is_down = true -%}
  {%- elsif heartbeatJSON.status == 1 -%}
    {%- assign is_up = true -%}
  {%- endif -%}
{%- endif -%}

{%- if is_down -%}
🚨 <b>ALERT — SERVICE DOWN</b>
{%- elsif is_up -%}
✅ <b>RECOVERED — SERVICE UP</b>
{%- else -%}
⚠️ <b>STATUS UPDATE</b>
{%- endif -%}

━━━━━━━━━━━━━━━━━━━━
<b>Monitor:</b> {{ name }}
<b>Status:</b> {{ status }}
<b>Target:</b> <code>{{ hostnameOrURL }}</code>
<b>Message:</b> {{ msg }}

{%- if heartbeatJSON -%}
{%- if heartbeatJSON.localDateTime -%}
<b>Time:</b> {{ heartbeatJSON.localDateTime }}
{%- endif -%}
{%- if heartbeatJSON.ping -%}
<b>Response:</b> {{ heartbeatJSON.ping }} ms
{%- endif -%}
{%- if heartbeatJSON.retries and heartbeatJSON.retries > 0 -%}
<b>Retries:</b> {{ heartbeatJSON.retries }}
{%- endif -%}
{%- endif -%}

{%- if monitorJSON.type -%}
<b>Type:</b> <code>{{ monitorJSON.type | upcase }}</code>
{%- endif -%}

{%- if is_down -%}
<b>Hints:</b>
{%- if name contains "pfSense" or name contains "Gateway" -%}
 Check WAN, DNS, Tailscale subnet routes
{%- elsif name contains "Proxmox" or name contains "PVE" -%}
 Check quorum: <code>pvecm status</code>
{%- elsif name contains "TrueNAS" or name contains "NAS" -%}
 Check <code>zpool status</code> and Scrutiny
{%- elsif name contains "Internet" -%}
 WAN down while LAN may still work — check pfSense gateway
{%- else -%}
 Compare LAN vs Tailscale monitors if both exist
{%- endif -%}
{%- endif -%}

<i>Homelab • Uptime Kuma</i>
```

**Template variables:** `name`, `status`, `hostnameOrURL`, `msg`, `monitorJSON`, `heartbeatJSON`. Use `monitorJSON.description`, `monitorJSON.pathName`, `monitorJSON.tags` for extra context.

**Proxmox HTTPS monitors:** enable **Ignore TLS/SSL errors** (self-signed certs).

---

### TrueNAS Scale monitoring — quick reference

| Port / service          | Default port | Monitor type               |
| ----------------------- | ------------ | -------------------------- |
| TrueNAS WebUI           | 443          | HTTP(s)                    |
| TrueNAS SSH             | 22           | TCP                        |
| TrueNAS SMB             | 445          | TCP                        |
| TrueNAS NFS             | 2049         | TCP                        |
| Scrutiny WebUI          | 31054        | HTTP(s)                    |
| Uptime Kuma             | 31050        | HTTP(s)                    |
| pfSense GUI             | 443          | HTTP(s)                    |
| pfSense DNS             | 53           | DNS                        |
| Proxmox WebUI/API       | 8006         | HTTP(s)                    |
| Proxmox SSH             | 22           | TCP                        |
| Corosync                | 5405         | TCP                        |
| Tailscale control plane | 443          | HTTP(s)                    |
| Internet check          | —            | HTTP(s) → Cloudflare trace |

> [!NOTE]
> Allow **LAN → monitored ports** on pfSense if rules are tightened beyond defaults. Kuma on TrueNAS must reach targets on `172.16.0.0/16` and Tailscale `100.x.x.x` addresses.
