# Docs

| File | Contents |
| --- | --- |
| [architecture.md](architecture.md) | What runs, and the version pins |
| [gateway-auth.md](gateway-auth.md) | Pocket ID login on the Envoy gateways, and how a route opts out |
| [actions-runners.md](actions-runners.md) | Self-hosted Actions runners for private repos, and the GitHub App |
| [headlamp.md](headlamp.md) | Read-only Kubernetes UI on the internal gateway |
| [litellm.md](litellm.md) | LiteLLM proxy on the internal gateway, and the Forge cutover |
| [postgres17.md](postgres17.md) | Shared Postgres: backups to Ceph and R2, alerts, and the restore drill |
| [grafana.md](grafana.md) | Grafana and Grafana OnCall moved from Forge: datasources, plugins, secrets, and the cutover |
| [hermes.md](hermes.md) | Hermes agents in Kata VMs: Chief, and what to create for a new one |
| [openproject.md](openproject.md) | OpenProject task board for Ryan and the bots: database, sign-in, backups |
| [matrix.md](matrix.md) | Tuwunel homeserver, first admin, and Hermes bot provisioning |
| [multus.md](multus.md) | Multus in front of Cilium, and the `vlan30` attachment |
| [scrypted.md](scrypted.md) | Scrypted NVR on VLAN 30, and the Forge cutover |
| [website.md](website.md) | The `ryanholt.net` static site, and how it shares the apex with Matrix |
| [deviations.md](deviations.md) | Where this tree leaves onedr0p/cluster-template |
| [lessons-from-v1.md](lessons-from-v1.md) | What the archived tree taught us |
| [placeholders.md](placeholders.md) | Values a person still has to fill in |
| [sops.md](sops.md) | YubiKey decryption, and the age key Flux gets later |
| [external-secrets.md](external-secrets.md) | 1Password through External Secrets: rate limits, the 12h refresh, rotating with force-sync |
| [adr/](adr/) | Decision records |

`AGENTS.md` at the repo root is the instruction file for agents.
