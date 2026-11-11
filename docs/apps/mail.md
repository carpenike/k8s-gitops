# Mail

Stalwart v1.1.0 in namespace `mail`. ADR 0013 (server and storage), 0014
(inbound edge relay), 0015 (accounts from Pocket ID) and 0017 (Bulwark
webmail).

| Path | Purpose |
| --- | --- |
| `kubernetes/apps/mail/stalwart/app` | Server, bucket claim, certificate, route, network policy |
| `kubernetes/apps/mail/stalwart/backup` | Hourly copy of the blob bucket to R2 |
| `kubernetes/apps/mail/bulwark/app` | Bulwark webmail ([Webmail](#webmail)) |
| `kubernetes/apps/cnpg-system/postgres17/app` | Role and database `stalwart`, and Secret `stalwart-db` |

## Storage

| Stalwart store | Where | Off the chassis |
| --- | --- | --- |
| Data (accounts, mailboxes, metadata, configuration) | Database `stalwart` on `postgres17` | Barman WAL archive and daily base backup to R2, 30-day point-in-time recovery ([postgres17.md](../platform/postgres17.md)) |
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
| `webmail.holthome.net` | `envoy-internal`, published by `mikrotik-dns` | Bulwark webmail |
| `mx.holthome.net` | `10.45.10.25`, Service `stalwart-mail` | SMTP 25, 465, 587; IMAP 993; POP3 995; ManageSieve 4190; `smtp-edge` 2525 from the edge relay only |
| MX of each mail domain (public DNS) | The Vultr edge relay | Inbound SMTP from the internet (ADR 0014) |

`mikrotik-dns` only reads HTTPRoutes, so the `mx` A record has to be
added on the router by hand. The `stalwart` Certificate covers `mx` for
the mail protocols. HTTPS terminates at Envoy.

Tailnet devices reach `10.45.10.25` through Connector `home`, on the ports
the tailnet policy grants them ([tailscale.md](../platform/tailscale.md)).

The route is `native`: mail and DAV clients send their own credentials and
cannot complete the gateway's Pocket ID login.

## 1Password

Vault `k8s-secrets`:

| Item | Field | Use |
| --- | --- | --- |
| `stalwart` | `database_password` | Role `stalwart` on `postgres17`. Read by `cnpg-system` and `mail` |
| `stalwart` | `admin_password` | `STALWART_RECOVERY_ADMIN=admin:<password>`. Always accepted as an administrator while set |
| `stalwart` | `cloudflare_api_token` | `STALWART_CLOUDFLARE_TOKEN`. Cloudflare token with `Zone / Zone / Read` and `Zone / DNS / Edit` on zone `holthome.net` only, for automatic DNS ([DNS](#dns)) |
| `stalwart` | `smtp2go_password` | `STALWART_SMTP2GO_PASSWORD`. Password of the SMTP2GO SMTP user, for the interim outbound route ([Outbound](#outbound)) |
| `stalwart` | `smtp2go_username` | That SMTP user's name. Not read by the cluster: it is typed into the route |
| `bulwark` | `session_secret` | `SESSION_SECRET` for Bulwark, at least 32 characters (`openssl rand -base64 32`) |
| `stalwart-r2` | `access_key_id`, `secret_access_key`, `endpoint_url`, `bucket` | The blob copy. Same values as `postgres17-r2`: the same R2 token and bucket, with blobs under `stalwart/blobs/` beside Barman's `cnpg/postgres17/`. Rotating the `postgres17-r2` token means updating both items |

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
   Leave Settings › Network › Proxy › Trusted Networks empty. Every
   connection from a network listed there must start with a PROXY
   header or Stalwart drops it, and nothing here sends one: not Envoy,
   not the edge relay. Client addresses in HTTP logs come from Envoy's
   forwarded headers, which is a separate HTTP setting.

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
6. **Domain**: add `holthome.net`, with DKIM management Automatic (DKIM1
   Ed25519 and RSA), TLS Manual (cert-manager owns the certificate), and
   report address `mailto:postmaster@holthome.net`. Then set up its DNS as
   in [DNS](#dns).
7. **Outbound**: through SMTP2GO for now ([Outbound](#outbound)), and
   through the edge relay (ADR 0014) once Vultr opens its outbound 25.
8. **Directory** (ADR 0015), before creating any account, because
   Stalwart does not move accounts between directories:
   - in Pocket ID, create a public OIDC client for the WebUI (PKCE, no
     secret) with the redirect URI the WebUI shows, and allow the groups
     that should have mail
   - in Pocket ID, also create an API with resource
     `https://mail.holthome.net` (no permissions) and grant it to the
     client for user-delegated access. The WebUI sends that URL as the
     RFC 8707 `resource` parameter, and Pocket ID rejects a resource the
     client has no grant for: "The 'resource' or 'scope' parameter is
     invalid"
   - in Stalwart, add an OIDC directory: issuer `https://id.holthome.net`
     (exactly as Pocket ID reports it), `claimUsername`
     `preferred_username`, `usernameDomain` the mail domain, `claimGroups`
     `groups`, and the client id under `acceptedAudiences`. Set it as
     the directory, and the client id as the WebUI Application's
     `oauthClientId`
   - restart the pod after saving the Application
     (`kubectl -n mail rollout restart deployment stalwart`). Stalwart
     writes `oauthClientId` and the scopes into the WebUI's page when it
     starts, so until then the WebUI sends an empty client id and Pocket
     ID answers "The requested OAuth 2.0 Client does not exist"
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

## DNS

`holthome.net` is the cluster's zone at Cloudflare. external-dns
(`cloudflare-dns`) only touches records it owns, marked by `k8s.`-prefixed
ownership TXT records, so it leaves mail records alone. Stalwart manages
the mail records itself through a Cloudflare DNS provider, with the token
in `STALWART_CLOUDFLARE_TOKEN`. Automatic management is also what lets
Stalwart rotate DKIM keys; with Manual it never rotates them.

| Record type | Owner | Why |
| --- | --- | --- |
| DKIM | Stalwart | Rotation every 90 days, old key retired after 7 |
| MX | Stalwart | Points at `mx.holthome.net`. Publicly that name is the edge VM (an A record added by hand at cutover); on the LAN the MikroTik answers `10.45.10.25` |
| SPF | Stalwart | Authorizes the MX host, which is right because the edge also sends outbound (ADR 0014). SMTP2GO needs no change to it: it sends with its own return-path subdomain |
| SMTP2GO return-path, DKIM and link-tracking CNAMEs | SMTP2GO, added once through its Cloudflare connection | Interim outbound ([Outbound](#outbound)). Names and targets come from SMTP2GO's sender-domain page. Stalwart writes only the names it publishes, and external-dns only records it owns |
| DMARC | Stalwart | Reports to the domain's report address |
| TLS-RPT | Stalwart | Same address |
| CAA | Nobody, for now | `holthome.net` is the whole cluster zone. A CAA record at the apex limits which certificate authorities may issue for every name in it, including Cloudflare's proxied hostnames |
| MTA-STS | Later | Needs `mta-sts.holthome.net` served publicly over HTTPS |
| SRV, autoconfig, autodiscover | Later | They would point at JMAP and DAV on 443, which are not exposed on the mail address |

Setup, in order:

1. In Cloudflare, turn off Email Routing for the zone (it locks its MX
   records and removes them with itself), and delete leftovers from
   earlier tests: the proxied `mail` A and AAAA records (they send IPv6
   clients to Cloudflare instead of `envoy-internal`) and `autodiscover`.
   Mailgun's `include:mailgun.org` and DKIM selector `pic` can go too;
   Pocket ID and Mealie on Forge still name Mailgun as their SMTP server
   and move to Stalwart's submission port before they need mail again.
2. Create the Cloudflare token and store it as `cloudflare_api_token` in
   item `stalwart`. The ExternalSecret needs the field, so do this before
   merging the change that reads it; Reloader restarts the pod.
3. Save the apex TXT records before Stalwart touches the zone. They also
   hold site verifications (`MS=`, `google-site-verification`, keybase),
   and SPF is a TXT record at the same name:

   ```sh
   dig +short TXT holthome.net @adel.ns.cloudflare.com > holthome-apex-txt.before
   ```

4. In Stalwart, Settings › Network › DNS › DNS Providers: add Cloudflare,
   secret EnvironmentVariable `STALWART_CLOUDFLARE_TOKEN`.
5. On domain `holthome.net`: DNS management Automatic, that provider, no
   origin, and publish only DKIM, MX, SPF, DMARC and TLS-RPT.
6. Check against the Cloudflare nameserver, not the MikroTik, and diff
   the apex TXT records against step 3. Restore anything that went
   missing other than the old SPF.

## Outbound

Interim, until the edge relay can send (ADR 0014, "Interim outbound
through SMTP2GO"). Stalwart relays every remote domain to SMTP2GO on
465 with implicit TLS. The egress policy already allows 465 to public
IPv4.

1. **SMTP2GO account** (free plan). Leave Maintain Return-Path off, and
   send bounce notifications to the sender.
2. **Sender domain.** Sending › Verified Senders › Sender domains: add
   `holthome.net`. SMTP2GO can add its three CNAMEs (return path `em…`,
   DKIM, link tracking `link`) to Cloudflare itself; otherwise add them
   by hand, DNS only (not proxied). The link-tracking CNAME does nothing
   while tracking is off. Do not change the apex SPF; it stays
   Stalwart's. Wait until SMTP2GO shows the domain verified.
3. **SMTP user.** Sending › SMTP Users: add one. On its Tracking & Status
   tab, turn Open Tracking and Click Tracking off: they rewrite the body
   and links and break Stalwart's DKIM signature. Store its name and
   password in item `stalwart` as `smtp2go_username` and
   `smtp2go_password`. The ExternalSecret needs `smtp2go_password`, so do
   this before merging the change that reads it; Reloader restarts the
   pod.
4. **Route.** In the WebUI, add an MTA route of type Relay, or:

   ```sh
   stalwart-cli create MtaRoute/Relay --json '{
     "name": "smtp2go",
     "description": "Interim outbound relay (ADR 0014)",
     "host": "mail.smtp2go.com",
     "port": 465,
     "protocol": "smtp",
     "implicitTls": true,
     "allowInvalidCerts": false,
     "authUsername": "<smtp2go_username>",
     "authSecret": {"@type": "EnvironmentVariable",
                    "variableName": "STALWART_SMTP2GO_PASSWORD"}
   }'
   ```

5. **Outbound strategy.** Change the `route` expression of
   MtaOutboundStrategy from its default (`'mx'` for remote domains) to
   send remote domains to the new route:

   ```sh
   stalwart-cli update MtaOutboundStrategy --json '{
     "route": {"else": "'\''smtp2go'\''",
               "match": {"0": {"if": "is_local_domain(rcpt_domain)",
                               "then": "'\''local'\''"}}}
   }'
   ```

   In the WebUI this is Settings › MTA › Outbound › Strategy, Routing:
   keep the `is_local_domain(rcpt_domain)` → `'local'` condition and set
   ELSE to `'smtp2go'`, quotes included. It applies at the next reload.
   Undo it by setting ELSE back to `'mx'`.

   On the same page, delete the TLS condition
   `retry_num > 0 && last_error == 'tls'` → `'invalid-tls'`, leaving ELSE
   `'default'`. That default retries a delivery that failed with a TLS
   error under a strategy that does not validate certificates, and the
   TLS strategy applies to relay hops too, so a forged certificate on the
   second try would receive the SMTP2GO password. Every remote domain
   goes through the relay, so nothing needs the fallback. Leave
   Scheduling and Connection as they are.
6. **DKIM.** Nothing to change. Signing happens in the DATA stage, before
   routing: the default `dkimSignDomain` signs mail from authenticated
   senders on local domains with the domain's active keys. Check that the
   DATA stage expression is still the default. Mail from Pocket ID and
   Mealie is signed once they submit with an account on 587 or 465.

SMTP2GO accepts only senders on its verified domains. Mail with another
domain in the envelope sender, such as a Sieve redirect that keeps the
original sender, is refused and stays in Stalwart's queue.

Test, with an outside mailbox (inbound is not live yet, so use a check
that does not reply by mail):

1. From an account on `holthome.net`, send a message to a Gmail address
   and to the address mail-tester.com gives you.
2. In Stalwart's queue (WebUI, or `stalwart-cli` queue listing) the
   message leaves on route `smtp2go`; SMTP2GO's activity view shows it
   delivered.
3. In Gmail, Show original: SPF `PASS` for SMTP2GO's return-path
   subdomain of `holthome.net`, DKIM `PASS` for `holthome.net`, DMARC
   `PASS`. The headers carry two `DKIM-Signature`s for `d=holthome.net`:
   Stalwart's (`s=v1-rsa`, `s=v1-ed25519`) and SMTP2GO's. Both should
   verify; if Stalwart's fails, something in SMTP2GO rewrote the message
   (tracking).
4. mail-tester.com shows the same results and checks blocklists.

## Webmail

Bulwark (ADR 0017) at `https://webmail.holthome.net`. It signs in with
Pocket ID only, then the browser calls Stalwart's JMAP API at
`mail.holthome.net` with that token. Before the first sign-in:

1. 1Password item `bulwark` with `session_secret`.
2. Pocket ID: a public client `bulwark` (PKCE, no secret), callback
   `https://webmail.holthome.net/en/auth/callback`, gated to `family`.
   Give the API `Stalwart Mail` (`https://mail.holthome.net`) four
   permissions keyed `urn:ietf:params:oauth:scope:mail`, `…:contacts`,
   `…:calendars` and `…:files` (`PUT /api/apis/{id}/permissions`), and
   grant the API to `bulwark` for user-delegated access with all four.
   Without them Stalwart answers 401 to Bulwark's token: it refuses an
   outside client's token that carries none of these scopes. Bulwark
   builds the callback from the browser's locale, so a browser set to
   another language needs that locale's path too.
3. Stalwart: turn on `usePermissiveCors` in the HTTP settings. The
   webmail runs on another origin, and without it the browser blocks
   every JMAP call. It adds `Access-Control-Allow-Origin: *` to every
   response and opens nothing: each call still needs credentials. Saving
   it is not enough: it applies after a pod restart
   (`kubectl -n mail rollout restart deployment stalwart`).

Each browser keeps its own Bulwark settings. Settings sync and Bulwark's
admin dashboard are off, and the pod keeps nothing, so a restart costs
nothing but a fresh page load.

## Restore

1. Restore `postgres17` (or just database `stalwart`) to the chosen time,
   as in [postgres17.md](../platform/postgres17.md).
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
4. **Public DNS.** Stalwart in the cluster already publishes the MX
   (`mx.holthome.net`, see [DNS](#dns)). At cutover, add a public A
   record for `mx.holthome.net` pointing at the VM. On the LAN,
   `mx.holthome.net` stays `10.45.10.25`.
5. Export the edge's configuration with `stalwart-cli snapshot` too.

Adding an address: create the account in the cluster (ADR 0015) and add
the address to the edge's recipient list.

## Not in this tree yet

- **Outbound through the edge.** A residential address will be rejected
  or spam-foldered, so outbound goes through the edge VM, whose address
  has a matching PTR (ADR 0014). That needs Vultr to open its outbound
  25, a way from the cluster to the tailnet (such as an operator egress
  Service), and a policy rule; the current egress rule excludes
  100.64.0.0/10. Until then it goes through SMTP2GO ([Outbound](#outbound)).
  At the switch, point the outbound strategy at the edge's route, then
  remove the SMTP2GO CNAMEs, field `smtp2go_password` and its
  ExternalSecret entry, and close the account.
- **Webmail.** Stalwart has no bundled webmail. Native clients work over
  IMAP or JMAP.
- **More than one replica.** Needs a shared in-memory store (Redis or
  Valkey) and Stalwart's cluster settings.
