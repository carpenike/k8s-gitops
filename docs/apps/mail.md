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
   4, no PROXY protocol. Listeners bind at startup, so restart the pod
   afterwards (`kubectl -n mail rollout restart deployment stalwart`); a
   settings reload validates a new listener but does not open it. Mail on
   it was already checked by the edge relay and arrives from a Connector
   pod's address, so:
   - MtaStageAuth `require` defaults to `local_port != 25`, which answers
     the edge's MAIL FROM with `503 You must authenticate first`. Set it
     to `local_port != 25 && listener != 'smtp-edge'`, and add the same
     `listener != 'smtp-edge'` condition to `saslMechanisms` so the
     listener offers no AUTH
   - MtaStageData `enableSpamFilter`:
     `is_empty(authenticated_as) && listener != 'smtp-edge'`
   - nothing to change for SPF, DMARC and reverse DNS: their default
     expressions on SenderAuth already run only when `local_port == 25`

   The edge's spam verdict arrives as its `X-Spam-Score` header
   (`spam, score=…` or `ham, score=…`). A system Sieve script cannot file
   into a mailbox (at DATA it can only reject, discard or edit), so filing
   that mail into Junk is a rule in each user's own Sieve script:

   ```sieve
   require ["fileinto"];
   if header :contains "X-Spam-Score" "spam," { fileinto "Junk"; }
   ```

   Without it, mail the edge scored between its spam and reject
   thresholds reaches the inbox, tagged.

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
| CAA at the apex | Nobody, for now | `holthome.net` is the whole cluster zone. A CAA record at the apex limits which certificate authorities may issue for every name in it, including Cloudflare's proxied hostnames |
| CAA at `mx.holthome.net` | The edge's Stalwart | Let's Encrypt, bound to the edge's ACME account. It covers `mx.holthome.net` and the names under it only ([Edge relay](#edge-relay-adr-0014)) |
| MTA-STS | Later | Needs `mta-sts.holthome.net` served publicly over HTTPS ([MTA-STS](#mta-sts)) |
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
`10.45.10.25:2525`. The VM is NixOS host `mx-edge` in the nix-config
repo; its Stalwart settings live in its own store, not in either repo.

1. **VM.** A small Vultr instance with a static IPv4. Firewall: public
   25 only, plus Tailscale's UDP. Set the reverse DNS of the address to
   `mx.holthome.net`.
2. **Tailscale.** Join with tag `tag:mx-edge` and `--accept-routes`. The
   grant lets it reach `10.45.10.25` on `tcp:2525` and nothing else.
   Check from the VM: `nc -vz 10.45.10.25 2525`. Turn tailnet DNS off
   (`tailscale set --accept-dns=false`): MagicDNS sends `holthome.net` to
   the MikroTik, which the tag may not reach, so every lookup under it
   times out and each SMTP step waits 15 s. The edge resolves through a
   local unbound instead, which DNS blocklists such as Spamhaus also
   require (they refuse queries from large shared resolvers).
3. **Stalwart, MTA only.** Same version as the cluster. Its own
   RocksDB store on the VM's disk holds the queue and its configuration.
   Manage it over the tailnet on 8080. `holthome.net` is not a Domain on
   the edge: a local domain would be delivered locally, not relayed.
   - **Certificate.** A DnsServer `Cloudflare` reading
     `STALWART_CLOUDFLARE_TOKEN`, an AcmeProvider (Let's Encrypt,
     challenge `Dns01`, contact `postmaster@holthome.net`), and a Domain
     `mx.holthome.net` with certificate management Automatic, DKIM
     Manual, and DNS management Automatic with origin `holthome.net` and
     `publishRecords` `caa` only. The certificate covers
     `mx.holthome.net` and `*.mx.holthome.net`. Publishing only CAA keeps
     the edge away from the records the cluster's Stalwart owns
   - **Recipients.** MtaStageRcpt `allowRelaying` names every address,
     `else` `false`. Never accept the whole domain, or the edge bounces
     mail to forged senders. People also get their sub-addresses:

     ```text
     rcpt_domain == 'holthome.net' && (rcpt == 'ryan@holthome.net' ||
       starts_with(rcpt, 'ryan+') || … || rcpt == 'postmaster@holthome.net')
     ```

     Unknown addresses and other domains get `550 5.7.1 Relay not
     allowed`
   - **Route.** `MtaRoute/Relay` `cluster` to `10.45.10.25` port 2525,
     STARTTLS (`implicitTls` false), `allowInvalidCerts` true: the edge
     connects by address, so the name check would fail, and the hop
     already runs inside the tailnet. MtaOutboundStrategy `route`: keep
     `is_local_domain(rcpt_domain)` → `'local'`, add
     `rcpt_domain == 'holthome.net'` → `'cluster'`, `else` `'mx'`
   - **Sender checks.** SenderAuth `dmarcVerify` `strict` when
     `local_port == 25` (the default `relaxed` records a failure but
     accepts the mail), so `p=reject` domains, `holthome.net` included,
     are refused with `550 5.7.1 Email rejected per DMARC policy`
   - **Spam filter.** SpamSettings `scoreReject` 15 (the default 0
     rejects nothing). Accepted mail carries `X-Spam-Score`
   - **Queue.** MtaDeliverySchedule `remote` expiry 7 days (default 3),
     to cover a cluster rebuild
   - **Listeners.** Only `smtp` (25) and `http` (8080); delete the rest.
     Restart Stalwart after changing listeners
   - **Logs.** A `Stdout` tracer; the default `Log` tracer writes to
     `/var/log/stalwart`, which the container does not have
4. **Public DNS.** Stalwart in the cluster already publishes the MX
   (`mx.holthome.net`, see [DNS](#dns)). At cutover, add a public A
   record for `mx.holthome.net` pointing at the VM. On the LAN,
   `mx.holthome.net` stays `10.45.10.25`.
5. Export the edge's configuration with `stalwart-cli snapshot` too.

Checks, from the VM against `127.0.0.1:25` (a residential line usually
blocks outbound 25, so a laptop at home cannot test it): an address on
the list relays and shows up in the cluster's log as `message-ingest`;
an unknown address and an outside domain get `550 Relay not allowed`;
a sender in `@holthome.net` gets the DMARC rejection.

Adding an address: create the account in the cluster (ADR 0015) and add
the address to the edge's `allowRelaying` expression.

## MTA-STS

Follow-up, after the cutover to the edge has carried real mail for a
week or two. MTA-STS tells sending servers to deliver only over TLS
with a valid certificate for the MX, which closes STARTTLS stripping.
It fails closed: with `enforce`, a lapsed edge certificate or an MX
that no longer matches the policy makes compliant senders hold or bounce
mail, and they cache the policy for `max_age`.

1. **Read the TLS reports first.** TLS-RPT is already published, so
   senders mail daily reports to `postmaster@holthome.net`. They should
   show successful TLS sessions to the edge and no failures.
2. **Serve the policy.** `https://mta-sts.holthome.net/.well-known/mta-sts.txt`,
   publicly, with a valid certificate. Not from the edge: its
   certificate does not cover that name and it has no public 443. An
   HTTPRoute on `envoy-external` for `mta-sts.${SECRET_DOMAIN}`, path
   `/.well-known/mta-sts.txt` only, to Service `stalwart` port 8080 if
   Stalwart serves the policy there (check with `curl` against the pod
   first), or else a static file.
   Senders keep their cached copy, so the host being down during a
   cluster outage does not stop mail.
3. **Publish in `testing` mode.** `mx: mx.holthome.net`, `max_age` about
   a day. Add `mtaSts` to the Domain's `publishRecords` so Stalwart
   publishes `_mta-sts` and changes its `id` with the policy. Senders
   report failures but still deliver.
4. **Enforce.** After a few weeks of clean reports, switch to `enforce`
   and raise `max_age` to about a week.

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
- **MTA-STS.** Planned once the edge carries real mail ([MTA-STS](#mta-sts)).
- **More than one replica.** Needs a shared in-memory store (Redis or
  Valkey) and Stalwart's cluster settings.
