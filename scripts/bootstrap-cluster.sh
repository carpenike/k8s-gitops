#!/usr/bin/env bash
# Install sequence for a workstation that can reach the sleds.
# Matches the onedr0p cluster-template order: topf secrets, apply
# --auto-bootstrap, talosconfig, kubeconfig, sops-age, onepassword-sdk,
# CRDs, helmfile sync with a retry.
#
# This script talks to hardware. It does not run from CI.
# Pass --yes. Without it, the script prints the plan and exits.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="all"
YES=0

for arg in "$@"; do
  case "${arg}" in
    --yes) YES=1 ;;
    talos|apps|all) STAGE="${arg}" ;;
    *)
      echo "usage: $0 [--yes] [talos|apps|all]" >&2
      exit 2
      ;;
  esac
done

plan() {
  cat <<'EOF'
talos:
  1. topf secrets          (writes talos/secrets.sops.yaml, gitignored)
  2. topf apply --auto-bootstrap
  3. topf talosconfig      (talos/talosconfig, gitignored)
  4. topf kubeconfig       (./kubeconfig, gitignored)
apps:
  5. wait until nodes register
  6. create namespaces
  7. sops-age secret from ./age.key
  8. onepassword-sdk secret from $ONEPASSWORD_SERVICE_ACCOUNT_TOKEN
  9. apply CRDs from bootstrap/helmfile/crds.yaml
  10. helmfile sync, retried twice
topf reads the upsmon password from the SOPS secret. sops and vals must
be on PATH. If ./age.key exists it is exported as SOPS_AGE_KEY_FILE.
Until the nut-upsd DaemonSet is running, upsmon retries.
EOF
}

if [[ "${YES}" -ne 1 ]]; then
  plan
  echo "Refusing to run. Re-invoke with --yes when the sleds are in maintenance mode." >&2
  exit 2
fi

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing command: $1" >&2
    exit 1
  fi
}

talos_stage() {
  require topf
  require sops
  require vals
  if [[ -f "${ROOT}/age.key" ]]; then
    export SOPS_AGE_KEY_FILE="${ROOT}/age.key"
  fi
  (
    cd "${ROOT}/talos"
    if [[ ! -f secrets.sops.yaml ]]; then
      topf secrets --confirm=false >/dev/null
    fi
    topf apply --auto-bootstrap --confirm=false
    topf talosconfig > talosconfig
    topf kubeconfig --validity 8760h > "${ROOT}/kubeconfig"
  )
}

apps_stage() {
  require kubectl
  require helmfile
  require yq
  export KUBECONFIG="${KUBECONFIG:-${ROOT}/kubeconfig}"
  if [[ ! -f "${ROOT}/age.key" ]]; then
    echo "age.key is missing. Generate it locally. See .sops.yaml." >&2
    exit 1
  fi
  if [[ -z "${ONEPASSWORD_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
    echo "ONEPASSWORD_SERVICE_ACCOUNT_TOKEN is empty." >&2
    exit 1
  fi

  deadline=$((SECONDS + 600))
  until kubectl wait nodes --for=condition=Ready=False --all --timeout=10s >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "timed out waiting for nodes to register" >&2
      exit 1
    fi
    sleep 5
  done

  for app in "${ROOT}/kubernetes/apps"/*/; do
    ns="$(basename "${app}")"
    kubectl create namespace "${ns}" --dry-run=client -o yaml \
      | kubectl apply --server-side --filename - >/dev/null
  done

  kubectl --namespace flux-system create secret generic sops-age \
    --from-file=age.agekey="${ROOT}/age.key" \
    --dry-run=client -o yaml \
    | kubectl apply --server-side --filename - >/dev/null
  kubectl --namespace external-secrets create secret generic onepassword-sdk \
    --from-literal=token="${ONEPASSWORD_SERVICE_ACCOUNT_TOKEN}" \
    --dry-run=client -o yaml \
    | kubectl apply --server-side --filename - >/dev/null

  helmfile --file "${ROOT}/bootstrap/helmfile/crds.yaml" template --quiet \
    | yq eval-all 'select(.kind == "CustomResourceDefinition")' \
    | kubectl apply --server-side --force-conflicts --filename - >/dev/null

  ok=0
  for _ in 1 2 3; do
    if helmfile --file "${ROOT}/bootstrap/helmfile/apps.yaml" sync --hide-notes; then
      ok=1
      break
    fi
    sleep 20
  done
  if [[ "${ok}" -ne 1 ]]; then
    echo "helmfile sync failed after 3 attempts" >&2
    exit 1
  fi
}

case "${STAGE}" in
  talos) talos_stage ;;
  apps) apps_stage ;;
  all)
    talos_stage
    apps_stage
    ;;
esac
