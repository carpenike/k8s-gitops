# GitHub Copilot Instructions for Kubernetes Applications

> **Schema Reference Best Practice (last updated: 2025-05-27):**
> - Use the latest authoritative schema URLs for each manifest type (see below).
> - Place schema references as a comment before the document separator (---) at the top of each YAML file.
> - Review and update schema URLs regularly as upstream projects change.

## When to Apply These Instructions

These instructions should be applied when working with Kubernetes application manifests, including:
- Files in `/kubernetes/*/apps/` directories
- When creating or modifying application deployments
- When working with namespace resources, PVCs, services, or other application-level Kubernetes objects
- When setting up application monitoring, networking, or security

## Application Structure

1. Place each application in its own directory under `/kubernetes/<cluster>/apps/<namespace>/<app-name>/`:
   ```
   kubernetes/<cluster>/apps/<namespace>/<app-name>/
   ├── app/                   # Directory containing application resources
   │   ├── externalsecret.yaml  # If using secrets
   │   ├── helmrelease.yaml     # The main Helm release definition
   │   ├── kustomization.yaml   # References all resources and templates
   │   └── pvc.yaml             # If using additional persistent storage
   └── ks.yaml                  # Flux Kustomization resource
   ```

2. The app directory's kustomization.yaml should include all resources and templates:
   ```yaml
   apiVersion: kustomize.config.k8s.io/v1beta1
   kind: Kustomization
   resources:
     - ./helmrelease.yaml
     - ./pvc.yaml             # If using additional volumes
     - ./externalsecret.yaml  # If using secrets
     - ../../../../templates/volsync  # If using volsync for backups
     - ../../../../templates/gatus/guarded  # If using monitoring
   ```

3. Create a Flux Kustomization (ks.yaml) to reference the app directory:
   ```yaml
   apiVersion: kustomize.toolkit.fluxcd.io/v1
   kind: Kustomization
   metadata:
     name: app-name
     namespace: flux-system
   spec:
     targetNamespace: namespace-name
     commonMetadata:
       labels:
         app.kubernetes.io/name: app-name
     path: ./kubernetes/cluster-0/apps/namespace-name/app-name/app
     prune: true
     sourceRef:
       kind: GitRepository
       name: k8s-gitops-kubernetes
     dependsOn:
       - name: rook-ceph-cluster  # For storage
       - name: volsync           # For backups
     postBuild:
       substitute:
         APP: app-name
         VOLSYNC_CAPACITY: 10Gi
   ```

## Common Application Patterns

1. For namespaces, follow this pattern:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.Namespace
   apiVersion: v1
   kind: Namespace
   metadata:
     name: namespace-name
     labels:
       kustomize.toolkit.fluxcd.io/prune: disabled
   ```

2. For PersistentVolumeClaims:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.PersistentVolumeClaim
   apiVersion: v1
   kind: PersistentVolumeClaim
   metadata:
     name: app-name-data
     namespace: namespace-name
   spec:
     accessModes:
       - ReadWriteOnce
     resources:
       requests:
         storage: 10Gi  # Adjust as needed
     storageClassName: ceph-block  # Or appropriate storage class
   ```

3. For external secrets:
   ```yaml
   apiVersion: external-secrets.io/v1beta1
   kind: ExternalSecret
   metadata:
     name: app-name
     namespace: namespace-name
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

## Security Considerations

1. Use NetworkPolicies to restrict traffic:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: default-deny
     namespace: namespace-name
   spec:
     podSelector: {}
     policyTypes:
       - Ingress
       - Egress
   ```

2. Configure Pod Security Standards:
   ```yaml
   apiVersion: v1
   kind: Namespace
   metadata:
     name: namespace-name
     labels:
       pod-security.kubernetes.io/enforce: baseline
   ```

3. Always use RBAC with least privilege:
   ```yaml
   apiVersion: v1
   kind: ServiceAccount
   metadata:
     name: app-name
     namespace: namespace-name
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: Role
   metadata:
     name: app-name
     namespace: namespace-name
   rules:
     - apiGroups: [""]
       resources: ["pods"]
       verbs: ["get", "list", "watch"]
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: RoleBinding
   metadata:
     name: app-name
     namespace: namespace-name
   subjects:
     - kind: ServiceAccount
       name: app-name
   roleRef:
     kind: Role
     name: app-name
     apiGroup: rbac.authorization.k8s.io
   ```

## Monitoring and Health Checks

1. Add Prometheus ServiceMonitor:
   ```yaml
   apiVersion: monitoring.coreos.com/v1
   kind: ServiceMonitor
   metadata:
     name: app-name
     namespace: namespace-name
   spec:
     selector:
       matchLabels:
         app.kubernetes.io/name: app-name
     endpoints:
       - port: metrics
         interval: 1m
   ```

2. Configure health checks in Helm values:
   ```yaml
   probes:
     liveness:
       enabled: true
       custom: true
       spec:
         httpGet:
           path: /healthz
           port: http
         initialDelaySeconds: 10
         periodSeconds: 10
     readiness:
       enabled: true
       custom: true
       spec:
         httpGet:
           path: /readyz
           port: http
         initialDelaySeconds: 10
         periodSeconds: 10
   ```

## YAML Schema Validation Guidelines

- **Namespace:**
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.Namespace
  ```
- **PersistentVolumeClaim:**
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.PersistentVolumeClaim
  ```
