# Application Deployment Pattern Guide

This document outlines the standard patterns for deploying applications in this GitOps repository.

## Directory Structure

All applications should follow this standardized directory structure:

```
kubernetes/<cluster>/apps/<namespace>/<app-name>/
├── app/                   # Directory containing application resources
│   ├── externalsecret.yaml  # If using secrets
│   ├── helmrelease.yaml     # The main Helm release definition
│   ├── kustomization.yaml   # References all resources and templates
│   └── pvc.yaml             # If using additional persistent storage
└── ks.yaml                  # Flux Kustomization resource
```

## Key Components

### 1. Flux Kustomization (ks.yaml)

This file defines how Flux should deploy the application:

```yaml
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app app-name
  namespace: flux-system
spec:
  targetNamespace: target-namespace
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  path: ./kubernetes/<cluster>/apps/<namespace>/<app-name>/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: k8s-gitops-kubernetes
  dependsOn:
    # Include relevant dependencies
    - name: external-secrets-stores  # If using secrets
    - name: rook-ceph-cluster        # If using storage
    - name: volsync                  # If using persistent volumes with backups
  postBuild:
    substitute:
      APP: *app
      # Additional substitution variables
      VOLSYNC_CAPACITY: 10Gi         # If using VolSync
```

### 2. Application Kustomization (app/kustomization.yaml)

This file brings together all the application resources:

```yaml
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./pvc.yaml                     # If using additional volumes
  - ./externalsecret.yaml          # If using secrets
  - ../../../../templates/volsync  # If using VolSync
  - ../../../../templates/gatus/guarded  # If using monitoring
```

### 3. HelmRelease (app/helmrelease.yaml)

The main application definition:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: app-name
spec:
  interval: 30m
  chart:
    spec:
      chart: app-template
      version: x.y.z  # Always pin versions
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system
  # Remediation strategy
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
  # Application configuration
  values:
    # Application values here
```

## Common Patterns by Application Type

### Applications with Persistent Storage

For applications that need persistent storage, follow these patterns:

1. **Include VolSync dependencies**:
   ```yaml
   dependsOn:
     - name: rook-ceph-cluster
     - name: volsync
   ```

2. **Configure VolSync parameters**:
   ```yaml
   postBuild:
     substitute:
       APP: *app
       VOLSYNC_CAPACITY: 10Gi
       VOLSYNC_STORAGECLASS: ceph-block
       VOLSYNC_ACCESSMODES: ReadWriteOnce
   ```

3. **Reference in HelmRelease**:
   ```yaml
   persistence:
     config:
       existingClaim: app-name  # Matches ${APP}
   ```

### Applications with Secrets

For applications that need secrets from 1Password:

1. **Include external-secrets dependency**:
   ```yaml
   dependsOn:
     - name: external-secrets-stores
   ```

2. **Create an ExternalSecret**:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/external-secrets.io/externalsecret_v1beta1.json
   apiVersion: external-secrets.io/v1beta1
   kind: ExternalSecret
   metadata:
     name: app-name
   spec:
     secretStoreRef:
       kind: ClusterSecretStore
       name: onepassword-connect
     target:
       name: app-name-secret
       creationPolicy: Owner
     data:
       - secretKey: key-name
         remoteRef:
           key: op://vault/item/field
   ```

3. **Reference in HelmRelease**:
   ```yaml
   env:
     - name: SECRET_VALUE
       valueFrom:
         secretKeyRef:
           name: app-name-secret
           key: key-name
   ```

### Applications with Ingress

For applications that need external access:

1. **For internal access**:
   ```yaml
   ingress:
     main:
       annotations:
         external-dns.alpha.kubernetes.io/target: internal.holthome.net
       className: internal-nginx
       hosts:
         - host: app-name.holthome.net
           paths:
             - path: /
               service:
                 identifier: app
                 port: http
   ```

2. **For external access**:
   ```yaml
   ingress:
     main:
       annotations:
         external-dns.alpha.kubernetes.io/target: external.holthome.net
       className: external-nginx
       hosts:
         - host: app-name.holthome.net
           paths:
             - path: /
               service:
                 identifier: app
                 port: http
   ```

## Best Practices

1. **Schema Validation**: Always include schema references at the top of your YAML files
2. **Version Pinning**: Always pin chart and image versions
3. **Resource Limits**: Always define resource limits and requests
4. **Health Probes**: Configure appropriate health checks
5. **Security Context**: Use appropriate security contexts
6. **Annotations**: Use reloader.stakater.com/auto: "true" for automatic pod restarts on config changes
7. **Dependencies**: Define all required dependencies in the Flux Kustomization
8. **Networking**: Use the appropriate ingress class and DNS target based on access requirements

## Template Structure

The repository maintains several shared templates:

1. **VolSync**: For persistent storage with backup capabilities
2. **Gatus**: For application monitoring
   - `guarded`: For authenticated monitoring
   - `external`: For external monitoring

These templates should be included in your application's kustomization.yaml when needed.
