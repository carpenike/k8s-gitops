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
| `mx.holthome.net` | `10.45.10.25`, Service `stalwart-mail` | SMTP 25, 465, 587; IMAP 993; ManageSieve 4190; `smtp-edge` 2525 from the edge relay only |
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
| `stalwart` | `cloudflare_api_token` | `STALWART_CLOUDFLARE_TOKEN`. Cloudflare token with `Zone / Zone / Read` and `Zone / DNS / Edit` on zones `holthome.net`, `ryanholt.net`, `stefanieholt.com` and `devialea.com`, for automatic DNS ([DNS](#dns), [More mail domains](#more-mail-domains)) |
| `stalwart` | `smtp2go_password` | `STALWART_SMTP2GO_PASSWORD`. Password of the SMTP2GO SMTP user, for the outbound route ([Outbound](#outbound)) |
| `stalwart` | `smtp2go_username` | That SMTP user's name. Not read by the cluster: it is typed into the route |
| `stalwart` | `metrics_password` | `STALWART_METRICS_PASSWORD`. Basic auth for `/metrics/prometheus`, shared with the ServiceMonitor ([Metrics](#metrics)) |
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
   an empty store. Delete `pop3s` (995): nothing here uses POP3, and the
   Service and network policy do not carry it. Delete `https` (443): HTTPS
   terminates at envoy-internal, which reaches Stalwart on 8080, so 443
   was never reachable. Add `submission` on 587 (STARTTLS): the Service
   and the network policy already carry 587, and many mail apps default
   to it. Leave Settings › Network › Proxy › Trusted Networks empty. Every
   connection from a network listed there must start with a PROXY
   header or Stalwart drops it, and nothing here sends one: not Envoy,
   not the edge relay.

   **Client addresses and bans.** Stalwart bans an address after 100
   failed logins, 35 abuse events or 30 scan hits a day, and applies the
   HTTP rate limits per address. Two paths share one address unless this
   is set:
   - HTTP arrives from envoy-internal. Set Http `clientIpSource`
     `xForwardedFor` with `forwardedHops` 1, so the address is the one
     Envoy appends. Only envoy-internal reaches 8080 (network policy), so
     nobody can supply the header directly. With `peer`, the default,
     every web, Bulwark and JMAP user was one address
   - tailnet clients and the edge relay's 2525 arrive from a Connector
     pod. Add Allowed IP `10.42.0.0/16` (the pod network: Envoy, the
     Connector, Hermes agents), which is never banned or rate limited.
     Otherwise one phone retrying a stale app password could ban the
     Connector, and with it inbound mail from the edge

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

   Installed 2026-11-23 for `ryan` and `stefanie` as their active script
   `filters`, filing into `Junk Mail` (Stalwart's name for the junk
   folder) with `stop`, under a `# rule:[…]` comment. Bulwark reads a
   script in that form as an external rule, shows it on its Filters page
   and keeps it when its own filters are saved. The rule runs on the
   server, so it applies whatever mail app is used. Only one script is
   active per account: an app that manages Sieve over ManageSieve would
   replace it with its own. Chief needs none; its allowlist drops spam.

   The network policy and the tailnet grant are what keep everyone but
   the edge off this listener. Do not open 2525 anywhere else.
6. **Domain**: add `holthome.net`, with DKIM management Automatic (DKIM1
   Ed25519 and RSA), TLS Manual (cert-manager owns the certificate), and
   report address `mailto:postmaster@holthome.net`. Then set up its DNS as
   in [DNS](#dns). Set ReportSettings `outboundReportDomain`
   `holthome.net`: unset, bounces and reports come from
   `MAILER-DAEMON@localhost.local`, unsigned.
   Then, in Settings › Network › General, set `defaultHostname`
   `mx.holthome.net` and the default domain `holthome.net`. A new store
   leaves the hostname blank and the default domain pointing at nothing,
   and Stalwart falls back to `STALWART_HOSTNAME`. The hostname goes into
   `Received` and `Message-ID` headers, bounces and reports, and the MX
   it publishes, and has to match the edge's reverse DNS and the
   certificate. The form will not save the hostname without a valid
   default domain.
7. **Outbound**: through SMTP2GO ([Outbound](#outbound)). The edge relay
   is the fallback (ADR 0014).
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
     `preferred_username`, `usernameDomain` the mail domain, no
     `claimGroups`, and the client id under `acceptedAudiences`. Set it as
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
| SPF | Stalwart | Authorizes the MX host, the edge, which sends its own DMARC reports and is the fallback outbound route (ADR 0014). SMTP2GO needs no change to it: it sends with its own return-path subdomain |
| SMTP2GO return-path, DKIM and link-tracking CNAMEs | SMTP2GO, added once through its Cloudflare connection | Outbound ([Outbound](#outbound)). Names and targets come from SMTP2GO's sender-domain page. Stalwart writes only the names it publishes, and external-dns only records it owns |
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

Through SMTP2GO, the standing route since 2026-11-25 (ADR 0014,
"Outbound through SMTP2GO"). The edge takes over only if SMTP2GO's terms
stop allowing this use or the household outgrows its free plan (1,000 a
month, 200 a day). Stalwart relays every remote domain to SMTP2GO on 465
with implicit TLS. The egress policy already allows 465 to public IPv4.

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

### Through the edge

One destination, `mail.grokbot.com`, goes through the edge relay instead
(ADR 0014, "Fallback path through the edge"): a mail rule forwards
Planning Center notices there, and SMTP2GO refuses a redirect that keeps
Planning Center as the sender. The edge delivers it unchanged.

1. **Password.** Field `edge_relay_password` in item `stalwart`, 40
   random characters. The ExternalSecret reads it as
   `STALWART_EDGE_RELAY_PASSWORD`; Reloader restarts the pod.
2. **Tailnet grant.** `tag:k8s` to `tag:mx-edge` includes `tcp:587`
   ([tailscale.md](../platform/tailscale.md)).
3. **Edge firewall.** Public 587 stays closed: NixOS opens only 25 to
   the internet. Tailscale's own `ts-input` chain runs before NixOS's and
   accepts everything on `tailscale0`, so on the tailnet the grant is the
   gate. nix-config `hosts/mx-edge/stalwart.nix` also lists 587 on
   `tailscale0`, which matters only if Tailscale stops managing the
   firewall.
4. **Edge Stalwart**, over its admin API on 8080:
   - Account `relay` (User, domain `mx.holthome.net`) with that password
   - NetworkListener `relay`: SMTP on `[::]:587`, STARTTLS. Restart
     Stalwart afterwards
   - MtaStageAuth `require` stays `local_port != 25`, and SASL is offered
     only over TLS off port 25, as before. `mustMatchSender`: false for
     the relay account, else true, because a redirect carries the
     original envelope sender
   - MtaStageRcpt `allowRelaying` gains, before `else`: `local_port ==
     587 && authenticated_as == 'relay@mx.holthome.net' && rcpt_domain ==
     'mail.grokbot.com'` → true. A leaked password relays to that domain
     only. `authenticated_as` is the full login, as `auth.success` logs it
   - Its outbound strategy already sends that domain to its MX
5. **Egress.** Service `mx-edge-relay` (annotation
   `tailscale.com/tailnet-ip`, port 587) and the network policy rule for
   its proxy pods.
6. **Route.** `MtaRoute/Relay` `edge` to
   `mx-edge-relay.mail.svc.cluster.local` port 587, `implicitTls` false,
   `allowInvalidCerts` true (it connects by Service name, inside the
   tailnet), user `relay@mx.holthome.net`, secret
   EnvironmentVariable `STALWART_EDGE_RELAY_PASSWORD`. Then
   MtaOutboundStrategy `route` gains `rcpt_domain == 'mail.grokbot.com'`
   → `'edge'` between `'local'` and the SMTP2GO `else`.

Check before step 6: from outside the tailnet, 587 on the edge's public
address is closed; through the tailnet, an unauthenticated session is
refused relay, and the relay login to another domain gets `550 Relay
not allowed`. After step 6, a message from `ryan@ryanholt.net` to the
Grok address leaves on route `edge` and passes SPF (the domain's SPF is
`mx`, and the MX is the edge), DKIM and DMARC. Undo by removing the
route condition.

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

## Metrics

Stalwart serves Prometheus metrics (`stalwart_*`) at `/metrics/prometheus`
on its HTTP listener, 8080. The HTTPRoute sends every path on
`mail.holthome.net` there, so the endpoint takes Basic auth:

- 1Password item `stalwart`, field `metrics_password` (any strong
  random value). ExternalSecret `stalwart-metrics` turns it into
  `STALWART_METRICS_USERNAME` (`prometheus`) and
  `STALWART_METRICS_PASSWORD`; the pod gets both through `envFrom`
- In the WebUI, Settings › Telemetry › Metrics › Prometheus: `Enabled`,
  user `prometheus`, secret EnvironmentVariable
  `STALWART_METRICS_PASSWORD`. Set it only after the pod has the
  variable, or the endpoint stays off
- The app-template ServiceMonitor scrapes every 60 s with the same
  Secret, and the network policy admits the Prometheus pods on 8080

Check: `curl -s -u prometheus:<password>
https://mail.holthome.net/metrics/prometheus | head` returns
`stalwart_` series, and without the password it returns 401.

If the ServiceMonitor reaches the cluster before Secret
`stalwart-metrics` exists (the 1Password field was missing, or the
ExternalSecret was slower), the Prometheus operator rejects it with
`unable to get secret "stalwart-metrics"` and does not try again when the
Secret appears; an annotation does not wake it either. Restart the
operator (`kubectl -n observability rollout restart deploy
kube-prometheus-stack-operator`) and the target comes up on the next sync.

## Upgrading Stalwart

Renovate opens the image bump. Read the release notes before merging: a
minor release can need steps the image does not do itself. A newer
release may write data an older one cannot read, so the way back is the
restore below, not the old tag. Check that the latest `postgres17`
backup and the hourly blob copy (`stalwart-blobs-r2`) succeeded first.

The Recreate strategy means mail stops for the restart, about a minute.
Senders retry, so nothing is lost.

After the new pod is ready, do the release's manual steps as the
recovery admin, over JMAP or in the WebUI. For 1.2 there were two:

- New permissions on the default roles. Roles created by an older
  release do not get them. `x:Authentication` `singleton` names the
  default roles: User `b`, Group `c`, System Administrator `e`. Add each
  name with an `x:Role/set` patch such as
  `"enabledPermissions/sysMailRuleGet": true`, so the existing set is
  kept. For 1.2 that was the `sysMailRule*`, `sysBlockedSender*`,
  `sysSafeSender*` and `sysCalendarSettings*` permissions on all three
  roles, and `sysExchangeGet` and `sysExchangeUpdate` on the
  administrator role. Restarting once with
  `STALWART_UPDATE_ROLE_PERMISSIONS=true` does the same, but needs a
  second change and restart to take the variable out again.
- A newer WebUI. Stalwart downloads the WebUI bundle from GitHub
  (`x:Application`, release `v2`) and keeps it for 90 days, so a server
  upgrade does not refresh it. Run `x:Action/set` with
  `{"@type": "UpdateApps"}` (Management › Actions in the WebUI) to fetch
  it now.

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
     mail to forged senders. People also get their sub-addresses. One
     condition per mail domain, so `starts_with` stays inside it:

     ```text
     rcpt_domain == 'holthome.net' && (rcpt == 'ryan@holthome.net' ||
       starts_with(rcpt, 'ryan+') || … || rcpt == 'postmaster@holthome.net')
     rcpt_domain == 'ryanholt.net' && (rcpt == 'ryan@ryanholt.net' ||
       starts_with(rcpt, 'ryan+'))
     ```

     Unknown addresses and other domains get `550 5.7.1 Relay not
     allowed`
   - **Route.** `MtaRoute/Relay` `cluster` to `10.45.10.25` port 2525,
     STARTTLS (`implicitTls` false), `allowInvalidCerts` true: the edge
     connects by address, so the name check would fail, and the hop
     already runs inside the tailnet. MtaOutboundStrategy `route`: keep
     `is_local_domain(rcpt_domain)` → `'local'`, add
     `rcpt_domain == 'holthome.net' || rcpt_domain == 'ryanholt.net' ||
     rcpt_domain == 'stefanieholt.com' || rcpt_domain == 'devialea.com'`
     → `'cluster'`, `else` `'mx'`. Set `tls` to just `'default'`: the
     default rule `retry_num > 0 && last_error == 'tls'` → `'invalid-tls'`
     retries a failed TLS delivery without checking the certificate
   - **Hostname.** `defaultHostname` `mx.holthome.net`, default domain
     `mx.holthome.net`, for the same reasons as the cluster's
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
   - **Reports.** ReportSettings `outboundReportDomain`
     `mx.holthome.net`. The edge mails daily DMARC aggregate reports to
     the domains that sent it mail, from `noreply-dmarc@` that domain.
     Unset, it is `localhost.local`, which receivers defer or junk. The
     `v=spf1 a -all` record on `mx.holthome.net` covers the VM, so the
     reports pass SPF and DMARC. Vultr already allows outbound 25 from
     this VM
4. **Public DNS.** Stalwart in the cluster already publishes the MX
   (`mx.holthome.net`, see [DNS](#dns)). The cutover is a public A
   record for `mx.holthome.net` pointing at the VM, DNS only (not
   proxied), plus reverse DNS for the VM's address set to
   `mx.holthome.net` in Vultr. On the LAN, `mx.holthome.net` stays
   `10.45.10.25`.
5. Export the edge's configuration with `stalwart-cli snapshot` too.

Checks, from the VM against `127.0.0.1:25` (a residential line usually
blocks outbound 25, so a laptop at home cannot test it): an address on
the list relays and shows up in the cluster's log as `message-ingest`;
an unknown address and an outside domain get `550 Relay not allowed`;
a sender in `@holthome.net` gets the DMARC rejection.

Adding an address: create the account in the cluster (ADR 0015) and add
the address to the edge's `allowRelaying` expression. Adding a domain:
also add it to the edge's `route` expression, or the edge sends its mail
to the domain's MX instead of the cluster.

## Monitoring the edge

The cluster's Prometheus scrapes the Vultr edge over the tailnet:

| Piece | Where |
| --- | --- |
| node-exporter on 9100, systemd collector, open on `tailscale0` only | nix-config `hosts/mx-edge/monitoring.nix` |
| Stalwart's `/metrics/prometheus` on 8080 (already tailnet only), Basic auth `prometheus` | the edge's Metrics › Prometheus, secret `Value` set over its admin API |
| Egress Service `observability/mx-edge` (`tailscale.com/tailnet-ip`), ExternalSecret `mx-edge-metrics`, ScrapeConfigs `mx-edge-node` and `mx-edge-stalwart` | `kubernetes/apps/observability/kube-prometheus-stack/app/monitors/mx-edge.yaml` |
| Alerts for both servers | `kubernetes/apps/mail/stalwart/app/prometheusrule.yaml` |

- **Tailnet grant:** `tag:k8s` to `tag:mx-edge` on `tcp:8080` and
  `tcp:9100` ([tailscale.md](../platform/tailscale.md)). The operator
  runs the egress proxy as `tag:k8s`.
- **Password:** 1Password item `mx-edge`, field `metrics_password`. Store
  it before the ScrapeConfig reaches the cluster: like the
  ServiceMonitor in [Metrics](#metrics), the operator rejects a scrape
  whose Basic-auth Secret is missing and does not retry until restarted.
- **Tailnet address:** the egress Service names the edge by its tailnet
  IP, which changes if the VM re-joins the tailnet. Update the
  annotation after a rebuild.
- **Alerts:** the edge unreachable, its Stalwart down or its container
  unit inactive, a failed nightly upgrade, its disk over 85%, the edge
  accepting mail but delivering none for an hour, deliveries being
  retried on either server, the cluster's Stalwart down, and over 30
  failed logins in 15 minutes. Queue size itself is not alerted on:
  Stalwart exports that gauge only in the Enterprise edition. Nothing
  exports the edge's certificate expiry, so it has no alert.

## More mail domains

`ryanholt.net` and `stefanieholt.com` move here from Microsoft 365
(tenant `holt.onmicrosoft.com`). `devialea.com` moves from Cloudflare
Email Routing, which only forwards and has no mailbox to copy. All three
zones are at Cloudflare.

Accounts stay in `holthome.net`. The OIDC directory appends
`usernameDomain` to the bare Pocket ID username, so a sign-in always asks
for `<username>@holthome.net`. An account moved to another domain no
longer matches, and the next sign-in creates a new, empty
`<username>@holthome.net` account. Moving the old one back then fails
with `primaryKeyViolation` until the new one is deleted. Delete it and
move the old one in the same JMAP request, because an open WebUI or
Bulwark tab signs in again within seconds and recreates it. The other
domains' addresses are aliases on the `holthome.net` account:

| Address | Account |
| --- | --- |
| `ryan@ryanholt.net` | `ryan@holthome.net` |
| `stefanie@stefanieholt.com` | `stefanie@holthome.net` |
| `design@devialea.com` | `stefanie@holthome.net` |

`claimUsername` `email` would not work instead: Pocket ID's email is
not always an address this server hosts.

A Domain in Stalwart is local from the moment it exists. Mail that this
server's users send to it stays here, even while its MX still points at
Microsoft 365. Microsoft 365 does the same for mail between its own
users until the domain is removed from the tenant. An address on the
domain that is not an alias here bounces for this server's users, so
add every address the old host had.

Done (2026-11-18): the three Domains exist (DKIM Automatic, DNS management
Manual, report address `postmaster@holthome.net`), the aliases are set,
and the edge accepts and routes all three.

`ryanholt.net` cut over on 2026-11-24 (steps 1 to 6). Step 7 is still
open. `stefanieholt.com` and `devialea.com` have not moved yet.

Cutover, per domain:

1. **Cloudflare token.** Add the zone to the token in
   `cloudflare_api_token` (Zone DNS Edit), then set the Domain's DNS
   management to Automatic with the Cloudflare provider and publish
   DKIM only. With Manual, Stalwart never rotates the DKIM keys.
2. **Apex TXT.** Save it first, as for `holthome.net`
   ([DNS](#dns)). Keep any `MS=` verification until the domain is
   removed from the tenant.
3. **SMTP2GO.** Add the domain under Verified Senders › Sender domains
   and let SMTP2GO add its CNAMEs through its Cloudflare connection.
   SMTP2GO refuses mail from a sender domain it has not verified. The
   account lives on `app-us.smtp2go.com`; a page opened on
   `app.smtp2go.com` lands on the login screen even when signed in.
   Set up automatically hands off to Cloudflare, which asks for a
   Cloudflare sign-in and then adds three DNS-only CNAMEs: `em<id>`
   (return path), `s<id>._domainkey` (DKIM) and `link` (tracking).
   Press Verify on the domain's page afterwards.
4. **Mailbox.** Copy the Microsoft 365 mailbox into the account (not
   for `devialea.com`), as in [Copying a mailbox](#copying-a-mailbox).
5. **Records.** For `devialea.com`, first turn off Email Routing for
   the zone: it locks its MX records and deletes them with itself. Its
   SPF include and its Cloudflare DMARC report address go too.
   For the other two, add `mx`, `spf`, `dmarc` and `tlsRpt` to the
   Domain's `dnsManagement.publishRecords`, next to `dkim`. Saving that
   publishes nothing by itself. Queue the publish as a task:

   ```json
   ["x:Task/set", {"create": {"t": {"@type": "DnsManagement",
     "domainId": "<domain id>", "onSuccessRenewCertificate": false,
     "updateRecords": {"mx": true, "spf": true, "dmarc": true,
                       "tlsRpt": true}}}}, "0"]
   ```

   Stalwart then replaces the record sets it owns at each name: the
   Microsoft MX goes, the old SPF is swapped for Stalwart's while other
   apex TXT values such as `MS=` stay, and DMARC (now `p=reject`) and
   TLS-RPT report to `postmaster@holthome.net` instead of
   `ryan@ryanholt.net`. Delete what is left by hand: the `selector1`
   and `selector2` DKIM CNAMEs and the `autodiscover` CNAME. The Teams
   and Intune records (`sip`, `lyncdiscover`, the SIP SRV records,
   `enterpriseenrollment`, `enterpriseregistration`) are not mail; they
   go when the domain leaves the tenant.
6. **Check.** Mail from outside arrives through the edge, mail sent from
   the alias passes DKIM and DMARC at Gmail, and nothing new arrives in
   Microsoft 365 or through Cloudflare's forwarding. Send the test from
   an address on another domain: a Gmail "Send mail as" alias for the
   domain relays through whatever SMTP server it was set up with, and
   with `p=reject` that fails DMARC unless the server is Stalwart.
7. **Retire.** After a few quiet days, run the copy once more, remove
   the domain from the tenant, and drop any `MS=` record.

### Copying a mailbox

[Vandelay](https://stalw.art/docs/migration/), Stalwart's migration
tool, copies a mailbox in two steps that meet at a local SQLite
archive. `vandelay import exchange-graph` reads the Microsoft 365
mailbox over Microsoft Graph, and `vandelay export` writes the archive
to the Stalwart account over JMAP.

It runs in Deployment `stalwart-migration` (`stalwart/migration/`, a
separate Flux Kustomization), because an archive is about the size of
the mailbox. The archives sit on its 60 GiB `ceph-block` volume, which
can be grown. The pod fetches the pinned Vandelay release and checks
its SHA-256 at start, then idles. Each step is a `kubectl exec`. The
toolbox is temporary: remove the directory and its Kustomization once
the domains have moved, which deletes the volume and the archives.

Graph sign-in uses Entra app `Vandelay mail migration` in the tenant: a
public client with no secret, single tenant, with admin consent for
`User.Read Mail.Read MailboxSettings.Read Calendars.Read Contacts.Read
Files.Read offline_access`. Those are delegated permissions, so the app
reads only the mailbox of whoever signs in. Its client ID is on the
app's Overview page in Entra. Delete the app after the last copy.

Per mailbox, here Ryan's:

```sh
kubectl -n mail exec -it deploy/stalwart-migration -- \
  vandelay import exchange-graph --objects mail \
    --client-id <client id> --tenant holt.onmicrosoft.com \
    ryan-m365.sqlite
```

It prints a code for <https://login.microsoft.com/device>. The mailbox's
owner signs in there. Then compare, and write:

```sh
kubectl -n mail exec -it deploy/stalwart-migration -- sh -c \
  'vandelay export --dry-run --url "$STALWART_URL" --auth-basic admin \
     --account-name ryan@holthome.net --objects mailbox,email \
     ryan-m365.sqlite'
```

Run it again without `--dry-run` to write. The export signs in as the
recovery administrator (`VANDELAY_PASSWORD`, from field
`admin_password` of item `stalwart`) and writes to the named account.

- `--objects mailbox,email` matters. Without it the export also sets
  the account's active Sieve script to the archive's, and a Microsoft
  365 archive has none, so it would switch off the account's `filters`
  script and its Junk rule.
- The export matches each message with the account by its Message-ID
  header, in any folder, and creates only what matches nothing. Running
  it again, or after mail has already arrived here, creates no
  duplicates. A message that already exists keeps its folder and flags.
- Running the import again reads only messages new since the last run.
  Read state and folder moves made in Outlook after the first import
  are not copied. The final pass after the MX switch is the same two
  commands.
- Size. Ryan's mailbox (2026-11-24) was a 22 GB archive of 327,327
  messages. The import took nearly 6 hours, mostly Graph throttling
  (HTTP 429, retried). 23 messages failed with HTTP 500 from Graph on
  every retry. The export of 290,346 messages took about 1.5 hours and
  added about 5 GB to database `stalwart` on postgres17, whose volume
  was raised to 60Gi first ([postgres17](../platform/postgres17.md)).
  Message bodies go to the Ceph bucket.

#### Leaving folders out

Vandelay has no folder filter. To skip folders, copy the archive and
delete them from the copy, then export the copy. The original stays
whole, so a later import still knows which messages it has fetched;
trim again after each import. The pod has no `sqlite3`; Alpine's
`sqlite`, `sqlite-libs`, `readline`, `libncursesw` and `zlib` packages
unpacked into `/tmp` run with `LD_LIBRARY_PATH` pointing at their
`usr/lib`. The archive keeps each message's folders in
`emails.mailbox_ids` (a JSON array of `mailboxes.id`) and the Graph IDs
in `sync_id_exchange_graph`:

```sql
-- in sqlite3: .backup ryan-export.sqlite  (from ryan-m365.sqlite, -readonly)
-- then on ryan-export.sqlite, with <ids> the folders to drop:
CREATE TEMP TABLE drop_emails AS SELECT e.id FROM emails e
  WHERE NOT EXISTS (SELECT 1 FROM json_each(e.mailbox_ids) j
                    WHERE j.value NOT IN (<ids>));
DELETE FROM sync_id_exchange_graph
  WHERE type_name = 'email' AND local_id IN (SELECT id FROM drop_emails);
DELETE FROM emails WHERE id IN (SELECT id FROM drop_emails);
DELETE FROM blobs WHERE id NOT IN (SELECT blob_id FROM emails);
DELETE FROM sync_id_exchange_graph
  WHERE type_name = 'mailbox' AND local_id IN (<ids>);
DELETE FROM mailboxes WHERE id IN (<ids>);  -- children before parents
```

`vandelay inspect <archive> mailbox` lists the folders with their
message counts; the IDs come from `SELECT id, name, parent_id FROM
mailboxes`. Ryan's copy left out `RSS Feeds` and `Sync Issues` and kept
`Clutter`.

#### Messages over 50 MB

The export skips a message larger than Stalwart's JMAP upload limit
(`maxUploadSize`, 50 MB) and says a re-run will not help. To copy one,
raise four settings over JMAP as the recovery administrator, run
`x:Action/set` `ReloadSettings`, export again, then put them back and
reload:

| Setting | Default | For a 177 MB message |
| --- | --- | --- |
| `Jmap.maxUploadSize` | 50000000 | 200000000 |
| `Jmap.uploadQuota` (per account, per `uploadTtl`) | 50000000 | 500000000 |
| `Email.maxMessageSize` | 75000000 | 200000000 |
| `SystemSettings.maxBufferedMemory` | unset (512 MiB) | 1610612736 |

The last one matters even after the upload limits are raised.
`Email/import` reserves twice a message's size from the memory budget,
a read may take at most three quarters of the budget, and Vandelay puts
several messages in one call even with `-j 1`; otherwise the import
answers `serverUnavailable` and the log shows `limit.memory-budget`.
The pod's memory limit is 2Gi. The JMAP session's `maxSizeUpload` shows
whether a reload took effect.

## Agent mailboxes

A bot reads its own mailbox with Hermes' `email` platform (IMAP and
SMTP). Hermes acts only on mail from an allowlisted sender whose topmost
`Authentication-Results` header comes from the pinned server name,
`mx.holthome.net`, and reports DMARC pass or aligned SPF or DKIM pass.

Mail from outside gets that header from the edge (port 25). Mail a
household user sends from this server (Bulwark over JMAP, a mail app on
465 or 587) gets none: Stalwart adds `Authentication-Results` only on
port 25, and mail from the edge arrives on 2525. So system Sieve script
`agent-auth-results` runs at the DATA stage for every authenticated
session (MtaStageData `script`: `!is_empty(authenticated_as)` →
`'agent-auth-results'`). JMAP submissions pass through the same stage.
The script:

- removes any `Authentication-Results` the client wrote, from every
  authenticated submission. Without this, a stolen app password could
  submit a forged `mx.holthome.net; dmarc=pass` header and nothing would
  be added above it
- adds one to mail for the listed agent mailboxes when the `From` header
  holds exactly the envelope sender. `mustMatchSender` has already tied
  the envelope sender to the account, its aliases and its groups; it does
  not look at `From`

```sieve
require ["variables", "envelope", "editheader", "relational", "comparator-i;ascii-numeric"];

# Authenticated submissions only (SMTP 587/465 and JMAP). MtaStageData selects
# this script only when authenticated_as is set; the test repeats that.
if not string :is "${env.authenticated_as}" "" {
    # A client never gets to supply its own Authentication-Results.
    deleteheader "Authentication-Results";

    # Stamp mail to the agent mailboxes, but only when the From header is
    # exactly the envelope sender, which mustMatchSender has already verified.
    # Agent mailboxes, with their plus-addresses: list each one here.
    if allof (envelope :all :comparator "i;unicode-casemap" :matches "to" ["chief@holthome.net", "chief+*@holthome.net"],
              address :count "eq" :comparator "i;ascii-numeric" "from" "1",
              address :all :comparator "i;unicode-casemap" :is "from" "${envelope.from}",
              address :domain :matches "from" "*") {
        set :lower "from_domain" "${1}";
        addheader "Authentication-Results" "mx.holthome.net; auth=pass smtp.auth=${env.authenticated_as}; dmarc=pass (authenticated submission) header.from=${from_domain}";
    }
}
```

| Mailbox | Bot | App password |
| --- | --- | --- |
| `chief@holthome.net` (and `chief+…@`) | Hermes Chief | 1Password `hermes-chief`, field `email_password` |

Adding an agent mailbox: create the account (role User, no groups), give
it one app password, put its address and its plus-address pattern in the
script's list, and add both to the edge's `allowRelaying` expression.

Tested 2026-11-18 with a temporary account, deleted afterwards: SMTP on
465 and JMAP submission were stamped and their forged headers removed, a
`From` that did not match was not stamped, `MAIL FROM` for another
address got `501 5.5.4`, and Hermes v0.23.0's own check accepted the
stamped messages and rejected the other one.

2525 trusts its mail as already filtered, so the header on top of that
mail is the edge's only while the tailnet policy grants 2525 to the edge
alone.

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

- **Outbound through the edge.** One destination goes through it:
  `mail.grokbot.com`, for a forwarding rule SMTP2GO refuses ([Through
  the edge](#through-the-edge); ADR 0014, "Fallback path through the
  edge"). Everything else stays on SMTP2GO
  ([Outbound](#outbound)) unless its terms change or the household
  outgrows its free plan. A residential address would be
  rejected or spam-foldered, so the fallback is the edge VM, whose
  address has a matching PTR. It needs a way from the cluster to the
  tailnet (such as an operator egress Service) and a policy rule; the
  current egress rule excludes 100.64.0.0/10. Vultr already allows
  outbound 25. Sending straight to recipients' MX also wants a resolver
  that validates DNSSEC, so that DANE is on. At the switch, point the
  outbound strategy at the edge's route, then remove the SMTP2GO CNAMEs,
  field `smtp2go_password` and its ExternalSecret entry, and close the
  account.
- **MTA-STS.** Planned once the edge carries real mail ([MTA-STS](#mta-sts)).
- **More than one replica.** Needs a shared in-memory store (Redis or
  Valkey) and Stalwart's cluster settings.
