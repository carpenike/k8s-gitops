# Hermes agents

Hermes Agent (`docker.io/nousresearch/hermes-agent`, v0.22.6) bots on
Matrix (`ryanholt.net`, [matrix.md](matrix.md)). Each bot is a folder of
inputs under `kubernetes/apps/hermes/<bot>/`, built by the Kustomize
component `kubernetes/components/hermes-bot/`, in its own namespace
`hermes-<bot>`.

| Bot | Namespace | Matrix ID | Model | Who it answers |
| --- | --- | --- | --- | --- |
| `chief` | `hermes-chief` | `@chief:ryanholt.net` | `claude-sonnet` via LiteLLM | `@ryan:ryanholt.net` |

## Adding a bot

1. Add the Matrix name to the appservice regex
   ([matrix.md](matrix.md#bot-accounts)). This needs the YubiKey.
2. Copy `kubernetes/apps/hermes/chief/kustomization.yaml` to
   `kubernetes/apps/hermes/<bot>/kustomization.yaml`, set `namespace:
   hermes-<bot>` and the inputs below, and add `./<bot>` to
   `kubernetes/apps/hermes/kustomization.yaml`.

That is the whole bot. Nothing else is copied or edited.

### Inputs

Flat strings in ConfigMap `hermes-bot-inputs`, so they could become a CRD
spec later:

| Input | Example | Used for |
| --- | --- | --- |
| `BOT_NAME` | `chief` | Namespace `hermes-<BOT_NAME>`, object names, the R2 path, the LiteLLM key alias `hermes-<BOT_NAME>`. Lowercase letters, digits, `-` |
| `MATRIX_USER` | `chief` | Bare localpart. `@<MATRIX_USER>:ryanholt.net`, device `HERMES_<MATRIX_USER>` |
| `LLM_MODEL` | `claude-sonnet` | LiteLLM model name; also the key's only allowed model |
| `LLM_BUDGET_USD` | `25` | Key budget |
| `LLM_BUDGET_DURATION` | `30d` | Budget reset period |
| `MATRIX_ALLOWED_USERS` | `@ryan:ryanholt.net` | Comma-separated Matrix IDs the bot answers |
| `AGENT_STORAGE_SIZE` | `10Gi` | Agent state PVC |
| `WORKSPACE_STORAGE_SIZE` | `20Gi` | Shared workspace PVC |
| `API_SERVER_ENABLED` | `true` | Optional, default `false`. The OpenAI-compatible API on envoy-internal ([API server](#api-server-opt-in)). `true` or `false` only |

The `namespace:` line has to match `hermes-<BOT_NAME>`. Kustomize's
namespace transformer cannot be driven by a ConfigMap value. The
component also derives the bot's namespace from `BOT_NAME` everywhere it
is used, so a mismatch fails to apply rather than landing objects in the
wrong place.

## What the component creates

In namespace `hermes-<bot>`, from the bot's folder (kustomize
replacements, no Flux substitution):

- The Namespace, with Pod Security `restricted`, label
  `hermes.holthome.net/bot: <bot>`, and pruning disabled.
- ConfigMaps `hermes-bot-inputs` and `hermes-bot-derived`.
- Flux Kustomizations `provision` and `app`. Both use `postBuild.substituteFrom`
  on the two ConfigMaps.

`provision` (`kubernetes/components/hermes-bot/provision`) waits for every
object:

- The CiliumNetworkPolicies below.
- The Matrix provisioning template
  (`kubernetes/apps/matrix/hermes-bot-provisioner/template`). Job
  `matrix/hermes-provision-<bot>` logs `@<MATRIX_USER>` in through the
  appservice and patches Secret `hermes-<bot>-matrix`.
- The LiteLLM key template
  (`kubernetes/apps/litellm/key-provisioner/template`). Key
  `hermes-<bot>` in team `hermes`, written to Secret `litellm` as
  `OPENAI_API_KEY`.
- Job `hermes-ssh-keygen`, which writes Secrets `agent-ssh` (the agent's
  ed25519 key, plus a `known_hosts` line for the screen) and `screen-ssh`
  (the screen's host key, plus `authorized_keys` holding only the agent's
  public key).

The Jobs refuse to write a Secret that lacks their own labels
(`app.kubernetes.io/name` and `app.kubernetes.io/instance`). A mistyped
name fails instead of overwriting some other Secret. Flux creates each
Secret empty with `ssa: IfNotPresent` and never reapplies it.

`app` (`kubernetes/components/hermes-bot/app`) depends on `provision`, and
contains the HelmRelease `hermes` (app-template 5.3.0) and VolSync.

## Two pods

```
            Matrix (tuwunel:8008)     LiteLLM :4000
                     ^                     ^
                     |                     |
   +-----------------+---------------------+---+
   | agent   (runc)                            |   hermes gateway run
   | Matrix token, LiteLLM key, crypto store   |   /opt/data  (ceph-block, VolSync)
   +-------------------+-----------------------+
                       | ssh :22 (key-only, pinned host key)
   +-------------------v-----------------------+
   | screen  (kata-qemu)                       |   sshd as pn
   | terminal, files, execute_code, Chromium,  |   /workspace (ceph-filesystem RWX,
   | Xvnc + Xfce, cua-driver. No credentials.  |   shared with agent)
   +-------------------------------------------+
                       |
                 public internet
```

### Agent

`hermes gateway run`, uid 10000, read-only root, all capabilities dropped,
no ServiceAccount token, `runc`. It is the only pod with credentials:

- `envFrom` Secret `hermes-<bot>-matrix`: `MATRIX_HOMESERVER` (the
  in-cluster `http://tuwunel.matrix.svc.cluster.local:8008`),
  `MATRIX_USER_ID`, `MATRIX_DEVICE_ID`, `MATRIX_ACCESS_TOKEN`.
- `envFrom` Secret `litellm`: `OPENAI_API_KEY`. That name is the
  `openai-api` provider's key variable, so Hermes' local environment
  policy strips it from every child process it starts. It is referenced
  in `config.yaml` as `model.api_key: ${OPENAI_API_KEY}`.

The `config` init container runs `hermes config set` for the keys git
owns. The rest of `config.yaml` stays Hermes-managed:

| Key | Value |
| --- | --- |
| `model.provider` | `custom` |
| `model.default` | `LLM_MODEL` |
| `model.base_url` | `http://litellm.litellm.svc.cluster.local:4000/v1` |
| `model.api_key` | `${OPENAI_API_KEY}`, expanded at runtime |
| `terminal.backend` | `ssh` |
| `terminal.ssh_host` | `screen.hermes-<bot>.svc.cluster.local` |
| `terminal.ssh_user` / `ssh_port` / `ssh_key` | `pn` / `22` / `/etc/hermes-ssh/id_ed25519` |
| `terminal.cwd` | `/workspace` |
| `bot_desktop.placement` | `terminal` |
| `matrix.allowed_users` | `MATRIX_ALLOWED_USERS` |

`hermes config set` warns that `terminal.ssh_*` are "not recognized".
That warning is cosmetic: `hermes_cli/config.py` `TERMINAL_CONFIG_ENV_MAP`
bridges each one to `TERMINAL_SSH_*`, which the terminal tool reads.

The image starts s6-overlay when its entrypoint is PID 1, and s6 cannot
drop supplementary groups as non-root. `shareProcessNamespace: true` makes
the pause container PID 1, so `docker/entrypoint-dispatch.sh` takes its
direct-bootstrap path, which works as uid 10000 on a read-only root. The
s6-supervised dashboard is unavailable; nothing here uses it. `/run` and
`/tmp` are emptyDirs, as in jyje/hermes-agent-helm
`values-hardened.yaml`.

`$HERMES_HOME` is `/opt/data` on PVC `agent-data` (`ceph-block`, RWO,
kept on uninstall). It holds `config.yaml`, sessions, memories, skills,
and the Matrix crypto store (`platforms/matrix/store/`). VolSync backs it
up to R2 at 03:45 UTC, which is 10:45 PM Eastern in winter and 11:45
PM in summer (7 daily, 4 weekly). The R2 path is
`hermes-<bot>`. The PVC's `dataSourceRef` is ReplicationDestination
`agent-data-restore`, so a new PVC starts from the latest backup in that
path, or empty if there is none.

### Screen

`ghcr.io/carpenike/hermes-screen`, built from
`images/hermes-screen/Dockerfile`, with `runtimeClassName: kata-qemu`. The
Dockerfile is upstream `docker/sandbox-desktop.Dockerfile` at v0.22.6
(Xvnc, Xfce, headed Chromium, cua-driver), plus `openssh-server`, with
passwordless sudo removed. Upstream publishes
`nousresearch/hermes-sandbox:*-desktop` only up to v0.21.7. Its
Dockerfile differs from v0.22.6, so the image is built here
(`.github/workflows/hermes-screen-image.yaml`) and pinned by digest.

sshd (`images/hermes-screen/sshd_config`) runs as `pn` (uid 1000) on
port 22. It binds without capabilities through the namespaced sysctl
`net.ipv4.ip_unprivileged_port_start=22`. Its settings:

- Public key only; password and keyboard-interactive login are off.
- `AllowUsers pn`, no root login, and no PAM.
- No `AcceptEnv`. Hermes forwards only skill-declared passthrough
  variables, and none are configured.
- No TCP, agent, X11, or tunnel forwarding.
- `SetEnv XDG_RUNTIME_DIR=/tmp/hermes-runtime
  PLAYWRIGHT_BROWSERS_PATH=/opt/playwright`. Upstream puts these in
  `/etc/environment` for `pam_env`; with no PAM that file is never read.

The host key and `authorized_keys` come from Secret `screen-ssh`, so the
host key is stable across restarts. The agent pre-seeds
`~/.ssh/known_hosts`, and Hermes connects with
`StrictHostKeyChecking=accept-new`, so a changed host key is refused.

The screen has no Matrix or LiteLLM credentials, no ServiceAccount token,
and no route to LiteLLM, Tuwunel, the LAN, or the API server.

Chromium runs **without its own sandbox** in the screen. Both launches
pass `--no-sandbox`:

- the dock's Browser icon: `tools/bot_desktop/runtime.py:874`,
  `dock_exec_line(..., sandbox_bypass=True)`;
- the agent's automation browser: `tools/browser_session_sandbox.py:117`,
  where `build_chromium_argv` gets `CHROMIUM_SANDBOX_BYPASS_ARGS`
  unconditionally.

Turning the sandbox back on would mean patching Hermes. The boundary is
the Kata VM: a renderer escape lands in a guest that has no credentials
and no LAN or cluster routes.

### Where tools run

From the Hermes source at v0.22.6:

| Source | Behaviour |
| --- | --- |
| `tools/terminal_tool_backends.py` (`_SSH_KEYS`), `tools/environments/ssh.py` | `terminal.backend: ssh` runs every terminal command on `ssh_user@ssh_host` |
| `tools/terminal_tool.py` (`_degraded_result`) | An unreachable backend raises `EnvironmentConnectionError` and returns `status: degraded` (or the error, with `degraded_mode: fail`). It never runs the command locally |
| `tools/file_tools.py`, `tools/code_execution_tool.py` | File tools and `execute_code` go through the same terminal environment (a remote kernel for remote backends) |
| `tools/bot_desktop/placement.py` | With an ssh backend, the desktop, browser, and `computer_use` run inside that backend. `placement: terminal` refuses rather than falling back to the gateway host |
| `tools/bot_desktop/sandbox_host.py` | The desktop user is `pn`, so `ssh_user` is `pn` |

`web_search` and `web_extract` run in the gateway through a search
provider. None is configured, so the agent has no internet egress.

Keep it that way, or set those tools' own keys first. With no
tool-specific key, the TTS, STT, live-voice, image-generation, and
video-generation tools fall back to `OPENAI_API_KEY` and call
`api.openai.com`:

- `tools/tts_tool_openai.py`
- `tools/transcription_cloud.py`, `tools/transcription_tools.py`
- `tools/voice_live.py`
- `tools/image_generation_tool.py`
- `agent/video_gen_provider.py`

Here that variable holds the LiteLLM virtual key, so opening agent
egress would send it to OpenAI. Today the agent CNP blocks the
connection.

Two Hermes-internal paths still run on the agent: the gateway itself, and
Bot Mode DM (`tools/bot_mode_dm.py`), which runs a Hermes-built command.
Neither takes a command from the model.

### Skills and file sync

On each command, `tools/environments/ssh.py` pushes `~/.hermes/skills`,
`credentials`, and `cache` to `pn`'s `~/.hermes`. On teardown,
`file_sync.py` pulls changed and new files back; credentials are
upload-only. The app container mounts `/opt/data/skills` read-only
(`subPath: skills` of the same PVC), so a sync-back that tries to change or
add a skill fails with `EROFS`, logs a warning after three attempts, and
writes nothing. The init container, whose mount is writable, syncs
bundled skills on each start. The cost: the agent cannot author or edit
skills at runtime. To change a skill, edit it on the PVC from the
`config` init container or with `task k8s:browse-pvc`, then restart.

### Shared workspace

PVC `workspace` (`ceph-filesystem`, RWX) at `/workspace` in both pods.
Both pods use `fsGroup: 1000`, which is `pn`'s group, so files keep one
group. It is scratch: there is no VolSync for it. Anything worth keeping
belongs in Matrix or a skill.

## Network

Default deny in `hermes-<bot>` both ways. The allows:

| Pod | Ingress | Egress |
| --- | --- | --- |
| agent | none; with `API_SERVER_ENABLED`, the `envoy-internal` proxies on 8642 (CNP `agent-api`) | DNS; `litellm/litellm:4000`; `matrix/tuwunel:8008`; screen `:22` |
| screen | agent on 22 | DNS; `0.0.0.0/0` except RFC1918, CGNAT, link-local |
| `hermes-ssh-keygen` | none | DNS; kube-apiserver |
| `hermes-volsync` (movers) | none | DNS; public internet (R2) |

Tuwunel's policy admits `app.kubernetes.io/controller: agent` from any
namespace labelled `hermes.holthome.net/bot`.

## API server (opt-in)

Hermes' gateway can also serve an OpenAI-compatible API:

- `/v1/chat/completions`, `/v1/responses`, `/v1/runs`, `/v1/models`;
- `/health`, which needs no key.

It is for Ryan's other assistant on the LAN to talk to a bot directly.
**Off by default.** A bot turns it on with `API_SERVER_ENABLED=true` in its
inputs; today only Chief does.

When it is on, the component adds these, all gated in the HelmRelease by
that one input:

| Object | What |
| --- | --- |
| ExternalSecret / Secret `api-server` | `API_SERVER_KEY` from 1Password item `hermes-<bot>`, field `api_server_key`, plus `API_SERVER_ENABLED=true`, `API_SERVER_HOST=0.0.0.0`, `API_SERVER_PORT=8642`, `API_SERVER_MODEL_NAME=<bot>` |
| Service `agent-api` | Port 8642 on the agent pod |
| HTTPRoute `agent-api` | `https://<bot>-api.${SECRET_DOMAIN}`, **envoy-internal only**. Never envoy-external, never a cloudflared rule. Labelled `gateway.holthome.net/auth: public`: a bearer client cannot do the gateway login, and Hermes checks the key itself |
| CiliumNetworkPolicy `agent-api` | Ingress to 8642 from the envoy-internal proxies only. Agent egress is unchanged |
| ReferenceGrant `agent-api-gateway-auth` | Lets `pocket-id-exempt` select the route |

The agent reads the Secret through an optional `envFrom`. A bot that is
off has no Secret, so no `API_SERVER_*` variables and no listener. In
v0.22.6 the key, not `API_SERVER_ENABLED`, is what starts the server:
`gateway/config_env.py` `_api_server` enables it whenever
`API_SERVER_KEY` is a usable secret (16+ characters, not a placeholder),
and the adapter refuses to start otherwise. The screen pod gets neither
the key nor the port. Hermes strips `API_SERVER_KEY` from child processes,
as it does the other credentials. `API_SERVER_CORS_ORIGINS` is unset, so
no browser origin is allowed.

**The key is remote code execution.** An API turn has the same terminal,
file, `execute_code`, browser, memory, and `session_search` tools as a
Matrix turn (no `computer_use`), and they run in the screen pod. Anyone
on the LAN who has the key can make the bot do anything it can do from
Matrix.

### What it shares with Matrix

From the source at v0.22.6:

- **One process.** The API server is a gateway platform adapter
  (`gateway/platforms/api_server.py`). `hermes gateway run` connects every
  enabled adapter concurrently in the same process
  (`gateway/run_startup.py`, `_start_connect_pending`), so Matrix and the
  API share one gateway, config, model key, and `$HERMES_HOME`.
- **Matrix allowlists do not apply.** API requests run their own agent
  loop (`_run_agent`, which "never passes through `TurnRunner`") and are
  authorised only by the bearer key (`_check_auth`,
  `hmac.compare_digest`). `matrix.allowed_users` and
  `GATEWAY_ALLOWED_USERS` gate messaging platforms
  (`gateway/authz_mixin.py`, `_is_user_authorized`). Nothing extra is
  needed for API calls, and nothing extra stops them.
- **Curated memory is shared; conversations are not.**
  - `MEMORY.md` and `USER.md` live in `$HERMES_HOME/memories`
    (`tools/memory_tool.py`, `get_memory_dir`), one set per bot. API and
    Matrix turns read and write the same memory, which enters each
    session's prompt as a snapshot at session start.
  - Transcripts are separate sessions. API sessions have source
    `api_server`, are keyed by `X-Hermes-Session-Id` /
    `X-Hermes-Session-Key`, and never continue the Matrix DM.
  - `session_search` covers every session that isn't kanban, subagent or
    tool (`tools/session_search_tool.py`, `_HIDDEN_SESSION_SOURCES`). So
    an API turn can search and read the Matrix DM's history, which is
    stored decrypted in the session DB.

### Turning it on for a bot

1. In 1Password vault `k8s-secrets`, item `hermes-<bot>`, add field
   `api_server_key` with a strong secret, e.g. `openssl rand -hex 32`.
   Never commit it.
2. Add `API_SERVER_ENABLED=true` to the bot's inputs.

If the field is missing, ExternalSecret `api-server` stays unready, the
Secret is never created, and the bot runs without an API server.

### Rotating the key

Change `api_server_key` in 1Password. External Secrets picks it up within
the 1h refresh, or at once with:

```sh
kubectl -n hermes-<bot> annotate externalsecret api-server force-sync="$(date +%s)" --overwrite
```

Reloader restarts the agent when Secret `api-server` changes, and the old
key stops working. Update the client's copy.

### Example

With the key in a file (mode 0600) on the client:

```sh
curl -s https://chief-api.<internal domain>/health
curl -s https://chief-api.<internal domain>/v1/chat/completions \
  -H "Authorization: Bearer $(cat ~/.config/hermes/chief-api-key)" \
  -H 'Content-Type: application/json' \
  -d '{"model": "chief", "messages": [{"role": "user", "content": "hostname?"}]}'
```

Add `-H 'X-Hermes-Session-Key: <name>'` to keep one conversation going
across requests.

## Matrix recovery key

Hermes reads `MATRIX_RECOVERY_KEY` only at connect time
(`plugins/platforms/matrix/adapter.py`,
`_verify_or_bootstrap_cross_signing`). It is not in the steady-state
environment: a bot whose crypto store survives does not need it.

New bot: on first boot Hermes bootstraps cross-signing and writes a
recovery key once to `/opt/data/matrix-recovery-key` (0600). Move it to
1Password item `hermes-<bot>`, field `matrix_recovery_key`, and delete the
file. Until it is deleted the key sits on the PVC, so it is in every
nightly R2 backup and in any restore:

```sh
kubectl -n hermes-<bot> exec deploy/hermes-agent -c app -- cat /opt/data/matrix-recovery-key
kubectl -n hermes-<bot> exec deploy/hermes-agent -c app -- rm /opt/data/matrix-recovery-key
```

Fresh crypto store (lost PVC, empty restore): delete the bot's
`HERMES_<USER>` device from the admin room first ([matrix.md](matrix.md)),
then re-verify for one boot with a hand-made Secret. The HelmRelease
mounts it with `optional: true`, and nothing in git creates it:

```sh
kubectl -n hermes-<bot> create secret generic matrix-recovery \
  --from-literal=MATRIX_RECOVERY_KEY="$(op read 'op://k8s-secrets/hermes-<bot>/matrix_recovery_key')"
kubectl -n hermes-<bot> rollout restart deploy/hermes-agent
kubectl -n hermes-<bot> logs deploy/hermes-agent -c app | grep 'cross-signing verified'
kubectl -n hermes-<bot> delete secret matrix-recovery
kubectl -n hermes-<bot> rollout restart deploy/hermes-agent
```

## Removing a bot

Remove `./<bot>` from `kubernetes/apps/hermes/kustomization.yaml`. Flux
prunes the two Kustomizations and everything they made except the
Namespace (pruning disabled) and the two PVCs (`retain: true` is Helm's
keep policy: the PVCs outlive the HelmRelease). The `ceph-block` and
`ceph-filesystem` PVs have reclaim policy `Delete`, so deleting the PVC or
the Namespace deletes the data. R2 still has the agent's backups. Then
deactivate the Matrix account from the admin room and remove the name
from the appservice regex.

## Backups and restores

### A backup you can rely on

`lastManualSync` and a `Successful` result do not prove a snapshot was
written. A source whose directory is empty logs "Directory is empty
skipping backup" and still succeeds. Only restic's "snapshot … saved" line
proves it. Stop the agent first, so the snapshot is of a volume nothing
is writing:

```sh
flux -n hermes-<bot> suspend helmrelease hermes
kubectl -n hermes-<bot> scale deploy/hermes-agent --replicas 0
kubectl -n hermes-<bot> wait --for=delete pod -l app.kubernetes.io/controller=agent --timeout=5m
kubectl -n hermes-<bot> patch replicationsource agent-data --type merge \
  -p '{"spec":{"trigger":{"manual":"<label>"}}}'
kubectl -n hermes-<bot> get replicationsource agent-data -o jsonpath='{.status.lastManualSync}{"\n"}'   # = <label>
kubectl -n hermes-<bot> get replicationsource agent-data \
  -o jsonpath='{.status.latestMoverStatus.logs}' | grep -E 'snapshot [0-9a-f]+ saved'
```

Resume with `flux -n hermes-<bot> resume helmrelease hermes`, which scales
the agent back up.

### Check the first restore before trusting a bot

A new `agent-data` PVC is filled once from the latest snapshot in R2. Check
which snapshot it used:

```sh
kubectl -n hermes-<bot> get replicationdestination agent-data-restore \
  -o jsonpath='{.status.latestMoverStatus.logs}' | grep -E 'restoring snapshot|No eligible snapshots found'
```

`latestMoverStatus.logs` holds only the lines VolSync's filter keeps
(`internal/controller/mover/restic/logfilter.go`, v0.17.0). That is restic's
own `restoring snapshot <id> of [/data] …`, not the mover script's
`Selected restic snapshot` line.

- `restoring snapshot <id>`: the volume was restored from `<id>`.
- `No eligible snapshots found`: the bot started on an empty volume. Stop
  it before it uploads a fresh device identity:

  ```sh
  flux -n hermes-<bot> suspend helmrelease hermes
  kubectl -n hermes-<bot> scale deploy/hermes-agent --replicas 0
  ```

  Then restore into the volume (below), or take the "Fresh crypto store"
  path above.

A restore can bring back `/opt/data/matrix-recovery-key` if it was never
deleted after first boot:

```sh
kubectl -n hermes-<bot> exec deploy/hermes-agent -c app -- sh -c 'test -e /opt/data/matrix-recovery-key && echo present || echo absent'
kubectl -n hermes-<bot> exec deploy/hermes-agent -c app -- rm -f /opt/data/matrix-recovery-key
```

### Restoring into an existing volume

`agent-data-restore` runs only when the PVC is created. To roll a running
bot back to a snapshot, stop the agent as above, then apply a one-off
ReplicationDestination. Without `restoreAsOf` it picks the latest
snapshot:

```yaml
apiVersion: volsync.backube/v1alpha1
kind: ReplicationDestination
metadata:
  name: agent-data-rollback
  namespace: hermes-<bot>
spec:
  trigger:
    manual: rollback-1
  restic:
    repository: agent-volsync
    destinationPVC: agent-data
    copyMethod: Direct
    enableFileDeletion: true
    moverPodLabels:
      app.kubernetes.io/name: hermes-volsync
    moverSecurityContext:
      runAsNonRoot: true
      runAsUser: 10000
      runAsGroup: 10000
      fsGroup: 1000
      seccompProfile:
        type: RuntimeDefault
```

`moverPodLabels` matters: the namespace's CNP allows R2 egress only for
`hermes-volsync`. Check for `restoring snapshot`, delete the object, then
resume the HelmRelease. Restoring an older crypto store can leave the bot
unable to decrypt messages sent after that snapshot.

## Chief's migration (4 Nov 2026)

Chief moved from the single-pod deployment in namespace `hermes` to
`hermes-chief`. The path used was the **R2 restore**, not a fresh store:

- Pre-merge backup: snapshot `c65cd916`, 388 files. This was the first
  real one, because the old source's earlier sync had skipped an "empty"
  directory.
- `agent-data-restore` restored `c65cd916`. Chief came up on its existing
  crypto store and device `HERMES_CHIEF` and answered `@ryan` in an
  encrypted room.

The cleanup removed `kubernetes/apps/hermes/legacy`, so Flux pruned
Namespace `hermes`. The old volume's PV, `pvc-5e863780-3f91-4043-9158-47f7bf687927`,
was set to `Retain` first. It survives as `Released` with the
pre-migration state. Deleting a `Retain` PV object leaves the Ceph RBD
image behind. To free the space, set the policy back to `Delete` and let
the CSI driver remove the image:

```sh
kubectl patch pv pvc-5e863780-3f91-4043-9158-47f7bf687927 \
  -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'
```
