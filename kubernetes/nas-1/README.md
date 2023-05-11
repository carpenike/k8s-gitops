## NAS-1

NAS-1 is my backup NAS. I've got it configured as a k8s cluster to orchestrate infrastructure as code for the required apps on the node.

## How to bootstrap

Assuming you are in the `nas-1` root folder:

### Flux

#### Install Flux

```sh
kubectl apply --server-side --kustomize ./bootstrap
```

### Apply Cluster Configuration

_These cannot be applied with `kubectl` in the regular fashion due to some files being encrypted with sops_

```sh
sops --decrypt ./bootstrap/age-key.sops.yaml | kubectl apply -f -
kubectl apply -f ./flux/vars/cluster-settings.yaml
```

### Kick off Flux applying this repository

```sh
kubectl apply --server-side --kustomize ./flux/config
```
