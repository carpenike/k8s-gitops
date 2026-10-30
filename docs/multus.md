# Multus

Multus is the CNI meta-plugin in front of Cilium. Cilium remains the pod
network (`eth0`). A pod that needs a second interface on the wireless
client VLAN attaches `NetworkAttachmentDefinition/vlan30`. Scrypted is
the consumer. The app is `kubernetes/apps/scrypted` (ADR 0008). No Coral
label exists yet. The app's node selector is a placeholder until the
owner labels the sled that has the USB Coral. ADR 0007.

VLAN 30 is wireless clients, `10.30.0.0/16`. The phones are on that
VLAN. HomeKit and mDNS have to be on it. VLAN 50 is cameras,
`10.50.0.0/16`. Scrypted reaches the cameras by routed unicast from the
VLAN 30 address. There is no VLAN 50 subinterface and no VLAN 50
attachment. The untagged server LAN does not have an attachment either.
The node already has that network on `ens1f0`.

Each sled has one NIC. Talos aliases it to `lan0`. The kernel name is
`ens1f0`. The switch port's native VLAN is the server LAN, VLAN 20,
`10.20.0.0/16`, gateway `10.20.0.1`. `talos/all/20-network.yaml.tpl`
adds `VLANConfig` `ens1f0.30` on `lan0`: VLAN id 30, 802.1q, up,
multicast on, MTU from the node, and no address. A macvlan child does
not need a parent address. Leaving the address off keeps the sleds off
the client VLAN.

The owner applies that machine config. If `ens1f0.30` does not appear,
reboot the sled. The switch port for each sled has to carry VLAN 30
tagged, with the native VLAN left on the server LAN. This repo does not
change the switch.

The chart is `oci://ghcr.io/home-operations/charts/multus` tag `0.1.1`,
the chart onedr0p/home-ops pins. At that tag the chart's appVersion is
multus-cni `v4.3.1` and the plugin image is
`ghcr.io/home-operations/cni-plugins:1.9.1`. Renovate moves the chart tag.
The HelmRelease does not override those image tags.

The chart deploys the thin plugin. The DaemonSet copies binaries into
`/opt/cni/bin` and writes config under `/etc/cni/net.d`. containerd invokes
the Multus binary on the host. The thick plugin's `/run/netns` mount is
not part of this chart.

## Cilium

`cni.exclusive` is `false`. With `true`, Cilium removes other CNI config
and renames `00-multus.conf` to `00-multus.conf.cilium_bak`. `devices`
stays `ens1f0`. The macvlan master is `ens1f0.30`.

`dependsOn` waits until the Cilium HelmRelease is Ready. On an already
running cluster that Ready condition is from the previous reconcile, so
Cilium can still roll after Multus has written its config. After both
HelmReleases are current, `00-multus.conf` should be the first file in
`/etc/cni/net.d` and it should delegate to Cilium. If that file is missing
or named `00-multus.conf.cilium_bak`, restart the Multus DaemonSet once
`cni.exclusive` is false.

## Plugins on Talos

Talos v1.14 ships `bridge`, `firewall`, `flannel`, `host-local`,
`loopback`, and `portmap`. It does not ship `macvlan`, `static`, or `sbr`.
`cniPlugins.enabled` is `true`, so the chart's init container copies the
reference plugins into `/opt/cni/bin`. That directory is a writable
overlay. After a reboot the DaemonSet writes the plugins again. No system
extension.

## The `vlan30` attachment

`NetworkAttachmentDefinition/vlan30` in `kube-system` is macvlan, bridge
mode, master `ens1f0.30`, static IPAM, plus `sbr`. The static route is
`0.0.0.0/0` via `10.30.0.1`. `sbr` keeps that route on traffic sourced
from the macvlan address. Cluster traffic stays on `eth0`. Leave
`default-route` off the annotation.

The annotation address uses prefix `/16`, so `10.30.0.0/16` is on-link
and the gateway is for destinations outside that prefix, including the
cameras on `10.50.0.0/16`. The `ips` capability is set so the address in
the annotation is handed to the static plugin.

HomeKit, mDNS, and camera connections have to be sourced from the VLAN 30
address. Traffic sourced from the pod address uses Cilium and leaves the
node on VLAN 20.

`ens1f0.30` has no host address. There is no node address on VLAN 30 for
the macvlan child to miss. Traffic to the node still uses the Cilium
interface.

## Annotation

The attachment lives in `kube-system`. An app in another namespace names
that namespace. Scrypted uses `10.30.0.31/16`. The VLAN 30 DHCP pool
`wireless_pool` is `10.30.100.1`–`10.30.100.254`, so `10.30.0.31` is
outside it and needs no reservation. That address has to stay outside
`10.30.100.0/24`. `10.30.0.30` and `10.30.0.116` are already static on
this VLAN.

```yaml
annotations:
  k8s.v1.cni.cncf.io/networks: |-
    [{
      "name": "vlan30",
      "namespace": "kube-system",
      "ips": ["10.30.0.31/16"]
    }]
```

`mac` is optional. A HelmRelease that uses the app-template chart sets the
same annotation under `defaultPodOptions.annotations`, which is where
onedr0p/home-ops puts it for Home Assistant.

## Before a pod attaches

- Trunk VLAN 30, tagged, on each sled's switch port
- Apply the Talos machine config so `ens1f0.30` exists
- If the router restricts inter-VLAN traffic, allow that VLAN 30 address
  to reach `10.50.0.0/16`
