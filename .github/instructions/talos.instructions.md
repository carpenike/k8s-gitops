---
description: Talos and topf rules
applyTo: "talos/**,cluster.example.toml"
---

# Talos

- `talos/topf.yaml` is the node inventory. Patches in `talos/all/` apply to every node. Patches in `talos/control-plane/` apply to control-plane nodes.
- Addresses in git are RFC 5737 documentation addresses. Replace them locally before apply, and do not commit the real ones unless they are also placeholders.
- Control-plane nodes are schedulable. Do not put the control-plane taint back.
- `schematicId` stays all zeros until an Image Factory build that includes `nut-client` exists.
- Do not run `topf secrets` and commit the result. The bundle is a cluster credential.
- Do not copy kernel arguments that disable CPU mitigations or AppArmor from the archived tree.
