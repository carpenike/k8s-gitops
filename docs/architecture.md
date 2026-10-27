# Architecture

Four Talos nodes in one chassis. Their names are `sled-1.holthome.net`
through `sled-4.holthome.net`. `sled-1` through `sled-3` are control
planes with the control-plane taint removed, so they run workloads. `sled-4`
is a worker. All four are Ceph hosts. A single chassis is one failure
domain: a sled can fail, the chassis cannot. Backups leave the chassis.
Workloads that must outlive it stay on Forge.

Flux syncs `kubernetes/apps` from this GitHub repository. The branch in
`flux-instance` is `rebuild` until cutover, then `main`.

## Platform

| Layer | Choice | Pin |
| --- | --- | --- |
| Node OS | Talos, Image Factory, UEFI, `nut-client` | v1.14.5 |
| Kubernetes | Talos-managed | v1.37.1 |
| GitOps | Flux Operator and Flux instance | chart 0.62.1, Flux 2.10.0 |
| CNI | Cilium, kube-proxy replacement, BGP | 1.20.4 |
| Ingress | Envoy Gateway, `envoy-internal` and `envoy-external` | 1.9.3 |
| Gateway API | CRDs from the Envoy Gateway chart | 1.6.3 is the plan's standard channel |
| Certificates | cert-manager, Cloudflare DNS-01 wildcard | v1.21.3 |
| Public DNS | external-dns to Cloudflare, external gateway only | app v0.24.0, chart 1.23.0 |
| Internal DNS | external-dns plus MikroTik webhook | webhook v1.6.3 |
| Public reach | cloudflared tunnel to `envoy-external` | cloudflared 2026.10.3 |
| Secrets | External Secrets, 1Password SDK | chart 2.14.0 |
| Block | Rook-Ceph, 3 replicas, host failure domain | 1.21.1 |
| Media | NFS static volumes, class `nfs-media` | no provisioner |
| Postgres | CloudNativePG, chart appVersion 1.30.1 | chart 0.29.1 |
| Postgres backup | Barman Cloud plugin | chart 0.8.1, app v0.15.1 |
| PVC backup | VolSync restic | chart 0.17.0 |
| Metrics | kube-prometheus-stack, in-cluster Alertmanager off | chart 92.14.0 |
| Node upgrades | tuppr | chart 0.5.10 |
| Image pull cache | spegel | 0.8.0 |
| Dependency updates | Renovate | 44.188.2 |

Chart tags that the plan did not name (spegel, CoreDNS, metrics-server,
reloader, echo, app-template, tuppr, kube-prometheus-stack, cloudflared)
are the current pins from onedr0p/cluster-template or the chart repo as of
27 Oct 2026. Renovate is expected to move them.

## Networks

Pod CIDR `10.42.0.0/16` and service CIDR `10.43.0.0/16` are the
cluster-template defaults. They do not overlap the node LAN or the
LoadBalancer range.

The node LAN is `10.20.0.0/16`, gateway `10.20.0.1`. v1 already used that
prefix for kubelet `validSubnets`, etcd `advertisedSubnets`, and the BGP
peer (`10.20.0.1/32` in `CiliumBGPPeeringPolicy`). The four sleds reuse the
v1 bare-metal addresses `10.20.10.20` through `10.20.10.23`. The old VM
control plane at `10.20.0.20` is not carried forward. Static config uses a
`/16` mask so the gateway is on-link. v1 used DHCP and did not record the
mask.

Cilium advertises LoadBalancer IPs only. The pool is `10.45.0.0/16`, the
same `CiliumLoadBalancerIPPool` block as v1. Envoy reuses the v1 gateway
addresses: internal `10.45.10.50`, external `10.45.10.51`. The API VIP
`10.20.10.10` is a Talos Layer 2 VIP, not a Cilium pool address. The v1
VIP was SOPS-encrypted, so this one is new and still needs a free-address
check.

BGP is iBGP. ASN 64512 is on the nodes and on the router, matching v1.
Optional TCP MD5, if used later, belongs in 1Password.

## Names

`holthome.net` is the cluster zone. Node names, `internal.holthome.net`,
`external.holthome.net`, and the Flux webhook live there. The MikroTik
external-dns release writes that zone only.

Public apps also use these zones. Cloudflare DNS, the DNS-01 solver, the
external gateway certificates, and the tunnel ingress list each of them.
The home router does not:

- `warwed.com`
- `ryanholt.net`
- `whiskeywhiskeywhiskey.org`
- `stefanieholt.com`

Each of those has an apex name and a wildcard certificate. The tunnel
sends them all to `envoy-external`, and checks the origin certificate as
`external.holthome.net`.

## Data

Rook is told `useAllDevices: false` and a device path that matches nothing
real (`example-osd-REPLACE_ME`). Boot disks stay out of Ceph until the
by-id filter is filled in from the sleds.

Postgres clusters are not installed yet. `kubernetes/examples/cnpg-cluster.yaml`
shows a two-instance cluster on `ceph-block` with WAL archiving through the
Barman Cloud plugin. Object storage endpoints are `s3.example.invalid` and
are not live. The same pattern is the intent for a second copy in R2.

VolSync is installed. ReplicationSource objects are examples only.

kube-prometheus-stack runs Prometheus and not Alertmanager or Grafana.
Alerts are forwarded to `alertmanager.example.invalid:9093`, which stands
in for Forge.

## What stays off the cluster

Plex, transcode, home automation, USB radios, cameras, and Pocket ID stay
on Forge. The NAS boxes serve files and backups. They are not Kubernetes
nodes. Garage on the backup NAS is a NixOS change, not a manifest in this
repo.

## Out of band

BMC hardware monitoring runs on Forge, outside this cluster. prometheus
`ipmi_exporter` there scrapes each sled BMC for temperatures, fans, PSU
status, and the hardware event log. Alerts land on Forge's Alertmanager.
There is no in-cluster exporter. The BMCs sit on an isolated management
network. `cluster.example.toml` records that network with RFC 5737
TEST-NET-2 addresses (`198.51.100.0/24`, sleds `.11`–`.14`). Real
addresses and credentials belong in the Forge repo and in 1Password.
ADR 0004.

### Power

NUT shutdown and the later power-on are a pair.

Shutdown starts when the NUT primary (the host behind
`nut.example.invalid`) sends FSD. Every sled runs the same `nut-client`
patch: `upsmon` secondary, `SHUTDOWNCMD /sbin/poweroff`. That patch does
not stagger the nodes. The order to configure on the primary is the
reverse of power-on:

1. `sled-4` (worker)
2. `sled-3`, then `sled-2`, then `sled-1` (control planes, last member last)

Power-on is Forge's job, after the UPS reports the battery has recovered.
Forge uses IPMI or Redfish, waits until the previous sled is on, then
starts the next:

1. `sled-1`, then `sled-2`, then `sled-3` (control planes, so etcd can form)
2. `sled-4` (worker) last

The waits and the 1Password item name for the BMC user live with Forge.
This repo only records the order and the placeholder addresses.
