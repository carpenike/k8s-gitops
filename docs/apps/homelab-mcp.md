# homelab-mcp

The Claude tools server from [carpenike/mcp](https://github.com/carpenike/mcp),
at `mcp.${SECRET_DOMAIN}` on envoy-external. It is its own OAuth 2.1
authorization server, federated to Pocket ID, so the route is `native`
(see [gateway-auth.md](../platform/gateway-auth.md)).

Manifests: `kubernetes/apps/homelab-mcp/`.

## Views

Each URL is a separate protected resource. A token for one is refused on
the others. Configure them in `HOMELAB_MCP_VIEWS` in the HelmRelease.

| URL | Tools | Scopes | For |
| --- | --- | --- | --- |
| `/mcp` | read-only tools | `home.read` | The everyday Claude connector |
| `/mcp/full` | every enabled tool | `home.read` and `home.write`, both requested on connect | Claude, when writes are wanted |
| `/mcp/agent/hermes` | the `hermes` list | `hermes` | Hermes (every Hermes bot) |
| `/mcp/agent/grokbot` | the `hermes` list, plus `finances_transactions` and `finances_categorize` (category and notes only; no rules, payee merges or loan writes), school reads, Cooklang reads, every MFP tool, the Obsidian vault (`vault_*`: reads and writes every personal domain (fitness, inbox, property, tech, family-history, finances, health, church, education, wardrobe), reads `agents`; no move or delete), and the OpenProject handoff board as user `grokbot` (`openproject_*`, Personal and Bots only) | `grokbot` | Grokbot (every Grokbot agent) |
| `/mcp/steffi` | Grocy (reads and stock writes, as her), Cooklang reads, every MFP tool (her own diary), her own Withings readings, and the dinner planner (`meals_*`, shared recipe pool only, never NYT) | `steffi.read` and `steffi.write`, both requested on connect | Steffi; `credentials: "per_user"` |
| `/mcp/house-sensors` | the `atrium-family-house-sensors` list | the same | Groundskeeper |
| `/mcp/replog` | `scope:atrium-personal-replog`. Not `"read"` or `"all"` | `atrium-personal-replog` and `atrium-personal-replog.write` | Ryan only (`ryan@ryanholt.net`). `credentials: "per_user"`: the bearer is `replog.ryan`, never `HOMELAB_MCP_REPLOG_TOKEN` |

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
postgres17 on 5432, `replog.replog.svc` on 8080 and `grocy.grocy.svc` on 80. That policy is in the HelmRelease (`rawResources`), not
`ciliumnetworkpolicy.yaml`, because kubeconform rejects `${SECRET_DOMAIN}` in
a `toFQDNs` name.

| Category | Upstream |
| --- | --- |
| `mfp` | www/api.myfitnesspal.com |
| `cooklang`, `ha`, `paperless` | their hosts on `${SECRET_DOMAIN}` |
| `grocy` | `grocy.grocy.svc:80` in the cluster ([grocy.md](grocy.md)). `GROCY-API-KEY` per call: the shared `grocy_api_key`, or the caller's `grocy.<alias>` in a per-user view |
| `arcraiders` | public game-data sites |
| `gatus` | `status.${SECRET_DOMAIN}` `/api/v1/endpoints`, let through Forge's admin login (nix-config) |
| `fidelity` | api.snaptrade.com |
| `finances`, `finances_docs`, `finances_loans`, `finances_sentinel` | the Actual sidecar in this pod (to `budget.${SECRET_DOMAIN}`), the finances repo on github.com, postgres17 `finances_context` |
| `money` | postgres17 `homelab_finance` (`money_overview` only) |
| `school`, `school_today` | postgres17 `schoolhouse` |
| `amazon`, `costco`, `samsclub` | postgres17 `lading` |
| `withings` | wbsapi.withings.net (token on the state volume) |
| `vault` | the Obsidian vault on PVC `homelab-mcp-vault`, kept in step by the `obsidian-sync` container ([below](#obsidian-sync)) |
| `replog` | `replog.replog.svc:8080`. Bearer `HOMELAB_MCP_REPLOG_TOKEN` |
| `meals` | postgres17 `meals` (its own store), plus the `nyt`, `cooklang`, `mfp` and `grocy` tools it composes ([Dinner planner](#dinner-planner)) |

`messaging` (`signal_send`) uses the signal-api container in this pod on
loopback, and sends to **ops only** from every view: each view path is in
`HOMELAB_MCP_SIGNAL_OPS_ONLY_VIEWS` (Ryan, 2026-11-13; family stays off until
he asks). A new view must be added to that list too.

Off: `nixos` (Forge's deploy trigger). Signal capture and reports run in this pod
(below) and write the shared context store in postgres17.

The stores in postgres17 and how they got there:
[postgres17.md, "Forge stores"](../platform/postgres17.md#forge-stores).

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
| `permissions` (init) | Sets `/var/lib/homelab-mcp` and the Signal volume to uid 65532, mode 0700. The finance runtime refuses anything else. Also lays out the vault volume (below). The only step that runs as root (`CHOWN`, `FOWNER` only) |
| `obsidian-sync` | Obsidian's headless Sync client for the vault ([below](#obsidian-sync)) |
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
- `homelab-mcp-vault` (25 Gi): the Obsidian vault, the Sync client's login
  and end-to-end key, and its install ([below](#obsidian-sync)).

All three are backed up to R2 by VolSync every 6 hours, at :15, :45 and :30
(`../backup`, item `volsync-r2-template`).

MFP writes stay off (`HOMELAB_MCP_MFP_WRITES_ENABLED: "false"`) until the
write tests pass. The mfp tools only read.

The upstreams on `${SECRET_DOMAIN}` must answer API calls from the
cluster without the gateway login. Check each host when it first fails:

- Home Assistant takes its own bearer token.
- Grocy takes `GROCY-API-KEY`. It is in the cluster now and called on its Service, not its host name ([grocy.md](grocy.md)).
- Paperless takes `Token`.
- Gatus needs the `/api/v1/endpoints` bypass.
- Actual takes the sidecar's password login.

### Obsidian Sync

The `obsidian-sync` container runs Obsidian's headless Sync client
(`obsidian-headless`, ADR 0016) and keeps the vault on `homelab-mcp-vault`
in step with Ryan's devices. The app's `vault_*` tools read and write the
same folder.

- **Pinned by Renovate.** `app/obsidian-sync/package.json` and
  `package-lock.json` pin the client and its dependencies by integrity hash.
  `run.sh` installs them with `npm ci` into the volume (`ob/`), once per
  lockfile. The client is not redistributable, so it is never baked into an
  image. One step is not hash-pinned: `better-sqlite3`'s install downloads its
  prebuilt binary from its GitHub release. The image is
  `node:22-bookworm-slim`, digest-pinned.
- **Volume layout** (made by the permissions init container):
  - `workspace/notes`: the vault. `HOMELAB_MCP_VAULT_PATH`.
  - `workspace/.tmp`: the tools' scratch dir, outside the vault on the same
    mount, so their writes are atomic and Sync never sees a temp file.
  - `config/` (0700): the client's login token and the derived end-to-end key.
    Mounted only into `obsidian-sync`, never into the app.
  - `ob/`: the install.
- **Phases** (`/tmp/obsidian-sync/state`): `installing`, then `waiting` until
  the one-time setup below, then `syncing`. While syncing, the client touches
  `.obsidian/.sync.lock` every second, and the liveness probe restarts it if
  that stops.

**One-time setup** (and again after a restore, or if the device is removed in
Obsidian's settings), in a terminal. Each command prompts; the account
password, MFA code and end-to-end password go only to the client:

```bash
kubectl -n homelab-mcp exec -it deploy/homelab-mcp -c obsidian-sync -- ob login
kubectl -n homelab-mcp exec -it deploy/homelab-mcp -c obsidian-sync -- ob sync-list-remote
kubectl -n homelab-mcp exec -it deploy/homelab-mcp -c obsidian-sync -- ob sync-setup --vault "<vault name>" --path /vault/notes --device-name homelab-mcp
kubectl -n homelab-mcp exec -it deploy/homelab-mcp -c obsidian-sync -- ob sync-config --path /vault/notes --configs "" --file-types image,audio,video,pdf
```

`--configs ""` keeps Obsidian's settings (`.obsidian/`) out of it, and the
file types leave out "unsupported" files. Within a minute `run.sh` sees the
setup and starts `ob sync --continuous`. Check it with
`kubectl -n homelab-mcp logs deploy/homelab-mcp -c obsidian-sync`.

**The handoff board.** `openproject_*` act as one OpenProject user per
connector (`HOMELAB_MCP_OPENPROJECT_VIEW_BOTS`): `/mcp` and `/mcp/full` as
`claude`, `/mcp/agent/grokbot` as `grokbot`; every other view gets no
OpenProject. Scopes are project trees (`..._BOT_SCOPES`), and OpenProject's
memberships ([openproject.md](openproject.md), "Board structure") bound them
again: Grokbot never sees Work. Tokens are the provisioner's Secrets
`homelab-mcp-openproject-<bot>`, mounted at `/run/openproject-tokens`.

**Who sees what.** `app/vault-policy.yaml` (the `homelab-mcp-vault-policy`
ConfigMap, mounted into the app only) splits the vault into domains and binds
each connector to a profile. Claude (`/mcp`, `/mcp/full`) sees everything;
Grokbot sees only the personal domains (and `agents`, read-only), and to it
every other folder does not exist. Grok connectors are shared by every bot on
the account, so all Grok bots are this one profile. External providers can never be given a work-sensitivity domain: the app
refuses to load such a policy, and with no valid policy every vault tool
refuses every caller. Adding a domain is an edit to that file and a pod
restart (reloader does it), never an image change. Moves and deletes are
preview then confirm.

### Withings

Ryan and Steffi share one Withings Body Scan, each under their own Withings
user, so each has their own OAuth token on the state volume (carpenike/mcp
0.70.0). A call reads the caller's own token, chosen from the verified email
through `HOMELAB_MCP_USERS`. `HOMELAB_MCP_WITHINGS_READ_GRANTS` is empty, so
neither reads the other's and no bot reads Steffi's (Ryan, 2026-11-23).
Ryan's token is `withings-token.json`; Steffi's is
`withings-token.steffi.json` beside it. `HOMELAB_MCP_WITHINGS_USERIDS` pins
her token to her Withings userid, and a token for any other user is refused.

To authorize Steffi (once, and again after a restore), she runs this herself,
in a private browser window so Withings does not reuse Ryan's sign-in, and
picks her own user if the consent page asks:

```sh
WITHINGS_CLIENT_ID=op://k8s-secrets/homelab-mcp-withings/client_id \
WITHINGS_CLIENT_SECRET=op://k8s-secrets/homelab-mcp-withings/client_secret \
op run -- python3 scripts/withings_authorize.py \
  | kubectl -n homelab-mcp exec -i deploy/homelab-mcp -c app -- \
      python -m homelab_mcp.tools._withings seed --alias steffi
```

`scripts/withings_authorize.py` is in carpenike/mcp. Steffi has her own
Withings account (the scale is shared with it), so sign in with her login.
Her pin is userid `31471867`; a seed of any other user's token is refused
with "the token is for Withings user N, not the pinned …". For a new
person, pin a placeholder `0` first: the refusal names their userid. Re-authorizing Ryan is the same command with
`--alias ryan`. Until her token exists, `HomelabMcpWithingsTokenUnusable`
fires for `alias="steffi"`.

## 1Password

Item `homelab-mcp` in vault `k8s-secrets`:

| Field | Value |
| --- | --- |
| `pocketid_client_secret` | Secret of the existing Pocket ID client `mcp`. Its callback is already `https://mcp.${SECRET_DOMAIN}/oauth/callback`. Take it from Forge's `homelab-mcp` sops secret, or regenerate it in Pocket ID at cutover |
| `ha_token` | Home Assistant long-lived token for writes (Forge's `homelab-mcp/ha_token`) |
| `ha_read_token` | Home Assistant token for reads |
| `grocy_api_key` | Grocy API key |
| `paperless_token` | Paperless API token |
| `replog_token` | Shared-mode RepLog coach service token. ExternalSecret `homelab-mcp` writes it as `HOMELAB_MCP_REPLOG_TOKEN`. This field stays. `/mcp/replog` does not use it |
| `replog_signing_private_key` | Ed25519 private key (PEM) that signs a 60-second RepLog on-behalf JWT per call (carpenike/mcp#176, replog ADR 025). ExternalSecret `homelab-mcp` writes it as `HOMELAB_MCP_REPLOG_SIGNING_PRIVATE_KEY`; `HOMELAB_MCP_REPLOG_ON_BEHALF_PROOF` is `signed_jwt`. The public half is item `replog`, field `on_behalf_public_key`. There is no shared on-behalf credential |
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
| `replog.ryan` | Ryan's own RepLog coach service token. `/mcp/replog` reads this file and does not fall back to `homelab-mcp/replog_token`. There is no `replog.steffi` |

To give someone a per-user key:
1. Add them to `HOMELAB_MCP_USERS` in the HelmRelease.
2. Add the field to the item. The ExternalSecret extracts every field, so
   nothing else changes; force-sync it to skip the 12h wait. Every field of
   the item becomes a file there, so keep only credentials in it, and no two
   fields with the same label (the provider refuses those).

The volume is optional, so the pod starts before the item exists. A
per-user call then fails with `<upstream>_no_user_credential` and is
counted in `homelab_mcp_user_credential_missing_total`; it never falls back
to the shared key. `/mcp/steffi` and `/mcp/replog` set `credentials: "per_user"`.

The database passwords come from the postgres17 items (`schoolhouse`,
`lading`, `homelab-finance`, `finances-context`;
[postgres17.md](../platform/postgres17.md#1password)). The ExternalSecrets build the
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

The OAuth signing key is item `homelab-mcp-state`, field
`oauth_signing_key` (`HOMELAB_MCP_OAUTH_SIGNING_KEY`), copied on 28 Nov 2026
from `/var/lib/homelab-mcp/state/signing-key.pem` with the same SHA-256, so
tokens issued before the copy stay valid. Every pod signs and verifies with
it. Rotating it logs every client out once. The logins themselves are in
postgres17 ([Shared state](#shared-state)); the old `state.db` on the PVC is
only the import source. Losing the PVC loses the Signal identity, the vault
copy (Obsidian Sync restores it) and the finances checkout (it re-clones).

Also:

| Item | Fields | From Forge |
| --- | --- | --- |
| `homelab-mcp-signal` | `number`, `group_id`, `ops_group_id`, `bot_uuid`, `capture_senders` | `HOMELAB_MCP_SIGNAL_*` in sops `homelab-mcp/finance-signal-env` |
| `homelab-finance` | `report_password` (new field) | none; generate |
| `homelab-mcp-email` | `username`, `read_password`, `write_password` | none; Stalwart app passwords ([Email](#email)) |
| `homelab-mcp-email-send` | `send_password` | none; only when sending is wanted ([Email](#email)) |
| `homelab-mcp-icloud` | `username`, `password` | none; Apple app-specific password ([iCloud](#icloud)) |

`homelab-mcp-jobs` reuses `homelab-mcp` (`sidecar_token`,
`finances_repo_token`, `finances_*` amounts), `homelab-finance/export_db_password`,
`lading/reader_password` and `homelab-finance/report_password`.

## Email

The `email_*` tools (carpenike/mcp 0.71.0, `docs/EMAIL.md` there) read and
draft in Ryan's personal Stalwart mailbox over JMAP at
`https://mail.${SECRET_DOMAIN}`, through envoy-internal. Microsoft/VA work
mail is not in that mailbox and stays out of these tools.

| Setting | Value | Why |
| --- | --- | --- |
| `HOMELAB_MCP_EMAIL_VIEWS` | `/mcp`, `/mcp/full`, `/mcp/agent/grokbot` | Every other view is refused before any request |
| `HOMELAB_MCP_EMAIL_SEND_VIEWS` | `/mcp/full`, `/mcp/agent/grokbot` | The connectors that can preview and send (Ryan, 2026-11-25). On Grokbot the gate is the model's own check, so the budget and recipient lists bound it |
| `HOMELAB_MCP_EMAIL_RECIPIENT_DENYLIST` | `@va.gov` | Personal mail stays away from VA. `@microsoft.com` is allowed: the agents send calendar invites to Ryan's work address |
| Grokbot tool list | read, draft, reply and forward drafts, moves, keywords, preview and send | |

Credentials are three Stalwart app passwords, created by Ryan in the
self-service portal, each with `allowedIps` `10.42.0.0/16` (Stalwart sees
the pod address in Envoy's `X-Forwarded-For`) and an expiry:

1. `read_password`: permissions `Disable` with `emailSend` and the JMAP
   set methods. Used by the read tools.
2. `write_password`: `Disable` with `emailSend`. Drafts, moves, keywords.
3. `send_password`: `Inherit`. Only `email_send_draft` uses it. It lives in
   its own item, `homelab-mcp-email-send`, so sending is a separate opt-in:
   without that item every connector is drafts-only.

Put the login and the first two in item `homelab-mcp-email`. Both Secrets
are optional in the HelmRelease, so the pod starts without them and the
tools answer `email_not_configured` or `email_send_disabled`. Reloader
restarts the pod when they appear. Revoking an app password in Stalwart
cuts that capability at once.

The pod's egress allows `mail.${SECRET_DOMAIN}` on 443. Stalwart's policy
already admits envoy-internal on 8080, so it needs no change.

From 0.72.0 the same tools also schedule sends, cancel them, report
delivery status, manage the vacation auto-reply and Sieve filters, draft
unsubscribe requests, list top senders and unanswered threads, and snooze.
Grokbot gets all of these except `email_set_vacation` and the filter
writes, which change how the whole mailbox answers and routes mail. The
scheduler runs `homelab-email-snooze-wake` every 5 minutes with the write
password (it can move mail, never send). Check the Stalwart details
carpenike/mcp `docs/EMAIL.md` lists (spam header, FUTURERELEASE, Sieve and
vacation permissions) before relying on them.

A per-user connector (Steffi's, later) reads its own mailbox from
`email.<alias>` in the user-credentials Secret, JSON with `username`,
`read_password`, `write_password` and optional `send_password`, and never
Ryan's. Add her view to `EMAIL_VIEWS` (and `EMAIL_SEND_VIEWS` to send) when
that file exists. The snooze job wakes only Ryan's mailbox until the
scheduler also mounts the user-credentials Secret.

## Dinner planner

The `meals_*` tools (carpenike/mcp `docs/MEALS.md`) plan household dinners
over NYT Cooking, the cookbook, MyFitnessPal and Grocy. They are on `/mcp`
and `/mcp/full` through the `"read"` and `"all"` tiers and are listed on
`/mcp/steffi`. No `/mcp/agent/*` view carries them.

- Store: postgres17 database `meals`, schema `meals`, role `meals`
  (`HOMELAB_MCP_MEALS_PG_DSN` in `homelab-mcp-env` and `homelab-mcp-jobs`,
  password from item `meals`, field `db_password`;
  [postgres17.md](../platform/postgres17.md#1password)). The plan, cook log
  and preferences are shared by everyone on a meals view, by design.
- NYT stays Ryan's: a `per_user` caller never reaches it and reads the
  shared recipe pool instead. The scheduler runs `homelab-meals-refresh` at
  03:15 to top the pool up, with the NYT cookie file mounted read-only and
  inside the planner's daily NYT budget. Exit 1 means NYT refused (expired
  session or rate limit); renew the cookie as carpenike/mcp
  `docs/NYT-COOKIE-RUNBOOK.md` describes.
- Budgets: `HOMELAB_MCP_MEALS_SLOTS` holds Ryan's dinner slot from
  `Personal/Fitness/Plan.md` ("Daily budget"). `HOMELAB_MCP_MEALS_VAULT_TARGETS`
  points at `Personal/Fitness/Status.md`, whose `target_kcal` and
  `target_protein_g` frontmatter are the day's targets. Steffi has neither
  yet, so she gets nutrition only and no diary comparison.

## Shared state

The server's own state is in postgres17 database `homelab_mcp`, so a second
replica sees the same logins, previews and tool state
(carpenike/mcp #208, #209, #213):

| Schema (login) | Holds | DSN in `homelab-mcp-env` |
| --- | --- | --- |
| `mcp_oauth` (`homelab_mcp_oauth`) | OAuth clients, refresh token digests and tombstones, consents, authorization codes, pending logins | `HOMELAB_MCP_OAUTH_STATE_DSN` |
| `mcp_gate` (`homelab_mcp_gate`) | consumed preview token digests | `HOMELAB_MCP_GATE_CONSUMED_DSN` |
| `mcp_tools` (`homelab_mcp_tools`) | ARC Raiders state, the calendar feed host allowlist, the finances classification memo, Withings tokens | `HOMELAB_MCP_TOOL_STATE_DSN` |

Passwords are item `homelab-mcp-state`, fields `oauth_password`,
`gate_password` and `tools_password`
([postgres17.md](../platform/postgres17.md#1password)). Field
`gate_token_key` is `HOMELAB_MCP_GATE_TOKEN_KEY`, the HMAC key every replica
signs previews with; the gate refuses the shared DSN without it.

The first start with each DSN copies that store's files from the state
volume (`state.db`, `arcraiders.db`, `icloud-feed-hosts.db`,
`finances-state.json`, `withings-token*.json`) into empty tables, once, and
never writes the files. Rolling back means removing the DSNs: the files are
as they were at the cutover, so a connector that logged in since logs in
once more, and a rotated Withings token needs `python -m homelab_mcp.tools._withings seed` again ([Withings](#withings)).

## Web and worker

Two Deployments run the same server image, so a release no longer takes the
public route down for the length of a pod restart:

- **web** (2 replicas, RollingUpdate, a PodDisruptionBudget of one) mounts
  no PVC. It holds logins and tokens, runs the tools whose state is in
  postgres17 or upstream, and is the only pod envoy may reach.
- **homelab-mcp**, the worker (1 replica, Recreate), keeps every volume and
  sidecar: the vault and Obsidian Sync, signal-api and capture, the Actual
  sidecar, the scheduler and the finances checkout. Service
  `homelab-mcp-worker` reaches its app container on 9200, and its policy
  admits only the web pods there.

The web pods forward a `tools/call` for any tool in
`HOMELAB_MCP_WORKER_TOOLS` to the worker with the caller's own bearer token
(carpenike/mcp #214). The worker checks that token itself, against the same
signing key, and applies the same view and vault policy, so a web pod
asserts nothing on the caller's behalf. Forwarded today: `vault_*`,
`finances_*`, `meals_*`, `signal_send`, and `email_preview_send_draft` /
`email_send_draft`, whose hourly and daily send budget lives in one
process's memory. While the worker restarts (about 20 seconds) those tools
answer `worker_unavailable` with a hint to retry; everything else keeps
working.

Service `homelab-mcp` (the route, and the web pods' /metrics) selects the
web pods. Service `homelab-mcp-worker` carries the worker's 9200 and both of
its metrics ports; alert `HomelabMcpWorkerDown` watches it.

Rolled out on 28 Nov 2026 in two pull requests: the web pods first, beside
the worker and with no traffic, then the Service switch. Rolling back the
switch means pointing Service `homelab-mcp` at controller `homelab-mcp`
again and admitting envoy on the worker's 9200.

Still per pod, so two replicas allow twice as much: the dynamic client
registration rate limit (`HOMELAB_MCP_OAUTH_REGISTER_RATE_LIMIT_MAX`).

## iCloud

The `icloud_*` tools (carpenike/mcp 0.72.0, `docs/ICLOUD.md` there) read
and change Ryan's Apple calendars over CalDAV and read his contacts over
CardDAV. Calendars and contacts live in iCloud, not Stalwart.

The credential is the main risk: an Apple app-specific password cannot be
scoped, so the one in item `homelab-mcp-icloud` also opens iCloud Mail and
Contacts. The server keeps every request on Apple's CalDAV/CardDAV hosts
and the account's own collections, keeps contacts read-only, and requires
preview then confirm for any event with attendees (iCloud emails them as
Ryan) and for every update or delete. The pod's egress allows only
`caldav.icloud.com`, `contacts.icloud.com` and their `pNN-` partition
hosts. Revoke the password at appleid.apple.com to cut it at once.

| Setting | Value | Why |
| --- | --- | --- |
| `HOMELAB_MCP_ICLOUD_VIEWS` | `/mcp`, `/mcp/full`, `/mcp/agent/grokbot` | Every other view is refused before any request |
| `HOMELAB_MCP_ICLOUD_WRITE_VIEWS` | `/mcp/full`, `/mcp/agent/grokbot` | One gated calendar path for both agents (Ryan, 2026-11-25) |
| Grokbot tool list | the 11 calendar and contact `icloud_*` tools, not the four feed-host tools | Writes still need Ryan's confirmation through the preview |
| `HOMELAB_MCP_ICLOUD_FEED_HOSTS` | `outlook.office365.com`, `api.team-manager.gc.com`, `ical-cdn.teamsnap.com`, `calendar.google.com`, `groups.planningcenteronline.com`, `www.fcps.org` | Hosts subscribed-calendar feeds are fetched from (0.73.0); fetched through feed-proxy |
| `HOMELAB_MCP_ICLOUD_FEED_PROXY_URL` | `http://homelab-mcp-feed-proxy.homelab-mcp.svc.cluster.local:9300` | The feed-proxy pod (0.74.0); this pod's egress lists no feed hosts |
| `HOMELAB_MCP_ICLOUD_FEED_ADMIN_VIEWS` | `/mcp/full` | The only connector that may approve a new feed host (Ryan, 2026-11-26) |
| `HOMELAB_MCP_ICLOUD_SUBSCRIBED_VIEWS` | `/mcp`, `/mcp/full`, `/mcp/agent/grokbot` | Subscribed calendars not named below, the work feed included (Ryan, 2026-11-26) |
| `HOMELAB_MCP_ICLOUD_CALENDAR_VIEWS` | `{}` | Calendar name or id -> views; name a calendar here to narrow who sees it |

A subscribed calendar (an ICS feed added to the iCloud account) holds only
its feed URL, which is a secret link and never shown. When
`icloud_list_calendars` reports `feed_allowed: false`, Ryan approves the
host it names in chat from Home (full): `icloud_preview_allow_feed_host`,
then `icloud_allow_feed_host` with the token. No pull request is needed.
Approvals are kept in `icloud-feed-hosts.db` on the state volume.

The `feed-proxy` controller is a second pod from the same image
(`homelab-feed-proxy`). It holds no secrets and no service-account token,
and its policy admits only the homelab-mcp pod on 9300. Its egress is 443
to public IPv4 only, with every private and reserved range excepted. The
proxy also refuses any name that resolves to a non-public address. Code
running in the main pod could send data out in a URL through it. That
takes control of the server, not a prompt, and is the accepted cost of
approving hosts from chat (carpenike/mcp `docs/ICLOUD.md`).

A per-user connector uses `icloud.<alias>` (JSON `username`, `password`)
from the user-credentials Secret, never Ryan's Apple ID.

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
| `HomelabMcpWithingsTokenUnusable` | No Withings token, or Withings refused it and a refresh, for 1 hour |
| `HomelabMcpObsidianSyncDown` | The `obsidian-sync` container has not been running for 15 minutes |
| `HomelabMcpObsidianSyncRestarting` | `obsidian-sync` restarted more than twice in an hour |
| `HomelabMcpOauthRefreshReuseRevoked` | Refresh-token reuse detection revoked a family (homelab-mcp 0.68.0+): a client is locked out until it signs in again, or a token leaked |
| `HomelabMcpOauthRefreshReissuedOften` | The lost-response grace re-issued refresh tokens more than twice in a day (info) |

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
   ([postgres17.md](../platform/postgres17.md#restore-from-forge-cutover)).
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
