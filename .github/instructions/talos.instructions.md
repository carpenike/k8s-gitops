# GitHub Copilot Instructions for Talos Configuration

> **Schema Reference Best Practice (last updated: 2025-05-27):**
> - Use the latest authoritative schema URLs for each manifest type (see below).
> - Place schema references as a comment before the document separator (---) at the top of each YAML file.
> - Review and update schema URLs regularly as upstream projects change.

## When to Apply These Instructions

These instructions should be applied when working with Talos OS configuration files, including:
- Files in `/kubernetes/*/talos/` directories
- Files named `talconfig.yaml`
- Any files related to Talos machine configuration
- When configuring Kubernetes on Talos OS nodes

## Talos Configuration Structure

1. Follow the Talos configuration schema:
   ```yaml
   # yaml-language-server: $schema=https://raw.githubusercontent.com/budimanjojo/talhelper/master/pkg/config/schemas/talconfig.json
   ```

2. Use YAML anchors for repeated values:
   ```yaml
   clusterName: &clusterName ${clusterName}
   endpoint: "https://${clusterName}.${domainName}:6443"
   ```

3. Pin Talos and Kubernetes versions using Renovate annotations:
   ```yaml
   # renovate: depName=ghcr.io/siderolabs/installer datasource=docker
   talosVersion: v1.9.x
   # renovate: depName=ghcr.io/siderolabs/kubelet datasource=docker
   kubernetesVersion: v1.30.x
   ```

4. Always include API server certificate SANs:
   ```yaml
   additionalApiServerCertSans: &sans
     - &talosControlplaneVip ${clusterEndpointIP}
     - ${clusterName}.${domainName}
     - "127.0.0.1"
   additionalMachineCertSans: *sans
   ```

## Node Configuration

1. Define node configurations under the `nodes` section:
   ```yaml
   nodes:
     - hostname: node-name.domain
       controlPlane: true|false
       ipAddress: x.x.x.x
       installDisk: /dev/xxx
   ```

2. Configure network interfaces:
   ```yaml
   networkInterfaces:
     - interface: bond0
       bond:
         mode: active-backup
         deviceSelectors:
           - hardwareAddr: xx:xx:xx:xx:xx:xx
             driver: driver-name
       dhcp: true
   ```

3. For VLAN configurations:
   ```yaml
   vlans:
     - &vlanXX
       vlanId: XX
       mtu: 1500
       dhcp: true
       dhcpOptions:
         routeMetric: 4096
   ```

4. Reference VLAN configurations to reduce duplication:
   ```yaml
   vlans:
     - *vlanXX
   ```

## Talos Machine Configuration

1. Use `talhelper` for generating machine configurations:
   - Use the task command: `task talos:gen-config`
   - Apply with: `task talos:apply-config`

2. Always version control the Talos configuration files.

3. For patches and customizations, use the `patches` section:
   ```yaml
   patches:
     - global: true
       patch:
         - op: add
           path: /machine/files/-
           value:
             content: |
               # File content here
             permissions: 0644
             path: /path/to/file
   ```

4. For Cilium networking:
   ```yaml
   cniConfig:
     name: none
   ```

5. Configure node labels and taints:
   ```yaml
   nodeLabels:
     key: value
   taints:
     - key: key
       value: value
       effect: NoSchedule|NoExecute|PreferNoSchedule
   ```

## YAML Schema Validation Guidelines

- **Talos Config:**
  ```yaml
  # yaml-language-server: $schema=https://raw.githubusercontent.com/budimanjojo/talhelper/master/pkg/config/schemas/talconfig.json
  ```
