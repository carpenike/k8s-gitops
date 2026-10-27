# Architecture

Four Talos nodes in one chassis. `sled-1` through `sled-3` are control
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
cluster-template defaults. They are cluster-internal overlays. They must
not overlap the LAN. The LAN itself is not stored in git. Placeholder node
and gateway addresses are RFC 5737 TEST-NET-1 (`192.0.2.0/24`).

Cilium advertises LoadBalancer IPs only. The pool is `192.0.2.16/28`, which
covers the internal gateway `192.0.2.20` and the external gateway
`192.0.2.21`. The API VIP `192.0.2.10` is a Talos Layer 2 VIP, not a
Cilium pool address.

BGP is iBGP: the placeholder ASN is 64512 on the nodes and on the router.
Optional TCP MD5, if used later, belongs in 1Password.

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

Plex, transcode, home automation, USB radios, cameras, Pocket ID, and the
out-of-band metrics stack stay on Forge. The NAS boxes serve files and
backups. They are not Kubernetes nodes. Garage on the backup NAS is a
NixOS change, not a manifest in this repo.
