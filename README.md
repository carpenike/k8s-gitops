# k8s-gitops

GitOps for a four-sled Talos cluster. Three nodes are schedulable control
planes. One node is a worker. All four run Rook-Ceph OSDs.

The previous tree is the tag `archive/talos-v1`. This branch replaces it.
Nothing here is applied to hardware yet.

## Layout

| Path | Role |
| --- | --- |
| `kubernetes/apps` | Flux sync root |
| `talos/` | topf inventory and machine patches |
| `bootstrap/helmfile` | Cilium, CoreDNS, spegel, cert-manager, Flux Operator |
| `cluster.example.toml` | Placeholder inputs. Not a live config |
| `docs/` | Architecture, decisions, lessons, open placeholders |
| `AGENTS.md` | Canonical instructions for coding agents |

`kubernetes/examples/` is documentation in YAML. Flux does not reconcile it.

## Versions

Pinned from the rebuild plan (checked 27 Oct 2026): Talos v1.14.5,
Kubernetes v1.37.1, Flux 2.10.0 with Flux Operator chart 0.62.1, Cilium
1.20.4, Envoy Gateway 1.9.3, cert-manager v1.21.3, external-dns v0.24.0,
MikroTik webhook v1.6.3, External Secrets chart 2.14.0, Rook 1.21.1,
CloudNativePG chart 0.29.1 (app 1.30.1), Barman Cloud plugin chart 0.8.1
(app v0.15.1), VolSync chart 0.17.0, kube-prometheus-stack 92.14.0.
Renovate owns the bumps after that. See `docs/architecture.md`.

## Validate

```sh
bash scripts/validate.sh
```

Needs `yamllint`, `kustomize`, `kubeconform`, and `gitleaks` on `PATH`.
`mise.toml` lists the Kubernetes tools. The workflow
`.github/workflows/validate.yaml` runs the same checks without secrets.

## Not in git

Age keys, Talos secrets, the 1Password service-account token, Cloudflare
tokens, the tunnel token, MikroTik credentials, and real hostnames.
Node and LoadBalancer ranges are recorded in `docs/architecture.md`.
The list of blanks to fill is `docs/placeholders.md`.
