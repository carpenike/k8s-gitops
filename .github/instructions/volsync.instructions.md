# GitHub Copilot Instructions for VolSync Integration

> **Schema Reference Best Practice (last updated: 2025-05-27):**
> - Use the latest authoritative schema URLs for each manifest type (see below).
> - Place schema references as a comment before the document separator (---) at the top of each YAML file.
> - Review and update schema URLs regularly as upstream projects change.

## When to Apply These Instructions

These instructions should be applied when working with persistent storage in applications, including:
- Any application that requires persistent storage
- When creating new PVCs that should be backed up
- When integrating with the VolSync operator for data backup and recovery
- When working with both application-specific and shared PVCs

## VolSync Integration Pattern

1. For applications with persistent storage, always include VolSync as a dependency in the kustomization:
   ```yaml
   # In ks.yaml
   spec:
     dependsOn:
       - name: rook-ceph-cluster
       - name: volsync
   ```

2. Configure VolSync parameters through the postBuild substitution:
   ```yaml
   # In ks.yaml
   spec:
     postBuild:
       substitute:
         APP: app-name  # Used as the PVC name
         VOLSYNC_CAPACITY: 10Gi
         VOLSYNC_STORAGECLASS: ceph-block  # Or ceph-filesystem for ReadWriteMany
         VOLSYNC_ACCESSMODES: ReadWriteOnce
         VOLSYNC_SNAPSHOTCLASS: csi-ceph-block  # Optional
   ```

3. Include the VolSync template in the app's kustomization:
   ```yaml
   # In app/kustomization.yaml
   resources:
     - ./helmrelease.yaml
     - ./pvc.yaml  # For additional volumes
     - ../../../../templates/volsync
   ```

4. Reference the VolSync-backed PVC in the HelmRelease:
   ```yaml
   # In app/helmrelease.yaml
   persistence:
     config:
       existingClaim: app-name  # This matches ${APP} from the ks.yaml
   ```

## Common VolSync Configuration Patterns

### Basic Configuration (ReadWriteOnce)

```yaml
# In ks.yaml
postBuild:
  substitute:
    APP: app-name
    VOLSYNC_CAPACITY: 10Gi
```

### Configuration for Shared Access (ReadWriteMany)

```yaml
# In ks.yaml
postBuild:
  substitute:
    APP: app-name
    VOLSYNC_CAPACITY: 10Gi
    VOLSYNC_STORAGECLASS: ceph-filesystem
    VOLSYNC_ACCESSMODES: ReadWriteMany
    VOLSYNC_SNAPSHOTCLASS: csi-ceph-filesystem
```

### Configuration with Multiple PVCs

When an application needs multiple PVCs:
1. Create the main config PVC using VolSync (handled automatically)
2. Create additional PVCs manually in the app/pvc.yaml file
3. Reference both PVCs in the HelmRelease:

```yaml
# In app/pvc.yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.PersistentVolumeClaim
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-name-cache  # Additional PVC
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 5Gi
  storageClassName: ceph-block

# In app/helmrelease.yaml
persistence:
  config:
    existingClaim: app-name  # VolSync-backed main PVC
  cache:
    existingClaim: app-name-cache  # Additional PVC
    globalMounts:
      - path: /config/cache
```

## Working with Shared PVCs

For applications that need access to shared data (media files, etc.), combine VolSync-backed PVCs with shared PVCs:

```yaml
# In app/helmrelease.yaml
persistence:
  config:
    existingClaim: app-name  # VolSync-backed PVC for app config
  media:
    existingClaim: media-nfs-share-pvc  # Shared PVC
    globalMounts:
      - path: /media
```

## Best Practices

1. Use VolSync for all application configuration data that needs to be persisted
2. Use the default naming pattern where the PVC name matches the app name
3. Keep cache and temporary data in separate PVCs to avoid unnecessary backups
4. Use `ceph-block` and ReadWriteOnce for most application config volumes
5. Use `ceph-filesystem` and ReadWriteMany for volumes that need shared access
6. Always include VolSync in the dependsOn list for applications with persistent storage

## YAML Schema Validation Guidelines

- **PersistentVolumeClaim:**
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.PersistentVolumeClaim
  ```
