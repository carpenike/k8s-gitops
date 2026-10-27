# Placeholders still open

Hardware from the 27 Oct 2026 preflight is filled in: MACs (sled-0
unverified), boot-disk selector, schematic id, BMC host addresses, and
node names. Passwords, tokens, and the age private key stay out of git.

The 1Password vault is `k8s-secrets`, id `h3aojtbptukuxixo5ysdco7r6u`.
That is the vault the v1 Connect ClusterSecretStore selected by name.
The SDK store uses the id.

## Matched to archive/talos-v1

Same item and the same fields. Kubernetes secret keys stay what the
charts and the ClusterIssuer already read.

| Consumer | Item | 1Password field | Secret key |
| --- | --- | --- | --- |
| cert-manager ClusterIssuer | `Cloudflare` | `cert-manager` | `api-token` |
| external-dns Cloudflare | `Cloudflare` | `external-dns` | `api-token` |
| cloudflared | `Cloudflare` | `tunnel_account_tag`, `tunnel_secret`, `tunnel_id` | `credentials.json` and `TunnelID` |

v1 cloudflared pulled the whole `Cloudflare` item and prefixed each field
with `cloudflare_`. The template there reads `cloudflare_tunnel_account_tag`,
`cloudflare_tunnel_secret`, and `cloudflare_tunnel_id`, so the item fields
are the names without that prefix. This branch asks for those three fields
by name and builds the same `credentials.json`.

## No v1 equivalent

These stay as `PLACEHOLDER_ITEM_*` in the manifests. The proposed names
are not created yet.

| Placeholder | Proposed item | Proposed fields | Why it is unmatched |
| --- | --- | --- | --- |
| `PLACEHOLDER_ITEM_mikrotik-dns` | `mikrotik` | `baseurl`, `username`, `password` | v1 internal DNS was item `bind`, fields `externaldns_algorithm` and `externaldns_secret`. That is RFC2136, not the MikroTik webhook |
| `PLACEHOLDER_ITEM_flux-webhook` | `flux-webhook` | `token` | v1 had no Flux Receiver. Item `actions-runner-controller` field `ACTION_RUNNER_CONTROLLER_GITHUB_WEBHOOK_SECRET_TOKEN` is a different webhook and is not used |
| `PLACEHOLDER_ITEM_nut` | `nut` | `username`, `password` | No NUT item in v1. The Talos patch reads `password` from `NUT_UPSMON_PASSWORD` at apply time. The UPS name `apc` is still an assumption |
| `PLACEHOLDER_ITEM_BMC` | `bmc` | `username`, `password` | No BMC item in the v1 manifests. Forge `ipmi_exporter` reads it. Not an ExternalSecret |

The External Secrets service-account token is also unmatched. v1 stored a
Connect token in the SOPS secret `onepassword-connect-token`, key `token`.
The SDK token is new. The bootstrap script writes it to `onepassword-sdk`
in `external-secrets` from `ONEPASSWORD_SERVICE_ACCOUNT_TOKEN`. It is not
a vault item and it is not committed.

## Still to confirm or generate

| Placeholder | Where | Replace with |
| --- | --- | --- |
| API VIP `10.20.10.10` | `talos/topf.yaml`, `talos/all/20-network.yaml.tpl` | Confirm it is free. The v1 VIP was encrypted and was not copied |
| `/16` mask on `bond0` | `talos/all/20-network.yaml.tpl` | Confirm the LAN mask. v1 used DHCP and did not record it |
| sled-0 boot WWID | `talos/topf.yaml` `bootWwid` | Read it when the node is up. Install does not wait on it; the Samsung 870 model and size selector covers all four |
| sled-0 MAC `0c:c4:7a:8e:90:f4` | `talos/topf.yaml` | Unverified. The node was dark during the preflight |
| BMC mask | `cluster.example.toml` `[bmc].cidr` | `10.9.18.0/24` is inferred from `.20`–`.23`. No gateway was observed |
| UPS name `apc` | `talos/all/80-nut-client.yaml.tpl` | The name in Forge's NUT config, once that nix-config change exists |
| `nas-media.example.invalid` | `kubernetes/examples/nfs-pv.yaml` | Media NFS server, when a PV is actually added |
| `s3.example.invalid`, `PLACEHOLDER_BUCKET_cnpg` | `kubernetes/examples/cnpg-cluster.yaml` | Garage and R2 endpoints and bucket names |
| `alertmanager.example.invalid:9093` | kube-prometheus-stack values | Forge Alertmanager address |
| `refs/heads/rebuild` | flux-instance HelmRelease | `refs/heads/main` at cutover |
| Second X520 port | `talos/all/20-network.yaml.tpl` has one link, the active `ens1f0` | The other port's MAC, if the bond should have two members |
| ASN `64512` | Cilium BGP | Matches v1. Confirm RouterOS still uses it |

`kubernetes/examples/` is not applied by Flux.
