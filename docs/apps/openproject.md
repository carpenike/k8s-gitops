# OpenProject

OpenProject Community Edition 17.9.6 is the shared task board for Ryan and
the bots: Chief posts a task, tells Hank over A2A to pick it up, and Hank
comments and closes it there (docs/apps/hermes.md, A2A). It replaces the Forge
install that was never put into use (nix-config).

| | |
| --- | --- |
| Manifests | `kubernetes/apps/openproject/` |
| Chart | `oci://ghcr.io/opf/helm-charts/openproject` 13.17.1, image `openproject/openproject:17.9.6-slim` by digest |
| URL | `https://tasks.<internal domain>`, envoy-internal only (LAN and VPN) |
| In-cluster API | `http://openproject.openproject.svc.cluster.local:8080/api/v3` |
| Database | `openproject` on postgres17, role `openproject` |
| Cache | memcached (`memcached.openproject.svc`), official image |
| Attachments | PVC `openproject`, ceph-filesystem, RWX, 10 GiB |
| Backups | Database: postgres17's backups. Attachments: VolSync restic to R2 (`openproject`), nightly, from a CephFS snapshot |
| 1Password | item `openproject` in `k8s-secrets`: `database_password`, `secret_key_base`, `admin_password`, and the board webhook's `webhook_secret` and `bot_webhook_secret`; item `chief-engineer`: `routine_url`, `routine_key` and `openproject_api_token` ([Bots outside the cluster](#bots-outside-the-cluster)) |

## Layout

- **Web** (puma) and **one GoodJob worker**, which also runs OpenProject's
  scheduled jobs. Both mount the attachments volume, hence RWX.
- **Seeder Job**: the chart runs it for each revision. It migrates the
  database and seeds a new install.
- **Not deployed:**
  - the bundled Bitnami postgresql and memcached (frozen
    `bitnamilegacy` images);
  - hocuspocus, so real-time co-editing of documents is off;
  - the bundled RustFS S3 server;
  - the chart's Ingress (an HTTPRoute instead);
  - the IMAP `cron` Deployment for incoming mail. The chart renders it even
    with `cron.enabled: false`, so the HelmRelease deletes it with a
    post-renderer.

## Database

The `openproject` Database on postgres17 installs `btree_gist`, `pg_trgm`
and `unaccent` in **`pg_catalog`**, not `public`. The image's SQL
structure load clears `search_path` and names operator classes such as
`gin_trgm_ops` without a schema. With the extensions in `public`, the first
schema load fails even though they exist. Forge learned this first.

The role password is 1Password field `database_password`, read by both
`cnpg-system` (the managed role) and `openproject` (the app).

## Sign-in

- **Ryan.** One login, OpenProject's own account with 2FA. The route is
  labelled `gateway.holthome.net/auth: app`, so the gateway's Pocket ID
  login is off for it ([gateway-auth.md](../platform/gateway-auth.md), "One login per
  route"). Pocket ID can't be that login:
  - OpenID Connect and SAML are Enterprise add-ons. In 17.9.6,
    `auth_plugin.rb` drops every SSO provider without an Enterprise token,
    including ones configured from the environment.
  - Header sign-in (`auth_source_sso`, Community) finds the user with
    `LdapAuthSource.find_user`, a real LDAP query. It needs an LDAP
    directory, which Pocket ID isn't.

  The first admin is seeded from `admin_password` and must change it at
  first sign-in. Turn on 2FA for it.
- **Bots** use API tokens against the in-cluster Service and never reach
  the gateway. `OPENPROJECT_ADDITIONAL__HOST__NAMES` admits that Service
  name. HSTS is off, as on Forge, so the bots' `http://` calls aren't
  redirected to https (Envoy terminates TLS for browsers).
- **Self-registration is off.** Ryan creates people and bot users.

## First start

```sh
kubectl -n openproject get pods
kubectl -n openproject logs job/openproject-seeder-1 | tail
kubectl -n cnpg-system get database openproject -o jsonpath='{.status.applied}{"\n"}'
```

Then open `https://tasks.<internal domain>`, sign in as `admin`, change
the password, and turn on 2FA.

## Bot access

Chief and Hank use the board through **openproject-mcp**
(`images/openproject-mcp`, Kustomization `openproject-mcp` in this
namespace), a small streamable-HTTP MCP server. OpenProject's own MCP
server is an Enterprise add-on (17.2 release notes), and the community
`openproject-ce-mcp` is stdio-only. The tools are ported from homelab-mcp's
OpenProject toolset on Forge (`carpenike/mcp`, `docs/OPENPROJECT.md`).

| | |
| --- | --- |
| Endpoint | `http://openproject-mcp.openproject.svc.cluster.local:8000/mcp`, in the cluster only |
| Who may connect | Hermes agent pods in bot namespaces (CNP `openproject-mcp`; the agent side is the component's `agent-task-board`), and OpenProject's own pods for the webhook relay ([Waking a bot](#waking-a-bot)) |
| Auth | Each request carries the bot's own OpenProject API token as `Authorization: Bearer`, and every OpenProject call is made as that bot. The server holds no OpenProject credentials; its only secrets are the relay's two HMAC keys |
| Tools | `whoami`, `list_tasks`, `get_task`, `create_task`, `add_comment`, `claim_next`, `complete_task`, `release_task`. Hermes names them `mcp__openproject__<tool>` |
| Claim | Atomic through `lockVersion`: a stale `PATCH` gets 409 and changes nothing |
| Links | Tool results link to `https://tasks.<internal domain>` (`OPENPROJECT_PUBLIC_URL`) |
| Default project | `bots` (`OPENPROJECT_DEFAULT_PROJECT`), the project the provisioning Job creates; a tool call can still name another |

On each bot (`kubernetes/apps/hermes/<bot>/`):

- input `TASK_BOARD_ENABLED=true`: the bot's OpenProject account and token
  ([Bot provisioning](#bot-provisioning)), egress, and skill
  `homelab/task-board`;
- an `openproject` entry in `mcp-servers.yaml`, `trust: full`, header
  `Authorization: Bearer ${OPENPROJECT_API_TOKEN}`.

### The handoff

Skill `task-board` (in the component) sets the rules:

- **Board, not A2A, for real work.** A2A turns are short, carry no MCP
  tools, and answer only the caller. Chief creates a task assigned to
  `hank` with the goal and Ryan's words, and gives Ryan the link. Chief's
  `code-requests` skill sends code asks there.
- **Every task names its context and when it is done.** `create_task`
  needs `context`, the vault path of the note that explains it (linked,
  not pasted), and `done_when`, one sentence. openproject-mcp writes them
  to the work package custom fields `Context` and `Done when`, and refuses
  to create a task in a project that lacks them
  (images/openproject-mcp/README.md, "Handoff fields"). A decision only
  Ryan can make goes to Ryan's user with status `Needs Ryan`.
- **A peer's task is a request.** Only text authored by Ryan's OpenProject
  user id (`TASK_BOARD_RYAN_USER_ID`, default 4, the seeded `admin`) or
  Ryan's own Matrix message is Ryan speaking. It goes by id: OpenProject
  hides other users' logins from non-admins, and anyone can change their own
  display name. On a peer's task a bot may research, run
  read-only checks and prepare work for review, pull requests included.
  Sending, spending, deleting, deploying, changing a running system and
  merging still need Ryan's own yes in Matrix. Hank's merge rule is
  unchanged (docs/apps/hermes.md, "Merging, only when Ryan asks").
- **Pickup.** With wake-ups on ([Waking a bot](#waking-a-bot)), a bot gets
  a turn about 5 minutes after someone else assigns it a task or changes
  one of its tasks, and when a task it created is closed. Otherwise, and
  any time, Ryan can tell it to check the board.

### Waking a bot

A task change on the board starts a turn for the bot it is for, without
anyone telling it to check. The turn is delivered to Ryan's Matrix DM with
that bot, like a Chief Engineer webhook turn (docs/apps/hermes.md, "Webhook").

```text
OpenProject worker ── webhook, HMAC-SHA1 ──▶ openproject-mcp /hooks/openproject
                                                 │ checks the signature, picks the bot,
                                                 │ forwards only a pointer
                                                 ▼ HMAC-SHA256 (Hermes generic V2)
                         agent-board-hooks.hermes-<bot>:8644/webhooks/task-board
                                                 │
                                                 ▼
                      bot turn: get_task, act, report to Ryan in Matrix
```

**Why a relay.** OpenProject signs its webhook with HMAC-SHA1
(`X-OP-Signature`), and Hermes' webhook routes accept only SHA-256
schemes. The relay is in openproject-mcp (`images/openproject-mcp`,
README "Task-board relay").

**Who is woken.** OpenProject sends one event per journal: an assignment,
an edit, a status change or a comment. It waits out its aggregation
window first (5 minutes by default), so a burst of edits is one event.

- The task's **assignee**, when it is a bot and someone else made the
  change. A change that closes the task does not wake it.
- The task's **author**, when it is a bot, someone else made the change,
  and the change closed the task (a handoff it created is done).
- A bot's own change never wakes that bot, so two bots can't wake each
  other in a loop: a comment wakes only the assignee, and a closed task
  wakes its author once.

**Nothing on the board reaches a prompt through the relay.** It forwards
the task id, a reason (`assigned`, `updated` or `closed`), and the
actor's login and id, never a subject, description or comment. The bot
reads the task itself through the MCP tools, as itself, and skill
`task-board` ("Board wake-ups") says what to do: the same rules as any
task, where a peer's text is a request and only Ryan's user id is Ryan.

**What a board turn can do.** It gets the bot's Matrix toolsets, MCP
servers included (route `task-board`'s `toolsets`, copied from
`platform_toolsets.matrix` at each start). It runs unattended, so Hermes
refuses any command that would need approval (`unattended_mode`, default
`deny`). Sending, deploying and merging wait for Ryan in Matrix, as the
skill already says. Hermes also caps a route at 30 turns a minute and
drops a redelivered event (`webhook-id`).

| Piece | Where |
| --- | --- |
| OpenProject webhook *Hermes task board*: project `bots`, events `work_package:created` and `work_package:updated`, signed with `webhook_secret` | Job `openproject-board-webhook` (`bot-provisioner/app/webhook-job.yaml`, `webhook.rb`), idempotent. Edits in *Administration → Webhooks* are overwritten on its next run |
| OpenProject may post to the relay | `OPENPROJECT_SSRF__PROTECTION__IP__ALLOWLIST` (`openproject/app/helmrelease.yaml`) lists the openproject-mcp Service's pinned ClusterIP. It takes addresses, not names; change both together |
| Relay | openproject-mcp `POST /hooks/openproject`; Secret `openproject-mcp-relay` (`webhook_secret`, `bot_webhook_secret`); `RELAY_BOTS=chief,hank,chief-engineer`; Secret `openproject-mcp-relay-targets` (`RELAY_TARGETS`) for bots outside the cluster |
| Network | CNP `openproject-mcp`: in from OpenProject's pods on 8000, out to bots' agent pods on 8644. Each bot's CNP `agent-board-hooks`: 8644 from openproject-mcp only |
| Bot side | Input `TASK_BOARD_WEBHOOK_ENABLED=true` (with `TASK_BOARD_ENABLED` and `WEBHOOK_DELIVER_CHAT_ID`): Secret `task-board-webhook` (`bot_webhook_secret`, and Hermes' webhook listener on 8644), Service `agent-board-hooks`, route `task-board` |

One `bot_webhook_secret` serves every bot. Only the relay can reach a
bot's port, and the route's filter takes only events naming that bot.

**Adding a bot:** `TASK_BOARD_WEBHOOK_ENABLED=true` and its
`WEBHOOK_DELIVER_CHAT_ID` in its inputs, and its login in `RELAY_BOTS`.
The agent pod can start a moment before Secret `task-board-webhook`
exists. Reloader then restarts it once the Secret is created
(`reloadOnCreate`, `kube-system/reloader`), and the next start writes
the route.

**Rotating a key:** change the field in 1Password. For `webhook_secret`,
also bump `script-revision` in `webhook-job.yaml` so the Job stores the
new key in OpenProject. The ExternalSecrets refresh every 12 hours, and
Reloader restarts openproject-mcp.

**Check it:**

```sh
kubectl -n openproject logs job/openproject-board-webhook
kubectl -n openproject logs deploy/openproject-mcp | grep relay
kubectl -n hermes-<bot> logs deploy/hermes-agent -c config | grep 'route task-board'
```

OpenProject's own log of each delivery and the relay's answer is under
*Administration → API and webhooks → Webhooks → Hermes task board*.

**After a relay restart**, the first event on an already closed task
counts as its close: the author may hear about that task once more.

### Bots outside the cluster

**Chief Engineer**, Ryan's homelab assistant on Grok Bot, is a board user
like Chief and Hank: login `chief-engineer`, a *Member* of `bots`, never an
admin. It isn't a Hermes bot, so it reaches the board and is woken a
different way.

- **Account.** Flux Kustomization `external-bot-chief-engineer`
  (`bot-provisioner/external-bots.yaml`) runs the same `provision.rb` with
  `BOT_EXTERNAL=true` (template `bot-provisioner/external`): user,
  membership, and an API token in Secret
  `openproject/openproject-bot-chief-engineer`. Nothing in the cluster
  reads that Secret. Ryan copies the token to 1Password (item
  `chief-engineer`, field `openproject_api_token`) and to Chief Engineer's
  machine.
- **Access.** Over Chief Engineer's own VPN into the LAN, to
  `https://tasks.<internal domain>/api/v3` on envoy-internal, with HTTP
  Basic `apikey:<token>`. Nothing is published to the internet. The route
  has OpenProject's own sign-in (`gateway.holthome.net/auth: app`), so the
  token works without the gateway login. If the VPN is narrowed, the board
  needs DNS and 443 to envoy-internal.
- **Wake-ups.** A Grok Bot routine with a webhook trigger: a POST to its
  URL with `Authorization: Bearer <key>` starts a run, and the result goes
  to the bot's chat. The relay sends `chief-engineer`'s events there
  (`RELAY_TARGETS`, from item `chief-engineer`, fields `routine_url` and
  `routine_key`), with the same pointer as a Hermes bot gets plus
  `task_url`. Egress: CNP `openproject-mcp`, `toFQDNs` the routine's
  host. Same rules as any bot: it is woken when someone else changes its
  task or closes one it created, never by its own changes. Grok runs
  routines at most 200 times an hour each.
- **What it knows.** [grok-board-guide.md](grok-board-guide.md): the
  guide for its instructions (API recipes, statuses, user ids, the trust
  rules of skill `task-board`) and the routine's instruction. Its tasks
  and comments are a peer's requests to Hank and Chief, never Ryan's.

**Setting it up** (Ryan):

1. In Grok, create a routine for Chief Engineer with a **webhook trigger**,
   and paste in the routine instruction from the guide. Its Webhook
   section shows the URL and the key. If the URL's host isn't
   `api2.cursor.sh`, change the `toFQDNs` rule in
   `openproject-mcp/app/ciliumnetworkpolicy.yaml`.
2. Create 1Password item `chief-engineer` in `k8s-secrets` with
   `routine_url` and `routine_key`.
3. After the merge, copy the token from Secret
   `openproject/openproject-bot-chief-engineer` to that item
   (`openproject_api_token`) and to Chief Engineer's machine.
4. Paste the guide into Chief Engineer's instructions, with the real
   domain.

**Another Grok bot:** another Kustomization in `external-bots.yaml`, its
login in `RELAY_BOTS`, and an entry in the `openproject-mcp-relay-targets`
template.

### Board structure

`bot-provisioner/app/board.yaml` is the board's shape, and Job
`openproject/openproject-board-structure` (`structure.rb`, OpenProject's own
Rails runner, no API token, no Kubernetes access) makes OpenProject match it.
The board ConfigMap has a hash suffix, so an edit to `board.yaml` replaces the
Job; bump the Job's `script-revision` annotation for an edit to `structure.rb`.

- **Projects:** Bots, Personal (one sub-project per approved vault domain:
  Fitness, Property, Tech, Family History, Finances, Health, Church and
  Education) and Work, all private. The seeded demo projects are archived
  (they were public, so every bot could see them).
- **Role Agent:** view, create, edit, comment, watch, relate and be assigned.
  No moving or copying items between projects, no deleting, no managing
  members or the project. Its workflows are Member's, plus every transition
  into and out of **Needs Ryan** (also for Member and Project admin).
- **Fields:** `Context` (a vault path) and `Done when` (one sentence) on every
  board project and type. `fields_required` turns them required, after the
  bots' servers send them (openproject-mcp 0.4.0, homelab-mcp 0.62.0).
- **Members:** each listed user on exactly its projects' subtrees as Agent,
  and removed from every other project. structure.rb creates a missing user
  (no token). Ryan (user 4) is Project admin of every board project and the
  assignee for Needs Ryan.
- **The rule:** external providers never get a role in Work. Grokbot is xAI;
  the Hermes bots call Azure, Anthropic and Tavily, not local models (checked
  2026-11-11), so they are external too.
- **Self-check:** the run ends by asking OpenProject what each member can
  see, and fails (rolling everything back) unless it is exactly that
  member's line. A public project or a stray membership fails it.

A new personal domain: add `{identifier: <name>, name: <Name>, parent:
personal}` here, and the matching domain in homelab-mcp's `vault-policy.yaml`.
Members listed with `personal` get it through the subtree.

Dry run, against the live board, rolled back:

```sh
kubectl -n openproject exec -i deploy/openproject-web -c openproject -- sh -c 'mkdir -p /tmp/board && cat > /tmp/board/structure.rb' < kubernetes/apps/openproject/bot-provisioner/app/structure.rb
kubectl -n openproject exec -i deploy/openproject-web -c openproject -- sh -c 'cat > /tmp/board/board.yaml' < kubernetes/apps/openproject/bot-provisioner/app/board.yaml
kubectl -n openproject exec deploy/openproject-web -c openproject -- sh -c 'cd /app && DRY_RUN=true BOARD_FILE=/tmp/board/board.yaml bundle exec rails runner /tmp/board/structure.rb'
```

### Bots through homelab-mcp

Claude and Grokbot can't reach the in-cluster API; they use homelab-mcp's
`openproject_*` tools, which act as one OpenProject user per connector
(`HOMELAB_MCP_OPENPROJECT_VIEW_BOTS`). `homelab-mcp-bots.yaml` runs
`provision.rb` with `BOT_TARGET=homelab-mcp` once per bot: it issues the
token into Secret `homelab-mcp/homelab-mcp-openproject-<bot>` (Role on that
one Secret for ServiceAccount `openproject/homelab-provision-<bot>`), which
homelab-mcp mounts at `HOMELAB_MCP_OPENPROJECT_TOKENS_DIR`. Nobody copies the
token, and it is never printed. The user and its memberships come from
structure.rb.

### Bot provisioning

Nothing to do by hand. Each bot's Flux Kustomization `task-board`
(`kubernetes/components/hermes-bot/task-board`) runs Job
`openproject/hermes-provision-<bot>`. It is the Matrix provisioner's shape
([matrix.md](matrix.md), "Provisioning a bot"):

- Flux creates an empty Secret `hermes-<bot>-openproject` in the bot's
  namespace (`ssa: IfNotPresent`), and a Role there with `get` and `patch`
  on that one name for ServiceAccount `openproject/hermes-provision-<bot>`.
- The Job runs `provision.rb`
  (`kubernetes/apps/openproject/bot-provisioner/app`) with `bundle exec
  rails runner` in OpenProject's own image and the seeder's environment,
  using OpenProject's services the way its seeder does. OpenProject's API
  can't do this: an admin can create users and memberships over API v3,
  but not another user's API token, and its OAuth application endpoints
  are read-only. So no admin token is needed, or stored.
- It refuses a Secret without the provisioner labels, and exits at once
  for a bot without `TASK_BOARD_ENABLED=true`.
- The bot's inputs reach it as one string, `BOT_INPUTS`
  (`task_board=<true|false> ryan_user_id=<id>`): `kustomize build` drops
  the quotes around a lone `"${VAR}"`, so a substituted `true` or `4`
  would become a YAML bool or int, which an env value can't be.
- It ensures user `<bot>` (active, never an admin; an admin account of
  that login is refused, not demoted), project **Bots** (`bots`), the bot
  as *Member* and Ryan (`TASK_BOARD_RYAN_USER_ID`) as *Project admin*.
- It keeps the token in the Secret while OpenProject still accepts it for
  that user. Otherwise it deletes its own earlier tokens for the bot
  (token name `hermes (k8s-gitops provisioner)`), creates one, and
  merge-patches `OPENPROJECT_API_TOKEN`, `OPENPROJECT_USER`,
  `OPENPROJECT_USER_ID` and `OPENPROJECT_PROJECT` into the Secret. The
  token is never printed.
- The agent reads the Secret with `envFrom` (optional). Reloader restarts
  the agent when the Job writes it.

The Kustomization is separate from the bot's `provision` on purpose:
nothing depends on it, so OpenProject being down never holds a bot's app.
Every bot gets the Job; it is a no-op without the input. To re-issue a
bot's token, clear `OPENPROJECT_API_TOKEN` in its Secret, or revoke the
token in OpenProject, and reconcile the bot's `task-board` Kustomization.
Removing a bot prunes its Secret and RBAC; its OpenProject user stays
(lock it under *Administration → Users*).

The Job's image is OpenProject's, pinned like the HelmRelease's
(`template/job.yaml`); bump them together.

Check a bot:

```sh
kubectl -n openproject logs job/hermes-provision-<bot>
kubectl -n hermes-<bot> logs deploy/hermes-agent -c config | grep 'mcp servers from git'
kubectl -n hermes-<bot> exec deploy/hermes-agent -c app -- hermes mcp test openproject
```
