# Talos

`topf` renders machine config from `topf.yaml` plus the patches in `all/`
and `control-plane/`. Files ending in `.tpl` are Go templates; topf renders
those per node.

## First boot

Redfish virtual media is unlicensed on these sleds, so the first boot is a
USB stick or the iKVM virtual drive loaded with the metal ISO for schematic
`a3ea39fe448d8d4f3bdfbfc4e662b30fa37e91e609b160bd103377e8f11bbd5c`
(`talos/schematic.yaml`: `siderolabs/intel-ucode` and `siderolabs/nut-client`).

```text
factory.talos.dev/metal-iso/a3ea39fe448d8d4f3bdfbfc4e662b30fa37e91e609b160bd103377e8f11bbd5c:v1.14.5
```

The ISO installs onto the Samsung SSD 870 (500GB class). The three 960GB
SSDs are Ceph disks and are not install targets. The boot WWIDs for all four sleds are
in `topf.yaml`.

## Disk encryption

`encryptDisk` is `false` for all four sleds. The planned LUKS2 `nodeID` key
does not work on these boards. There is no TPM (`No TPM chip found` on
sled-1, 27 Oct 2026). Worse, the SMBIOS machine UUID is
`00000000-0000-0000-0000-<BMC-MAC-ish>` (for example
`00000000-0000-0000-0000-0cc47ac6b500`), and Talos refuses to derive a
`nodeID` key from it: `machine UUID ... entropy check failed`. STATE then
never formats and the node never leaves boot. Encrypting needs a different
key provider (KMS, or a static key kept out of git), which is a decision for
the owner. Switching later means reinstalling. `all/60-encryption.yaml.tpl`
stays in the tree and is skipped while `encryptDisk` is false.

## NUT

Each sled runs `upsd` in the `nut-upsd` DaemonSet and polls the APC card
at `10.9.18.245` with `snmp-ups`. `upsmon` on that same host is a
secondary of `apc@127.0.0.1`. The UPS name is `apc`. The password is the
SOPS secret `nut-credentials`, not an environment variable and not a
1Password item.

`topf apply` from `talos/` resolves `data.upsmonPassword` in `topf.yaml`.
That needs `sops` and `vals` on PATH, and either `age.key` or the YubiKey.
Until the DaemonSet is up, `upsmon` retries the connection. That gap is
accepted. ADR 0005. The every-node patch is `all/80-nut-client.yaml.tpl`.

## Talos API for tuppr

`control-plane/10-talos-api.yaml` grants `os:admin` to Kubernetes service
accounts in `system-upgrade`. tuppr's chart asks for that role. Apply that
document to each control plane (`sled-0`, `sled-1`, `sled-2`). Workers do
not serve the aggregated API.

## Apply

`scripts/bootstrap-cluster.sh` is the install sequence. It refuses to run
without `--yes`. Do not run it from CI. `topf secrets` writes
`talos/secrets.sops.yaml`, which is gitignored. Encrypt that bundle with
sops. The age recipient is already in `.sops.yaml`. Do not commit `age.key`.
