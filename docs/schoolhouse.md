# schoolhouse

The Schoology parent-account ingest
([carpenike/schoolhouse](https://github.com/carpenike/schoolhouse)). It
replaces Forge's `hosts/forge/services/schoolhouse.nix` in
carpenike/nix-config. The data is three minors' education records. The
`school_*` tools that read it are in homelab-mcp, through
`schoolhouse_reader` ([homelab-mcp.md](homelab-mcp.md)).

## What runs

Namespace `schoolhouse`, chart `app-template` 5.3.0, image
`ghcr.io/carpenike/schoolhouse`, pinned by tag and digest to schoolhouse main
`d25df9d` (#24).

| Controller | Kind | What it does | Secret |
| --- | --- | --- | --- |
| `schoolhouse` | Deployment, 1 replica | `/healthz` and `/metrics` on 9220 | `schoolhouse-health`: reader DSN only |
| `ingest` | CronJob | `schoolhouse-migrate`, then `schoolhouse-ingest` | `schoolhouse-ingest`: owner DSN, Schoology login, children, iCal feeds |

- Schedule: `0 7,16,20 * * 1-5` in `America/New_York`, Forge's
  `Mon..Fri 07:00/16:00/20:00`. Kubernetes has no `RandomizedDelaySec`, so
  the job sleeps 0 to 900 seconds first, the module's 15 minutes of jitter.
- `concurrencyPolicy: Forbid`, `backoffLimit: 0`, `restartPolicy: Never`.
  Forge never retried a failed ingest. The next slot is hours away, and an
  immediate retry would spend the district's politeness budget on the same
  failure.
- Exit 0 (clean) and 1 (partial: parsers pending) are success, as Forge's
  `SuccessExitStatus=0 1`. Exit 2 fails the Job. The run is killed after 30
  minutes (Forge's `TimeoutStartSec`).
- State: PVC `schoolhouse-state` (ceph-block, RWO, 1Gi), mounted only by
  the ingest at `/var/lib/schoolhouse`. It holds the Schoology session cookie
  jar `schoology.cookies.json` (0600), a live parent login. An init
  container sets the volume root to `65532:65532` mode 0700 on every run,
  Forge's `StateDirectoryMode`. There is no `fsGroup`, so file modes are not
  widened.
- Settings ported from Forge: `SCHOOLHOUSE_SCHOOLOGY_ORIGIN=https://app.schoology.com`,
  `TIMEZONE=America/New_York`, `STALE_AFTER_HOURS=18`,
  `RAW_RETENTION_DAYS=30`, `FACULTY_REFRESH_DAYS=7`. Forge sets no IMAP
  variables, so the digest source is off.
- Probes are TCP. `/healthz` returns 503 every weekend by design, and a
  restart fixes neither staleness nor a database outage. Readiness is off.
- The CronJob ships `suspend: true`. It is turned on at the cutover.

## Network

Default deny. The health pod accepts 9220 from Prometheus
(`observability`, `app.kubernetes.io/name: prometheus`) and reaches only
DNS and `postgres17` on 5432. The ingest pod accepts nothing and reaches
DNS, `postgres17`, and `app.schoology.com:443`.

`app.schoology.com` is the parent origin: login and every scraped page, no
SSO hop (schoolhouse `docs/RECON.md` section 1). It is also assumed to be the
iCal feed host, since Schoology issues calendar share links on the instance
the account uses. The feed URLs are secret, so that is unchecked. To check
it without printing a URL, on Forge:

```sh
sudo jq -r '.[]' /run/secrets/schoolhouse/ical_feeds | sed -E 's|^https?://([^/]+)/.*|\1|' | sort -u
```

If a feed is on another host, the ingest logs
`iCal fetch failed for child <id> (ConnectTimeout)` and continues. Add that
exact host to `schoolhouse-ingest` in `ciliumnetworkpolicy.yaml`.

## 1Password

Vault `k8s-secrets`:

| Item | Field | Value | Forge sops key |
| --- | --- | --- | --- |
| `schoolhouse-ingest` (new) | `schoology_username` | Parent Schoology login (native app.schoology.com account) | `schoolhouse/schoology_username` |
| `schoolhouse-ingest` | `schoology_password` | Its password | `schoolhouse/schoology_password` |
| `schoolhouse-ingest` | `children` | JSON `{"<schoology uid>": "<name>"}` | `schoolhouse/children` |
| `schoolhouse-ingest` | `ical_feeds` | JSON `{"<schoology uid>": "<feed URL>"}` or `{}`. Capability URLs | `schoolhouse/ical_feeds` |
| `schoolhouse` | `db_password` | Role `schoolhouse` ([postgres17.md](postgres17.md#1password)) | `schoolhouse/db_password` |
| `schoolhouse` | `reader_password` | Role `schoolhouse_reader` | `schoolhouse/reader_password` |

The health server uses `schoolhouse_reader`. Its queries are SELECTs only.
The reader needs the grants from the postgres17 restore step, or `/metrics`
reports `schoolhouse_database_up 0`.

## Alerts

Ported from `schoolhouse.nix`, same expressions and severities:

| Alert | Fires when |
| --- | --- |
| `SchoolhouseDown` | No `/metrics` scrape for 10 minutes |
| `SchoolhouseIngestStale` | Last good ingest older than 12h, on a weekday after 14:00 UTC |
| `SchoolhouseDatabaseUnreachable` | `schoolhouse_database_up == 0` for 10 minutes |
| `SchoolhouseRecordsCollapsed` | Last run saw under half the 14-day average of records |

Prometheus here keeps 7 days, so the 14-day average covers 7. Until the
restore at the cutover, the health server's database has no schema, so its
`/healthz` and freshness metrics report errors; the ingest CronJob stays
suspended.

## Cutover from Forge

1. Merge carpenike/schoolhouse #24. Pin the image here (tag and digest).
2. Create the 1Password items above. postgres17 (#5766) is merged and the
   `schoolhouse` database is restored, with reader grants
   ([postgres17.md](postgres17.md#restore-from-forge-cutover)).
3. On Forge, stop the timer and service and keep them stopped:
   `systemctl stop schoolhouse-ingest.timer schoolhouse-ingest.service schoolhouse.service`.
   The nix-config change that removes them follows.
4. Copy Forge's `/var/lib/schoolhouse` onto `schoolhouse-state`, as uid
   65532 with modes kept (`schoology.cookies.json` stays 0600), before the
   first CronJob run. The CronJob is suspended, so nothing mounts the
   volume. For example, with a helper pod that mounts the PVC and runs as
   65532:

   ```sh
   # on Forge
   sudo tar -C /var/lib/schoolhouse --numeric-owner --owner=65532 --group=65532 -cpf - . > schoolhouse-state.tar
   # into the helper pod, then inside it:
   tar -C /var/lib/schoolhouse -xpf schoolhouse-state.tar
   ```

   Delete the helper pod and the tar file.
5. Set `suspend: false` on the `ingest` CronJob. Start one run by hand and
   read the log (`kubectl -n schoolhouse create job --from=cronjob/schoolhouse-ingest first-run`).
   It sleeps up to 15 minutes first. A `logged in to https://app.schoology.com`
   line, or a reused session, means it works.
