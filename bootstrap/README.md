# Bootstrap

Flux is installed with the same helmfile shape as onedr0p/cluster-template.
`bootstrap/helmfile/apps.yaml` installs Cilium, CoreDNS, spegel, cert-manager,
the Flux Operator, and the Flux instance. Everything else reconciles from
`kubernetes/apps` after that.

The helmfile reads chart URLs from each `ocirepository.yaml` and values from
each `helmrelease.yaml`. It does not create secrets.

`crds.yaml` seeds the Prometheus Operator CRDs from
`prometheus-operator-crds` 32.0.2 once, before Cilium, and the external
snapshotter CRDs from `snapshot-controller` 0.1.2. The Prometheus chart is
operator v0.94.2, the same operator as kube-prometheus-stack 92.14.0. It
renders the CRDs as templates. Day-2 upgrades belong only to the Flux
HelmRelease `prometheus-operator-crds`, which sets `install.crds` and
`upgrade.crds` to `CreateReplace` and therefore also replaces anything the
chart places in a `crds/` directory. kube-prometheus-stack sets
`crds.enabled: false` and `install.crds` / `upgrade.crds: Skip`. Renovate
groups the two chart tags and waits until both have an update. The CRD
chart appVersion has to match the operator appVersion in
kube-prometheus-stack before that PR is merged.

The install sequence is `scripts/bootstrap-cluster.sh`. It refuses to run
without `--yes`, and it was not run from this branch. mise tasks
`bootstrap`, `bootstrap-talos`, and `bootstrap-apps` call it.

Order, matching cluster-template: `topf secrets`, `topf apply
--auto-bootstrap`, talosconfig, kubeconfig, `sops-age` from `./age.key`,
`onepassword-sdk` from `$ONEPASSWORD_SERVICE_ACCOUNT_TOKEN`, CRDs from
`bootstrap/helmfile/crds.yaml`, then `helmfile sync` retried twice.

`topf apply` decrypts the upsmon password from
`kubernetes/apps/nut-system/nut/app/secret.sops.yaml` through vals. `sops`
and `vals` have to be on PATH, and the run is from `talos/` so the relative
ref resolves. The age recipient is already in `.sops.yaml`. Keep `age.key`
off the repo and encrypt the Talos secrets bundle with sops before
committing it.

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
