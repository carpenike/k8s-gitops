---
status: proposed
date: 2026-11-03
decision-makers: Ryan Holt
---

# Tuwunel as the Matrix homeserver

## Context and Problem Statement

Hermes agents (ADR 0009) need a chat surface, and the family needs
accounts on the same server. Bots need accounts created by automation,
not by a person with a registration token. The server name is
`ryanholt.net` and cannot change once accounts exist.

## Decision Drivers

- One pod, one RWO volume, no new database. The cluster has CloudNativePG,
  but a homeserver that needs no Postgres is less to run
- Bot accounts come from an appservice, so their namespace can be
  exclusive and their creation needs no registration token
- No account is an admin by default
- The public route follows the existing `envoy-external` pattern
- Pod Security `restricted`

## Considered Options

- Tuwunel (`ghcr.io/matrix-construct/tuwunel`)
- Synapse
- Conduit

## Decision Outcome

Chosen option: "Tuwunel", because it is one static binary with embedded
RocksDB, it runs unprivileged with no user in the image, it reads
appservice registrations from a directory, and it serves both
`/.well-known/matrix` files from its own config.

The chart is `app-template` 5.3.0. Details are in
[../matrix.md](../apps/matrix.md).

Secrets are SOPS, not External Secrets. The registration token,
`as_token`, and `hs_token` are generated once, have no upstream source,
and are read by nothing outside the cluster, the same case as the upsmon
password in ADR 0005. This is an exception to ADR 0002. Restic
credentials for the backup are v1's shared 1Password item
`volsync-r2-template`.

### Consequences

- Good, because the database and media are one volume, backed up by one
  VolSync source
- Good, because a bot's credentials are a per-user access token in its own
  namespace, and the `as_token` never leaves `matrix`
- Bad, because Tuwunel v1.9.4 has no Prometheus endpoint
- Bad, because there is no horizontal scaling. Downtime on upgrade is the
  `Recreate` restart, longer when a database migration runs
- Bad, because rotating a SOPS token is a commit
- The apex `ryanholt.net` moves to `envoy-external`. `/.well-known/matrix/`
  goes to Tuwunel and every other path to the static site in namespace
  `web`

## Pros and Cons of the Options

### Tuwunel

- Good, because it runs as a non-root user with every capability dropped
- Good, because appservice `/register` bypasses `allow_registration`, so
  people and bots have separate paths
- Bad, because it is a smaller project than Synapse

### Synapse

- Good, because it is the reference implementation, with metrics
- Bad, because it wants Postgres, workers for scale, and a larger footprint

### Conduit

- Good, because it is the same single-binary shape
- Bad, because Tuwunel is the maintained descendant with appservice
  directory loading and OIDC login
