---
status: proposed
date: 2026-11-11
decision-makers: Ryan Holt
---

# Obsidian vault for the agents, via Obsidian's headless Sync client

## Context and Problem Statement

Ryan wants the agents (Claude through homelab-mcp, and Grokbot) to read and
write his Obsidian vault: a "brain" both he and they keep. The vault syncs
between his devices with Obsidian Sync (Plus, end-to-end encrypted, moved off
iCloud so Sync is its only replicator). The cluster needs its own synced copy
of the vault for the tools to work on, and somewhere those tools run.

A 2024-era CouchDB/LiveSync deployment exists only on the legacy `main`
branch (cluster-0). A Forge module (carpenike/nix-config#1409: the headless
client plus a third-party vault MCP server) was merged but never enabled, and
Forge's services have since moved to this cluster.

## Decision Drivers

- Use Obsidian's own Sync, which Ryan pays for, rather than a second
  replication system.
- No second authentication system: the vault tools should sit behind
  homelab-mcp's OAuth, views (Grokbot's explicit tool list), audit log and
  tests, like every other tool.
- A beta client that can delete: obsidian-headless 0.0.14 treats a file its
  scan misses as deleted (obsidianmd/obsidian-headless#19, #28). Block storage
  and backups outside Obsidian's service matter.
- The client is `UNLICENSED`: Obsidian's terms allow running it on machines
  operated for you, not redistributing it (#39, #52 unanswered).
- Keep it current with Renovate, like everything else.

## Considered Options

1. **Obsidian's headless Sync client as a container in the homelab-mcp pod**,
   on a new ceph-block volume, and the vault tools as a `vault_*` category in
   homelab-mcp.
2. The same client as its own Deployment on a CephFS (RWX) volume shared with
   homelab-mcp.
3. jimprosser/obsidian-web-mcp (a community vault MCP server) beside the
   client, as in the Forge module.
4. Self-hosted LiveSync (CouchDB), as in the legacy cluster.

## Decision Outcome

Chosen option: "1", because it keeps one sync system (Obsidian's), one
auth/audit/test surface (homelab-mcp), and the vault on block storage beside
the only process that writes it besides the client.

- The `obsidian-sync` container runs `node:22-bookworm-slim` (digest-pinned)
  and installs `obsidian-headless` from a lockfile in this repo
  (`apps/homelab-mcp/homelab-mcp/app/obsidian-sync/`) into the volume, once
  per lockfile. Nothing is redistributed. Renovate's npm manager bumps the
  lockfile, and its docker manager bumps the image; reloader restarts the pod
  when the generated ConfigMap changes.
- The install runs in the sidecar, not an init container, so npm or GitHub
  being unreachable never stops homelab-mcp from starting.
- One volume, three areas: `workspace/` (the vault and the tools' scratch
  directory, mounted into both containers), `config/` (the client's login and
  derived end-to-end key, 0700, mounted only into obsidian-sync) and `ob/`
  (the install).
- The tools (carpenike/mcp `vault_*`) require the hash a note was read at for
  every change, and write temp files outside the vault, so a phone edit is
  never silently overwritten and Sync never sees a partial file.
- VolSync backs the volume up to R2 every 6 hours, in addition to Obsidian
  Sync's 12-month version history.
- Egress: `*.obsidian.md` (the client refuses other hosts), plus the npm
  registry and `release-assets.githubusercontent.com` for the install.

### Consequences

- Good: the agents get one vault, with links and search across all of it,
  under the access rules every other tool has.
- Good: a client version bump is a Renovate PR and a pod restart.
- Bad: the client's login and derived end-to-end key live on a cluster
  volume and in its backups (restic-encrypted). Whoever can exec into the pod
  or restore the backup can read the vault.
- Bad: a hang that keeps the client's event loop alive (#60) is not caught
  by the liveness probe; restart and down alerts plus tool errors are the
  signal.
- Bad: the vault volume's sidecar shares the homelab-mcp pod: a pod restart
  restarts the sync, and the pod's egress list grows by the Obsidian, npm and
  release-asset hosts.
- Neutral: the one-time `ob login` and `ob sync-setup` are run by hand in the
  container (docs/homelab-mcp.md), as is a re-setup after a restore.

## Pros and Cons of the Options

### 2. Separate Deployment on CephFS

- Good: isolates the client from homelab-mcp restarts and egress.
- Bad: a network filesystem makes the client's missed-scan deletions likelier
  (#19, #28), and its SQLite state wants local block storage.

### 3. obsidian-web-mcp

- Good: ready-made, MIT, rich tool set.
- Bad: a second auth system and connector, outside the views and audit; no
  protection against lost updates; a single maintainer (with a critical OAuth
  flaw fixed in 0.2.0). Its good ideas are adapted into `vault_*` instead.

### 4. LiveSync (CouchDB)

- Bad: a second replication system beside the Obsidian Sync Ryan uses on his
  devices, and a database to run and back up.
