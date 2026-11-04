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
| agent | none | DNS; `litellm/litellm:4000`; `matrix/tuwunel:8008`; screen `:22` |
| screen | agent on 22 | DNS; `0.0.0.0/0` except RFC1918, CGNAT, link-local |
| `hermes-ssh-keygen` | none | DNS; kube-apiserver |
| `hermes-volsync` (movers) | none | DNS; public internet (R2) |

Tuwunel's policy admits `app.kubernetes.io/controller: agent` from any
namespace labelled `hermes.holthome.net/bot`.

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

## Chief's migration from namespace `hermes`

Chief's new PVC restores from the same R2 path (`hermes-chief`) the old
`chief` ReplicationSource wrote to, so Chief keeps its Matrix crypto
store and device `HERMES_CHIEF`.

`kubernetes/apps/hermes/legacy` keeps the old HelmRelease at zero
replicas, its Namespace, its CNP, and PVC `chief-data`. It is **not a
rollback point**. The merge itself:

- prunes Kustomizations `chief-matrix` and `chief-litellm`, with Secrets
  `hermes/hermes-chief-matrix` and `hermes/chief-litellm`;
- prunes the old ReplicationSource `chief`, so nothing backs up
  `chief-data` any more;
- logs `@chief` in again on device `HERMES_CHIEF`. The new token
  replaces the one the old Secret held;
- deletes LiteLLM key `hermes-chief` and issues a new one, so the key's
  spend and budget window start again at zero. Team `hermes` keeps its
  spend.

### Before merge: a backup that has data in it

The old ReplicationSource's only sync so far logged "Directory is empty
skipping backup" and still reported success. R2 may have no snapshot.
`lastManualSync` and a successful result do not prove a snapshot was
written. Only the restic "snapshot … saved" line does.

```sh
flux -n hermes suspend helmrelease chief
kubectl -n hermes scale deploy/chief --replicas 0
kubectl -n hermes wait --for=delete pod -l app.kubernetes.io/name=chief --timeout=5m
kubectl -n hermes get pods -l app.kubernetes.io/name=chief   # No resources found
kubectl -n hermes patch replicationsource chief --type merge \
  -p '{"spec":{"trigger":{"manual":"pre-migration-1"}}}'
kubectl -n hermes get replicationsource chief -o jsonpath='{.status.lastManualSync}{"\n"}'
# Gate: this must print a "snapshot <id> saved" line.
kubectl -n hermes get replicationsource chief \
  -o jsonpath='{.status.latestMoverStatus.logs}' | grep -E 'snapshot [0-9a-f]+ saved'
```

Wait until no `chief` pod exists before triggering, so the snapshot is
of a volume nothing is writing. If the gate prints nothing, do not
merge. Look at what is on `chief-data` first
(`task k8s:browse-pvc NS=hermes CLAIM=chief-data`).

### After merge: check the restore before trusting Chief

```sh
kubectl -n hermes-chief get replicationdestination agent-data-restore \
  -o jsonpath='{.status.latestMoverStatus.logs}' | grep -E 'Selected restic snapshot|No eligible snapshots found'
```

- `Selected restic snapshot`: the volume was restored. Carry on with the
  post-deploy checks.
- `No eligible snapshots found`: Chief started on an empty volume. Stop
  it at once, before it uploads a fresh device identity for
  `HERMES_CHIEF`:

  ```sh
  flux -n hermes-chief suspend helmrelease hermes
  kubectl -n hermes-chief scale deploy/hermes-agent --replicas 0
  ```

  Then either restore from `chief-data` (see Rollback, with the
  directions swapped) or go the "Fresh crypto store" way above.

Restored state can include `/opt/data/matrix-recovery-key`, if it was
never deleted after Chief's first boot. Check and delete it:

```sh
kubectl -n hermes-chief exec deploy/hermes-agent -c app -- sh -c 'test -e /opt/data/matrix-recovery-key && echo present || echo absent'
kubectl -n hermes-chief exec deploy/hermes-agent -c app -- rm -f /opt/data/matrix-recovery-key
```

### Rollback

Reverting the PR alone does not give back the old Chief as it was:

- `chief-data` holds the state from before the merge. The crypto store
  on it is older than the one Chief has been using since.
- The revert re-creates `chief-matrix` and `chief-litellm`, so the token
  and the LiteLLM key rotate again, and the key's spend resets again.

A real rollback carries the current state back:

1. Stop the new agent and back it up, with the same gate as above:
   ```sh
   flux -n hermes-chief suspend helmrelease hermes
   kubectl -n hermes-chief scale deploy/hermes-agent --replicas 0
   kubectl -n hermes-chief wait --for=delete pod -l app.kubernetes.io/controller=agent --timeout=5m
   kubectl -n hermes-chief patch replicationsource agent-data --type merge \
     -p '{"spec":{"trigger":{"manual":"rollback-1"}}}'
   kubectl -n hermes-chief get replicationsource agent-data \
     -o jsonpath='{.status.latestMoverStatus.logs}' | grep -E 'snapshot [0-9a-f]+ saved'
   ```
2. Revert the PR. Flux re-creates the old Kustomizations, which
   re-provision the Matrix token and LiteLLM key in `hermes`, and the old
   `chief` HelmRelease at one replica. Scale `deploy/chief` to 0 as soon
   as it appears.
3. Restore `chief-data` from R2 with a one-off ReplicationDestination.
   It reads the same `hermes-chief` path, which now has the newest
   snapshot:
   ```yaml
   apiVersion: volsync.backube/v1alpha1
   kind: ReplicationDestination
   metadata:
     name: chief-rollback
     namespace: hermes
   spec:
     trigger:
       manual: rollback-1
     restic:
       repository: chief-volsync
       destinationPVC: chief-data
       copyMethod: Direct
       moverSecurityContext:
         runAsNonRoot: true
         runAsUser: 10000
         runAsGroup: 10000
         fsGroup: 10000
         seccompProfile:
           type: RuntimeDefault
   ```
   Check its `latestMoverStatus.logs` for `Selected restic snapshot`,
   delete it, then scale `deploy/chief` back to 1.

### Cleanup, after Chief answers `@ryan` in an encrypted room from `hermes-chief`

A follow-up PR deletes `kubernetes/apps/hermes/legacy`. PV `chief-data`
has reclaim policy `Delete`, so deleting Namespace `hermes` would delete
the old volume with it. Keep it until you're sure:

```sh
kubectl patch pv "$(kubectl -n hermes get pvc chief-data -o jsonpath='{.spec.volumeName}')" \
  -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl delete namespace hermes
```

Delete the released PV by hand later.
