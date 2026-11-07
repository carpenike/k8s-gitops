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

The pod only reaches hosts named in the CiliumNetworkPolicy, on 443.

These categories run here:

- `mfp`
- `cooklang`
- `ha`
- `grocy`
- `paperless`
- `arcraiders`

The Forge-local categories stay off until they have a network path from the
cluster:

- `finances`
- `money`
- `school`
- `amazon`
- `costco`
- `samsclub`
- `messaging`
- `nixos`

A tool that Forge served today and is missing here is one of these.

To enable a category:

1. Add it to `HOMELAB_MCP_TOOL_CATEGORIES`.
2. Add its upstream host to the policy's `toFQDNs`.

MFP writes stay off (`HOMELAB_MCP_MFP_WRITES_ENABLED: "false"`) until the
write tests pass. The mfp tools only read.

The upstreams on `${SECRET_DOMAIN}` must answer API calls from the
cluster without the gateway login. Check each host when it first fails:

- Home Assistant takes its own bearer token.
- Grocy takes `GROCY-API-KEY`.
- Paperless takes `Token`.

## 1Password

Create the item `homelab-mcp` in vault `k8s-secrets`:

| Field | Value |
| --- | --- |
| `pocketid_client_secret` | Secret of the existing Pocket ID client `mcp`. Its callback is already `https://mcp.${SECRET_DOMAIN}/oauth/callback`. Take it from Forge's `homelab-mcp` sops secret, or regenerate it in Pocket ID at cutover |
| `ha_token` | Home Assistant long-lived token for writes (Forge's `homelab-mcp/ha_token`) |
| `ha_read_token` | Home Assistant token for reads |
| `grocy_api_key` | Grocy API key |
| `paperless_token` | Paperless API token |
| `mfp_cookies` | The MyFitnessPal cookie export (carpenike/mcp `docs/MFP-COOKIE-RUNBOOK.md`) |

Two ExternalSecrets read the item:

- `homelab-mcp` builds `homelab-mcp-env`, which the pod reads as
  environment variables.
- `homelab-mcp-mfp` builds `homelab-mcp-mfp`, which is mounted at
  `/run/mfp`.

The server re-reads the cookie file when it changes, so new cookies need a
force-sync but no restart:

```sh
kubectl -n homelab-mcp annotate externalsecret homelab-mcp-mfp \
  force-sync="$(date +%s)" --overwrite
```

The OAuth signing key and the state database are created on first start,
in `/var/lib/homelab-mcp/state` on the PVC. They are not in 1Password.
Losing the PVC means every client connects again. Nothing else is lost.

## Image

`ghcr.io/carpenike/homelab-mcp` is built by carpenike/mcp
`.github/workflows/image.yml`, on the `mcp-k8s-build` runners, from main.

The HelmRelease carries a placeholder tag,
`sha-0000000000000000000000000000000000000000`. Replace it with
`sha-<commit>@sha256:<digest>` from the first main build. The tag does not
exist, so the release cannot start by accident.

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

1. Merge carpenike/mcp #117, #118 and #119.

   Merging to main triggers nix-config's automatic homelab-mcp pin bump.
   Do not let that reach Forge: #118 makes the server refuse Forge's
   leftover Atrium settings at startup. Close the bump PR, or disable the
   job first.

2. Wait for the image build on main. Set the tag and digest in the
   HelmRelease.

3. Create the 1Password item above.

4. On Forge, turn off homelab-mcp: the service, the Caddy vhost, and the
   Cloudflare tunnel ingress for `mcp`. Then delete the `mcp` DNS record.

   external-dns will not take over a record it does not own (TXT
   ownership, prefix `k8s.`).

5. Merge this app. external-dns publishes `mcp.${SECRET_DOMAIN}` to the
   cluster tunnel.

6. Remove the old connectors in Claude. Add one connector per view URL
   (`/mcp`, `/mcp/admin`), and approve each on the consent page.

   Point Hermes at `/mcp/agent`, and Groundskeeper at
   `/mcp/house-sensors`.

Tokens from Forge do not work here. The signing key is new, and the
audience is now the view URL.
