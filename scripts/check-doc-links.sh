#!/usr/bin/env bash
# Fails when a reference to a doc in this repository does not resolve.
#
# Three checks, on tracked files only:
#   1. A relative Markdown link, [text](path), names a file that exists.
#   2. Its #anchor, when the target is a Markdown file, is a heading there.
#   3. A plain mention of docs/<something>.md anywhere in the tree (manifest
#      comments, alert annotations, bot prompts) names a file that exists.
#
# Web links are not fetched. No cluster, no secrets, no network.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# docs/ paths that belong to another repository. Check 3 skips them. Add a
# path here only when the text around the mention names that repository.
EXTERNAL_DOCS="
docs/rpi/README.md
docs/pocketid.md
docs/MFP-COOKIE-RUNBOOK.md
docs/RECON.md
docs/services/openproject.md
docs/deploying/kubernetes.md
"
# docs/rpi/README.md             microsoft/hve-core
# docs/pocketid.md               network-config
# docs/MFP-COOKIE-RUNBOOK.md     carpenike/mcp
# docs/RECON.md                  carpenike/schoolhouse
# docs/services/openproject.md   carpenike/nix-config
# docs/deploying/kubernetes.md   Tuwunel upstream

fail=0
report() {
  echo "$1" >&2
  fail=1
}

# GitHub's heading anchors for one Markdown file, one per line. Fenced code
# is skipped. A repeated heading gets -1, -2 and so on, as GitHub does.
anchors() {
  awk '
    /^[[:space:]]*(```|~~~)/ { fence = !fence; next }
    fence { next }
    /^#{1,6}[[:space:]]/ {
      line = $0
      sub(/^#+[[:space:]]+/, "", line)
      sub(/[[:space:]]+#*[[:space:]]*$/, "", line)
      # Keep the text of a link, drop its target.
      while (match(line, /\[[^]]*\]\([^)]*\)/)) {
        link = substr(line, RSTART, RLENGTH)
        text = link
        sub(/^\[/, "", text)
        sub(/\]\(.*$/, "", text)
        line = substr(line, 1, RSTART - 1) text substr(line, RSTART + RLENGTH)
      }
      line = tolower(line)
      gsub(/[^a-z0-9 _-]/, "", line)
      gsub(/ /, "-", line)
      if (line in seen) {
        print line "-" seen[line]
        seen[line]++
      } else {
        print line
        seen[line] = 1
      }
    }
  ' "$1"
}

# Checks 1 and 2.
while IFS= read -r file; do
  dir="$(dirname "${file}")"
  # Links inside fenced code are examples, not links.
  awk '
    /^[[:space:]]*(```|~~~)/ { fence = !fence; next }
    !fence { print FNR ":" $0 }
  ' "${file}" | { grep -o -E '^[0-9]+:|\]\([^)]+\)' || true; } | {
    line=""
    while IFS= read -r token; do
      case "${token}" in
        *:) line="${token%:}"; continue ;;
      esac
      target="${token#](}"
      target="${target%)}"
      # Drop an optional link title: [text](path "title").
      target="$(printf '%s' "${target}" | sed -E 's/[[:space:]]+"[^"]*"$//')"
      case "${target}" in
        http://* | https://* | mailto:* | '<'*) continue ;;
      esac
      path="${target%%#*}"
      anchor=""
      case "${target}" in
        *'#'*) anchor="${target#*#}" ;;
      esac
      if [ -z "${path}" ]; then
        resolved="${file}"
      else
        resolved="${dir}/${path}"
      fi
      if [ ! -e "${resolved}" ]; then
        report "${file}:${line}: link target does not exist: ${target}"
        continue
      fi
      if [ -n "${anchor}" ] && [ -f "${resolved}" ]; then
        case "${resolved}" in
          *.md)
            if ! anchors "${resolved}" | grep -q -x -F -- "${anchor}"; then
              report "${file}:${line}: no heading for #${anchor} in ${resolved}"
            fi
            ;;
        esac
      fi
    done
    exit "${fail}"
  } || fail=1
done < <(git ls-files '*.md')

# Check 3.
while IFS=: read -r file line path; do
  [ -e "${path}" ] && continue
  if printf '%s' "${EXTERNAL_DOCS}" | grep -q -x -F -- "${path}"; then
    continue
  fi
  report "${file}:${line}: ${path} does not exist"
done < <(git grep -I -n -o -E 'docs/[A-Za-z0-9._/-]+\.md' -- . ':!scripts/check-doc-links.sh')

if [ "${fail}" -ne 0 ]; then
  echo "doc links: broken references above" >&2
  exit 1
fi
echo "doc links: ok"
