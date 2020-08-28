#!/usr/bin/env bash

ACTION=$1
DURATION=$2
NAMESPACE=default

BLOCKY_PODS=$(kubectl get pods -n $NAMESPACE -o=jsonpath="{range .items[*]}{.metadata.name} " -l app.kubernetes.io/name=blocky)

for pod in $BLOCKY_PODS; do
    case "${ACTION}" in
        status)
            kubectl exec -n $NAMESPACE "${pod}" -- /app/blocky blocking status;
        ;;
        enable)
            kubectl exec -n $NAMESPACE "${pod}" -- /app/blocky blocking enable;
        ;;
        disable)
            if [ -z "${DURATION}" ]; then
                kubectl exec -n $NAMESPACE "${pod}" -- /app/blocky blocking disable
            else
                kubectl exec -n $NAMESPACE "${pod}" -- /app/blocky blocking disable --duration ${DURATION};
            fi
        ;;
    esac
done
