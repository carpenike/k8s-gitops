# postgres17

Cluster `postgres17` in `cnpg-system` is the shared PostgreSQL 17 database:
LiteLLM's `litellm` ([litellm.md](litellm.md)) and Hindsight's `hindsight`
([hermes-memory.md](hermes-memory.md)). Losing it loses bot memory and the
proxy's keys and spend.

## postgres17 backup and restore

Two copies, both taken by CloudNativePG:

| What | Where | When | Kept |
| --- | --- | --- | --- |
| Volume snapshot (`ScheduledBackup` `postgres17-daily`) | Ceph, `csi-ceph-block`. Does not leave the chassis | 03:00 UTC | Until deleted (`backupOwnerReference: cluster`) |
| Barman base backup (`ScheduledBackup` `postgres17-r2-daily`) | Cloudflare R2, `s3://<bucket>/cnpg/postgres17/base/` | 08:30 UTC (03:30 EST, 04:30 EDT) | 30-day recovery window |
| WAL archive | Same, `…/cnpg/postgres17/wals/` | Continuous. `archive_timeout` is 5 minutes | Same window |

Hindsight also has its own nightly `pg_dump` to R2
([hermes-memory.md](hermes-memory.md#backups)). That one restores a single
bot's schema. The R2 copy here restores the whole server to any point in
the last 30 days.

### How it is wired

The Barman Cloud plugin (`kubernetes/apps/cnpg-system/barman-cloud`, chart
0.8.1, plugin v0.15.1) does the R2 side. CloudNativePG 1.30.1 supports it,
and the in-tree `spec.backup.barmanObjectStore` is deprecated in favour of
it.

- `postgres17/app/objectstore.yaml`: ObjectStore `postgres17-r2`,
  `retentionPolicy: 30d`, gzip for WAL and base backups.
- `postgres17/app/cluster.yaml`: `spec.plugins` names the plugin with
  `isWALArchiver: true` and `barmanObjectName: postgres17-r2`.
- `postgres17/app/scheduledbackup.yaml`: `postgres17-r2-daily`,
  `method: plugin`, `immediate: true` (one base backup as soon as it is
  created; see "First check after merge" if that one fails). It runs on the
  standby when one is in sync.
- `postgres17/r2/externalsecret.yaml`: Kustomization `postgres17-r2` makes
  Secret `postgres17-r2` (keys `ACCESS_KEY_ID`, `ACCESS_SECRET_KEY`) and
  Secret `postgres17-r2-vars` (`CNPG_R2_ENDPOINT`, `CNPG_R2_BUCKET`). The R2
  endpoint contains the account id, so it stays out of this public repo.
  Kustomization `postgres17` substitutes those two values into the
  ObjectStore and depends on `postgres17-r2`.
- `postgres17/app/podmonitor.yaml` and `prometheusrule.yaml`: Prometheus
  scrapes the instances and alerts (below).

If the 1Password item is missing or unreadable, `postgres17-r2` stays
unready, and `postgres17` (with `litellm` and `hindsight`, which depend on
it) waits. Nothing is deleted or restarted: Flux simply stops applying
changes until the item exists.

### 1Password

Item `postgres17-r2` in vault `k8s-secrets`, in the same Cloudflare account
as `volsync-r2-template`:

| Field | Value |
| --- | --- |
| `access_key_id` | Access key id of an R2 API token with Object Read & Write on the bucket only |
| `secret_access_key` | That token's secret access key |
| `endpoint_url` | `https://<account id>.r2.cloudflarestorage.com`, no bucket and no trailing slash |
| `bucket` | Bucket name. A new bucket for CNPG is preferred, so the token cannot touch the VolSync repositories. The `cnpg/postgres17/` prefix keeps it apart if the VolSync bucket is reused |

Do not add an R2 lifecycle rule that deletes objects under `cnpg/`; Barman
removes what falls out of the 30-day window, and a lifecycle rule would
break the WAL chain.

### Alerts

`PrometheusRule` `postgres17-backup` (`cnpg-system`). The CNPG operator
chart ships no rules, so nothing else covers this.

| Alert | Fires when | First check |
| --- | --- | --- |
| `Postgres17WALArchivingFailing` | The latest `archive_command` failure is newer than the latest success, for 30 min | `kubectl cnpg status postgres17 -n cnpg-system`; log of container `plugin-barman-cloud` on the primary |
| `Postgres17WALArchivingStalled` | The primary has archived nothing in 24 h | Same |
| `Postgres17BackupFailed` | The latest base backup to R2 failed | `kubectl -n cnpg-system get backup --sort-by=.metadata.creationTimestamp` |
| `Postgres17BackupStale` | No good base backup in 30 h (or none ever), for 1 h | `kubectl -n cnpg-system get scheduledbackup postgres17-r2-daily` |
| `Postgres17MetricsAbsent` | Prometheus has no postgres17 series for 30 min, so the alerts above cannot fire | `kubectl -n cnpg-system get podmonitor postgres17` |

While WAL cannot be archived it stays in `pg_wal` on the 20 GiB volume, so
a failing archive eventually fills the disk. Treat the first alert as
urgent.

### First check after merge

Wait for both Kustomizations and the instance rollout. Adding or removing
the plugin restarts the standby, then restarts the primary in place: the
Cluster uses `primaryUpdateMethod: restart`, so there is no switchover.
LiteLLM and Hindsight lose the database until the primary is back. On
2026-11-04 that took about three and a half minutes. Both reconnected on
their own; neither pod restarted.

```sh
flux -n cnpg-system get kustomizations | grep -E '^(NAME|postgres17)'
kubectl -n cnpg-system get externalsecret postgres17-r2 postgres17-r2-vars
kubectl -n cnpg-system get pods -l cnpg.io/cluster=postgres17 \
  -o 'custom-columns=NAME:.metadata.name,ROLE:.metadata.labels.cnpg\.io/instanceRole,INIT:.spec.initContainers[*].name,CONTAINERS:.spec.containers[*].name'
```

Each pod should list `plugin-barman-cloud`, under INIT when the plugin
injects it as a native sidecar, otherwise under CONTAINERS. Then archiving, which must say
OK and show a recent last-archived WAL. `kubectl cnpg` is the krew plugin
(`kubectl krew install cnpg`); keep it at the operator's version, 1.30.x.
`ContinuousArchiving=True` alone proves nothing: it was already true before
this change, when `archive_command` had nowhere to send WAL.

```sh
kubectl cnpg status postgres17 -n cnpg-system
kubectl -n cnpg-system get cluster postgres17 \
  -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")]}{"\n"}'
```

The immediate base backup, and what the ObjectStore sees in R2:

```sh
kubectl -n cnpg-system get backup -l cnpg.io/scheduled-backup=postgres17-r2-daily
kubectl -n cnpg-system get objectstore postgres17-r2 \
  -o jsonpath='{.status.serverRecoveryWindow.postgres17}{"\n"}'
```

The `Backup` should reach `completed`, and the recovery window should show
`firstRecoverabilityPoint` and `lastSuccessfulBackupTime`.

The immediate backup can fail with `requested plugin is not available:
barman-cloud.cloudnative-pg.io`. That means it was created before the
instances restarted with the plugin sidecar; it happened on the first
rollout. WAL archiving is unaffected, but R2 has no base backup until the
next 08:30 UTC run. Take one by hand once both pods list
`plugin-barman-cloud`:

```sh
cat <<EOF | kubectl create -f -
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: postgres17-r2-manual-$(date -u +%Y%m%d%H%M)
  namespace: cnpg-system
spec:
  cluster:
    name: postgres17
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
EOF
kubectl -n cnpg-system get backup -w
```

The first one took about 15 seconds. Then list the
objects in R2 from a workstation. The values stay in the shell:

```sh
export AWS_ACCESS_KEY_ID="$(op read 'op://k8s-secrets/postgres17-r2/access_key_id')"
export AWS_SECRET_ACCESS_KEY="$(op read 'op://k8s-secrets/postgres17-r2/secret_access_key')"
R2="$(op read 'op://k8s-secrets/postgres17-r2/endpoint_url')"
B="$(op read 'op://k8s-secrets/postgres17-r2/bucket')"
nix shell nixpkgs#awscli2 -c aws s3 ls --endpoint-url "$R2" --region auto "s3://$B/cnpg/postgres17/base/"
nix shell nixpkgs#awscli2 -c aws s3 ls --endpoint-url "$R2" --region auto --recursive "s3://$B/cnpg/postgres17/wals/" | tail -5
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
```

`base/` holds one `<backup id>/` per base backup, each with `backup.info`
and `data.tar.gz`. `wals/` grows by a segment at least every few minutes.

Finally, Prometheus: the five rules load, and the target is up.

```sh
kubectl -n cnpg-system get prometheusrule postgres17-backup
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=barman_cloud_cloudnative_pg_io_last_available_backup_timestamp'
```

### Restore drill

Recover the R2 copy into a throwaway Cluster in namespace
`postgres17-drill`, check the two databases, delete it. Run it after the
first base backup, then every few months. It reads R2 and writes nothing
there: the drill Cluster has no `spec.plugins`, so it archives nothing, and
the copied ObjectStore drops `retentionPolicy`.

Manifests: [`kubernetes/examples/postgres17-restore-drill.yaml`](../kubernetes/examples/postgres17-restore-drill.yaml)
(not reconciled).

1. Namespace and credentials:

   ```sh
   yq 'select(.kind != "Cluster")' kubernetes/examples/postgres17-restore-drill.yaml | kubectl apply -f -
   kubectl -n postgres17-drill wait externalsecret/postgres17-r2 --for=condition=Ready --timeout=2m
   ```

2. ObjectStore, copied from the live one (endpoint and bucket are only
   there), without retention:

   ```sh
   kubectl -n cnpg-system get objectstore postgres17-r2 -o yaml \
     | yq '{"apiVersion": .apiVersion, "kind": .kind,
            "metadata": {"name": .metadata.name, "namespace": "postgres17-drill"},
            "spec": (.spec | del(.retentionPolicy))}' \
     | kubectl apply -f -
   ```

3. The Cluster. Recovery runs as job `postgres17-drill-1-full-recovery`,
   restores the latest base backup, and replays WAL to the end of the
   archive:

   ```sh
   yq 'select(.kind == "Cluster")' kubernetes/examples/postgres17-restore-drill.yaml | kubectl apply -f -
   kubectl -n postgres17-drill get pods -w     # Ctrl-C once postgres17-drill-1 is Running
   kubectl -n postgres17-drill wait cluster/postgres17-drill --for=condition=Ready --timeout=30m
   ```

4. Both databases exist, with rows. Save the query once:

   ```sh
   cat > /tmp/rowcounts.sql <<'SQL'
   SELECT table_schema AS schema, table_name AS "table",
          (xpath('/row/n/text()',
                 query_to_xml(format('SELECT count(*) AS n FROM %I.%I', table_schema, table_name),
                              false, true, '')))[1]::text::bigint AS rows
   FROM information_schema.tables
   WHERE table_type = 'BASE TABLE'
     AND table_schema NOT IN ('pg_catalog', 'information_schema')
   ORDER BY rows DESC
   LIMIT 15;
   SQL
   ```

   Then, in the drill Cluster:

   ```sh
   kubectl -n postgres17-drill exec postgres17-drill-1 -c postgres -- \
     psql -Atc "SELECT datname FROM pg_database WHERE datname IN ('litellm', 'hindsight') ORDER BY 1"
   for db in litellm hindsight; do
     echo "== $db"
     kubectl -n postgres17-drill exec -i postgres17-drill-1 -c postgres -- psql -d "$db" -f - < /tmp/rowcounts.sql
   done
   ```

   Expect both names, LiteLLM tables such as `LiteLLM_SpendLogs` and
   `LiteLLM_VerificationToken`, and Hindsight's tables in each
   `user_<bot>` schema. The same query on the live primary gives
   the numbers to compare against (read-only; a few rows of drift on busy
   tables is the time since the last archived WAL):

   ```sh
   primary=$(kubectl -n cnpg-system get pods -l cnpg.io/cluster=postgres17,cnpg.io/instanceRole=primary -o jsonpath='{.items[0].metadata.name}')
   for db in litellm hindsight; do
     echo "== $db"
     kubectl -n cnpg-system exec -i "$primary" -c postgres -- psql -d "$db" -f - < /tmp/rowcounts.sql
   done
   ```

5. Delete it. This removes the Cluster, its PVC and the copied ObjectStore.
   Objects in R2 are not touched:

   ```sh
   kubectl -n postgres17-drill delete cluster postgres17-drill
   kubectl delete namespace postgres17-drill
   ```

For a real restore, the same Cluster shape works under a new name in
`cnpg-system` (point-in-time: add `bootstrap.recovery.recoveryTarget.targetTime`).
Then repoint LiteLLM and Hindsight at its `-rw` Service, or rename it into
place. Give the restored Cluster its own `spec.plugins` entry with a new
`serverName` before it archives, so it never writes into
`cnpg/postgres17/`.

## Forge stores

Three databases moved here from Forge's local PostgreSQL so that homelab-mcp can run in the cluster:
- `schoolhouse` (grades scraped from Schoology),
- `lading` (Amazon, Costco and Sam's Club order history),
- `homelab_finance` (the household finance projection).

A fourth, `finances_context`, is new. It holds the shared transaction-context
table that the `finances_context_*` tools and Forge's Signal capture worker
both write to (carpenike/mcp #120).

The writers stay on Forge: the Schoolhouse scraper, lading's sync and the
Signal worker. Forge's Grafana does too. They connect to Service
`postgres17-forge` (LoadBalancer `10.45.10.52`, the primary) over TLS. The
export job and the homelab-mcp readers run in the cluster and use
`postgres17-rw` like every other app.

| Database | Owner (writes) | Readers | Connects from |
| --- | --- | --- | --- |
| `schoolhouse` | `schoolhouse` | `schoolhouse_reader` (homelab-mcp), `schoolhouse_grafana` | Owner and Grafana from Forge; reader in-cluster |
| `lading` | `lading` | `lading_reader` (homelab-mcp, finances export) | Owner from Forge; reader in-cluster |
| `homelab_finance` | `homelab_finance` (finances export CronJob) | `homelab_finance_money` (`money_overview` only), `homelab_finance_grafana` | Owner in-cluster (from Forge only for the restore); Grafana from Forge |
| `finances_context` | `finances_context` | none; the same role reads and writes | homelab-mcp in-cluster, Signal worker from Forge |

`pg_hba` admits Forge (`10.20.0.30`) for exactly the Forge rows above. It
rejects every other address on the node LAN, `10.20.0.0/16`. Cilium's
LoadBalancer is DSR, so Postgres sees Forge's own address. If that ever stops
holding, Forge is rejected: the rule fails closed.

Readers get no cluster-wide role. Each owner grants its own readers, once, at
restore time (below), and default privileges cover the tables its later
migrations create. One store's reader therefore cannot read another store,
unlike Forge's shared `readonly` group.

### 1Password

Create these items in vault `k8s-secrets`, one strong random password per
field. Reusing Forge's sops values keeps the cutover to a host change.

| Item | Field | Role | Forge sops key it replaces |
| --- | --- | --- | --- |
| `schoolhouse` | `db_password` | `schoolhouse` | `schoolhouse/db_password` |
| `schoolhouse` | `reader_password` | `schoolhouse_reader` | `schoolhouse/reader_password` |
| `schoolhouse` | `grafana_password` | `schoolhouse_grafana` | `schoolhouse/grafana_password` |
| `lading` | `db_password` | `lading` | `lading/db_password` |
| `lading` | `reader_password` | `lading_reader` | `lading/reader_password` |
| `homelab-finance` | `export_db_password` | `homelab_finance` | `homelab-mcp/export_db_password` |
| `homelab-finance` | `money_password` | `homelab_finance_money` | none (Forge used peer auth) |
| `homelab-finance` | `grafana_db_password` | `homelab_finance_grafana` | `homelab-mcp/grafana_db_password` |
| `finances-context` | `db_password` | `finances_context` | none (new) |

Until an item exists, its ExternalSecret is not ready and CloudNativePG
leaves that role (and the Database it owns) unapplied. Nothing else in
postgres17 is affected.

### TLS from Forge

CloudNativePG serves its own certificate, signed by the CA in Secret
`postgres17-ca`, key `ca.crt`. That is a public certificate, not a secret.
Copy it to Forge and connect with `sslmode=verify-ca`, for example:

```sh
kubectl -n cnpg-system get secret postgres17-ca -o jsonpath='{.data.ca\.crt}' | base64 -d > postgres17-ca.crt
```

`verify-ca` rather than `verify-full`: the server certificate names the
in-cluster Services, not the LoadBalancer address. The CA check still refuses
any server that does not hold CloudNativePG's key.

### Restore from Forge (cutover)

1. Stop every writer on Forge (the nix-config PR's cutover lists the units):
   - schoolhouse and its ingest timer;
   - lading and its sync timers;
   - the finances export timer;
   - the Signal capture and report units;
   - the Forge homelab-mcp.
2. Dump each store on Forge, then restore it as its owner. Restore as the
   owner, not with the dump's owners or ACLs:

   ```sh
   export PGSSLMODE=verify-ca PGSSLROOTCERT=postgres17-ca.crt PGHOST=10.45.10.52
   for db in schoolhouse lading homelab_finance; do
     sudo -u postgres pg_dump -h /run/postgresql -Fc --no-owner --no-acl "$db" > "$db.dump"
   done
   pg_restore --no-owner --no-acl -U schoolhouse -d schoolhouse schoolhouse.dump
   pg_restore --no-owner --no-acl -U lading -d lading lading.dump
   pg_restore --no-owner --no-acl -U homelab_finance -d homelab_finance homelab_finance.dump
   ```

3. Grant the readers, as each owner:

   ```sql
   -- psql -U schoolhouse -d schoolhouse
   GRANT USAGE ON SCHEMA public TO schoolhouse_reader, schoolhouse_grafana;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO schoolhouse_reader, schoolhouse_grafana;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO schoolhouse_reader, schoolhouse_grafana;

   -- psql -U lading -d lading
   GRANT USAGE ON SCHEMA public TO lading_reader;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO lading_reader;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO lading_reader;

   -- psql -U homelab_finance -d homelab_finance
   GRANT USAGE ON SCHEMA household_finance TO homelab_finance_grafana, homelab_finance_money;
   GRANT SELECT ON ALL TABLES IN SCHEMA household_finance TO homelab_finance_grafana;
   ALTER DEFAULT PRIVILEGES IN SCHEMA household_finance GRANT SELECT ON TABLES TO homelab_finance_grafana;
   GRANT SELECT ON household_finance.money_overview TO homelab_finance_money;
   ```

4. Move the transaction context: on Forge, with the Signal worker stopped:

   ```sh
   HOMELAB_MCP_FINANCES_CONTEXT_DSN="postgresql://finances_context:<password>@10.45.10.52/finances_context?sslmode=verify-ca&sslrootcert=postgres17-ca.crt" \
     homelab-finances-context copy --from /var/lib/homelab-mcp/finances-context.db
   ```

   It refuses a target that already has rows, and keeps ids and Signal
   event keys.

5. Repoint Forge (nix-config) and start the writers. Merge the homelab-mcp
   app (k8s-gitops).

The snapshot tables in `homelab_finance` (`reconcile_daily`,
`sync_health_daily`, `hygiene_daily`) are the only record of past bank
balances, so restore them; never let the export job recreate them empty.
Keep Forge's database for a week after the cutover before dropping it.
