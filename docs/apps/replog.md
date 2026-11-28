# replog

The family workout log from [carpenike/replog](https://github.com/carpenike/replog).
It already runs on Forge, public at `https://replog.holthome.net`
(`replog.${SECRET_DOMAIN}`). This is that instance moving onto the cluster.
Nothing here changes Forge, DNS, or Cloudflare. The cutover does, and it
is written out below.

Manifests: `kubernetes/apps/replog/`. The layout follows
[homelab-mcp.md](homelab-mcp.md), including the public route from the
Forge move ([k8s-gitops #5765](https://github.com/carpenike/k8s-gitops/pull/5765)).

## What Forge runs today

`hosts/forge/services/replog.nix` in carpenike/nix-config.

| | |
| --- | --- |
| Hostname | `replog.${config.networking.domain}`, which is `replog.holthome.net` |
| Exposure | Cloudflare tunnel `forge`, then Caddy, then the binary. The Caddy vhost is a pass-through: `cloudflare.enable`, `tunnel = "forge"`, no caddySecurity. DNS registration is the module default, a CNAME to that tunnel's `cfargotunnel.com` name |
| Listen | `127.0.0.1:5008` |
| Data | `/var/lib/replog/replog.db` and `/var/lib/replog/avatars/` on ZFS dataset `tank/services/replog` |
| Package | `inputs.replog.packages.<system>.default`, the Nix build of the flake. Not a container |
| Backups | Sanoid on that dataset, and a restic job of `/var/lib/replog` from a ZFS snapshot |
| OIDC | `REPLOG_OIDC_ISSUER=https://id.<domain>`, `REPLOG_OIDC_CLIENT_ID=replog`. The secret is sops key `replog/oidc_client_secret` |
| Sops keys | `replog/admin_user`, `replog/admin_pass`, `replog/admin_email`, `replog/secret_key`, `replog/oidc_client_secret`, assembled into EnvironmentFile `replog-env` |

The binary binds loopback because Caddy is on the same machine, and
`REPLOG_TRUSTED_PROXIES` is `127.0.0.1/32,::1/128` for that reason. Neither
belongs in the cluster: Envoy is another pod. The listen here is `:8080`
and the trusted proxies are the pod CIDR `10.42.0.0/16`.

Nothing else in the Forge module or the Go config names a Forge address.
The Nix comment about `REPLOG_WEBAUTHN_*` is stale. ADR 019 removed
passkeys, and `nix/lib/derive-baseurl.nix` now sets only `REPLOG_BASE_URL`.
The healthcheck dials `127.0.0.1` inside the process, which is the
container, not Forge.

Website login is Pocket ID, the same issuer and client id Forge sets.
The client secret is copied from Forge's sops key.

## What runs here

One replica, `Recreate`. SQLite in WAL mode
(`modernc.org/sqlite`) at `/data/replog.db` on PVC `replog-data`:
class `ceph-block` (Ceph RBD), `ReadWriteOnce`, 5Gi. Avatars are
`/data/avatars` on the same volume. There is no Postgres.

Form-check clips (carpenike/replog#62) are on their own PVC,
`replog-videos`: class `ceph-filesystem` (CephFS), `ReadWriteMany`, 20Gi,
mounted at `/videos`, with `REPLOG_VIDEO_DIR=/videos`. The image's default
is `/data/videos`, which would put clips on the database volume. An image
built before #62 ignores the variable, and the volume stays empty, so the
deploy change is safe in either order.

`REPLOG_VIDEO_MAX_MB` is 95, not the app's default 100. Envoy streams
request bodies and sets no size cap, but the public name is behind
Cloudflare, which refuses bodies over 100 MB on this plan, and a 100 MiB
clip plus multipart overhead is over that. HTTPRoute rule `video-upload`
matches `POST /api/athletes/*/workouts/*/sets/*/video` and gives it 900
seconds instead of 300, for a slow uplink.

Web Push rest alerts (also #62) send from the pod to the browser push
services in replog's `DefaultAllowedHosts`. The pod's network policy
allows 443 to `fcm.googleapis.com`, `android.googleapis.com`,
`*.push.apple.com`, `*.push.services.mozilla.com` and
`*.notify.windows.com`. VAPID keys are generated on first start and kept
in the database, so no new 1Password field. Video share links (`/s/*`,
`/api/share/*`) are public by design and go through rule `app`.
The database starts empty. Forge's files are not copied.

`REPLOG_BASE_URL` is `https://replog.${SECRET_DOMAIN}`.
`REPLOG_LOG_FORMAT=json`. `REPLOG_METRICS_ENABLED=true` serves `GET /metrics`
on port 8080.

The HTTPRoute is native on `envoy-external` and `envoy-internal`, with a
ReferenceGrant, which is homelab-mcp's public route. The website rule is
a prefix match on `/`. Rule `deny-mcp` is a longer prefix, `/api/mcp`,
and HTTPRouteFilter `replog-deny-mcp` makes Envoy answer 404. That
request has no backend, so the pod never sees it.

The image is distroless, uid 65532, and has no shell. `fsGroup: 65532`
makes `/data` writable.

Egress is cluster DNS and `id.${SECRET_DOMAIN}:443` for the website's
Pocket ID login. That name is in the HelmRelease `rawResources`, because
kubeconform rejects `${SECRET_DOMAIN}` in a `toFQDNs` match. A notification
URL saved in the admin UI needs its own allow before it can be reached.

## Agents

homelab-mcp's `/mcp/replog` view calls this Service in-cluster at
`replog.replog.svc:8080`. That view is `credentials: "per_user"`, so the
bearer is the file `replog.ryan` from item `homelab-mcp-user-credentials`
in vault `k8s-secrets` (Ryan's alias in `HOMELAB_MCP_USERS`). It does not
fall back to the shared token. Item `homelab-mcp`, field `replog_token`,
stays: ExternalSecret `homelab-mcp` still writes it into Secret
`homelab-mcp-env` as `HOMELAB_MCP_REPLOG_TOKEN` for shared-mode calls.
The replog CiliumNetworkPolicy admits the homelab-mcp
pods on port 8080 only, and the homelab-mcp policy allows that egress.

The binary still mounts `/api/mcp` when the website OIDC settings are
set, because it has no separate switch. The public route does not
forward it: rule `deny-mcp` matches `PathPrefix` `/api/mcp` and returns
404. The website rule is `PathPrefix` `/`, which would otherwise include
that path.

## Image

The HelmRelease pins
`ghcr.io/carpenike/replog:sha-7f52207d2a05d806981852e34752b68fa43986b3@sha256:f3ea0d31a0023060aa50d65c9e669533b15d2b6cef5b10b8c4921c352c93979a`.
Renovate tracks that image with the other `ghcr.io/carpenike` images.
This repo has no Flux ImagePolicy. Merging does not move
`replog.holthome.net` off Forge.

The app runs its goose migrations on start, so a new image migrates the
SQLite database on the RBD volume before it serves. Image `7f52207`
(replog#65, ADR 028) adds migration 0028: nullable
`workouts.program_week`/`program_day`. RepLog stores the program day each
session really was, from backfill `program_week`/`program_day` or a live
session start, and plan-vs-done compares against that template day. Rows
from before 0028 keep the day counted from earlier sessions. Check the
version with `kubectl -n replog logs deploy/replog | grep goose` (expect
`version: 28`).

## 1Password

Create item `replog` in vault `k8s-secrets` before the Kustomization
reconciles. ClusterSecretStore `onepassword`. ExternalSecret `replog`
writes Secret `replog-env`. Field names are Forge's sops keys. Do not use
`admin` / `admin`.

| Field | Secret key | What to put |
| --- | --- | --- |
| `secret_key` | `REPLOG_SECRET_KEY` | A new key, `openssl rand -base64 32`. Do not copy Forge's `replog/secret_key`. The cluster database is empty, so the old key has nothing to decrypt |
| `admin_user` | `REPLOG_ADMIN_USER` | A new bootstrap username. Read only while the users table is empty |
| `admin_pass` | `REPLOG_ADMIN_PASS` | A new bootstrap password. Same |
| `admin_email` | `REPLOG_ADMIN_EMAIL` | A new bootstrap email. Same |
| `oidc_client_secret` | `REPLOG_OIDC_CLIENT_SECRET` | Copy Forge's sops value `replog/oidc_client_secret`. That is the existing Pocket ID client `replog` for the website. A new secret would not match the client |
| `service_token` | `REPLOG_SERVICE_TOKEN` | Coach service token. It must start with `rlcst_`, and the characters after that prefix must be at least 16 printable ASCII characters with no spaces. Not a Forge key. The value stays in 1Password. The bootstrap admin is a coach, so `REPLOG_SERVICE_USER` is not set |
| `on_behalf_public_key` | `REPLOG_ON_BEHALF_JWT_PUBLIC_KEY` | Ed25519 public key (PEM) that verifies homelab-mcp's signed 60-second on-behalf tokens (ADR 025 amendment). Public. The private half is item `homelab-mcp`, field `replog_signing_private_key`. `REPLOG_ON_BEHALF_MODE` is `signed` in the HelmRelease; the shared on-behalf credential was removed 2026-11-22 |

The backup reads the existing item `volsync-r2-template`. No new field.
The restic repository path is `<REPOSITORY_TEMPLATE>/replog`.

## Cutover

Do this in order. Do not merge this while Forge should keep the name,
unless the route is understood: external-dns will not take a record it
does not own (TXT prefix `k8s.`), so the HTTPRoute alone does not move
DNS. Deleting Forge's record does.

1. Optional. On Forge, while it is still up, export JSON from the app if
   any of the current workouts are worth keeping. The cluster database
   starts empty. There is no copy of `/var/lib/replog`.
2. On Forge: `systemctl stop replog` and `systemctl mask replog`.
3. Merge. The image is already pinned and `replicas` is already 1.
   Merging does not move `replog.holthome.net` off Forge.
4. Verify `https://replog.holthome.net/healthz` only after step 5. Until
   then the name still belongs to Forge, and Forge is stopped, so the
   name will not answer. Check the pod with a port-forward first.
5. nix-config pull request: remove `services.replog`, the Caddy vhost
   `replog`, and that hostname from tunnel `forge`. Then delete the
   Cloudflare record for `replog.holthome.net`. It is the CNAME the Caddy
   module registered at the tunnel's `cfargotunnel.com` target
   (`cloudflare.dns.register` defaults to true, record type falls back to
   the tunnel default, which is a CNAME). external-dns then publishes the
   name to the cluster tunnel, proxied, because the route parents
   `envoy-external`.

Rollback, before the DNS record is deleted: set `replicas: 0`, unmask and
start `replog` on Forge. The CNAME still points at tunnel `forge`.

Rollback, after the record is deleted: set `replicas: 0`, restore the
nix-config (vhost and tunnel ingress), and let that module recreate the
CNAME. Do not hand-edit Cloudflare from this repo.

## Backup

VolSync `ReplicationSource` `replog`, `copyMethod: Snapshot`, volume
snapshot class `csi-ceph-block`, every 6 hours at minute 20. Restic reads
the Ceph RBD snapshot, not the live files. A block snapshot is
crash-consistent, and SQLite replays the WAL on restore.

Keep 7 daily and 4 weekly. The mover runs as uid 65532.

Clips: `ReplicationSource` `replog-videos`, `copyMethod: Snapshot`, volume
snapshot class `csi-ceph-filesystem`, nightly at 03:50 UTC, to restic path
`<REPOSITORY_TEMPLATE>/replog-videos` (ExternalSecret
`replog-videos-volsync`, same 1Password item). Keep 7 daily and 4 weekly.
The rows that name the clips are in `replog-data`, which runs more often,
so a restore can have a row whose clip is newer than the last nightly run.

To restore a cluster backup: scale the Deployment to 0, restore the
snapshot onto `replog-data`, delete any leftover `-wal` and `-shm` from
the broken copy, and scale back to 1. The new `REPLOG_SECRET_KEY` has to
be the one this database was created with.

## Monitoring

ServiceMonitor `replog` scrapes `GET /metrics` on port 8080 every 60
seconds. That path is on the public route too, because the process has
one listener. Forge did not expose a separate metrics port either.

`ReplogDown` stays quiet while `replicas` is 0. It fires when a running
Deployment has had no scrape for 10 minutes.
