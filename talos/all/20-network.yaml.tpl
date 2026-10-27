# topf renders the Go templates in this file. The LAN is 10.20.0.0/16, so
# the gateway 10.20.0.1 is on-link. v1 handed these addresses out by DHCP
# and did not record the mask.
---
apiVersion: v1alpha1
kind: LinkAliasConfig
name: ethSel0
selector:
  match: glob("{{ .Node.Data.macAddr }}", mac(link.hardware_addr))
---
apiVersion: v1alpha1
kind: BondConfig
name: bond0
links:
  - ethSel0
bondMode: active-backup
mtu: {{ .Node.Data.mtu }}
addresses:
  - address: "{{ .Node.IP }}/16"
routes:
  - gateway: "10.20.0.1"
{{- if eq .Node.Role "control-plane" }}
---
apiVersion: v1alpha1
kind: Layer2VIPConfig
link: bond0
name: "10.20.10.10"
{{- end }}
