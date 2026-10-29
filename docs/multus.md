# Multus

Multus is the CNI meta-plugin in front of Cilium. Cilium remains the pod
network (`eth0`). A pod that needs a second interface on the node LAN, for
mDNS or to reach cameras, attaches `NetworkAttachmentDefinition/lan`.
Scrypted is the first expected consumer. No app is attached in this change.
ADR 0006.

Each sled has one NIC. Talos aliases it to `lan0`. The kernel name is
`ens1f0`. Cameras and other IoT devices are on that same network,
`10.20.0.0/16`, gateway `10.20.0.1`. There is no VLAN subinterface and no
Talos `VLANConfig`.

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
stays `ens1f0`, which is also the macvlan master.

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
overlay. This change does not edit Talos machine config and does not
require a reboot. After a reboot the DaemonSet writes the plugins again.

## The `lan` attachment

`NetworkAttachmentDefinition/lan` in `kube-system` is macvlan, bridge
mode, master `ens1f0`, static IPAM, plus `sbr`. The static route is
`0.0.0.0/0` via `10.20.0.1`. `sbr` keeps that route on traffic sourced
from the macvlan address. Cluster traffic stays on `eth0`. Leave
`default-route` off the annotation.

The annotation address uses prefix `/16`, so `10.20.0.0/16` is on-link
and the gateway is only for destinations outside that prefix. The `ips`
capability is set so the address in the annotation is handed to the
static plugin.

A macvlan interface cannot reach the host address of the parent it is
enslaved to. A pod cannot reach its own node's `ens1f0` address
(`10.20.10.20` through `10.20.10.23`, whichever node it landed on) over
`net1`. Other nodes, the gateway `10.20.0.1`, and the rest of
`10.20.0.0/16` are reachable. Traffic to that same node still works over
the Cilium interface.

## Annotation

The attachment lives in `kube-system`. An app in another namespace names
that namespace. Pick a free address on `10.20.0.0/16`. Stay off the
gateway `10.20.0.1`, the API VIP `10.20.10.10`, and the node addresses
`10.20.10.20` through `10.20.10.23`. `10.20.10.50/16` below is an example
shape, not a reserved address.

```yaml
annotations:
  k8s.v1.cni.cncf.io/networks: |-
    [{
      "name": "lan",
      "namespace": "kube-system",
      "ips": ["10.20.10.50/16"]
    }]
```

`mac` is optional. A HelmRelease that uses the app-template chart sets the
same annotation under `defaultPodOptions.annotations`, which is where
onedr0p/home-ops puts it for Home Assistant.
