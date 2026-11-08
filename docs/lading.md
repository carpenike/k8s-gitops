# lading

Amazon, Costco and Sam's Club order sync (carpenike/lading, a private
repo). It replaces Forge's `hosts/forge/services/lading.nix` in
carpenike/nix-config. The `amazon_*` tools that read the store are in
homelab-mcp, through `lading_reader` ([homelab-mcp.md](homelab-mcp.md)).

Each sync pod holds one Amazon username, password and TOTP seed. That
credential can place orders and change shipping addresses.

## What runs

Namespace `lading`, chart `app-template` 5.3.0, image
`ghcr.io/carpenike/lading`, pinned by tag and digest to lading main
`d73fae0` (#9).

| Controller | Kind | Schedule (`America/New_York`) | Secret | State volume |
| --- | --- | --- | --- | --- |
| `lading` | Deployment, 1 replica | always on, `/healthz` on 9230 | `lading-health`: reader DSN only | none |
| `sync-ryan` | CronJob | `20 4 * * *` (module default 04:20) | `lading-ryan`, seeds `lading-ryan-seeds` | `lading-ryan-state` |
| `sync-steffi` | CronJob | `40 5 * * *` (Forge `05:40`) | `lading-steffi`, seed `lading-steffi-seeds` | `lading-steffi-state` |

- Each CronJob runs `lading-migrate`, then `lading-sync`, with
  `LADING_ACCOUNT` set to its account. Ryan has Costco and Sam's Club on
  (`LADING_COSTCO_ENABLED`, `LADING_SAMSCLUB_ENABLED`). Steffi has Costco
  only. The health server gets what the module derives:
  `LADING_KNOWN_ACCOUNTS=["ryan","steffi"]`,
  `LADING_COSTCO_ACCOUNTS=["ryan","steffi"]`,
  `LADING_SAMSCLUB_ACCOUNTS=["ryan"]`.
- Settings ported from Forge, on every container: `TIMEZONE=America/New_York`,
  `STALE_AFTER_HOURS=36`, `TRANSACTION_WINDOW_DAYS=45`,
  `MAX_DETAIL_FETCHES_PER_RUN=40`, `COSTCO_WINDOW_DAYS=90`.
- Kubernetes has no `RandomizedDelaySec`, so each run sleeps 0 to 3600
  seconds first, the module's hour of jitter. A login at the same minute
  every day is a pattern bot detection scores.
- **No automatic retries.** `backoffLimit: 0`, `restartPolicy: Never`,
  `concurrencyPolicy: Forbid`. lading has no retry loop on purpose: a failed
  login retried is how an Amazon account gets challenge-locked. A failed run
  stays failed until the next day or a person.
- Exit 0 and 1 (partial) are success, as Forge's `SuccessExitStatus=0 1`.
  The run is killed after 45 minutes (Forge's `TimeoutStartSec`).
- One PVC per account (ceph-block, RWO, 1Gi), mounted at `/var/lib/lading`
  with `LADING_STATE_DIR` and `HOME` there. It holds the Amazon cookie jar
  `amazon.cookies.json` (a live session), the rotating
  `costco-tokens.json` and `samsclub-tokens.json` (0600), and the
  amazon-orders config and output dir. Accounts never share a volume. An
  init container sets each volume root to `65532:65532` mode 0700 on every
  run, as Forge's dataset and `StateDirectoryMode`. There is no `fsGroup`,
  so file modes are not widened.
- The CronJobs shipped `suspend: true` and were turned on at the cutover.

### Token seeds

Forge installs `lading/<account>/costco_tokens` and
`lading/ryan/samsclub_tokens` into the state directory only when no live
token file exists (`costcoSeed` and `samsclubSeed` in lading's
`nix/module.nix`). The `seed` init container does the same: for each source
the account has, `[ -e <live file> ]`, and only if absent
`install -m 0600` from the seed Secret, as uid 65532. It never overwrites a
live token. The refresh tokens rotate on every redemption, so restoring a
spent seed over a live token breaks the next refresh with `invalid_grant`.

The seed Secret is mounted in the seed container only, mode 0444 because a
Secret volume is root-owned and there is no `fsGroup`.

Re-seeding: put the new blob in the 1Password field, wait for the
ExternalSecret refresh (or force-sync it,
[external-secrets.md](external-secrets.md)), delete the live file on that
account's volume, then run the job.

## Network

Default deny. The health pod accepts 9230 from Prometheus only and reaches
DNS and `postgres17:5432`. The sync pods accept nothing. They reach DNS,
`postgres17:5432`, and 443 on these names only (no wildcards):

| Host | Why | Accounts |
| --- | --- | --- |
| `www.amazon.com` | amazon-orders 4.9.2: sign-in, MFA, order history, details, transactions | ryan, steffi |
| `signin.costco.com` | Costco Azure B2C token endpoint (`sync/costco.py`) | ryan, steffi |
| `ecom-api.costco.com` | Costco receipts GraphQL | ryan, steffi |
| `titan.samsclub.com` | Sam's Club Azure B2C token endpoint (`sync/samsclub.py`) | ryan |
| `www.samsclub.com` | Sam's Club orchestra GraphQL | ryan |

Captcha image hosts are not allowed. lading never uses a solver, so a
captcha fails the run either way.

## 1Password

Vault `k8s-secrets`:

| Item | Field | Forge sops key |
| --- | --- | --- |
| `lading-ryan` (new) | `amazon_username` | `lading/ryan/amazon_username` |
| `lading-ryan` | `amazon_password` | `lading/ryan/amazon_password` |
| `lading-ryan` | `amazon_otp_secret_key` | `lading/ryan/amazon_otp_secret_key` (base32, spaces fine) |
| `lading-ryan` | `costco_tokens` | `lading/ryan/costco_tokens` (seed JSON) |
| `lading-ryan` | `samsclub_tokens` | `lading/ryan/samsclub_tokens` (seed JSON) |
| `lading-steffi` (new) | `amazon_username` | `lading/steffi/amazon_username` |
| `lading-steffi` | `amazon_password` | `lading/steffi/amazon_password` |
| `lading-steffi` | `amazon_otp_secret_key` | `lading/steffi/amazon_otp_secret_key` |
| `lading-steffi` | `costco_tokens` | `lading/steffi/costco_tokens` (seed JSON) |
| `lading` | `db_password` | `lading/db_password` (role `lading`, [postgres17.md](postgres17.md#1password)) |
| `lading` | `reader_password` | `lading/reader_password` (role `lading_reader`) |

The health server uses `lading_reader`; `/healthz` is SELECTs only. Only
the sync jobs migrate, so on an empty database `/healthz` reads `error`
until the first sync. After the restore the schema is already there.

## Alerts

nix-config has no lading Prometheus rule. Forge alerted through Gatus on
`/healthz` and a systemd service-down rule. lading has no `/metrics`, so the
rules use kube-state-metrics, per CronJob (one per account):

| Alert | Fires when |
| --- | --- |
| `LadingDown` | The health Deployment has no available replica for 10 minutes |
| `LadingSyncFailed` | The newest run of that account's CronJob finished without success |
| `LadingSyncStale` | No successful run for 36h (`stale_after_hours`), or none ever on a CronJob older than that |

These see the Job's exit status only. Per-source freshness within a run
(Amazon, Costco, Sam's Club) is on `/healthz`, which nothing scrapes yet.
Until the cutover the sync CronJobs are suspended, so `LadingSyncStale` fires
36 hours after merge: merge this at the cutover (docs/forge-cutover.md).

### When a sync fails

Read the Job's log first (`kubectl -n lading logs job/<name>`). An
`AmazonOrdersAuthError` or a JavaScript challenge is not fixed by running
again. Forge's recovery was to copy a working `amazon.cookies.json` (0600,
owned by 65532) onto the account's volume. Do not add a captcha solver or a
browser.

## Cutover from Forge

1. Merge carpenike/lading #9. Pin the image here (tag and digest).
2. Create the 1Password items above. postgres17 (#5766) is merged and the
   `lading` database is restored, with reader grants
   ([postgres17.md](postgres17.md#restore-from-forge-cutover)).
3. On Forge, stop the timers and services and keep them stopped:
   `systemctl stop lading-sync-ryan.timer lading-sync-steffi.timer lading-sync-ryan.service lading-sync-steffi.service lading.service`.
   The nix-config change that removes them follows.
4. Before either CronJob runs, copy each Forge account directory onto its
   own volume, as uid 65532 with modes kept (cookie jar and token files stay
   0600):
   - `/var/lib/lading/ryan/.` onto `lading-ryan-state`;
   - `/var/lib/lading/steffi/.` onto `lading-steffi-state`.

   Never put one account's files on the other's volume. The CronJobs are
   suspended, so nothing mounts the volumes. For example, per account, with
   a helper pod that mounts that PVC and runs as 65532:

   ```sh
   # on Forge
   sudo tar -C /var/lib/lading/ryan --numeric-owner --owner=65532 --group=65532 -cpf - . > lading-ryan-state.tar
   # into the helper pod, then inside it:
   tar -C /var/lib/lading -xpf lading-ryan-state.tar
   ```

   Delete the helper pods and tar files. They contain live sessions.
5. With the live token files in place, the seed step does nothing. Set
   `suspend: false` on both CronJobs. Run ryan's once by hand and read the
   log (`kubectl -n lading create job --from=cronjob/lading-sync-ryan first-run`).
   Expect `amazon session authenticated` and Costco and Sam's Club fetches
   that do not report seeding. Then let steffi's run on its schedule.

No offsite backup of the volumes, as on Forge: the seeds in 1Password are
the offsite copy, and a live Amazon session does not go to a third-party
bucket.
