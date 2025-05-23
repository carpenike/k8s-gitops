# Working with Shared PVCs Guide

This document provides guidance on how to effectively use shared Persistent Volume Claims (PVCs) within the repository.

## Overview

Shared PVCs are used to provide common storage across multiple applications. This is particularly useful for media files, shared configuration, or other data that needs to be accessed by multiple pods.

## Available Shared PVCs

The repository maintains several pre-configured shared PVCs:

### Media Namespace

- **`media-nfs-share-pvc`**: NFS mount for media content
  - Typically mounted at `/media`
  - Used by applications like Plex, Sonarr, Radarr, etc.
  - Provides ReadWriteMany access

### Selfhosted Namespace

- **`selfhosted-nfs-share-pvc`**: NFS mount for selfhosted application data
  - Used by applications in the selfhosted namespace
  - Provides ReadWriteMany access

### Home Namespace

- **`home-nfs-share-pvc`**: NFS mount for home automation data
  - Used by applications in the home namespace
  - Provides ReadWriteMany access

## How to Reference Shared PVCs

### Basic Configuration

To mount a shared PVC in your application:

```yaml
# In app/helmrelease.yaml
persistence:
  media:
    existingClaim: media-nfs-share-pvc
    globalMounts:
      - path: /media
```

### Using SubPath for Specific Directories

If you need to mount a specific subdirectory:

```yaml
persistence:
  movies:
    existingClaim: media-nfs-share-pvc
    globalMounts:
      - path: /movies
        subPath: movies
```

### Multiple Mounts from Same PVC

You can mount different subdirectories from the same shared PVC:

```yaml
persistence:
  movies:
    existingClaim: media-nfs-share-pvc
    globalMounts:
      - path: /movies
        subPath: movies
  tv:
    existingClaim: media-nfs-share-pvc
    globalMounts:
      - path: /tv
        subPath: tv
```

## Common Mount Patterns

### Media Applications

For applications like Plex, Sonarr, Radarr:

```yaml
persistence:
  # Application config (VolSync-backed)
  config:
    existingClaim: app-name
  
  # Media mounts
  media:
    existingClaim: media-nfs-share-pvc
    globalMounts:
      - path: /media
```

### Document Management

For applications like Paperless:

```yaml
persistence:
  # Application data (VolSync-backed)
  data:
    existingClaim: paperless
  
  # Consume directory for incoming documents
  consume:
    existingClaim: selfhosted-nfs-share-pvc
    globalMounts:
      - path: /consume
        subPath: paperless/consume
```

## Best Practices

1. **Application-Specific Data**: Always use VolSync-backed PVCs for application-specific data
2. **Shared Data**: Use shared PVCs for common data that needs to be accessed by multiple applications
3. **Path Organization**: Use consistent mount paths across applications
   - `/media` for media content
   - `/data` for application data
   - `/consume` for file ingestion
4. **SubPath Usage**: Use subPath to organize data within a shared PVC
5. **Read-Only When Possible**: If an application only needs to read data, consider mounting as readOnly: true
6. **Security Context**: Ensure your application has the correct permissions to access the mounted data

## Advanced Configuration

### Advanced Mounts

For more complex mounting needs:

```yaml
persistence:
  config:
    existingClaim: app-name
    advancedMounts:
      app-name:  # Controller name
        app:  # Container name
          - path: /specific/path
            subPath: specific-subpath
```

### ReadOnly Mounts

For data that should not be modified:

```yaml
persistence:
  media:
    existingClaim: media-nfs-share-pvc
    globalMounts:
      - path: /media
        readOnly: true
```

## Troubleshooting

1. **Access Denied**: Check that the pod's security context (runAsUser, runAsGroup) has permission to access the mounted data
2. **Mount Not Found**: Verify the PVC exists in the correct namespace
3. **Cannot Write to Mount**: Confirm the mount is not set to readOnly and the security context has write permissions
