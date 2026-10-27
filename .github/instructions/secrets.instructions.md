---
description: What may be committed in this public repository
applyTo: "**/*secret*,**/*.sops.*,**/*externalsecret*"
---

# Secrets

The repository is public. History is kept, so a secret committed once stays reachable.

- Do not commit tokens, age private keys, Talos secrets bundles, tunnel credentials, or kubeconfigs.
- 1Password is the source of truth. ExternalSecrets reference item names that start with `PLACEHOLDER_` until real names are chosen.
- The 1Password service-account token and the age key are bootstrap secrets created out of band. See `bootstrap/README.md`.
- A file named `*.sops.yaml` must already be encrypted (`ENC[`). `scripts/check-sops-encrypted.sh` enforces that. Absence of those files is expected on this branch.
- `.sops.yaml.example` uses the marker `AGE_RECIPIENT_PLACEHOLDER`. Do not paste a real recipient over it in a commit that also adds the private key.
