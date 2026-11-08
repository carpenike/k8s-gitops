# homelab-mcp

The Claude tools server from [carpenike/mcp](https://github.com/carpenike/mcp),
at `mcp.${SECRET_DOMAIN}` on envoy-external. It is its own OAuth 2.1
authorization server, federated to Pocket ID, so the route is `native`
(see [gateway-auth.md](gateway-auth.md)).

Manifests: `kubernetes/apps/homelab-mcp/`.

## Views

Each URL is a separate protected resource. A token for one is refused on
the others. Configure them in `HOMELAB_MCP_VIEWS` in the HelmRelease.

| URL | Tools | Scopes | For |
| --- | --- | --- | --- |
| `/mcp` | read-only tools | `home.read` | The everyday Claude connector |
| `/mcp/admin` | every enabled tool | `home.read` and `home.write`, both requested on connect | Claude, when writes are wanted |
| `/mcp/agent` | the `hermes` list | `hermes` | Hermes |
| `/mcp/house-sensors` | the `atrium-family-house-sensors` list | the same | Groundskeeper |

Only users listed in a view can use it. Today that is Ryan only.

The first time a user connects a client to a view, they get a consent page.

## What runs here

The pod only reaches hosts named in its CiliumNetworkPolicy, on 443, plus
postgres17 on 5432. That policy is in the HelmRelease (`rawResources`), not
`ciliumnetworkpolicy.yaml`, because kubeconform rejects `${SECRET_DOMAIN}` in
a `toFQDNs` name.

| Category | Upstream |
| --- | --- |
| `mfp` | www/api.myfitnesspal.com |
| `cooklang`, `ha`, `grocy`, `paperless` | their hosts on `${SECRET_DOMAIN}` |
| `arcraiders` | public game-data sites |
| `gatus` | `status.${SECRET_DOMAIN}` `/api/v1/endpoints`, let through Forge's admin login (nix-config) |
| `fidelity` | api.snaptrade.com |
| `finances`, `finances_docs`, `finances_loans`, `finances_sentinel` | the Actual sidecar in this pod (to `budget.${SECRET_DOMAIN}`), the finances repo on github.com, postgres17 `finances_context` |
| `money` | postgres17 `homelab_finance` (`money_overview` only) |
| `school`, `school_today` | postgres17 `schoolhouse` |
| `amazon`, `costco`, `samsclub` | postgres17 `lading` |

Off: `messaging` (`signal_send` needs Forge's signal-cli, which stays on
Forge) and `nixos` (Forge's deploy trigger). The Signal capture and report
workers stay on Forge and write the shared context store in postgres17.

The stores in postgres17 and how they got there:
[postgres17.md, "Forge stores"](postgres17.md#forge-stores).

### Actual sidecar

Actual's only API client is the Node package `@actual-app/api`, so container
`actual` runs it in this pod; the tools call it on loopback.
- It logs in once per start, and Actual locks the account after 5 failed
  logins in 15 minutes. So a failed boot holds `/health` at 503 for 5 minutes
  before exiting (`SIDECAR_BOOT_FAILURE_HOLD_SECONDS`).
- Its liveness probe is the TCP port, and it has no readiness probe. A
  not-ready container would take the whole pod, and every MCP endpoint, out
  of service when Actual is down.

### Finances export

The nightly export into `homelab_finance` stays on Forge. It is one step of
a chain there: bank ingestion, then the export (`--after-ingestion`), then
snapshots. It writes to postgres17 through `postgres17-forge` as the owner.
`money_*` here and Forge's Grafana read the result.

MFP writes stay off (`HOMELAB_MCP_MFP_WRITES_ENABLED: "false"`) until the
write tests pass. The mfp tools only read.

The upstreams on `${SECRET_DOMAIN}` must answer API calls from the
cluster without the gateway login. Check each host when it first fails:

- Home Assistant takes its own bearer token.
- Grocy takes `GROCY-API-KEY`.
- Paperless takes `Token`.
- Gatus needs the `/api/v1/endpoints` bypass.
- Actual takes the sidecar's password login.

## 1Password

Item `homelab-mcp` in vault `k8s-secrets`:

| Field | Value |
| --- | --- |
| `pocketid_client_secret` | Secret of the existing Pocket ID client `mcp`. Its callback is already `https://mcp.${SECRET_DOMAIN}/oauth/callback`. Take it from Forge's `homelab-mcp` sops secret, or regenerate it in Pocket ID at cutover |
| `ha_token` | Home Assistant long-lived token for writes (Forge's `homelab-mcp/ha_token`) |
| `ha_read_token` | Home Assistant token for reads |
| `grocy_api_key` | Grocy API key |
| `paperless_token` | Paperless API token |
| `mfp_cookies` | The MyFitnessPal cookie export (carpenike/mcp `docs/MFP-COOKIE-RUNBOOK.md`) |
| `sidecar_token` | Shared token between the tools, and the sidecar (Forge's `homelab-mcp/actual-env` `SIDECAR_TOKEN`, or a new `openssl rand -hex 32`) |
| `actual_password` | Actual server password (Forge's `homelab-mcp/actual-env` `ACTUAL_PASSWORD`) |
| `actual_budget_sync_id` | Budget sync id (same file, `ACTUAL_BUDGET_SYNC_ID`) |
| `actual_encryption_password` | Budget encryption password (same file, `ACTUAL_ENCRYPTION_PASSWORD`) |
| `finances_repo_token` | GitHub token for carpenike/finances, contents read and write (Forge's `HOMELAB_MCP_FINANCES_REPO_TOKEN`) |
| `finances_floor`, `finances_amazon_baseline`, `finances_buffer_floor` | The private monthly numbers from Forge's `homelab-mcp/env` (`HOMELAB_MCP_FINANCES_*`) |
| `snaptrade_client_id`, `snaptrade_consumer_key` | SnapTrade read credentials (Forge's `HOMELAB_MCP_SNAPTRADE_*`) |
| `amazon_account_last4` | JSON object, ledger account name to card last four, as in Forge's `HOMELAB_MCP_AMAZON_ACCOUNT_LAST4`. Without it `amazon_*` matches top out at `probable` |

The database passwords come from the postgres17 items (`schoolhouse`,
`lading`, `homelab-finance`, `finances-context`;
[postgres17.md](postgres17.md#1password)). The ExternalSecrets build the
DSNs from them, URL-encoded, against `postgres17-rw`.

ExternalSecrets:

- `homelab-mcp` builds `homelab-mcp-env`, the MCP container's environment.
- `homelab-mcp-mfp` builds `homelab-mcp-mfp`, which is mounted at
  `/run/mfp`.
- `homelab-mcp-actual` holds the sidecar's login, which only the sidecar
  container sees.

The server re-reads the cookie file when it changes, so new cookies need a
force-sync but no restart:

```sh
kubectl -n homelab-mcp annotate externalsecret homelab-mcp-mfp \
  force-sync="$(date +%s)" --overwrite
```

The OAuth signing key and the state database are created on first start,
in `/var/lib/homelab-mcp/state` on the PVC. They are not in 1Password.
Losing the PVC means every client connects again. Nothing else is lost; the
finances checkout re-clones.

## Images

carpenike/mcp `.github/workflows/image.yml` builds both images on the
`mcp-k8s-build` runners from main:

- `ghcr.io/carpenike/homelab-mcp`: the server;
- `ghcr.io/carpenike/homelab-mcp-actual-sidecar`.

Both are pinned by tag and digest (`sha-<commit>@sha256:<digest>`). The first
pin is mcp `0f27fd4`; bump both together from a later main build.

## Alerts

The PrometheusRule `homelab-mcp` defines three alerts. They route to Forge's
Alertmanager like every other alert here.

| Alert | Fires when |
| --- | --- |
| `HomelabMcpDown` | Prometheus gets no `/metrics` for 10 minutes |
| `HomelabMcpMfpAuthExpired` | MyFitnessPal refused the cookies. The tools return an auth error until they are replaced |
| `HomelabMcpMfpCookiesExpiringSoon` | The session cookie expires within 5 days |

## Cutover from Forge

There is no staging hostname. The cluster takes `mcp.${SECRET_DOMAIN}`
over from Forge directly.

1. Merge carpenike/mcp #117 through #120.

   Merging to main triggers nix-config's automatic homelab-mcp pin bump.
   Do not let that reach Forge before the nix-config cutover PR: #118 makes
   the server refuse Forge's leftover Atrium settings at startup. Close the
   bump PR, or disable the job first.

2. Wait for both image builds on main. Set the tags and digests here.

3. Create the 1Password items above and the postgres17 ones, then merge the
   postgres17 PR.

4. Stop Forge's writers and homelab-mcp, then restore the stores and copy
   the transaction context ([postgres17.md](postgres17.md#restore-from-forge-cutover)).

5. Apply the nix-config cutover. It turns off Forge's homelab-mcp: the
   service, the Caddy vhost, and the Cloudflare tunnel ingress for `mcp`. It
   points schoolhouse, lading, the finances export, the Signal workers and
   Grafana at postgres17, and lets Gatus' read API through. Then delete the `mcp` DNS
   record.

   external-dns will not take over a record it does not own (TXT
   ownership, prefix `k8s.`).

6. Merge this app. external-dns publishes `mcp.${SECRET_DOMAIN}` to the
   cluster tunnel.

7. Remove the old connectors in Claude. Add one connector per view URL
   (`/mcp`, `/mcp/admin`), and approve each on the consent page.

   Point Hermes at `/mcp/agent`, and Groundskeeper at
   `/mcp/house-sensors`.

Tokens from Forge do not work here. The signing key is new, and the
audience is now the view URL.
