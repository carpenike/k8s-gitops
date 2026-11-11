---
description: What may be committed in this public repository
applyTo: "**/*secret*,**/*.sops.*,**/*externalsecret*"
---

# Secrets

The repository is public. History is kept, so a secret committed once stays reachable.

- Do not commit tokens, age private keys, Talos secrets bundles, tunnel credentials, or kubeconfigs.
- 1Password is the source of truth. ExternalSecrets name real items in vault `k8s-secrets`. `PLACEHOLDER_` names appear only under `kubernetes/examples/`, which Flux does not apply.
- The 1Password service-account token and the age private key are bootstrap secrets created out of band. See `bootstrap/README.md`.
- Ryan's SOPS access is the YubiKey OpenPGP fingerprint in `.sops.yaml`. Do not commit a copy of that key. Flux decrypts with the cluster age recipient in the same key group. See `docs/sops.md`.
- A file named `*.sops.yaml` must already be encrypted (`ENC[`). `scripts/check-sops-encrypted.sh` enforces that.
