---
status: accepted
date: 2026-10-27
decision-makers: Ryan Holt
---

# Internal DNS via the MikroTik external-dns webhook

## Context and Problem Statement

Private HTTPRoutes need names on the LAN. The router already holds static
records for hosts that are not in the cluster. Those records share the zone.

## Decision Drivers

- The router remains the DNS source of truth
- Only cluster-owned names should be written by the cluster
- Public names stay on Cloudflare, and only for the external gateway
- A broken webhook must have a manual fallback

## Considered Options

- k8s_gateway, with the zone forwarded to the cluster
- external-dns with the MikroTik webhook
- A static wildcard on the router and no internal automation

## Decision Outcome

Chosen option: "external-dns with the MikroTik webhook", because a zone
forward to k8s_gateway would answer for the static records too. external-dns
writes only the names it owns and keeps TXT records so it can tell them
apart. The webhook is mirceanton/external-dns-provider-mikrotik v1.6.3.
Its own README says it is not yet proven at large scale, so the API user
should be limited to DNS and the domain filter should be the cluster zone.

Public records are a second external-dns release pointed at Cloudflare and
at `envoy-external` only. That release's domain filter is `holthome.net`
plus the public service zones `warwed.com`, `ryanholt.net`,
`whiskeywhiskeywhiskey.org`, and `stefanieholt.com`. The MikroTik release
stays on `holthome.net`, so the router does not answer for those zones.

The fallback, if the webhook misbehaves, is a static wildcard on the router
aimed at the internal gateway address.

### Consequences

- Good, because static router records stay where they are
- Bad, because two external-dns releases must not both manage the same names
- The internal release is filtered to `envoy-internal`. The public release is
  filtered to `envoy-external`
- `envoy-external` annotates `external-dns.kubernetes.io/target` with
  `external.holthome.net`. `cloudflare-dns` publishes a proxied record, so
  `echo.holthome.net` resolves to Cloudflare anycast from the LAN as well as
  from the internet. The router does not shadow it. `10.45.10.51` is that
  gateway's LoadBalancer address, not `envoy-internal` (`10.45.10.50`)
- `envoy-internal` targets `10.45.10.50`. The MikroTik release manages A and
  TXT only, so a hostname target would be a CNAME and would not be written

## Pros and Cons of the Options

### k8s_gateway

- Good, because cluster-template ships it and it needs no router API
- Bad, because the forwarded zone would hide existing static names

### MikroTik webhook

- Good, because ownership is per record
- Bad, because it depends on a RouterOS API user and a young provider

### Static wildcard only

- Good, because there is nothing to automate
- Bad, because every name is manual, and ownership is not recorded
