# OpenProject

OpenProject Community Edition 17.9.6 is the shared task board for Ryan and
the bots: Chief posts a task, tells Hank over A2A to pick it up, and Hank
comments and closes it there (docs/hermes.md, A2A). It replaces the Forge
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
| 1Password | item `openproject` in `k8s-secrets`: `database_password`, `secret_key_base`, `admin_password` |

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
  login is off for it ([gateway-auth.md](gateway-auth.md), "One login per
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
| Who may connect | Hermes agent pods in bot namespaces (CNP `openproject-mcp`; the agent side is the component's `agent-task-board`) |
| Auth | Each request carries the bot's own OpenProject API token as `Authorization: Bearer`. The server holds no secrets; every OpenProject call is made as that bot |
| Tools | `whoami`, `list_tasks`, `get_task`, `create_task`, `add_comment`, `claim_next`, `complete_task`, `release_task`. Hermes names them `mcp__openproject__<tool>` |
| Claim | Atomic through `lockVersion`: a stale `PATCH` gets 409 and changes nothing |
| Links | Tool results link to `https://tasks.<internal domain>` (`OPENPROJECT_PUBLIC_URL`) |

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
  `hank` with the goal, the context, what done looks like and Ryan's
  words, and gives Ryan the link. Chief's `code-requests` skill sends code
  asks there.
- **A peer's task is a request.** Only text authored by Ryan's OpenProject
  user id (`TASK_BOARD_RYAN_USER_ID`, default 4, the seeded `admin`) or
  Ryan's own Matrix message is Ryan speaking. It goes by id: OpenProject
  hides other users' logins from non-admins, and anyone can change their own
  display name. On a peer's task a bot may research, run
  read-only checks and prepare work for review, pull requests included.
  Sending, spending, deleting, deploying, changing a running system and
  merging still need Ryan's own yes in Matrix. Hank's merge rule is
  unchanged (docs/hermes.md, "Merging, only when Ryan asks").
- **Pickup.** A bot works its tasks in its own Matrix session, when Ryan
  tells it to ("check the board"). Automatic pickup is not wired yet.

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
