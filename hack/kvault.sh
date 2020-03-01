#!/bin/bash

export REPO_ROOT=$(git rev-parse --show-toplevel)

name="secrets/$(dirname "$@")/$(basename -s .txt "$@")"
echo "Writing $name to vault"
if output=$(envsubst < "$REPO_ROOT/cluster/$*"); then
  printf '%s' "$output" | vault kv put "$name" values.yaml=-
fi
