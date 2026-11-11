---
status: proposed
date: 2026-11-11
decision-makers: Ryan Holt
---

# Inbound mail through a Stalwart edge relay on Vultr, over the tailnet

## Context and Problem Statement

ADR 0013 put Stalwart in the cluster with its mail ports on LoadBalancer
`10.45.10.25`, reachable from the LAN only. Mail from the internet needs a
public address that accepts port 25. The home connection cannot provide
one reliably: the address is residential and dynamic, Cloudflare Tunnel
carries HTTP only, and `docs/mail.md` lists inbound 25 as needing its own
ADR.

The cluster already has a path from the tailnet into the home network:
the Tailscale operator's Connector `home` (ADR 0012), a subnet router that
advertises single addresses and is gated by grants in the tailnet policy.

## Decision Drivers

- No new public entry point into the home network, and no port forward on
  the router
- Stalwart in the cluster stays the only store of mail (ADR 0013)
- Senders' real addresses must be checked (SPF, DNSBL, rate limits). The
  Connector source-NATs, so the cluster never sees them
- Mail must not be lost while the cluster is down or being rebuilt
- Unknown recipients must be rejected during the SMTP session, so the
  system never sends backscatter
- A path to sending from a static address with a matching PTR later

## Considered Options

- Stalwart as an MTA-only edge relay on a Vultr VM, relaying over the
  tailnet to a dedicated listener in the cluster
- HAProxy on a Vultr VM forwarding TCP over the tailnet, with PROXY
  protocol v2 to a dedicated Stalwart listener
- A router port forward of 25 to `10.45.10.25`
- A Tailscale operator ingress proxy for Stalwart instead of the Connector

## Decision Outcome

Chosen option: "Stalwart as an MTA-only edge relay on a Vultr VM", because
it is the only option that queues mail while the cluster is down and
checks senders at their real address, and it is the same software as the
server behind it.

The VM runs Stalwart and `tailscaled` with tag `tag:mx-edge`. Public DNS
points the MX of each mail domain at the VM. The edge:

- accepts mail for the mail domains only, from anyone, and rejects every
  recipient not on its list during RCPT
- runs SPF, DKIM, DMARC, reverse DNS, DNSBL and the spam filter, and
  rejects mail over the reject threshold during DATA
- relays everything it accepts through an `MtaRoute/Relay` to
  `10.45.10.25:2525`, and queues while that is unreachable
- gets its own certificate for the MX name with Stalwart's ACME client

The cluster side:

- Connector `home` also advertises `10.45.10.25/32`. The tailnet policy
  auto-approves it, and grants `tag:mx-edge` only `tcp:2525` on it
- Service `stalwart-mail` gets port 2525. The network policy opens 2525
  to the Connector pods and nothing else
- Stalwart gets a listener `smtp-edge` on 2525 (SMTP, STARTTLS offered).
  The DATA stage `enableSpamFilter` expression and the SPF, DMARC and
  reverse-DNS verification expressions skip sessions on that listener,
  because they would judge the Connector pod's address. The edge's
  verdict travels in its headers, and a global Sieve script files mail the
  edge marked as spam into Junk

The same route also lets tailnet devices reach the client ports (465,
587, 993, 995, 4190) through the Connector. Grants give those to
`autogroup:member` only.

### Consequences

- Good, because nothing new listens on the home connection; the only
  internet-facing SMTP is a VM that can reach one port in the cluster
- Good, because the edge queues mail through a cluster outage for as long
  as its queue retention allows, instead of relying on senders' retries
- Good, because sender checks and rejections happen at the real address,
  during the SMTP session
- Good, because a static address with its own PTR can later carry
  outbound mail and replace the relay in `docs/mail.md`
- Bad, because there are two Stalwart servers to configure and patch. The
  edge's configuration lives in its own store, like the cluster's
  (`stalwart-cli snapshot`), not in this repo
- Bad, because the edge's recipient list is a second copy of the
  addresses. A new address must be added there before it can receive
  mail from the internet
- Bad, because the cluster trusts listener `smtp-edge` completely. The
  network policy and the tailnet grant are the only things that keep
  other senders off it
- Bad, because mail sits on the VM's disk while queued, outside the
  cluster and its backups
- Neutral, because the VM costs a few dollars a month and needs a Vultr
  support request to open outbound 25, if outbound is ever moved there

## Pros and Cons of the Options

### Stalwart edge relay

- Good, because it queues and filters at the edge
- Bad, because of the second server and the second recipient list

### HAProxy with PROXY protocol

- Good, because the VM is stateless: one config file, no recipient list
- Good, because the cluster sees every sender's real address
- Bad, because nothing queues: a cluster outage turns into deferrals at
  every sender, and a long one into bounces
- Bad, because the internet talks SMTP directly to the cluster's
  Stalwart, through a listener that must require the PROXY header

### Router port forward

- Good, because it needs no VM
- Bad, because many residential ISPs block inbound 25, the address
  changes, and it is a new public entry point into the home network

### Tailscale operator ingress proxy

- Good, because Stalwart would get its own tailnet device and name
  without widening the Connector's routes
- Bad, because ADR 0012 chose the Connector over operator proxies, and
  it adds a proxy StatefulSet for one port
