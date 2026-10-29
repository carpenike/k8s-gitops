---
status: proposed
date: 2026-10-29
decision-makers: Ryan Holt
---

# Multus in front of Cilium for VLAN interfaces

## Context and Problem Statement

Some pods need a second interface on a LAN VLAN. Scrypted is the first
expected consumer: it needs mDNS and HomeKit, and it needs to reach
cameras. Home Assistant-style apps are the same shape. `hostNetwork`
would put the pod on the node LAN and share the host network namespace.
Cilium is the pod network. A second primary CNI would overlap it.

No VLAN link is declared in `talos/`. The only node link is `ens1f0`
(Talos alias `lan0`) on `10.20.0.0/16`. v1's `bond0.30` is recorded as
not part of this install.

## Decision Drivers

- Cilium stays the pod network (`eth0`) and the BGP LoadBalancer path
- A consuming app sets its own address with an annotation
- Talos v1.14 does not ship `macvlan` or `static`
- The pattern should match onedr0p/home-ops beside Cilium on Talos
- VLAN IDs and subnets that are not in this repo stay unset

## Considered Options

- `hostNetwork` on the app
- Multus thin plugin, macvlan bridge, static IPAM (home-operations chart)
- Multus thick DaemonSet from the upstream manifest (Sidero guide)
- Cilium only, with no second interface

## Decision Outcome

Chosen option: "Multus thin plugin, macvlan bridge, static IPAM", because
that is the chart and attachment shape onedr0p/home-ops runs, and the thin
plugin is invoked by containerd on the host. The thick plugin's
`/run/netns` hostPath does not apply.

The chart is `oci://ghcr.io/home-operations/charts/multus` tag `0.1.1`.
`cni.exclusive` on Cilium is `false`. The chart init container installs
the reference CNI plugins, including `macvlan`, `static`, and `sbr`, into
`/opt/cni/bin`. `NetworkAttachmentDefinition/iot` in `kube-system` is the
shared attachment. Its `master` is `TODO` until a VLAN link exists.
Scrypted is not migrated in this change.

### Consequences

- Good, because a pod opts in with `k8s.v1.cni.cncf.io/networks` and keeps
  cluster traffic on Cilium
- Good, because plugin binaries are installed by the DaemonSet. This
  change does not edit Talos machine config and does not require a reboot
- Bad, because a later VLAN link is a machine-config apply, and that apply
  can reboot a node
- Bad, because `master` and the VLAN gateway are unset, so the attachment
  is not usable until a person fills them in
- Cilium `devices` stays `ens1f0`. The macvlan master has to be a different
  kernel link, or Cilium's BPF program on `ens1f0` is on the parent

## Pros and Cons of the Options

### hostNetwork

- Good, because it needs no extra CNI
- Bad, because the pod shares the host network namespace, and every such
  app would do that

### Multus thin plugin

- Good, because it matches home-ops and the Talos CNI paths
- Good, because static IPAM plus the `ips` capability lets each app set
  its address in the annotation
- Bad, because Cilium must keep `cni.exclusive` false or it removes
  `00-multus.conf`

### Multus thick DaemonSet

- Good, because the Sidero guide starts there
- Bad, because the upstream manifest is the thick plugin, and this repo's
  chosen chart is the thin plugin home-ops already runs

### Cilium only

- Good, because it adds no component
- Bad, because a pod on the Cilium network is not on the camera VLAN, and
  mDNS does not cross that boundary
