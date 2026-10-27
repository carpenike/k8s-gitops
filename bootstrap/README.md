# Bootstrap

Flux is installed with the same helmfile shape as onedr0p/cluster-template.
`bootstrap/helmfile/apps.yaml` installs Cilium, CoreDNS, spegel, cert-manager,
the Flux Operator, and the Flux instance. Everything else reconciles from
`kubernetes/apps` after that.

The helmfile reads chart URLs from each `ocirepository.yaml` and values from
each `helmrelease.yaml`. It does not create secrets.

The install sequence is `scripts/bootstrap-cluster.sh`. It refuses to run
without `--yes`, and it was not run from this branch. mise tasks
`bootstrap`, `bootstrap-talos`, and `bootstrap-apps` call it.

Order, matching cluster-template: `topf secrets`, `topf apply
--auto-bootstrap`, talosconfig, kubeconfig, `sops-age` from `./age.key`,
`onepassword-sdk` from `$ONEPASSWORD_SERVICE_ACCOUNT_TOKEN`, CRDs from
`bootstrap/helmfile/crds.yaml`, then `helmfile sync` retried twice.

`NUT_UPSMON_PASSWORD` must be set before apply. The age recipient is
already in `.sops.yaml`. Keep `age.key` off the repo and encrypt the Talos
secrets bundle with sops before committing it.

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
