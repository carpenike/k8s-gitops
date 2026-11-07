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

## Bot access (next step)

Not wired yet. Each bot gets its own OpenProject user and API token
(1Password item `hermes-<bot>`). Each bot also needs an MCP server for the
API v3 and egress to the Service. The design notes from Forge still apply:
- atomic claim with `lockVersion` (409 means someone else got it);
- comments through `/activities`;
- webhooks with polling as the fallback.

They're in nix-config's history, `docs/services/openproject.md`.
