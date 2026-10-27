# Deviations from onedr0p/cluster-template

Upstream studied: `onedr0p/cluster-template` default branch, fetched
27 Oct 2026. The layout below is that repo's post-render shape: `mise.toml`,
`talos/topf.yaml`, per-node patches, `bootstrap/helmfile` that reads
`ocirepository.yaml` and `helmrelease.yaml`, and Flux Kustomizations under
`kubernetes/apps/<namespace>/<app>/`.

The template's generator (`template/`, makejinja, pydantic, `mise run
configure`) is not vendored. `configure` writes an age key, a deploy key,
and a webhook token, then encrypts them. This branch must not generate
those. Manifests are committed directly, with placeholders, in the shape
configure would have emitted. `cluster.example.toml` records the inputs.
`cluster.schema.json` from the template is not copied, so the example file
has no `#:schema` line.

## Component changes

| Template | This tree | Why |
| --- | --- | --- |
| k8s_gateway for internal DNS | external-dns and the MikroTik webhook | A zone forward would capture static router records. ADR 0003 |
| SOPS/age for app secrets | External Secrets, 1Password SDK; SOPS only for bootstrap. Personal decrypt is the v1 YubiKey PGP fingerprint | ADR 0002 and `docs/sops.md` |
| BGP optional, eBGP (different ASNs) | BGP required, same ASN on both sides | Plan: iBGP to RouterOS 7 |
| Cilium `cni.exclusive: false` | `true` | That flag exists in the template for Multus. Multus is not installed |
| LoadBalancer pool = the whole node CIDR | Pool is `10.45.0.0/16`, separate from the node LAN | v1 already advertised services from that range. Nodes stay on `10.20.0.0/16` |
| Storage left as a follow-up | Rook-Ceph, static NFS class, VolSync | Plan |
| Postgres left as a follow-up | CloudNativePG operator and Barman Cloud plugin; no Cluster is reconciled | Plan. The example Cluster is under `kubernetes/examples/` |
| No metrics stack | kube-prometheus-stack, Alertmanager and Grafana disabled | Alerts go to Forge. Forge already runs Grafana |
| No tuppr | tuppr plus TalosUpgrade and KubernetesUpgrade | Plan. Health checks watch Ceph only, not kopiur |
| Talos tool pin v1.14.4 in `.mise/config.toml` | v1.14.5 in `mise.toml` and `topf.yaml` | Plan pin. Template checkout was one patch behind |
| Flux CLI 2.9.6 and operator chart 0.61.0 | Flux 2.10.0 and charts 0.62.1 | Plan pin. Flux 2.10.0 was released 26 Oct 2026 |
| Envoy Gateway chart 1.9.2 | 1.9.3 | Plan pin |
| external-dns chart 1.23.0 (appVersion 0.23.0) | same chart, image tag `v0.24.0` | Plan pin. The chart's appVersion had not caught the app release |
| cloudflared tunnel secret from a local JSON file | ExternalSecret `TUNNEL_TOKEN` | No tunnel JSON in a public repo |
| Deploy key for private git | No deploy key | This repo is public. Flux clones over HTTPS with no pull secret |
| `gateways.dns` VIP for k8s_gateway | Removed | The router is the internal resolver |
| Full Flux controller patch set | A shorter set: HelmRelease defaults, concurrency, in-memory kustomize, sops-age secret | The longer flag list was not re-checked against Flux 2.10 |
| spegel, reloader, metrics-server, CoreDNS, echo | Kept | They are part of the template's running cluster, and the plan calls the template the base |

## Deliberately not done

- `mise run configure`, `topf secrets`, `topf render`, and `helmfile sync` were not run. They create secrets or need a cluster.
- `.sops.yaml` lists the YubiKey fingerprint only. No age recipient is committed, and no `*.sops.yaml` ciphertext is committed.
- Gateway API YAML is not copied into git. The Envoy Gateway chart is the CRD source. The plan's Gateway API version is v1.6.3; the chart is expected to carry the channel it was built for.
- The VolSync OCI tag `0.17.0` matches the app release. The registry was not queried from this environment (GHCR token requests returned 403), so the tag still needs a confirmation on first install.
- Taskfile from v1 is gone. The template uses mise. `mise.toml` has validate tasks and does not wrap bootstrap.
