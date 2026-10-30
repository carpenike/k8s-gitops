# LiteLLM

The proxy that fronts cloud models. ADR 0006. Forge still serves
`https://llm.holthome.net` until the cutover below. This cluster serves
`https://litellm.holthome.net` on `envoy-internal` (`10.45.10.50`).
`mikrotik-dns` publishes that name. The route has no parent on
`envoy-external`, so Cloudflare does not publish it.

## What Forge runs today

Read from `carpenike/nix-config` `main`. `services.atriumForge.adoption.models`
is true (`hosts/forge/atrium/adoption.nix`), so the adopted block in
`hosts/forge/services/atrium-models.nix` is the live process.

- Unit `podman-litellm.service`, host network, `127.0.0.1:4100`.
  The unadopted module would publish `127.0.0.1:4100` to container port
  `4000` (`hosts/forge/services/litellm.nix`, because `4000` is TeslaMate).
  Adoption sets `internalPort = 4100`, `listenAddress = 127.0.0.1`, and
  `publishPort = false`. Caddy's `llm.holthome.net` vhost is LAN-only.
- Image `ghcr.io/berriai/litellm:v1.100.1` at digest
  `sha256:a3715fa7ad8387941ab697259bd2881d68931657247a41984f90fae6d11c62bf`.
  Atrium refuses any other image.
- Database `litellm` on Forge's local PostgreSQL 17, role `litellm`.
- Dataset `tank/services/litellm` at `/var/lib/litellm`. Snapshots and
  restic cover that dataset. The rows that matter are in PostgreSQL
  (pgBackRest), not in the dataset. The dataset holds the generated salt
  key.
- In-process callback `atrium_admission.hook.admission`, fed by files from
  `atrium-resolver`, `atrium-reconciler`, `atrium-model-policy.service`,
  and `atrium-admission-settings.service`. The container requires those
  units. `atrium-reconciler` requires `podman-litellm.service`.
- Router settings forced by adoption: `num_retries = 0`, `max_fallbacks = 0`,
  empty fallback lists. Host settings that remain: `simple-shuffle`,
  `timeout = 600`. `turn_off_message_logging` is on.
- Admin UI SSO is Pocket ID client `litellm`, callback
  `https://llm.holthome.net/sso/callback`, `PROXY_ADMIN_ID=ryan`.
  API calls use virtual keys. Caddy does not add a second login.
- `copilot/*` and `copilot-oai/*` use `http://127.0.0.1:4141` (adoption
  maps `host.containers.internal` to loopback). copilot-api stays on Forge
  at `https://copilot.holthome.net`.

Open WebUI on Forge is disabled and talks to Azure directly. paperless-ai
talks to Anthropic directly. Neither is a LiteLLM client.

## What this cluster runs

Namespace `litellm`, chart `app-template` 5.3.0, the same image digest.

The model list matches Forge, with one address change: `copilot/*` and
`copilot-oai/*` use `https://copilot.holthome.net` and
`https://copilot.holthome.net/v1`. `host.containers.internal` does not
exist here. copilot-api's Caddy vhost is the LAN path, and it already
requires the bearer key.

The Atrium callback is absent. Importing it without the Nix-built package
and the live publication files would crash the process. Atrium and Whiskey
keep using Forge until that hook has a home.

The route label is `gateway.holthome.net/auth: native`. A gateway Pocket ID
redirect would reject bearer keys. The label covers the whole host,
including `/sso/callback`, because the UI has its own Pocket ID client.
`ReferenceGrant` `litellm-gateway-auth` lets `pocket-id-exempt` select the
route.

Probes:

| Probe | Path | Auth |
| --- | --- | --- |
| startup, liveness | `GET /health/liveliness` | none |
| readiness | `GET /health/readiness` | none; 503 when the database is down |

`GET /health/liveness` is an alias of `liveliness`. `GET /health` is the
model check. It needs a key and spends tokens. It is not a probe.

`/metrics` needs the master key. The ServiceMonitor is labeled
`release: kube-prometheus-stack` and sends `LITELLM_MASTER_KEY`.

Resources match the cap Forge raised after Prisma OOM under 1G: request
1Gi, limit 2Gi and 1 CPU. Startup is allowed 300 seconds.

One replica. A second replica races Prisma migrations.

The process runs as root with every capability dropped. Forge's module
sets `runAsRoot` because Prisma writes into the image tree at startup.
The namespace stays on the cluster baseline policy.

## Database

Cluster `postgres17` in `cnpg-system`, image
`ghcr.io/cloudnative-pg/postgresql:17.9`, two instances, 20Gi on
`ceph-block`. Bootstrap database `app` is unused by LiteLLM. Database
`litellm` is owned by role `litellm`. The role password is ExternalSecret
`litellm-db`.

`ScheduledBackup` `postgres17-daily` takes an online volume snapshot at
03:00 UTC through `csi-ceph-block`. `waitForArchive` is false because WAL
is not shipped off the chassis. Snapshots accumulate on Ceph. Barman Cloud
is the off-chassis copy and stays unattached while its endpoint is
`s3.example.invalid`.

## 1Password

Vault `k8s-secrets`, item `litellm`. The cluster token is read-only, so
create the item before expecting the ExternalSecrets to become Ready.
One line per field, no surrounding quotes.

| Field | Source on Forge | Kubernetes use |
| --- | --- | --- |
| `master_key` | sops `litellm/master_key` | `LITELLM_MASTER_KEY` |
| `salt_key` | file below | `LITELLM_SALT_KEY` |
| `database_password` | sops `litellm/database_password` | CNPG role and `DATABASE_URL` |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` in sops `litellm/provider-keys` | same env name |
| `openai_api_key` | `OPENAI_API_KEY` in that file | same env name |
| `google_api_key` | `GOOGLE_API_KEY` in that file | same env name |
| `azure_api_key` | `AZURE_API_KEY` in that file | same env name |
| `copilot_api_key` | first line of `/var/lib/copilot-api/api-key` | `COPILOT_API_KEY` |
| `oidc_client_secret` | sops `litellm/oidc-client-secret` | `GENERIC_CLIENT_SECRET` |

`GENERIC_CLIENT_ID` is the literal `litellm` and is not a field.

The salt key is not in sops. The module generates it once when
`saltKeyFile` is unset, which it is. The file is
`/var/lib/litellm/secrets/salt-key` (the oneshot writes
`<dataDir>/secrets/salt-key`, and the dataset is `/var/lib/litellm`).
Read it on Forge. If `systemctl cat litellm-env` shows another path, use
that file. Copy the existing value. LiteLLM cannot rotate a salt key after
credentials are stored. A new salt makes the restored rows unreadable.

On the Pocket ID client `litellm`, add callback
`https://litellm.holthome.net/sso/callback`. Leave the existing
`https://llm.holthome.net/sso/callback` in place while Forge still serves
that name.

## Cutover

Do the dump and the secret reads on Forge. Do not change Forge's Nix or
stop its container in this phase. The cluster copy is independent. Forge's
database and dataset stay as the rollback.

### 1. Secrets

Create the 1Password item from the table above. Decrypt the sops values on
a workstation that has the YubiKey. Read the salt file and the copilot-api
key on Forge.

### 2. Wait until the new database exists

After this branch is synced:

```sh
flux reconcile kustomization postgres17 -n cnpg-system --with-source
flux reconcile kustomization litellm -n litellm --with-source
```

`litellm` stays pending until `postgres17` is Ready, which stays pending
until item `litellm` exists.

### 3. Stop the new proxy before it migrates an empty database

The HelmRelease starts Prisma against whatever is in `litellm`. Suspend it
before restoring:

```sh
flux suspend helmrelease litellm -n litellm
kubectl -n litellm scale deploy/litellm --replicas=0
```

If the pod already became Ready, it has migrated an empty database. The
restore step drops that schema first.

### 4. Copy the Forge database

On Forge, as a read-only dump. PostgreSQL 17 is the server there. This
does not stop `postgresql.service`.

```sh
ssh forge 'sudo -u postgres pg_dump -Fc --no-owner --no-privileges -d litellm' \
  > litellm.dump
```

Copy it to the primary and restore. The primary pod is `postgres17-1`
unless a failover renamed it (`kubectl -n cnpg-system get pods -l cnpg.io/instanceRole=primary`).
Local peer auth inside the pod is user `postgres`.

```sh
primary=$(kubectl -n cnpg-system get pods -l cnpg.io/cluster=postgres17,cnpg.io/instanceRole=primary -o jsonpath='{.items[0].metadata.name}')
kubectl -n cnpg-system cp litellm.dump "$primary":/tmp/litellm.dump
kubectl -n cnpg-system exec "$primary" -- psql -U postgres -d litellm -v ON_ERROR_STOP=1 -c \
  'DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION litellm;'
kubectl -n cnpg-system exec "$primary" -- pg_restore --no-owner --no-privileges --role=litellm --exit-on-error -d litellm /tmp/litellm.dump
kubectl -n cnpg-system exec "$primary" -- rm -f /tmp/litellm.dump
rm -f litellm.dump
```

`pg_restore` may warn about `transaction_timeout` or a comment on the
`postgres` role. A warning that does not abort is noise from the version
gap between Forge's 17 package and image 17.9. `--exit-on-error` still
fails the command on a real error. The salt key in 1Password must already
be the Forge file before the next step.

### 5. Start and check

```sh
flux resume helmrelease litellm -n litellm
kubectl -n litellm rollout status deploy/litellm
curl -fsS https://litellm.holthome.net/health/liveliness
curl -fsS https://litellm.holthome.net/health/readiness
```

Readiness JSON has `"db": "connected"`.

Create a throwaway key with the master key, then call the info route
Atrium's resolver uses. Delete the throwaway key afterward.

```sh
# MASTER is the 1Password master_key value, in the shell only.
curl -fsS https://litellm.holthome.net/key/generate \
  -H "Authorization: Bearer $MASTER" \
  -H 'Content-Type: application/json' \
  -d '{"key_alias":"cluster-cutover-test","duration":"1h","models":["openai/gpt-4o"]}'
# TEST is the key field from that response.
curl -fsS https://litellm.holthome.net/key/info \
  -H "Authorization: Bearer $TEST"
```

Then one completion with `$TEST` against a cheap model the key is allowed
to call. A 200 from `/key/info` proves the restored virtual-key table.
A completion proves provider env vars. copilot routes additionally need
`https://copilot.holthome.net` to resolve from a pod. CoreDNS forwards to
the node resolver. If that name fails, fix DNS before sending copilot
traffic. Direct `anthropic/*`, `openai/*`, `gemini/*`, and the Azure names
do not need it.

Existing virtual keys from Forge work on this URL when the salt matches.
Try one key that already exists, with `GET /key/info`, before telling
anyone to switch.

### 6. Move clients that are not Atrium

Point Claude Code and other SDK users at `https://litellm.holthome.net`
(`ANTHROPIC_BASE_URL`, or `base_url` `https://litellm.holthome.net/v1`).
Leave `https://llm.holthome.net` on Forge. Atrium, the reconciler, and
Whiskey still require that process and its admission hook. Whiskey's
egress allowlist is `llm.holthome.net` (`fixedWhiskeyHosts` in
`hosts/forge/services/atrium-adapters.nix`).

### 7. Stop Forge only after the hook has a home

This is a nix-config change. It is not in this repository, and it is not
safe while `callbacks` includes `atrium_admission.hook.admission`.

When the hook runs in the cluster pod, or when Ryan accepts a proxy
without that hook:

1. `hosts/forge/atrium/runtime.nix`: set `endpoints.models` to
   `https://litellm.holthome.net`.
2. `hosts/forge/atrium/registry.nix`: set `deployments.litellm.endpoint`
   to the same URL.
3. `hosts/forge/services/atrium-adapters.nix`: add `litellm.holthome.net`
   to `fixedWhiskeyHosts`.
4. `hosts/forge/services/atrium-models.nix`: point the hosts entry and the
   health URL at the new name, and drop `requires` / `after` on
   `podman-litellm.service` from `atrium-reconciler` only once the
   reconciler is talking to the cluster. Until then those edges keep the
   Forge container up.
5. `hosts/forge/services/litellm.nix`: set
   `modules.services.litellm.enable = false`. Leave
   `modules.storage.datasets.services.litellm` and the sanoid dataset
   `tank/services/litellm` in place. Disabling the service removes the
   container and the Caddy vhost. It does not destroy the ZFS dataset
   unless that dataset block is also removed.
6. Keep `/var/lib/litellm/secrets/salt-key` until a restore has been
   proven and the 1Password field is known good. Then the container can
   stay stopped.

No draft pull request was opened on `carpenike/nix-config`. Applying that
diff now stops the admission hook. The pull request tool for this
repository cannot open it there.

### Rollback

Phase 6 is a client URL. Point those clients back at
`https://llm.holthome.net`. Forge was never stopped.

To drop the cluster copy:

```sh
flux suspend helmrelease litellm -n litellm
```

Reverting this branch removes the proxy and, if `postgres17` is reverted
with it, the cluster. `databaseReclaimPolicy: retain` keeps the database
if only the `Database` object is deleted. The Forge database is untouched
either way.

Phase 7 rollback is the inverse Nix change: enable the module again, point
the endpoints back at `https://llm.holthome.net`, and leave the dataset
where it is. The salt file on the dataset is what a restored Forge
container needs.
