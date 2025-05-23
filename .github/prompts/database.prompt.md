# Database Deployment Prompt

Use this prompt to deploy a database service to your Kubernetes cluster.

## Database Details

- **Database Type**: [DB_TYPE] (e.g., PostgreSQL, MySQL, Redis, MongoDB)
- **Database Name**: [DB_NAME]
- **Namespace**: [NAMESPACE] (e.g., db, apps)
- **Cluster**: [CLUSTER] (e.g., cluster-0, nas-1)

## Helm Configuration

- **Chart**: [CHART_NAME] (e.g., app-template, bitnami/postgresql)
- **Version**: [CHART_VERSION]
- **Interval**: [RECONCILIATION_INTERVAL] (e.g., 30m)

## Container Configuration

- **Image Repository**: [IMAGE_REPO]
- **Image Tag**: [IMAGE_TAG]
- **Container Port**: [CONTAINER_PORT]

## Database Configuration

- **Database Name**: [DB_NAME]
- **Database User**: [DB_USER]
- **Database Password**: From OnePassword secret
- **Database Parameters**:
  - [PARAM_1]: [VALUE_1]
  - [PARAM_2]: [VALUE_2]

## Resource Requirements

- **CPU Requests**: [CPU_REQUEST] (e.g., 100m)
- **Memory Requests**: [MEMORY_REQUEST] (e.g., 128Mi)
- **Memory Limits**: [MEMORY_LIMIT] (e.g., 512Mi)

## Storage Requirements

- **Persistent Storage Required**: [YES/NO]
  - If yes, provide details:
    - Size: [STORAGE_SIZE] (e.g., 10Gi)
    - Storage Class: [STORAGE_CLASS] (e.g., ceph-block)
    - Mount Path: [MOUNT_PATH] (e.g., /data)

## Network Configuration

- **Service Type**: [SERVICE_TYPE] (e.g., ClusterIP)
- **Ingress Required**: [YES/NO] (Usually No for databases)
  - If yes, provide details:
    - Hostname: [HOSTNAME]
    - Internal or External: [INTERNAL/EXTERNAL]
    - Authentication Required: [YES/NO]

## Backup Configuration

- **Backup Required**: [YES/NO]
  - If yes, provide details:
    - Schedule: [BACKUP_SCHEDULE] (e.g., "0 2 * * *")
    - Retention: [BACKUP_RETENTION] (e.g., 7 days)

## Security Configuration

- **Network Policy Required**: [YES/NO]
  - If yes, specify allowed namespaces or apps:
    - [NAMESPACE_1]
    - [NAMESPACE_2]
- **Run As User**: [RUN_AS_USER]
- **Run As Group**: [RUN_AS_GROUP]
- **FS Group**: [FS_GROUP]

## Sample Request

"Please deploy a PostgreSQL database using the bitnami/postgresql chart version 13.2.0. Name it 'app-db' in the 'db' namespace on cluster-0. It should use 500m CPU request and 2Gi memory limit with 20Gi persistent storage using the ceph-block storage class. Create a database called 'myapp' with user 'myapp_user' and store the password in OnePassword. Allow connections from the 'selfhosted' namespace and set up daily backups at 2 AM with 7-day retention."
