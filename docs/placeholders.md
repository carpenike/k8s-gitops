# Placeholders to fill in

Nothing in this list is a secret value. Do not replace a placeholder by
committing the real value when that value is an address, a hostname, a
token, or a key. Addresses can move into an encrypted vars file later.
Tokens go to 1Password.

| Placeholder | Where | Replace with |
| --- | --- | --- |
| `192.0.2.0/24` and the `.1`, `.10`–`.14`, `.16/28`, `.20`, `.21` addresses | `cluster.example.toml`, `talos/topf.yaml`, `talos/all/20-network.yaml.tpl`, Cilium pool, Gateway annotations | The real LAN plan, kept out of the public repo once it is real |
| `10.42.0.0/16`, `10.43.0.0/16`, `10.43.0.10` | Talos network patch, Cilium, CoreDNS | Confirm they do not overlap the LAN. They are cluster overlays, not LAN addresses |
| `example.com` and `${SECRET_DOMAIN}` | `kubernetes/components/sops/cluster-secrets.yaml` and any manifest that uses the substitution | The public zone, via the encrypted secret, not a plaintext edit of every file |
| `sled-1` … `sled-4` | `talos/topf.yaml` | Hostnames you are willing to publish, or rename only in the uncommitted `cluster.toml` |
| `02:00:00:00:00:0N` | `talos/topf.yaml` | NIC MACs from maintenance mode |
| `/dev/disk/by-id/example-boot-REPLACE_ME` | `talos/topf.yaml` | Boot disk by-id. Not an OSD |
| `/dev/disk/by-id/example-osd-REPLACE_ME` | Rook cluster HelmRelease | OSD by-id filter for the four data SSDs per sled. `useAllDevices` stays false |
| 64 zeros | `schematicId` | Image Factory id for a schematic that includes `nut-client` |
| ASN `64512` both sides | Cilium BGP manifests, `cluster.example.toml` | The RouterOS ASN. Both sides match for iBGP |
| `PLACEHOLDER_VAULT_ID` | ClusterSecretStore | 1Password vault id |
| `PLACEHOLDER_ITEM_*` | ExternalSecrets | 1Password item and field names |
| `onepassword-sdk` secret | not in git | `kubectl create secret` from `bootstrap/README.md` |
| `sops-age` secret | not in git | New age key, not the v1 recipient |
| `AGE_RECIPIENT_PLACEHOLDER` | `.sops.yaml.example` | The new public recipient, in `.sops.yaml`, after the private key exists only on disk and in the cluster |
| `nut.example.invalid` and `upsmon` | `talos/all/80-nut-client.yaml` | NUT server and credentials from 1Password, applied with the machine config, not committed |
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
