#!/bin/sh
# Points the git-owned paths in /config at the git-sync checkout, so a new
# commit on hass-config main replaces them atomically when git-sync swaps its
# symlink. Everything else in /config stays on the volume and belongs to Home
# Assistant (.storage, automations.yaml, scripts.yaml, scenes.yaml,
# custom_components, media). docs/apps/home-automation.md, "Config from git".
#
# Idempotent. A real file or directory found where a link belongs (the copy
# from Forge at cutover) is moved to /config/.pre-gitops/ once, not deleted.
#
# Flux postBuild substitution runs over this file (it is in a generated
# ConfigMap) and replaces every braced variable, so variables here are
# written $VAR, without braces.
set -eu

CHECKOUT=/git/hass-config
PATHS="configuration.yaml packages dashboards scripts blueprints custom_sentences www/streamline-card"

[ -d "$CHECKOUT" ] || { echo "no checkout at $CHECKOUT" >&2; exit 1; }
[ -f "$CHECKOUT/configuration.yaml" ] || { echo "checkout has no configuration.yaml" >&2; exit 1; }

for p in $PATHS; do
  dest="/config/$p"
  src="$CHECKOUT/$p"
  if [ ! -e "$src" ]; then
    # Not in git (yet): leave whatever the volume has.
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  if [ -L "$dest" ]; then
    [ "$(readlink "$dest")" = "$src" ] && continue
  elif [ -e "$dest" ]; then
    mkdir -p "/config/.pre-gitops/$(dirname "$p")"
    mv "$dest" "/config/.pre-gitops/$p"
    echo "moved $dest to /config/.pre-gitops/$p"
  fi
  # -n replaces an existing link instead of following it into a directory.
  ln -sfn "$src" "$dest"
  echo "linked $dest -> $src"
done
