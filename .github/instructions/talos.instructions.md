---
description: Talos and topf rules
applyTo: "talos/**,cluster.example.toml"
---

# Talos

- `talos/topf.yaml` is the node inventory. Patches in `talos/all/` apply to every node. Patches in `talos/control-plane/` apply to control-plane nodes.
- Node addresses are the v1 bare-metal hosts on `10.20.0.0/16` (`10.20.10.20`–`10.20.10.23`). The API VIP `10.20.10.10` is new and must be confirmed free. Do not commit MACs, disk serials, or a Talos secrets bundle.
- Control-plane nodes are schedulable. Do not put the control-plane taint back.
- `schematicId` stays all zeros until an Image Factory build that includes `nut-client` exists.
- Do not run `topf secrets` and commit the result. The bundle is a cluster credential.
- Do not copy kernel arguments that disable CPU mitigations or AppArmor from the archived tree.
