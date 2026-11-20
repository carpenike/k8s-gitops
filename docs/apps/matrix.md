# Matrix

Tuwunel v1.9.4 in namespace `matrix`, for Hermes bot accounts and family
accounts. ADR 0010. Server name `ryanholt.net`, so user IDs are
`@ryan:ryanholt.net` and bot names like `@chief:ryanholt.net`. The server name
cannot change without wiping the database.

| Path | Purpose |
| --- | --- |
| `kubernetes/apps/matrix/tuwunel/app` | Homeserver, routes, network policy, SOPS secrets |
| `kubernetes/apps/matrix/tuwunel/backup` | VolSync restic source for the data volume |
| `kubernetes/apps/matrix/hermes-bot-provisioner/app` | Shared provisioning script and its network policy |
| `kubernetes/apps/matrix/hermes-bot-provisioner/template` | Per-bot Job, RBAC, and Secret, instantiated by `kubernetes/components/hermes-bot` ([hermes.md](hermes.md)) |

## Names and DNS

Both routes parent `envoy-external` and are labeled
`gateway.holthome.net/auth: public`. Matrix clients send bearer tokens
and homeservers sign requests; neither can complete the gateway login.

| Name | Route | Serves |
| --- | --- | --- |
| `matrix.ryanholt.net` | `tuwunel` | Client and federation API, all paths |
| `ryanholt.net` | `tuwunel-well-known` | `/.well-known/matrix/` only. Every other path is the website |

`cloudflare-dns` publishes both as proxied CNAMEs to
`external.holthome.net`. The tunnel sends `ryanholt.net` and
`*.ryanholt.net` to `envoy-external`, and the `ryanholt-net-production`
certificate covers both names.

`matrix.ryanholt.net` has its own listener on `envoy-external`,
`https-matrix`. The `tuwunel` route attaches to it by `sectionName`, and
ClientTrafficPolicy `envoy-external-matrix` sets
`escapedSlashesAction: KeepUnchanged` on that listener alone. Matrix paths
carry `%2F` inside one segment, for example a cross-signing upload with the
key id in the path. The default would redirect those requests and break
them. Every other `envoy-external` host keeps the default. Listeners on one
port are chosen by SNI, so the tunnel's `matrix.ryanholt.net` rule sets
`originServerName: matrix.ryanholt.net`. Without it, cloudflared sends
`external.holthome.net` and lands on the shared listener. See
[gateway-auth.md](../platform/gateway-auth.md).

The apex is also the `ryanholt.net` website ([website.md](website.md)).
Its route in namespace `web` matches `/`; this one matches the longer
prefix `/.well-known/matrix/`, and Gateway API picks the longest match
across routes on the same host. The site never sees the Matrix paths.

As of 3 Nov 2026 the apex, `www`, and `matrix` have no address records
at Cloudflare's authoritative servers, the public resolvers, or the
MikroTik, and there are no `k8s.` ownership TXT records, so
`cloudflare-dns` creates all three without a conflict. The apex keeps its
MX, SPF, and Microsoft verification TXT records and `autodiscover`
(Outlook mail). Cloudflare's apex CNAME flattening lets those sit next to
the new CNAME; external-dns does not touch records it does not own.

Delegation:

- `/.well-known/matrix/client` returns `{"m.homeserver":{"base_url":"https://matrix.ryanholt.net"}}`
- `/.well-known/matrix/server` returns `{"m.server":"matrix.ryanholt.net:443"}`

Federation arrives on 443 through Cloudflare. Nothing listens on 8448,
and no SRV record is needed.

`trusted_servers = []`: there is no notary. Tuwunel fetches each server's
signing keys from that server, so `matrix.org` neither learns which
servers this one talks to nor vouches for their keys.

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

## Encryption

`encryption_enabled_by_default_for_room_type = "all"`. Every room created
on this server starts with `m.room.encryption` (Megolm), whatever preset
the client sends. Rooms created before the setting keep what they had;
encryption cannot be turned off in a room once it is on. The server stores
ciphertext for message bodies and E2EE media. Room membership, names,
profiles, and timestamps are not end-to-end encrypted.

| Layer | State |
| --- | --- |
| Client to Cloudflare, tunnel, Envoy | TLS |
| Envoy to Tuwunel, between sleds | Plain HTTP on the pod network |
| Message bodies and E2EE media | End-to-end encrypted by clients |
| `tuwunel-data` on Ceph | Not encrypted at rest; the OSD disks are not LUKS |
| Restic backups in R2 | Encrypted by restic |

Bots read encrypted rooms only with E2EE on (`MATRIX_E2EE_MODE=required`
for Hermes) and a persistent volume for the Hermes key store
(`~/.hermes/platforms/matrix/store/`). If that store is lost, the bot
cannot decrypt older messages and its device has to be verified again.
Delete the bot's `HERMES_<NAME>` device from the admin room before
provisioning it again, so the new keys are not mixed with the old ones.

## Bot accounts

Appservice `hermes-bots`, file `hermes-bots.yaml` in Secret
`tuwunel-appservice-hermes-bots`, mounted as `appservice_dir`. The
namespace is an explicit list of bot names, today
`^@(chief|hank):ryanholt\.net$`, exclusive, so a person cannot register those
names. Anchored at both ends: `@hankbot` or `@chief2` do not match. Bot
IDs have no prefix; with a handful of accounts on this server a reserved
prefix buys nothing. `rate_limited: false`. `url: null`: the
appservice receives no transactions. Its sender is `@_hermes`, outside
the bot namespace.

`as_token` can act as any user the namespace matches, which is why the
regex lists names instead of a pattern: a broad pattern would let it log in
as `@ryan`. It stays in namespace `matrix`. Bots get their own access
token, not the `as_token`.

Adding a bot name means editing the regex inside the SOPS file, which
needs the YubiKey:

```sh
sops kubernetes/apps/matrix/tuwunel/app/appservice-hermes-bots.sops.yaml
# users regex: '^@(chief|hank|newbot):ryanholt\.net$'
```

Tuwunel reads `appservice_dir` only at startup; Reloader restarts the pod
on the Secret change.

### Provisioning a bot

The template takes `BOT_NAME` and `MATRIX_USER` from the hermes-bot
component ([hermes.md](hermes.md)). The bot's namespace is always
`hermes-<BOT_NAME>`; `provision.py` refuses any other. For `BOT_NAME:
pilot`, `MATRIX_USER: pilot` (once `pilot` is in the namespace regex):

- Flux creates an empty Secret `hermes-pilot-matrix` in `hermes-pilot`
  (`kustomize.toolkit.fluxcd.io/ssa: IfNotPresent`, so Flux never
  reapplies it), a Role there with `get` and `patch` on that one name,
  and a RoleBinding to ServiceAccount `matrix/hermes-provision-pilot`.
  RBAC cannot limit `create` by name, which is why Flux creates the
  object and the Job only patches it.
- Job `matrix/hermes-provision-pilot` runs `provision.py` for `@pilot`:
  0. It refuses unless the Secret carries labels
     `app.kubernetes.io/name: hermes-bot-provisioner` and
     `app.kubernetes.io/instance: pilot`.
  1. If the Secret already has a token that `/account/whoami` accepts,
     it refreshes the non-secret fields and exits.
  2. `POST /_matrix/client/v3/register` with `m.login.application_service`
     and `inhibit_login`. `M_USER_IN_USE` is treated as success.
  3. `POST /_matrix/client/v3/login` with `m.login.application_service`
     and a fixed device id `HERMES_PILOT`, so a re-run replaces that
     device's token instead of adding devices, and a restored crypto store
     still matches.
  4. Merge-patches `MATRIX_HOMESERVER`
     (`http://tuwunel.matrix.svc.cluster.local:8008`), `MATRIX_USER_ID`
     (`@pilot:ryanholt.net`), `MATRIX_DEVICE_ID`, and
     `MATRIX_ACCESS_TOKEN` into the Secret.

`BOT_NAME` is lowercase letters, digits, and `-`, at most 40 characters.
The Job and the bots both talk to Tuwunel in-cluster; the bots never go
through Cloudflare.

Removing the bot prunes the Secret and RBAC. The Matrix account stays;
deactivate it from the admin room with
`!admin users deactivate @pilot:ryanholt.net`.

## Network policy

`default-deny` selects every pod in `matrix`, both directions. Allows:

| Pod | Ingress | Egress |
| --- | --- | --- |
| Tuwunel | `envoy-external` proxies in `network`, the provisioning Job, and Hermes agent pods in namespaces labelled `hermes.holthome.net/bot`, on 8008 | Cluster DNS, public IPv4 on any port (federation) |
| Provisioning Job | none | Cluster DNS, Tuwunel on 8008, `kube-apiserver` |
| VolSync mover | none | Cluster DNS, public IPv4 (R2) |

RFC1918, CGNAT, and link-local are excluded from both public rules.
Turning on Pocket ID needs an egress allow for `id.holthome.net`. A LAN
restic repository would need its address on the mover rule.

The namespace is Pod Security `restricted`. Tuwunel runs as 1000:1000,
the Job as 65534, and the movers as 1000 with `seccompProfile: RuntimeDefault`
set through `moverSecurityContext`.

## Storage and backup

PVC `tuwunel-data`, 20Gi, `ceph-block`, RWO, kept on uninstall. RocksDB
and media both live there. One replica, `Recreate`.

ReplicationSource `tuwunel` snapshots it through `csi-ceph-block` at
03:30 and sends it to restic, 7 daily and 4 weekly. The snapshot is crash
consistent; RocksDB replays its WAL on restore. Credentials are
ExternalSecret `tuwunel-volsync` from 1Password item
`volsync-r2-template`, the Cloudflare R2 item every v1 app used. The
repository is `<REPOSITORY_TEMPLATE>/tuwunel`, v1's per-app path
convention. Nothing waits on Kustomization `tuwunel-backup`.

Restore, in short: scale `tuwunel` to 0, point a VolSync
`ReplicationDestination` at the same repository with
`copyMethod: Direct` and `destinationPVC: tuwunel-data`, then scale back
to 1.

## Metrics

Tuwunel v1.9.4 has no Prometheus endpoint. There is no ServiceMonitor.

## Not here

Element Call, LiveKit, bridges, and MAS are out of scope. SSO is off;
the commented `[[global.identity_provider]]` block in the HelmRelease is
the Pocket ID stub. Its `issuer_url` must not change once accounts are
linked to it.
