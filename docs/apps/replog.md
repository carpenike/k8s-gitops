# replog

The family workout log from [carpenike/replog](https://github.com/carpenike/replog),
at `https://replog.${SECRET_DOMAIN}` (`replog.holthome.net`). The HTTPRoute
parents `envoy-internal` only. `mikrotik-dns` publishes the name.
`cloudflare-dns` watches `envoy-external`, so the hostname is not public.

Manifests: `kubernetes/apps/replog/`. The layout follows
[homelab-mcp.md](homelab-mcp.md): one namespace, an app-template HelmRelease,
an ExternalSecret from ClusterSecretStore `onepassword`, a native HTTPRoute,
a ServiceMonitor, and a VolSync restic source on its own Kustomization.

## What runs

One replica, `Recreate`. The database is SQLite in WAL mode
(`modernc.org/sqlite`). The file is `/data/replog.db` on PVC `replog-data`:
storage class `ceph-block` (Ceph RBD), `ReadWriteOnce`, 5Gi. Avatars are
`/data/avatars` on the same volume. There is no Postgres and no CephFS.

The container listens on `:8080`. `REPLOG_BASE_URL` is
`https://replog.${SECRET_DOMAIN}`, so session cookies are `Secure`.
`REPLOG_LOG_FORMAT=json`. `REPLOG_METRICS_ENABLED=true` serves `GET /metrics`
on the same port. `REPLOG_TRUSTED_PROXIES` is the pod CIDR `10.42.0.0/16`,
because only the `envoy-internal` proxies can open 8080.

Pocket ID and the MCP server stay off. There is no separate MCP flag. The
process serves `/api/mcp` and its OAuth authorization server only when
`REPLOG_OIDC_ISSUER`, `REPLOG_OIDC_CLIENT_ID` and `REPLOG_OIDC_CLIENT_SECRET`
are all set. Those three are commented out in the HelmRelease and the
ExternalSecret. The password in the ExternalSecret is the only login. The
route is labelled `gateway.holthome.net/auth: native`, the same label
homelab-mcp uses, so the gateway does not ask for a Pocket ID login in
front of the app ([gateway-auth.md](../platform/gateway-auth.md)). An MCP
client cannot complete that gateway login either, so the label is already
the one MCP needs.

## Turning MCP on later

Importing a coach program through an AI conversation uses the native MCP
server at `/api/mcp`. homelab-mcp is one native route with a 300 second
timeout, because streamable HTTP holds the request open, and a
ReferenceGrant so `pocket-id-exempt` can select it. This route is that
shape on `envoy-internal` only. The `mcp` rule in `httproute.yaml` is
commented. It is a `PathPrefix` match on `/api/mcp`, which is more specific
than the `app` rule, so uncommenting it attaches the path without editing
the SPA rule. `/.well-known/oauth-*` and `/oauth/*` stay on the `app` rule.
Do not add `envoy-external`.

Uncomment, in this order:

1. HelmRelease env: `REPLOG_OIDC_ISSUER` (`https://id.${SECRET_DOMAIN}`),
   `REPLOG_OIDC_CLIENT_ID` (`replog`), and `REPLOG_OIDC_REDIRECT_URL`
   (`https://replog.${SECRET_DOMAIN}/auth/oidc/callback`).
2. ExternalSecret: template key `REPLOG_OIDC_CLIENT_SECRET` and remoteRef
   `replog/oidc_client_secret`. Create that 1Password field then, not before.
3. HTTPRoute rule `mcp`.
4. Egress to `id.${SECRET_DOMAIN}` on 443. Put it in the HelmRelease
   `rawResources`, as homelab-mcp does, not in `ciliumnetworkpolicy.yaml`.

In Pocket ID, the confidential client needs two redirect URIs: the web
callback above, and `https://replog.${SECRET_DOMAIN}/oauth/callback`. The
authorization server also refuses a token until that user has MCP enabled
in the app (`PUT /api/users/{id}/mcp`). The binary's redirect allowlist is
Claude, VS Code, and localhost. It is not an environment variable.

The image is `gcr.io/distroless/static-debian12:nonroot` (uid 65532) and has
no shell. `fsGroup: 65532` makes `/data` writable. homelab-mcp instead runs a
root init container that `chown`s its volume, because that process refuses a
group-writable directory and its image has a shell. replog does neither.

Probes: startup and liveness are `GET /healthz`. Readiness is `GET /readyz`,
which pings the database. The image's Docker `HEALTHCHECK` is
`/replog healthcheck`, which calls the same `/healthz`.

Egress is cluster DNS only. Turning OIDC on later means an allow to
`id.${SECRET_DOMAIN}:443`, and that rule has to move into the HelmRelease
(`rawResources`) because kubeconform rejects `${SECRET_DOMAIN}` in a
`toFQDNs` name. Notification URLs saved in the admin UI also need an egress
rule for the host they call. Nothing in the pod can open those today.

## Image

GoReleaser publishes `ghcr.io/carpenike/replog` only on `v*` tags, and there
is no release yet. The HelmRelease tag is `v0.0.0`, which will not pull.
Replace it with the first release, tag and digest, before the pod can start.
Renovate's helm-values manager sees the image, and `.renovaterc.json5`
disables it until that pin exists. This repo does not use a Flux
ImagePolicy. homelab-mcp's image is a `sha-` tag pinned by hand for the
same reason: the self-built-images group follows a floating tag.

## 1Password

Create item `replog` in vault `k8s-secrets` before the Kustomization
reconciles. ClusterSecretStore `onepassword`. ExternalSecret `replog` writes
Secret `replog-env`. Do not use `admin` / `admin`.

| Field | Secret key | Notes |
| --- | --- | --- |
| `secret_key` | `REPLOG_SECRET_KEY` | `openssl rand -base64 32`. Read on every start and written into the database. Changing it later makes settings encrypted with the old key unreadable |
| `admin_user` | `REPLOG_ADMIN_USER` | Created only when the users table is empty |
| `admin_pass` | `REPLOG_ADMIN_PASS` | Same. A later edit of this field does not change the login |
| `admin_email` | `REPLOG_ADMIN_EMAIL` | Same |

Field `oidc_client_secret` is not part of this deploy. Add it when MCP is
turned on ([above](#turning-mcp-on-later)). The backup reads the existing
item `volsync-r2-template`. No new field there.
The restic repository path is `<REPOSITORY_TEMPLATE>/replog`.

## Backup

VolSync `ReplicationSource` `replog`, `copyMethod: Snapshot`, volume snapshot
class `csi-ceph-block`, every 6 hours at minute 20. Restic reads the Ceph RBD
snapshot, not the live files. A block snapshot is crash-consistent, and
SQLite replays the WAL on restore. Do not copy `replog.db`, `replog.db-wal`
or `replog.db-shm` off the mounted volume while the process is running.

Keep 7 daily and 4 weekly. The mover runs as uid 65532, the same as the pod.

To restore: scale the Deployment to 0, restore the snapshot onto
`replog-data`, delete any leftover `replog.db-wal` and `replog.db-shm` from
the broken copy, and scale back to 1. The log should say the secret key was
loaded and should not say it bootstrapped a new admin. If
`REPLOG_SECRET_KEY` is set, the restored database needs the same value.

## Monitoring

ServiceMonitor `replog` scrapes `GET /metrics` on port 8080 every 60 seconds.
`/metrics` is also reachable on the internal hostname, because the process
has one listener. It is not on `envoy-external`.

`ReplogDown` fires when that scrape is missing for 10 minutes, including a
pod that failed `/readyz` and left the Service. It will fire while the image
tag is still the placeholder.
