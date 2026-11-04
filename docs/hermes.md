# Hermes agents

Hermes Agent (`docker.io/nousresearch/hermes-agent`, v0.22.6) bots on
Matrix (`ryanholt.net`, [matrix.md](matrix.md)). Each bot is a folder of
inputs under `kubernetes/apps/hermes/<bot>/`, built by the Kustomize
component `kubernetes/components/hermes-bot/`, in its own namespace
`hermes-<bot>`.

| Bot | Namespace | Matrix ID | Model | Who it answers |
| --- | --- | --- | --- | --- |
| `chief` | `hermes-chief` | `@chief:ryanholt.net` | `claude-sonnet` via LiteLLM | `@ryan:ryanholt.net` |

Long-term memory (Hindsight, shared, one schema per bot) is in
[hermes-memory.md](hermes-memory.md).

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
| `LLM_MODEL` | `claude-sonnet` | LiteLLM model name for the main model. The key itself may call every model on the proxy ([LiteLLM key](#litellm-key)) |
| `LLM_BUDGET_USD` | `25` | Key budget |
| `LLM_BUDGET_DURATION` | `30d` | Budget reset period |
| `MATRIX_ALLOWED_USERS` | `@ryan:ryanholt.net` | Comma-separated Matrix IDs the bot answers |
| `AGENT_STORAGE_SIZE` | `10Gi` | Agent state PVC |
| `WORKSPACE_STORAGE_SIZE` | `20Gi` | Shared workspace PVC |
| `API_SERVER_ENABLED` | `true` | Optional, default `false`. The OpenAI-compatible API on envoy-internal ([API server](#api-server-opt-in)). `true` or `false` only |
| `OUTLOOK_MCP_ENABLED` | `true` | Optional, default `false`. The Outlook MCP server ([Outlook](#outlook-opt-in)). `true` or `false` only |
| `OUTLOOK_MCP_EXPECTED_USERNAME` | `ryan@ryanholt.net` | With `OUTLOOK_MCP_ENABLED`: the one Microsoft account the server may use. Committed as-is: this repo is public |
| `HINDSIGHT_ENABLED` | `true` | Optional, default `false`. Long-term memory on the shared Hindsight server ([hermes-memory.md](hermes-memory.md)). `true` or `false` only |
| `WEBHOOK_ENABLED` | `true` | Optional, default `false`. The signed `chief-engineer` webhook on envoy-internal ([Webhook](#webhook-opt-in)). `true` or `false` only |
| `WEBHOOK_DELIVER_CHAT_ID` | `!1NY-w--JkAFJ…` | Required with `WEBHOOK_ENABLED`: the Matrix room ID of Ryan's DM with the bot, where webhook turns are delivered and mirrored. Without it the route is not written |
| `TAVILY_ENABLED` | `true` | Optional, default `false`. `web_search` and `web_extract` through Tavily ([Web search](#web-search-opt-in)). `true` or `false` only |

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
  `OPENAI_API_KEY` ([LiteLLM key](#litellm-key)).
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

### LiteLLM key

Each bot gets one LiteLLM virtual key, `hermes-<bot>`, with:

- **Models:** `all-proxy-models`, LiteLLM's sentinel for every model on
  the proxy. That covers the named models (`claude-*`, `gpt-6*`,
  `decision-1`, the `gpt-image-*` models) and the wildcard routes
  (`anthropic/*`, `openai/*`, `gemini/*`, `copilot/*`, `copilot-oai/*`),
  so any upstream model those providers offer, at its price. Team
  `hermes` sets no model list, so nothing narrows it.
- **Budget:** `LLM_BUDGET_USD` per `LLM_BUDGET_DURATION`. This is the
  only limit on spend, and the guard if a runaway or prompt-injected turn
  calls an expensive model.

`LLM_MODEL` is only the main model Hermes uses (`model.default`). Other
models are for Hermes features that name one: `/model` in chat,
`fallback_providers`, `delegation.model`, `auxiliary.<task>.model`, and
`/moa` presets. All of them point at the same LiteLLM endpoint and key.

The provisioner updates an existing key's models and budget in place
(`/key/update`); the key value does not change. To narrow a bot again,
set `MODELS` in `kubernetes/components/hermes-bot/derived.yaml` back to a
comma-separated list. It applies to every bot.

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
provider. A bot with `TAVILY_ENABLED=true` uses Tavily, and its agent may
reach `api.tavily.com` on 443 and nothing else on the internet ([Web
search](#web-search-opt-in)). Otherwise none is configured.

Keep agent egress to named hosts like that, or set those tools' own keys
first. With no
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
| agent | none; with `API_SERVER_ENABLED`, the `envoy-internal` proxies on 8642 (CNP `agent-api`); with `WEBHOOK_ENABLED`, the `envoy-internal` proxies on 8644 (CNP `agent-hooks`) | DNS; `litellm/litellm:4000`; `matrix/tuwunel:8008`; screen `:22`; with `OUTLOOK_MCP_ENABLED`, `login.microsoftonline.com` and `graph.microsoft.com` on 443 (CNP `agent-outlook`, FQDN); with `HINDSIGHT_ENABLED`, `hermes-memory` Hindsight pods on 8888 (CNP `agent-hindsight`); with `TAVILY_ENABLED`, `api.tavily.com` on 443 (CNP `agent-tavily`, FQDN) |
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

The agent reads the Secret through an optional `envFrom`. In v0.22.6 the
key, not `API_SERVER_ENABLED`, is what starts the server:
`gateway/config_env.py` `_api_server` enables it whenever
`API_SERVER_KEY` is a usable secret (16+ characters, not a placeholder),
and the adapter refuses to start otherwise.

A bot that is off still runs Hermes' own **loopback-only** listener. On
any boot whose env has no `API_SERVER_KEY`, `docker/stage2-hook.sh`
generates one into `$HERMES_HOME/.env`. Upstream uses it as a control
plane for cron fires. It binds the default `127.0.0.1:8642`, so nothing
outside the agent pod can reach it. Turning the API on changes the bind
to `0.0.0.0` and the key to the Secret's.

The screen pod gets neither the key nor the port. Hermes strips `API_SERVER_KEY` from child processes,
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

### Why the init container cleans `.env`

Hermes loads `$HERMES_HOME/.env` with `override=True`, so an
`API_SERVER_KEY` line there beats the Secret's env var. stage2 says so in
the log: "the .env value wins at runtime". The volume of a bot that ran
before the API was on, like Chief, already has such a line: its own
generated key. Clients holding the 1Password key then get 401 ("Invalid
gateway API key").

The `config` init container therefore:

- gets the same optional `envFrom` on `api-server`, so its stage2 run
  sees the key and skips generation. Without it, the init container
  would write a fresh key into `.env` on every boot;
- deletes any `^API_SERVER_KEY=` line from `/opt/data/.env` when that env
  key is present. Bots that are off are untouched.

Removing the line by hand without this would not last. The next start's
init container would generate another one.

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

## Webhook (opt-in)

A signed, asynchronous inbox for **Chief Engineer**, Ryan's homelab
assistant on Grok Bot. Chief Engineer POSTs a request; Hermes answers
`202` at once and runs the turn afterwards in its own session. When the
turn ends, Chief DMs Ryan on Matrix: what came in, who sent it, and what
he did or proposes. Ryan can reply in that DM, which has the delivered
text in its history (`mirror_to_session`).

**Off by default.** A bot turns it on with `WEBHOOK_ENABLED=true` and
`WEBHOOK_DELIVER_CHAT_ID=<room id>` in its inputs; today only Chief does.

When it is on, the component adds these, all gated in the HelmRelease by
`WEBHOOK_ENABLED`:

| Object | What |
| --- | --- |
| ExternalSecret / Secret `webhook` | `WEBHOOK_SECRET` from 1Password item `hermes-<bot>`, field `webhook_secret`, plus `WEBHOOK_ENABLED=true` and `WEBHOOK_PORT=8644` |
| Service `agent-hooks` | Port 8644 (`webhook`) on the agent pod |
| HTTPRoute `agent-hooks` | `https://<bot>-hooks.${SECRET_DOMAIN}`, **envoy-internal only**, path `/webhooks/chief-engineer` exactly; nothing else on 8644 (Hermes' `/health`, other routes) is reachable through it. Labelled `gateway.holthome.net/auth: public`: the sender signs each request and cannot do the gateway login |
| CiliumNetworkPolicy `agent-hooks` | Ingress to 8644 from the envoy-internal proxies only. The screen pod cannot reach it |
| ReferenceGrant `agent-hooks-gateway-auth` | Lets `pocket-id-exempt` select the route |
| config.yaml route `chief-engineer` | Written by the `config` init container (below) |

Like the API server, the hostname has no cloudflared rule and no public
DNS record: cloudflare-dns publishes only envoy-external routes, and the
tunnel's wildcard ends on envoy-external, which has no route for it.

### How the sender reaches it

The route is on envoy-internal only, and Chief Engineer runs off the
LAN. It has to POST from a host on the LAN that resolves
`<bot>-hooks.<internal domain>`. Which host relays, and what that
host's tunnel may reach, belongs to the network configuration, not to
this repo.

A relay that is down or away fails before the request reaches Hermes.
Chief never hears of it and nothing reaches the DM, so the sender has to
notice and report a failed POST itself. Prefer a relay that is always on
the LAN.

The signature is the sender's identity: anyone holding `webhook_secret`
is "Chief Engineer" to Chief, from any host. Keep it only on the
sender's side (and `op read` for Ryan's own tests), and rotate it if it
leaks ([Rotating the secret](#rotating-the-secret)).

### How Hermes handles it (v0.22.6)

From `gateway/platforms/webhook.py` and `gateway/config_env.py`:

- `WEBHOOK_ENABLED=true` in the env enables the platform; `WEBHOOK_PORT`
  and `WEBHOOK_SECRET` become `platforms.webhook.extra.port` and
  `.secret`. The listener binds every interface.
- **The secret stays out of config.yaml.** The route has no `secret` of
  its own, so Hermes uses the global one (`route.get("secret",
  self._global_secret)`) from `WEBHOOK_SECRET`. A route with no usable
  secret fails startup, and `INSECURE_NO_AUTH` is never used.
- **Signature: generic HMAC V2.** `X-Webhook-Signature-V2` is the hex
  HMAC-SHA256 of `<timestamp>.<raw body>` with the secret, and
  `X-Webhook-Timestamp` is Unix seconds within ±300 s. A V2 header never
  falls back to the replayable body-only V1. Bad or missing signature:
  `401`.
- **Filters:** `subject` and `body` must exist in the JSON body. Anything
  else is answered `200 {"status": "ignored", "reason": "filter"}` and no
  turn runs.
- **Idempotency: send `webhook-id`, not `X-Request-ID`.** Hermes takes
  the delivery id from the first of `X-GitHub-Delivery`, `svix-id`,
  `webhook-id` and `X-Request-ID` (`_header_delivery_id`), else a random
  one. Envoy replaces a client's `X-Request-ID` with its own UUID at the
  edge (no ClientTrafficPolicy here preserves it), so through the gateway
  that header never dedupes. `webhook-id` passes through unchanged, and on
  its own it does not switch Hermes to Svix/Standard Webhooks signing;
  only a `webhook-signature` header would. A repeat of an admitted id gets
  `200 {"status": "duplicate"}` and no second turn. Send a fresh
  `webhook-id` per message, and the same one on retries. The id is not
  covered by the signature.
- **One session per delivery**, keyed on route and delivery id, so a
  webhook turn never continues the Matrix DM's session.
- Rate limit 30/min per route, body cap 1 MB (Hermes defaults).

### The route

The init container writes `platforms.webhook.extra.routes.chief-engineer`
with Hermes' own `read_raw_config`/`save_config`, so the rest of
config.yaml stays Hermes-managed. It writes the route only when the input
is on, the Secret's `WEBHOOK_SECRET` reached the init container (the same
optional `envFrom` as `api-server` and `hindsight`) and
`WEBHOOK_DELIVER_CHAT_ID` is set; otherwise it removes it. A missing
1Password field therefore means no Secret, no listener and no route
(envoy answers `503`), not a gateway that fails to start. A missing room
ID leaves the listener up with no route (`404`).

- `prompt`: names the sender, states that the message is a request and
  not Ryan's approval, and passes `{subject}`, `{priority}` and `{body}`.
- `deliver: matrix`, `deliver_extra.chat_id`: `WEBHOOK_DELIVER_CHAT_ID`.
- `mirror_to_session: true`.
- `filters`: `subject` and `body` exist.
- `toolsets` (below).

### Tools on a webhook turn

The default `hermes-webhook` toolset is `_HERMES_WEBHOOK_SAFE_TOOLS`:
`web_search`, `web_extract`, `vision_analyze` and `clarify`. That is too
little to look into a homelab question. Hermes also adds every enabled MCP
server to it (`_merge_mcp_servers`), so on Chief the default would include
the **Outlook** server.

The route's `toolsets` replaces it with Chief's Matrix toolset minus
everything that reaches people or services outside Matrix:

| Kept | Dropped, and why |
| --- | --- |
| `terminal`, `file`, `code_execution` (in the screen pod, as on Matrix) | `no_mcp`: no Outlook, so no mail |
| `web`, `vision`, `image_gen`, `tts` | `browser`, `computer_use`: they can submit forms and fill saved logins and cards (`browser_vault`) |
| `memory`, `session_search`, `skills`, `todo`, `clarify` | `connections`: hosted connectors (Gmail, Notion, …) and account authorization |
| | `cronjob`: a scheduled job runs later, unattended, and delivers anywhere |
| | `delegation`: a subagent's toolset was not checked |

The resolved set was checked in Chief's pod with Hermes' own
`_get_platform_tools`: all twelve kept toolsets survive the webhook
platform's filtering, and no MCP server is added.

**Approvals deny.** Webhook sessions are unattended
(`tools/approval_context.py`), and Chief's `approvals.unattended_mode` is
`deny`. A command that would ask for approval on Matrix is refused during
a webhook turn, so Chief can only propose it. Ryan approves by replying
in the DM, where it runs as a normal Matrix turn.

### Request, not approval

A webhook message is a request from another bot, never Ryan's approval.
Anything that sends, posts, spends, deletes, or changes systems needs
Ryan's explicit yes in the Matrix DM. The prompt says so on every
delivery, and the toolset and approval mode above enforce most of it. The
`terminal` tool can still reach the internet from the screen pod, as it
can on Matrix.

### Payload

```json
{
  "subject": "Disk on forge at 91%",
  "body": "tank/services grew 40 GB overnight. Can you find what grew?",
  "priority": "normal",
  "sender": "chief-engineer"
}
```

`subject` and `body` are required. `priority` is shown as written (a
missing one renders as `{priority}`). `sender` is informational: the
signature, not the field, is what identifies Chief Engineer.

### Turning it on for a bot

1. In 1Password vault `k8s-secrets`, item `hermes-<bot>`, add field
   `webhook_secret` with a strong secret, e.g. `openssl rand -hex 32`.
   Never commit it. Give the sender the same value.
2. Add `WEBHOOK_ENABLED=true` and `WEBHOOK_DELIVER_CHAT_ID=<room id>` to
   the bot's inputs. The room ID is Ryan's DM with the bot: the
   `matrix:dm` entry in `/opt/data/sessions/sessions.json`, or the bot's
   `joined_rooms` whose members are the bot and Ryan.

### Signing a request

The secret is read into a variable and never written to disk:

```bash
secret=$(op read "op://k8s-secrets/hermes-chief/webhook_secret")
body='{"subject":"Test","body":"Reply with the date.","priority":"low","sender":"chief-engineer"}'
ts=$(date +%s)
sig=$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$secret" | sed 's/^.* //')
curl -sS https://chief-hooks.<internal domain>/webhooks/chief-engineer \
  -H 'Content-Type: application/json' \
  -H "X-Webhook-Timestamp: $ts" \
  -H "X-Webhook-Signature-V2: $sig" \
  -H "webhook-id: $(uuidgen)" \
  --data-binary "$body"
unset secret
```

Sign exactly the bytes sent (`--data-binary`, not `-d`, which can change
them). Expect `202 {"status": "accepted", ...}`.

### Rotating the secret

Change `webhook_secret` in 1Password and give the sender the new value.
External Secrets picks it up within the 1h refresh, or at once with:

```sh
kubectl -n hermes-<bot> annotate externalsecret webhook force-sync="$(date +%s)" --overwrite
```

Reloader restarts the agent when Secret `webhook` changes, and requests
signed with the old secret get `401`. The init container strips any
`^WEBHOOK_SECRET=`, `^WEBHOOK_ENABLED=` or `^WEBHOOK_PORT=` line from
`/opt/data/.env` when the Secret is present, for the reason in [Why the
init container cleans `.env`](#why-the-init-container-cleans-env): Hermes
loads `.env` with `override=True`, so a stale line would beat the Secret.

## Web search (opt-in)

`web_search` and `web_extract` through [Tavily](https://tavily.com).
Before this, no web backend was configured and the agent could not reach
the internet, so both tools failed.

**Off by default.** A bot turns it on with `TAVILY_ENABLED=true` in its
inputs; today only Chief does. When it is on, the component adds:

| Object | What |
| --- | --- |
| ExternalSecret / Secret `tavily` | `TAVILY_API_KEY` from 1Password item `hermes-<bot>`, field `tavily_api_key` |
| Optional `envFrom: tavily` | The agent's `app` container only. The web tools run in the gateway process; the screen pod never gets the key |
| config.yaml, set by the `config` init container | `web.backend: tavily` and `web.keyless_fallback: false` |
| CiliumNetworkPolicy `agent-tavily` | Agent egress to `api.tavily.com` on TCP 443 only, plus the L7 DNS rule `toFQDNs` needs |

`TAVILY_BASE_URL` is unset, so requests go to `https://api.tavily.com`.

### Strict backend, no fallback

From Hermes v0.22.6 (`tools/web_tools.py`, `agent/web_search_registry.py`,
`plugins/web/keyless_mcp.py`, `plugins/web/tavily/provider.py`):

- A stored `web.backend` is used as-is: no availability probe, no switch
  to another provider. Search and extract both resolve to `tavily`.
- `web.keyless_fallback: false` turns off the three keyless paths:
  - the anonymous free-tier ring (Exa, Parallel, Firecrawl, Keenable);
  - the one-shot "keyless rescue" retry of a failed call on that ring;
  - Tavily's own keyless mode, which its `auto` tier uses when no key is
    set.
- So **without the key** (field missing, ExternalSecret unready, Secret
  never created) the bot still starts, and both tools return
  `TAVILY_API_KEY is not set`. Nothing else is tried, and nothing could
  get out anyway: the agent may reach only `api.tavily.com`.
- A Tavily error (rate limit, plan limit, outage) reaches the model as the
  error text, with no retry elsewhere.

### No LLM in `web_extract`

In v0.22.6 `web_extract` returns clean page content with **no LLM
summarization** (`tools/web_tools.py`: "Extract clean page content (no
LLM)"). Pages over `web.extract_char_limit` (15000) come back head and
tail, with the full text saved to disk for `read_file`.
`hermes_cli/config_defaults.py` says leftover `auxiliary.web_extract`
blocks are ignored, so none is written. The bot's own model, through
LiteLLM, reads the result like any other tool output. No auxiliary call
can go to OpenRouter or Nous: the agent has no route to them, and other
auxiliary tasks with provider `auto` inherit the main model.

### Turning it on for a bot

1. In 1Password vault `k8s-secrets`, item `hermes-<bot>`, add field
   `tavily_api_key` with the bot's Tavily API key (app.tavily.com). Never
   commit it.
2. Add `TAVILY_ENABLED=true` to the bot's inputs.

### Rotating the key

Create a new key in Tavily, put it in `tavily_api_key`, then revoke the
old one. External Secrets picks it up within the 1h refresh, or at once
with:

```sh
kubectl -n hermes-<bot> annotate externalsecret tavily force-sync="$(date +%s)" --overwrite
```

Reloader restarts the agent when Secret `tavily` changes.

### Turning it off

Remove `TAVILY_ENABLED=true` from the bot's inputs (or set `false`).
Flux removes the ExternalSecret, Secret and policy. On the next boot the
init container unsets `web.backend` if it is still `tavily`.
`web.keyless_fallback` stays `false`, so the bot has no web search at
all rather than silently using the keyless ring, which its egress would
block anyway. Delete the 1Password field if the key is no longer used.

## Outlook (opt-in)

An Outlook (Microsoft 365) MCP server for a bot, against Ryan's own M365
tenant: read and search mail, drafts, send, move. **Off by default**: a
bot turns it on with `OUTLOOK_MCP_ENABLED=true`. Today only Chief does.

### What runs where

- **Server and pin.** [Softeria/ms-365-mcp-server](https://github.com/Softeria/ms-365-mcp-server)
  **0.178.0**, baked into `ghcr.io/carpenike/hermes-agent`
  (`images/hermes-agent`). That image is upstream
  `nousresearch/hermes-agent` v0.22.6 by digest, plus the server installed
  by `npm ci` from a vendored `package-lock.json`, without optional
  dependencies or install scripts. Nothing is fetched at runtime. Every
  bot uses this image; the server only runs for a bot that turns it on.
- **Process.** Hermes spawns it over stdio, in the agent pod only. The
  screen pod renders identically with it on or off: no ids, no tokens, no
  egress.
- **Config.** The `config` init container runs `hermes-outlook-config
  enable|disable` on every boot. `enable` writes `mcp_servers.outlook`:

  | Key | Value |
  | --- | --- |
  | `command` | `/usr/local/bin/outlook-mcp` (the wrapper below) |
  | `args` | `--enabled-tools-file /opt/outlook-mcp/enabled-tools.txt --allowed-scopes 'User.Read Mail.ReadWrite Mail.Send'` |
  | `trust` | `untrusted`: every tool without `readOnlyHint` asks first |
  | `tools.include` | the same allowlist; `resources`, `prompts` and `sampling` off |
  | `env` | `MS365_MCP_CLIENT_ID`, `_TENANT_ID` and `_EXPECTED_USERNAME` from the gateway env (Secret `outlook-mcp`); `MS365_MCP_TOKEN_CACHE_PATH` and `_SELECTED_ACCOUNT_PATH` under `/opt/data/outlook/`; `MS365_MCP_LOG_DIR=/var/log/outlook-mcp` (emptyDir); `MS365_MCP_REQUIRE_CONFIRM=true`; `MS365_MCP_USE_KEYTAR=false` |

  Hermes passes the child only that `env` plus its safe baseline
  (`tools/mcp_tool_config.py`, `_build_safe_env`), so the Matrix and
  LiteLLM keys never reach it.
- **Secret `outlook-mcp`** (ExternalSecret, gated): 1Password item
  `hermes-<bot>`, fields `outlook_client_id` and `outlook_tenant_id`, plus
  `OUTLOOK_MCP_EXPECTED_USERNAME` from the inputs.
- **Egress.** CNP `agent-outlook` lets the agent reach
  `login.microsoftonline.com` and `graph.microsoft.com` on 443
  (`toFQDNs`) and nothing else new. Its L7 DNS rule lets Cilium's DNS
  proxy see the agent's lookups. This is the repo's first FQDN policy.

**The wrapper** (`images/hermes-agent/outlook-mcp/outlook-mcp`) fails
closed. It refuses to start when:

- the client id is missing or is Softeria's shared default app (the
  server would otherwise fall back to it, `src/secrets.ts`);
- the tenant is missing or is `common`, `organizations` or `consumers`;
- the expected username is missing or still `REPLACE_*`;
- any flag would widen the server: org, work or app mode, HTTP,
  discovery, presets, extra scopes, or a different tool filter or scope
  list.

It also unsets client-secret, certificate, managed-identity and
`MS365_MCP_ORG_MODE` variables, and always passes the baked filter and
scope list, so `--login` asks for exactly what the server uses.

### Tools

`images/hermes-agent/outlook-mcp/enabled-tools.txt` (anchored regexes,
names from `src/endpoints.json` at v0.178.0), mirrored by
`tools.include`:

| Read (no approval) | Write (approval every time) |
| --- | --- |
| `list-mail-messages` (its `search` parameter is search), `list-mail-folder-messages`, `get-mail-message`, `list-mail-folders`, `list-mail-child-folders`, `list-mail-attachments`, `get-mail-attachment-content` | `create-draft-email`, `create-reply-draft`, `send-mail`, `move-mail-message` |

There is no mark-read tool in 0.178.0. Marking read would mean
`update-mail-message`, a general `PATCH` on the message, so it is
excluded. Also excluded:

- every `delete-*`, mail rules, mailbox settings and shared mailboxes;
- calendar, contacts, OneDrive, Teams and SharePoint;
- `send-draft-message`, so a draft can't be sent from the bot; Ryan
  sends it from Outlook;
- `reply-*` and `forward-*`, which send at once;
- `download-bytes`.

In stdio mode the server also registers its own auth tools (`login`,
`logout`, `verify-login`, `list-accounts`, `select-account`,
`remove-account`). `--enabled-tools` doesn't cover them
(`src/server.ts`), so `tools.include` is what keeps them away from the
model.

`--list-permissions` on the pinned build with this filter reports
effective permissions `Mail.ReadWrite` and `Mail.Send`, with `User.Read`
allowed but unused by the tools. `--login` requests those two; MSAL adds
`openid`, `profile` and `offline_access`. The login check calls
`GET /me`, which needs `User.Read`: hence the admin consent below.

**Not on the API server.** Hermes adds every enabled MCP server to every
platform (`hermes_cli/tools_config.py`, `_merge_mcp_servers`).
`hermes-outlook-config` therefore sets `platform_toolsets.api_server` to
`hermes-api-server` plus `no_mcp`. Otherwise anyone with the API key
could read the mailbox without approval, and `/v1/runs` callers answer
their own approval prompts.

### Approvals: what Ryan sees, and when nobody can answer

From Hermes v0.22.6, `tools/mcp_tool_handlers.py` (`_trust_gate_check`,
`_ask_for_call`, `_format_trust_gate_arguments`) and
`tools/approval_prompt.py` (`request_elicitation_consent`).

**The prompt** for a write tool such as `send-mail`, in the Matrix room:

- the text "MCP tool 'send-mail' on UNTRUSTED server 'outlook' wants to
  run … This tool is write-capable …";
- then **"Arguments:"**: the call's arguments as JSON. For `send-mail`
  that is `body` (the whole message: `subject`, `body.content`,
  `toRecipients`, `ccRecipients`…) and `confirm`;
- choices once, this session, always, or deny.

Things that can hide the details:

- Credential-named fields are masked and secret-shaped strings redacted.
  Email addresses are not redacted.
- The JSON is **cut at 1,200 characters** ("… [arguments truncated]"),
  in whatever order the model wrote the keys. With a long body the
  recipients can fall past the cut. **If the card says truncated and you
  can't see `toRecipients`, deny.**

**No human to approve** (a cron job, `hermes chat -q`, or an API request
without a live approval callback): the prompt fails closed with
"decline", and the tool returns "The user did not approve … The command
was NOT run". A gateway session with no notifier also declines. A prompt
nobody answers before the timeout counts as cancelled.

**Never answer "Always" for `send-mail`.**

- "Always" is stored in `command_allowlist` in `config.yaml` as
  `mcp:outlook/send-mail`. Hermes checks that list process-wide
  (`tools/approval.py`, `is_approved`), so after one "Always" every later
  send skips the prompt, cron jobs included.
- `hermes-outlook-config` deletes every `mcp:outlook/*` entry on each
  boot, so a slip lasts until the next restart. A restart is the fix:
  `kubectl -n hermes-<bot> rollout restart deploy/hermes-agent`.
- "Session" is per chat and safe enough for a batch of drafts.
- `/yolo` and `approvals.mode: off` bypass the prompt too; don't use them
  on a bot with Outlook.

`MS365_MCP_REQUIRE_CONFIRM=true` adds a second check in the server: a
`send-mail`, draft or move call must carry `confirm: true`, which is
visible in the prompt.

### Entra app (once, in Ryan's tenant)

1. Entra admin center → App registrations → New registration:
   - name `hermes-<bot>-outlook`;
   - **accounts in this organizational directory only** (single tenant);
   - no redirect URI.
2. Authentication → Advanced settings → **Allow public client flows:
   Yes** (device code). Add no client secret or certificate.
3. API permissions → Microsoft Graph → **Delegated**: `User.Read`,
   `Mail.ReadWrite`, `Mail.Send`, `offline_access`. Remove anything else.
   Then **Grant admin consent** for the tenant.
4. Copy the Application (client) ID and Directory (tenant) ID into
   1Password item `hermes-<bot>` (vault `k8s-secrets`), fields
   `outlook_client_id` and `outlook_tenant_id`.
5. Set `OUTLOOK_MCP_EXPECTED_USERNAME` in the bot's inputs.

### One-time login

The token cache starts empty. Until a login, the server refuses to start
("Expected Microsoft account … not found in token cache", in
`/opt/data/logs/mcp-stderr.log`), and the bot simply has no Outlook
tools.

`kubectl exec` runs as the Hermes user (uid 10000, `HOME=/opt/data`)
with the agent container's environment, including Secret `outlook-mcp`.
The wrapper adds the same paths and filter Hermes uses:

```sh
kubectl -n hermes-<bot> exec -it deploy/hermes-agent -c app -- outlook-mcp --login
```

It prints a code. Open https://microsoft.com/devicelogin on any device,
enter it, and sign in as the expected account. The command ends with
`{"success":true,…}`. Then restart, so the gateway reconnects at once:

```sh
kubectl -n hermes-<bot> rollout restart deploy/hermes-agent
kubectl -n hermes-<bot> exec deploy/hermes-agent -c app -- outlook-mcp --verify-login
```

**Log in again** after:

- about 90 days without use (the refresh token's inactivity limit);
- a password change, or a sign-in policy change that revokes sessions;
- an admin revokes the user's sessions or the app's consent;
- `--logout`, or deleting `/opt/data/outlook/`.

`--verify-login` shows whether it's still good.

### Backups hold a mailbox credential

`/opt/data/outlook/` holds the MSAL token cache: a refresh token for the
mailbox, with `Mail.ReadWrite` and `Mail.Send`. Its encryption key
(`.cache-key`) sits beside it (`src/token-cache-storage.ts`). Both are on
`agent-data`, so every nightly R2 backup, and any restore, carries a
working mailbox credential until it expires or is revoked.

To kill it, revoke the user's sessions in Entra (or remove the app's
consent), then run `outlook-mcp --logout`.

### Upgrades and the pin

The server version is pinned in `images/hermes-agent/outlook-mcp/package.json`
and locked with integrity hashes in `package-lock.json`. The Hermes base
is pinned by digest in the `Dockerfile`, and the HelmRelease pins the
built image by digest. To upgrade:

1. Bump the version, then regenerate the lockfile without running
   scripts:

   ```sh
   cd images/hermes-agent/outlook-mcp && npm install --package-lock-only --ignore-scripts
   ```

2. Read the release notes and diff `src/endpoints.json`, `src/cli.ts`
   and `src/auth-tools.ts` against the old tag. Look for renamed tools,
   new auth tools, new flags or env vars the wrapper should refuse, and
   default changes, especially the client id and confirm behaviour.
3. Update `enabled-tools.txt` and `tools.include` together.
4. Rebuild with `hermes-agent-image.yaml`, run `outlook-mcp
   --list-permissions` against the new build, and check the scopes
   haven't grown.
5. Pin the new digest.

Don't take an upgrade only because it exists. The pin moves when a fix or
a needed tool lands.

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
