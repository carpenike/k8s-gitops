#!/usr/bin/env bash
# Same approach as onedr0p/cluster-template template/resources/kubeconform.sh.
# Builds every Kustomize directory under kubernetes/apps and kubernetes/examples.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

kubeconform_args=(
  -strict
  -ignore-missing-schemas
  -skip
  "Gateway,HTTPRoute,Secret,DNSEndpoint"
  -schema-location
  default
  -schema-location
  "https://k8s-schemas.home-operations.com/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -verbose
)

find "${ROOT}/kubernetes/apps" "${ROOT}/kubernetes/examples" \
  -type f -name kustomization.yaml -print0 |
  while IFS= read -r -d '' file; do
    dir="$(dirname "${file}")"
    # Components are included by parent builds. Building one alone fails.
    if grep -q 'kind: Component' "${file}"; then
      continue
    fi
    echo "=== Validating kustomization in ${dir} ==="
    kustomize build "${dir}" --load-restrictor LoadRestrictionsNone |
      kubeconform "${kubeconform_args[@]}"
  done
