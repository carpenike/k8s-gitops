# GitHub Copilot Instructions for Flux Configuration

> **Schema Reference Best Practice (last updated: 2025-05-27):**
> - Use the latest authoritative schema URLs for each manifest type (see YAML Schema Validation Guidelines).
> - Place schema references as a comment before the document separator (---) at the top of each YAML file.
> - Review and update schema URLs regularly as upstream projects change.
> 
> **API Version Update (May 2025):**
> - Source controller resources (GitRepository, HelmRepository, OCIRepository) should use `source.toolkit.fluxcd.io/v1`
> - HelmRelease resources should continue using `helm.toolkit.fluxcd.io/v2beta2` (v2 GA not yet released)
> - Prometheus monitoring resources (PrometheusRule, ScrapeConfig) should use `monitoring.coreos.com/v1`

## When to Apply These Instructions

These instructions should be applied when working with FluxCD configuration files, including:
- Files in `/kubernetes/*/flux/` directories
- Kustomization resources with `kustomize.toolkit.fluxcd.io` API group
- GitRepository, HelmRepository, and OCIRepository resources
- Any file related to FluxCD reconciliation

## Flux Configuration Best Practices

1. Use the correct API versions (Updated May 2025):
   - `kustomize.toolkit.fluxcd.io/v1` for Flux Kustomization CRD resources
   - `helm.toolkit.fluxcd.io/v2beta2` for HelmRelease resources (v2beta2 is current stable, v2 GA not yet released)
   - `source.toolkit.fluxcd.io/v1` for source controller resources (GitRepository, HelmRepository, OCIRepository)

   > **IMPORTANT: Flux Kustomization vs Native Kustomize**
   > - Files with `kind: Kustomization` and `apiVersion: kustomize.toolkit.fluxcd.io/v1` are Flux Kustomization CRDs
   > - Files named `kustomization.yaml` with no `kind` field or with `kind: Kustomization` and `apiVersion: kustomize.config.k8s.io/v1beta1` are native kustomize files
   > - Do not confuse these two types; they serve different purposes and require different API versions
   > - Flux Kustomization CRDs tell Flux what to reconcile
   > - Native kustomization.yaml files tell kustomize how to build manifests

2. Always specify reconciliation intervals:
   - 10m for cluster-level Kustomizations
   - 15m for application HelmReleases
   - 1h for external source repositories

3. Always implement proper remediation for HelmRelease resources:
   ```yaml
   install:
     createNamespace: true
     remediation:
       retries: 5
   upgrade:
     remediation:
       retries: 5
   ```

4. Use the following structure for sourcing Helm charts:
   ```yaml
   chart:
     spec:
       chart: chart-name
       version: x.y.z  # Always pin versions
       sourceRef:
         kind: HelmRepository  # Or OCIRepository for OCI-based charts
         name: repository-name
         namespace: flux-system
   ```

5. For Kustomizations, always configure:
   - `prune: true` to enable garbage collection
   - `path: ./path/to/directory` pointing to the correct directory
   - `sourceRef` pointing to the GitRepository

6. When using SOPS for decryption, include:
   ```yaml
   decryption:
     provider: sops
     secretRef:
       name: sops-age
   ```

7. For variable substitution, use:
   ```yaml
   postBuild:
     substituteFrom:
       - kind: ConfigMap
         name: cluster-settings
   ```

8. Use patch transformers when applying common configurations to multiple resources.

9. Organize Flux resources:
   - Place sources in `/kubernetes/<cluster>/flux/repositories/`
   - Place kustomizations in `/kubernetes/<cluster>/flux/`
   - Group repositories by type (helm, git, oci)

## YAML Schema Validation Guidelines

- **Flux Kustomization (ks.yaml):**
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd/kustomize-controller/main/config/crd/bases/kustomize.toolkit.fluxcd.io_kustomizations.yaml
  ```
- **HelmRelease:**
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd/helm-controller/main/config/crd/bases/helm.toolkit.fluxcd.io_helmreleases.yaml
  ```
