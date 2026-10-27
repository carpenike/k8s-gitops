# One 10G switch, so each sled uses one port. The port is the per-node
# MAC (the active X520). The LAN is 10.20.0.0/16, so the gateway
# 10.20.0.1 is on-link. v1 handed these addresses out by DHCP and did
# not record the mask.
---
apiVersion: v1alpha1
kind: LinkAliasConfig
name: lan0
selector:
  match: mac(link.hardware_addr) == "{{ .Node.Data.macAddr }}"
---
apiVersion: v1alpha1
kind: LinkConfig
name: lan0
mtu: {{ .Node.Data.mtu }}
up: true
addresses:
  - address: "{{ .Node.IP }}/16"
routes:
  - gateway: "10.20.0.1"
{{- if eq .Node.Role "control-plane" }}
---
apiVersion: v1alpha1
kind: Layer2VIPConfig
link: lan0
name: "10.20.10.10"
{{- end }}
