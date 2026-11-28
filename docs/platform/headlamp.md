# Headlamp

[Headlamp](https://headlamp.dev) is the Kubernetes dashboard. It is installed
from the official chart on
`https://kubernetes-sigs.github.io/headlamp/`, chart `0.46.0`.

Open it at `https://headlamp.holthome.net`. The HTTPRoute's only parent is
`envoy-internal`. `mikrotik-dns` publishes that name as an A record for
`10.45.10.50`. `cloudflare-dns` publishes `envoy-external` only, so this
name stays off Cloudflare.

## Login

Headlamp has its own Pocket ID client, client id `headlamp`, and sends the
person's ID token to the API server. The API server checks that token
itself, so every request in the cluster is that person, and RBAC applies
to them, not to a shared ServiceAccount.

- The route is labelled `gateway.holthome.net/auth: native`, so the
  gateway's Pocket ID login is replaced by Headlamp's (one login per
  route, [gateway-auth.md](gateway-auth.md)). ReferenceGrant
  `headlamp-gateway-auth` lets `pocket-id-exempt` select it.
- `OIDC_AUTO_LOGIN` sends a visitor straight to Pocket ID. The callback is
  `https://headlamp.holthome.net/oidc-callback`, with PKCE.
- Scopes `openid`, `profile`, `email`, `groups`.
- Secret `headlamp-oidc` holds the client id, the issuer and the scopes,
  plus the client secret from 1Password item `headlamp`, field
  `oidc_client_secret` (vault `k8s-secrets`).

## API server

`talos/control-plane/20-authentication.yaml` is the API server's
`KubeAuthenticationConfig`. It trusts issuer `https://id.holthome.net` for
audience `headlamp`.

- Username: claim `preferred_username`, prefix `oidc:`. A Pocket ID user
  `ryan` is Kubernetes user `oidc:ryan`.
- Groups: claim `groups`, prefix `oidc:`. Pocket ID group `admins` is
  Kubernetes group `oidc:admins`.
- The prefix keeps a Pocket ID name from matching any `system:` user or
  group.
- The document is the whole authentication config. Its `anonymous` block is
  Talos's default (`/livez`, `/readyz`, `/healthz`), kept on purpose.

`preferred_username` and not `email`: the API server refuses an `email`
username when the token's `email_verified` is false.

## Who can do what

| Kubernetes subject | Binding | Rights |
| --- | --- | --- |
| Group `oidc:admins` (Pocket ID `admins`) | ClusterRoleBinding `oidc-admins-cluster-admin` | `cluster-admin` |
| Any other Pocket ID user | none | Logs in, sees nothing |
| ServiceAccount `headlamp` | none (`clusterRoleBinding.create: false`) | Nothing. The UI does not use it |

To give someone read-only, bind ClusterRole `view` to `oidc:<username>` or
to a new Pocket ID group. ClusterRole `headlamp-flux-view` is aggregated
into `view` and `edit`, so the Flux plugin works for those roles too.

The Flux plugin is `headlamp_flux` 0.7.0 from Artifact Hub, installed by
the chart's `pluginsManager` sidecar.

## Rollout order

The API server must trust the token before Headlamp starts sending it.

1. In Pocket ID (`https://id.holthome.net`), create an OIDC client with
   client id `headlamp`, callback
   `https://headlamp.holthome.net/oidc-callback`, PKCE on. Allow group
   `admins` (and any other group that should reach the login).
2. Save its client secret in 1Password item `headlamp`, field
   `oidc_client_secret`, vault `k8s-secrets`.
3. Apply the Talos config to each control plane (`sled-0`, `sled-1`,
   `sled-2`) from `talos/` with `topf apply --mode no-reboot`. The node
   does not reboot, but Talos restarts the kube-apiserver static pod, and
   topf does one control plane at a time. Check with
   `talosctl -n <sled> read /system/config/kubernetes/kube-apiserver/authentication-config.yaml`.
4. Merge this repo change. Flux creates `headlamp-oidc`, the
   ReferenceGrant and the binding, and rolls the pod.

Until step 3 is on all three control planes, a login succeeds and every
API call returns 401. Until step 2, the ExternalSecret is not ready and
the Kustomization health check fails.

## kubectl

The same issuer can serve kubectl through
[kubelogin](https://github.com/int128/kubelogin). Add the new client's id
to `audiences` in `20-authentication.yaml`. That is not set up.
