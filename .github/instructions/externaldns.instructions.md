# GitHub Copilot Instructions for ExternalDNS with Cloudflare and Bind

## When to Apply These Instructions

These instructions should be applied when working with ExternalDNS configuration, including:
- Files in `/kubernetes/*/apps/network/external-dns/` directories
- When configuring external DNS with Cloudflare
- When configuring internal DNS with Bind
- When adding annotations to Ingress or Service resources
- When setting up split-horizon DNS

## ExternalDNS Best Practices

1. Use separate ExternalDNS deployments for external (Cloudflare) and internal (Bind) DNS:
   ```yaml
   # For external DNS (Cloudflare)
   fullnameOverride: externaldns-external
   
   # For internal DNS (Bind)
   fullnameOverride: externaldns-internal
   ```

2. Configure appropriate domain filters:
   ```yaml
   domainFilters:
     - holthome.net
   ```

3. Set up proper provider-specific configurations:
   - For Cloudflare:
     ```yaml
     provider: cloudflare
     env:
       - name: CF_API_TOKEN
         valueFrom:
           secretKeyRef:
             name: externaldns-external-secrets
             key: cloudflare_api_token
     ```
   - For Bind:
     ```yaml
     provider: rfc2136
     env:
       - name: EXTERNAL_DNS_RFC2136_HOST
         value: "10.20.0.15"
       - name: EXTERNAL_DNS_RFC2136_PORT
         value: "5391"
       - name: EXTERNAL_DNS_RFC2136_ZONE
         value: "holthome.net"
       - name: EXTERNAL_DNS_RFC2136_TSIG_AXFR
         value: "true"
       - name: EXTERNAL_DNS_RFC2136_TSIG_KEYNAME
         value: externaldns
       - name: EXTERNAL_DNS_RFC2136_TSIG_SECRET_ALG
         valueFrom:
           secretKeyRef:
             name: externaldns-internal-secrets
             key: bind_rndc_algorithm
       - name: EXTERNAL_DNS_RFC2136_TSIG_SECRET
         valueFrom:
           secretKeyRef:
             name: externaldns-internal-secrets
             key: bind_rndc_secret
     ```

4. Use appropriate policy for DNS synchronization:
   ```yaml
   policy: sync  # Use 'sync' for complete DNS management
   ```

## DNS Annotation Patterns

1. For routing an Ingress through the external Cloudflare proxy:
   ```yaml
   metadata:
     annotations:
       external-dns.alpha.kubernetes.io/target: external.holthome.net
   ```

2. For routing an Ingress through internal DNS only:
   ```yaml
   metadata:
     annotations:
       external-dns.alpha.kubernetes.io/target: internal.holthome.net
   ```

3. For direct hostname assignment:
   ```yaml
   metadata:
     annotations:
       external-dns.alpha.kubernetes.io/hostname: app.holthome.net
   ```

4. Using YAML anchors for consistent hostname patterns:
   ```yaml
   metadata:
     annotations:
       external-dns.alpha.kubernetes.io/target: &hostname ingress-ext.holthome.net
   spec:
     hostName: something.holthome.net
     listener:
       annotations:
         external-dns.alpha.kubernetes.io/hostname: *hostname
   ```

## Split-Horizon DNS Configuration

For services that need to be accessible both internally and externally:

1. Configure the internal ExternalDNS instance to handle `*.internal.holthome.net`
2. Configure the external ExternalDNS instance to handle `*.holthome.net` or `*.external.holthome.net`
3. Use targeted annotations to control which DNS provider handles each record

## Gateway/Ingress Controller Configuration

For Cilium gateways or ingress controllers:

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: Gateway
metadata:
  name: gateway
  annotations:
    external-dns.alpha.kubernetes.io/target: &hostname ingress-ext.holthome.net
spec:
  gatewayClassName: cilium
  listeners:
    - name: http
      port: 80
      protocol: HTTP
      hostname: "*"
      allowedRoutes:
        namespaces:
          from: All
      annotations:
        external-dns.alpha.kubernetes.io/hostname: *hostname
```

## Cloudflare-Specific Settings

For Cloudflare-specific functionality:

```yaml
extraArgs:
  - --cloudflare-dns-records-per-page=1000
  - --cloudflare-proxied  # Enable Cloudflare proxy protection
```

## Bind-Specific Settings

For Bind DNS server integration:

```yaml
extraArgs:
  - --rfc2136-min-ttl=60  # Set minimum TTL for records
```
