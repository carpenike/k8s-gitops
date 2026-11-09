# homelab-mcp

The Claude tools server from [carpenike/mcp](https://github.com/carpenike/mcp),
at `mcp.${SECRET_DOMAIN}` on envoy-external. It is its own OAuth 2.1
authorization server, federated to Pocket ID, so the route is `native`
(see [gateway-auth.md](gateway-auth.md)).

Manifests: `kubernetes/apps/homelab-mcp/`.

## Views

Each URL is a separate protected resource. A token for one is refused on
the others. Configure them in `HOMELAB_MCP_VIEWS` in the HelmRelease.

| URL | Tools | Scopes | For |
| --- | --- | --- | --- |
| `/mcp` | read-only tools | `home.read` | The everyday Claude connector |
| `/mcp/full` | every enabled tool | `home.read` and `home.write`, both requested on connect | Claude, when writes are wanted |
| `/mcp/agent/hermes` | the `hermes` list | `hermes` | Hermes (every Hermes bot) |
| `/mcp/agent/grokbot` | the `hermes` list, for now | `grokbot` | Grokbot (every Grokbot agent) |
| `/mcp/steffi` | Grocy (reads and stock writes, as her) and Cooklang reads | `steffi.read` and `steffi.write`, both requested on connect | Steffi; `credentials: "per_user"` |
| `/mcp/house-sensors` | the `atrium-family-house-sensors` list | the same | Groundskeeper |

View paths follow one rule. The household owner's views sit at the root
and are named by access: `/mcp` (read) and `/mcp/full` (read and write);
the server requires a view at `/mcp`. Every other person gets
`/mcp/<person>`, and every agent platform `/mcp/agent/<platform>`.

Agents get one view per platform, at `/mcp/agent/<platform>`, not one per
bot. Every bot on a platform gets the same tool list. Each bot that connects
(each Hermes bot runs in its own `hermes-<bot>` namespace) still logs in and
holds its own token, so one can be disconnected without the others. Split a
bot out into its own view only when it needs a risky tool the others must
not have. A new platform is one more entry in `HOMELAB_MCP_VIEWS`, with its
own `read_scope`, so a platform's tokens never work on another's view.

Only users listed in a view can use it. Steffi can use `/mcp/steffi` only;
every other view is Ryan's.

`/mcp/steffi` acts as her: its Grocy tools send her own key (field
`grocy.steffi` below) and are refused, never given Ryan's, until it exists.
Cooklang has no key at all, so it is the same for everyone. Nothing else
can be added to this view unless it either resolves her own credential or
uses none; the server refuses to start otherwise (carpenike/mcp
`credentials.py`).

The first time a user connects a client to a view, they get a consent page.

## What runs here

The pod only reaches hosts named in its CiliumNetworkPolicy, on 443, plus
postgres17 on 5432. That policy is in the HelmRelease (`rawResources`), not
`ciliumnetworkpolicy.yaml`, because kubeconform rejects `${SECRET_DOMAIN}` in
a `toFQDNs` name.

| Category | Upstream |
| --- | --- |
| `mfp` | www/api.myfitnesspal.com |
| `cooklang`, `ha`, `grocy`, `paperless` | their hosts on `${SECRET_DOMAIN}` |
| `arcraiders` | public game-data sites |
| `gatus` | `status.${SECRET_DOMAIN}` `/api/v1/endpoints`, let through Forge's admin login (nix-config) |
| `fidelity` | api.snaptrade.com |
| `finances`, `finances_docs`, `finances_loans`, `finances_sentinel` | the Actual sidecar in this pod (to `budget.${SECRET_DOMAIN}`), the finances repo on github.com, postgres17 `finances_context` |
| `money` | postgres17 `homelab_finance` (`money_overview` only) |
| `school`, `school_today` | postgres17 `schoolhouse` |
| `amazon`, `costco`, `samsclub` | postgres17 `lading` |

Off: `messaging` (not configured yet; signal-api now runs in this pod) and
`nixos` (Forge's deploy trigger). Signal capture and reports run in this pod
(below) and write the shared context store in postgres17.

The stores in postgres17 and how they got there:
[postgres17.md, "Forge stores"](postgres17.md#forge-stores).

### Actual sidecar

Actual's only API client is the Node package `@actual-app/api`, so container
`actual` runs it in this pod; the tools call it on loopback.
- It logs in once per start, and Actual locks the account after 5 failed
  logins in 15 minutes. So a failed boot holds `/health` at 503 for 5 minutes
  before exiting (`SIDECAR_BOOT_FAILURE_HOLD_SECONDS`).
- Its liveness probe is the TCP port, and it has no readiness probe. A
  not-ready container would take the whole pod, and every MCP endpoint, out
  of service when Actual is down.

### Finance jobs

The finance workers that ran on Forge run in this pod as well, because
carpenike/mcp accepts the Actual sidecar and signal-api only on loopback,
and the jobs share one state directory with the server.

| Container | What it does |
| --- | --- |
| `permissions` (init) | Sets `/var/lib/homelab-mcp` and the Signal volume to uid 65532, mode 0700. The finance runtime refuses anything else. The only step that runs as root (`CHOWN`, `FOWNER` only) |
| `actual` | The Actual sidecar |
| `signal-api` | signal-cli-rest-api 0.101, JSON-RPC mode, the household bot's registration on PVC `homelab-mcp-signal`. No authentication, so no Service and no route; the network policy admits nothing to 8080 |
| `capture` | `homelab-finances-runtime capture 8080`: the Signal note listener |
| `scheduler` | supercronic, crontab in the HelmRelease, America/New_York |
| `metrics` | `homelab-finances-runtime serve-metrics`: the jobs' `finance_*.prom` files on 9202, scraped by the ServiceMonitor |

| Job | When | Replaces on Forge |
| --- | --- | --- |
| Bank ingestion (`homelab-finances-ingest due && run`) | Every 15 minutes; pulls once a day, anchored to 19:30 UTC | `homelab-mcp-finances-ingest.timer` |
| Ingestion metrics | Every 2 minutes | `finance-ingest-metrics.timer` |
| Nightly export (`homelab-finances-export`) | 05:30 | `homelab-mcp-finances-export.timer` |
| Snapshots | Every 5 minutes | `finance-snapshot.timer` |
| Daily report (`project`, then `report daily`) | 08:00, 08:05, 08:10 | `finance-signal-report@daily.timer` |
| Weekly report | Fridays 16:00, 16:05, 16:10 | `finance-signal-report@weekly.timer` |
| Signal metrics (`collect`) | Every 2 minutes | `finance-signal-metrics.timer` |

The export writes `homelab_finance` as its owner; that credential is in
`homelab-mcp-jobs`, which only the scheduler reads, never the server's
environment. Reports read through `homelab_finance_report`
(`money_overview` and `export_runs` only).

Volumes:
- `homelab-mcp-state`: server state, the Signal store
  (`finances-context.db`), the ingestion reservation and report state, the
  finances checkout.
- `homelab-mcp-signal`: signal-cli's registration. Not reproducible.

Both are backed up to R2 by VolSync every 6 hours (`../backup`, item
`volsync-r2-template`).

MFP writes stay off (`HOMELAB_MCP_MFP_WRITES_ENABLED: "false"`) until the
write tests pass. The mfp tools only read.

The upstreams on `${SECRET_DOMAIN}` must answer API calls from the
cluster without the gateway login. Check each host when it first fails:

- Home Assistant takes its own bearer token.
- Grocy takes `GROCY-API-KEY`.
- Paperless takes `Token`.
- Gatus needs the `/api/v1/endpoints` bypass.
- Actual takes the sidecar's password login.

## 1Password

Item `homelab-mcp` in vault `k8s-secrets`:

| Field | Value |
| --- | --- |
| `pocketid_client_secret` | Secret of the existing Pocket ID client `mcp`. Its callback is already `https://mcp.${SECRET_DOMAIN}/oauth/callback`. Take it from Forge's `homelab-mcp` sops secret, or regenerate it in Pocket ID at cutover |
| `ha_token` | Home Assistant long-lived token for writes (Forge's `homelab-mcp/ha_token`) |
| `ha_read_token` | Home Assistant token for reads |
| `grocy_api_key` | Grocy API key |
| `paperless_token` | Paperless API token |
| `mfp_cookies` | The MyFitnessPal cookie export (carpenike/mcp `docs/MFP-COOKIE-RUNBOOK.md`) |
| `sidecar_token` | Shared token between the tools, and the sidecar (Forge's `homelab-mcp/actual-env` `SIDECAR_TOKEN`, or a new `openssl rand -hex 32`) |
| `actual_password` | Actual server password (Forge's `homelab-mcp/actual-env` `ACTUAL_PASSWORD`) |
| `actual_budget_sync_id` | Budget sync id (same file, `ACTUAL_BUDGET_SYNC_ID`) |
| `actual_encryption_password` | Budget encryption password (same file, `ACTUAL_ENCRYPTION_PASSWORD`) |
| `finances_repo_token` | GitHub token for carpenike/finances, contents read and write (Forge's `HOMELAB_MCP_FINANCES_REPO_TOKEN`) |
| `finances_floor`, `finances_amazon_baseline`, `finances_buffer_floor` | The private monthly numbers from Forge's `homelab-mcp/env` (`HOMELAB_MCP_FINANCES_*`) |
| `snaptrade_client_id`, `snaptrade_consumer_key` | SnapTrade read credentials (Forge's `HOMELAB_MCP_SNAPTRADE_*`) |
| `amazon_account_last4` | JSON object, ledger account name to card last four, as in Forge's `HOMELAB_MCP_AMAZON_ACCOUNT_LAST4`. Without it `amazon_*` matches top out at `probable` |

Item `homelab-mcp-user-credentials` in vault `k8s-secrets` holds per-user
upstream keys, one field per upstream and person, named
`<upstream>.<alias>` (alias from `HOMELAB_MCP_USERS`):

| Field | Value |
| --- | --- |
| `grocy.ryan` | Ryan's own Grocy API key, used only by views with `credentials: "per_user"` |
| `grocy.steffi` | Steffi's own Grocy API key (from her Grocy user), same use |

To give someone a per-user key:
1. Add them to `HOMELAB_MCP_USERS` in the HelmRelease.
2. Add the field to the item. The ExternalSecret extracts every field, so
   nothing else changes; force-sync it to skip the 12h wait. Every field of
   the item becomes a file there, so keep only credentials in it, and no two
   fields with the same label (the provider refuses those).

The volume is optional, so the pod starts before the item exists. A
per-user call then fails with `<upstream>_no_user_credential` and is
counted in `homelab_mcp_user_credential_missing_total`; it never falls back
to the shared key. No view uses `per_user` yet.

The database passwords come from the postgres17 items (`schoolhouse`,
`lading`, `homelab-finance`, `finances-context`;
[postgres17.md](postgres17.md#1password)). The ExternalSecrets build the
DSNs from them, URL-encoded, against `postgres17-rw`.

ExternalSecrets:

- `homelab-mcp` builds `homelab-mcp-env`, the MCP container's environment.
- `homelab-mcp-mfp` builds `homelab-mcp-mfp`, which is mounted at
  `/run/mfp`.
- `homelab-mcp-actual` holds the sidecar's login, which only the sidecar
  container sees.
- `homelab-mcp-user-credentials` builds the Secret of the same name, mounted
  at `/run/user-credentials` (optional).

The server re-reads the cookie file when it changes, so new cookies need a
force-sync but no restart:

```sh
kubectl -n homelab-mcp annotate externalsecret homelab-mcp-mfp \
  force-sync="$(date +%s)" --overwrite
```

The OAuth signing key and the state database are created on first start,
in `/var/lib/homelab-mcp/state` on the PVC. They are not in 1Password.
Losing the PVC means every client connects again. Nothing else is lost; the
finances checkout re-clones.

Also:

| Item | Fields | From Forge |
| --- | --- | --- |
| `homelab-mcp-signal` | `number`, `group_id`, `ops_group_id`, `bot_uuid`, `capture_senders` | `HOMELAB_MCP_SIGNAL_*` in sops `homelab-mcp/finance-signal-env` |
| `homelab-finance` | `report_password` (new field) | none; generate |

`homelab-mcp-jobs` reuses `homelab-mcp` (`sidecar_token`,
`finances_repo_token`, `finances_*` amounts), `homelab-finance/export_db_password`,
`lading/reader_password` and `homelab-finance/report_password`.

## Images

carpenike/mcp `.github/workflows/image.yml` builds both images on the
`mcp-k8s-build` runners from main:

- `ghcr.io/carpenike/homelab-mcp`: the server and every finance job
  container (it carries `homelab-finances-runtime` and supercronic, since
  mcp 0.39.0);
- `ghcr.io/carpenike/homelab-mcp-actual-sidecar`.

Both are pinned by tag and digest (`sha-<commit>@sha256:<digest>`), to mcp
main `13d15b5` (0.41.0). Bump both together from a later main build. signal-api is `docker.io/bbernhard/signal-cli-rest-api`
(no GHCR copy upstream), pinned the same way.

## Alerts

The PrometheusRule `homelab-mcp` defines these, plus the finance job alerts
ported from Forge (groups `homelab-mcp-finance-*`, same expressions and
runbook text; the systemd unit checks became `FinanceSchedulerDown` and
`FinanceSignalContainerDown`). They route to Forge's Alertmanager like every
other alert here.

| Alert | Fires when |
| --- | --- |
| `HomelabMcpDown` | Prometheus gets no `/metrics` for 10 minutes |
| `HomelabMcpMfpAuthExpired` | MyFitnessPal refused the cookies. The tools return an auth error until they are replaced |
| `HomelabMcpMfpCookiesExpiringSoon` | The session cookie expires within 5 days |

## Cutover from Forge

There is no staging hostname. The cluster takes `mcp.${SECRET_DOMAIN}`
over from Forge directly.

1. ~~Merge carpenike/mcp #117 through #120.~~ Done.
2. Merge carpenike/mcp #121 and pin its image here (both tags).
3. Create the 1Password items above and the postgres17 ones, then merge the
   postgres17 PR.
4. Stop on Forge: homelab-mcp, the Actual sidecar, the finance ingest,
   export, snapshot and report timers, Signal capture, and `signal-api`.
5. Restore the stores and copy the transaction context
   ([postgres17.md](postgres17.md#restore-from-forge-cutover)).
6. Merge this app with `replicas: 0`, or scale it to 0 once it is up, then
   copy into its volumes, as uid 65532 with modes preserved:
   - Forge `/var/lib/homelab-mcp/finances-context.db` (0600) and
     `/var/lib/homelab-mcp/finances-ingest/` into `homelab-mcp-state`;
   - Forge `/var/lib/signal-api/` into `homelab-mcp-signal`.

   Do not copy Forge's OAuth state: tokens from Forge do not work here.
   Scale back to 1.
7. Apply the nix-config cutover: it removes homelab-mcp, the finance jobs
   and signal-api from Forge, and the Caddy vhost and tunnel ingress for
   `mcp`. Then delete the `mcp` DNS record.

   external-dns will not take over a record it does not own (TXT
   ownership, prefix `k8s.`).
8. external-dns publishes `mcp.${SECRET_DOMAIN}` to the cluster tunnel.
9. Remove the old connectors in Claude. Add one connector per view URL
   (`/mcp`, `/mcp/full`), and approve each on the consent page.

   Point Hermes at `/mcp/agent/hermes`, Grokbot at `/mcp/agent/grokbot`,
   and Groundskeeper at
   `/mcp/house-sensors`.

Tokens from Forge do not work here. The signing key is new, and the
audience is now the view URL.
