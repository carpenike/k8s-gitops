---
status: proposed
date: 2026-10-30
decision-makers: Ryan Holt
---

# Scrypted on the Talos cluster

## Context and Problem Statement

Scrypted runs on Forge as `podman-scrypted.service`. It is the camera NVR,
the HomeKit bridge, and the Coral detection process. Forge is out of
memory on this container. The phones are on VLAN 30. The cameras are on
VLAN 50. ADR 0007 adds the `vlan30` attachment and reserves
`10.30.0.31/16` for this move. ADR 0001 left cameras on Forge. This
record is the exception.

## Decision Drivers

- HomeKit and mDNS share L2 with the phones, without `hostNetwork`
- Camera pulls are sourced from `10.30.0.31`, not from a sled address
- One replica, because there is one address and one HomeKit identity
- Recordings stay on the NFS export Forge already writes
- Plugin state and the HomeKit identity move with `/server/volume`
- The Coral is USB. Node Feature Discovery labels the sled that has it.
  There is no gasket extension and no PCIe Coral
- The repository stays public. No Scrypted password is committed

## Considered Options

- Leave Scrypted on Forge
- `hostNetwork` on a sled
- A VLAN 50 attachment so the cameras are on-link
- Multus `vlan30`, NFS recordings, a Ceph PVC for `/server/volume`

## Decision Outcome

Chosen option: "Multus `vlan30`, NFS recordings, a Ceph PVC for
`/server/volume`", because ADR 0007 already built the interface the
phones require, and the recordings are already on the media export.

The chart is `app-template` 5.3.0. The image is
`ghcr.io/koush/scrypted:v0.147.0-noble-full` at the digest Forge pins.
The pod attaches `kube-system/vlan30` at `10.30.0.31/16`. An init
container adds a route for `10.50.0.0/16` via `10.30.0.1` with source
`10.30.0.31`. Avahi listens on `net1` only. The deployment strategy is
`Recreate`. The replica count ships at 0 so an empty volume cannot
start a new HomeKit bridge.

Recordings are a static NFS volume,
`10.20.0.10:/mnt/tank/share/scrypted`, class `nfs-media`, mounted at
`/nvr`. Config and plugins are a `ceph-block` PVC mounted at
`/server/volume`. The UI is an HTTPRoute on `envoy-internal` only.

The node selector is `feature.node.kubernetes.io/coral-tpu=true`. Node
Feature Discovery sets it from USB vendor `1a6e`, or from `18d1:9302`
after the runtime reloads the device. The pod mounts `/dev/bus/usb`.
There is no PCIe Coral.

### Consequences

- Good, because HomeKit discovery is on VLAN 30 and the sleds still have
  no address there
- Good, because a sled failure is not a Forge failure for cameras that
  have moved, and Forge stops spending memory on this process after
  cutover
- Bad, because the replica count stays 0 until a person copies the Forge
  volume and sets it to 1. Starting on an empty volume is a new bridge
- Bad, because a chassis failure takes the NVR down with the cluster.
  Recordings remain on the NAS
- Bad, because cameras cannot open connections to `10.30.0.31`. Pull
  (RTSP, ONVIF polling) works. Camera-initiated push does not
- The HomeKit pairing keys move with the Ceph volume. A new empty volume
  is a new bridge

## Pros and Cons of the Options

### Leave Scrypted on Forge

- Good, because the Coral, the iGPU, and the firewall rules are already
  there
- Bad, because the container is memory-starved and ADR 0007 exists so
  it can leave

### hostNetwork

- Good, because mDNS needs no second interface
- Bad, because the sled address is on VLAN 20, and the phones are on
  VLAN 30

### VLAN 50 attachment

- Good, because the cameras would be on-link
- Bad, because HomeKit would still need VLAN 30, and ADR 0007 already
  rejected a camera-VLAN interface

### Multus vlan30

- Good, because it is the attachment ADR 0007 reserved for this app
- Good, because the NFS export and the Ceph class already exist
- Bad, because outbound camera traffic needs a source route the shared
  attachment does not install
- Bad, because the replica count is a manual edit at cutover. Flux
  would revert a one-off scale
