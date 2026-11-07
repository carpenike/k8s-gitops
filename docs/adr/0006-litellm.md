---
status: proposed
date: 2026-10-30
decision-makers: Ryan Holt
---

# LiteLLM on the Talos cluster

## Context and Problem Statement

LiteLLM runs on Forge as `podman-litellm.service`. Forge is loaded and
overheating. The proxy fronts cloud models and does not need a GPU. The
cluster already has Flux, Envoy Gateway, External Secrets, Rook-Ceph,
CloudNativePG, and Prometheus. No PostgreSQL `Cluster` was reconciled
before this change. ADR 0001 keeps GPU, USB, and chassis-survival
workloads on Forge. This proxy is not one of those.

## Decision Drivers

- The model list, master key, and salt key have to match Forge so virtual
  keys and stored credentials keep working
- One PostgreSQL operator, already installed
- App secrets stay in 1Password
- The public repository cannot hold key material
- API clients send a bearer key and cannot complete a browser login
- The qualified image is `ghcr.io/berriai/litellm` v1.100.1 at the digest
  in Forge's `hosts/forge/services/litellm.nix`

## Considered Options

- Official chart `oci://ghcr.io/berriai/litellm-helm`
- Plain Deployments
- `app-template` 5.3.0, the chart already used for cloudflared

## Decision Outcome

Chosen option: "`app-template` 5.3.0, database `litellm` on Cluster
`postgres17`", because the chart already matches how this repo runs a
single container, and the official chart's defaults fight the platform.

The route `litellm.${SECRET_DOMAIN}` parents only `envoy-internal` and is
labeled `gateway.holthome.net/auth: native`. Forge does not put Caddy's
portal in front of this vhost. The Admin UI keeps LiteLLM's own Pocket ID
client. API paths and the UI share that opt-out: a gateway login on the
UI would still break `/sso/callback` unless that path were split out, and
the UI already has a login.

One replica. The process applies Prisma migrations when it starts. The
official chart scales by moving migrations into a job. That job is not
wired here.

`/health/liveliness` and `/health/readiness` are the probes. Both answer
without a key. `GET /health` calls each model and needs a key, so it is
not a probe. `/metrics` needs the master key. The ServiceMonitor sends
that key.

Daily volume snapshots use class `csi-ceph-block`. They stay on Ceph.
Barman Cloud stays off until the placeholder bucket in
`kubernetes/examples/cnpg-cluster.yaml` is a real endpoint. Attaching it
now would point WAL at `s3.example.invalid`.

The Atrium admission hook stays on Forge. It is an in-process callback
plus files published on that host. This deployment does not mount it.
Cutover of `llm.holthome.net` waits on that. The procedure is in
[litellm.md](../litellm.md).

### Consequences

- Good, because a sled failure is not a Forge failure for clients that
  have moved, and Forge stops spending CPU on this process after cutover
- Bad, because a chassis failure takes the proxy down with the cluster
- Bad, because Atrium and Whiskey still require the Forge container until
  the admission hook moves
- The salt key is copied once and then left unchanged

## Pros and Cons of the Options

### Official LiteLLM Helm chart

- Good, because it has a migration job, a ServiceMonitor, and an external
  database switch
- Bad, because the chart still defaults to a Bitnami PostgreSQL subchart
  and a Redis dependency, and this cluster has one CloudNativePG operator
  and no Redis
- Bad, because published chart appVersions lag the v1.100.1 digest Atrium
  is qualified against, and the chart's image default has disagreed with
  the current image docs (`litellm-database` versus `litellm`)
- The HTTPRoute, the Pocket ID opt-out, and the ExternalSecret would sit
  beside the chart anyway

### Plain manifests

- Good, because nothing is hidden in a values file
- Bad, because probes, resources, config mounts, and the ServiceMonitor
  are already expressed once in `app-template`

### app-template 5.3.0

- Good, because cloudflared already pins this chart, and Renovate already
  bumps that tag
- Good, because the model file stays a ConfigMap and every secret stays an
  `os.environ` reference
- Bad, because replicas stay at 1 until a migration job exists
- Bad, because the stock image is run as root so Prisma can write its
  tree, which is the same reason Forge's module sets `runAsRoot`
