# Agent instructions

This file is the canonical instruction set for AI coding agents in this
repository. `CLAUDE.md` and `.github/copilot-instructions.md` point here.
Path-scoped supplements live in `.github/instructions/` and use `applyTo`,
the pattern described in hve-core's `.github/instructions/README.md`.

## How work is split

A person, or an agent acting as the spec writer, records the change in a
pull request and, when it is an architectural choice, in `docs/adr/`.
Copilot or Claude Code implements that spec in a pull request. Agents do
not apply manifests to a cluster, do not generate age or Talos secrets, and
do not check the human-review box in the pull request template. That split
matches the hve-core line "AI carries the rules, humans keep the judgment"
(`README.md` of microsoft/hve-core) and the research-plan-implement-review
sequence in hve-core `docs/rpi/README.md`.

## What this repo is

Public GitOps for a four-node Talos cluster: three schedulable control
planes and one worker. Flux runs via the Flux Operator. The desired state
is `kubernetes/apps`. `archive/talos-v1` is the previous tree, frozen. Do
not restore it onto this branch.

Read `docs/architecture.md` and `docs/deviations.md` before adding a
component. The component list and versions are in `docs/architecture.md`.
If the plan and this tree disagree, the plan wins and the tree should be
updated in a pull request.

## Hard rules

- The GitHub repository is public. Do not commit secrets, tokens, age
  private keys, Talos secret bundles, kubeconfigs, tunnel credentials, home
  or private addresses, or internal hostnames.
- Site-specific values stay as the placeholders in `docs/placeholders.md`
  and `cluster.example.toml`.
- Do not generate an age key, a deploy key, or a webhook token and commit
  the result. Bootstrap commands in `bootstrap/README.md` are run by a
  person, on a workstation, with values that never enter git.
- Do not point Flux at a live cluster from CI. Workflows install nothing
  and use no GitHub secrets.
- Pin image and chart tags. Renovate is the updater. Do not use `latest`.
- One CNI (Cilium), one HTTP gateway (Envoy Gateway), one block store
  (Rook-Ceph), one secrets operator (External Secrets). Do not add the
  overlapping pieces called out in `docs/lessons-from-v1.md`.

## Layout

```text
kubernetes/apps/<namespace>/<app>/ks.yaml
kubernetes/apps/<namespace>/<app>/app/helmrelease.yaml
kubernetes/apps/<namespace>/<app>/app/ocirepository.yaml
talos/topf.yaml
talos/all/                 patches for every node
talos/control-plane/       patches for control-plane nodes
bootstrap/helmfile/        first install, before Flux syncs the repo
docs/adr/                  decisions
kubernetes/examples/       not reconciled
```

`kubernetes/apps` has no root kustomization. The Flux instance sync path
is that directory, and kustomize-controller includes each child that has a
`kustomization.yaml`.

## Checks

From a workstation with the tools in `mise.toml` installed:

```sh
bash scripts/validate.sh
```

CI runs the same steps in `.github/workflows/validate.yaml`: yamllint,
kubeconform, a check that any `*.sops.yaml` is encrypted, gitleaks on the
working tree, and `renovate-config-validator` for Renovate 44.188.2.

## What was adopted from hve-core

Adopted, and cited so it is not invented:

- Canonical-style repo instructions, here, with
  `.github/copilot-instructions.md` deferring to them. hve-core itself uses
  `.github/copilot-instructions.md` as the long file. This repo inverts
  that because `AGENTS.md` is the canonical file.
- `.github/instructions/*.instructions.md` with `applyTo` frontmatter
  (`.github/instructions/README.md`).
- ADR headings from MADR v4.0.0, which hve-core vendors in
  `.github/instructions/project-planning/adr-standards.instructions.md`.
  Records live in `docs/adr/` rather than hve-core's `docs/planning/adrs/`.
- Pull request template with a human review checkbox agents must not tick
  (priority rules in hve-core `.github/copilot-instructions.md`).
- gitleaks on the default ruleset (`.gitleaks.toml` extends the built-in
  rules, the same idea as hve-core's `.gitleaks.toml`). The workflow scans
  the working tree, not full history, because history is retained on
  purpose.
- The research, plan, implement, review sequence for non-trivial edits
  (`docs/rpi/README.md`), without the RPI agent or tracking folders.

Not adopted: the VS Code extension, `plugin.json`, skills, custom agents,
evals, PowerShell validators, Docusaurus, and `.copilot-tracking/`. hve-core
describes itself as a pattern source rather than a dependency. This repo
copies the patterns above and does not submodule it.
