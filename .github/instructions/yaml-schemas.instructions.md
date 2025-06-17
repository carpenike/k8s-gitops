# GitHub Copilot Instructions for YAML Schema Validation

> **Schema Reference Best Practice (last updated: 2025-05-27):**
> - Use the latest authoritative schema URLs for each manifest type (see below).
> - Place schema references as a comment before the document separator (---) at the top of each YAML file.
> - Review and update schema URLs regularly as upstream projects change.

## When to Apply These Instructions

These instructions should be applied when working with any YAML configuration files in the repository, including:
- HelmRelease resources
- Kustomization files
- Namespace definitions
- ExternalSecret resources
- Any other Kubernetes manifests

## YAML Schema Validation Best Practices

1. Always add schema validation references to YAML files:
   ```yaml
   # yaml-language-server: $schema=<schema-url>
   ```

2. Use the appropriate schema for each file type:

   - **For bjw-s app-template HelmRelease resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
     ```

   - **For standard FluxCD HelmRelease resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd/helm-controller/main/config/crd/bases/helm.toolkit.fluxcd.io_helmreleases.yaml
     ```

   - **For standard Kustomization files** (native kustomize configuration):
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1beta1.json
     ```
     > **Note:** These files should always use `apiVersion: kustomize.config.k8s.io/v1beta1`

   - **For Kustomize Component files**:
     ```yaml
     # yaml-language-server: $schema=https://json.schemastore.org/kustomization
     ```
     > **Note:** These files should always use `apiVersion: kustomize.config.k8s.io/v1alpha1` and `kind: Component`

   - **For FluxCD Kustomization resources** (Flux CRD, usually in ks.yaml files):
     ```yaml
     # yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
     ```
     > **Note:** These files should always use `apiVersion: kustomize.toolkit.fluxcd.io/v1`

   - **For Namespace resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.Namespace
     ```

   - **For ExternalSecret resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/external-secrets/external-secrets/main/config/crds/bases/external-secrets.io_externalsecrets.yaml
     ```

   - **For Secret resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.Secret
     ```

   - **For PersistentVolumeClaim resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.PersistentVolumeClaim
     ```

   - **For ServiceMonitor resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
     ```

   - **For PrometheusRule resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
     ```

   - **For ScrapeConfig resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_scrapeconfigs.yaml
     ```

   - **For ConfigMap resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/core/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.core.v1.ConfigMap
     ```

   - **For NetworkPolicy resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/networking/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.networking.v1.NetworkPolicy
     ```

   - **For Role resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/rbac/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.rbac.v1.Role
     ```

   - **For RoleBinding resources**:
     ```yaml
     # yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes/api/master/rbac/v1/openapi-spec/swagger.json#/definitions/io.k8s.api.rbac.v1.RoleBinding
     ```

3. Schema placement:
   - Add schema references after the `---` document separator
   - If no document separator exists, add one followed by the schema reference
   - Place schema references before any other content in the file

## Verifying Schema Validation

1. VS Code will automatically validate YAML against the referenced schema
2. Make sure all required fields are present
3. Follow the schema's constraints for field values and structure
4. Pay attention to validation warnings and errors in your editor

### Validating Files Against Schemas

After adding schema references, it's important to verify that the file content adheres to the schema:

1. **Visual validation in VS Code**:
   - Files with errors will show red squiggly lines under problematic sections
   - The Problems panel (View > Problems) will list all schema validation issues
   - Hover over underlined sections to see detailed error messages

2. **Using the Problems panel effectively**:
   - Filter by "Schema" to see only schema validation issues
   - Double-click on a problem to navigate directly to the relevant line
   - Problems are sorted by severity (Error, Warning, Information)

3. **Troubleshooting common schema validation errors**:
   - Missing required fields: Add the required fields with appropriate values
   - Type errors: Ensure values match the expected type (string, number, boolean)
   - Enum errors: Verify that values match one of the allowed options
   - Format errors: Check that fields like ports, resource quantities, and selectors use correct formats

4. **Resolving specific schema errors**:
   - For `kind` or `apiVersion` errors: Verify you're using the correct API version
   - For nested object errors: Ensure all required sub-fields are present
   - For array errors: Check that array items have the correct structure

## Schema Compliance Best Practices

When working with schema-validated YAML files:

1. **Always check for schema validation errors**:
   - Review any red underlines or warning indicators in VS Code
   - Fix all schema validation errors before committing changes
   - Use the Problems panel (View > Problems) to see detailed error information
   - Run `yamllint` to catch additional YAML syntax issues not covered by the schema

2. **Ensure mandatory fields are provided**:
   - The schema defines which fields are required
   - Fill in all required fields with appropriate values
   - Use schema-provided documentation (hover over fields) to understand requirements
   - Example for HelmRelease: Always include `spec.chart.spec.version` with a pinned version

3. **Respect field type constraints**:
   - Use correct data types as required by the schema (strings, numbers, booleans, etc.)
   - Format special fields correctly (e.g., resources, selectors, ports)
   - Resource quantities should use Kubernetes format (e.g., `100m`, `256Mi`)
   - Boolean values must be `true` or `false`, not strings like "true" or "false"

4. **Validate before applying to cluster**:
   - Always fix schema errors before applying manifests to your cluster
   - Schema validation prevents many runtime errors and configuration issues
   - Use `flux validate` for additional validation of Flux resources
   - For critical resources, use `kubectl apply --dry-run=server` for server-side validation

5. **Learn from schema documentation**:
   - VS Code provides hover documentation from the schema
   - Use this documentation to learn about available options and constraints
   - Pay attention to enum values which limit available options
   - Use pattern validation to ensure strings match required formats

6. **Fix schema validation errors systematically**:
   - Address required properties first, as they may resolve dependent errors
   - For type errors, convert values to the right type (enclose strings in quotes, remove quotes from numbers)
   - For enum errors, refer to the schema documentation for allowed values
   - For complex objects, ensure nested structure matches the schema definition

7. **Handle structured data correctly**:
   - Array items must follow the schema's defined structure
   - Maps and dictionaries should have the correct key/value formats
   - Follow YAML indentation rules for nested structures
   - Use YAML anchors and aliases consistently with schema-defined structures

### Common Schema Errors and Solutions

| Error Type | Example | Solution |
|------------|---------|----------|
| Missing required field | `spec.chart.spec.version is required` | Add `version: "1.2.3"` to the spec.chart.spec section |
| Type error | `should be number` | Change `port: "8080"` to `port: 8080` (remove quotes) |
| Enum error | `should be equal to one of the allowed values` | Change `ingressClassName: "custom"` to an allowed value like `ingressClassName: "nginx"` |
| Pattern error | `should match pattern...` | Ensure formats match requirements, e.g., semantic versions like `1.2.3` |
| Format error | `should match format "hostname"` | Ensure hostnames follow RFC 1123 format |
| Array item error | `should have required property` | Ensure each array item has all required fields |
| API version error | `kustomize build failed: accumulating resources...` | For Component files, ensure using `apiVersion: kustomize.config.k8s.io/v1alpha1` with `kind: Component` |

## Schema Validation Challenges and Solutions

When working with YAML schemas in Kubernetes manifests, you may encounter some specific challenges:

1. **App-template Schema vs. Standard HelmRelease Schema**:
   - The app-template specific schema is more restrictive than the standard HelmRelease schema
   - When using complex app-template patterns with YAML anchors, you might encounter validation errors
   - If you encounter schema validation errors with the app-template schema, consider:
     - Updating ingress definitions to use `service.identifier` instead of `service.name`
     - Adding required `pathType` fields to ingress paths
     - Avoiding YAML anchors in certain contexts or replacing them with direct values
     - In some cases, switching to the standard HelmRelease schema if app-template patterns cause validation issues

2. **HelmRelease with OCIRepository Validation**:
   - When converting from HelmRepository to OCIRepository for app-template HelmReleases:
     - Remove the `chart.spec` section and replace with `chartRef`
     - Use `kind: OCIRepository` in the chartRef
     - Remove the chart version as it's specified in the OCIRepository resource
     ```yaml
     # From:
     chart:
       spec:
         chart: app-template
         version: 3.5.1
         sourceRef:
           kind: HelmRepository
           name: bjw-s
           namespace: flux-system

     # To:
     chartRef:
       kind: OCIRepository
       name: app-template
       namespace: flux-system
     ```

3. **Remediation Settings for Reliability**:
   - Always include remediation settings for better reliability:
     ```yaml
     install:
       remediation:
         retries: 3
     upgrade:
       cleanupOnFail: true
       remediation:
         strategy: rollback
         retries: 3
     ```

## Example Usage

### Basic Schema Reference

For a bjw-s app-template HelmRelease:
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s/helm-charts/main/charts/library/common/crds/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: app-name
  namespace: default
spec:
  # Rest of HelmRelease definition
```

### Complete Examples with Schema Validation

#### HelmRelease Example
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s/helm-charts/main/charts/library/common/crds/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: &app app-name
  namespace: default
spec:
  interval: 15m
  chart:
    spec:
      chart: app-template
      version: 1.5.1  # Schema requires pinned version
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system
  install:
    createNamespace: true
    remediation:
      retries: 5
  upgrade:
    remediation:
      retries: 5
  values:
    # Schema validates these values against the app-template structure
    image:
      repository: ghcr.io/example/app
      tag: v1.0.0
    
    service:
      main:
        ports:
          http:
            port: 8080  # Schema validates this is a number, not a string
    
    ingress:
      main:
        enabled: true  # Schema validates this is a boolean
        ingressClassName: "nginx"  # Schema validates this exists
```

#### Kustomization Example
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1beta1.json
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:  # Schema validates this is required
  - namespace.yaml
  - helmrelease.yaml
  - pvc.yaml
namespace: app-namespace  # Schema validates this field
```

#### ExternalSecret Example
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/external-secrets/external-secrets/main/config/crds/bases/external-secrets.io_externalsecrets.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: default
spec:
  # Schema validates these required fields
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: app-secrets
    creationPolicy: Owner  # Schema validates this is an enum with specific values
  data:
    - secretKey: DATABASE_PASSWORD
      remoteRef:
        key: op://vault/database/password
```

For a standard Kustomization:
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/api/openapi/kustomization_schema.json
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  # Resources list
```
