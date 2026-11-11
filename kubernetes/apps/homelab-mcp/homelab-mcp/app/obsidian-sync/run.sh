#!/bin/sh
# obsidian-sync: Obsidian's headless Sync client, keeping /vault/notes in step
# with the owner's devices. Three phases, written to $STATE for the liveness
# probe:
#   installing  npm ci from the pinned lockfile, once per lockfile, into the
#               volume (never baked into an image: the client is not
#               redistributable). A failed install retries; it never blocks
#               the pod, because this runs in a sidecar, not an init container.
#   waiting     until the one-time `ob login` and `ob sync-setup` have been run
#               in this container (docs/homelab-mcp.md, "Obsidian Sync").
#   syncing     `ob sync --continuous`. The client refreshes
#               /vault/notes/.obsidian/.sync.lock every second while its event
#               loop runs; the liveness probe restarts it if that stops.
# Variables are written $name, never with braces: Flux substitutes braced ones.
set -u
STATE=/tmp/obsidian-sync/state
mkdir -p /tmp/obsidian-sync /tmp/obsidian-sync/npm
phase() { echo "$1" > "$STATE"; echo "obsidian-sync: $1"; }

want=$(sha256sum /opt/obsidian-sync/package-lock.json | cut -c1-16)
cur=/opt/ob/$want
phase installing
until [ -x "$cur/node_modules/.bin/ob" ]; do
  new=/opt/ob/.new
  rm -rf "$new" && mkdir -p "$new"
  cp /opt/obsidian-sync/package.json /opt/obsidian-sync/package-lock.json "$new/"
  if (cd "$new" && npm ci --omit=dev --no-audit --no-fund --loglevel=warn); then
    for old in /opt/ob/*; do
      [ "$old" = "$cur" ] || rm -rf "$old"
    done
    mv "$new" "$cur"
  else
    rm -rf "$new"
    echo "obsidian-sync: install failed; retrying in 5 minutes"
    sleep 300
  fi
done
ln -sfn "$cur" /opt/ob/current

phase waiting
until [ -s "$XDG_CONFIG_HOME/obsidian-headless/auth_token" ] &&
  ob sync-status --path "$VAULT" > /dev/null 2>&1; do
  sleep 60
done

phase syncing
exec ob sync --continuous --path "$VAULT"
