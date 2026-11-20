---
status: proposed
date: 2026-11-11
decision-makers: Ryan Holt
---

# Self-hosted mail on Stalwart, on postgres17 and Ceph RGW

## Context and Problem Statement

Mail for the public zones is hosted elsewhere today (`ryanholt.net` has
Microsoft MX records, see `docs/apps/matrix.md`). Ryan wants to try running a
mail server on this cluster. It has to fit the rules in `AGENTS.md`: one
HTTP gateway, one block store (Rook-Ceph), backups that leave the chassis,
and no second ingress.

Mail is not only HTTP. SMTP (25, 465, 587), IMAP (993), POP3 (995) and
ManageSieve (4190) are raw TCP, so they cannot go through Envoy Gateway's
HTTP listeners.

The cluster already has the two stores Stalwart's distributed layout
expects: the shared CloudNativePG cluster `postgres17` (two instances,
Barman WAL archive to R2) and the Ceph object store `ceph-objectstore`
(the rook-ceph-cluster chart default, StorageClass `ceph-bucket`).

## Decision Drivers

- Kubernetes-native: one process, no Compose stack to port
- State on the platform's existing stores, with copies off the chassis
- A lost sled should cost a reschedule, not a volume reattach
- No new gateway, ingress class, or storage system
- Standard protocols (IMAP, SMTP, JMAP, CalDAV, CardDAV) so any client works

## Considered Options

- Stalwart 1.x: data and search on `postgres17`, blobs in a Ceph RGW bucket
- Stalwart 1.x: every store RocksDB on one `ceph-block` volume (the Tuwunel
  pattern, ADR 0010)
- mailcow (Postfix, Dovecot, Rspamd, SOGo, MariaDB and more)
- docker-mailserver (Postfix, Dovecot, Rspamd in one container)

## Decision Outcome

Chosen option: "Stalwart 1.x: data and search on `postgres17`, blobs in a
Ceph RGW bucket", because it is one Rust binary with mail, spam filtering,
JMAP and DAV built in, and this split puts each kind of state where the
cluster already protects it best. Accounts, mailboxes, message metadata,
configuration and the full-text index are rows in `postgres17`, which
already has a standby and point-in-time recovery from R2. Message bodies
and attachments are immutable, content-addressed objects in bucket
`stalwart-blobs` on `ceph-objectstore`. An hourly `rclone copy` (never
delete) puts them in R2. The pod keeps nothing on disk.

Mail protocols get their own Cilium LoadBalancer address, `10.45.10.25`,
with `externalTrafficPolicy: Local` so Stalwart sees client addresses.
That is a TCP Service, not an HTTP gateway. The WebUI, JMAP and DAV stay on
`envoy-internal`.

### Consequences

- Good, because the pod is stateless: losing a sled reschedules it without
  waiting for an RBD volume to detach
- Good, because the database gets the same backup, alerts and restore
  drill as every other `postgres17` store (`docs/platform/postgres17.md`)
- Good, because blobs do not grow the database, and RGW's erasure-coded
  data pool stores them at 1.5x rather than 3x
- Bad, because mail now depends on `postgres17` and the RGW. A database
  switchover or restart pauses delivery; senders retry
- Bad, because a restore has two halves. The database restores to any
  point in 30 days; blobs written in the last hour before a chassis loss
  may be missing from R2
- Bad, because R2 keeps every blob ever written, including ones Stalwart
  later deleted. A prune would have to compare against the database
- Bad, because one replica only: Stalwart's local in-memory store is not
  shared. Scaling out needs Redis or Valkey and is a later decision
- Bad, because a residential address cannot send mail reliably and most
  ISPs block port 25. Outbound needs a relay and inbound needs a reachable
  port 25. Both are outside this tree and are listed in `docs/apps/mail.md`
- Neutral, because Stalwart 1.x keeps its configuration in its own store,
  not in git. `stalwart-cli snapshot` exports it as a plan that
  `stalwart-cli apply` can replay

## Pros and Cons of the Options

### Stalwart, postgres17 plus RGW

- Good, because it is Stalwart's recommended layout for more than a toy
  install, on stores the cluster already runs
- Good, because the database has point-in-time recovery
- Bad, because there are two stores to restore together

### Stalwart, RocksDB on ceph-block

- Good, because it has the fewest moving parts and one volume to restore
- Bad, because the pod is tied to one RWO volume, the backup is a
  snapshot every few hours, and there is no point-in-time recovery

### mailcow

- Good, because it is mature, with SOGo webmail and groupware
- Bad, because it supports Docker Compose only. Running it here means
  porting about fifteen containers or nesting Compose in a VM

### docker-mailserver

- Good, because it is the familiar Postfix and Dovecot stack in one image
- Bad, because there is no JMAP, CalDAV or CardDAV, and no admin UI
