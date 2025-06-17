# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Architecture

This is a **multi-cluster Kubernetes GitOps repository** managed with **FluxCD v2**. The architecture follows a hierarchical pattern: cluster → namespace → application, with encrypted secrets using SOPS and Age encryption.

### Key Directory Structure

- `kubernetes/cluster-0/` - Primary production cluster
- `kubernetes/nas-1/` - Backup NAS cluster
- `.taskfiles/` - Task automation definitions
- `docs/` - Comprehensive documentation and guides

### Application Deployment Pattern

Each application follows this standardized structure:
```
apps/<namespace>/<app-name>/
├── app/                    # Application resources
│   ├── helmrelease.yaml   # Main Helm chart definition
│   ├── kustomization.yaml # Resource aggregation
│   ├── externalsecret.yaml # Secrets from 1Password
│   └── pvc.yaml           # Additional storage
└── ks.yaml                # Flux Kustomization
```

## Development Commands

### Task Automation (using `task` command)

**Flux Operations:**
```bash
task flux:gr-sync    # Sync all Flux GitRepositories
task flux:ks-sync    # Sync all Flux Kustomizations  
task flux:hr-sync    # Sync all Flux HelmReleases
task flux:hr-suspend # Suspend all HelmReleases
task flux:hr-resume  # Resume all HelmReleases
```

**Kubernetes Operations:**
```bash
task k8s:validate           # Validate all manifests with kubeconform
task k8s:validate-cluster   # Validate specific cluster [CLUSTER=cluster-0]
task k8s:validate-app       # Validate app [CLUSTER=cluster-0] [NS=required] [APP=required]
task k8s:validate-strict    # Validate with strict mode and verbose output
task k8s:browse-pvc         # Mount PVC to temp container [CLUSTER=cluster-0] [NS=default] [CLAIM=required]
task k8s:delete-failed-pods # Delete all failed pods
```

**Other Task Categories:**
```bash
task externalsecrets:*   # External Secrets operations
task rook:*             # Rook-Ceph storage operations  
task volsync:*          # VolSync backup operations
```

### Validation and Linting

- **Kubeconform validation:** Configured with comprehensive CRD schemas (`.kubeconform.yaml`)
- **MegaLinter CI:** Runs actionlint, ansible-lint, kubeconform, markdownlint, yamllint, prettier
- **Manual validation:** `task k8s:validate` validates all Kubernetes manifests

## Security and Secrets

- **SOPS encryption:** All secrets encrypted at rest with Age keys
- **External Secrets Operator:** Runtime secret injection from 1Password
- **Never commit unencrypted secrets or sensitive data**

## GitOps Workflow

1. **FluxCD** automatically syncs changes from this repository
2. **Hierarchical reconciliation** with dependency management
3. **Pull request validation** with kubeconform and linting
4. **Renovate automation** for dependency updates

## Key Technologies

- **FluxCD v2** - GitOps engine with OCI repositories
- **Talos Linux** - Kubernetes OS
- **Cilium CNI** - Networking with BGP and Gateway API
- **Rook-Ceph** - Distributed storage
- **VolSync** - PV backup/recovery
- **External Secrets Operator** - Secret management
- **cert-manager** - TLS automation

## Cluster Variables

Default cluster is `cluster-0`. To work with different clusters, set `CLUSTER` variable:
```bash
CLUSTER=nas-1 task k8s:validate-cluster
```