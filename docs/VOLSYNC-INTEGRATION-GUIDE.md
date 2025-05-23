# VolSync Integration Guide

This document explains how to integrate VolSync for persistent storage and backups in your applications.

## Overview

VolSync provides backup and recovery capabilities for persistent volumes in Kubernetes. In this repository, we use VolSync to:

1. Create persistent volumes for application data
2. Enable automatic backups of these volumes
3. Facilitate disaster recovery and migration

## Directory Structure

Applications using VolSync follow this structure:

```
kubernetes/<cluster>/apps/<namespace>/<app-name>/
├── app/
│   ├── helmrelease.yaml     # References the VolSync-backed PVC
│   ├── kustomization.yaml   # Includes the VolSync template
│   └── pvc.yaml             # Only for additional volumes
└── ks.yaml                  # Contains VolSync configuration
```

## Key Components

### 1. Flux Kustomization (ks.yaml)

The `ks.yaml` file defines VolSync parameters through substitution variables:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app-name
  namespace: flux-system
spec:
  # ...other fields...
  postBuild:
    substitute:
      APP: app-name                        # Used as the PVC name
      VOLSYNC_CAPACITY: 10Gi               # Storage capacity
      VOLSYNC_STORAGECLASS: ceph-block     # Storage class
      VOLSYNC_ACCESSMODES: ReadWriteOnce   # Access mode
      VOLSYNC_SNAPSHOTCLASS: csi-ceph-block # Optional snapshot class
  dependsOn:
    - name: rook-ceph-cluster
    - name: volsync
```

### 2. App Kustomization

The application's `kustomization.yaml` includes the VolSync template:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./pvc.yaml               # Optional: For additional volumes
  - ../../../../templates/volsync
```

### 3. HelmRelease Configuration

The `helmrelease.yaml` file references the VolSync-backed PVC:

```yaml
persistence:
  config:
    existingClaim: app-name  # This matches ${APP} from ks.yaml
```

## Common Patterns

### Basic Configuration (ReadWriteOnce)

For most applications that need standard single-pod access:

```yaml
# In ks.yaml
postBuild:
  substitute:
    APP: app-name
    VOLSYNC_CAPACITY: 10Gi
```

### Shared Access Configuration (ReadWriteMany)

For applications where multiple pods need access to the same volume:

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

### Multiple Volumes

Applications often need both VolSync-backed volumes and additional volumes:

1. The main configuration volume is automatically created by VolSync
2. Additional volumes are defined in `pvc.yaml` and referenced in the HelmRelease

```yaml
# In app/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-name-cache
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 5Gi
  storageClassName: ceph-block

# In app/helmrelease.yaml
persistence:
  config:
    existingClaim: app-name    # VolSync-backed PVC
  cache:
    existingClaim: app-name-cache
    globalMounts:
      - path: /config/cache
```

### Shared PVCs

Some applications need access to shared data stored on existing PVCs:

```yaml
# In app/helmrelease.yaml
persistence:
  config:
    existingClaim: app-name    # VolSync-backed PVC
  media:
    existingClaim: media-nfs-share-pvc
    globalMounts:
      - path: /media
```

## Best Practices

1. **Naming Convention**: The main PVC should match the application name (defined by APP)
2. **Storage Types**:
   - Use `ceph-block` with `ReadWriteOnce` for most application data
   - Use `ceph-filesystem` with `ReadWriteMany` when multiple pods need access
3. **Multiple Volumes**: Separate different types of data:
   - Config data: Use VolSync-backed PVC
   - Cache data: Use separate PVCs to avoid backing up temporary data
   - Media/shared data: Use shared PVCs like `media-nfs-share-pvc`
4. **Dependencies**: Always include both rook-ceph-cluster and volsync in the dependsOn list
5. **Templates**: Always include the volsync template in your kustomization.yaml

## Troubleshooting

If your VolSync-backed PVC isn't being created:

1. Verify the `APP` parameter in `ks.yaml` matches the application name
2. Check that the volsync template is included in your `kustomization.yaml`
3. Ensure the dependencies on rook-ceph-cluster and volsync are properly defined
4. Validate that the VOLSYNC_* variables are correctly set

For issues with backups:
1. Check the VolSync controller logs
2. Ensure the snapshot class exists and is properly configured
3. Verify the storage class supports snapshots
