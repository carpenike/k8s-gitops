# Grafana and Grafana OnCall

Grafana and Grafana OnCall move from Forge into namespace `grafana`.
Alertmanager, Prometheus and Loki stay on Forge, outside the cluster, so
something still watches the cluster when the cluster is down. Grafana reads
Forge's Prometheus and Loki through Forge's Caddy, and Forge's Alertmanager
posts to OnCall here.

Forge keeps serving both until the cutover below. Source for everything
Forge-side: `carpenike/nix-config` `main`,
`hosts/forge/infrastructure/observability/grafana.nix`,
`modules/nixos/services/grafana`, `hosts/forge/services/grafana-oncall.nix`
and `modules/nixos/services/grafana-oncall`.

## What runs

| Kustomization | Path | What |
| --- | --- | --- |
| `grafana-dashboards` | `kubernetes/apps/grafana/grafana/dashboards` | Dashboard ConfigMaps and the provider file. No postBuild: the JSON has Grafana's own `$__timeFilter` and `${child:sqlstring}` |
| `grafana` | `kubernetes/apps/grafana/grafana/app` | Grafana, its PVC, secrets, route, alert |
| `grafana-backup` | `kubernetes/apps/grafana/grafana/backup` | VolSync of `grafana-data` |
| `grafana-oncall` | `kubernetes/apps/grafana/grafana-oncall/app` | OnCall engine, Celery, Redis, route, alerts |
| `grafana-oncall-plugin-setup` | `kubernetes/apps/grafana/grafana-oncall/plugin-setup` | Job that connects Grafana's OnCall plugin to the engine |
| `grafana-oncall-backup` | `kubernetes/apps/grafana/grafana-oncall/backup` | VolSync of `grafana-oncall-data` |

Namespace `grafana`, not `observability`. `observability` is privileged
Pod Security for node-exporter, and the namespace-wide default deny
(`kubernetes/apps/grafana/ciliumnetworkpolicy.yaml`) would cut off
kube-prometheus-stack there. Here every pod runs as a fixed non-root uid
with no capabilities, so the namespace enforces `restricted`.

### Grafana

- `docker.io/grafana/grafana:12.3.11`, pinned by digest, one replica,
  `Recreate`, app-template 5.3.0. Forge runs nixpkgs `nixos-25.11`'s
  `grafana` 12.3.6+security-01 (`flake.lock` input `nixpkgs_3`, rev
  `b6018f87`, `pkgs/servers/monitoring/grafana/default.nix`). The copied
  database needs the same or a newer Grafana, and 12.3.11 is the newest
  12.3 patch. Grafana does not migrate a database down: never pin below
  Forge, and check Forge's running version before the cutover.
- uid and gid 472 (the image's `grafana` user). PVC `grafana-data`
  (`ceph-block`, 5Gi) at `/var/lib/grafana`: `grafana.db` and the plugins.
- Login: Pocket ID generic OAuth exactly as Forge. Client id `grafana`,
  `https://id.holthome.net/authorize`, `/api/oidc/token`,
  `/api/oidc/userinfo`, scopes `openid profile email groups`, role
  `contains(groups[*], 'admins') && 'Admin' || 'Viewer'`, sign-up off,
  login form off, sign-out to Pocket ID's end-session with
  `post_logout_redirect_uri` back to Grafana. The host is the same, so
  the Pocket ID client's callback `https://grafana.holthome.net/login/generic_oauth`
  does not change.
- Route `grafana.holthome.net` on `envoy-external`, label `native` (one
  login per route, [gateway-auth.md](gateway-auth.md)). Forge publishes
  the same name through its Cloudflare tunnel with no Caddy login, so this
  keeps it public with Grafana's own login.
- Plugins, preinstalled from grafana.com at start (`GF_PLUGINS_PREINSTALL_SYNC`):
  `volkovlabs-echarts-panel@7.2.2` (Business Charts, the version nixpkgs
  pinned for Forge; Household Finance's Sankey) and
  `grafana-oncall-app@1.16.11` (Forge installs it unpinned; this pins the
  engine's version). `GF_PLUGINS_PREINSTALL` is set to the same two, which
  replaces Grafana 12's default background list (the unpinned Drilldown
  apps), and auto-update is off. Forge's `externalServiceAccounts` toggle
  and managed service accounts are on, for the OnCall plugin.
- Turned off because the egress policy would refuse them anyway: usage
  reporting, update checks, the news feed, and Gravatar (Grafana fetches
  avatars server-side).
- Metrics: `/metrics` on 3000, ServiceMonitor `grafana`. Alert
  `GrafanaServiceDown` (Forge's alert name, severity `high`).

### Datasources

Provisioned from Secret `grafana-datasources` (ExternalSecret, because two
carry passwords) at `/etc/grafana/provisioning/datasources`. UIDs and names
are Forge's, so every dashboard, and every row in the copied `grafana.db`,
resolves unchanged.

| Name | UID | URL | Notes |
| --- | --- | --- | --- |
| Prometheus | `auto-prometheus-auto` | `https://prom.holthome.net` | Forge's Prometheus via Caddy. Default. `httpMethod: GET`, because Forge's bypass for the sleds is GET only |
| Loki | `auto-loki-auto` | `https://loki.holthome.net` | Forge's Loki via Caddy. Forge's `timeout: 120`, `maxLines: 5000` |
| Prometheus (k8s) | `k8s-prometheus` | `http://kube-prometheus-stack-prometheus.observability.svc.cluster.local:9090` | This cluster's Prometheus. New; no Forge dashboard uses it |
| Schoolhouse | `schoolhouse` | `postgres17-rw.cnpg-system.svc.cluster.local:5432`, db `schoolhouse`, user `schoolhouse_grafana`, `sslmode=require` | [postgres17.md](postgres17.md) |
| Household Finance | `household-finance` | same host, db `homelab_finance`, user `homelab_finance_grafana`, `sslmode=require` | [postgres17.md](postgres17.md) |

Forge's `auto-*` UIDs come from its module: a datasource without a `uid`
gets `auto-<key>`, and the keys are `prometheus-auto` and `loki-auto`.

Forge also provisions datasources this cluster does not: `Alertmanager`
(uid `alertmanager`, Forge's loopback Alertmanager), `TeslaMate` (uid
`TeslaMate`) and `Tracearr` (uid `postgres-tracearr-1`), both on Forge's
local PostgreSQL at `127.0.0.1`. Their rows come across in `grafana.db`
and fail to connect. TeslaMate's provisioned dashboards (provider
`TeslaMate Dashboards`) are not provisioned here, and Grafana removes a
provider's dashboards once the provider is gone. Keeping them needs
TeslaMate's database reachable from the cluster first.

### Dashboards

ConfigMaps from `kubernetes/apps/grafana/grafana/dashboards`, with Forge's
provider names, folders and dashboard UIDs. Editable in the UI and
rescanned every 60 seconds, as on Forge; the JSON here is the source.

| Provider and folder | Files | From nix-config |
| --- | --- | --- |
| `Household Finance` | `overview.json`, `cashflow-categories.json`, `debt-projects.json`, `data-health.json` | `hosts/forge/services/household-finance-dashboards.nix` |
| `Schoolhouse` | `sync-health.json`, `review-queue.json`, `grades.json`, `work.json` | `hosts/forge/services/schoolhouse-dashboards.nix` |
| `Operation W.W.W.`, folder `Applications` | `whiskey-audience.json`, `whiskey-faro-rum.json` | `hosts/forge/infrastructure/observability/dashboards` |

The JSON was rendered from those Nix files. A later change there has to be
rendered and copied here.

### OnCall

`docker.io/grafana/oncall:v1.16.11` and `docker.io/library/redis:8.10-alpine`,
both at the digests Forge's module pins. OnCall OSS is archived upstream;
this is its last release. Paging now depends on the cluster.

| Controller | Containers | Notes |
| --- | --- | --- |
| `grafana-oncall` | init `migrate` (`python manage.py migrate --noinput`), `engine` (uwsgi on 8080), `celery` (worker with beat) | One pod, because engine and Celery open the same SQLite file and the volume is RWO |
| `redis` | `app` | `--save 60 1 --appendonly yes` on PVC `grafana-oncall-redis`, so queued escalation steps survive a reschedule |

- uid 957, gid 952: Forge's static `grafana-oncall` ids.
- PVC `grafana-oncall-data` (`ceph-block`, 2Gi) at `/var/lib/oncall`: the
  SQLite database (`oncall.db`, the image's default name for
  `DATABASE_TYPE=sqlite3`). Celery beat's schedule is an emptyDir at
  `/var/lib/oncall/celery`.
- Env is the module's: `settings.hobby`, SQLite, Redis broker, Celery
  queues, concurrency 1, beat on, exporter on. `BASE_URL` is
  `https://oncall.holthome.net`. `GRAFANA_API_URL` is
  `http://grafana.grafana.svc.cluster.local:3000`.
- Route `oncall.holthome.net` on `envoy-internal`, label `public`, two
  rules only: `POST /integrations/v1/...` (Forge's Alertmanager) and
  `GET /health/` (an outside check). Everything else in the engine is not
  routed; people use OnCall through the Grafana plugin. A source allowlist
  for Forge would not work: Envoy sees a node address (`externalTrafficPolicy: Cluster`,
  [gateway-auth.md](gateway-auth.md)). The integration token in the path is
  the credential, as it was on Forge.
- Metrics: `/metrics/` on 8080 with bearer `PROMETHEUS_EXPORTER_SECRET`,
  ServiceMonitor `grafana-oncall-engine`.
- Alerts keep Forge's names: `GrafanaOnCallServiceDown`,
  `GrafanaOnCallCeleryServiceDown`, `GrafanaOnCallRedisServiceDown`
  (severity `high`). Forge's Alertmanager routes
  `alertname=~"GrafanaOnCall.*ServiceDown"` straight to Pushover, not to
  OnCall. `GrafanaOnCallPluginSetupFailed` is new.

### Plugin setup Job

Forge's one-shot `grafana-oncall-plugin-setup` unit as Job
`grafana-oncall-plugin-setup` (`setup-plugin.py`). It waits for Grafana and
the engine, then:

- if the plugin is enabled with `onCallApiUrl`
  `http://grafana-oncall-engine.grafana.svc.cluster.local:8080` and
  `grafanaUrl` `http://grafana.grafana.svc.cluster.local:3000`, it asks
  the plugin to sync;
- otherwise it writes those settings (`stackId` 5, `orgId` 100, the
  self-hosted values) and calls the plugin's install, which gives the
  engine Grafana's URL and a service account token.

Forge's script stopped as soon as the plugin was enabled. This one also
checks the URLs, because the copied `grafana.db` is enabled with Forge's
(Forge's loopback engine port and podman bridge address). It logs in as `admin` with
`grafana/admin-password`.

The Job runs once. To run it again (after the cutover, or after a script
change, which does not change the Job's spec):

```sh
kubectl -n grafana delete job grafana-oncall-plugin-setup
flux -n grafana reconcile ks grafana-oncall-plugin-setup --with-source
```

### Network policy

`default-deny` covers the namespace. Then:

| Pod | In | Out |
| --- | --- | --- |
| Grafana | 3000 from `envoy-external`, Prometheus, the OnCall pod, the setup Job | DNS; 443 to `id.`, `prom.`, `loki.holthome.net`, `grafana.com`, `storage.googleapis.com`; Prometheus 9090; postgres17 5432; OnCall engine 8080 |
| OnCall engine and Celery | 8080 from `envoy-internal`, Grafana, Prometheus, the setup Job | DNS; Redis 6379; Grafana 3000; 443 to public addresses |
| Redis | 6379 from the OnCall pod | nothing |
| Setup Job | nothing | DNS; Grafana 3000; engine 8080 |
| VolSync movers | nothing | DNS; public addresses (R2) |

Grafana's policy is in its HelmRelease (`rawResources`), because Cilium's
schema refuses `${SECRET_DOMAIN}` in `toFQDNs` before Flux substitutes it.
`grafana.com` and `storage.googleapis.com` are there only for the two
plugin downloads (the catalog API, and the archive it redirects to). If a
plugin install fails with a refused connection, the Grafana log names the
host.

OnCall's 443 is to any public address, not a host list: where it sends
notifications (Telegram, Slack, outgoing webhooks, Grafana Cloud for push,
SMS and calls) is set in its database, not in this repo. Private ranges
stay closed. Narrow it once the channels in use are known.

## Secrets

1Password vault `k8s-secrets`. Field names are Forge's sops keys.

| Item | Field | Value | Read by |
| --- | --- | --- | --- |
| `grafana` (new) | `admin-password` | Forge's sops `grafana/admin-password`. The variable only seeds a new database; after the copy, `admin`'s password is Forge's, and the setup Job and OnCall log in with this field | Grafana, OnCall, setup Job |
| `grafana` | `oidc_client_secret` | Forge's sops `grafana/oidc_client_secret` (Pocket ID client `grafana`) | Grafana |
| `grafana-oncall` (new) | `secret_key` | Forge's sops `grafana-oncall/secret_key`. Must be Forge's: OnCall encrypts integration and notifier credentials in the copied database with it. Also `MIRAGE_SECRET_KEY` | OnCall |
| `grafana-oncall` | `metrics_secret` | Forge's sops `grafana-oncall/metrics_secret` | OnCall, the ServiceMonitor |
| `schoolhouse` | `grafana_password` | [postgres17.md](postgres17.md) | Grafana datasource |
| `homelab-finance` | `grafana_db_password` | [postgres17.md](postgres17.md) | Grafana datasource |
| `volsync-r2-template` | existing | Repositories `grafana-data` and `grafana-oncall-data` | VolSync |

`grafana-oncall/alertmanager-webhook-url` stays in Forge's sops: Forge's
Alertmanager reads it. It has no field here.

## Backups

VolSync restic to R2, crash-consistent Ceph snapshots: `grafana-data`
daily at 03:20, `grafana-oncall-data` every 6 hours at :40. Seven daily
and four weekly. Redis is not backed up.

## Cutover

Before:

- nix-config allows the sleds' reads of Forge's Prometheus and Loki (the
  Forge changes below, first block). Without it the Forge datasources fail;
  nothing else does.
- postgres17 has the `schoolhouse_grafana` and `homelab_finance_grafana`
  roles and the data ([postgres17.md](postgres17.md)).
- The 1Password items above exist with Forge's values.

Steps:

1. Check versions on Forge. Grafana must be 12.3.11 or older:
   `grafana --version`. OnCall must be
   `v1.16.11`: `podman inspect grafana-oncall-engine --format '{{.ImageName}}'`.
   The installed OnCall plugin must be 1.16.11:
   `jq -r .info.version /var/lib/grafana/plugins/grafana-oncall-app/plugin.json`.
   If Grafana is newer, raise the image here first. If the plugin differs,
   change both `GF_PLUGINS_PREINSTALL*` pins to it.
2. Stop the cluster's copies and empty the fresh Redis queue:

   ```sh
   flux -n grafana suspend hr grafana grafana-oncall
   kubectl -n grafana scale deploy grafana grafana-oncall --replicas 0
   kubectl -n grafana exec deploy/grafana-oncall-redis -- redis-cli FLUSHALL
   ```

3. Stop Forge's, so nothing writes after the copy:
   `systemctl stop grafana grafana-oncall-plugin-setup podman-grafana-oncall-celery podman-grafana-oncall-engine`.
   Alertmanager retries OnCall until step 7; its Pushover routes keep working.
4. Copy the databases off Forge and check them:

   ```sh
   cp /var/lib/grafana/data/grafana.db /tmp/grafana.db
   ls /var/lib/grafana-oncall/data/          # expect oncall.db
   cp /var/lib/grafana-oncall/data/oncall.db /tmp/oncall.db
   sqlite3 /tmp/grafana.db 'PRAGMA integrity_check'
   sqlite3 /tmp/oncall.db 'PRAGMA integrity_check'
   ```

   Forge keeps `grafana.db` in `data/` (the NixOS default); the image
   keeps it at the root of `/var/lib/grafana`.
5. Put them on the PVCs with a pod that runs as each app's uid (restricted
   Pod Security, no network needed for `kubectl cp`):

   ```sh
   kubectl -n grafana run grafana-restore --restart=Never \
     --image=docker.io/library/python:3.15.2-slim-trixie@sha256:e97b88e416c3c01eb427b21fd8cd3ebf006e6ee38afcfcc3cae1c54ee2ab0a75 \
     --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":472,"runAsGroup":472,"fsGroup":472,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"r","image":"docker.io/library/python:3.15.2-slim-trixie@sha256:e97b88e416c3c01eb427b21fd8cd3ebf006e6ee38afcfcc3cae1c54ee2ab0a75","command":["sleep","3600"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}},"volumeMounts":[{"name":"d","mountPath":"/data"}]}],"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"grafana-data"}}]}}'
   kubectl -n grafana exec grafana-restore -- rm -f /data/grafana.db /data/grafana.db-journal /data/grafana.db-wal /data/grafana.db-shm
   kubectl -n grafana cp /tmp/grafana.db grafana-restore:/data/grafana.db
   kubectl -n grafana exec grafana-restore -- chmod 0640 /data/grafana.db
   kubectl -n grafana exec grafana-restore -- ls -ln /data
   kubectl -n grafana delete pod grafana-restore
   ```

   The file must be owned by 472:472, mode 0640. Repeat for OnCall with
   `runAsUser: 957`, `runAsGroup: 952`, `fsGroup: 952`, claim
   `grafana-oncall-data`, and `/data/oncall.db` (same removals of
   `oncall.db-*`, mode 0640, owner 957:952). Leave the `plugins/`
   directory Grafana already filled.
6. Start them, then rerun the plugin Job, which rewrites Forge's plugin
   URLs:

   ```sh
   flux -n grafana resume hr grafana grafana-oncall
   kubectl -n grafana delete job grafana-oncall-plugin-setup
   flux -n grafana reconcile ks grafana-oncall-plugin-setup --with-source
   kubectl -n grafana logs job/grafana-oncall-plugin-setup
   ```

   Check `https://grafana.holthome.net/api/health` reports 12.3.11 and that
   the log shows no migration error, sign in with Pocket ID, test each
   datasource, and open Alerts & IRM, OnCall: the plugin status is
   connected and the escalation chains and schedules are Forge's.
7. In nix-config, point Forge's Alertmanager at the cluster: set sops
   `grafana-oncall/alertmanager-webhook-url` to
   `https://oncall.holthome.net/integrations/v1/alertmanager/<token>/`, with
   the token from the Alertmanager integration in the copied database
   (Grafana, OnCall, Integrations). From Forge, `dig oncall.holthome.net`
   must answer `10.45.10.50`. Send a test alert and watch it page.
8. Move DNS. `grafana.holthome.net` and `oncall.holthome.net` are Forge
   tunnel CNAMEs in Cloudflare (Caddy vhosts with `cloudflare.enable`).
   external-dns does not take over a record it does not own, so delete both
   records once Forge no longer serves them. cloudflare-dns then publishes
   `grafana.` to `external.holthome.net`, and mikrotik-dns publishes
   `oncall.` on the LAN. If the router has a static entry for either name
   pointing at Forge, remove it.
9. Remove Forge's Grafana and OnCall (the Forge changes below).

Rollback before step 7: suspend the two HelmReleases and start Forge's
units again; Forge's databases were not changed.

## Forge changes (nix-config)

The cutover PR in nix-config. Sled addresses are `10.20.10.20/32` through
`10.20.10.23/32`; cluster pods leave through them (Cilium masquerade).

Reads Grafana makes (before the cutover):

- `prom.holthome.net` (`hosts/forge/infrastructure/monitoring-ui.nix`):
  bypass the Pocket ID policy for the four sleds, method `GET`, resources
  `^/api/v1/(query|query_range|query_exemplars|series|labels|label/[^/]+/values|metadata|status/buildinfo|format_query|rules|alerts)$`.
  The same AND matcher shape as `am.`'s `POST /api/v2/alerts` bypass.
- `loki.holthome.net` (`hosts/forge/infrastructure/observability/loki.nix`):
  that vhost is Caddy basic auth (`CADDY_LOKI_ADMIN_BCRYPT`), not
  caddy-security, so the bypass has to skip basic auth for the four sleds,
  method `GET`, resources
  `^/loki/api/v1/(query|query_range|labels|label/[^/]+/values|series|index/(stats|volume|volume_range)|patterns|detected_fields|detected_field/[^/]+/values|detected_labels|status/buildinfo|format_query)$`.
  Add `^/loki/api/v1/tail$` (a WebSocket GET) if live tail in Explore
  should work.

At the cutover:

- Alertmanager: the new `grafana-oncall/alertmanager-webhook-url` value
  (step 7). `hosts/forge/infrastructure/observability/alertmanager.nix`
  sets `receivers.oncall.enable = config.modules.services.grafana-oncall.enable`,
  and `hosts/forge/secrets.nix` declares that secret under
  `grafanaOncallEnabled`. Both must stop depending on Forge's OnCall
  module, or disabling it also removes the receiver and its secret. Keep
  the `GrafanaOnCall.*ServiceDown` Pushover route; the cluster's alerts
  use those names.
- Remove Forge's Grafana: `./grafana.nix` from
  `hosts/forge/infrastructure/observability/default.nix` (with it the
  `grafana.` Caddy vhost and tunnel entry, the `grafana-oncall-plugin-setup`
  unit, the `grafana-oncall-network` podman network, the
  `grafana-service-down` rule, the sanoid dataset, homepage and Gatus
  contributions), sops `grafana/admin-password` and
  `grafana/oidc_client_secret` (the values live in 1Password item
  `grafana` now), `grafana-oncall-plugin-setup` in
  `hosts/forge/core/systemd-restart-policy.nix`. The `grafanaDatasources`
  in `schoolhouse.nix`, `homelab-mcp.nix`, `tracearr.nix`, TeslaMate's
  integration, the Alertmanager datasource and alloy's dashboard provider
  are all gated on Grafana being enabled and go quiet; the dashboard Nix
  files stay the source of the JSON here.
- Remove Forge's OnCall: `./services/grafana-oncall.nix` from
  `hosts/forge/default.nix` (its `oncall.` vhost and tunnel entry, its
  three `*ServiceDown` rules, Gatus and homepage entries), the
  `grafana-oncall` scrape job in
  `hosts/forge/infrastructure/observability/prometheus.nix`, sops
  `grafana-oncall/secret_key` and `grafana-oncall/metrics_secret` (now in
  1Password item `grafana-oncall`), the three `podman-grafana-oncall-*`
  entries in `systemd-restart-policy.nix`.
- Watch the cluster copies from Forge's Gatus instead: `https://grafana.holthome.net`
  and `https://oncall.holthome.net/health/`. That is the out-of-cluster
  check when the cluster itself is down.
- Optional: an Alertmanager read bypass on `am.holthome.net` (sleds,
  `GET`, `^/api/v2/(alerts|alerts/groups|silences|silence/[^/]+|status)$`)
  if the `Alertmanager` datasource should come back here.
