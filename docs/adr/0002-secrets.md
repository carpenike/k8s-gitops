---
status: accepted
date: 2026-10-27
decision-makers: Ryan Holt
---

# External Secrets for app secrets, SOPS only for bootstrap

## Context and Problem Statement

The cluster needs Cloudflare, MikroTik, backup, and webhook credentials.
The repository is public. v1 ran 1Password Connect inside the cluster and
also encrypted files with age and PGP.

## Decision Drivers

- 1Password stays the source of truth so rotation does not mean a new commit
- No Connect server to operate
- Flux still has to decrypt something before External Secrets is up
- A leaked git history cannot be rewritten away

## Considered Options

- SOPS/age for every secret
- External Secrets with the 1Password SDK provider, SOPS only for bootstrap
- 1Password Connect, as in v1

## Decision Outcome

Chosen option: "External Secrets with the 1Password SDK provider, SOPS only
for bootstrap", because the SDK uses a service-account token and does not
need a Connect pod. The age private key and that token are created by hand
and are not committed. App credentials are ExternalSecret resources whose
item names are placeholders until a vault exists.

Personal decryption reuses the YubiKey OpenPGP fingerprint from
`archive/talos-v1:.sops.yaml` (`user_ryan`). That file put the fingerprint
and the cluster age recipient in one SOPS key group, so either key could
decrypt. `.sops.yaml` keeps the fingerprint and leaves the age slot empty.
The v1 age recipient is not reused. This branch does not generate a
replacement. See `docs/sops.md`.

### Consequences

- Good, because rotating an app secret is a 1Password edit
- Bad, because the first bootstrap has two out-of-band secrets
- cert-manager waits on External Secrets for the Cloudflare token, instead of
  a sops secret shipped at install time

## Pros and Cons of the Options

### SOPS for everything

- Good, because the cluster can install with no external secret store
- Bad, because every rotation is a commit, and the files sit in a public repo

### External Secrets SDK plus SOPS bootstrap

- Good, because the public git data is item names, not secret values
- Bad, because the ClusterSecretStore is useless until the token exists

### 1Password Connect

- Good, because v1 already had the pattern
- Bad, because Connect is another deployment, and it was a hidden dependency
