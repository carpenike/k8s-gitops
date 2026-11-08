---
status: proposed
date: 2026-11-07
decision-makers: Ryan Holt
---

# Kata VM runner pods for CI jobs that need privilege

## Context and Problem Statement

`carpenike/mcp` has two CI jobs the unprivileged `mcp-k8s` scale set cannot
run, and GitHub-hosted runners are blocked by the account spending limit:

- The Nix job installs Nix as root and builds with the Nix sandbox, which
  needs mount and user namespaces.
- The image job runs `docker build` and pushes to GHCR, which needs a
  Docker daemon.

`docs/actions-runners.md` left the privilege level for Nix jobs to be
decided separately. A privileged `runc` pod gives repository CI code
host-level privilege on a sled, bounded only by the runner egress policy.

## Decision Drivers

- CI code must not get privilege on the host
- Use what the sleds already run. Kata is on every sled (ADR 0009)
- Keep ordinary jobs on the cheap, unprivileged `runc` scale sets

## Considered Options

- Kata VM runner pods (`runtimeClassName: kata-qemu`), privileged inside
  the guest
- Privileged `runc` runner pods with a hostPath `/dev/kvm`
- Stay on GitHub-hosted runners

## Decision Outcome

Chosen option: "Kata VM runner pods", because the `kata-qemu` containerd
handler in `siderolabs/kata-containers` sets
`privileged_without_host_devices = true`
(`container-runtime/kata-containers/11-kata-qemu.part`). A privileged
container in such a pod is privileged inside its own guest VM. It gets no
host devices and does not share the host kernel.

The first scale set is `mcp-k8s-build`. Its runner container and the dind
sidecar are privileged, both inside the guest.

### Consequences

- Good, because the Nix sandbox and a Docker daemon work without granting
  privilege on the host
- Good, because Cilium already keeps socket load balancing to the host
  namespace (`socketLB.hostNamespaceOnly`), so service IPs and cluster DNS
  work from inside the VM
- Bad, because no `/dev/kvm` reaches the guest. A job that needs KVM, such
  as a NixOS VM test, fails here. mcp's only one is the Atrium-native check,
  which goes away when the Atrium integration is removed
- Bad, because each job pays the Kata VM overhead (`250m` CPU, `160Mi`)
  and a VM boot
- Neutral: runner pods keep the `runner-egress` CiliumNetworkPolicy, which
  blocks the LAN and allows public IPv4

## Pros and Cons of the Options

### Kata VM runner pods

- Good, because the privilege boundary is a VM, not a namespace
- Bad, because there's no KVM, and VM startup adds time per job

### Privileged runc runner pods with /dev/kvm

- Good, because it runs everything, including NixOS VM tests
- Bad, because repository CI code becomes root-equivalent on a sled

### GitHub-hosted runners

- Good, because it needs no cluster change
- Bad, because the account spending limit blocks them
