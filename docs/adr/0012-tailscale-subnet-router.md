---
status: proposed
date: 2026-11-10
decision-makers: Ryan Holt
---

# Tailnet access through a Tailscale operator subnet router

## Context and Problem Statement

Internal apps are HTTPRoutes on `envoy-internal` (`10.45.10.50`) with
`holthome.net` names that the router publishes (ADR 0003). They are
reachable only on the LAN. Two kinds of clients need them from elsewhere:

- Ryan's own devices away from home.
- Grok Bot. Tailscale announced on 9 Nov 2026 that Grok Bot can join a
  tailnet as a device carrying the connecting user's identity, scoped by
  tailnet policy (a custom posture attribute on Premium and Enterprise, a
  tag on other plans). Today Chief Engineer reaches the task board over
  its own VPN into the LAN (`docs/apps/openproject.md`).

v1 ran a Tailscale load balancer class beside ingress-nginx and Cilium's
Gateway resources, and `docs/history/lessons-from-v1.md` lists that as ingress
sprawl. `AGENTS.md` allows one HTTP gateway.

## Decision Drivers

- Envoy Gateway stays the only HTTP gateway; no second ingress class
- Existing hostnames, certificates and Pocket ID policies keep working
  unchanged for tailnet clients
- Nothing new is published to the internet
- The router stays the resolver for `holthome.net`
- Grok Bot gets only what a grant names, not Ryan's full access

## Considered Options

- Tailscale operator `Connector` as a subnet router for `envoy-internal`
  and the router's DNS
- Tailscale operator `Ingress` (or a ProxyGroup of ingress proxies) per app,
  with `*.ts.net` names
- Tailscale on the router or on Forge instead of in the cluster

## Decision Outcome

Chosen option: "Tailscale operator `Connector` as a subnet router",
because it moves packets to the gateway that already exists. Every
internal HTTPRoute is reachable from the tailnet under its own name, with
its own certificate and auth, and the operator adds no HTTP routing of its
own. The chart's `tailscale` IngressClass is disabled.

The Connector advertises `10.45.10.50/32` and `10.20.0.1/32` only, with two
replicas on different sleds. Split DNS in the tailnet points `holthome.net`
at `10.20.0.1`. Setup and the tailnet policy are in `docs/platform/tailscale.md`.

### Consequences

- Good, because there is no new gateway, certificate or DNS writer
- Good, because route approval and access are in the tailnet policy, and
  the advertised prefixes are in git
- Bad, because the proxies run privileged in namespace `tailscale`
- Bad, because a tailnet client that does not accept subnet routes cannot
  use it. Linux clients need `--accept-routes`. Whether Grok Bot's device
  does is untested; if it does not, the follow-up is a ProxyGroup of
  ingress proxies for the specific services Grok Bot needs, recorded in a
  new ADR, because that is a second HTTP entry point
- Neutral, because reaching `10.45.10.50:443` is reaching every internal
  route at the network layer. Pocket ID still gates the routes without a
  `gateway.holthome.net/auth` label; `native` routes rely on the app's own
  sign-in

## Pros and Cons of the Options

### Connector subnet router

- Good, because it reuses envoy-internal end to end
- Good, because it is two `/32` routes, easy to audit
- Bad, because clients need subnet routes and split DNS turned on

### Tailscale Ingress or ProxyGroup per app

- Good, because `*.ts.net` names with their own certificates work on any
  tailnet client, including one that ignores subnet routes
- Bad, because it is a second HTTP entry point with its own TLS, and each
  app gets a second hostname. OAuth apps such as homelab-mcp bind their
  metadata to one hostname

### Tailscale outside the cluster

- Good, because a cluster outage does not cut remote access
- Bad, because the router and Forge are not managed from this repo, and
  the approval and grant changes would not be reviewed here
