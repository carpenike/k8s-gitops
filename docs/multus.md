# Multus

Multus is the CNI meta-plugin in front of Cilium. Cilium remains the pod
network (`eth0`). A pod that needs a second interface on a LAN VLAN, for
mDNS or to reach cameras, attaches a NetworkAttachmentDefinition. Scrypted
is the first expected consumer. No app is attached in this change.
ADR 0006.

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
stays `ens1f0`. A macvlan master has to be a different kernel link.

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

## The `iot` attachment

`NetworkAttachmentDefinition/iot` in `kube-system` is macvlan, bridge
mode, static IPAM, plus `sbr`. `sbr` keeps return traffic for the
macvlan address on that interface. Cluster traffic stays on `eth0`. Leave
`default-route` off the annotation unless the pod should egress through
the VLAN.

The `ips` capability is set so the address in the annotation is handed to
the static plugin.

### TODO

`master` is the string `TODO`. `talos/` declares no VLAN link. Do not
attach a pod until `master` is the kernel name from `ip link`. The Talos
alias `lan0` is not a kernel name.

| Candidate | Where it is recorded | Why it is not `master` |
| --- | --- | --- |
| `ens1f0` (alias `lan0`), `10.20.0.0/16`, gateway `10.20.0.1` | `talos/all/20-network.yaml.tpl`, Cilium `devices` | Node LAN. Cilium's device. Not a VLAN subinterface |
| `10.9.18.0/24` | BMC, [architecture.md](architecture.md) | Isolated management network. No node interface in the Talos patches |
| v1 `bond0.30` at `10.30.10.2x/16` | [deviations.md](deviations.md) | Not part of this install. There is no bond. `CN=10.30.0.1` on the MikroTik webhook is the router certificate, not a node interface |

Adding that link later is a Talos `VLANConfig` (link `lan0`, `name` set to
the kernel name the NAD will use) and a machine-config apply. Do that
apply before any app references `iot`. A network apply can reboot a node.
Confirm the diff before applying.

`ipam.routes` has no gateway. Same-VLAN destinations are reachable from
the prefix in the annotation. Add a route once the VLAN gateway is known.
`sbr` keeps that route off Cilium's default table.

## Annotation

The attachment lives in `kube-system`. An app in another namespace names
that namespace. Replace the address. Pick one that is free on the VLAN,
outside any DHCP pool.

```yaml
annotations:
  k8s.v1.cni.cncf.io/networks: |-
    [{
      "name": "iot",
      "namespace": "kube-system",
      "ips": ["<address>/<prefix>"]
    }]
```

`mac` is optional. A HelmRelease that uses the app-template chart sets the
same annotation under `defaultPodOptions.annotations`, which is where
onedr0p/home-ops puts it for Home Assistant.
