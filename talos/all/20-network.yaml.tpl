# topf renders the Go templates in this file. The gateway and prefix are
# RFC 5737 placeholders, matching cluster.example.toml.
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
  - address: "{{ .Node.IP }}/24"
routes:
  - gateway: "192.0.2.1"
{{- if eq .Node.Role "control-plane" }}
---
apiVersion: v1alpha1
kind: Layer2VIPConfig
link: bond0
name: "192.0.2.10"
{{- end }}
