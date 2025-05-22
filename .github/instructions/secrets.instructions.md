# GitHub Copilot Instructions for Secrets Management

## When to Apply These Instructions

These instructions should be applied when working with secrets and sensitive data, including:
- Any files with `.sops.yaml` extension
- Files in `/kubernetes/*/bootstrap/` directories containing secrets
- When working with `Secret` resources in Kubernetes
- When using the ExternalSecrets operator
- When handling credentials, tokens, keys, or any sensitive information
- When implementing SOPS/AGE encryption for GitOps

## Secret Management Principles

1. Never commit plaintext secrets to the repository.
2. Use SOPS with AGE for encrypting secrets.
3. Use ExternalSecrets for retrieving secrets from external providers.
4. Include the `.sops.yaml` configuration file.

## SOPS and AGE

1. Configure SOPS with AGE:
   ```yaml
   # .sops.yaml
   creation_rules:
     - path_regex: kubernetes/.*\.sops\.ya?ml
       encrypted_regex: ^(data|stringData)$
       age: age1xyz...
   ```

2. Encrypt Kubernetes secrets:
   ```yaml
   # Before encryption
   apiVersion: v1
   kind: Secret
   metadata:
     name: mysecret
     namespace: default
   stringData:
     password: super-secret
   ```

3. Use SOPS to encrypt:
   ```bash
   sops --encrypt --in-place secret.yaml
   ```

4. Name encrypted secrets with `.sops.yaml` suffix.

5. Store the AGE key securely:
   ```yaml
   apiVersion: v1
   kind: Secret
   metadata:
     name: sops-age
     namespace: flux-system
   stringData:
     age.agekey: AGE-SECRET-KEY-...
   ```

## External Secrets

1. Configure ClusterSecretStore:
   ```yaml
   apiVersion: external-secrets.io/v1beta1
   kind: ClusterSecretStore
   metadata:
     name: provider-name
   spec:
     provider:
       # Provider-specific configuration
   ```

2. Create ExternalSecret resources:
   ```yaml
   apiVersion: external-secrets.io/v1beta1
   kind: ExternalSecret
   metadata:
     name: app-secret
     namespace: app-namespace
   spec:
     secretStoreRef:
       kind: ClusterSecretStore
       name: provider-name
     target:
       name: app-secret
       creationPolicy: Owner
     data:
       - secretKey: DB_PASSWORD
         remoteRef:
           key: path/to/secret
           property: password
   ```

3. For OnePassword integration:
   ```yaml
   data:
     - secretKey: password
       remoteRef:
         key: op://vault/item/field
   ```

## Flux and SOPS Integration

1. Configure Flux to decrypt SOPS secrets:
   ```yaml
   apiVersion: kustomize.toolkit.fluxcd.io/v1
   kind: Kustomization
   metadata:
     name: cluster-apps
     namespace: flux-system
   spec:
     # ... other fields
     decryption:
       provider: sops
       secretRef:
         name: sops-age
   ```

2. Apply this pattern to all Kustomizations that need secret decryption.

3. Place the sops-age secret in the bootstrap directory:
   ```
   kubernetes/<cluster>/bootstrap/age-key.sops.yaml
   ```

## Sensitive Environment Variables

1. Reference secrets in HelmRelease values:
   ```yaml
   envFrom:
     - secretRef:
         name: app-secret
   ```

2. For individual environment variables:
   ```yaml
   env:
     - name: DB_PASSWORD
       valueFrom:
         secretKeyRef:
           name: app-secret
           key: password
   ```
