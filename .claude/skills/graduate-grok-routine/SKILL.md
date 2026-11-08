---
name: graduate-grok-routine
description: Move a Grok Bot routine into a Hermes bot's git-declared routines. Use when Ryan pastes a Grok routine handoff (a public spec, a private notepad block, and what can't move), or asks to graduate, move or migrate a Grok routine to Hermes or to Chief's routines.yaml.
---

# Graduate a Grok routine to Hermes

Read `.github/instructions/hermes-routines.instructions.md` and follow it
step by step. It is the source of truth; this skill only points to it, so
Copilot and other agents get the same rules.

In short:

1. Check that the routine qualifies.
2. Add it to `kubernetes/apps/hermes/<bot>/routines.yaml`.
3. Give Ryan a script for the private block, for 1Password item
   `hermes-<bot>-routines`. The block never goes into git or the pull
   request.
4. Validate, and open a draft pull request that lists Ryan's steps.
