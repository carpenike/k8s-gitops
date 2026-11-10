# Tailscale

The Tailscale Kubernetes operator runs in namespace `tailscale`, from the
chart on `https://pkgs.tailscale.com/helmcharts`, chart `1.104.4`. It runs
one `Connector`, `home`, as a subnet router into the home network. ADR 0012
is the decision.

| Piece | Where |
| --- | --- |
| Operator HelmRelease, HelmRepository, OAuth ExternalSecret | `kubernetes/apps/tailscale/tailscale-operator/app` |
| Connector `home`, ProxyClass `connector` | `kubernetes/apps/tailscale/connector/app` |
| OAuth client | 1Password item `tailscale` in `k8s-secrets`, fields `client_id` and `client_secret` |

## What it gives a tailnet device

The Connector advertises two routes:

- `10.45.10.50/32`, the `envoy-internal` LoadBalancer address
- `10.20.0.1/32`, the router, which resolves `holthome.net` (ADR 0003)

With split DNS for `holthome.net` pointing at `10.20.0.1`, a tailnet device
resolves `<app>.holthome.net` the same way the LAN does and reaches it
through the Connector. Certificates, Pocket ID and the HTTPRoutes are
unchanged. The chart's `tailscale` IngressClass is disabled: Envoy Gateway
is still the only HTTP gateway.

Two replicas, spread across sleds by ProxyClass `connector`, advertise the
same routes, so one can drain without dropping them. The proxies need
`NET_ADMIN` and a privileged init container, so the namespace is labeled
privileged.

Cilium already has what the operator needs. `socketLB.hostNamespaceOnly`
is true (set for Kata), which Tailscale requires for a Connector under
kube-proxy replacement, and `devices` is pinned to `ens1f0`, which avoids
the `tailscale0` MTU problem.

## Setup (Ryan, before the merge)

1. **Tailnet policy.** Merge this into the policy file (Access controls in
   the admin console). If the file is still the default allow-all
   (`"src": ["*"], "dst": ["*"]`), replace that rule, or Grok Bot gets
   everything you can reach.

   ```jsonc
   {
     "tagOwners": {
       "tag:k8s-operator": ["autogroup:admin"],
       "tag:k8s":          ["tag:k8s-operator"],
       "tag:k8s-subnet":   ["tag:k8s-operator"],
       "tag:grokbot":      ["autogroup:admin"],
     },
     "autoApprovers": {
       // Must match advertiseRoutes in connector/app/connector.yaml.
       "routes": {
         "10.45.10.50/32": ["tag:k8s-subnet"],
         "10.20.0.1/32":   ["tag:k8s-subnet"],
       },
     },
     "grants": [
       // Your own devices: the internal gateway and the resolver.
       { "src": ["autogroup:member"], "dst": ["10.45.10.50/32"], "ip": ["tcp:443", "tcp:80"] },
       { "src": ["autogroup:member"], "dst": ["10.20.0.1/32"],   "ip": ["udp:53", "tcp:53"] },
       // Grok Bot, once its device is tagged (see below).
       { "src": ["tag:grokbot"], "dst": ["10.45.10.50/32"], "ip": ["tcp:443"] },
       { "src": ["tag:grokbot"], "dst": ["10.20.0.1/32"],   "ip": ["udp:53", "tcp:53"] },
     ],
   }
   ```

2. **OAuth client.** Settings, OAuth clients, Generate. Scopes: **Devices
   Core**, **Auth Keys** and **Services**, all write, with tag
   `tag:k8s-operator`. Store the ID and secret in 1Password item
   `tailscale` (vault `k8s-secrets`), fields `client_id` and
   `client_secret`.

3. **Split DNS.** DNS page, Nameservers, Add nameserver, Custom:
   `10.20.0.1`, restricted to domain `holthome.net`.

## Checks (after the merge)

```sh
kubectl -n tailscale get helmrelease,externalsecret,proxyclass,connector
kubectl -n tailscale get pods -o wide
```

- Both Connector pods run on different sleds, and the admin console shows
  two `tag:k8s-subnet` machines with both routes approved (not "awaiting
  approval": that means autoApprovers does not match the Connector).
- From a laptop off the LAN, with Tailscale up:
  `dig +short headlamp.holthome.net` returns `10.45.10.50`, and
  `https://headlamp.holthome.net` shows the Pocket ID login.
- macOS, iOS and Windows clients accept subnet routes by default. Linux
  needs `tailscale set --accept-routes`.

## Grok Bot

Connect Grok Bot from the Tailscale plugin in the Grok Bot desktop app. Its
device joins with your identity, so until it is scoped it matches
`autogroup:member` and gets your grants.

- **Personal or Starter plan:** in the admin console, tag the Grok Bot
  device `tag:grokbot`. A tagged device is no longer `autogroup:member`, so
  it gets only the two `tag:grokbot` grants.
- **Premium or Enterprise:** Tailscale gives Grok Bot devices the posture
  attribute `custom:grokbot`. Define `posture:grokbot`
  (`custom:grokbot == true`) and `posture:human` (`custom:grokbot NOT SET`),
  set `"defaultSrcPosture": ["posture:human"]`, and give the Grok Bot
  grants `"srcPosture": ["posture:grokbot"]` with `autogroup:member` as the
  source instead of the tag.

**Untested: whether Grok Bot's device uses subnet routes and split DNS.**
Grok Bot runs on Linux, where a client ignores subnet routes unless told
to accept them. To test, ask Chief Engineer to fetch
`https://tasks.<internal domain>/api/v3` and say what address the name
resolved to.

- If it works, Chief Engineer no longer needs its own VPN into the LAN.
  Update "Bots outside the cluster" in [openproject.md](openproject.md).
- If it does not, the fallback is a ProxyGroup of ingress proxies with
  `*.ts.net` names for the services Grok Bot needs. That is a second HTTP
  entry point, so it needs its own ADR. homelab-mcp is not a candidate: it
  is already public with its own OAuth, which is bound to its `mcp.`
  hostname.

Reaching `10.45.10.50:443` reaches every internal route at the network
layer. Routes without a `gateway.holthome.net/auth` label still require
the Pocket ID login, which Grok Bot cannot complete. `native` routes rely
on the app's own sign-in, as they do on the LAN.

## Widening the routes

Add the prefix to `advertiseRoutes` in `connector/app/connector.yaml`, add
the same prefix under `autoApprovers.routes`, and add a grant for whoever
should reach it. A route that is advertised but not auto-approved waits in
the admin console. For the whole node LAN, the prefix is `10.20.0.0/16`.

## Versions

The operator and its proxies run the chart appVersion (`v1.104.4`). The
operator does not support proxies newer than itself, so leave the proxy
image tag empty and let Renovate move the chart. Proxy metrics are off.
The ProxyClass API calls them unstable.
