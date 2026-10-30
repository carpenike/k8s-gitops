---
status: proposed
date: 2026-10-30
decision-makers: Ryan Holt
---

# Multus in front of Cilium for a VLAN 30 interface

## Context and Problem Statement

Scrypted needs a second interface on VLAN 30 so HomeKit and mDNS work
without `hostNetwork`. The phones are on VLAN 30 (wireless clients,
`10.30.0.0/16`). There is no mDNS reflector. Cameras are on VLAN 50
(`10.50.0.0/16`). Scrypted reaches them by routed unicast, so it does
not need an interface on VLAN 50.

`hostNetwork` would put the pod in the host network namespace. Cilium
is the pod network. A second primary CNI would overlap it.

Each sled has one 10G port, `ens1f0` (Talos alias `lan0`). That port's
native VLAN is the server LAN, VLAN 20, `10.20.0.0/16`, gateway
`10.20.0.1`. Management (`10.9.18.0/24`) is a different untagged
network and is not this port.

## Decision Drivers

- Cilium stays the pod network (`eth0`) and the BGP LoadBalancer path
- HomeKit discovery shares L2 with the phones on VLAN 30
- A consuming app sets its own address with an annotation
- The sleds do not take an address on the wireless client VLAN
- Camera traffic is routed from the VLAN 30 address to `10.50.0.0/16`
- Talos v1.14 does not ship `macvlan` or `static`
- The pattern should match onedr0p/home-ops beside Cilium on Talos

## Considered Options

- `hostNetwork` on the app
- Multus thin plugin, macvlan bridge on untagged `ens1f0`
- Multus thin plugin, macvlan bridge on a VLAN 30 subinterface
- Multus thin plugin, macvlan bridge on a VLAN 50 subinterface
- Multus thick DaemonSet from the upstream manifest (Sidero guide)
- Cilium only, with no second interface

## Decision Outcome

Chosen option: "Multus thin plugin, macvlan bridge on a VLAN 30
subinterface", because the phones are on VLAN 30 and discovery has to
happen there.

Talos `VLANConfig` creates `ens1f0.30` on alias `lan0`, VLAN id 30,
802.1q, up, multicast on, and no address. A macvlan child does not need
a parent address. An address on the subinterface would give every sled
a routable leg on the client VLAN, which these nodes do not need.

The chart is `oci://ghcr.io/home-operations/charts/multus` tag `0.1.1`.
`cni.exclusive` on Cilium is `false`. The chart init container installs
the reference CNI plugins, including `macvlan`, `static`, and `sbr`, into
`/opt/cni/bin`. `NetworkAttachmentDefinition/vlan30` in `kube-system` is
the shared attachment. Its master is `ens1f0.30`. Addresses come from
`10.30.0.0/16`. The static route gateway is `10.30.0.1`.
Each app sets its own address in the annotation. Scrypted is not
deployed in this change.

The untagged `lan` attachment is removed. Nothing needs a second
interface on the server LAN. There is no VLAN 50 attachment.

This record is 0007. Rebuild already used 0006 for LiteLLM.

### Consequences

- Good, because a pod opts in with `k8s.v1.cni.cncf.io/networks` and keeps
  cluster traffic on Cilium
- Good, because HomeKit and mDNS are on the same VLAN as the phones
- Bad, because the owner has to apply the Talos machine config, and the
  switch ports for the sleds have to carry VLAN 30 tagged
- Bad, because camera reachability depends on the router forwarding
  from that VLAN 30 address to `10.50.0.0/16`
- Cilium `devices` stays `ens1f0`. The macvlan master is `ens1f0.30`

## Pros and Cons of the Options

### hostNetwork

- Good, because it needs no extra CNI
- Bad, because the pod shares the host network namespace, and the host
  address is on VLAN 20, so HomeKit discovery would not be on VLAN 30

### Multus thin plugin on untagged ens1f0

- Good, because it needs no Talos VLAN document
- Bad, because that L2 domain is the server LAN, and the phones are on
  VLAN 30

### Multus thin plugin on ens1f0.30

- Good, because it matches home-ops and puts the pod on VLAN 30
- Good, because the subinterface has no address, so the sleds stay off
  the client VLAN
- Good, because static IPAM plus the `ips` capability lets each app set
  its address from `10.30.0.0/16`
- Bad, because Cilium must keep `cni.exclusive` false or it removes
  `00-multus.conf`
- Bad, because the owner has to trunk VLAN 30 and apply Talos config

### Multus thin plugin on a VLAN 50 subinterface

- Good, because the cameras would be on-link
- Bad, because the phones are on VLAN 30, and HomeKit discovery would
  still need a reflector

### Multus thick DaemonSet

- Good, because the Sidero guide starts there
- Bad, because the upstream manifest is the thick plugin, and this repo's
  chosen chart is the thin plugin home-ops already runs

### Cilium only

- Good, because it adds no component
- Bad, because a pod on the Cilium network does not have an L2 interface
  on VLAN 30
