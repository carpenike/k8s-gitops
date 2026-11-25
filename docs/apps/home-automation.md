# Home automation

EMQX, zigbee2mqtt, Z-Wave JS UI and Home Assistant, moved from Forge.
ADR 0018. Namespace `home-automation`. Every controller ships at
`replicas: 0`; each cutover below sets one to 1 in its own pull request.
Until then Forge serves all four.

| App | Image | Volume | Route (`envoy-internal`) | Login |
| --- | --- | --- | --- | --- |
| EMQX | `emqx/emqx` 6.3.3 | `emqx-data` 2Gi | `emqx.${SECRET_DOMAIN}` (dashboard) | EMQX's own (label `app`) |
| zigbee2mqtt | `koenkk/zigbee2mqtt` 2.14.2 | `zigbee2mqtt-data` 1Gi | `zigbee.${SECRET_DOMAIN}` | Gateway Pocket ID |
| Z-Wave JS UI | `zwave-js/zwave-js-ui` 11.27.0 | `zwave-js-ui-store` 1Gi | `zwave.${SECRET_DOMAIN}` | Gateway Pocket ID |
| Home Assistant | `home-operations/home-assistant` 2026.10.1 | `home-assistant-config` 10Gi, `home-assistant-venv` 5Gi | `ha.${SECRET_DOMAIN}` | Home Assistant's own (label `app`) |

Every volume is `ceph-block` and has a VolSync restic backup to R2
(`<app>/backup`): hourly for zigbee2mqtt, Z-Wave JS UI and Home
Assistant, daily for EMQX. The recorder is in postgres17 and is covered by
CloudNativePG's backups.

## Network

- **EMQX** is `ClusterIP` (`emqx.home-automation.svc:1883`). LoadBalancer
  `emqx-forge` at `10.45.10.30` accepts only Forge (`10.20.0.30`). After
  the EMQX cutover, Forge's `mqtt-forward-cluster` relays every client
  still on Forge through it, including the cluster Scrypted's
  `mqtt-forward` sidecar, which dials Forge. Point that sidecar at
  `emqx.home-automation.svc:1883` later, and delete `emqx-forge` when the
  last Forge client moves.
- **zigbee2mqtt** reaches the coordinator at `10.30.100.183:6638` from
  `eth0`, routed, as Forge did.
- **Z-Wave JS UI** runs on the sled with the stick (NFD label
  `feature.node.kubernetes.io/zwave-stick`). The WebSocket server on 3002
  has no authentication; only Home Assistant may connect. Until Home
  Assistant moves, that is Forge, through LoadBalancer `zwave-js-ui-forge`
  at `10.45.10.31`, which accepts only `10.20.0.30`; Forge's
  `zwave-forward-cluster` relays its loopback `:3002` there. Delete both
  with the Home Assistant cutover.
- **Home Assistant** has `net1` on `kube-system/vlan30` at `10.30.0.32/16`
  ([multus.md](../platform/multus.md)). HomeKit (21063-21068), mDNS, the
  Sonos callback (1400) and WeatherFlow UDP (50222) use it. Its policy
  admits 8123 from `envoy-internal` only, which is why `trusted_proxies`
  can be the pod range `10.42.0.0/16`. Phones away from home use the
  house VPN; there is no external route.

## Config from git

Home Assistant's config is `carpenike/hass-config` (private). The pod has
three extra containers:

1. `git-clone` (init): git-sync clones `main` once into `/git` with a
   read-only deploy key.
2. `link-config` (init): `link-config.sh` points the git-owned paths in
   `/config` at the checkout. A real file found where a link belongs is
   moved to `/config/.pre-gitops/`, never deleted.
3. `git-sync` (sidecar): pulls every 60 seconds. After a new commit it
   POSTs the local webhook `HA_GITOPS_WEBHOOK_ID`, and hass-config's
   `packages/gitops.yaml` reloads YAML.

| Owned by git (linked) | Owned by Home Assistant (on the volume) |
| --- | --- |
| `configuration.yaml`, `packages/`, `dashboards/`, `scripts/`, `blueprints/`, `custom_sentences/`, `www/streamline-card/` | `.storage/`, `automations.yaml`, `scripts.yaml`, `scenes.yaml`, `custom_components/`, `media/`, `www/` (other than the link) |

A change to `configuration.yaml` that adds an integration needs a pod
restart (`kubectl -n home-automation rollout restart deploy/home-assistant`).
Reloading picks up packages, automations, scripts, templates and
dashboards.

The merge is the deployment. A hass-config PR can add `shell_command`
or `command_line` entries, which run in the pod with its secrets. So
hass-config `main` needs branch protection: a pull request, Ryan's
review, and the `check_config` CI job green. Agents open PRs and never
merge.

## 1Password

Vault `k8s-secrets`. Values come from Forge's sops file
(`hosts/forge/secrets.sops.yaml` in carpenike/nix-config), never printed.

| Item | Fields | Used by |
| --- | --- | --- |
| `emqx` | `dashboard_password`, `home_assistant_password`, `zigbee2mqtt_password`, `zwave_js_ui_password`, `frigate_password`, `teslamate_password`, `scrypted_password` | Broker bootstrap users; each client's own password. Forge keys `emqx/dashboard_password`, `home-assistant/mqtt-password`, `zigbee2mqtt/mqtt_password`, `zwave-js-ui/mqtt_password`, and the Frigate, TeslaMate and Scrypted ones |
| `zwave-js-ui` | `session_secret`, `s0_legacy_key`, `s2_unauthenticated_key`, `s2_authenticated_key`, `s2_access_control_key`, `s2_long_range_key`, `s2_long_range_access_control_key` | Forge keys `zwave-js-ui/*`. Must be Forge's values, or secure nodes stop answering |
| `zigbee2mqtt` | `network_key`, `pan_id`, `ext_pan_id` | Forge keys `zigbee2mqtt/*`, exactly as stored there (the PAN ids are what Forge puts in `ZIGBEE2MQTT_CONFIG_ADVANCED_*`). The PAN ids go into the environment; `network_key` is a record, since the copied `secret.yaml` already holds it |
| `home-assistant-env` | One field per variable in Forge's `home-assistant/env`, named as the variable | `extract` into the container environment |
| `home-assistant-recorder` | `db_password` | Role `hass_recorder` in postgres17. New value |
| `home-assistant-gitops` | `deploy_key`, `webhook_id` | git-sync. The deploy key's public half goes on hass-config with write access off. The webhook id is a random string |

The broker imports `users.csv` (from item `emqx`) into its own database
on start. After the first start, change a password in the EMQX dashboard
as well as in 1Password.

ACLs are `emqx/app/acl.conf`, the same users and topics as Forge.
`no_match` is `allow`, as on Forge. Switch it to `deny` once the
dashboard's authorization metrics show no misses for a week.

## Before the cutovers

- [ ] 1Password items above exist (six); every ExternalSecret in the namespace
      is `SecretSynced`
- [ ] hass-config prep PR merged (real `configuration.yaml`, portable
      script calls, CI, `packages/gitops.yaml`), branch protection on
- [ ] Deploy key added to hass-config, write access off
- [ ] `kubectl -n cnpg-system get database home-assistant` is applied
- [ ] Z-Wave stick moved to a sled with a short USB extension, label
      `zwave-stick=true` on exactly one node
- [ ] Lower the DNS TTL for `ha.`, `zigbee.`, `zwave.` and `emqx.` a day
      ahead

## Cutovers

One window each, in this order. Every step that stops a Forge unit or
copies data needs Ryan's go.

### 1. EMQX

1. Set `replicas: 1` for `emqx`. Check the six users exist in the
   dashboard and that `emqx-forge` answers from Forge. No client uses it
   yet.
2. Merge the nix-config change that disables Forge's EMQX and runs
   `mqtt-forward-cluster` instead: socat on Forge's `:1883` to
   `10.45.10.30:1883`. Every Forge client, and the cluster Scrypted's
   `mqtt-forward` sidecar (which dials `10.20.0.30:1883`), keeps its
   settings and reaches the cluster broker through it. Apply it on Forge.
3. Check that each client reconnects (the dashboard's client list) and that
   Zigbee, Scrypted and TeslaMate entities update in Home Assistant.
   Retained messages on Forge's broker are not copied; zigbee2mqtt and the
   others republish discovery and state when they reconnect.

Forge's sops file has no `frigate/mqtt_password`, so `emqx/frigate_password`
is a new value. Frigate authenticates only after that value is added to
Forge's sops as `frigate/mqtt_password`.

Each client moves off the forwarder when it moves to the cluster. Delete the
forwarder and `emqx-forge` when the last Forge client is gone.

### 2. zigbee2mqtt

Two pull requests: nix-config disables Forge's zigbee2mqtt (its dataset
stays snapshotted and backed up for the rollback week), and this repo sets
`replicas: 1`. Do the three steps in one sitting. Zigbee is down from step 1
to step 3, about ten minutes; devices keep their state and rejoin nothing.

1. Merge the nix-config pull request and apply it on Forge. That stops
   `zigbee2mqtt` there. Do not merge it and walk away: Forge applies `main`
   nightly, and Zigbee would stay down until the next two steps. Check
   `systemctl is-active zigbee2mqtt` on Forge says `inactive`. Only one
   process may hold the coordinator.
2. Copy `/var/lib/zigbee2mqtt` into the `zigbee2mqtt-data` volume, which
   exists already at `replicas: 0`. From a workstation with `kubectl` and
   SSH to Forge:

   ```sh
   kubectl -n home-automation run z2m-copy --image=busybox:1.38 \
     --restart=Never --overrides='{"spec":{
       "securityContext":{"runAsUser":1000,"runAsGroup":1000,"fsGroup":1000},
       "containers":[{"name":"z2m-copy","image":"busybox:1.38",
         "command":["sleep","3600"],
         "volumeMounts":[{"name":"data","mountPath":"/data"}]}],
       "volumes":[{"name":"data",
         "persistentVolumeClaim":{"claimName":"zigbee2mqtt-data"}}]}}'
   kubectl -n home-automation wait --for=condition=Ready pod/z2m-copy
   ssh forge 'sudo tar -C /var/lib/zigbee2mqtt --exclude=./log -cf - .' \
     | kubectl -n home-automation exec -i z2m-copy -- tar -C /data -xf -
   kubectl -n home-automation exec z2m-copy -- ls -la /data
   kubectl -n home-automation delete pod z2m-copy
   ```

   The listing shows `configuration.yaml`, `secret.yaml`, `database.db`,
   `coordinator_backup.json`, `devices.yaml` and `groups.yaml`, owned by
   `1000`. The environment overrides the broker, the frontend address and
   port, and the PAN ids; everything else (channel 25, transmit power,
   availability, the network key in `secret.yaml`) comes from the copied
   files.
3. Merge the pull request that sets `replicas: 1`. Check the log says the
   coordinator started and MQTT connected, `zigbee.${SECRET_DOMAIN}` opens
   behind the Pocket ID login, and Zigbee entities update in Home Assistant
   on Forge.

### 3. Z-Wave JS UI

Moving the stick to the labelled sled takes Z-Wave down; it is back when
the cluster pod runs. As for zigbee2mqtt, two pull requests: nix-config
disables Forge's `zwave-js-ui` (dataset kept) and runs
`zwave-forward-cluster`, and this repo sets `replicas: 1` and adds
`zwave-js-ui-forge`.

1. On Forge, stop `zwave-js-ui` and keep it stopped until the nix-config
   change applies. `systemctl mask --runtime` does not hold on NixOS (the
   unit file is in `/etc/systemd/system`); use a runtime drop-in instead,
   `/run/systemd/system/zwave-js-ui.service.d/99-cutover-block.conf` with
   `[Unit]` and `ConditionPathExists=/nonexistent`, then
   `systemctl daemon-reload`. Tar `/var/lib/zwave-js-ui` to `/var/backup`.
2. Copy `/var/lib/zwave-js-ui` into `zwave-js-ui-store` the same way as
   zigbee2mqtt (a busybox pod on the volume, `ssh forge 'sudo tar …' |
   kubectl exec -i … tar -x`), leaving out `logs/`. The pod runs as
   root, so no uid is needed. In the copied `settings.json`, set
   `zwave.port` to `/dev/zwave`: a port saved there wins over
   `ZWAVEJS_SERIAL_PORT`, which only applies when settings.json has none
   (found at the 2026-11-25 cutover). MQTT is disabled there (Home
   Assistant uses the WebSocket server); if it is turned on later, its host
   is `emqx.home-automation.svc.cluster.local`, user `zwave-js-ui`.
3. Merge this repo's pull request, then the nix-config one, and apply that
   on Forge. Home Assistant keeps its URL: Forge's loopback `:3002` now
   relays to `10.45.10.31:3002`, which accepts only Forge.
4. Check every node is alive in the UI and Z-Wave entities update in Home
   Assistant.

### 4. Home Assistant

1. Stop and mask `home-assistant` on Forge. Take a ZFS snapshot.
2. Dump and restore the recorder:

   ```sh
   sudo -u postgres pg_dump -h /run/postgresql -Fc --no-owner --no-acl home_assistant > home_assistant.dump
   kubectl -n cnpg-system port-forward svc/postgres17-rw 15432:5432 &
   PGHOST=127.0.0.1 PGPORT=15432 PGSSLMODE=require \
     pg_restore --no-owner --no-acl -U hass_recorder -d home_assistant home_assistant.dump
   ```

3. Copy `/var/lib/home-assistant` into `home-assistant-config` without
   `.git`, owned by `568:568`. Keep `media/`, `custom_components/`,
   `.storage/` and `omada-block.env`.
4. Set `replicas: 1`. `link-config` moves the copied git-owned paths to
   `.pre-gitops/` and links the checkout.
5. In Home Assistant: Z-Wave JS integration URL
   `ws://zwave-js-ui.home-automation.svc.cluster.local:3002`; Settings,
   System, Network: only `net1` for mDNS and HomeKit.
6. Point `ha.<domain>` at the cluster (mikrotik-dns publishes it once the
   route is accepted).
7. Check, in order: login and the mobile app, Z-Wave nodes, Zigbee
   entities, HomeKit bridges paired on a phone, a Sonos announcement,
   WeatherFlow readings, the Atlona and Omada `command_line` switches,
   a test automation, the recorder writing, homelab-mcp `ha_health`, and a
   no-op hass-config commit reloading within a minute.

## Rollback

Each app on its own, during the first week:

1. Set its `replicas: 0` in a PR.
2. For Z-Wave, move the stick back to Forge.
3. Unmask and start the Forge unit; point DNS back. Forge's data is as it
   was when the unit stopped.
4. After several days in the cluster, copy the volume back first, or
   Forge forgets what was paired or changed since.

After a week without rollback, a nix-config PR retires the four services
from Forge and keeps their datasets for a retention window, as
`hosts/forge/services/retired-to-cluster.nix` did in November.
