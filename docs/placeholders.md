# Placeholders to fill in

Nothing in this list is a secret value. Tokens and private keys go to
1Password or stay on the YubiKey. The node LAN and the LoadBalancer range
are already filled in from v1. Server names are `sled-N.holthome.net`.
The cluster zone and the public service zones are filled in. MACs, disk
ids, and BMC addresses stay as placeholders. BMC addresses in git are
RFC 5737 TEST-NET-2.

| Placeholder | Where | Replace with |
| --- | --- | --- |
| API VIP `10.20.10.10` | `cluster.example.toml`, `talos/topf.yaml`, `talos/all/20-network.yaml.tpl` | Confirm it is free. The v1 VIP was encrypted and was not copied |
| Sled addresses `10.20.10.20`–`.23` | `talos/topf.yaml` | Confirm the four sleds still own these v1 bare-metal addresses |
| `/16` mask on `bond0` | `talos/all/20-network.yaml.tpl` | Confirm the LAN mask. v1 used DHCP and did not record it |
| `10.42.0.0/16`, `10.43.0.0/16`, `10.43.0.10` | Talos network patch, Cilium, CoreDNS | Cluster overlays. They do not overlap `10.20.0.0/16` or `10.45.0.0/16` |
| `sled-1.holthome.net` … `sled-4.holthome.net` | `talos/topf.yaml` | Confirm these are the names to publish. The zone is `holthome.net` |
| `02:00:00:00:00:0N` | `talos/topf.yaml` | NIC MACs from maintenance mode |
| `/dev/disk/by-id/example-boot-REPLACE_ME` | `talos/topf.yaml` | Boot disk by-id. Not an OSD |
| `/dev/disk/by-id/example-osd-REPLACE_ME` | Rook cluster HelmRelease | OSD by-id filter for the four data SSDs per sled. `useAllDevices` stays false |
| 64 zeros | `schematicId` | Image Factory id for a schematic that includes `nut-client` |
| ASN `64512` both sides | Cilium BGP manifests, `cluster.example.toml` | Matches v1. Confirm RouterOS still uses it |
| `PLACEHOLDER_VAULT_ID` | ClusterSecretStore | 1Password vault id |
| `PLACEHOLDER_ITEM_*` | ExternalSecrets | 1Password item and field names |
| `onepassword-sdk` secret | not in git | `kubectl create secret` from `bootstrap/README.md` |
| Cluster age recipient | `.sops.yaml` key group, next to the YubiKey fingerprint | A new age public recipient. Not the v1 age key. Private key stays in `age.key` and in the `sops-age` Secret |
| `nut.example.invalid` and `upsmon` | `talos/all/80-nut-client.yaml` | NUT server and credentials from 1Password, applied with the machine config, not committed. Shutdown order is in `docs/architecture.md` |
| `198.51.100.0/24`, gateway `.1`, sleds `.11`–`.14` | `cluster.example.toml` `[bmc]` and `bmc_address` | Real BMC addresses, written in the Forge repo. This public repo keeps RFC 5737 TEST-NET-2 |
| `PLACEHOLDER_ITEM_BMC` | `cluster.example.toml` `[bmc].onepassword_item` | 1Password item for the BMC user. Username and password never go in git |
| `nas-media.example.invalid` | `kubernetes/examples/nfs-pv.yaml` | Media NFS server, when a PV is actually added |
| `s3.example.invalid`, `PLACEHOLDER_BUCKET_cnpg` | `kubernetes/examples/cnpg-cluster.yaml` | Garage and R2 endpoints and bucket names, credentials via ExternalSecret |
| `alertmanager.example.invalid:9093` | kube-prometheus-stack values | Forge Alertmanager address |
| `refs/heads/rebuild` | flux-instance HelmRelease | `refs/heads/main` at cutover |
| Bond members | `talos/all/20-network.yaml.tpl` has one link | Second port, MTU, and VLAN once the switch plan is chosen |
| Secure Boot and disk encryption | `encryptDisk: false` | Decide before install. Changing later means reinstalling |
| VolSync chart tag `0.17.0` | OCIRepository | Confirm the tag exists on `ghcr.io/backube/helm-charts/volsync` at first install |
| Renovate GitHub App | repo setting | Install the app. The config is `.renovaterc.json5` |
| GitHub secret scanning and push protection | repo setting | Turn on for the public repo. Not a file in this tree |

`kubernetes/examples/` is not applied by Flux. Copy an example into
`kubernetes/apps` only after its secrets exist.
