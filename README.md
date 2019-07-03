# Helpful Links

## General

Sort Events by TimeStamp: `kubectl get events --sort-by='{.lastTimestamp}'`

## Prometheus

Enabling monitoring via annotations: https://medium.com/@dmitrio_/installing-rook-v1-0-on-aks-f8c22a75d93d

## Rook CEPH

Access toolbox: `kubectl -n rook-ceph exec -it $(kubectl -n rook-ceph get pod -l "app=rook-ceph-tools" -o jsonpath='{.items[0].metadata.name}') bash`

Decode admin password: `kubectl -n rook-ceph get secret rook-ceph-dashboard-password -o jsonpath="{['data']['password']}" | base64 --decode && echo`
