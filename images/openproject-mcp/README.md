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

The container listens on `0.0.0.0:$PORT` (default 8000) as UID 65532. It runs
one uvicorn process and writes nothing outside `/tmp`, so
`readOnlyRootFilesystem` works.

Requests to `/mcp` must carry a `Host` that is in `ALLOWED_HOSTS`. This is
the MCP SDK's DNS-rebinding check. Other hosts get HTTP 421.

## Environment

None of these is a secret.

| Variable | Default | Meaning |
|---|---|---|
| `OPENPROJECT_URL` | `http://openproject.openproject.svc.cluster.local:8080` | Where API calls go (the in-cluster Service). A trailing `/api/v3` is tolerated |
| `OPENPROJECT_PUBLIC_URL` | *(= `OPENPROJECT_URL`)* | Base of human-facing links, such as a task's `url`, e.g. `https://tasks.example.com` |
| `OPENPROJECT_DEFAULT_PROJECT` | *(none)* | Project identifier or id used when a tool gets no `project`. With no default, list/claim cover every project the caller can see, and `create_task` needs `project` |
| `OPENPROJECT_READY_STATUSES` | `New` | Comma list of status names or ids that `claim_next` may take |
| `OPENPROJECT_IN_PROGRESS_STATUS` | `In progress` | Status a claim sets |
| `OPENPROJECT_DONE_STATUS` | `Closed` | Status `complete_task` sets |
| `OPENPROJECT_RELEASE_STATUS` | `New` | Status `release_task` resets to |
| `OPENPROJECT_CLAIM_MAX_ATTEMPTS` | `5` | PATCH attempts per claim, and the retry bound for complete/release (1–20) |
| `OPENPROJECT_CACHE_SECONDS` | `600` | TTL for status/priority/type/project lookups (0 = off). Identity uses `min(60, this)` |
| `PORT` | `8000` | Listen port |
| `ALLOWED_HOSTS` | `openproject-mcp.openproject.svc.cluster.local:*,openproject-mcp.openproject.svc:*,openproject-mcp:*,localhost:*,127.0.0.1:*` | Comma list of allowed `Host` headers. `name:*` allows any port and also the bare `name`, so a Service on port 80 works |
| `LOG_LEVEL` | `INFO` | Python log level |

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
| `get_task` | yes | `task_id`, `comments=5` | One slim task and its newest comments: `{id, author, author_id, author_login, created_at, text}` |
| `add_comment` | no | `task_id`, `text` | Post a comment as the caller |
| `create_task` | no | `subject`, `project?`, `description?`, `type?`, `priority?`, `assignee?`, `due_date?` | Create a task. `assignee` is `me`, a member's login or name, or a numeric user id |

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
