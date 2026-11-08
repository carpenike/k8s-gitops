# Gateway login

HTTPS on `envoy-external` and `envoy-internal` asks for a Pocket ID login
before it forwards. The policy is `pocket-id` in namespace `network`. It
targets the `https` listener on each Gateway. Echo
(`echo.holthome.net`) has no label and no route policy, so it inherits
that login. HTTP port 80 is open only to routes in `network`, and this
policy does not attach to it.

This follows Forge's Caddy portal in `hosts/forge/services/pocketid.nix`
and `modules/nixos/services/caddy/default.nix`.

| Forge | This cluster |
| --- | --- |
| Issuer `https://id.holthome.net`, discovery from that issuer | `oidc.provider.issuer: https://id.${SECRET_DOMAIN}` |
| Scopes `openid`, `profile`, `email`, `groups` | Same scopes |
| Policy `default` allows role `authenticated`, which the portal adds to every user in realm `forge-pocketid` | The OIDC filter requires a completed login. There is no extra group check on the gateway policy |
| Claim `groups`. Value `admins` becomes role `admins` (Prometheus and Alertmanager). The same claim feeds policies `media`, `home`, and `automation` | The `groups` scope is requested. A route that needs one value uses the merged rule below |
| Cookies are host-only. Names are `AUTHP_HOST_*`. No cookie domain | `cookieDomain` is unset, so the cookie host is the request host. Access and ID cookies are `EG_HOST_ACCESS_TOKEN` and `EG_HOST_ID_TOKEN` |
| Callback path `/caddy-security/oauth2/forge-pocketid` | Envoy Gateway's default callback `https://<host>/oauth2/callback`. Logout path `/logout` |
| Client id `caddy-security` on Forge | A new confidential client. The id and secret are 1Password item `pocket-id-gateway` |

The client secret is Kustomization `envoy-gateway-auth` in namespace
`network`. `kubernetes/apps/network` sets that namespace, so
`flux get ks -n flux-system` does not list it. Nothing depends on it.
`envoy-gateway`, DNS, the tunnel, and echo do not wait on this
Kustomization. Its health check is ExternalSecret `pocket-id-gateway`.

A missing or empty client secret, or any other failure while building
the OIDC filter, is fail-closed on the listeners this policy targets.
Envoy Gateway 1.9.3 sets an HTTP 500 direct response on every HTTP route
on that listener that does not already have a more specific
SecurityPolicy, and the xDS route uses that direct response instead of
forwarding. The comment in the translator is "return a 500 direct
response to avoid unauthorized access." The same path returns 500 when
the secret's `client-secret` key is empty, when OIDC discovery fails, or
when the controller's HMAC secret is absent. `failOpen` exists only for
`extAuth`, and only when that is the sole error. This policy does not
set `extAuth`.

Source, tag `v1.9.3`:

- `internal/gatewayapi/securitypolicy.go`, `buildOIDC` (`secret %s/%s does not exist`, `client secret not found in secret`) and `translateSecurityPolicyForListeners` (the 500 direct response).
- `internal/gatewayapi/validate.go`, `validateSecretRef`.
- `internal/xds/translator/route.go`, `Route_DirectResponse`.

Echo has no route policy, so `https://echo.holthome.net` returns 500
until `pocket-id` translates. A route that already has its own
SecurityPolicy is left as that policy programmed it. `flux-webhook` is
one of those routes.

A SecurityPolicy the API server rejects is not attached, so it cannot
install this 500. The manifests in this repo pass the 1.9.3 CRD.
`scripts/validate.sh` checks them.

## One login per route

A person signs in once per route. A route keeps the gateway's Pocket ID
login and the app behind it trusts that login or asks for none, or the
route opts out below and the app's own login is the only one. A gateway
login followed by an app login is not allowed.

## Opt out

Envoy Gateway 1.9.3 keeps one effective SecurityPolicy per target. A
policy on an HTTPRoute replaces a policy on its Gateway when `mergeType`
is unset. `pocket-id-exempt` selects every HTTPRoute with:

```yaml
metadata:
  labels:
    gateway.holthome.net/auth: public   # or native, or app
```

All three replace the gateway OIDC policy with
`authorization.defaultAction: Allow`.

| Label | Route | Examples |
| --- | --- | --- |
| `public` | Must answer without a login: a webhook, or an API that checks its own bearer token | `flux-webhook`, Hermes `agent-api` |
| `native` | The app has its own Pocket ID client | LiteLLM, Hermes Webapp |
| `app` | The app has its own login that is not Pocket ID, because Pocket ID can't sign in to it (for example OIDC is a paid feature). `envoy-internal` only, with 2FA on the app's accounts | OpenProject ([openproject.md](openproject.md)) |

Prefer `native` whenever the app supports OIDC.

The selector watches every namespace. A labeled route outside `network`
needs a ReferenceGrant in the route's namespace:

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: envoy-gateway-auth
spec:
  from:
    - group: gateway.envoyproxy.io
      kind: SecurityPolicy
      namespace: network
  to:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
```

`flux-webhook` in namespace `flux-system` is labeled `public`. GitHub
authenticates that hook with the Receiver token. Its ReferenceGrant
`flux-webhook-gateway-auth` allows `SecurityPolicy` from namespace
`network` to select HTTPRoute `flux-webhook`. Echo stays behind the
gateway policy.

A Hermes bot's API route, `agent-api` in `hermes-<bot>` on
`envoy-internal` only, is also labelled `public`. Its clients send the
bot's `API_SERVER_KEY` as a bearer token, and Hermes checks it. Its
ReferenceGrant is `agent-api-gateway-auth` ([hermes.md](hermes.md)).

Two policies must not select the same route. The oldest attached policy
wins. A route uses the label or its own SecurityPolicy, and only one of
those.

## Path, method, and source bypass

`matrix.ryanholt.net` has its own `envoy-external` listener,
`https-matrix`. ClientTrafficPolicy `envoy-external-matrix` keeps `%2F` in
paths as sent on that listener only (`escapedSlashesAction:
KeepUnchanged`); Matrix needs it. cloudflared selects that listener with
SNI `matrix.ryanholt.net` (its own ingress rule). Every other listener,
including the shared `https` listener on `envoy-external` and all of
`envoy-internal`, keeps the Envoy Gateway default, `UnescapeAndRedirect`.
A path rule on `https-matrix` should be a `RegularExpression` that an
encoded `/` cannot satisfy.

The two `envoy-external` HTTPS listeners share port 443 and certificate
`ryanholt-net-production-tls`, so Envoy Gateway marks both
`OverlappingTLSConfig` and would advertise only `http/1.1`. ClientTrafficPolicies
`envoy-external-matrix` and `envoy-external-https` set ALPN back to `h2`,
`http/1.1` explicitly, which keeps cloudflared's `http2Origin`. The
reasoning for why that is safe is in `clienttrafficpolicy.yaml`. The
listener status still shows the condition; that is expected.


Forge's Caddy module can skip the portal for a regex path
(`bypassResources`), a path prefix (`bypassPaths`), and a source CIDR
(`allowedNetworks`). Alertmanager's vhost
(`hosts/forge/infrastructure/monitoring-ui.nix`) combines all three with a
method (`bypassMethods`): `POST` to `^/api/v2/alerts$` from the four sled
addresses skips the portal, and everything else stays policy `admins`. The
cluster's alerts are delivered that way. The same shape here is a named
HTTPRoute rule and a SecurityPolicy that targets that rule's
`sectionName`.

`mergeType` stays unset, so this rule replaces the gateway login and the
other rules on the same HTTPRoute keep it. `defaultAction: Deny` closes
everything the rule does not list.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: alertmanager
spec:
  rules:
    - name: webhook
      matches:
        - method: POST
          path:
            type: RegularExpression
            value: ^/api/v2/alerts$
      backendRefs:
        - name: alertmanager
          port: 9093
    - name: ui
      backendRefs:
        - name: alertmanager
          port: 9093
---
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: alertmanager-webhook
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: alertmanager
      sectionName: webhook
  authorization:
    defaultAction: Deny
    rules:
      - name: post-alerts
        action: Allow
        operation:
          methods: ["POST"]
          path:
            type: RegularExpression
            value: ^/api/v2/alerts$
        principal:
          clientCIDRs:
            - 10.20.10.20/32
            - 10.20.10.21/32
            - 10.20.10.22/32
            - 10.20.10.23/32
```

Put that policy in the same namespace as the HTTPRoute. This example is
the convention. It is not installed. Alertmanager stays on Forge.

An IP allowlist for a whole route is the same policy without
`sectionName`, with a single Allow rule whose only principal is
`clientCIDRs`, and with `defaultAction: Deny`.

`clientCIDRs` match the client address Envoy records.
`EnvoyProxy` `envoy` sets `externalTrafficPolicy: Cluster`, so a packet
that arrives at the LoadBalancer is seen as a node address.
`ClientTrafficPolicy` `clientIPDetection.xForwardedFor` is how a later
allowlist trusts a proxy's `X-Forwarded-For`. The public tunnel's peer is
cloudflared, so a visitor allowlist on `envoy-external` needs that
detection and a trusted hop list.

A route that should keep the login and add a rule sets
`mergeType: StrategicMerge`. That value is only valid on an HTTPRoute or
GRPCRoute target. `Replace` is rejected by the CRD. Strategic merge keeps
the gateway OIDC block and adds the route's authorization rules. Those
rules run after the login. They do not skip it. A path that must answer
with no session uses the section override above.

Forge's tighter policies check claim `groups` (string array) for
`admins`, `media`, `home`, or the automation role. A route that needs
that check merges a JWT provider for issuer `https://id.holthome.net`
and an authorization rule:

```yaml
principal:
  jwt:
    provider: pocket-id
    claims:
      - name: groups
        valueType: StringArray
        values: ["admins"]
```

The JWT block has to be in that same SecurityPolicy, and its remote JWKS
needs a Backend for `id.holthome.net`. No route on this branch asks for a
group, so that provider is not installed.

## Pocket ID client

Create a confidential client at `https://id.holthome.net`. Envoy Gateway
1.9.3 sends an authorization-code request with PKCE (S256) and the client
secret. Suggested client name: `envoy-gateway`.

- Public client: off. PKCE: on.
- Pushed authorization requests: off. Reauthentication on each visit: off.
- Group restriction: off. Forge's default policy allows every logged-in
  user. Group checks belong on the route, as above.
- Consent: skip, so a first-party login does not stop on a consent page.
- Scopes the client may return: `openid`, `profile`, `email`, `groups`.

Callback URLs. Pocket ID 2.14 treats these as URL patterns. `*` is one
hostname label, so `https://echo.holthome.net/oauth2/callback` matches
and `https://holthome.net/oauth2/callback` does not. Add an apex pattern
when a route uses an apex host. Add another label (`*.*.example.com`)
when a route uses a deeper name.

- `https://*.holthome.net/oauth2/callback`
- `https://*.warwed.com/oauth2/callback`
- `https://*.ryanholt.net/oauth2/callback`
- `https://*.whiskeywhiskeywhiskey.org/oauth2/callback`
- `https://*.stefanieholt.com/oauth2/callback`

Logout callbacks. Discovery supplies the end-session endpoint, and
`/logout` on the app host sends the browser there.

- `https://*.holthome.net/**`
- `https://*.warwed.com/**`
- `https://*.ryanholt.net/**`
- `https://*.whiskeywhiskeywhiskey.org/**`
- `https://*.stefanieholt.com/**`

Store the issued client id and secret in 1Password vault `k8s-secrets`,
item `pocket-id-gateway`, fields `client_id` and `client_secret`. The
ExternalSecret maps those fields onto secret keys `client-id` and
`client-secret`. The values stay out of git.
