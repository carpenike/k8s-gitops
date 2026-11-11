# Mail

Stalwart v1.1.0 in namespace `mail`. ADR 0013.

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
| `mx.holthome.net` | `10.45.10.25`, Service `stalwart-mail` | SMTP 25, 465, 587; IMAP 993; POP3 995; ManageSieve 4190 |

`mikrotik-dns` only reads HTTPRoutes, so the `mx` A record has to be
added on the router by hand. The `stalwart` Certificate covers `mx` for
the mail protocols. HTTPS terminates at Envoy.

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
6. **Domain**: add the mail domain and publish the records the UI
   generates (MX, SPF, DKIM, DMARC, MTA-STS, TLS-RPT, autoconfig SRV) in
   Cloudflare by hand. `cloudflare-dns` does not manage them.
7. **Outbound**: add a relay route (for example SMTP2GO on 2525 or 587)
   for remote domains, with its password as an EnvironmentVariable secret.
8. **Directory**: optionally add Pocket ID (`https://id.holthome.net`) as an
   OIDC directory. That needs egress to it in `ciliumnetworkpolicy.yaml`.
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

## Not in this tree yet

- **Inbound port 25 from the internet.** Cloudflare Tunnel carries HTTP
  only. Options are a router port forward to `10.45.10.25` if the ISP
  allows 25, or a small VPS with a static address that forwards over
  Tailscale (with PROXY protocol on the listeners so Stalwart sees the
  sender's address). Either is a new ADR.
- **Outbound reputation.** A residential address will be rejected or
  spam-foldered. Use a relay (step 7) until there is a static address
  with a matching PTR record.
- **Webmail.** Stalwart has no bundled webmail. Native clients work over
  IMAP or JMAP.
- **More than one replica.** Needs a shared in-memory store (Redis or
  Valkey) and Stalwart's cluster settings.
