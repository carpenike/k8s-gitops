# Placeholders still open

Hardware from the 27 Oct 2026 preflight is filled in: MACs (sled-0
unverified), boot-disk selector, schematic id, BMC host addresses, and
node names. Passwords, tokens, and the age private key stay out of git.

## 1Password items

Vault id is still `PLACEHOLDER_VAULT_ID` on the ClusterSecretStore.
Create these items in that vault. Names can change if the ExternalSecret
`remoteRef.key` changes with them.

| Item | Fields | Consumer |
| --- | --- | --- |
| `PLACEHOLDER_VAULT_ID` | the vault id itself | ClusterSecretStore `onepasswordSDK.vault` |
| service-account token | `token` | `onepassword-sdk` Secret in `external-secrets`, created by the bootstrap script. Not an ExternalSecret |
| `PLACEHOLDER_ITEM_cloudflare-dns` | `api-token` | cert-manager ClusterIssuer and external-dns Cloudflare |
| `PLACEHOLDER_ITEM_cloudflare-tunnel` | `tunnel-token` | cloudflared |
| `PLACEHOLDER_ITEM_mikrotik-dns` | `baseurl`, `username`, `password` | external-dns MikroTik webhook |
| `PLACEHOLDER_ITEM_flux-webhook` | `token` | Flux Receiver |
| `PLACEHOLDER_ITEM_nut` | `username`, `password`. UPS name is assumed `apc` | `NUT_UPSMON_PASSWORD` at `topf apply`. Not an ExternalSecret; nut-client runs before the cluster |
| `PLACEHOLDER_ITEM_BMC` | `username`, `password` | Forge `ipmi_exporter`. Not a manifest in this repo |

## Still to confirm or generate

| Placeholder | Where | Replace with |
| --- | --- | --- |
| API VIP `10.20.10.10` | `talos/topf.yaml`, `talos/all/20-network.yaml.tpl` | Confirm it is free. The v1 VIP was encrypted and was not copied |
| `/16` mask on `bond0` | `talos/all/20-network.yaml.tpl` | Confirm the LAN mask. v1 used DHCP and did not record it |
| sled-0 boot WWID | `talos/topf.yaml` `bootWwid` | Read it when the node is up. Install does not wait on it; the Samsung 870 model and size selector covers all four |
| sled-0 MAC `0c:c4:7a:8e:90:f4` | `talos/topf.yaml` | Unverified. The node was dark during the preflight |
| BMC mask | `cluster.example.toml` `[bmc].cidr` | `10.9.18.0/24` is inferred from `.20`–`.23`. No gateway was observed |
| UPS name `apc` | `talos/all/80-nut-client.yaml.tpl` | The name in Forge's NUT config, once that nix-config change exists |
| `AGE_RECIPIENT_PLACEHOLDER` | `.sops.yaml` | Output of `age-keygen -y age.key`. Generate the key locally |
| `nas-media.example.invalid` | `kubernetes/examples/nfs-pv.yaml` | Media NFS server, when a PV is actually added |
| `s3.example.invalid`, `PLACEHOLDER_BUCKET_cnpg` | `kubernetes/examples/cnpg-cluster.yaml` | Garage and R2 endpoints and bucket names |
| `alertmanager.example.invalid:9093` | kube-prometheus-stack values | Forge Alertmanager address |
| `refs/heads/rebuild` | flux-instance HelmRelease | `refs/heads/main` at cutover |
| Second X520 port | `talos/all/20-network.yaml.tpl` has one link, the active `ens1f0` | The other port's MAC, if the bond should have two members |
| ASN `64512` | Cilium BGP | Matches v1. Confirm RouterOS still uses it |

`kubernetes/examples/` is not applied by Flux.
