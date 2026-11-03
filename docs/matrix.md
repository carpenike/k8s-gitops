# Matrix

Tuwunel v1.9.4 in namespace `matrix`, for Hermes bot accounts and family
accounts. ADR 0010. Server name `ryanholt.net`, so user IDs are
`@ryan:ryanholt.net` and `@hermes-<name>:ryanholt.net`. The server name
cannot change without wiping the database.

| Path | Purpose |
| --- | --- |
| `kubernetes/apps/matrix/tuwunel/app` | Homeserver, routes, network policy, SOPS secrets |
| `kubernetes/apps/matrix/tuwunel/backup` | VolSync restic source for the data volume |
| `kubernetes/apps/matrix/hermes-bot-provisioner/app` | Shared provisioning script and its network policy |
| `kubernetes/apps/matrix/hermes-bot-provisioner/template` | Per-bot Job, RBAC, and Secret. Not wired to a bot |
| `kubernetes/examples/hermes-bot-matrix.yaml` | The Flux Kustomization a bot adds |

## Names and DNS

Both routes parent `envoy-external` and are labeled
`gateway.holthome.net/auth: public`. Matrix clients send bearer tokens
and homeservers sign requests; neither can complete the gateway login.

| Name | Route | Serves |
| --- | --- | --- |
| `matrix.ryanholt.net` | `tuwunel` | Client and federation API, all paths |
| `ryanholt.net` | `tuwunel-well-known` | `/.well-known/matrix/` only. Other apex paths are Envoy 404 |

`cloudflare-dns` publishes both as proxied CNAMEs to
`external.holthome.net`. The tunnel already sends `ryanholt.net` and
`*.ryanholt.net` to `envoy-external`, and the `ryanholt-net-production`
certificate covers both names. No tunnel or certificate change is needed.

The apex already has a proxied record. On 3 Nov 2026 it answered
Cloudflare error 1016 (origin DNS error), so nothing is served there now.
external-dns only replaces a record whose `k8s.` TXT owner record is
`default`. If the apex record is not owned that way, delete it in
Cloudflare and let `cloudflare-dns` create it. Taking the apex this way
means any later website on `ryanholt.net` has to share it with this route.

Delegation:

- `/.well-known/matrix/client` returns `{"m.homeserver":{"base_url":"https://matrix.ryanholt.net"}}`
- `/.well-known/matrix/server` returns `{"m.server":"matrix.ryanholt.net:443"}`

Federation arrives on 443 through Cloudflare. Nothing listens on 8448,
and no SRV record is needed.

Checks once Flux has reconciled:

```sh
curl -s https://ryanholt.net/.well-known/matrix/server
curl -s https://ryanholt.net/.well-known/matrix/client
curl -s https://matrix.ryanholt.net/_matrix/client/versions
```

The federation tester at `https://federationtester.matrix.org` should
report `ryanholt.net` as reachable.

## Registration

`allow_registration = true` with `registration_token_file`. An account
cannot be created without the token, and open registration is off
because the `yes_i_am_very_very_sure...` option is unset. Tuwunel
rejects every registration when `allow_registration` is false, including
token registration, so it has to be true for the token to work.
Appservice registration skips that check (`register.rs` at v1.9.4).

`grant_admin_to_first_user = false`. The first account is not an admin.
No bot is an admin.

The token is `kubernetes/apps/matrix/tuwunel/app/registration-token.sops.yaml`.

## First admin account

1. Read the token with the YubiKey:

   ```sh
   sops -d kubernetes/apps/matrix/tuwunel/app/registration-token.sops.yaml | yq '.stringData.token'
   ```

2. In Element (or any client), sign up on homeserver `ryanholt.net` with
   username `ryan` and that token.

3. Promote the account. Nobody is in the admin room yet, so the command
   runs from config. In `kubernetes/apps/matrix/tuwunel/app/helmrelease.yaml`,
   under `[global]`, set:

   ```toml
   admin_execute = ["users make-user-admin @ryan:ryanholt.net"]
   admin_execute_errors_ignore = true
   ```

   Merge. The ConfigMap checksum changes, so the pod restarts and runs
   the command at startup. `@ryan` is joined to the admin room
   (`#admins:ryanholt.net`) with admin power.

4. Remove both lines in the next pull request. `admin_execute` runs on
   every start, and with `admin_execute_errors_ignore` false a failing
   command stops the server from starting.

Later admins are promoted from the admin room:
`!admin users make-user-admin @name:ryanholt.net`.

Family accounts use the same token. Rotate it afterwards by editing the
SOPS file (`sops kubernetes/apps/matrix/tuwunel/app/registration-token.sops.yaml`).
The option is reloadable; the pod also restarts on the Secret change.

## Bot accounts

Appservice `hermes-bots`, file `hermes-bots.yaml` in Secret
`tuwunel-appservice-hermes-bots`, mounted as `appservice_dir`. The
namespace is `^@hermes-.*:ryanholt\.net$`, exclusive, so a person cannot
register a `hermes-` name. `rate_limited: false`. `url: null`: the
appservice receives no transactions. Its sender is `@_hermes`, outside
the bot namespace.

`as_token` can act as any `@hermes-*` user. It stays in namespace
`matrix`. Bots get their own access token, not the `as_token`.

### Provisioning a bot

The template takes `BOT_NAME` and `BOT_NAMESPACE`. For `BOT_NAME: pilot`:

- Flux creates an empty Secret `hermes-pilot-matrix` in `BOT_NAMESPACE`
  (`kustomize.toolkit.fluxcd.io/ssa: IfNotPresent`, so Flux never
  reapplies it), a Role there with `get` and `patch` on that one name,
  and a RoleBinding to ServiceAccount `matrix/hermes-provision-pilot`.
  RBAC cannot limit `create` by name, which is why Flux creates the
  object and the Job only patches it.
- Job `matrix/hermes-provision-pilot` runs `provision.py`:
  1. If the Secret already has a token that `/account/whoami` accepts,
     it exits.
  2. `POST /_matrix/client/v3/register` with `m.login.application_service`
     and `inhibit_login`. `M_USER_IN_USE` is treated as success.
  3. `POST /_matrix/client/v3/login` with `m.login.application_service`
     and a fixed device id `HERMES_PILOT`, so a re-run replaces that
     device's token instead of adding devices.
  4. Merge-patches `MATRIX_HOMESERVER` (`https://matrix.ryanholt.net`),
     `MATRIX_USER_ID` (`@hermes-pilot:ryanholt.net`), and
     `MATRIX_ACCESS_TOKEN` into the Secret.

To wire a bot, copy `kubernetes/examples/hermes-bot-matrix.yaml` next to
the bot's own `ks.yaml`, set the two substitutions, and add a `dependsOn`
on the Kustomization that creates `BOT_NAMESPACE`. The bot reads the
Secret with `envFrom`. Hermes accepts `MATRIX_HOMESERVER` plus
`MATRIX_ACCESS_TOKEN`; `MATRIX_USER_ID` is there too.

`BOT_NAME` is lowercase letters, digits, and `-`, at most 40 characters.
The Job's pod talks to `http://tuwunel.matrix.svc.cluster.local:8008`.
The bots use the public URL.

Removing the bot's Kustomization prunes the Secret and RBAC. The Matrix
account stays; deactivate it from the admin room with
`!admin users deactivate @hermes-pilot:ryanholt.net`.

## Network policy

`default-deny` selects every pod in `matrix`, both directions. Allows:

| Pod | Ingress | Egress |
| --- | --- | --- |
| Tuwunel | `envoy-external` proxies in `network`, and the provisioning Job, on 8008 | Cluster DNS, public IPv4 on any port (federation) |
| Provisioning Job | none | Cluster DNS, Tuwunel on 8008, `kube-apiserver` |
| VolSync mover | none | Cluster DNS, public IPv4 |

RFC1918, CGNAT, and link-local are excluded from both public rules.
Turning on Pocket ID needs an egress allow for `id.holthome.net`. A
Garage repository on the backup NAS needs its address on the mover rule.

The namespace is Pod Security `restricted`. Tuwunel runs as 1000:1000,
the Job as 65534, and the movers as 1000 with `seccompProfile: RuntimeDefault`
set through `moverSecurityContext`.

## Storage and backup

PVC `tuwunel-data`, 20Gi, `ceph-block`, RWO, kept on uninstall. RocksDB
and media both live there. One replica, `Recreate`.

ReplicationSource `tuwunel` snapshots it through `csi-ceph-block` at
03:30 and sends it to restic, 7 daily and 4 weekly. The snapshot is crash
consistent; RocksDB replays its WAL on restore. Credentials are
ExternalSecret `tuwunel-volsync` from 1Password item `volsync-restic`,
which does not exist yet (see [placeholders.md](placeholders.md)). Until
it does, Kustomization `tuwunel-backup` is not ready and nothing waits on
it.

## Metrics

Tuwunel v1.9.4 has no Prometheus endpoint. There is no ServiceMonitor.

## Not here

Element Call, LiveKit, bridges, and MAS are out of scope. SSO is off;
the commented `[[global.identity_provider]]` block in the HelmRelease is
the Pocket ID stub. Its `issuer_url` must not change once accounts are
linked to it.
