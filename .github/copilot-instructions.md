# GitHub Copilot Instructions for k8s-gitops Repository

## Modular Instruction Files

This repository maintains modular instruction files for different aspects of the GitOps workflow in `.github/instructions/`. These files serve as detailed reference documentation for humans, while this main file contains all the critical information that GitHub Copilot needs.

**Reference instruction files:**

- [`flux.instructions.md`](instructions/flux.instructions.md): Detailed FluxCD configuration guidelines
- [`helmrelease.instructions.md`](instructions/helmrelease.instructions.md): Complete HelmRelease patterns and examples
- [`talos.instructions.md`](instructions/talos.instructions.md): Talos OS configuration best practices
- [`applications.instructions.md`](instructions/applications.instructions.md): Application deployment patterns
- [`secrets.instructions.md`](instructions/secrets.instructions.md): Comprehensive secret management
- [`external-secrets.instructions.md`](instructions/external-secrets.instructions.md): External Secrets with 1Password
- [`externaldns.instructions.md`](instructions/externaldns.instructions.md): ExternalDNS with Cloudflare and Bind
- [`yaml-schemas.instructions.md`](instructions/yaml-schemas.instructions.md): YAML Schema Validation Guidelines
- [`volsync.instructions.md`](instructions/volsync.instructions.md): VolSync integration for persistent storage

> **Note**: The guidance from these files is incorporated into the sections below. When working with specific components, refer to the relevant sections in this file.

## Instructions Reference Guide

The following sections contain file-specific guidance. When helping with code in this repository, apply these instructions based on the context:

- **For FluxCD Files**: Apply the FluxCD best practices when working with files under `/kubernetes/*/flux/`.
- **For HelmRelease Files**: Apply the HelmRelease patterns when working with any `helm-release.yaml` files.
- **For Talos Configuration**: Apply the Talos management guidelines when working with files under `/kubernetes/*/talos/`.
- **For Application Manifests**: Apply the application guidelines when working with files under `/kubernetes/*/apps/`.
- **For Secret Management**: Apply the secret management practices when working with any secret-related files.
- **For External Secrets**: Apply the External Secrets with 1Password practices when working with `externalsecret.yaml` files.
- **For DNS Management**: Apply the ExternalDNS practices when working with Cloudflare (external) and Bind (internal) DNS configuration.
- **For Persistent Storage**: Apply the VolSync integration practices when working with applications that need persistent storage.

## Component-Specific Guidelines

### FluxCD Configuration
When working with files in `/kubernetes/*/flux/`:
- Use `kustomize.toolkit.fluxcd.io/v1` for Kustomization resources
- Use `helm.toolkit.fluxcd.io/v2beta2` for HelmRelease resources
- Use `source.toolkit.fluxcd.io/v1` for source controller resources
- Set reconciliation intervals: 10m for cluster-level Kustomizations, 15m for HelmReleases
- Always configure `prune: true` on Kustomizations for garbage collection
- Use SOPS for secret decryption with proper secretRef

### HelmRelease Resources
When working with `helm-release.yaml` files:
- Use YAML anchors for better readability and DRY principle
- Always pin chart versions explicitly
- Configure remediation with retries for install and upgrade
- Define proper health probes (liveness, readiness, startup)
- Always specify resource limits and requests
- Use appropriate ingress annotations and TLS configuration

## HelmRelease Pattern

Follow this pattern for all HelmRelease resources:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: &app app-name
  namespace: namespace
spec:
  interval: 15m
  chart:
    spec:
      chart: app-template
      version: 1.x.x
      sourceRef:
        kind: HelmRepository
        name: repository-name
        namespace: flux-system
  install:
    createNamespace: true
    remediation:
      retries: 5
  upgrade:
    remediation:
      retries: 5
  values:
    image:
      repository: image/repository
      tag: vX.Y.Z
    
    env:
      TZ: "America/New_York"
      # Application-specific env vars
    
    service:
      main:
        ports:
          http:
            port: 80  # Or application-specific port
    
    probes:
      liveness: &probes
        enabled: true
        custom: true
        spec:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 0
          periodSeconds: 10
          timeoutSeconds: 1
          failureThreshold: 3
      readiness: *probes
      startup:
        enabled: false
    
    ingress:
      main:
        enabled: true
        ingressClassName: "nginx"
        hosts:
          - host: &host "{{ .Release.Name }}.${SECRET_DOMAIN}"
            paths:
              - path: /
                pathType: Prefix
        tls:
          - hosts:
              - *host
    
    persistence:
      config:
        enabled: true
        type: pvc
    
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        memory: 512Mi
```

### Talos Configuration
When working with files in `/kubernetes/*/talos/`:
- Use `talconfig.yaml` with proper schema reference
- Pin Talos and Kubernetes versions using Renovate annotations
- Configure node-specific settings under the `nodes` section
- Use YAML anchors for repeated values like VLAN configurations
- Configure network interfaces with proper bonds and VLANs

### Application Manifests
When working with files in `/kubernetes/*/apps/`:
- Place each application in its own directory under `/kubernetes/<cluster>/apps/<namespace>/<app-name>/`
- Create a kustomization.yaml file for each application
- Include namespace definitions with appropriate labels
- Use NetworkPolicies to restrict traffic between namespaces
- Configure proper monitoring with ServiceMonitor resources

## New Application Structure

When adding a new application, follow this directory structure:

```
kubernetes/<cluster>/apps/<namespace>/<app-name>/
├── helm-release.yaml       # If using Helm
├── kustomization.yaml      # Always required
├── namespace.yaml          # If creating a new namespace
├── pvc.yaml                # If requiring persistent storage
└── externalsecret.yaml     # If using external secrets
```

### Secret Management
When working with secrets:
- Never commit plaintext secrets to the repository
- Use SOPS with AGE for encrypting secrets
- Name encrypted secrets with `.sops.yaml` suffix
- Use ExternalSecrets for retrieving secrets from external providers
- Reference secrets securely in environment variables

### External Secrets with 1Password
When working with External Secrets and 1Password:
- Use `external-secrets.io/v1beta1` API version
- Reference the `onepassword-connect` ClusterSecretStore in all ExternalSecret resources
- Use target creation policy `Owner` to ensure proper secret lifecycle management
- Use template data with references to 1Password values (e.g., `"{{ .APP_KEY }}"`)
- Use YAML anchors for repeated values like database credentials
- Structure 1Password paths consistently (e.g., `op://vault/item/field`)
- Store the 1Password Connect token securely as a bootstrap secret

### ExternalDNS Configuration
When working with ExternalDNS:
- Use separate deployments for external (Cloudflare) and internal (Bind) DNS
- Use `external-dns.alpha.kubernetes.io/target: external.holthome.net` for external DNS
- Use `external-dns.alpha.kubernetes.io/target: internal.holthome.net` for internal DNS
- For direct hostname assignment, use `external-dns.alpha.kubernetes.io/hostname`
- Use YAML anchors for consistent hostname patterns
- For Cloudflare, configure `--cloudflare-proxied` when appropriate
- For Bind, configure proper TSIG authentication for secure updates

## YAML Schema Validation

When creating or modifying YAML configuration files in this repository, always include appropriate schema validation references:

1. **For bjw-s app-template HelmRelease resources**:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
   ```

2. **For standard FluxCD HelmRelease resources**:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/helmrelease-helm-v2beta2.json
   ```

3. **For standard Kustomization files**:
   ```yaml
   # yaml-language-server: $schema=https://json.schemastore.org/kustomization
   ```

4. **For FluxCD Kustomization resources (ks.yaml)**:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
   ```

5. **For Namespace resources**:
   ```yaml
   # yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/v1/namespace.json
   ```

6. **For ExternalSecret resources**:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/external-secrets.io/externalsecret_v1beta1.json
   ```

Always place schema references after the `---` document separator at the top of the file and before any other content.

### Validating Schema Compliance

When generating or modifying YAML files, always validate that the content adheres to the schema:

1. **Ensure mandatory fields are provided**:
   - Always include required fields with appropriate values
   - For HelmRelease resources, always pin chart versions (e.g., `version: "1.2.3"`)
   - For Kustomization resources, always specify required resources

2. **Use correct types for values**:
   - Numbers should be unquoted: `replicas: 3` (not `replicas: "3"`)
   - Booleans should be literal `true` or `false` (not strings)
   - Resource quantities should use Kubernetes format: `memory: 256Mi`

3. **Fix validation errors systematically**:
   - Address structural errors first (missing required fields)
   - Then fix type errors (incorrect data types)
   - Finally, resolve semantic errors (invalid values)

4. **Follow schema-specific patterns**:
   - For HelmRelease resources, use the proper chart reference structure
   - For Kustomization resources, use valid path and sourceRef configurations
   - For ExternalSecrets, provide proper secretStoreRef and target fields

5. **Verify with additional tools**:
   - Use `flux validate` for FluxCD resources
   - Use `kubectl apply --dry-run=server` for Kubernetes resources

## Repository Overview

This repository manages a GitOps-based Kubernetes deployment using FluxCD to deploy and maintain applications on Talos-based Kubernetes clusters. The repository follows a structured approach with a clear separation between cluster components, applications, and configuration.

## Repository Structure

- `/kubernetes/` - Contains all Kubernetes configuration for clusters
  - `/<cluster-name>/` - Configuration specific to a named cluster (e.g., cluster-0, nas-1)
    - `/apps/` - Application deployments organized by namespace/function
    - `/bootstrap/` - Cluster bootstrap configuration including encrypted secrets (SOPS)
    - `/components/` - Reusable components across the cluster (e.g., gatus, volsync)
    - `/flux/` - FluxCD configuration including repositories, sources, and kustomizations
    - `/talos/` - Talos OS configuration for cluster nodes
- `/_archive/` - Reference files and previously used configurations
- `/templates/` - Template files for common patterns (e.g., gatus, volsync)

## GitOps Principles

When suggesting changes or writing code:

1. All changes must follow the GitOps pattern - the Git repository is the source of truth.
2. All Kubernetes resources should be defined declaratively as YAML files.
3. Secrets must be encrypted using SOPS/AGE and never committed in plaintext.
4. Follow progressive delivery patterns with proper health checks and rollback strategies.

## FluxCD Best Practices

1. Use HelmRelease resources for Helm chart deployments with explicit versioning.
2. Group related resources with Kustomizations.
3. Use source controllers (GitRepository, HelmRepository, OCIRepository) to track external resources.
4. Implement proper reconciliation intervals (default 15m for HelmReleases).
5. Implement health checks in all deployments to enable automatic rollback.

## Talos Management

1. Use `talconfig.yaml` to define Talos machine configurations.
2. Node-specific configurations should be defined under the `nodes` section.
3. All Talos configurations should be version controlled.
4. Use the talosctl utility for cluster management operations.

## HelmRelease Pattern

Follow this pattern for all HelmRelease resources:

1. Use `app-template` chart for most applications.
2. Define proper health probes (liveness, readiness, startup).
3. Use resource limits and requests.
4. Use proper annotations for ingress resources.
5. Use template variables for common values.
6. Use referenced anchors (*name) where appropriate to reduce duplication.

Example:
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: &app app-name
  namespace: namespace
spec:
  interval: 15m
  chart:
    spec:
      chart: app-template
      version: 1.x.x
      sourceRef:
        kind: HelmRepository
        name: repository-name
        namespace: flux-system
  install:
    createNamespace: true
    remediation:
      retries: 5
  upgrade:
    remediation:
      retries: 5
  values:
    # Application values go here
```

## Naming Conventions

1. Use kebab-case for resource names (e.g., `media-browser`, `cluster-apps`).
2. Use lowercase for namespace names.
3. Use descriptive names that indicate function rather than implementation.

## Security Practices

1. Follow RBAC best practices with least privilege principles.
2. Use network policies to restrict traffic between namespaces.
3. Encrypt all secrets using SOPS with AGE keys.
4. Do not commit plain secrets to the repository.

## Directory Structure Patterns

When creating new applications:

1. Place application manifests in the appropriate namespace directory.
2. Create a kustomization.yaml file in the application directory.
3. Reference the application in the namespace kustomization.yaml.

## Workflow Assistance

1. Help automate YAML generation following the repository patterns.
2. Suggest improvements to existing manifests for better reliability and security.
3. Ensure all manifests follow Kubernetes best practices.
4. Highlight potential issues with resource specifications or security concerns.
5. Help with Talos OS configuration and network setup following the existing patterns.
