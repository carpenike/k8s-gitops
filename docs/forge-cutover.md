# Forge to cluster cutover

One window moves everything that used Forge's local Postgres off Forge:
homelab-mcp and its finance and Signal workers, schoolhouse, lading,
Grafana and Grafana OnCall. Forge keeps Alertmanager, Prometheus, Loki,
Gatus, Actual (`budget.`) and Pocket ID.

Each app's own doc has the detail; this page is the order.

| Doc | What it covers |
| --- | --- |
| [postgres17.md](postgres17.md#forge-stores) | The four databases, roles, 1Password items, restore and grants |
| [homelab-mcp.md](homelab-mcp.md) | The pod: server, Actual sidecar, signal-api, capture, scheduler, metrics |
| [schoolhouse.md](schoolhouse.md), [lading.md](lading.md) | Ingest and sync CronJobs, their state volumes |
| [grafana.md](grafana.md) | Grafana and OnCall, the database copies, Forge-side changes |

## PRs

| PR | Repo | Merge when |
| --- | --- | --- |
| #5766 postgres17 databases | k8s-gitops | Merged |
| #5778 build runners | k8s-gitops | Before the images (any time) |
| schoolhouse #24, lading #9 | schoolhouse, lading | After #5778; they push the images |
| mcp #121 finance runtime (0.39.0) | mcp | Any time; it pushes the image |
| #1433 Prometheus/Loki sled read bypass | nix-config | Any time before Grafana |
| #1434 cluster Watchdog routing | nix-config | Any time (a live bug fix) |
| #1432 homelab-mcp pin bump | nix-config | With the Forge retirement PR, or closed by it |
| #5765 homelab-mcp (pin from #121 first) | k8s-gitops | Window, step 4 |
| #5780 schoolhouse and lading (pin from #24, #9 first) | k8s-gitops | Window, step 4 |
| #5781 Grafana and OnCall | k8s-gitops | Window, step 4 |
| Forge retirement | nix-config | Window, step 7 |

## Before the window

1. Images: merge #5778, then schoolhouse #24, lading #9 and mcp #121. Pin
   each `main` build (tag and digest) into #5765, #5780 and #5781's
   placeholders. GitHub App installation `175991169` must include
   carpenike/lading.
2. 1Password, vault `k8s-secrets`, values copied from Forge's sops file,
   never printed:
   - `homelab-mcp` (done), `homelab-mcp-signal`,
     `homelab-finance/report_password`;
   - `schoolhouse-ingest`, `lading-ryan`, `lading-steffi`;
   - `grafana`, `grafana-oncall` (OnCall's `secret_key` must be Forge's:
     it decrypts the copied database).
3. Deploy #1433 and #1434 on Forge. Check from a sled that
   `https://prom.<domain>/api/v1/query?query=up` and
   `https://loki.<domain>/loki/api/v1/labels` answer without a login, and
   that `/graph` and `/loki/api/v1/push` still need one.
4. On Forge, write down: `grafana --version` (the cluster runs 12.3.11, so
   Forge's must be older or equal), and the hosts in
   `schoolhouse/ical_feeds` without printing the URLs (schoolhouse.md).

## The window

1. **Stop on Forge**, in this order, and keep them stopped:
   - the finance timers (ingest, export, snapshots, reports, metrics) and
     `finance-signal-capture`;
   - `homelab-mcp` and its Actual sidecar;
   - `podman-signal-api`;
   - schoolhouse (health and ingest timer) and every `lading-sync-*` timer;
   - Grafana OnCall (engine, celery, redis) and Grafana.
2. **Databases:** dump and restore `schoolhouse`, `lading` and
   `homelab_finance` into postgres17, grant the readers, and copy the
   transaction context ([postgres17.md](postgres17.md#restore-from-forge-cutover)).
3. **Copy files off Forge** (keep modes; everything below ends up owned by
   the target uid):
   - `/var/lib/homelab-mcp/finances-context.db` and
     `/var/lib/homelab-mcp/finances-ingest/` (uid 65532);
   - `/var/lib/signal-api/` (uid 65532);
   - `/var/lib/schoolhouse/` and each lading account's state directory
     (uid 65532);
   - Grafana's `grafana.db` (uid 472) and OnCall's SQLite database
     (uid 957).

   Do not copy homelab-mcp's OAuth state: tokens from Forge do not work in
   the cluster.
4. **Merge #5765, #5780 and #5781.** Scale homelab-mcp, Grafana and OnCall
   to 0 as soon as their PVCs exist (or merge with `replicas: 0`);
   schoolhouse's and lading's CronJobs ship suspended. Copy the files from
   step 3 onto the PVCs (a `kubectl debug` or busybox pod mounting the PVC,
   as the right uid), then scale back to 1.
5. **Check before going on:**
   - homelab-mcp: `/healthz` ok; the `capture` and `scheduler` containers
     running; `finance_signal_path_healthy 1` and
     `finance_signal_listener_healthy 1` on port 9202; no
     `FinanceSignal*` or `FinanceIngest*` alert firing.
   - signal-api: the bot answers in the family group (send a note and see
     the acknowledgment).
   - Grafana: Pocket ID login, the Household Finance and Schoolhouse
     dashboards show data, Prometheus (Forge) and Loki datasources green;
     the OnCall plugin connected.
6. **Unsuspend** the schoolhouse and lading CronJobs (`suspend: false` in
   #5780's HelmReleases, a follow-up commit).
7. **Deploy the Forge retirement PR** (nix-config). Set Forge
   Alertmanager's `grafana-oncall/alertmanager-webhook-url` to the cluster
   OnCall integration URL in the same deploy.
8. **DNS:** delete Forge's Cloudflare tunnel records for `mcp.`,
   `grafana.` and `oncall.`; external-dns publishes the cluster's (it does
   not take over records it does not own).
9. **Clients:** remove the old Claude connectors and add one per view URL
   (`/mcp`, `/mcp/admin`); point Hermes at `/mcp/agent` and Groundskeeper at
   `/mcp/house-sensors`.

## After

- Watch one full day: the 08:00 daily report, the 19:30 UTC bank pull, the
  05:30 export, schoolhouse's weekday runs, lading's 04:20 and 05:40 syncs.
- Create the cluster's own Healthchecks.io check and enable
  `clusterUrlSecret` (nix-config #1434's comment).
- Keep Forge's data (datasets and the three databases) for a week, then
  delete them in a follow-up.

## Rollback

Until step 7, start the Forge units again and scale the cluster workloads to
0; nothing on Forge was changed. After step 7, revert the Forge retirement
PR (its data is still there) and do the same. Writes made in the cluster in
between (Signal notes, ingestion, exports, grades, orders) are in postgres17
and the cluster volumes, not on Forge.
