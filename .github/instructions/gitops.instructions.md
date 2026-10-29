---
description: Flux layout and manifest rules for the rebuild
applyTo: "kubernetes/**/*.yaml,kubernetes/**/*.yml,bootstrap/**/*.yaml"
---

# GitOps manifests

`AGENTS.md` is canonical. This file is the path-scoped supplement, using the
`applyTo` frontmatter from hve-core `.github/instructions/README.md`.

- One Flux Kustomization per app, under `kubernetes/apps/<namespace>/<app>/ks.yaml`.
- The app directory holds `helmrelease.yaml`, `ocirepository.yaml`, and a kustomization.
- Chart versions are the OCIRepository tag. Renovate bumps them. Do not float `latest`.
- `kubernetes/apps` has no root `kustomization.yaml`. Flux generates one and includes each child directory that has its own file. That is the cluster-template behavior.
- `kubernetes/examples/` is not on the Flux path. Do not point a Kustomization at it.
- Gateway API routes for public apps use `envoy-external`. Everything else uses `envoy-internal`.
- Cilium is the primary CNI. Multus (`kube-system/multus`) is the meta-plugin in front of it for a second interface (ADR 0006). Do not add another primary CNI, a second ingress controller, or a second secrets operator.
