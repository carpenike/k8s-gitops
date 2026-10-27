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
SSDs are Ceph disks and are not install targets. `sled-0`'s boot WWID was
not observed; the model and size selector covers it. Known WWIDs for the
other sleds are in `topf.yaml`.

## Disk encryption

STATE and EPHEMERAL use a LUKS2 `nodeID` key. There is no TPM. On 27 Oct
2026, Talos on sled-1 logged `No TPM chip found` and `TPM device is not
available`. The chassis is SYS-2028TP-HTR (X10DRT-P) and the optional
AOM-TPM module is not installed. Secure Boot stays off.

`nodeID` is kept in the unencrypted META partition. A reinstall that wipes
META cannot unlock the old volumes. Changing the key type later also means
reinstalling.

## NUT

`upsmon` is a secondary of `apc@forge.holthome.net` (10.20.0.30). The UPS
name `apc` is the stand-in until the nix-config plan names it. Forge's NUT
server is a nix-config change and is not done yet. v1 had no NUT item.
The placeholder is `PLACEHOLDER_ITEM_nut`. The proposed item is `nut`,
field `password`. Set `NUT_UPSMON_PASSWORD` from that field before
`topf apply`. The password is not in this repo.

## Apply

`scripts/bootstrap-cluster.sh` is the install sequence. It refuses to run
without `--yes`. Do not run it from CI. `topf secrets` writes
`talos/secrets.sops.yaml`, which is gitignored. Encrypt that bundle with
sops. The age recipient is already in `.sops.yaml`. Do not commit `age.key`.
