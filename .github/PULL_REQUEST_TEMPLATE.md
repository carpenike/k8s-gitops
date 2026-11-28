## What changed

## Why

Link an ADR in `docs/adr/` when the change picks a component or a boundary.

## Checks

- [ ] `bash scripts/validate.sh` (or the Validate workflow) passed
- [ ] No new secret, token, age private key, home address, or internal hostname
- [ ] Placeholders that are still fake are listed in the PR

## Human review

- [ ] Reviewed and accepted by a person who owns this cluster

Agents leave that box unchecked.
