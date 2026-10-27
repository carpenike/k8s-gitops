# Bootstrap

Flux is installed with the same helmfile shape as onedr0p/cluster-template.
`bootstrap/helmfile/apps.yaml` installs Cilium, CoreDNS, spegel, cert-manager,
the Flux Operator, and the Flux instance. Everything else reconciles from
`kubernetes/apps` after that.

The helmfile reads chart URLs from each `ocirepository.yaml` and values from
each `helmrelease.yaml`. It does not create secrets.

Before the first `helmfile sync` (not run from this branch):

1. Build a Talos schematic with `nut-client` and replace the placeholder
   schematic id. Apply machine config with `topf` only after `docs/placeholders.md`
   is filled in. Do not commit the generated secrets bundle.
2. Create the Flux decryption secret and the 1Password token out of band.
   Commands are below. The token value comes from 1Password, not from git.

```sh
# Age private key stays on the workstation and in the cluster secret.
# Generate a new one. Do not commit age.key, and do not reuse the v1 age key.
# Add the public recipient to the .sops.yaml key group next to the YubiKey
# fingerprint, then re-encrypt. Ryan's own decrypt path is the YubiKey.
# See docs/sops.md.
kubectl --namespace flux-system create secret generic sops-age \
  --from-file=age.agekey=./age.key

kubectl --namespace external-secrets create secret generic onepassword-sdk \
  --from-literal=token="$ONEPASSWORD_SERVICE_ACCOUNT_TOKEN"
```

cert-manager's Cloudflare token, the tunnel token, MikroTik API credentials,
and the webhook token are ExternalSecrets. They stay unresolved until the
ClusterSecretStore can read 1Password.

This repository is public. Do not add those commands with real values, and
do not run them from CI.
