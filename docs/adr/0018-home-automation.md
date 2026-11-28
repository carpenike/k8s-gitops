---
status: proposed
date: 2026-11-25
decision-makers: Ryan Holt
---

# Home automation on the Talos cluster

## Context and Problem Statement

Home Assistant, zigbee2mqtt, Z-Wave JS UI and the EMQX broker run on
Forge as NixOS services. Home Assistant's config is the private repository
`carpenike/hass-config`, checked out by hand as Forge's data directory.
A merged change reaches the house only when someone pulls on Forge.

The owner wants agents to fix and improve automations through pull
requests that deploy on merge, the way the rest of this cluster works.
The owner also decided on 2026-11-25 that most services leave Forge, and
that Forge keeps only iGPU workloads and monitoring (Alertmanager,
Prometheus).

ADR 0001 says Forge keeps the workloads that need a GPU, USB radios, or
must outlive the chassis. This record amends that line for home
automation. Scrypted (ADR 0008) was the first exception.

## Decision Drivers

- A merged hass-config PR reaches Home Assistant without a person on Forge
- HomeKit, mDNS, Sonos callbacks and WeatherFlow UDP are on VLAN 30
- Home Assistant needs nothing on Forge once all four have moved
- The Z-Wave JS WebSocket server has no authentication and stays off the LAN
- One HomeKit identity, one Zigbee coordinator client, one recorder writer
- No site value or secret in this public repository

## Considered Options

- Keep everything on Forge and add a pull timer for hass-config
- Move Home Assistant only; leave the bridges and EMQX on Forge
- Move all four into one namespace on the cluster

## Decision Outcome

Chosen option: "Move all four into one namespace on the cluster", because
Home Assistant then depends on nothing on Forge, the Z-Wave socket never
leaves the cluster, and hass-config deploys through the same review path
as the rest of the house.

Namespace `home-automation`, one `app-template` release each, every
controller shipped at `replicas: 0` and `Recreate`:

- EMQX 6.3.3, one node. A multi-node cluster needs a commercial license
  from 5.9 on (Business Source License), so availability is the pod
  rescheduling onto another sled. `ClusterIP` for the cluster, plus a
  temporary LoadBalancer `10.45.10.30` that accepts only Forge
  (`10.20.0.30`) while Frigate and TeslaMate are still there. No LAN
  device uses MQTT.
- zigbee2mqtt 2.14.2. The coordinator is a network adapter
  (`tcp://10.30.100.183:6638`), reached by routed unicast.
- Z-Wave JS UI. The USB stick (`0658:0200`) moves from Forge to one sled.
  NFD rule `zwave-stick` labels it, and the pod is pinned there. The
  container is privileged to open the hostPath tty. Port 3002 is
  reachable from the Home Assistant pod only.
- Home Assistant 2026.10.1 on `vlan30` at `10.30.0.32/16`, outside the
  DHCP pool. Recorder in postgres17 (database `home_assistant`, role
  `hass_recorder`). Config from hass-config `main` by git-sync with a
  read-only deploy key; a webhook to Home Assistant reloads after each new
  commit.

Bluetooth already comes from ESPHome proxies over the network, so Forge's
adapter is not needed. Phones away from home use the house VPN, so Home
Assistant has no `envoy-external` route.

### Consequences

- Good, because a reviewed hass-config merge is live in about a minute
- Good, because the Z-Wave WebSocket and MQTT stay inside the cluster
- Good, because Forge stops running four stateful services
- Bad, because a chassis or shared-PSU failure now takes the whole
  house's automation down, not only the cluster's services
- Bad, because Z-Wave depends on one sled until the stick is moved by hand
- Bad, because a hass-config merge runs code in Home Assistant
  (`shell_command`, `command_line`), so the repository's branch protection
  and required review are now part of the house's security boundary
- Bad, because the zigbee2mqtt and Z-Wave JS UI frontends keep the gateway
  Pocket ID login, which admits any Pocket ID user. Forge's Caddy required
  group `admins`. The group check needs the JWT provider that
  [gateway-auth.md](../platform/gateway-auth.md) describes and this branch
  does not install yet

## Pros and Cons of the Options

### Keep everything on Forge with a pull timer

- Good, because nothing moves and nothing new can break
- Bad, because the owner is retiring Forge's general services
- Bad, because the deploy path would be a one-off timer unlike the cluster

### Move Home Assistant only

- Good, because the radios stay where they are
- Bad, because the unauthenticated Z-Wave socket and MQTT would have to be
  opened from Forge to the cluster over VLAN 20
- Bad, because Home Assistant would still fail when Forge does

### Move all four

- Good, because the dependencies move together and stay on cluster traffic
- Bad, because the stick has to move to a sled and the cutover is four
  windows instead of one
