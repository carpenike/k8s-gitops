# Lessons from the v1 tree

The tag `archive/talos-v1` points at the previous `main`. These notes are
from that tree's shape. They omit addresses, hostnames, and key material.

## Too many ways to do the same job

Block storage was wired three times: Rook-Ceph, OpenEBS, and democratic-csi.
Ingress was also split: ingress-nginx, including a class that used a
Tailscale load balancer, alongside Cilium's Gateway resources. Identity was
split across authentik and oauth2-proxy, with authelia and dex left in the
archive. Kyverno and Multus were further control planes on top of that.

The rebuild keeps one of each. Ceph for block, a static NFS class for
media, Envoy Gateway for HTTP, and no policy engine or extra CNI until a
real need shows up. Identity for public apps stays Pocket ID on Forge, not
a second IdP in the cluster.

Multus was added later, as a meta-plugin in front of Cilium, for a pod
interface on the wireless client VLAN (ADR 0007). Cilium is still the pod
network.

## A secret store that was itself a workload

External Secrets read 1Password through a Connect server deployed in the
cluster. Connect had to be healthy before anything else could get its
credentials, and it was another thing to upgrade. The SDK provider uses a
service-account token and no Connect pod. The token is a bootstrap secret,
created by hand, and it is not committed.

## Nodes that did not match

One control-plane node was a VM: virtio disk and NIC. The others were bare
metal with `ixgbe`. Install disks and NIC drivers differed. The rebuild is
four of the same sled, three of them schedulable control planes, one
worker. All four use the same install and a single 10G NIC.

## Internal DNS that wanted the whole zone

v1 ran k8s_gateway, which is also what cluster-template ships. That only
works if the home resolver forwards the entire zone to the cluster. Static
records for other hosts share the zone, so the forward would have taken
them over. The replacement is external-dns writing only cluster names to
the router, with TXT ownership. ADR 0003.

## Old versions, and kernel arguments that traded safety for speed

The last Talos and Kubernetes versions in the v1 inventory were v1.9.5 and
v1.30.11. Machine config also turned off CPU mitigations and AppArmor.
Those arguments are not carried forward. The new pins are Talos v1.14.5
and Kubernetes v1.37.1, and the node patches only disable the pieces Cilium
replaces (flannel, kube-proxy, and in-tree CoreDNS).
