# openproject-mcp

A small streamable-HTTP MCP server for the OpenProject Community Edition task
board that the Hermes bots share. OpenProject's own MCP server is
Enterprise-only, and the community `openproject-ce-mcp` speaks stdio only, so
this server runs in the cluster and Hermes connects to it by URL.

Built by `.github/workflows/openproject-mcp-image.yaml` and pushed as
`ghcr.io/carpenike/openproject-mcp`. Manifests pin the digest.

## Auth model

- The server holds **no OpenProject secret**.
- Every MCP request carries `Authorization: Bearer <OpenProject API token>`.
  A request to `/mcp` without a non-empty bearer token gets HTTP 401 before
  any MCP handling.
- Each OpenProject call made for that request uses that token, as OpenProject
  API key auth: HTTP Basic `apikey:<token>`.
- The caller is whoever `GET /api/v3/users/me` says the token belongs to. The
  answer is cached per sha256 of the token for 60 seconds (or less, if
  `OPENPROJECT_CACHE_SECONDS` is lower).
- OpenProject's memberships, roles and workflows are the permission boundary.
  The activity log shows which bot did what.
- Tokens and Basic headers never go into logs or tool results.

Each bot is its own non-admin OpenProject user, a member of the shared
project with a role that can view, add, edit, comment on and assign work
packages. In Hermes, each bot's MCP server entry sends its own token in the
header.

OpenProject shows a user's `login` only to that user and to holders of the
global *manage user* / *create user* permission. So:

- An assignee such as `hank` is resolved by searching the members of the
  target project (`/api/v3/principals`, filter `any_name_attribute`). That
  search matches logins server-side even when the login is hidden.
- A comment's `author_login` is the caller's own login, or a login this
  server has seen through `/users/me` (every bot that has called since the
  last restart), or the login `/users/{id}` shows. Otherwise it is null.
  `author_id` and `author` (display name) are always set.

## Endpoints

| Path | Auth | What |
|---|---|---|
| `POST /mcp` | Bearer | MCP over streamable HTTP. Stateless, with JSON responses. Serves both the 2025 `initialize` protocol and 2026-07-28 |
| `GET /healthz` | none | `{"status":"ok"}`. Does not call OpenProject |
| `POST /hooks/openproject` | OpenProject's `X-OP-Signature` | The task-board relay ([below](#task-board-relay)). 404 while it is off |
| `POST /hooks/alertmanager` | Bearer `ALERTMANAGER_HOOK_TOKEN` | The Alertmanager relay ([below](#alertmanager-relay)). 503 while it is off |

The container listens on `0.0.0.0:$PORT` (default 8000) as UID 65532. It runs
one uvicorn process and writes nothing outside `/tmp`, so
`readOnlyRootFilesystem` works.

Requests to `/mcp` must carry a `Host` that is in `ALLOWED_HOSTS`. This is
the MCP SDK's DNS-rebinding check. Other hosts get HTTP 421. The two
`/hooks/*` endpoints are not under that check, and authenticate themselves.

## Environment

None of these is a secret except the relays' keys, token and targets.

| Variable | Default | Meaning |
|---|---|---|
| `OPENPROJECT_URL` | `http://openproject.openproject.svc.cluster.local:8080` | Where API calls go (the in-cluster Service). A trailing `/api/v3` is tolerated |
| `OPENPROJECT_PUBLIC_URL` | *(= `OPENPROJECT_URL`)* | Base of human-facing links, such as a task's `url`, e.g. `https://tasks.example.com` |
| `OPENPROJECT_DEFAULT_PROJECT` | *(none)* | Project identifier or id used when a tool gets no `project`. With no default, list/claim cover every project the caller can see, and `create_task` needs `project` |
| `OPENPROJECT_READY_STATUSES` | `New` | Comma list of status names or ids that `claim_next` may take |
| `OPENPROJECT_IN_PROGRESS_STATUS` | `In progress` | Status a claim sets |
| `OPENPROJECT_DONE_STATUS` | `Closed` | Status `complete_task` sets |
| `OPENPROJECT_RELEASE_STATUS` | `New` | Status `release_task` resets to |
| `OPENPROJECT_CONTEXT_FIELD` | `Context` | Name of the work package custom field `create_task` writes `context` to (matched case-insensitively) |
| `OPENPROJECT_DONE_WHEN_FIELD` | `Done when` | Name of the custom field `create_task` writes `done_when` to |
| `OPENPROJECT_CLAIM_MAX_ATTEMPTS` | `5` | PATCH attempts per claim, and the retry bound for complete/release (1–20) |
| `OPENPROJECT_CACHE_SECONDS` | `600` | TTL for status/priority/type/project lookups (0 = off). Identity uses `min(60, this)` |
| `PORT` | `8000` | Listen port |
| `ALLOWED_HOSTS` | `openproject-mcp.openproject.svc.cluster.local:*,openproject-mcp.openproject.svc:*,openproject-mcp:*,localhost:*,127.0.0.1:*` | Comma list of allowed `Host` headers. `name:*` allows any port and also the bare `name`, so a Service on port 80 works |
| `LOG_LEVEL` | `INFO` | Python log level |
| `OPENPROJECT_WEBHOOK_SECRET` | *(none)* | **Secret.** The key OpenProject's webhook signs with. Relay only |
| `HERMES_WEBHOOK_SECRET` | *(none)* | **Secret.** The key the relay signs bot events with. Relay only |
| `RELAY_BOTS` | *(none)* | Comma list of the bots' OpenProject logins. Only these are ever woken |
| `RELAY_TARGETS` | *(none)* | **Secret.** JSON `{"<bot>": {"url": "https://…", "bearer": "<key>"}}`: bots outside the cluster, such as a Grok Bot routine's webhook trigger. A bad entry is logged (never its values) and ignored |
| `RELAY_HERMES_URL` | `http://agent-board-hooks.hermes-{bot}.svc.cluster.local:8644/webhooks/task-board` | Where a bot's event goes; `{bot}` is its login |
| `ALERTMANAGER_HOOK_TOKEN` | *(none)* | **Secret.** The bearer token Alertmanager sends. Alertmanager relay only; unset turns it off (503) |
| `ALERTS_BOT` | `hank` | The one bot that gets alerts |
| `ALERTS_HERMES_URL` | *(`RELAY_HERMES_URL` with the path `/webhooks/alerts`)* | Where alerts go; `{bot}` is `ALERTS_BOT` |

Status, priority and type names are resolved case-insensitively through the
API and cached. A numeric value is used as an id.

## Tools

Hermes prefixes each tool with the server name, e.g.
`mcp__openproject__claim_next`. Failures return
`{"error": {"code", "message", "hint"}}` and never raise. `project` is an
identifier or a numeric id.

| Tool | Read-only | Arguments | What it does |
|---|---|---|---|
| `whoami` | yes | — | id, login and name of the token's user; the default project |
| `claim_next` | no | `project?` | Atomically claim the next unassigned ready task (priority desc, due date asc, id asc). Sets the assignee to the caller and the status to In progress, with `lockVersion`. `claimed:false` is an answer, not an error |
| `complete_task` | no | `task_id`, `summary` | Set the done status (`lockVersion`, retried on 409), then post `summary` as a comment. The task must be assigned to the caller |
| `release_task` | no | `task_id`, `reason?` | Clear the assignee, reset the status, and post the optional reason. The task must be assigned to the caller |
| `list_tasks` | yes | `project?`, `status="open"`, `assignee="any"\|"unassigned"\|"me"`, `limit=25` | Tasks, newest-updated first, with `returned/total/truncated` |
| `get_task` | yes | `task_id`, `comments=5` | One slim task with its `context` and `done_when` (null when unset), and its newest comments: `{id, author, author_id, author_login, created_at, text}` |
| `add_comment` | no | `task_id`, `text` | Post a comment as the caller |
| `create_task` | no | `subject`, `context`, `done_when`, `project?`, `description?`, `type?`, `priority?`, `assignee?`, `due_date?`, `status?` | Create a task ([handoff fields](#handoff-fields)). `assignee` is `me`, a member's login or name, or a numeric user id |

### Claiming

OpenProject has no claim primitive. Instead, a `PATCH` with a stale
`lockVersion` gets **409** and writes nothing. When a claim gets a 409, it
re-reads the task. If the task is still unassigned and ready, it retries
with the fresh `lockVersion`; otherwise it skips the task. A 403 or 422
(the role or workflow refuses) skips the task with the reason. Two bots can
never both win one task. `complete_task` and `release_task` use the same
read, check, PATCH and retry loop.

The OpenProject workflow for the bots' role must allow `New → In progress`,
`In progress → Closed` and `In progress → New` (or whatever statuses are
configured).

### Handoff fields

Every task carries two work package custom fields: `Context`, the vault path
of the note that explains it, and `Done when`, one sentence. Once they are
required in OpenProject, a create without them fails, so `create_task` takes
both as required arguments:

1. A blank `context` or `done_when` is refused
   (`openproject_handoff_incomplete`) before any OpenProject call.
2. It POSTs `/projects/{id}/work_packages/form` with the task's type,
   priority, assignee and status, and finds the two fields in the form's
   schema by name (`OPENPROJECT_CONTEXT_FIELD`, `OPENPROJECT_DONE_WHEN_FIELD`).
   If either is missing it creates nothing (`openproject_fields_missing`).
3. It writes a `String` field as a plain string and a `Formattable` one as
   `{"raw": …}`.

`get_task` reads them back through the work package's own schema
(`_links.schema`, cached per token), and shows null when one is unset or the
schema cannot be read.

## Task-board relay

OpenProject can send a webhook when a work package changes, but it signs it
with HMAC-SHA1 (`X-OP-Signature: sha1=<hex>`), and a Hermes webhook route
accepts only SHA-256 schemes. `POST /hooks/openproject` sits between them
(`relay.py`):

1. It checks OpenProject's signature with `OPENPROJECT_WEBHOOK_SECRET`. A
   missing or wrong one gets 401.
2. It takes only `work_package:created` and `work_package:updated`. A comment
   arrives as an update, since OpenProject sends one event per journal.
3. It picks who to wake, by the `login`s OpenProject embeds (it renders the
   payload as its system user):
   - the **assignee**, if it is one of `RELAY_BOTS` and someone else made the
     change, unless the change closed the task;
   - the **author**, if it is one of `RELAY_BOTS`, someone else made the
     change, and the change closed the task.

   A bot's own change never wakes that bot, and an event without an `actor`
   wakes no one. "Closed the task" needs the previous status, which the
   relay keeps in memory per task. After a restart, the first event on a
   closed task counts as the close: at most one extra notice per task.
4. For each bot it posts `RELAY_HERMES_URL` a pointer only:
   `{"event_type": "task_board", "bot", "task_id", "reason": "assigned" |
   "updated" | "closed", "actor", "actor_id"}`. No subject, description or
   comment text goes through. It is signed with Hermes' generic V2 scheme
   (`X-Webhook-Signature-V2`, hex HMAC-SHA256 of `<timestamp>.<body>`, and
   `X-Webhook-Timestamp`) with `HERMES_WEBHOOK_SECRET`. `webhook-id` is
   `op-<sha256 of OpenProject's body>-<bot>`, so Hermes drops a redelivery.
   A bot with an entry in `RELAY_TARGETS` lives outside the cluster. It
   gets the same pointer plus `task_url`, as a JSON POST to its `url` with
   `Authorization: Bearer <bearer>`. A Grok Bot routine's webhook trigger
   takes exactly that. The relay never logs that URL, which carries the
   routine's id.
5. It answers OpenProject 200 with what each bot returned (`-1` if
   unreachable). OpenProject keeps that in its webhook log.

OpenProject sends an event once its journal aggregation window has passed
(5 minutes by default), so a burst of edits is one event, and a bot hears
about a change about 5 minutes after it.

## Alertmanager relay

Alertmanager's webhook receiver can send a bearer token but cannot sign its
body, and a Hermes route takes only HMAC-SHA256. `POST /hooks/alertmanager`
sits between them (`alerts.py`) and sends every alert to one bot,
`ALERTS_BOT`.

1. It needs `ALERTMANAGER_HOOK_TOKEN`, `HERMES_WEBHOOK_SECRET` and a valid
   `ALERTS_BOT`; without them it answers 503. `Authorization: Bearer <token>`
   is compared in constant time; a missing or wrong one gets 401.
2. The body is at most 256 KB (413). Anything that is not JSON, or not an
   Alertmanager webhook v4 payload (`version: "4"`, a `groupKey`, `status`
   `firing` or `resolved`, a non-empty `alerts` list with labels), gets 400.
3. It deduplicates per `groupKey`, in memory. A group is forwarded when it is
   new, when its status changed (firing to resolved or back), or when it is
   firing with a fingerprint not forwarded before. Anything else is a
   `repeat_interval` re-send: 200 `{"status":"duplicate"}`, nothing sent.
   Resolved groups are forgotten after 24 hours, and at most 1000 groups are
   kept (least recently forwarded first).
4. It posts `ALERTS_HERMES_URL`, by default
   `http://agent-board-hooks.hermes-<bot>.svc.cluster.local:8644/webhooks/alerts`
   (the board relay's Service and port), signed like the board relay: Hermes
   generic V2 with `HERMES_WEBHOOK_SECRET`. `webhook-id` is `am-` plus the
   sha256 of the group key, the status, and each forwarded alert's
   fingerprint and `startsAt`, so the same notice always has the same id and
   Hermes drops a repeat even after this server restarts, while an alert that
   fires again (a new `startsAt`) is a new delivery.
5. The bot accepting it (2xx) is 202 `{"status":"forwarded"}`. Anything else,
   or no answer, is 502 and the group is not marked as forwarded, so
   Alertmanager's retry delivers it.

The event:

```json
{"event_type": "alertmanager", "bot": "hank",
 "subject": "[FIRING] KubePodCrashLooping (warning) x3",
 "body": "<plain text, at most 8 KB>", "priority": "warning",
 "status": "firing", "group_key": "<groupKey>",
 "external_url": "<Alertmanager's externalURL>"}
```

`subject` is the status, `commonLabels.alertname` (or `multiple alerts`), the
severity and how many alerts the status is about (the firing ones, or all of
a resolved group). `priority` is `commonLabels.severity`, else the highest
severity among the alerts, else `unknown`. `body` has one block per alert,
firing first: alertname and severity, the other labels (`namespace`, `pod`,
`container`, `job`, `instance`, `service`, `node`, `cluster` first),
`summary`, `description`, `runbook_url`, `startsAt` (and `endsAt` once
resolved) and `generatorURL`. It is cut at 8 KB with a `…truncated` line.
Every value is data: control, format and line-separator characters become
spaces, so a label cannot start a new line, and each value is capped.

## Development

```sh
cd images/openproject-mcp
uv run pytest                       # tests, against recorded API v3 HAL fixtures
PYTHONPATH=src uv run python -m openproject_mcp.app
```

Dependencies: direct ones are pinned exactly in `pyproject.toml`, and every
package is pinned with hashes in `uv.lock`. The image installs with
`uv sync --locked`. To bump, change the pin, run
`uv lock --upgrade-package <name>`, then `uv run pytest`. Renovate does the
same for the pins and for the two base-image digests in the `Dockerfile`.
When the server itself changes, bump the version in `pyproject.toml`,
`src/openproject_mcp/__init__.py` and `OPENPROJECT_MCP_VERSION` in the
workflow.

## Attribution

The task-queue logic is ported from the owner's `homelab-mcp` (MIT,
Copyright (c) 2026 Ryan Holt; `LICENSE.homelab-mcp`). That covers the HAL
translation (`hal.py`), the claim/complete/release semantics (`tools.py`),
the error helper (`_http.py`) and the API v3 test fixtures. This server
differs in its identity model: there, the server held a token per bot and
took a `bot` argument. Here, each request's own token is the identity, and
the project scope comes from OpenProject memberships instead of a local map.
