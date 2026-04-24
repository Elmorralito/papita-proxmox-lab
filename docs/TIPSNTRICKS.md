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

After installing and initial configuration:

> [!WARNING]
> If there is no connection to the web GUI or ping from external endpoints to the WAN IP

It's possible that the IP filtering from the pfSense's firewall is blocking WAN external incoming connections to the Web GUI.

The **solution** is to modify the file `/cf/conf/config.xml` from console and using `vi` to add the following:

```xml
<!--in section <system> add.. -->
      <disablefilter>1</disablefilter>
```

Finally, reboot the VM and reconfigure the network interfaces if necessary.

> [!TIP]
> Default credentials on web GUI:
>
> - **username:** `admin`
> - **password:** `pfsense`

## [pfSense] Connect with Tailscale

**Walkthrough:** [Link here...](https://davidisaksson.dev/posts/tailscale-on-pfsense/)
