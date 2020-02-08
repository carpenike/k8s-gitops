#!/bin/bash

name="secrets/$(dirname "$@")/$(basename -s .txt "$@")"
echo "Writing $name to vault"
if output=$(envsubst < "$REPO_ROOT/$*"); then
  printf '%s' "$output" | vault kv put "$name" values.yaml=-
fi