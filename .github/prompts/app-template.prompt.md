# App-Template Deployment Prompt

Use this prompt to deploy a new application using the app-template Helm chart following the established patterns in this GitOps repository.

## Directory Structure

The application will be deployed with the following structure:
```
kubernetes/<cluster>/apps/<namespace>/<app-name>/
├── app/
│   ├── externalsecret.yaml  # If using secrets
│   ├── helmrelease.yaml     # The main Helm release definition
│   ├── kustomization.yaml   # References all resources and templates
│   └── pvc.yaml             # If using additional persistent storage
└── ks.yaml                  # Flux Kustomization resource that references the app directory
```

The kustomization.yaml file should include references to the app resources and any templates (like volsync):
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./pvc.yaml               # Local app-specific PVCs 
  - ./helmrelease.yaml       # The main Helm release
  - ./externalsecret.yaml    # If using secrets
  - ../../../../templates/volsync    # If using volsync for backups
  - ../../../../templates/gatus/guarded    # If using monitoring
```

## Application Details

- **Application Name**: [APP_NAME]
- **Namespace**: [NAMESPACE] (existing namespace or create new)
- **Cluster**: [CLUSTER] (e.g., cluster-0, nas-1)
- **Description**: [BRIEF_DESCRIPTION]

## Helm Configuration

- **Chart**: app-template
- **Version**: [CHART_VERSION] (e.g., 3.5.1)
- **Interval**: [RECONCILIATION_INTERVAL] (e.g., 30m, default)
- **Max History**: [MAX_HISTORY] (e.g., 3, default)

## Container Configuration

- **Image Repository**: [IMAGE_REPO]
- **Image Tag**: [IMAGE_TAG]
- **Container Port**: [CONTAINER_PORT]
- **Controller Name**: [CONTROLLER_NAME] (usually same as app name)

## Resource Requirements

- **CPU Requests**: [CPU_REQUEST] (e.g., 100m)
- **Memory Requests**: [MEMORY_REQUEST] (e.g., 128Mi)
- **Memory Limits**: [MEMORY_LIMIT] (e.g., 512Mi)

## Storage Requirements

- **Persistent Storage Required**: [YES/NO]
  - If yes, provide details:
    - **VolSync Backed Storage** (Recommended):
      - Primary Storage (config volume):
        - Size: [STORAGE_SIZE] (e.g., 10Gi)
        - Storage Class: [STORAGE_CLASS] (default: ceph-block)
        - Access Mode: [ACCESS_MODE] (default: ReadWriteOnce)
        - Snapshot Class: [SNAPSHOT_CLASS] (default: csi-ceph-block)
      - Additional Volumes: [YES/NO]
        - If yes, provide for each volume:
          - Name: [VOLUME_NAME] (e.g., cache)
          - Size: [VOLUME_SIZE] (e.g., 5Gi)
          - Mount Path: [MOUNT_PATH] (e.g., /config/cache)
          - Storage Class: [STORAGE_CLASS] (default: ceph-block)
    - **Existing PVC**:
      - PVC Name: [EXISTING_PVC_NAME] (e.g., media-nfs-share-pvc)
      - Mount Path: [MOUNT_PATH] (e.g., /media)
      - Sub-Path: [SUB_PATH] (optional, e.g., /movies)

## Network Configuration

- **Ingress Required**: [YES/NO]
  - If yes, provide details:
    - Hostname: [HOSTNAME] (e.g., app.holthome.net)
    - Internal or External: [INTERNAL/EXTERNAL]
      - For internal: Uses `internal-nginx` class and `internal.holthome.net` DNS target
      - For external: Uses `external-nginx` class and `external.holthome.net` DNS target
    - Authentication Required: [YES/NO]

## External Secrets

- **Secrets Required**: [YES/NO]
  - If yes, provide details:
    - OnePassword Item: [OP_ITEM]
    - Secret Keys:
      - [KEY_1]: "{{ .[TEMPLATE_KEY_1] }}"
      - [KEY_2]: "{{ .[TEMPLATE_KEY_2] }}"
    - Secret Name: [SECRET_NAME] (usually [APP_NAME]-secret)

## Environment Configuration

- **Environment Variables**:
  - TZ: America/New_York
  - [ENV_VAR_1]: [VALUE_1]
  - [ENV_VAR_2]: [VALUE_2]

## Health Checks

- **Health Check Path**: [HEALTH_CHECK_PATH] (e.g., /health or /ping)
- **Initial Delay**: [INITIAL_DELAY] (e.g., 0)
- **Period Seconds**: [PERIOD_SECONDS] (e.g., 10)
- **Timeout Seconds**: [TIMEOUT_SECONDS] (e.g., 1)
- **Failure Threshold**: [FAILURE_THRESHOLD] (e.g., 3)

## Security Context

- **Run As User**: [RUN_AS_USER] (e.g., 568)
- **Run As Group**: [RUN_AS_GROUP] (e.g., 568)
- **FS Group**: [FS_GROUP] (e.g., 568)
- **Supplemental Groups**: [SUPPLEMENTAL_GROUPS] (e.g., 65542 for gladius:external-services)
- **Read-Only Root Filesystem**: [YES/NO] (true recommended)
- **Allow Privilege Escalation**: [YES/NO] (false recommended)

## Dependencies

- **Depends On**:
  - [DEPENDENCY_1] (e.g., external-secrets-stores)
  - [DEPENDENCY_2] (e.g., cloudnative-pg-cluster)
  - [DEPENDENCY_3] (e.g., rook-ceph-cluster)
  - [DEPENDENCY_4] (e.g., volsync)
  
Common dependency patterns:
- For applications with secrets: `external-secrets-stores`
- For applications with persistent storage: `rook-ceph-cluster` and `volsync`
- For applications with database: `cloudnative-pg-cluster`

## Additional Configuration

- **Annotations Required**: [YES/NO]
  - If yes, provide details:
    - reloader.stakater.com/auto: "true" (for automatic pod restarts on config changes)
    - [ANNOTATION_KEY_2]: [ANNOTATION_VALUE_2]

- **Init Containers Required**: [YES/NO]
  - If yes, provide details:
    - Name: [INIT_CONTAINER_NAME]
    - Image: [INIT_CONTAINER_IMAGE]
    - Command: [INIT_CONTAINER_COMMAND]

- **Monitoring**: [YES/NO]
  - If yes, include Gatus monitoring template

## Sample Request

"Please deploy Paperless-NGX in the selfhosted namespace on cluster-0. It should use the image ghcr.io/paperless-ngx/paperless-ngx:2.5.0 on port 8000. It needs 500m CPU requests and 1Gi memory limit with two storage volumes: 1) a volsync-backed 20Gi PVC using the ceph-block storage class mounted at /data for the application config, and 2) the existing selfhosted-nfs-share-pvc mounted at /consume. It should be accessible at paperless.holthome.net through the internal ingress. It needs secrets stored in a OnePassword item called 'paperless' with PAPERLESS_SECRET_KEY, PAPERLESS_ADMIN_USER, and PAPERLESS_ADMIN_PASSWORD. The health check should be on /api/health/ endpoint. Run as user/group 1000 with a read-only root filesystem and no privilege escalation. Add an annotation for automatic reloading. Include Gatus monitoring. This application depends on rook-ceph-cluster for storage, external-secrets-stores for secrets management, and volsync for backups."

## YAML Schema Validation

All YAML files created should include appropriate schema references:

- **HelmRelease**:
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
  ```

- **Kustomization**:
  ```yaml
  # yaml-language-server: $schema=https://json.schemastore.org/kustomization
  ```

- **Flux Kustomization**:
  ```yaml
  # yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
  ```

- **ExternalSecret**:
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/external-secrets.io/externalsecret_v1beta1.json
  ```
