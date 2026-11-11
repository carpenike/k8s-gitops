# Mail

Stalwart v1.1.0 in namespace `mail`. ADR 0013 (server and storage), 0014
(inbound edge relay) and 0015 (accounts from Pocket ID).

| Path | Purpose |
| --- | --- |
| `kubernetes/apps/mail/stalwart/app` | Server, bucket claim, certificate, route, network policy |
| `kubernetes/apps/mail/stalwart/backup` | Hourly copy of the blob bucket to R2 |
| `kubernetes/apps/cnpg-system/postgres17/app` | Role and database `stalwart`, and Secret `stalwart-db` |

## Storage

| Stalwart store | Where | Off the chassis |
| --- | --- | --- |
| Data (accounts, mailboxes, metadata, configuration) | Database `stalwart` on `postgres17` | Barman WAL archive and daily base backup to R2, 30-day point-in-time recovery ([postgres17.md](postgres17.md)) |
| Full-text search | Same database (search store `Default`) | Same |
| Blobs (message bodies, attachments, Sieve scripts) | RGW bucket `stalwart-blobs` on `ceph-objectstore` | CronJob `stalwart-blobs-r2`, hourly at :40, `rclone copy` to `<bucket>/stalwart/blobs/` |
| In-memory (rate limits, locks) | Local to the pod | Not needed |

The pod has no volume. `/etc/stalwart/config.json` is the DataStore object
(`@type` `PostgreSql`), and the password comes from `STALWART_DB_PASSWORD`.
Everything else, the blob store included, is a JMAP object in the database.

The blob copy never deletes. Blobs are content-addressed and written once,
so a database restored to any earlier point finds every blob it references
in R2, except blobs written in the hour before the last copy. R2 grows with
every blob ever stored, including ones Stalwart later purged.

The bucket claim has `kustomize.toolkit.fluxcd.io/prune: disabled`.
`ceph-bucket` has `reclaimPolicy: Delete`, so deleting the claim deletes
the bucket and the mail in it.

## Names and addresses

| Name | Points at | Serves |
| --- | --- | --- |
| `mail.holthome.net` | `envoy-internal`, published by `mikrotik-dns` | WebUI (`/admin`), JMAP, CalDAV, CardDAV, autoconfig |
| `mx.holthome.net` | `10.45.10.25`, Service `stalwart-mail` | SMTP 25, 465, 587; IMAP 993; POP3 995; ManageSieve 4190; `smtp-edge` 2525 from the edge relay only |
| MX of each mail domain (public DNS) | The Vultr edge relay | Inbound SMTP from the internet (ADR 0014) |

`mikrotik-dns` only reads HTTPRoutes, so the `mx` A record has to be
added on the router by hand. The `stalwart` Certificate covers `mx` for
the mail protocols. HTTPS terminates at Envoy.

Tailnet devices reach `10.45.10.25` through Connector `home`, on the ports
the tailnet policy grants them ([tailscale.md](tailscale.md)).

The route is `native`: mail and DAV clients send their own credentials and
cannot complete the gateway's Pocket ID login.

## 1Password

Vault `k8s-secrets`:

| Item | Field | Use |
| --- | --- | --- |
| `stalwart` | `database_password` | Role `stalwart` on `postgres17`. Read by `cnpg-system` and `mail` |
| `stalwart` | `admin_password` | `STALWART_RECOVERY_ADMIN=admin:<password>`. Always accepted as an administrator while set |
| `stalwart-r2` | `access_key_id`, `secret_access_key`, `endpoint_url`, `bucket` | The blob copy. Same shape as `postgres17-r2`: an R2 token with Object Read & Write on one bucket, endpoint without the bucket |

The RGW credentials are not in 1Password. Rook writes them to Secret
`stalwart-blobs` in `mail` when it provisions the bucket.

## First run

1. Create both items. Flux applies the `postgres17` change (role and
   database), then `stalwart`. Check that the claim is bound and the RGW
   is up:

   ```sh
   kubectl -n rook-ceph get cephobjectstore ceph-objectstore
   kubectl -n mail get objectbucketclaim stalwart-blobs
   ```

2. Sign in at `https://mail.holthome.net/admin` as `admin`.
3. **Blob store first**, before any mail arrives (anything stored earlier
   stays in the database): set the BlobStore to S3 with
   - bucket `stalwart-blobs`
   - region Custom: name `us-east-1`, URL
     `http://rook-ceph-rgw-ceph-objectstore.rook-ceph.svc.cluster.local`
   - access key id: EnvironmentVariable `AWS_ACCESS_KEY_ID`
   - secret key: EnvironmentVariable `AWS_SECRET_ACCESS_KEY`

   Leave the search store `Default` (the database) and the in-memory store
   `Default`.
4. **Certificate**: add one with File sources `/etc/stalwart/tls/tls.crt`
   and `/etc/stalwart/tls/tls.key`, and use it on the TLS listeners.
5. **Listeners**: Stalwart creates 25, 465, 993, 995, 4190, 443 and 8080 on
   an empty store. Add `submission` on 587 (STARTTLS) if clients need it.
   Mark the `envoy-internal` pods as trusted proxies on the 8080 listener
   so HTTP logs and rate limits see the client address.

   Add `smtp-edge`: SMTP on 2525, STARTTLS with the certificate from step
   4, no PROXY protocol. Mail on it was already checked by the edge relay
   and arrives from a Connector pod's address, so exclude the listener
   from the checks that would judge that address:
   - DATA stage `enableSpamFilter`:
     `is_empty(authenticated_as) && listener != 'smtp-edge'`
   - the SPF, DMARC and reverse-DNS verification expressions: the same
     `listener != 'smtp-edge'` condition
   - a global Sieve script that files mail the edge marked as spam into
     Junk

   The network policy and the tailnet grant are what keep everyone but
   the edge off this listener. Do not open 2525 anywhere else.
6. **Domain**: add the mail domain and publish the records the UI
   generates (MX, SPF, DKIM, DMARC, MTA-STS, TLS-RPT, autoconfig SRV) in
   Cloudflare by hand. `cloudflare-dns` does not manage them.
7. **Outbound**: add a relay route (for example SMTP2GO on 2525 or 587)
   for remote domains, with its password as an EnvironmentVariable secret.
8. **Directory** (ADR 0015), before creating any account, because
   Stalwart does not move accounts between directories:
   - in Pocket ID, create a public OIDC client for the WebUI (PKCE, no
     secret) with the redirect URI the WebUI shows, and allow the groups
     that should have mail
   - in Stalwart, add an OIDC directory: issuer `https://id.holthome.net`
     (exactly as Pocket ID reports it), `claimUsername`
     `preferred_username`, `usernameDomain` the mail domain, `claimGroups`
     `groups`, and the client id under `acceptedAudiences`. Set it as
     the directory, and the client id as the WebUI Application's
     `oauthClientId`
   - create every account in advance. OIDC cannot look up an address, so
     an account that does not exist yet rejects mail until its owner
     first signs in
   - mail clients use app passwords, created by each user after signing
     in with Pocket ID
   - `admin` from `STALWART_RECOVERY_ADMIN` keeps working when Forge is
     down

   The network policy already allows 443 to `id.holthome.net`.
9. Export the result with `stalwart-cli snapshot` and keep it somewhere
   private. It contains DKIM keys, so it does not go in this repo.

Then check the first blob copy:

```sh
kubectl -n mail create job --from=cronjob/stalwart-blobs-r2 stalwart-blobs-r2-manual
kubectl -n mail logs -f job/stalwart-blobs-r2-manual
```

## Restore

1. Restore `postgres17` (or just database `stalwart`) to the chosen time,
   as in [postgres17.md](postgres17.md).
2. If the RGW bucket is gone, recreate the claim and copy the blobs back:
   `rclone copy r2:<bucket>/stalwart/blobs ceph:stalwart-blobs`, from a
   pod with the same environment as the CronJob.
3. Start Stalwart. Messages whose blobs were written after the last copy
   open as missing bodies; the metadata is still there.

## Edge relay (ADR 0014)

Inbound mail from the internet goes to Stalwart on a Vultr VM, which
checks it, queues it, and relays it over the tailnet to `smtp-edge` on
`10.45.10.25:2525`. The VM is not managed from this repo.

1. **VM.** A small Vultr instance with a static IPv4. Firewall: public
   25 only, plus Tailscale's UDP. Use Tailscale SSH, not public SSH. Set
   the reverse DNS of the address to the edge's MX name.
2. **Tailscale.** Join with tag `tag:mx-edge` and `--accept-routes`. The
   grant lets it reach `10.45.10.25` on `tcp:2525` and nothing else.
   Check from the VM: `nc -vz 10.45.10.25 2525`.
3. **Stalwart, MTA only.** Same version as the cluster. Its own
   RocksDB store on the VM's disk is enough: it holds the queue and its
   configuration.
   - certificate for the MX name from Stalwart's ACME client
   - the mail domains as relay domains, with every address on the RCPT
     recipient list, and unknown recipients rejected. Never accept the
     whole domain, or the edge bounces mail to forged senders
   - spam filter on, with a reject threshold
   - an `MtaRoute/Relay` to `10.45.10.25` port 2525, STARTTLS, and a
     routing rule that sends the mail domains there
   - queue retention long enough to cover a rebuild (days, not hours)
4. **Public DNS.** MX of each mail domain to the edge's name, and that
   name's A record to the VM. On the LAN, `mx.holthome.net` stays
   `10.45.10.25`.
5. Export the edge's configuration with `stalwart-cli snapshot` too.

Adding an address: create the account in the cluster (ADR 0015) and add
the address to the edge's recipient list.

## Not in this tree yet

- **Outbound reputation.** A residential address will be rejected or
  spam-foldered. Use a relay (step 7) until there is a static address
  with a matching PTR record. The edge VM is one: once Vultr opens its
  outbound 25, the cluster can relay through it. That needs a way from
  the cluster to the tailnet, such as an operator egress Service, and a
  policy rule; the current egress rule excludes 100.64.0.0/10.
- **Webmail.** Stalwart has no bundled webmail. Native clients work over
  IMAP or JMAP.
- **More than one replica.** Needs a shared in-memory store (Redis or
  Valkey) and Stalwart's cluster settings.
