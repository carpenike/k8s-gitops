# Architecture

Four Talos nodes in one chassis. Their names are `sled-0.holthome.net`
through `sled-3.holthome.net`. The index matches the old bare-metal
`node-0` through `node-3` addresses. `sled` is the hostname because these
are the chassis sleds. Control plane and worker are labels, so a later
machine that is not a sled does not have to join this series. `sled-0`
through `sled-2` are control planes with the control-plane taint removed,
so they run workloads. `sled-3` is a worker. All four are Ceph hosts. A
single chassis is one failure domain: a sled can fail, the chassis
cannot. Backups leave the chassis.
Workloads that must outlive it stay on Forge.

Flux syncs `kubernetes/apps` from this GitHub repository. The branch in
`flux-instance` is `rebuild` until cutover, then `main`.

## Platform

| Layer | Choice | Pin |
| --- | --- | --- |
| Node OS | Talos, Image Factory, UEFI, `nut-client` | v1.14.5 |
| UPS | `upsd` DaemonSet on every sled, Talos `upsmon` on localhost | instantlinux/nut-upsd 2.8.5-r1 |
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
| Actions runners | ARC scale sets, private `sam-tracker`, `sam-tracker-app` and `va-acr-app` | chart 0.15.1 |
| Dashboard | Headlamp, read-only, internal gateway | chart 0.46.0 |

Chart tags that the plan did not name (spegel, CoreDNS, metrics-server,
reloader, echo, app-template, tuppr, kube-prometheus-stack, cloudflared)
are the current pins from onedr0p/cluster-template or the chart repo as of
27 Oct 2026. Renovate is expected to move them. The Actions runner
policy, the GitHub App, and `runs-on: sam-tracker-k8s` /
`sam-tracker-app-k8s` / `va-acr-app-k8s` are in
[actions-runners.md](actions-runners.md). Headlamp's URL, read-only
ServiceAccount, and how to grant write later are in
[headlamp.md](headlamp.md).

## Networks

Pod CIDR `10.42.0.0/16` and service CIDR `10.43.0.0/16` are the
cluster-template defaults. They do not overlap the node LAN or the
LoadBalancer range.

Each sled has one 10G port on the one switch. Talos aliases that port to
`lan0` by its MAC. The node LAN is `10.20.0.0/16`,
gateway `10.20.0.1`. v1 already used that
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

BGP is iBGP. ASN 64512 is on the nodes and on the router at `10.20.0.1`.
RouterOS already peers `10.20.10.20` through `10.20.10.23` (`sled-0`
through `sled-3`). The LoadBalancer pool `10.45.0.0/16` is the range
those peers advertise.
Optional TCP MD5, if used later, belongs in 1Password.

## Names

`holthome.net` is the cluster zone. Node names, `internal.holthome.net`,
`external.holthome.net`, and the Flux webhook live there. The MikroTik
release writes A records for HTTPRoutes on `envoy-internal` only, aimed at
`10.45.10.50`. Routes on `envoy-external`, including echo and the Flux
webhook, are Cloudflare proxied names aimed at `external.holthome.net`.
There is no public wildcard: a name with no route is NODATA at `1.1.1.1`.

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

HTTPS on both gateways requires a Pocket ID login
(`https://id.holthome.net`) unless the HTTPRoute opts out. Echo is the
first route behind that login. `flux-webhook` is labeled public and
keeps its Receiver token. The client secret is Kustomization
`envoy-gateway-auth` in namespace `network`, which nothing else waits on. While that secret is
missing, Envoy Gateway answers the protected routes with 500. The label,
the path bypass, and the Pocket ID client settings are in
[gateway-auth.md](gateway-auth.md).

## Data

Rook `useAllDevices` stays false. `devicePathFilter` matches the three
960GB OSD SSDs on `ata6`–`ata8` of `pci-0000:00:1f.2`. The Samsung 870 boot
disk is `ata5` and does not match. `wipeDevicesFromOtherClusters` stays
true; the v1 Ceph data on those disks is wiped on install.

STATE and EPHEMERAL are LUKS2 with a `nodeID` key. The chassis has no TPM
module. sled-1's Talos dmesg on 27 Oct 2026 was `No TPM chip found` /
`TPM device is not available`. Secure Boot stays off. See `talos/README.md`.

Postgres clusters are not installed yet. `kubernetes/examples/cnpg-cluster.yaml`
shows a two-instance cluster on `ceph-block` with WAL archiving through the
Barman Cloud plugin. Object storage endpoints are `s3.example.invalid` and
are not live. The same pattern is the intent for a second copy in R2.

VolSync is installed. ReplicationSource objects are examples only.
It waits on `snapshot-controller` in `kube-system` (chart 0.1.2, external
snapshotter v8.7.0). That chart also carries the VolumeSnapshot CRDs.
`ceph-block` has VolumeSnapshotClass `csi-ceph-block`.

Rook 1.21 installs the ceph-csi-operator and creates CephConnection only
when `csi.createCsiOperatorResources` is true. The RBD and CephFS Driver
CRs come from the `ceph-csi-drivers` chart, not from the operator chart.
The provisioner names are `rook-ceph.rbd.csi.ceph.com` and
`rook-ceph.cephfs.csi.ceph.com`.

Prometheus Operator CRDs come from `prometheus-operator-crds` 32.0.2.
Bootstrap applies them once. The Flux HelmRelease of that chart is the
only day-2 owner (`install.crds` and `upgrade.crds` are `CreateReplace`).
kube-prometheus-stack does not manage CRDs. kube-prometheus-stack runs
Prometheus and not Alertmanager or Grafana.
Prometheus labels every series and alert `cluster=k8s-holthome` and sends
alerts to `https://am.holthome.net:443`. That name is Forge's Caddy vhost
(`hosts/forge/infrastructure/monitoring-ui.nix`). Its A record is
`10.20.0.30`, which is on `10.20.0.0/16`. The Alertmanager process listens
on `127.0.0.1:9093` only. Caddy requires a Pocket ID admin session and has
no API key, so the cluster's `POST /api/v2/alerts` is refused until Forge
allows that path from the sleds.

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
network. The 27 Oct 2026 preflight mapped `10.9.18.20` through
`10.9.18.23` to `sled-0` through `sled-3`. The `/24` mask is inferred.
Credentials stay in 1Password. ADR 0004.

### Power

Shutdown and power-on are different jobs. ADR 0005.

Each sled runs `upsd` (`snmp-ups` against the APC card at `10.9.18.245`)
and its own `upsmon`, a secondary of `apc@127.0.0.1`. On low battery or
FSD, default `upsmon` runs `SHUTDOWNCMD /sbin/poweroff`. There is no
primary and no stagger. `sled-0` through `sled-3` shut themselves down
independently when each one sees the flag. Forge is not a client of this
`upsd`. If Forge shuts down on the same UPS, that is Forge's own config.

Until the DaemonSet is running, `upsmon` retries. The nodes still boot.

Power-on is Forge's job, after the UPS reports the battery has recovered.
Forge uses IPMI or Redfish, waits until the previous sled is on, then
starts the next:

1. `sled-0`, then `sled-1`, then `sled-2` (control planes, so etcd can form)
2. `sled-3` (worker) last

The waits live with Forge. The BMC user is 1Password item `bmc` in vault
`k8s-secrets`, fields `username` and `password`. Those values are not in
git.
