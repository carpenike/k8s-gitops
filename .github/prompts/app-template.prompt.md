# App-Template Deployment Prompt

Use this prompt to deploy a new application using the app-template Helm chart.

## Application Details

- **Application Name**: [APP_NAME]
- **Namespace**: [NAMESPACE] (existing namespace or create new)
- **Cluster**: [CLUSTER] (e.g., cluster-0, nas-1)
- **Description**: [BRIEF_DESCRIPTION]

## Helm Configuration

- **Chart**: app-template
- **Version**: [CHART_VERSION] (e.g., 3.5.1)
- **Interval**: [RECONCILIATION_INTERVAL] (e.g., 30m)

## Container Configuration

- **Image Repository**: [IMAGE_REPO]
- **Image Tag**: [IMAGE_TAG]
- **Container Port**: [CONTAINER_PORT]

## Resource Requirements

- **CPU Requests**: [CPU_REQUEST] (e.g., 100m)
- **Memory Requests**: [MEMORY_REQUEST] (e.g., 128Mi)
- **Memory Limits**: [MEMORY_LIMIT] (e.g., 512Mi)

## Storage Requirements

- **Persistent Storage Required**: [YES/NO]
  - If yes, provide details:
    - Size: [STORAGE_SIZE] (e.g., 10Gi)
    - Storage Class: [STORAGE_CLASS] (e.g., ceph-block)
    - Mount Path: [MOUNT_PATH] (e.g., /config)

## Network Configuration

- **Ingress Required**: [YES/NO]
  - If yes, provide details:
    - Hostname: [HOSTNAME] (e.g., app.holthome.net)
    - Internal or External: [INTERNAL/EXTERNAL]
    - Authentication Required: [YES/NO]

## External Secrets

- **Secrets Required**: [YES/NO]
  - If yes, provide details:
    - One Password Item: [OP_ITEM]
    - Secret Keys:
      - [KEY_1]: [VALUE_OR_TEMPLATE_1]
      - [KEY_2]: [VALUE_OR_TEMPLATE_2]

## Environment Configuration

- **Environment Variables**:
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

## Dependencies

- **Depends On**:
  - [DEPENDENCY_1] (e.g., cloudnative-pg-cluster)
  - [DEPENDENCY_2] (e.g., external-secrets-stores)

## Additional Configuration

- **Annotations Required**: [YES/NO]
  - If yes, provide details:
    - [ANNOTATION_KEY_1]: [ANNOTATION_VALUE_1]
    - [ANNOTATION_KEY_2]: [ANNOTATION_VALUE_2]
- **Init Containers Required**: [YES/NO]
  - If yes, provide details:
    - Name: [INIT_CONTAINER_NAME]
    - Image: [INIT_CONTAINER_IMAGE]
    - Command: [INIT_CONTAINER_COMMAND]

## Sample Request

"Please deploy a new application called 'paperless-ngx' in the 'selfhosted' namespace on cluster-0. It uses the image ghcr.io/paperless-ngx/paperless-ngx:2.5.0 on port 8000. It needs 500m CPU requests and 1Gi memory limit. It needs persistent storage of 20Gi using the ceph-block storage class mounted at /data. It should be accessible at paperless.holthome.net with internal ingress and OAuth authentication. It needs a secret with PAPERLESS_SECRET_KEY, PAPERLESS_ADMIN_USER, and PAPERLESS_ADMIN_PASSWORD. The health check should be on /api/health/ endpoint. Run as user/group 1000."
