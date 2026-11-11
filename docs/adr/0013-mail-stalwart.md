---
status: proposed
date: 2026-11-11
decision-makers: Ryan Holt
---

# Self-hosted mail on Stalwart, stored in Ceph

## Context and Problem Statement

Mail for the public zones is hosted elsewhere today (`ryanholt.net` has
Microsoft MX records, see `docs/matrix.md`). Ryan wants to try running a
mail server on this cluster. It has to fit the rules in `AGENTS.md`: one
HTTP gateway, one block store (Rook-Ceph), backups that leave the chassis,
and no second ingress.

Mail is not only HTTP. SMTP (25, 465, 587), IMAP (993), POP3 (995) and
ManageSieve (4190) are raw TCP, so they cannot go through Envoy Gateway's
HTTP listeners.

## Decision Drivers

- Kubernetes-native: one process, no Compose stack to port
- State on the existing Ceph block pool, with an off-chassis copy through
  VolSync to R2 like Tuwunel
- No new gateway, ingress class, or storage system
- Standard protocols (IMAP, SMTP, JMAP, CalDAV, CardDAV) so any client works
- Small footprint on four sleds that already run Ceph

## Considered Options

- Stalwart 1.x, all stores RocksDB on a `ceph-block` volume
- Stalwart 1.x, data store on `postgres17`, blobs on Ceph
- mailcow (Postfix, Dovecot, Rspamd, SOGo, MariaDB and more)
- docker-mailserver (Postfix, Dovecot, Rspamd in one container)

## Decision Outcome

Chosen option: "Stalwart 1.x, all stores RocksDB on a `ceph-block`
volume", because it is one Rust binary with mail, spam filtering, JMAP and
DAV built in, and it puts all of its state on one Ceph RBD volume. That is
the same pattern as Tuwunel (ADR 0010): Ceph keeps three replicas across
the sleds, and a crash-consistent VolSync snapshot goes to R2.

Mail protocols get their own Cilium LoadBalancer address, `10.45.10.25`,
with `externalTrafficPolicy: Local` so Stalwart sees client addresses.
That is a TCP Service, not an HTTP gateway. The WebUI, JMAP and DAV stay on
`envoy-internal`.

### Consequences

- Good, because no other service has to be up for mail to work, including
  `postgres17`
- Good, because the whole mailbox store restores from one restic snapshot
- Bad, because one replica on an RWO volume means a node loss is a short
  outage while the pod moves. Senders retry, so inbound mail is delayed,
  not lost
- Bad, because a restore loses mail received after the last snapshot.
  The backup runs every six hours to keep that window small
- Bad, because a residential address cannot send mail reliably and most
  ISPs block port 25. Outbound needs a relay and inbound needs a reachable
  port 25. Both are outside this tree and are listed in `docs/mail.md`
- Neutral, because Stalwart 1.x keeps its configuration in its own store,
  not in git. `stalwart-cli snapshot` exports it as a plan that
  `stalwart-cli apply` can replay

## Pros and Cons of the Options

### Stalwart, RocksDB on ceph-block

- Good, because it is Stalwart's recommended single-node store
- Good, because it is one volume to snapshot and restore
- Bad, because it cannot scale past one replica

### Stalwart, postgres17 plus Ceph blobs

- Good, because the Barman R2 archive would give point-in-time recovery
- Bad, because mail would then depend on the shared database, and a
  restore would need the database and the blob volume from the same moment

### mailcow

- Good, because it is mature, with SOGo webmail and groupware
- Bad, because it supports Docker Compose only. Running it here means
  porting about fifteen containers or nesting Compose in a VM

### docker-mailserver

- Good, because it is the familiar Postfix and Dovecot stack in one image
- Bad, because there is no JMAP, CalDAV or CardDAV, and no admin UI
