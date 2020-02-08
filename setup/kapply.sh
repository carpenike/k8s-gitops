#!/bin/bash

if output=$(envsubst < "$@"); then
  printf '%s' "$output" | kubectl apply -f -
fi
