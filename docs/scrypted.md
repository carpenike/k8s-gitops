# Scrypted

Camera NVR, HomeKit bridge, and Coral detection. ADR 0008. Forge still
serves it until the cutover below. This cluster serves the UI at
`https://scrypted.holthome.net` on `envoy-internal` (`10.45.10.50`).
The manifest hostname is `scrypted.${SECRET_DOMAIN}`. `mikrotik-dns`
publishes that name. The route has no parent on `envoy-external`.

The gateway Pocket ID policy applies, then Scrypted's own login. Forge's
Caddy vhost does not add a second login. That is the cluster pattern for
an internal route.

## What Forge runs today

Read from `carpenike/nix-config` `main`.

- Unit `podman-scrypted.service`. `hostNetwork` is the module default.
  HTTP `11080`, HTTPS `10443`. Caddy proxies HTTP to `127.0.0.1:11080`
  with no portal in front. Healthcheck is `GET /` on `11080`.
- Image `ghcr.io/koush/scrypted:latest` at digest
  `sha256:e78b4fcecdd6c61acaaf22b50ccef303c738da58cc0be57afdb116521df52296`.
  That digest is the tag `v0.147.0-noble-full`. The full image installs
  `libedgetpu1-std`.
- Data directory `/var/lib/scrypted`, ZFS dataset `tank/services/scrypted`,
  mounted at `/server/volume`. The container runs as root.
- Recordings: NFS `10.20.0.10:/mnt/tank/share` mounted at `/mnt/data`
  (`nfsvers=4.2`, `soft`, `timeo=150`, `retrans=3`, `noatime`). Scrypted
  uses `/mnt/data/scrypted`, container path `/nvr`, env
  `SCRYPTED_NVR_VOLUME=/nvr`. The export squashes writers to uid 1000,
  gid 100. The client prefix is `10.20.0.0/16`.
- Devices: `/dev/bus/usb` for the USB Coral, plus the Intel iGPU for
  VAAPI. `--shm-size=1024m`. Env `SCRYPTED_DOCKER_AVAHI=true` and
  `LIBVA_DRIVER_NAME=iHD`. Time zone `America/New_York`.
- HomeKit firewall on Forge opens UDP `5353` and TCP `34428`, `47163`,
  `43205`, `44467`, `21064`. Those accessory ports are whatever the
  copied plugin state still binds. They are not Kubernetes Service
  ports. Phones reach them on `10.30.0.31`.
- MQTT plugin target on Forge is `mqtt://127.0.0.1:1883`, user
  `scrypted`. The password is a SOPS secret and is not in this repo.
  The plugin state, including that password, lives in `/server/volume`.
- Memory on Forge was raised to 8Gi after repeated cgroup kills. This
  pod requests 1 CPU and 2Gi, and limits 8 CPU and 12Gi. The 1Gi
  `/dev/shm` tmpfs counts against that limit.

## What this cluster runs

Namespace `scrypted`. Chart `app-template` 5.3.0. One replica,
`Recreate`. `hostNetwork` is false.

The pod annotation is the one in [multus.md](multus.md):

```yaml
k8s.v1.cni.cncf.io/networks: '[{"name":"vlan30","namespace":"kube-system","ips":["10.30.0.31/16"]}]'
```

Multus names that interface `net1`. Avahi's config allows `net1` and
denies `eth0`, so mDNS is not advertised from the pod address. An init
container with `NET_ADMIN` installs
`10.50.0.0/16 via 10.30.0.1 dev net1 src 10.30.0.31`. Phones on
`10.30.0.0/16` are on-link on `net1` without that route. `sbr` on the
attachment keeps traffic that is already sourced from `10.30.0.31` on
the macvlan.

`/server/volume` is PVC `scrypted-data`, `ceph-block`, 50Gi, retained
on Helm uninstall. `/nvr` is PVC `scrypted-nvr` bound to PV
`scrypted-nvr` (`10.20.0.10:/mnt/tank/share/scrypted`, class
`nfs-media`, `Retain`). The kubelet mounts NFS. The sled addresses are
inside the export's `10.20.0.0/16` client prefix.

The cameras cannot open connections toward VLAN 30. RTSP and ONVIF
polling work. A camera that pushes an event to Scrypted does not.

## Scheduling

Node Feature Discovery chart 0.20.1 runs a master and a worker in
`kube-system`. The worker reads PCI and USB. Two NodeFeatureRules:

| Label | Match |
| --- | --- |
| `feature.node.kubernetes.io/coral-tpu=true` | USB vendor `1a6e`, or vendor `18d1` and product `9302` |
| `feature.node.kubernetes.io/intel-gpu=true` | PCI vendor `8086` and class `0300` |

`1a6e` is the unflashed Coral (Global Unichip). After libedgetpu loads,
the same device is `18d1:9302`. sled-1 (`10.20.10.21`) and sled-3
(`10.20.10.23`) have that USB device. sled-0 and sled-2 do not. There
is no PCIe Coral. The Intel rule can match zero nodes.

Scrypted selects `feature.node.kubernetes.io/coral-tpu=true` and mounts
`/dev/bus/usb`. The Deployment ships at `replicas: 0`. NFD will label
the Coral sleds as soon as it runs. That must not start Scrypted. An
empty `scrypted-data` volume is a new HomeKit identity.

The Intel iGPU Forge uses is not mounted. Decode is CPU.
`feature.node.kubernetes.io/intel-gpu` is only a way to find `/dev/dri`
later.

## Cutover

Do this from a workstation. This repository does not stop Forge and
does not edit `carpenike/nix-config`.

`replicas: 0` is the gate. A `kubectl scale` does not stick: the next
reconcile puts the Deployment back to whatever git says.

1. Trunk VLAN 30 on the sled switch ports and apply the Talos machine
   config so `ens1f0.30` exists, if that is not done yet. See
   [multus.md](multus.md). Confirm `10.30.0.31` answers nothing else.
2. Let Flux reconcile Node Feature Discovery. Confirm the label on the
   two Coral sleds, and nowhere else:

   ```sh
   kubectl get nodes -L feature.node.kubernetes.io/coral-tpu
   ```

   Leave `replicas` at 0.
3. Stop Scrypted on Forge so only one process owns the HomeKit identity
   and the recordings directory:

   ```sh
   ssh forge 'sudo systemctl stop podman-scrypted.service'
   ```

   Leave the NixOS unit in place until the cluster copy is accepted.
4. Copy `/var/lib/scrypted` into PVC `scrypted-data`. Do not copy
   `/mnt/data/scrypted`. That directory is the NFS export this pod
   mounts at `/nvr`. The HelmRelease creates the claim at 0 replicas.
   Run the copy pod on a Coral node so a WaitForFirstConsumer volume is
   not pinned to sled-0 or sled-2. sled-1 and sled-3 both match; pick
   one with `nodeName` if the volume must stay there.

   ```sh
   kubectl -n scrypted apply -f - <<'EOF'
   apiVersion: v1
   kind: Pod
   metadata:
     name: scrypted-data-copy
     namespace: scrypted
   spec:
     restartPolicy: Never
     nodeSelector:
       feature.node.kubernetes.io/coral-tpu: "true"
     containers:
       - name: copy
         image: ghcr.io/koush/scrypted:v0.147.0-noble-full
         command: ["sleep", "infinity"]
         volumeMounts:
           - name: data
             mountPath: /server/volume
     volumes:
       - name: data
         persistentVolumeClaim:
           claimName: scrypted-data
   EOF
   kubectl -n scrypted wait --for=condition=Ready pod/scrypted-data-copy
   ssh forge 'sudo tar -C /var/lib/scrypted -cf - .' \
     | kubectl -n scrypted exec -i scrypted-data-copy -- tar -C /server/volume -xf -
   kubectl -n scrypted delete pod scrypted-data-copy --wait=true
   ```

5. If `scrypted.holthome.net` is a static DNS record aimed at Forge,
   delete it. `mikrotik-dns` only updates records it owns (TXT prefix
   `k8s.`, owner `cluster`) and publishes `envoy-internal` at
   `10.45.10.50`. Stop Forge's Caddy vhost for that name in the same
   window, or clients keep reaching Forge.
6. Set `replicas: 1` in
   `kubernetes/apps/scrypted/scrypted/app/helmrelease.yaml` and let Flux
   reconcile. Do not only scale the live Deployment. Then:

   ```sh
   kubectl -n scrypted rollout status deploy/scrypted
   ```

7. HomeKit. The pairing keys are in the copied volume. Phones on VLAN
   30 discover `10.30.0.31` over mDNS. If a bridge stays at
   "No Response", remove that bridge in the Home app and add it again.
   Do not delete `scrypted-data` to retry. That throws away the keys.
8. Verify. Open `https://scrypted.holthome.net` from the LAN. Confirm
   each camera streams (the pod pulls RTSP/ONVIF; the camera cannot
   connect inbound). Confirm new files show up under
   `/mnt/tank/share/scrypted` on `10.20.0.10`. Confirm the pod address
   on `net1` is `10.30.0.31/16`.
9. In the Scrypted MQTT plugin, replace `mqtt://127.0.0.1:1883` with a
   broker the pod can reach. The copied volume still has Forge's
   loopback address. Do not commit the password.

## Owner to-dos

- Set `replicas` from 0 to 1 only after `/var/lib/scrypted` is in
  `scrypted-data`.
- Forge's Intel iGPU is not mounted. Decode is CPU. Use
  `feature.node.kubernetes.io/intel-gpu` when a sled DRM node is known.
- VolSync is installed and unused. Recordings are the NAS copy. The
  config PVC is not in a ReplicationSource. Add one when a restic
  repository is chosen. Do not point it at the example in
  `kubernetes/examples/`.
- `10.30.0.31` has to stay outside `10.30.100.0/24`. `10.30.0.30` and
  `10.30.0.116` are already static on VLAN 30.
