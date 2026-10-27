#!/usr/bin/env bash
# Fail if a *.sops.yaml file is present and not encrypted.
# .sops.yaml at the repo root is the creation-rules file, not ciphertext.
# Zero encrypted files is success: nothing has been encrypted yet.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
found=0
status=0

while IFS= read -r -d '' file; do
  found=1
  if ! grep -q 'ENC\[' "${file}"; then
    echo "unencrypted sops file: ${file}" >&2
    status=1
  fi
done < <(find "${ROOT}" -type f \( -name '*.sops.yaml' -o -name '*.sops.yml' \) ! -name '.sops.yaml' ! -name '.sops.yml' -print0)

if [[ "${found}" -eq 0 ]]; then
  echo "no encrypted *.sops.yaml files"
fi

exit "${status}"
