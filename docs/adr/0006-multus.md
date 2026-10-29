---
status: proposed
date: 2026-10-29
decision-makers: Ryan Holt
---

# Multus in front of Cilium for a node-LAN interface

## Context and Problem Statement

Some pods need a second interface on the node LAN. Scrypted is the first
expected consumer: it needs mDNS and HomeKit, and it needs to reach
cameras. Home Assistant-style apps are the same shape. `hostNetwork`
would put the pod on the node LAN and share the host network namespace.
Cilium is the pod network. A second primary CNI would overlap it.

Each sled has one 10G port, `ens1f0` (Talos alias `lan0`), on
`10.20.0.0/16` with gateway `10.20.0.1`. Cameras and other IoT devices
are on that same network. There is no VLAN subinterface.

## Decision Drivers

- Cilium stays the pod network (`eth0`) and the BGP LoadBalancer path
- A consuming app sets its own address with an annotation
- Talos v1.14 does not ship `macvlan` or `static`
- The pattern should match onedr0p/home-ops beside Cilium on Talos
- The master is the one NIC the nodes already have

## Considered Options

- `hostNetwork` on the app
- Multus thin plugin, macvlan bridge on `ens1f0`, static IPAM
- A Talos VLAN subinterface as the macvlan master
- Multus thick DaemonSet from the upstream manifest (Sidero guide)
- Cilium only, with no second interface

## Decision Outcome

Chosen option: "Multus thin plugin, macvlan bridge on `ens1f0`, static
IPAM", because the cameras share the node LAN and the thin plugin is what
onedr0p/home-ops runs. The thick plugin's `/run/netns` hostPath does not
apply. A VLAN subinterface would invent a network the nodes do not have.

The chart is `oci://ghcr.io/home-operations/charts/multus` tag `0.1.1`.
`cni.exclusive` on Cilium is `false`. The chart init container installs
the reference CNI plugins, including `macvlan`, `static`, and `sbr`, into
`/opt/cni/bin`. `NetworkAttachmentDefinition/lan` in `kube-system` is the
shared attachment. Its master is `ens1f0`. Addresses come from
`10.20.0.0/16`. The static route gateway is `10.20.0.1`. Each app sets
its own address in the annotation. Scrypted is not migrated in this
change.

### Consequences

- Good, because a pod opts in with `k8s.v1.cni.cncf.io/networks` and keeps
  cluster traffic on Cilium
- Good, because plugin binaries are installed by the DaemonSet. This
  change does not edit Talos machine config and does not require a reboot
- Bad, because a macvlan child cannot reach its own node's address on
  `ens1f0`. Other hosts on `10.20.0.0/16` are reachable
- Cilium `devices` stays `ens1f0`, the same port the macvlan is enslaved to

## Pros and Cons of the Options

### hostNetwork

- Good, because it needs no extra CNI
- Bad, because the pod shares the host network namespace, and every such
  app would do that

### Multus thin plugin on ens1f0

- Good, because it matches home-ops and the Talos CNI paths
- Good, because static IPAM plus the `ips` capability lets each app set
  its address in the annotation, from `10.20.0.0/16`
- Bad, because Cilium must keep `cni.exclusive` false or it removes
  `00-multus.conf`
- Bad, because the pod cannot reach the host IP of the node it is on
  over the macvlan interface

### VLAN subinterface

- Good, because it would isolate cameras from the node LAN
- Bad, because the cameras are already on the node LAN, and a VLAN link
  is not configured

### Multus thick DaemonSet

- Good, because the Sidero guide starts there
- Bad, because the upstream manifest is the thick plugin, and this repo's
  chosen chart is the thin plugin home-ops already runs

### Cilium only

- Good, because it adds no component
- Bad, because a pod on the Cilium network does not have an L2 interface
  on `ens1f0`, and mDNS stays on that port
