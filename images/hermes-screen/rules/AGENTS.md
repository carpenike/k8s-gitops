# Rules for every coding engine in Hank's sandbox

You are a coding engine (Claude Code, Cursor or Copilot) started by Hank,
Ryan's homelab engineer bot, in his sandbox. These rules apply to every
repository you work in, on top of the repository's own `AGENTS.md`.
(k8s-gitops: images/hermes-screen/rules/AGENTS.md, the one source for all
three engines.)

## Git and GitHub

- Work on the branch the task names (`hermes/<slug>`), never on the
  default branch, and never on `rebuild` in carpenike/k8s-gitops: Flux
  deploys it.
- Every change goes through a pull request. Open it as a draft with
  `gh pr create --draft`.
- End every pull request body with the line `Engine: <your engine>`, with
  the engine named in your task prompt.
- Never merge a pull request: no `gh pr merge`, with or without flags.
  Ryan's approval on GitHub merges it; GitHub refuses a merge without it.
- Never force-push, delete a branch, or change repository settings,
  secrets or rulesets.
- Your GitHub access cannot change `.github/workflows`. If a task needs
  that, say so instead of working around it.

## Secrets and private details

- Never print, log, commit or paste a secret, token or key, including the
  files under `/etc/hermes-claude-code`.
- Never put internal hostnames, IP addresses or home details into a
  commit, pull request or anything public. carpenike/k8s-gitops and
  carpenike/nix-config are public.

## Scope

- Do the task you were given. If it turns out bigger or riskier than the
  prompt says, stop and explain instead of widening it.
- Run the repository's own checks before you open the pull request, and
  say in its body which checks ran and which could not.
- Never deploy, apply or change a live system (`kubectl apply`,
  `flux reconcile`, `nixos-rebuild`, ssh to a host). Changes reach live
  systems only by Ryan merging the pull request.
