# Copilot instructions

`AGENTS.md` is the canonical instruction file for this repository. Read it
before editing. The notes below are the pieces of
[microsoft/hve-core](https://github.com/microsoft/hve-core) that apply here.

From `.github/copilot-instructions.md` in hve-core (priority rules, adapted):

- Conventions in this repo win over a generic Kubernetes layout.
- Task-specific files in `.github/instructions/` are read before editing the
  paths they name.
- Do not mark a human review checkbox complete. Only a person does that.
- Fix the cause of a failing check. Do not silence kubeconform, yamllint, or
  gitleaks with a broad ignore.
- Do not add a compatibility layer for the archived v1 tree. `archive/talos-v1`
  is the frozen copy.

From `docs/rpi/README.md`: non-trivial changes are research, then a plan,
then the edit, then a check against the ADRs. Specs land in the PR or in
`docs/adr/`. Implementation of those specs is a pull request.

This file does not vendor hve-core agents, skills, evals, or the VS Code
extension. Those are a product framework, not GitOps config.
