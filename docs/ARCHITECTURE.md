# Papita Proxmox Lab — Architecture

Operator-facing description of the **current** end state for cluster `pvecm-oldtimers`: Proxmox VE nodes, HA/QDevice, pfSense, and TrueNAS NFS shared storage.

Runbooks and troubleshooting live in [TIPSNTRICKS.md](./TIPSNTRICKS.md). Network diagram: [Diagrams.drawio](./Diagrams.drawio). Deploy automation: `deploy/` (see `.cursor/rules/repo-map.mdc`).

---

## 1. Overview

```
Workstation (Tailscale / LAN)
        │
        ├─► Proxmox UI :8006  (cluster pvecm-oldtimers)
        ├─► pfSense WebGUI / Tailscale subnet router
        └─► TrueNAS SCALE 172.16.0.100  (NFS → PVE shared storage)

LAN 172.16.0.0/16  ◄── pfSense LAN (vmbr0)
WAN / upstream     ◄── pfSense WAN (vmbr1 → 192.168.78.0/24)
```

| Role              | Host / ID                | Notes                                   |
| ----------------- | ------------------------ | --------------------------------------- |
| PVE cluster       | `pvecm-oldtimers`        | Corosync on LAN `ring0`                 |
| PVE nodes         | `pve-001` … `pve-004`    | All four online (verified)              |
| Firewall / router | VM `100` `pfSense-FW001` | On `pve-001`, disks on `local-lvm`      |
| Shared storage    | TrueNAS `172.16.0.100`   | Pool `main_data_storage` → NFS          |
| QDevice           | `172.16.0.99`            | `corosync-qnetd` only — **not** TrueNAS |

---

## 2. Network

### 2.1 Addressing

| Segment               | CIDR / range      | Purpose                                                  |
| --------------------- | ----------------- | -------------------------------------------------------- |
| Homelab LAN           | `172.16.0.0/16`   | PVE management, corosync `ring0`, NFS clients, guest LAN |
| Upstream / WAN bridge | `192.168.78.0/24` | Physical uplink behind pfSense WAN                       |
| Tailscale CGNAT       | `100.64.0.0/10`   | Remote admin; pfSense advertises `172.16.0.0/16`         |

### 2.2 Proxmox bridges (typical node)

Verified on `pve-001`:

| Bridge  | Ports  | Address                                    | Role                                |
| ------- | ------ | ------------------------------------------ | ----------------------------------- |
| `vmbr0` | `nic1` | node `/16` on `172.16.0.0/16`              | Cluster LAN / management / corosync |
| `vmbr1` | `nic0` | e.g. `192.168.78.137/24` gw `192.168.78.1` | Upstream toward ISP/router          |

Node LAN IPs (corosync `ring0_addr`):

| Node      | `ring0` / LAN IP |
| --------- | ---------------- |
| `pve-001` | `172.16.0.101`   |
| `pve-002` | `172.16.0.102`   |
| `pve-003` | `172.16.0.103`   |
| `pve-004` | `172.16.0.104`   |

TrueNAS NFS server: **`172.16.0.100`**. Lab LAN gateway for clients is typically **`172.16.0.1`** (pfSense LAN) — see Tailscale/pfSense notes in TIPSNTRICKS.

### 2.3 pfSense placement

VM **100** `pfSense-FW001`:

| NIC    | Bridge  | Role                  |
| ------ | ------- | --------------------- |
| `net0` | `vmbr1` | WAN (upstream)        |
| `net1` | `vmbr0` | LAN (`172.16.0.0/16`) |

Disk: `local-lvm:vm-100-disk-0` on `pve-001`. **`onboot=1`**. Not HA-eligible while disks remain local (see §5).

Tailscale: pfSense joins the tailnet as a **subnet router** advertising `172.16.0.0/16`. Details: TIPSNTRICKS § pfSense / Tailscale.

---

## 3. Proxmox cluster

| Property          | Value                                                              |
| ----------------- | ------------------------------------------------------------------ |
| Cluster name      | `pvecm-oldtimers`                                                  |
| Members           | 4 (`pve-001` … `pve-004`)                                          |
| Quorum transport  | Corosync over LAN (`vmbr0` / `ring0`)                              |
| Main / entry node | `pve-001` (`172.16.0.101`) — common target for `deploy/proxmox.sh` |

Orchestration entrypoints:

- `deploy/toolkit.sh` → `deploy/proxmox.sh` (setup-node, setup-cluster-ha, start/stop-cluster, …)
- Node bootstrap: `deploy/setup/setup-pve-node.sh` (18 steps; QDevice client + softdog in step 18)

Cursor MCP: `proxmox-ve` (`mcp/proxmox-ve-mcp`) for REST reads and gated guest power — not for `pvecm` / WoL / sensors.

---

## 4. HA, QDevice, and fencing

### 4.1 Design goals

- Shared-disk HA for guests whose disks live on **TrueNAS NFS** (`truenas-nfs-main`).
- Quorum tie-breaker via **external QDevice** (not a PVE node, not TrueNAS).
- Watchdog fencing (`softdog`) prepared on nodes (setup step 18) before HA resources.

Config overlays:

- `deploy/setup/misc/cluster/default.qdevice.host` → **`172.16.0.99`**
- `deploy/setup/misc/cluster/default.truenas.nfs.env` → NFS IDs, `HA_GROUP_NAME`, `HA_NODES`
- Apply: `./deploy/proxmox.sh setup-cluster-ha --ip-address <online-node>` → `papita-cluster-quorum-ha.sh`

### 4.2 QDevice

| Item      | Value                                                   |
| --------- | ------------------------------------------------------- |
| Host      | `172.16.0.99`                                           |
| Service   | `corosync-qnetd`                                        |
| Bootstrap | `deploy/setup/misc/cluster/qdevice-server-bootstrap.sh` |
| Clients   | `corosync-qdevice` on each PVE node                     |

**Do not** run QDevice on TrueNAS (`172.16.0.100`). TrueNAS is NFS only.

Quorum math (4 PVE + QDevice): 5 votes → quorum 3 → cluster can remain quorate with **2 PVE nodes + QDevice**. Confirm live with `pve_cluster_health` (`quorate` from `/cluster/status`); per-vote QDevice detail via SSH `pvecm status`.

### 4.3 HA group

| Setting                     | Value (from `default.truenas.nfs.env`)                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Rule / group name           | `papita-ha`                                                                                                                        |
| `HA_NODES`                  | `pve-001,pve-003,pve-002,pve-004`                                                                                                  |
| `HA_AUTO_ENROLL_NFS_GUESTS` | `0`                                                                                                                                |
| `HA_SHUTDOWN_POLICY`        | `freeze` — HA guests are not recovered elsewhere on node shutdown/reboot; required by MCP power tools (check: `pve_get_ha_status`) |

Auto-enroll is **off**: guests on `local` / `local-lvm` (pfSense **100**, Fedora **101**) must **not** be HA-enrolled until disks move to shared NFS.

---

## 5. Guests (current)

| VMID | Name             | Node      | Storage     | HA                                      |
| ---- | ---------------- | --------- | ----------- | --------------------------------------- |
| 100  | `pfSense-FW001`  | `pve-001` | `local-lvm` | No — keep local; critical path firewall |
| 101  | `Fedora-Testing` | `pve-001` | `local-lvm` | No                                      |

Future HA guests: place disks on **`truenas-nfs-main`**, then enroll under `papita-ha` (see TIPSNTRICKS Path B).

---

## 6. TrueNAS and PVE storage

### 6.1 TrueNAS pools

| Pool                | Role                         | Topology (data)                                                        | Approx raw size |
| ------------------- | ---------------------------- | ---------------------------------------------------------------------- | --------------- |
| `main_data_storage` | PVE NFS / shared HA capacity | **`mirror-0`** (≈4 TB pair) **+** **`mirror-1`** (≈2 TB pair), striped | ≈5.4 TiB        |
| `core-components`   | NAS system / apps            | Single disk                                                            | ≈0.23 TiB       |

**History (brief):** former pool `misc_data_storage` was destroyed; its disks became `mirror-1` on `main_data_storage`. CT template data was migrated under `main_data_storage/ct-templates`.

### 6.2 NFS exports (TrueNAS → PVE)

Server: **`172.16.0.100`**. Options (PVE): `vers=4.1,hard,nconnect=4`.

| Export path                           | PVE storage ID      | Content                      | Purpose                                             |
| ------------------------------------- | ------------------- | ---------------------------- | --------------------------------------------------- |
| `/mnt/main_data_storage`              | `truenas-nfs-main`  | `images,rootdir`             | VM / LXC disks (HA-capable)                         |
| `/mnt/main_data_storage/ct-templates` | `truenas-nfs-media` | `iso,vztmpl,import,snippets` | ISOs, CT templates, OCI import, cloud-init snippets |
| `/mnt/main_data_storage/logs`         | `truenas-nfs-logs`  | `backup`                     | Backup / dump target                                |

Source of truth for IDs and content types: `deploy/setup/misc/cluster/default.truenas.nfs.env`.

**NFS client ACL (live 2026-09-23):** `pve-003` (`172.16.0.103`) can mount and write `truenas-nfs-main` (verified). Prefer allowing the full LAN `172.16.0.0/16` (or explicit `.101`–`.104`) on TrueNAS NFS shares.

### 6.3 Node-local storage

| Storage     | Type              | Content                    | Shared |
| ----------- | ----------------- | -------------------------- | ------ |
| `local-lvm` | LVM-thin          | `images,rootdir`           | No     |
| `local`     | dir `/var/lib/vz` | `iso,vztmpl,import,backup` | No     |

Use local for OS install scratch and for guests that must not migrate (pfSense today). Prefer `truenas-nfs-media` for ISO/CT/OCI library; prefer `truenas-nfs-main` for HA volume disks.

### 6.4 Cursor MCP (TrueNAS)

Package `mcp/truenas-mcp` — pool/dataset/NFS reads and gated writes. Does **not** register `pvesm` storage; cluster attach remains `papita-cluster-quorum-ha.sh` / `pvesm add nfs`.

---

## 7. How the pieces connect

1. **LAN** (`vmbr0` / `172.16.0.0/16`): PVE nodes, TrueNAS NFS, corosync, pfSense LAN.
2. **WAN** (`vmbr1`): pfSense upstream only.
3. **Shared storage path:** TrueNAS ZFS `main_data_storage` → NFS exports → PVE storage IDs → guest disks / media.
4. **HA path:** QDevice (`172.16.0.99`) + softdog + NFS on `truenas-nfs-main` + HA rule `papita-ha`.
5. **Remote access:** Tailscale via pfSense subnet routes (and/or node Tailscale from setup steps 8–9 / 17).

---

## 8. Last verified state (live)

Re-checked against Proxmox REST + TrueNAS WebSocket APIs on **2026-09-19** (workstation → cluster/`truenas-ha-scale` MagicDNS). Treat this as the snapshot that `@docs/ARCHITECTURE.md` was aligned to.

### 8.1 Cluster / guests

| Check                   | Result                                                                          |
| ----------------------- | ------------------------------------------------------------------------------- |
| Cluster                 | `pvecm-oldtimers`, **4** nodes, **quorate** (`quorate=1` via `/cluster/status`) |
| Nodes online            | `pve-001` `.101`, `pve-002` `.102`, `pve-003` `.103`, `pve-004` `.104`          |
| VM 100 `pfSense-FW001`  | `pve-001`, **running**, disk `local-lvm`                                        |
| VM 101 `Fedora-Testing` | `pve-001`, **running**, disk `local-lvm`                                        |

True `pvecm` / QDevice vote detail still requires SSH (`pvecm status`) — not fully exposed on REST.

### 8.2 PVE storage (active)

| Storage ID          | Type    | Export / path                           | Content                    | Shared | `pve-001` status                    |
| ------------------- | ------- | --------------------------------------- | -------------------------- | ------ | ----------------------------------- |
| `truenas-nfs-main`  | nfs     | `172.16.0.100:/mnt/main_data_storage`   | `images,rootdir`           | yes    | active; ≈**5.31 TiB** free          |
| `truenas-nfs-media` | nfs     | `…:/mnt/main_data_storage/ct-templates` | `iso,vztmpl,import`        | yes    | active; ≈124 MiB used (CT template) |
| `truenas-nfs-logs`  | nfs     | `…:/mnt/main_data_storage/logs`         | `backup`                   | yes    | active                              |
| `local-lvm`         | lvmthin | (per node)                              | `images,rootdir`           | no     | —                                   |
| `local`             | dir     | `/var/lib/vz`                           | `iso,vztmpl,import,backup` | no     | —                                   |

**Retired IDs confirmed absent:** `truenas-nfs-misc-*`, `truenas-nfs-templates`, `truenas-nfs-oci`.

### 8.3 TrueNAS pools / NFS

| Check               | Result                                                                    |
| ------------------- | ------------------------------------------------------------------------- |
| `misc_data_storage` | **Gone** (destroyed)                                                      |
| `main_data_storage` | ONLINE / healthy; **mirror-0** (`sdf`+`sdg`) + **mirror-1** (`sde`+`sdc`) |
| Pool size           | ≈5.44 TiB raw (API `size` ≈ 5.98×10¹² bytes)                              |
| Datasets            | `ct-templates` (~124 MiB), `logs`, `oci-images` (empty placeholder)       |
| NFS exports         | `/mnt/main_data_storage`, `…/ct-templates`, `…/logs`                      |
| NFS hosts ACL       | `.101`–`.104` usable (write verified on `.103` 2026-09-23)                |

Repo overlay matches live IDs: `deploy/setup/misc/cluster/default.truenas.nfs.env`.

---

## 9. Change log (storage / HA cutover)

Work performed to reach the state in §8. Guests **100/101 were not migrated**; no HA enroll of local-lvm VMs.

### 9.1 Before → after

| Area                             | Before                                                                                                       | After (current)                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| TrueNAS data pools for PVE       | `main_data_storage` (~3.5 TiB usable, single 4 TB mirror) **+** `misc_data_storage` (~1.76 TiB, 2 TB mirror) | **Only** `main_data_storage` with **two** striped mirrors (~5.3 TiB usable on PVE)                 |
| Misc pool disks                  | `sde` + `sdc` in `misc_data_storage`                                                                         | Same disks as **`mirror-1`** on `main_data_storage`                                                |
| PVE volume NFS                   | `truenas-nfs-main` + separate misc volume store (`truenas-nfs-misc-images`, content later `images,rootdir`)  | **`truenas-nfs-main` only** for VM/LXC volumes (grown with pool)                                   |
| PVE media NFS                    | Split: misc ISO / templates / OCI / logs IDs; then temporary `truenas-nfs-templates` + `truenas-nfs-oci`     | **`truenas-nfs-media`** (`iso,vztmpl,import`) + **`truenas-nfs-logs`**                             |
| CT template                      | On `misc_data_storage/ct-templates`                                                                          | On `main_data_storage/ct-templates` (ZFS local replication); still visible via `truenas-nfs-media` |
| `truenas-nfs-main` free (approx) | ~3.5 TiB                                                                                                     | **~5.31 TiB** (validated)                                                                          |

### 9.2 Steps executed (ordered)

1. **Mirror attach (misc):** attached unused 2 TB disk to single-disk `misc_data_storage` → 2-way mirror (`sde`+`sdc`).
2. **Enable volumes on misc NFS:** PVE `truenas-nfs-misc-images` content `iso` → `images,rootdir` (later superseded by pool merge).
3. **Pool merge into main:**
   - Replicated `misc_data_storage/ct-templates` → `main_data_storage/ct-templates` (`replication.run_onetime` / local push).
   - Removed PVE storages `truenas-nfs-misc-{images,templates,oci,logs}`.
   - Deleted misc NFS shares; **destroyed** `misc_data_storage`.
   - Extended `main_data_storage` with new **MIRROR** vdev (`sde`,`sdc`) via `pool.update`.
4. **Repoint media under main:** created NFS + PVE storages for templates/OCI/logs on `main_data_storage`; fixed `maproot_user=root` / `maproot_group=wheel` for nested shares.
5. **Combine media stores:** removed `truenas-nfs-templates` + `truenas-nfs-oci`; added **`truenas-nfs-media`** on `/mnt/main_data_storage/ct-templates` with `iso,vztmpl,import`; dropped unused OCI NFS share.
6. **Repo sync:** updated `default.truenas.nfs.env` share table to `truenas-nfs-main` / `truenas-nfs-media` / `truenas-nfs-logs`.

### 9.3 Intentionally unchanged

- Cluster membership (still 4 nodes).
- pfSense / Fedora disk placement (`local-lvm`).
- `HA_AUTO_ENROLL_NFS_GUESTS=0`.
- QDevice host file (`172.16.0.99`).
- NFS host ACL: `.103` (`pve-003`) write-verified on `truenas-nfs-main` (2026-09-23).
- Cloud-init QEMU template: VMID **9000** `ubuntu-2404-cloud` on `truenas-nfs-main`; snippets enabled on `truenas-nfs-media`.

---

## 10. Operational notes

| Topic                    | Guidance                                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------------------------ |
| Apply NFS/HA overlays    | `./deploy/proxmox.sh setup-cluster-ha --ip-address 172.16.0.101`                                       |
| True quorum              | `pve_cluster_health` → `quorate`; vote detail via SSH `pvecm status`                                   |
| Enroll HA guest          | Disks on `truenas-nfs-main` first; leave `HA_AUTO_ENROLL_NFS_GUESTS=0` unless intentional              |
| Expand capacity          | Grow `main_data_storage` (larger disks / add vdevs); do not split “free space” across pools via quotas |
| QDevice vs NFS           | Separate hosts: `.99` vs `.100`                                                                        |
| Diagrams / deep runbooks | [Diagrams.drawio](./Diagrams.drawio), [TIPSNTRICKS.md](./TIPSNTRICKS.md)                               |

---

## 11. Out of scope for this document

- Full pfSense firewall rule inventory (use pfSense UI / `pfsense-mcp` policy docs).
- Ceph OSD layout (not the HA shared path for this lab’s NFS design).
- Step-by-step node bootstrap (see `deploy/docs/setup-pve-node.usage.txt` and setup script).
- Secret material (`mcp.json` tokens, API keys) — never commit.

---

_Last live validation: 2026-09-19 via PVE/TrueNAS APIs. Re-check `pvecm status` and NFS host ACLs after membership or share changes._
