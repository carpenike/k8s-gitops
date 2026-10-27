#!/usr/bin/env bash
# Local counterpart of .github/workflows/validate.yaml. No cluster, no secrets.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

yamllint -c .yamllint.yml .
bash scripts/check-sops-encrypted.sh
bash scripts/kubeconform.sh

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-git --redact --config .gitleaks.toml --source .
else
  echo "gitleaks not installed; secret scan skipped" >&2
  exit 2
fi
