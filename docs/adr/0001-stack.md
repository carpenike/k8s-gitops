---
status: accepted
date: 2026-10-27
decision-makers: Ryan Holt
---

# Platform stack for the rebuild

## Context and Problem Statement

The homelab needs a new Kubernetes cluster on four identical sleds, with
GitOps, a single CNI, Gateway API, Ceph, and backups that leave the chassis.
The previous repository is public and is no longer synced by a cluster.

## Decision Drivers

- One tool per layer, after the v1 overlap described in `docs/lessons-from-v1.md`
- Community Flux and Talos conventions from onedr0p/cluster-template
- Backups must not depend on the chassis staying up
- The repository stays public, so site data cannot live in git

## Considered Options

- Talos plus this Flux stack
- NixOS with k3s on the sleds
- Argo CD instead of Flux

## Decision Outcome

Chosen option: "Talos plus this Flux stack", because the sleds should be
API-only and the surrounding charts, Renovate presets, and examples are
Flux-shaped. NixOS stays on the NAS and on Forge. Argo CD was not picked
for the same ecosystem reason.

Versions and component names are listed in `docs/architecture.md`. They
match the plan checked on 27 Oct 2026.

### Consequences

- Good, because machine config, upgrades (tuppr), and app config are pull requests
- Bad, because a chassis or shared-PSU failure takes every node down together
- Backups target an S3 endpoint off the chassis and a second copy in R2
- Forge keeps the workloads that need a GPU, USB radios, or must outlive the chassis

## Pros and Cons of the Options

### Talos plus Flux

- Good, because the node OS and the GitOps controller are both declarative
- Bad, because storage, BGP, and the tunnel all have to be designed up front

### NixOS with k3s

- Good, because the rest of the home is already NixOS
- Bad, because each node would have two control loops, and upgrades would be custom

### Argo CD

- Good, because the UI is stronger
- Bad, because the charts and Renovate presets this plan uses are written for Flux
