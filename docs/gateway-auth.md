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

The client secret is Kustomization `envoy-gateway-auth`. Nothing depends
on it. Until item `pocket-id-gateway` exists, the ExternalSecret stays
unready, Envoy Gateway does not program the OIDC filter, and the
gateways keep serving. `envoy-gateway`, DNS, the tunnel, and echo do not
wait on this Kustomization.

`flux-webhook.holthome.net` is an HTTPRoute on `envoy-external` and has
no auth label. Once `pocket-id` is accepted, GitHub's push hook is sent
through the same login. Add the public label to that route before push
delivery needs to succeed.

## Opt out

Envoy Gateway 1.9.3 keeps one effective SecurityPolicy per target. A
policy on an HTTPRoute replaces a policy on its Gateway when `mergeType`
is unset. `pocket-id-exempt` selects every HTTPRoute with:

```yaml
metadata:
  labels:
    gateway.holthome.net/auth: public   # or native
```

`public` is a route that must answer without a login. `native` is a route
whose app has its own Pocket ID client. Both replace the gateway OIDC
policy with `authorization.defaultAction: Allow`.

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

No route on this branch carries the label. Echo stays behind the gateway
policy.

Two policies must not select the same route. The oldest attached policy
wins. A route uses the label or its own SecurityPolicy, and only one of
those.

## Path, method, and source bypass

Forge's Caddy module can skip the portal for a regex path
(`bypassResources`), a path prefix (`bypassPaths`), and a source CIDR
(`allowedNetworks`). Alertmanager's vhost
(`hosts/forge/infrastructure/monitoring-ui.nix`) is still policy
`admins` for the whole host. The cluster's `POST /api/v2/alerts` is
refused there until that matcher exists. The shape to copy is a named
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
