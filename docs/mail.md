# Mail

Stalwart v1.1.0 in namespace `mail`. ADR 0013.

| Path | Purpose |
| --- | --- |
| `kubernetes/apps/mail/stalwart/app` | Server, certificate, route, network policy |
| `kubernetes/apps/mail/stalwart/backup` | VolSync restic source for the data volume |

## Storage

Every Stalwart store (data, blobs, full-text search, in-memory) is RocksDB
on the `stalwart-data` volume: `ceph-block`, 50 GiB, `retain: true`. Ceph
keeps three copies across the sleds. VolSync snapshots the volume through
`csi-ceph-block` every six hours (`15 */6 * * *`) and sends it to R2 with
restic, using 1Password item `volsync-r2-template` at path `<template>/stalwart`.
The snapshot is crash consistent, and RocksDB replays its WAL on restore.

The only file on disk is `/etc/stalwart/config.json`, the DataStore
object (`@type` `RocksDb`). Everything else is a JMAP object in that store.

## Names and addresses

| Name | Points at | Serves |
| --- | --- | --- |
| `mail.holthome.net` | `envoy-internal`, published by `mikrotik-dns` | WebUI (`/admin`), JMAP, CalDAV, CardDAV, autoconfig |
| `mx.holthome.net` | `10.45.10.25`, Service `stalwart-mail` | SMTP 25, 465, 587; IMAP 993; POP3 995; ManageSieve 4190 |

`mikrotik-dns` only reads HTTPRoutes, so the `mx` A record has to be
added on the router by hand. The `stalwart` Certificate covers `mx` for
the mail protocols. HTTPS terminates at Envoy.

The route is `native`: mail and DAV clients send their own credentials and
cannot complete the gateway's Pocket ID login.

## 1Password

| Item | Field | Use |
| --- | --- | --- |
| `stalwart` | `admin_password` | `STALWART_RECOVERY_ADMIN=admin:<password>`. Always accepted as an administrator while set |
| `volsync-r2-template` | existing | Backups, shared with other apps |

## First run

1. Create the `stalwart` item, then let Flux reconcile `stalwart`.
2. Sign in at `https://mail.holthome.net/admin` as `admin`.
3. **Certificate**: add one with File sources `/etc/stalwart/tls/tls.crt`
   and `/etc/stalwart/tls/tls.key`, and use it on the TLS listeners.
4. **Listeners**: Stalwart creates 25, 465, 993, 995, 4190, 443 and 8080 on
   an empty store. Add `submission` on 587 (STARTTLS) if clients need it.
   Mark the `envoy-internal` pods as trusted proxies on the 8080 listener
   so HTTP logs and rate limits see the client address.
5. **Domain**: add the mail domain and publish the records the UI
   generates (MX, SPF, DKIM, DMARC, MTA-STS, TLS-RPT, autoconfig SRV) in
   Cloudflare by hand. `cloudflare-dns` does not manage them.
6. **Outbound**: add a relay route (for example SMTP2GO on 2525 or 587)
   for remote domains, with its password as an EnvironmentVariable secret.
7. **Directory**: optionally add Pocket ID (`https://id.holthome.net`) as an
   OIDC directory. That needs egress to it in `ciliumnetworkpolicy.yaml`.
8. Export the result with `stalwart-cli snapshot` and keep it somewhere
   private. It contains DKIM keys, so it does not go in this repo.

## Not in this tree yet

- **Inbound port 25 from the internet.** Cloudflare Tunnel carries HTTP
  only. Options are a router port forward to `10.45.10.25` if the ISP
  allows 25, or a small VPS with a static address that forwards over
  Tailscale (with PROXY protocol on the listeners so Stalwart sees the
  sender's address). Either is a new ADR.
- **Outbound reputation.** A residential address will be rejected or
  spam-foldered. Use a relay (step 6) until there is a static address
  with a matching PTR record.
- **Webmail.** Stalwart has no bundled webmail. Native clients work over
  IMAP or JMAP.
