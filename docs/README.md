# Docs

The repository [README](../README.md) is the overview. These files are the
detail. `AGENTS.md` at the repo root is the instruction file for agents.

## Start here

| File | Contents |
| --- | --- |
| [architecture.md](architecture.md) | What runs, the networks, the names, where data lives, and what stays off the cluster |
| [adr/](adr/) | Decision records, listed [below](#decision-records) |
| [deviations.md](deviations.md) | Where this tree leaves onedr0p/cluster-template |
| [lessons-from-v1.md](lessons-from-v1.md) | What the archived tree taught us |

## Platform

| File | Contents |
| --- | --- |
| [gateway-auth.md](gateway-auth.md) | Pocket ID login on the Envoy gateways, and how a route opts out |
| [external-secrets.md](external-secrets.md) | 1Password through External Secrets: rate limits, the 12h refresh, rotating with force-sync |
| [sops.md](sops.md) | YubiKey decryption, and the age key Flux uses |
| [tailscale.md](tailscale.md) | Tailscale operator and the `home` subnet router to `envoy-internal`: tailnet policy, OAuth client, Grok Bot |
| [multus.md](multus.md) | Multus in front of Cilium, and the `vlan30` attachment |
| [postgres17.md](postgres17.md) | Shared Postgres: backups to Ceph and R2, alerts, and the restore drill |
| [grafana.md](grafana.md) | Grafana and Grafana OnCall: datasources, plugins, secrets |
| [actions-runners.md](actions-runners.md) | Self-hosted Actions runners for private repos, and the GitHub App |
| [headlamp.md](headlamp.md) | Read-only Kubernetes UI on the internal gateway |

Node config and first install are next to the files they describe:
[talos/README.md](../talos/README.md) and
[bootstrap/README.md](../bootstrap/README.md).

## Applications

| File | Contents |
| --- | --- |
| [hermes.md](hermes.md) | Hermes agents in Kata VMs, and what to create for a new one |
| [hermes-memory.md](hermes-memory.md) | Hindsight, the bots' shared long-term memory |
| [litellm.md](litellm.md) | LiteLLM proxy on the internal gateway, its models and keys |
| [homelab-mcp.md](homelab-mcp.md) | Claude tools server at `mcp.`: views and MFP cookies |
| [openproject.md](openproject.md) | OpenProject task board for Ryan and the bots: database, sign-in, backups |
| [grok-board-guide.md](grok-board-guide.md) | The task board instructions to paste into a Grok bot |
| [matrix.md](matrix.md) | Tuwunel homeserver, first admin, and Hermes bot provisioning |
| [mail.md](mail.md) | Stalwart mail server: postgres17 and RGW storage, backups, names, and first-run setup |
| [scrypted.md](scrypted.md) | Scrypted NVR on VLAN 30 |
| [schoolhouse.md](schoolhouse.md) | Schoology ingest CronJob and health server |
| [lading.md](lading.md) | Amazon, Costco and Sam's Club sync per account, and token seeds |
| [website.md](website.md) | The `ryanholt.net` static site, and how it shares the apex with Matrix |

## Build and migration records

These were written while the cluster was being built and apps were moving
onto it. Read them as a record of that work, not as a guide to the running
system.

| File | Contents |
| --- | --- |
| [forge-cutover.md](forge-cutover.md) | Moving homelab-mcp, its finance and Signal workers, schoolhouse, lading, Grafana and OnCall off Forge: PR order and the cutover window |
| [placeholders.md](placeholders.md) | Values a person had to fill in for the install, and which 1Password item each consumer reads |

## Decision records

Records use the [MADR](https://adr.github.io/madr/) headings.
[adr/template.md](adr/template.md) is the starting point for a new one.

| Record | Decision | Status |
| --- | --- | --- |
| [0001](adr/0001-stack.md) | Platform stack for the rebuild | accepted |
| [0002](adr/0002-secrets.md) | External Secrets for app secrets, SOPS only for bootstrap | accepted |
| [0003](adr/0003-internal-dns.md) | Internal DNS via the MikroTik external-dns webhook | accepted |
| [0004](adr/0004-ipmi.md) | Out-of-band management via IPMI/Redfish on Forge | accepted |
| [0005](adr/0005-nut.md) | In-cluster NUT, one upsd per sled | accepted |
| [0006](adr/0006-litellm.md) | LiteLLM on the Talos cluster | proposed |
| [0007](adr/0007-multus.md) | Multus in front of Cilium for a VLAN 30 interface | proposed |
| [0008](adr/0008-scrypted.md) | Scrypted on the Talos cluster | proposed |
| [0009](adr/0009-kata.md) | Kata Containers for a VM-sandboxed workload | proposed |
| [0010](adr/0010-matrix-tuwunel.md) | Tuwunel as the Matrix homeserver | proposed |
| [0011](adr/0011-kata-ci-runners.md) | Kata VM runner pods for CI jobs that need privilege | proposed |
| [0012](adr/0012-tailscale-subnet-router.md) | Tailnet access through a Tailscale operator subnet router | proposed |
| [0013](adr/0013-mail-stalwart.md) | Self-hosted mail on Stalwart, on postgres17 and Ceph RGW | proposed |
| [0014](adr/0014-mail-edge-relay.md) | Inbound mail through a Stalwart edge relay on Vultr, over the tailnet | proposed |
| [0015](adr/0015-mail-pocket-id.md) | Stalwart accounts from Pocket ID | proposed |
| [0016](adr/0016-obsidian-headless-sync.md) | Obsidian vault for the agents, via Obsidian's headless Sync client | proposed |
