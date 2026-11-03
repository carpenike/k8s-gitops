# Hermes agents

Hermes Agent (`docker.io/nousresearch/hermes-agent`, v0.22.6) in namespace
`hermes`. Each agent is one pod in a `kata-qemu` VM (ADR 0009) with a
Matrix account on `ryanholt.net` ([matrix.md](matrix.md)).

| Agent | Matrix ID | Model | Who it answers |
| --- | --- | --- | --- |
| `chief` | `@chief:ryanholt.net` | `claude-sonnet` via LiteLLM | `@ryan:ryanholt.net` |

## How Chief runs

`kubernetes/apps/hermes/chief`. Two Flux Kustomizations, both in namespace
`hermes`:

- `chief-matrix` instantiates the provisioning template for `BOT_NAME:
  chief`. It waits for the Job, so Secret `hermes-chief-matrix` has
  `MATRIX_HOMESERVER`, `MATRIX_USER_ID`, and `MATRIX_ACCESS_TOKEN` before
  the agent starts.
- `chief` is the HelmRelease (`app-template` 5.3.0): one replica,
  `Recreate`, `hermes gateway run`.

Pod security is `restricted`. The image normally starts s6-overlay as
root and drops to its `hermes` user (uid 10000). With
`shareProcessNamespace: true` the pause container is PID 1, so the
entrypoint skips s6 and bootstraps directly. That path accepts uid 10000,
so the pod runs as 10000 with no capabilities and a read-only root
(`docker/entrypoint-dispatch.sh`, `docker/stage2-hook.sh` at v0.22.6).
Supervised side services, such as the dashboard, are unavailable in that
mode. The gateway is the only process this pod needs.

`$HERMES_HOME` is `/opt/data` on PVC `chief-data` (10Gi, `ceph-block`,
kept on uninstall). It holds `config.yaml`, sessions, memories, and the
Matrix crypto store (`platforms/matrix/store/`). Hermes seeds and migrates
`config.yaml` itself, so the `config` init container only runs
`hermes config set` for the keys git owns:

| Key | Value |
| --- | --- |
| `model.provider` | `custom` |
| `model.default` | `claude-sonnet` |
| `model.base_url` | `http://litellm.litellm.svc.cluster.local:4000/v1` |
| `model.api_key` | `${LITELLM_API_KEY}`, stored literally and expanded at runtime |

Matrix settings are environment variables:

- `MATRIX_E2EE_MODE=required`: every room is encrypted, so the bot fails
  closed rather than joining without crypto.
- `MATRIX_ALLOWED_USERS=@ryan:ryanholt.net`.
- `MATRIX_DEVICE_ID=HERMES_CHIEF`, the device the provisioning Job logged
  in with.
- `MATRIX_RECOVERY_KEY_OUTPUT_FILE=/opt/data/matrix-recovery-key`.

Network: default deny in `hermes`. Chief has no ingress and no Service.
Egress is cluster DNS, LiteLLM on 4000, and public IPv4. RFC1918, CGNAT,
and link-local are excluded. Matrix is reached at
`https://matrix.ryanholt.net` through Cloudflare. No ServiceAccount token
is mounted.

Backup: VolSync restic to R2 (`volsync-r2-template`, path `hermes-chief`)
at 03:45, 7 daily and 4 weekly.

## What Ryan creates

1. **A LiteLLM virtual key.** In the LiteLLM Admin UI
   (`https://litellm.holthome.net`), create a key named `hermes-chief`,
   limited to model `claude-sonnet`. A budget is optional. Store it in
   1Password:

   ```sh
   op item create --vault k8s-secrets --category "API Credential" \
     --title hermes-chief 'litellm_api_key[concealed]=<key>'
   ```

   ExternalSecret `chief-litellm` reads `hermes-chief/litellm_api_key`.
   Until the item exists the pod cannot start, and Kustomization `chief`
   stays unready. Nothing else waits on it.

2. **The recovery key, after first boot.** Hermes sets up cross-signing
   for `@chief` and writes a new recovery key to
   `/opt/data/matrix-recovery-key` (mode 0600, never overwritten). Move it
   to the same item and delete the file:

   ```sh
   kubectl -n hermes exec deploy/chief -- cat /opt/data/matrix-recovery-key
   op item edit hermes-chief --vault k8s-secrets 'matrix_recovery_key[concealed]=<key>'
   kubectl -n hermes exec deploy/chief -- rm /opt/data/matrix-recovery-key
   ```

   With that key, a rebuilt crypto store can sign itself again
   (`MATRIX_RECOVERY_KEY`). It is not wired into the pod yet.

Then DM `@chief:ryanholt.net` from Element.

## Adding another agent

1. Add its name to the appservice regex ([matrix.md](matrix.md#bot-accounts)).
2. Copy `kubernetes/apps/hermes/chief` to `kubernetes/apps/hermes/<name>`,
   change `chief` throughout, and add its `ks.yaml` to
   `kubernetes/apps/hermes/kustomization.yaml`.
3. Create a LiteLLM key and a 1Password item `hermes-<name>`.

## Tested before merge

Locally under podman, on the pinned image, with the same flags the pod
uses (uid 10000, not PID 1, read-only root, no capabilities):

- Bootstrap and `hermes config set` succeed on an empty volume.
- `hermes gateway run` against Tuwunel v1.9.4 uploads device keys,
  bootstraps cross-signing, writes the recovery key, and auto-joins an
  encrypted DM from `@ryan`.

A model reply was not tested; that needs the LiteLLM key.
