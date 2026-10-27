# Headlamp

[Headlamp](https://headlamp.dev) is the Kubernetes dashboard. It is installed
from the official chart on
`https://kubernetes-sigs.github.io/headlamp/`, chart `0.46.0`.

Open it at `https://headlamp.holthome.net`. The HTTPRoute's only parent is
`envoy-internal`. `mikrotik-dns` publishes routes on that gateway.
`cloudflare-dns` publishes `envoy-external` only, so this name stays off
Cloudflare.

## Who can open it

The route has no `gateway.holthome.net/auth` label, so the gateway's Pocket
ID policy applies. Headlamp's own OIDC is not configured. That would need
OIDC flags on the Talos API server.

## What it can do in the cluster

It is read-only. The chart creates ServiceAccount `headlamp` and a
ClusterRoleBinding named `headlamp-admin` (the chart always uses that
suffix) to the built-in ClusterRole `view`. `view` cannot read Secrets.

The chart's in-cluster mode does not hand that token to the UI by itself.
`config.unsafeUseServiceAccountToken` is the chart setting that does: every
Headlamp user acts as the pod ServiceAccount, and the UI does not ask for a
token. The chart marks that flag unsafe unless an auth proxy sits in front.
Pocket ID on `envoy-internal` is that proxy, and the account is only `view`.

ClusterRole `headlamp-flux-view` adds get, list, and watch on Flux
Kustomizations, HelmReleases, and source objects (GitRepository,
OCIRepository, HelmRepository, HelmChart, Bucket). It is aggregated into
`view`, so the Flux plugin can list them. The same role is also labeled
`aggregate-to-edit`, which does nothing until the binding below changes.

The Flux plugin is `headlamp_flux` 0.7.0 from Artifact Hub, installed by
the chart's `pluginsManager` sidecar.

## Granting write later

In `kubernetes/apps/headlamp/headlamp/app/helmrelease.yaml`, change
`clusterRoleBinding.clusterRoleName` from `view` to `edit`. `edit` can
change most objects and can read Secrets. Flux reads stay, because
`headlamp-flux-view` is aggregated into `edit` as well. Use `admin` only
when `edit` is not enough. Leave the binding on `view` to stay read-only.
