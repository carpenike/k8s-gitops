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

The Atrium callback is not mounted yet. Atrium, including Whiskey, is the
only LiteLLM client and still uses Forge. The cutover plan is below.

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

`/metrics` is a 404 on the running proxy. Forge's gateway doc says the
route exists only after `litellm_settings.callbacks` includes `prometheus`
(`docs/services/ai-gateway.md`). This chart's ServiceMonitor already sends
the master key and is labeled `release: kube-prometheus-stack`, and the
config does not set that callback. Adding `prometheus` is a one-line config
change. When the admission hook is added, `callbacks` is one list and must
name both `atrium_admission.hook.admission` and `prometheus`. Naming only
the admission hook, which is what Forge does today, leaves `/metrics` as
404.

Resources match the cap Forge raised after Prisma OOM under 1G: request
1Gi, limit 2Gi and 1 CPU. Startup is allowed 300 seconds.

One replica. A second replica races Prisma migrations.

This pod runs as root with every capability dropped. The adopted Forge
container runs as `atrium-model-gateway` (uid 1064) with group 1065, and
Prisma uses `/var/lib/atrium-model-gateway/native-data`. The cutover below
switches this pod to that uid before the hook is loaded.

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

The CloudNativePG operator process had to be restarted once because it
came up before the VolumeSnapshot CRDs and did not watch them until the
restart. `snapshot-controller` is already a dependency of
`rook-ceph-cluster`, and `cloudnative-pg` depends on that cluster, but
the operator pod itself does not wait on `snapshot-controller`. The fix
is a direct `dependsOn` of `snapshot-controller` in namespace `kube-system`
on Kustomization `cloudnative-pg`. That orders a future install. It does
not restart the pod that already missed the CRDs.

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

## Atrium is the client

The first database copy is already on the cluster (44 keys and 2 teams
matched). Forge has kept taking writes since that copy. The cutover is a
write freeze, a final dump, and pointing Atrium at
`https://litellm.holthome.net`.

Atrium is the only caller. Whiskey is the Atrium text service: it calls
the gateway itself, and `fixedWhiskeyHosts` in
`hosts/forge/services/atrium-adapters.nix` allows `llm.holthome.net`.
Open WebUI is disabled. paperless-ai calls Anthropic directly. Neither
uses this proxy.

`hosts/forge/atrium/adoption.nix` sets models, native, whiskey, and
whiskeyText. The Python packages come from the private flake input
`github:carpenike/atrium/0da7baa39fafa7cc1601bfc27a3b64b13d0c72bc`
(`flake.nix`). That repository was not readable from this checkout. The
contract below is what nix-config wires. Do not reimplement the hook from
memory, and do not paste its source into this public repo.

## Admission hook

The adopted container loads two entry points from package
`atrium-litellm-admission`:

- `LITELLM_WORKER_STARTUP_HOOKS=atrium_admission.bootstrap:install`
- `litellm_settings.callbacks = [ "atrium_admission.hook.admission" ]`

`ATRIUM_ADMISSION_SETTINGS` points at
`/var/lib/atrium-model-gateway/config/admission.json`. That file is a
byte copy of `/etc/atrium/runtime/model-admission.json`, installed mode
`0600` by `atrium-admission-settings.service` as user
`atrium-model-gateway`. The JSON is the hook's file list. From
`hosts/forge/atrium/models.nix` it names:

| Settings field | Path | Owner the hook is told to expect |
| --- | --- | --- |
| `policy_path` | `/var/lib/atrium-policy/model-policy.json` | uid 0 (`policy_publisher_uid`) |
| producers `resolver` | `/run/atrium-publications/resolver/admission-associations.json` | uid 1060 |
| producers `controller-services` | `/run/atrium-publications/controller/service-associations.json` | uid 1063 |
| `runtime_directory` | `/var/lib/atrium-model-gateway/admission` | the gateway user, uid 1064 |
| `deny_url` | `https://atrium.holthome.net/v1/deny-feed` | fetched, not a file |
| `jwks_url` | `https://atrium.holthome.net/.well-known/jwks.json` | fetched, not a file |

`issuer` in that JSON is `endpoints.models`, today
`https://llm.holthome.net`. `poll_seconds` is 20. `fetch_timeout_seconds`
is 5.

Who writes the files:

- `atrium-model-policy.service` is a root oneshot. It copies
  `config.services.atrium.generated.resolver` onto `model-policy.json`
  mode `0640`, group `atrium-model-metadata` (gid 1065), by `install` and
  `mv -T`. The doc in `docs/services/atrium-forge-cloud.md` calls this an
  atomic root-provenance copy of the generated policy for the admission
  loader's protected-file contract. It changes when the Nix policy
  changes, not on a timer.
- `atrium-resolver.service` publishes into
  `/run/atrium-publications/resolver` (directory `2750`, owner 1060, group
  1065). The admission producer file is `admission-associations.json`.
  The resolver's private copies live under
  `/var/lib/atrium-resolver/models/` and are not mounted into the
  container.
- `atrium-reconciler.service` publishes into
  `/run/atrium-publications/controller` (directory `2750`, owner 1063,
  group 1065). The admission producer file is `service-associations.json`.
  The timer is `OnUnitInactiveSec=20s`. `atrium-model-health` requires
  `associations.json`, `native-bindings.json`, `service-associations.json`,
  and `reconciliation.json` to be regular files younger than 80 seconds.
- `atrium-model-admission-initialize` ran once:
  `atrium-litellm-admission --settings <path> initialize`. The durable
  result is `/var/lib/atrium-model-gateway/admission/initialized` and
  `admission-state.json`. The container user is the only writer after
  that. The private ownership ledger
  `/var/lib/atrium-reconciler/ownership.json` is a host startup assert. It
  is not one of the container's mounts. The gateway uid's description is
  "admission history, without producer-private custody."

The container also bind-mounts, read-only, the site-packages of
`atrium-litellm-admission`, `resolver`, and `credential-profiles`, plus
`python312Packages.certifi`, on `PYTHONPATH`:

```text
/opt/atrium-admission:/opt/atrium-resolver:/opt/atrium-profiles:/opt/atrium-certifi
```

nix-config's admission doc says live publications must not be replaced
with an environment snapshot or a systemd credential copy. A ConfigMap
fails that contract twice: the files are owned by root, so the producer
uid check (1060 and 1063) fails, and a ConfigMap does not refresh every
20 seconds inside an 80 second budget. The deny feed and JWKS are already
HTTPS on `atrium.holthome.net`. The association files and the policy file
are not. Do not add a new public HTTP API for them.

### How the pod runs the hook

Build one OCI image from the pinned Atrium packages
(`atrium-litellm-admission`, `resolver`, `credential-profiles`) plus
certifi, in nix-config, where the private input can be fetched. This
public repo only stores the image reference. An init container copies
those trees onto an emptyDir mounted at the `/opt/...` paths above.

A second sidecar, root, rsyncs the live files from Forge at least every
15 seconds and then sets the owners the settings JSON names:

- `model-policy.json` as root:1065, mode `0640`
- the resolver publication directory as 1060:1065, mode `2750`
- the controller publication directory as 1063:1065, mode `2750`
- `admission.json` as 1064:1064, mode `0600`, rewritten when
  `endpoints.models` changes

The same absolute paths are mounted into the proxy container. The proxy
runs as uid 1064, gid 1064, supplemental group 1065, which is the Forge
container's identity and the group that can read the `2750` directories.
`HOME` and `TMPDIR` stay `/var/lib/atrium-model-gateway` and
`.../scratch`. Admission history is a ceph-block PVC mounted at
`/var/lib/atrium-model-gateway`, seeded once from Forge's
`admission/` directory at the freeze. After the seed, only this pod
writes `admission-state.json`.

`litellm_settings.callbacks` becomes:

```yaml
callbacks:
  - atrium_admission.hook.admission
  - prometheus
```

The package has to be on `PYTHONPATH` before that list is installed.
Until the image exists, leave the admission name off or the process
crashes on import.

The pod must reach `https://atrium.holthome.net` for the deny feed and
JWKS. Atrium itself stays on Forge. The resolver and the reconciler stay
on Forge. They hold the signing keys, the sqlite history, and the SOPS
management keys. Moving those units is a different project.

## What each Forge unit does

| Unit | Talks to LiteLLM? | Cutover change |
| --- | --- | --- |
| `podman-litellm.service` | is the proxy | Stop after the final dump. `enable = false` only in the same Nix change as the assertion edit below. |
| `litellm-env.service` | builds the container env, `After=copilot-api-keys.service` | Goes away with the container. The cluster already has those values in item `litellm`. |
| `preseed-litellm.service` | no; restores `tank/services/litellm` if the dataset is empty | Keep it while the dataset is declared, so a rollback can refill an empty dataset. It does not start the proxy. |
| `postgresql-provision-databases.service` | creates Forge's `litellm` database | Leave the Forge database. It is the rollback copy. |
| `copilot-api-keys.service` | writes `/var/lib/copilot-api/api-key`; Forge's `litellm-env` reads it | Stays with copilot-api. If that file is regenerated, copy the new first line into 1Password field `copilot_api_key`. |
| `atrium-model-policy.service` | no; publishes `model-policy.json` | Stays. The rsync sidecar is how the pod sees the file. |
| `atrium-admission-settings.service` | no; publishes `admission.json` | Stays. Its JSON `issuer` follows `endpoints.models`, so the next activation rewrites the URL. The sidecar must pick that rewrite up before the pod is restarted. |
| `atrium-resolver.service` | yes: `GET /key/generate`, `/key/info`, `/team/info`, `/key/delete` with the management key in `/run/secrets/atrium-litellm-resolver-management` | Stays on Forge. `hosts/forge/atrium/runtime.nix` `endpoints.models` is the base URL (`models.nix` resolver `endpoint`). Change that one string to `https://litellm.holthome.net`. Do not add a hosts-file pin for the new name. The existing pin maps `llm.holthome.net` to `10.20.0.30` so Forge skips public DNS. The new name must resolve to `10.45.10.50`. |
| `atrium-reconciler.service` | yes: management routes plus `/credentials` and `/router/settings`, key `/run/secrets/atrium-litellm-controller-management` | Stays on Forge. Same base URL, via `models.controller` `endpoint` and `issuer`. Delete `podman-litellm.service` from `requires` and `after`. Until that edge is gone, a stopped local container holds the reconciler down. |
| `atrium-reconciler.timer` | starts the reconciler every 20s | Stop the timer for the freeze. Start it again after the Nix activation. |
| `atrium-model-health.service` | no HTTP of its own; runs `atrium-litellm-admission --settings ... status` and checks publication age | Stays. It is the check that publications are fresh. Run it after the URL flip. |
| `atrium-model-*-initialize` | already ran | Do not run them again. |
| gatus and homepage `litellm` | probe `endpoints.models` `/health/liveliness` | Follow the runtime URL. No separate edit if they stay `mkForce` on that URL. |
| Whiskey | calls `endpoints.models` for `cc.personal.ryan.sonnet` | Add `litellm.holthome.net` to `fixedWhiskeyHosts` in the same activation as the URL change. The old name can stay until the local vhost is gone. |
| `hosts/forge/atrium/registry.nix` | `deployments.litellm.endpoint` is the literal `https://llm.holthome.net` | Change it in the same activation. The registry also reads `config.modules.services.litellm.models` as the cloud inventory. Keep that model list when the container is disabled. |
| Caddy `llm.holthome.net` | fronts `127.0.0.1:4100` | Removed when the service is disabled. Remove the `networking.hosts` line for `llm.holthome.net` in the same change so Forge does not keep pinning the dead name to itself. |
| OUTPUT firewall rule in `atrium-models.nix` | rejects non-Caddy clients of `127.0.0.1:4100` | Remove it with the local listener. It does not affect the cluster. |

`modules.services.litellm.enable = false` while `adoption.models` is true
fails the assertion in `atrium-models.nix`. That assertion requires the
local service to be enabled, the image to match
`runtime.adoption.models.image`, `podmanNetwork == null`, and the router
settings to match. The Nix change has to drop the local-container
conjuncts and keep the image pin as a statement about the cluster image.

The dataset block and the sanoid entry for `tank/services/litellm` sit
inside `mkIf serviceEnabled` in `hosts/forge/services/litellm.nix`. Move
those declarations out of that guard before setting `enable = false`, so
the dataset stays under Nix. Keep `/var/lib/litellm/secrets/salt-key` on
it.

## Copilot

Forge's adopted proxy calls `http://127.0.0.1:4141` because
`extraHosts.host.containers.internal` is `127.0.0.1` and the port is also
published on the Podman bridge `10.88.0.1`. Neither address is reachable
from a pod. The container port is not on `10.20.0.30`.

The LAN path is `https://copilot.holthome.net`. Caddy's vhost proxies to
`127.0.0.1:4141` and answers `/usage-viewer*` and `/admin*` with 404.
Forge binds Caddy to `127.0.0.1`, `10.20.0.30`, and `10.89.0.1`, and opens
TCP 80 and 443. The generated DNS A record for that vhost is
`10.20.0.30`. From this environment, TCP `10.20.0.30:443` connected, and
the name `copilot.holthome.net` had no public address. The cluster's
CoreDNS forwards to the node resolver, so a pod sees the name only if
that resolver serves the LAN zone.

The cluster config already uses `https://copilot.holthome.net` and
`https://copilot.holthome.net/v1` with `COPILOT_API_KEY`. Before the
freeze, from a `litellm` pod:

```sh
kubectl -n litellm exec deploy/litellm -- python3 -c \
  'import urllib.request; print(urllib.request.urlopen("https://copilot.holthome.net/", timeout=5).read())'
```

The body is `Server running` when Caddy reaches copilot-api. A failure
here is DNS or the path, and copilot model routes stay broken until it
succeeds. Direct Anthropic, OpenAI, Gemini, and Azure routes do not use
this name. copilot-api itself stays on Forge: the GitHub device login is
interactive and the token lives on `tank/services/copilot-api`.

## Cutover

Prepare the cluster hook and the Nix diff before the freeze. Do not apply
the Nix URL change while Forge is still the proxy the resolver calls, and
do not run both proxies against one database.

### 1. Cluster, before the freeze

Land the admission image, the rsync sidecar, uid 1064, the PVC, and the
`callbacks` list. Scale the deployment to 0 until the final restore, so
the pod does not write the stale copy. Confirm the sidecar can see a
fresh `service-associations.json` and `admission-associations.json` once
scaled, then scale to 0 again for the dump.

From a pod, run the copilot check above while the deployment is up for
that test.

### 2. Write freeze

On Forge:

```sh
sudo systemctl stop atrium-reconciler.timer atrium-reconciler.service
sudo systemctl stop atrium-resolver.service
sudo systemctl stop podman-litellm.service
```

Stopping the resolver stops `/key/generate` and `/key/info`. Stopping the
proxy stops spend writes. Leave `postgresql.service`,
`copilot-api-keys.service`, and `preseed-litellm.service` running.

### 3. Final copy

Same salt as the running cluster. Same commands as the first restore.
Drop `public` on the cluster database first so Prisma's schema from the
stale copy does not collide with the dump.

```sh
ssh forge 'sudo -u postgres pg_dump -Fc --no-owner --no-privileges -d litellm' \
  > litellm.dump
primary=$(kubectl -n cnpg-system get pods \
  -l cnpg.io/cluster=postgres17,cnpg.io/instanceRole=primary \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n cnpg-system cp litellm.dump "$primary":/tmp/litellm.dump
kubectl -n cnpg-system exec "$primary" -- \
  psql -U postgres -d litellm -v ON_ERROR_STOP=1 -c \
  'DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION litellm;'
kubectl -n cnpg-system exec "$primary" -- \
  pg_restore --no-owner --no-privileges --role=litellm --exit-on-error \
  -d litellm /tmp/litellm.dump
kubectl -n cnpg-system exec "$primary" -- rm -f /tmp/litellm.dump
rm -f litellm.dump
```

Seed the admission PVC from
`/var/lib/atrium-model-gateway/admission` in this same window, while the
Forge container is stopped and is no longer writing `admission-state.json`.

### 4. Start the cluster proxy

Scale back to 1. Readiness must report `"db": "connected"`. The startup
hook must log `atrium_admission.bootstrap:install` without an import
error. `GET /health/liveliness` and `GET /health/readiness` on
`https://litellm.holthome.net`. Then `GET /key/info` with an existing
virtual key from the dump, not a newly generated one.

### 5. Point Atrium

Apply the Nix change in the checklist. It switches `endpoints.models` and
`deployments.litellm.endpoint`, adds the Whiskey allowlist name, drops the
local container requirement, and disables `podman-litellm`.

```sh
sudo systemctl start atrium-resolver.service
sudo systemctl start atrium-reconciler.timer
sudo systemctl start atrium-model-health.service
systemctl is-failed atrium-model-health.service
```

`atrium-model-health` is the publication-age check. The real request is
one completion through an existing Atrium key, Whiskey's
`cc.personal.ryan.sonnet` or a resolver-issued `cc.*` key, against
`https://litellm.holthome.net`. A 200 that the hook did not deny is the
cut. The resolver journal should show `/key/info` against the new host
on its next maintenance pass (20 seconds).

### 6. Leave Forge stopped

`systemctl is-active podman-litellm` stays `inactive`. Do not start it.
The dataset and the Forge database remain.

## Rollback

If step 4 or 5 fails before Atrium has written anything new:

```sh
sudo systemctl start podman-litellm.service
sudo systemctl start atrium-resolver.service
sudo systemctl start atrium-reconciler.timer
```

Revert the Nix activation if it was applied. Scale the cluster deployment
to 0 so it cannot write the copy. Forge's database was not dropped.

If Atrium has already written to the cluster database, dump that database
back into Forge's `litellm` database before starting `podman-litellm`,
with the same `DROP SCHEMA` / `pg_restore` shape, and keep the cluster
deployment at 0. The salt file on the Forge dataset is the one the Forge
container reads.

## Checklist

### k8s-gitops

- [ ] On Kustomization `cloudnative-pg`, `dependsOn` `snapshot-controller`
      in `kube-system`. Do not expect that to restart the current operator
      pod.
- [ ] `litellm_settings.callbacks` includes `prometheus` so `/metrics` is
      not 404. Include `atrium_admission.hook.admission` only in the same
      change as the package mount.
- [ ] Init container from the nix-built admission image, `PYTHONPATH` and
      `ATRIUM_ADMISSION_SETTINGS` matching Forge.
- [ ] Rsync sidecar, 15 second loop, owners 0, 1060, 1063, and 1064 on the
      paths in the table above.
- [ ] Pod uid 1064, gid 1064, supplemental group 1065. PVC for
      `/var/lib/atrium-model-gateway`. EmptyDir for scratch and for the
      read-only publication mounts' writable sync target.
- [ ] One replica remains.
- [ ] Document the image digest next to Forge's pin. Do not move either
      without the other.

### nix-config

- [ ] Build and push the admission site-packages image from pin
      `0da7baa39fafa7cc1601bfc27a3b64b13d0c72bc`.
- [ ] A read-only sync account on Forge for the publication directories
      and the policy file. Group 1065 can read the `2750` directories and
      the `0640` policy file. The destination chown still has to be root.
- [ ] `hosts/forge/atrium/runtime.nix`: `endpoints.models` =
      `https://litellm.holthome.net`.
- [ ] `hosts/forge/atrium/registry.nix`: `deployments.litellm.endpoint` =
      the same URL. Keep `config.modules.services.litellm.models` populated.
- [ ] `hosts/forge/services/atrium-adapters.nix`: add
      `litellm.holthome.net` to `fixedWhiskeyHosts`.
- [ ] `hosts/forge/services/atrium-models.nix`: delete the
      `podman-litellm.service` `requires` and `after` on the reconciler;
      delete the `networking.hosts` pin of `llm.holthome.net`; delete the
      OUTPUT reject rule for port 4100; replace the adoption assertion so
      `enable = false` is legal and the image pin remains.
- [ ] `hosts/forge/services/litellm.nix`: move the dataset and sanoid
      declarations out of `mkIf serviceEnabled`, then `enable = false`.
- [ ] Do not re-run `atrium-model-resolver-initialize`,
      `atrium-model-controller-initialize`, or
      `atrium-model-admission-initialize`.
- [ ] Leave `copilot-api`, `copilot-api-keys.service`, and
      `preseed-litellm.service` in place.
