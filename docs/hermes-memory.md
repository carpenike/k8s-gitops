# Hermes memory (Hindsight)

Long-term memory for the Hermes bots ([hermes.md](hermes.md)):
[Hindsight](https://github.com/vectorize-io/hindsight) 1.2.0 (MIT), one shared
server in namespace `hermes-memory`, one Postgres schema per bot.

```
 hermes-<bot> agent pod ──8888──▶ hindsight (hermes-memory) ──4000──▶ LiteLLM (claude-haiku)
   Bearer <bot key>                  │ in-process: embeddings + reranker
                                     └──5432──▶ postgres17 (cnpg-system), database hindsight
                                                 schema user_<bot> per bot
```

## What runs

`kubernetes/apps/hermes-memory`:

| Object | What |
| --- | --- |
| HelmRelease `hindsight` | Chart `oci://ghcr.io/vectorize-io/charts/hindsight` 1.2.0, one API pod (with the in-process worker), image `ghcr.io/carpenike/hindsight` |
| Service `hindsight` | `http://hindsight.hermes-memory.svc.cluster.local:8888`, the address the bots use. The chart's own Service is `hindsight-api` |
| ExternalSecrets `hindsight-db`, `hindsight-tenants` | Database password; the per-bot tenant keys |
| Kustomization `hindsight-litellm` | LiteLLM key `hermes-memory`, Secret `litellm` |
| CronJob `hindsight-backup` + VolSync | Nightly dump, copied to R2 |

Settings worth knowing:

- **Image** (`images/hindsight`, built by `hindsight-image.yaml`):
  upstream `hindsight-api:1.2.0`, the full API image the chart deploys, by
  digest. It adds the static-keys tenant extension, vendored from the
  v1.2.0 release commit, and the build fails if the extension doesn't
  import. **One local change** (see [Base schema](#base-schema)).
- **Models, in-process, baked into the image:** embeddings
  `BAAI/bge-small-en-v1.5` (384 dimensions) and reranker
  `hindsight-ai/hs-rerank-1`. `HF_HUB_OFFLINE=1`. **The embedding model is
  fixed:** changing it means re-embedding every memory, so treat it as
  permanent.
- **LLM** (fact extraction, reflection): `openai`-compatible provider at
  `http://litellm.litellm.svc.cluster.local:4000/v1`, model `claude-haiku`,
  key `hermes-memory` (claude-haiku only, USD 10 per 30 days, team
  `hermes`). Structured output through LiteLLM works for that model
  (checked 4 Nov 2026), so `HINDSIGHT_API_LLM_STRUCTURED_OUTPUT_IN_PROMPT`
  stays unset.
- **LLM request tracing is off** (`HINDSIGHT_API_LLM_TRACE_ENABLED=false`;
  upstream defaults it on and stores prompts and replies in the database).
  So is OpenTelemetry.
- **Off as well:** the control-plane UI, any HTTPRoute, and the chart's
  embedded Postgres.
- **Database:** `hindsight` on `postgres17`, owned by role `hindsight`.
  CNPG installs `vector`, `pg_trgm` and `btree_gin` in `public`, where
  Hindsight expects them; the role couldn't create them itself.
- **Tenants:** the static-keys extension maps each API key to a user. User
  `<bot>` gets schema `user_<bot>`, migrated on first use. The bots all use
  bank id `hermes`, so isolation comes from the schema, not the bank.
- **Sizing:** idle with both models loaded, the pod uses about 1.6 GiB
  (measured on 1.2.0, amd64). Embedding and reranking run on its CPU.
  Limit 4 GiB and 2 CPUs; request 2 GiB.

### Base schema

Hindsight migrates, at startup, exactly the schemas the tenant extension's
`list_tenants()` returns (`engine/memory_engine.py`). Its database-wide
maintenance routines (`banks_needing_consolidation()`,
`schemas_with_expired_rows(...)`, `mental_models_with_cron()`) are
installed only by the run that targets the configured base schema,
`public` (alembic `b6d2f8a4c1e7`; the loop calls them through
`engine/schema.py` `fq_routine`).

Upstream's static-keys extension returns only the user schemas, at v1.2.0
and on `main` as of 4 Nov 2026. `public` was never migrated, and every
maintenance cycle logged:

```
Consolidation reconcile discovery failed: function public.banks_needing_consolidation() does not exist
Scheduled mental model refresh discovery failed: function public.mental_models_with_cron() does not exist
```

Consolidation itself still ran, because each retain queues it. What was
missing is the reconcile pass that reschedules consolidation that was
never queued (after a crash, for example), and the cron mental-model
refresh, which nothing uses yet.

The vendored `list_tenants()` therefore returns the base schema first,
then the users, as Hindsight's built-in extensions do. Startup migrates
`public` too, and the routines land there once. The worker also polls
`public` for tasks; it holds none. No API key maps to `public`
(user schemas are always `user_<id>`), so no request can reach it.

Upstream tracks this as
[vectorize-io/hindsight#5400](https://github.com/vectorize-io/hindsight/issues/5400)
(open; reported on 0.10.1, confirmed on 1.1.0 and, with this fix, on
1.2.0). Upstream doesn't accept outside pull requests, so the fix has to
come from them. When re-vendoring the extension or upgrading Hindsight,
check that issue:

- **Fixed in the extension** (`list_tenants()` returns the base schema):
  take upstream's version and drop the local change.
- **Fixed in the engine** (startup migrates the base schema itself): drop
  the local change. Upstream's extension is then fine as it is.
- **Still open:** re-apply the change.

The workaround in the issue, running `hindsight-admin run-db-migration
--schema public` before the server starts, does the same job without
patching the extension. It isn't used here.

### Updating the image

`hindsight-image.yaml` tags each build `<version>-<sha>`. A build on
`rebuild` also moves the floating `<version>` tag (`1.2.0`), which the
HelmRelease pins by digest (`tag: 1.2.0@sha256:…`). The package is
public, so Renovate reads it without credentials.

- **Rebuilds** (a change under `images/hindsight`, or the weekly Friday
  rebuild): Renovate's **self-built images** PR re-pins the digest, together
  with the Hermes images. The weekly rebuild fires only once `rebuild` is
  the default branch, because GitHub runs schedules only from there.
- **A new Hindsight release**: Renovate's **hindsight** group moves the
  chart, `ARG HINDSIGHT_IMAGE` and `HINDSIGHT_VERSION` in the workflow in
  one PR. Before merging, re-vendor the tenant extension from the new
  release commit, re-apply the [Base schema](#base-schema) change if
  vectorize-io/hindsight#5400 is still open, and update the version in
  the HelmRelease's header comment. After the merge, the self-built images PR moves the pin to the
  new tag. Until it merges the new chart runs the old image. If the
  release notes say the chart needs the new API, put the branch build's
  digest in the group PR instead (`tag: <new>@sha256:<branch build>`).
  Renovate corrects it to the `rebuild` build afterwards.

## Network

Default deny in `hermes-memory`, both ways.

| Pod | In | Out |
| --- | --- | --- |
| hindsight | TCP 8888 from pods with `app.kubernetes.io/name=hermes` **and** `app.kubernetes.io/controller=agent`, in namespaces labelled `hermes.holthome.net/bot` | DNS; LiteLLM pods on 4000; postgres17 pods on 5432 |
| hindsight-backup | none | DNS; postgres17 on 5432 |
| hindsight-volsync | none | DNS; public IPv4 (R2) |

Screen pods (`controller=screen`) never match. `hermes-memory` itself
deliberately has no `hermes.holthome.net/bot` label. Bots reach it through
their own agent-egress policy (component input `HINDSIGHT_ENABLED`).

## Keys and 1Password

| Item (vault `k8s-secrets`) | Field | Used by |
| --- | --- | --- |
| `hindsight` | `database_password` | CNPG role `hindsight` (raw); the server's database URL (URL-encoded); the backup job (raw) |
| `hermes-<bot>` | `hindsight_api_key` | `hindsight-tenants` (server side) and the bot's own `hindsight` Secret (client side) |

Bot keys must be ASCII, with no commas, and unique across bots. Use
`openssl rand -hex 32`.

To add a bot, create its `hindsight_api_key` field. Then, in
`kubernetes/apps/hermes-memory/hindsight/app/externalsecret.yaml`, add one
`data` entry and `,<bot>:{{ .<bot> }}` to `HINDSIGHT_API_TENANT_USERS`, and
set the bot's `HINDSIGHT_ENABLED=true`. The tenant list is explicit: a bot
not listed gets 401.

### Rotating a bot's key

The extension accepts several keys for one user, but **rejects duplicate
keys at startup**. So the overlap has to keep old and new different:

1. Add field `hindsight_api_key_next` (the new key) to `hermes-<bot>`. Then,
   in a PR, add it to the tenants ExternalSecret. The `ne` keeps a single
   entry once both fields hold the same value:
   ```yaml
   HINDSIGHT_API_TENANT_USERS: "chief:{{ .chief }}{{ if and .chief_next (ne .chief .chief_next) }},chief:{{ .chief_next }}{{ end }}"
   ```
   ```yaml
   - secretKey: chief_next
     remoteRef:
       key: hermes-chief/hindsight_api_key_next
   ```
   After merge, Reloader restarts Hindsight, which now accepts both keys.
   The `and .chief_next` guard matters. An empty `_next` field would render
   `,chief:`, the extension refuses that at startup, and under `Recreate`
   that is an outage until the template is fixed.
2. **Roll:** copy the new key into `hindsight_api_key`. Force-sync the bot
   first, then the server:
   ```sh
   kubectl -n hermes-<bot> annotate externalsecret hindsight force-sync="$(date +%s)" --overwrite
   kubectl -n hermes-memory annotate externalsecret hindsight-tenants force-sync="$(date +%s)" --overwrite
   ```
   The bot restarts on the new key. The server drops to one entry (both
   fields now equal), so the old key stops working.
3. **Remove** the `_next` entry and field in a follow-up PR.

The database password rotates the same way as LiteLLM's: change the field,
then force-sync `cnpg-system/hindsight-db` and `hermes-memory/hindsight-db`.
Reloader restarts the server.

## Backups

`hindsight-backup` runs at **02:30 UTC**. It dumps the whole `hindsight`
database (every bot's schema) with `pg_dump -Fc`, as role `hindsight`,
using the same image and version as postgres17. Each dump is checked with
`pg_restore --list` before it counts. Dumps land on PVC `hindsight-dumps`
(5 GiB, ceph-block) as `hindsight-<UTC stamp>.dump`, seven kept.

VolSync copies that volume to R2 (path `hermes-memory`, item
`volsync-r2-template`) at **03:15 UTC**, keeping 7 daily and 4 weekly. A
recreated `hindsight-dumps` PVC is filled from the latest R2 snapshot
first, like a bot's `agent-data`.

Check a night's run:

```sh
kubectl -n hermes-memory get jobs --sort-by=.metadata.creationTimestamp   # newest last
kubectl -n hermes-memory logs job/<newest>                                  # "wrote /dumps/hindsight-…"
kubectl -n hermes-memory get replicationsource hindsight-dumps -o jsonpath='{.status.latestMoverStatus.logs}' | grep -E 'snapshot [0-9a-f]+ saved'
```

**Before any real memory goes in**, run the job once by hand and check that
both lines show:

```sh
kubectl -n hermes-memory create job --from=cronjob/hindsight-backup hindsight-backup-manual
```

### Restore

Stop the server first, so nothing writes during the restore:

```sh
flux -n hermes-memory suspend helmrelease hindsight
kubectl -n hermes-memory scale deploy/hindsight-api --replicas 0
```

Then start a shell with the dumps and the password. The one-off pod reuses
the backup job's labels, so its network policy applies:

```sh
kubectl -n hermes-memory run hindsight-restore --rm -it --restart=Never \
  --image=ghcr.io/cloudnative-pg/postgresql:17.9 \
  --labels=app.kubernetes.io/name=hindsight-backup \
  --overrides='{"spec":{"securityContext":{"runAsUser":26,"runAsGroup":26,"fsGroup":26,"runAsNonRoot":true,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"hindsight-restore","image":"ghcr.io/cloudnative-pg/postgresql:17.9","stdin":true,"tty":true,"command":["bash"],"env":[{"name":"PGPASSWORD","valueFrom":{"secretKeyRef":{"name":"hindsight-db","key":"PGPASSWORD"}}},{"name":"PGHOST","value":"postgres17-rw.cnpg-system.svc.cluster.local"},{"name":"PGUSER","value":"hindsight"},{"name":"PGDATABASE","value":"hindsight"},{"name":"PGSSLMODE","value":"require"}],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}},"volumeMounts":[{"name":"dumps","mountPath":"/dumps"}]}],"volumes":[{"name":"dumps","persistentVolumeClaim":{"claimName":"hindsight-dumps"}}]}}'
```

Inside it:

```sh
ls -1t /dumps                                    # newest first
pg_restore --list /dumps/hindsight-<stamp>.dump | grep ' SCHEMA '

# One bot: only its schema, objects dropped and recreated.
pg_restore --clean --if-exists --no-owner --role=hindsight -n user_<bot> \
  -d hindsight /dumps/hindsight-<stamp>.dump

# Whole database: every schema the dump lists, public included. Extensions
# are left alone (any -n skips them; CNPG owns them).
pg_restore --clean --if-exists --no-owner --role=hindsight \
  -n public -n user_chief -n user_<other> -d hindsight /dumps/hindsight-<stamp>.dump
```

Then resume:

```sh
flux -n hermes-memory resume helmrelease hindsight
```

Upstream also has `hindsight-admin backup <file>.zip --schema user_<bot>`
and `hindsight-admin restore … --schema user_<bot>`. They run in the server
pod and restore by deleting and reinserting rows. The dumps above are the
supported path here.

If the dump volume itself is gone, VolSync refills it from R2 when the PVC
is recreated. For an older snapshot, use a one-off `ReplicationDestination`
with `restoreAsOf`, as in [hermes.md](hermes.md) ("Restoring into an
existing volume").

## Deleting memory

- **One bank, using the bot's own key** (bank `hermes` is everything that
  bot remembers). Run it in the bot's agent pod, the only place allowed to
  reach 8888, which already has the key in `$HINDSIGHT_API_KEY`:
  ```sh
  kubectl -n hermes-<bot> exec deploy/hermes-agent -c app -- sh -c \
    'curl -sS -X DELETE -H "Authorization: Bearer $HINDSIGHT_API_KEY" "$HINDSIGHT_API_URL/v1/default/banks/hermes"'
  ```
- **A bot entirely:**
  1. Remove it from `hindsight-tenants` and set its `HINDSIGHT_ENABLED`
     back to false.
  2. Drop the schema:
     ```sh
     psql -c 'DROP SCHEMA user_<bot> CASCADE;'
     ```
     run in the restore shell above.
  3. The nightly dumps still hold it until they age out of the seven
     local copies and the R2 retention (7 daily, 4 weekly).
- **Everything:** suspend the HelmRelease, delete the `Database` object and
  drop database `hindsight`. Its `databaseReclaimPolicy` is `retain`, so
  deleting the object alone keeps the data.

## A bot's side (input `HINDSIGHT_ENABLED`)

`HINDSIGHT_ENABLED=true` in a bot's inputs (today: Chief) adds, all gated
on that input in the hermes-bot HelmRelease:

- **ExternalSecret `hindsight`** in `hermes-<bot>`. It reads
  `hindsight_api_key` from item `hermes-<bot>` and adds fixed values:
  - `HINDSIGHT_MODE=local_external`;
  - `HINDSIGHT_API_URL=http://hindsight.hermes-memory.svc.cluster.local:8888`;
  - `HINDSIGHT_BANK_ID=hermes`, `HINDSIGHT_TIMEOUT=30`;
  - `HINDSIGHT_RETAIN_INDICATOR=false`, `HINDSIGHT_RECALL_INDICATOR=false`.

  The agent's containers read it through an optional `envFrom`; the screen
  never does. Hermes strips `HINDSIGHT_API_KEY` and `HINDSIGHT_API_URL`
  from child processes.
- **CNP `agent-hindsight`:** agent egress to the Hindsight pods on 8888.
- **The plugin.** The agent image (`images/hermes-agent`) carries the
  Hindsight Hermes plugin at `/opt/hermes-plugins/hindsight`, vendored from
  the commit Hermes v0.22.6's `plugin-catalog/hindsight.yaml` pins
  (`d952b6e6`, plugin 1.2.3). It also has `hindsight-client` 0.10.1, the
  version the plugin's lockfile resolves, in Hermes' venv. On each boot the
  `config` init container, only when the key is there:
  1. copies the plugin to `$HERMES_HOME/plugins/hindsight` (`/opt/data`,
     the PVC, would shadow anything baked there);
  2. runs `hermes config set memory.provider hindsight`.

  Without the key (no 1Password field) it unsets the provider, and the bot
  keeps Hermes' built-in memory instead of failing every turn. It warns if
  a `config.json` exists.

**How Hermes finds it** (`plugins/memory/__init__.py` at v0.22.6): memory
providers are discovered by directory name, in this order, first match
wins:

1. bundled `plugins/memory/<name>/` in the Hermes tree;
2. `$HERMES_HOME/plugins/<name>/`;
3. `./.hermes/plugins/<name>/`, only with `HERMES_ENABLE_PROJECT_PLUGINS`;
4. `hermes_agent.memory_providers` entry points.

A directory counts if its `__init__.py` defines a `MemoryProvider`. There
is no enable list: `memory.provider` names the one active provider. The
image build copies the plugin into a scratch `$HERMES_HOME`, then checks
`find_provider_dir("hindsight")` and `load_memory_provider("hindsight")`.

## Never run `hermes memory setup` in a pod

The bots are configured by environment only: Secret `hindsight` in
`hermes-<bot>`, with mode `local_external`, the URL, bank `hermes`, the key
and the timeout. The plugin reads that environment **only when there is no
config file**. `hermes memory setup` breaks this in three ways:

- it writes `$HERMES_HOME/hindsight/config.json`, which then wins over every
  environment variable, key and URL included;
- it fetches a bank-template catalogue from GitHub;
- it can switch the bot to embedded mode, which wants to start a local
  daemon.

The agent pod has no route to the internet, so the result is a bot that
silently has no memory. If a `config.json` turns up in a bot's volume,
delete it and restart the bot.

## After merge: tests

Once the 1Password fields exist and Flux has reconciled:

1. `/health` is OK. The server logs the local embeddings (384-dim) and
   reranker, with no download.
2. A write and a recall with Chief's key work.
3. A wrong key returns 401.
4. A second test tenant can't read `user_chief`.
5. A Chief **screen** pod can't reach `hindsight.hermes-memory:8888`.
6. Restoring the test tenant from a manual backup works.
7. A Chief turn shows a retain, and the next turn a recall.
