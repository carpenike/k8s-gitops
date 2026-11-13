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
---
# VLAN 30 is the wireless client network, 10.30.0.0/16. The physical port
# stays untagged on the server LAN (VLAN 20). This subinterface has no
# address. A macvlan child does not need a parent address, and a node
# address would put every sled on the client VLAN. The kernel name is
# ens1f0.30. parent is the Talos alias lan0. Multicast stays on so mDNS
# from a macvlan child can leave the port.
apiVersion: v1alpha1
kind: VLANConfig
name: ens1f0.30
vlanID: 30
vlanMode: 802.1q
parent: lan0
up: true
multicast: true
mtu: {{ .Node.Data.mtu }}
{{- if eq .Node.Role "control-plane" }}
---
apiVersion: v1alpha1
kind: Layer2VIPConfig
link: lan0
name: "10.20.10.10"
{{- end }}
